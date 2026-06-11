"""Walk-forward pairs backtest engine (P1.6).

Structure per Concept §17:
- Pair selection re-runs every ``refit_interval_bars`` on data strictly
  BEFORE the current bar (the screener's own OOS holdout sits inside that
  window) - selection never sees the bars it will trade.
- Between refits, a Kalman filter tracks each active pair's hedge ratio
  bar by bar. New entries take the current beta; open positions keep their
  entry beta until close (the entry-freeze rule).
- Exits, stops, sizing, and costs are the SAME functions live trading uses.

Fill model (deliberately conservative):
- Entries/exits execute at the bar's close, with the slippage allowance
  charged on the taker legs via the cost model.
- One position per pair, scale-out closes half.

Sizing: risk derives from the z-distance to the hard stop in spread dollars;
positions whose derived leg notional sits below the venue minimum are
SKIPPED and logged, exactly like live (Concept §9.4).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from aegis.config import ExchangeFees, RiskConfig, StrategyBConfig
from aegis.core.timeframes import timeframe_ms
from aegis.risk.costs import edge_clears_costs, spread_round_trip_costs
from aegis.risk.sizing import concurrent_risk_allows, size_position
from aegis.strategy.kalman import KalmanBeta
from aegis.strategy.screening import PairCandidate, screen_pairs
from aegis.strategy.zscore import (
    Direction,
    ExitAction,
    PairPosition,
    compute_spread,
    empirical_entry_threshold,
    evaluate_entry,
    evaluate_exit,
    zscore,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestParams:
    initial_equity: float = 1000.0
    tier_risk_pct: float = 0.0075  # Mid tier for the whole walk-forward
    min_notional_usd: float = 10.0
    slippage_allowance_pct: float = 0.0008
    refit_interval_bars: int = 168  # weekly on 1h bars
    max_pairs: int = 10  # trade only the strongest survivors


@dataclass(frozen=True)
class Trade:
    symbol_a: str
    symbol_b: str
    direction: str
    entry_bar: int
    exit_bar: int
    exit_reason: str
    entry_z: float
    risk_amount: float
    leg_notional: float
    pnl_gross: float
    costs: float

    @property
    def pnl_net(self) -> float:
        return self.pnl_gross - self.costs

    @property
    def r_multiple(self) -> float:
        return self.pnl_net / self.risk_amount if self.risk_amount else 0.0


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    skipped_below_min_notional: int = 0
    skipped_risk_budget: int = 0
    skipped_edge_gate: int = 0
    refits: int = 0

    @property
    def r_multiples(self) -> np.ndarray:
        return np.array([t.r_multiple for t in self.trades])

    @property
    def expectancy_r(self) -> float:
        return float(self.r_multiples.mean()) if self.trades else 0.0

    def expectancy_ci90(self) -> tuple[float, float]:
        """Mean R +- 1.645 SE. A point estimate alone is banned (tracker rule)."""
        rs = self.r_multiples
        if len(rs) < 2:
            return (math.nan, math.nan)
        half = 1.645 * rs.std(ddof=1) / math.sqrt(len(rs))
        return (float(rs.mean() - half), float(rs.mean() + half))

    @property
    def max_drawdown_pct(self) -> float:
        curve = np.asarray(self.equity_curve)
        if len(curve) == 0:
            return 0.0
        peaks = np.maximum.accumulate(curve)
        return float(np.max(1.0 - curve / peaks))

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pnl_net > 0) / len(self.trades)

    def per_pair_pnl(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for t in self.trades:
            key = f"{t.symbol_a}/{t.symbol_b}"
            out[key] = out.get(key, 0.0) + t.pnl_net
        return out


@dataclass
class _OpenPosition:
    position: PairPosition
    units: float  # spread units held (per-unit P&L = spread change in $)
    entry_spread: float
    risk_amount: float
    risk_r: float
    leg_notional: float
    z_window: int
    realized: float = 0.0  # banked by scale-outs


class _ActivePair:
    """Per-pair state between refits: Kalman beta + trailing z history."""

    def __init__(self, candidate: PairCandidate, bar_hours: float):
        self.candidate = candidate
        self.kalman = KalmanBeta(initial_beta=candidate.beta)
        self.half_life_bars = max(candidate.half_life_hours / bar_hours, 2.0)
        self.z_window = 0  # set from config at activation
        self.z_history: list[float] = []
        # Removal logic: a pair that fails its weekly re-test while a position
        # is open stays MANAGED (exits keep firing) but takes no new entries.
        self.tradeable = True


def run_backtest(
    prices: pd.DataFrame,
    cfg_b: StrategyBConfig,
    risk_cfg: RiskConfig,
    fees: ExchangeFees,
    params: BacktestParams | None = None,
) -> BacktestResult:
    """Walk-forward backtest over a panel of close prices (1 bar per row)."""
    params = params or BacktestParams()
    result = BacktestResult()
    bar_hours = timeframe_ms(cfg_b.bar_timeframe) / 3_600_000
    bars_per_day = round(24 / bar_hours)
    warmup = (cfg_b.selection_window_days + cfg_b.oos_check_days) * bars_per_day

    equity = params.initial_equity
    open_positions: dict[tuple[str, str], _OpenPosition] = {}
    active: dict[tuple[str, str], _ActivePair] = {}
    open_risk_r = 0.0

    costs = spread_round_trip_costs(fees, params.slippage_allowance_pct)
    values = {sym: prices[sym].to_numpy(dtype=float) for sym in prices.columns}
    n_bars = len(prices)

    for bar in range(warmup, n_bars):
        # ---- Refit: re-screen on history strictly before this bar ----------
        if (bar - warmup) % params.refit_interval_bars == 0:
            report = screen_pairs(prices.iloc[:bar], cfg_b)
            result.refits += 1
            survivors = sorted(report.candidates, key=lambda c: c.pvalue)[: params.max_pairs]
            refreshed: dict[tuple[str, str], _ActivePair] = {}
            for candidate in survivors:
                key = (candidate.symbol_a, candidate.symbol_b)
                refreshed[key] = active.get(key) or _ActivePair(candidate, bar_hours)
                refreshed[key].tradeable = True
            for key in open_positions:
                if key not in refreshed and key in active:
                    refreshed[key] = active[key]
                    refreshed[key].tradeable = False  # manage to close, no re-entry
            active = refreshed
            for pair in active.values():
                pair.z_window = max(
                    int(cfg_b.z_window_half_life_multiple * pair.half_life_bars), 10
                )

        # ---- Per-bar pair updates ------------------------------------------
        for key, pair in active.items():
            a = values[key[0]]
            b = values[key[1]]
            # Late listings / delistings show up as NaN; freeze the pair for
            # that bar rather than poisoning the Kalman state.
            if not (np.isfinite(a[bar]) and np.isfinite(b[bar])):
                continue
            beta = pair.kalman.update(a[bar], b[bar])

            held = open_positions.get(key)
            if held is not None:
                # Exits use the FROZEN entry beta - never the live one.
                spread = compute_spread(
                    a[bar - held.z_window + 1 : bar + 1],
                    b[bar - held.z_window + 1 : bar + 1],
                    held.position.beta,
                )
                z = zscore(spread, held.z_window)
                action = evaluate_exit(
                    held.position,
                    z,
                    bar,
                    cfg_b.z_scale_out,
                    cfg_b.z_hard_stop,
                    cfg_b.time_stop_half_life_multiple,
                )
                equity, open_risk_r = _apply_exit(
                    result,
                    open_positions,
                    key,
                    held,
                    action,
                    spread[-1],
                    bar,
                    equity,
                    open_risk_r,
                    costs.total_pct,
                )
                continue

            # No open position: track z history and consider entry.
            window = pair.z_window
            if bar + 1 < window + 1:
                continue
            spread = compute_spread(
                a[bar - window + 1 : bar + 1], b[bar - window + 1 : bar + 1], beta
            )
            z = zscore(spread, window)
            pair.z_history.append(z)
            if len(pair.z_history) < window:
                continue

            if not pair.tradeable:
                continue
            threshold = empirical_entry_threshold(
                np.array(pair.z_history), cfg_b.z_entry_percentile
            )
            direction = evaluate_entry(z, threshold)
            if direction is None:
                continue

            spread_std = spread.std(ddof=1)
            stop_z_distance = max(cfg_b.z_hard_stop - abs(z), 0.1)
            price_a = a[bar]

            # Edge gate: expected |z|->0 convergence vs round-trip cost.
            expected_move_pct = abs(z) * spread_std / price_a
            if not edge_clears_costs(expected_move_pct, costs, cfg_b.min_edge_to_cost_ratio):
                result.skipped_edge_gate += 1
                continue

            stop_distance_pct = stop_z_distance * spread_std / price_a
            decision = size_position(
                equity=equity,
                tier_risk_pct=params.tier_risk_pct,
                stop_distance_pct=stop_distance_pct,
                min_notional=params.min_notional_usd,
            )
            if not decision.approved:
                result.skipped_below_min_notional += 1
                continue
            if not concurrent_risk_allows(
                open_risk_r, decision.risk_r, risk_cfg.max_concurrent_risk_r
            ):
                result.skipped_risk_budget += 1
                continue

            units = decision.notional / price_a
            open_positions[key] = _OpenPosition(
                position=PairPosition(
                    symbol_a=key[0],
                    symbol_b=key[1],
                    direction=direction,
                    beta=beta,
                    entry_z=z,
                    entry_bar=bar,
                    half_life_bars=pair.half_life_bars,
                    z_entry_threshold=threshold,
                ),
                units=units,
                entry_spread=spread[-1],
                risk_amount=decision.risk_amount,
                risk_r=decision.risk_r,
                leg_notional=decision.notional,
                z_window=window,
            )
            open_risk_r += decision.risk_r

        result.equity_curve.append(equity)

    return result


def _apply_exit(
    result: BacktestResult,
    open_positions: dict,
    key: tuple[str, str],
    held: _OpenPosition,
    action: ExitAction,
    spread_now: float,
    bar: int,
    equity: float,
    open_risk_r: float,
    total_cost_pct: float,
) -> tuple[float, float]:
    """Mutates position/result state for an exit action; returns new equity/risk."""
    if action is ExitAction.HOLD:
        return equity, open_risk_r

    sign = 1.0 if held.position.direction is Direction.LONG_SPREAD else -1.0
    move = sign * (spread_now - held.entry_spread)

    if action is ExitAction.SCALE_OUT:
        held.realized += move * held.units * 0.5
        held.units *= 0.5
        held.position = held.position.with_scale_out()
        return equity, open_risk_r

    pnl_gross = held.realized + move * held.units
    trade = Trade(
        symbol_a=key[0],
        symbol_b=key[1],
        direction=held.position.direction.value,
        entry_bar=held.position.entry_bar,
        exit_bar=bar,
        exit_reason=action.value,
        entry_z=held.position.entry_z,
        risk_amount=held.risk_amount,
        leg_notional=held.leg_notional,
        pnl_gross=pnl_gross,
        costs=held.leg_notional * total_cost_pct,
    )
    result.trades.append(trade)
    del open_positions[key]
    return equity + trade.pnl_net, open_risk_r - held.risk_r
