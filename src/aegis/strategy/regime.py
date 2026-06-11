"""Per-asset regime detection (P2.2, Concept §6).

Computed on 4h closes. Global BTC override (may only REDUCE risk) lands in
the portfolio brain once wired to live data. Regime flips never widen stops.
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np

from aegis.config import RegimeConfig
from aegis.strategy.swing import ema


class Regime(StrEnum):
    TRENDING_UP = "trending_up"
    SIDEWAYS = "sideways"
    TRENDING_DOWN = "trending_down"


def _true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    tr = np.zeros(len(close))
    tr[0] = high[0] - low[0]
    for i in range(1, len(close)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    return tr


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average Directional Index; NaN until ``2*period`` bars."""
    n = len(close)
    out = np.full(n, np.nan)
    if n < 2 * period:
        return out

    tr = _true_range(high, low, close)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0

    def wilder(x: np.ndarray) -> np.ndarray:
        s = np.full(n, np.nan)
        s[period] = x[1 : period + 1].mean()
        for i in range(period + 1, n):
            s[i] = (s[i - 1] * (period - 1) + x[i]) / period
        return s

    atr = wilder(tr)
    pdi = 100 * wilder(plus_dm) / atr
    mdi = 100 * wilder(minus_dm) / atr
    dx = 100 * np.abs(pdi - mdi) / (pdi + mdi + 1e-12)

    out[2 * period] = dx[period + 1 : 2 * period + 1].mean()
    for i in range(2 * period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
    return out


def bollinger_width(close: np.ndarray, period: int = 20, num_std: float = 2.0) -> np.ndarray:
    """Band width / middle band — tight bands suggest sideways chop."""
    out = np.full(len(close), np.nan)
    for i in range(period - 1, len(close)):
        window = close[i - period + 1 : i + 1]
        mid = window.mean()
        std = window.std(ddof=1)
        if mid == 0:
            continue
        out[i] = (2 * num_std * std) / mid
    return out


def sma(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    for i in range(period - 1, len(values)):
        out[i] = values[i - period + 1 : i + 1].mean()
    return out


def detect_regime(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    cfg: RegimeConfig,
    *,
    ema_fast: np.ndarray | None = None,
    ema_slow: np.ndarray | None = None,
) -> Regime:
    """Classify the latest bar's regime."""
    bar = len(close) - 1
    if bar < 200:
        return Regime.SIDEWAYS

    if ema_fast is None:
        ema_fast = ema(close, 9)
    if ema_slow is None:
        ema_slow = ema(close, 21)
    adx_val = adx(high, low, close)[bar]
    ma200 = sma(close, 200)[bar]
    bb_w = bollinger_width(close)[bar]

    if np.isnan(adx_val) or np.isnan(ma200):
        return Regime.SIDEWAYS

    trending = adx_val > cfg.adx_trend_threshold
    sideways = adx_val < cfg.adx_sideways_threshold and (np.isnan(bb_w) or bb_w < 0.04)

    if trending and ema_fast[bar] > ema_slow[bar] and close[bar] > ma200:
        return Regime.TRENDING_UP
    if trending and ema_fast[bar] < ema_slow[bar] and close[bar] < ma200:
        return Regime.TRENDING_DOWN
    if sideways:
        return Regime.SIDEWAYS
    return Regime.SIDEWAYS


def strategy_a_active(regime: Regime) -> bool:
    """Strategy A is long-only — inactive in sideways and downtrends."""
    return regime is Regime.TRENDING_UP


def strategy_b_size_factor(regime: Regime, cfg: RegimeConfig) -> float:
    """Strategy B full size sideways; half size in trends (Concept §6)."""
    if regime is Regime.SIDEWAYS:
        return 1.0
    return cfg.trend_size_factor
