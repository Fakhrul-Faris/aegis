"""Pairs screening pipeline (P1.1, Concept §8/§9.2).

Testing the top-50 universe pairwise is C(50,2) = 1,225 hypothesis tests; at
p < 0.05 roughly 61 "cointegrated" pairs appear by chance alone, and crypto's
shared BTC factor makes in-sample p-values flattering. The pipeline therefore
stacks four independent hurdles:

1. Engle-Granger on the selection window, Benjamini-Hochberg FDR-corrected
   across the WHOLE scan.
2. Stability: the relationship must hold (raw alpha) on each of N
   non-overlapping sub-windows of the selection window.
3. Mean-reversion half-life (Ornstein-Uhlenbeck fit) inside tradeable
   bounds - too fast and fees dominate, too slow and the time stop can
   never be satisfied.
4. Out-of-sample: the most recent days are EXCLUDED from selection; the
   spread (with the selection-window beta) must remain stationary there.

Each pair is tested once, with the alphabetically-first symbol as the
dependent variable - testing both directions and keeping the better p-value
would quietly double the false-positive rate.
"""

from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint

from aegis.config import StrategyBConfig
from aegis.core.timeframes import timeframe_ms

logger = logging.getLogger(__name__)

_MIN_POINTS = 100  # below this, no statistical claim is worth making


@dataclass(frozen=True)
class PairCandidate:
    symbol_a: str  # dependent leg
    symbol_b: str
    pvalue: float  # EG p-value on the selection window
    beta: float  # selection-window OLS hedge ratio
    half_life_hours: float
    oos_adf_pvalue: float


@dataclass
class ScreeningReport:
    tested: int = 0
    passed_fdr: int = 0
    passed_stability: int = 0
    passed_half_life: int = 0
    candidates: list[PairCandidate] | None = None

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = []


def ols_beta(y: np.ndarray, x: np.ndarray) -> float:
    """Hedge ratio: cov(y, x) / var(x)."""
    x_centered = x - x.mean()
    return float(x_centered @ (y - y.mean()) / (x_centered @ x_centered))


def benjamini_hochberg(pvalues: np.ndarray, alpha: float) -> np.ndarray:
    """Boolean mask of discoveries under BH FDR control."""
    m = len(pvalues)
    if m == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(pvalues)
    ranked = pvalues[order]
    below = ranked <= (np.arange(1, m + 1) / m) * alpha
    mask = np.zeros(m, dtype=bool)
    if below.any():
        cutoff = int(np.max(np.nonzero(below)[0]))
        mask[order[: cutoff + 1]] = True
    return mask


def ou_half_life_bars(spread: np.ndarray) -> float:
    """Mean-reversion half-life in bars from an AR(1)/OU fit.

    Regress d(spread) on lagged spread: a slope b < 0 means reversion with
    half-life ln(0.5)/ln(1+b). Returns +inf when there is no reversion.
    """
    s = np.asarray(spread, dtype=float)
    if len(s) < 3:
        return math.inf
    lagged = s[:-1]
    delta = np.diff(s)
    lagged_centered = lagged - lagged.mean()
    denom = lagged_centered @ lagged_centered
    if denom == 0:
        return math.inf
    b = float(lagged_centered @ (delta - delta.mean()) / denom)
    if b >= 0 or b <= -1:
        return math.inf if b >= 0 else 1.0
    return float(np.log(0.5) / np.log(1.0 + b))


def screen_pairs(prices: pd.DataFrame, cfg: StrategyBConfig) -> ScreeningReport:
    """Run the full pipeline on a panel of close prices.

    ``prices``: rows = consecutive bars of ``cfg.bar_timeframe``, columns =
    symbols. Must cover ``selection_window_days + oos_check_days``; pairs
    whose data is shorter are skipped, not guessed at.
    """
    report = ScreeningReport()
    bar_hours = timeframe_ms(cfg.bar_timeframe) / 3_600_000
    bars_per_day = round(24 / bar_hours)
    oos_bars = cfg.oos_check_days * bars_per_day
    selection_bars = cfg.selection_window_days * bars_per_day

    pairs: list[tuple[str, str, np.ndarray, np.ndarray]] = []
    pvalues: list[float] = []

    for sym_a, sym_b in itertools.combinations(sorted(prices.columns), 2):
        joined = prices[[sym_a, sym_b]].dropna()
        if len(joined) < oos_bars + max(selection_bars // 2, _MIN_POINTS):
            continue
        selection = joined.iloc[:-oos_bars].tail(selection_bars)
        oos = joined.iloc[-oos_bars:]
        if len(selection) < _MIN_POINTS or len(oos) < _MIN_POINTS // 2:
            continue
        a = selection[sym_a].to_numpy(dtype=float)
        b = selection[sym_b].to_numpy(dtype=float)
        try:
            pvalue = float(coint(a, b)[1])
        except (ValueError, np.linalg.LinAlgError):
            continue
        pairs.append((sym_a, sym_b, joined[sym_a].to_numpy(), joined[sym_b].to_numpy()))
        pvalues.append(pvalue)

    report.tested = len(pairs)
    if not pairs:
        return report

    fdr_mask = benjamini_hochberg(np.array(pvalues), cfg.fdr_alpha)
    report.passed_fdr = int(fdr_mask.sum())

    for keep, (sym_a, sym_b, full_a, full_b), pvalue in zip(fdr_mask, pairs, pvalues, strict=True):
        if not keep:
            continue
        sel_a = full_a[:-oos_bars][-selection_bars:]
        sel_b = full_b[:-oos_bars][-selection_bars:]

        # 2. Stability across non-overlapping sub-windows (raw alpha).
        chunks = np.array_split(np.arange(len(sel_a)), cfg.stability_subwindows)
        stable = True
        for chunk in chunks:
            if len(chunk) < _MIN_POINTS:
                stable = False
                break
            try:
                if float(coint(sel_a[chunk], sel_b[chunk])[1]) > cfg.fdr_alpha:
                    stable = False
                    break
            except (ValueError, np.linalg.LinAlgError):
                stable = False
                break
        if not stable:
            continue
        report.passed_stability += 1

        # 3. Half-life inside tradeable bounds.
        beta = ols_beta(sel_a, sel_b)
        spread_sel = sel_a - beta * sel_b
        half_life_hours = ou_half_life_bars(spread_sel) * bar_hours
        if not (cfg.half_life_min_hours <= half_life_hours <= cfg.half_life_max_hours):
            continue
        report.passed_half_life += 1

        # 4. Out-of-sample stationarity with the SELECTION beta (no peeking).
        spread_oos = full_a[-oos_bars:] - beta * full_b[-oos_bars:]
        try:
            oos_pvalue = float(adfuller(spread_oos)[1])
        except (ValueError, np.linalg.LinAlgError):
            continue
        if oos_pvalue > cfg.fdr_alpha:
            continue

        report.candidates.append(
            PairCandidate(
                symbol_a=sym_a,
                symbol_b=sym_b,
                pvalue=pvalue,
                beta=beta,
                half_life_hours=half_life_hours,
                oos_adf_pvalue=oos_pvalue,
            )
        )

    logger.info(
        "pair screening complete",
        extra={
            "tested": report.tested,
            "passed_fdr": report.passed_fdr,
            "passed_stability": report.passed_stability,
            "passed_half_life": report.passed_half_life,
            "candidates": len(report.candidates),
        },
    )
    return report
