"""Forex SCM walk-forward backtest engine (FX1 + FX2).

Asian range → London breakout with optional confirmation layer (ADR,
DXY, calendar). Costs from Fusion RAW model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from aegis.config_forex import ForexConfig
from aegis.risk.forex_costs import ForexCostsConfig, forex_round_trip_costs
from aegis.strategy.forex_confirms import (
    ConfirmContext,
    build_confirm_context,
    filter_signals_with_confirms,
    load_calendar_event_times,
)
from aegis.strategy.forex_session import (
    BreakoutSignal,
    compute_asian_ranges,
    detect_scm_signals,
)


@dataclass(frozen=True)
class ScmTrade:
    symbol: str
    direction: str
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    exit_reason: str
    risk_amount_usd: float
    notional_usd: float
    costs_usd: float

    @property
    def pnl_gross_usd(self) -> float:
        sign = 1.0 if self.direction == "long" else -1.0
        return sign * (self.exit_price - self.entry_price) / self.entry_price * self.notional_usd

    @property
    def pnl_net_usd(self) -> float:
        return self.pnl_gross_usd - self.costs_usd

    @property
    def r_multiple(self) -> float:
        return self.pnl_net_usd / self.risk_amount_usd if self.risk_amount_usd else 0.0


@dataclass
class ScmBacktestResult:
    trades: list[ScmTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    skipped_no_range: int = 0
    raw_signals: int = 0
    confirm_skips: dict[str, int] = field(default_factory=dict)
    use_confirms: bool = False

    @property
    def r_multiples(self) -> np.ndarray:
        return np.array([t.r_multiple for t in self.trades])

    @property
    def expectancy_r(self) -> float:
        return float(self.r_multiples.mean()) if self.trades else 0.0

    def expectancy_ci90(self) -> tuple[float, float]:
        rs = self.r_multiples
        if len(rs) < 2:
            return (math.nan, math.nan)
        half = 1.645 * rs.std(ddof=1) / math.sqrt(len(rs))
        return (float(rs.mean() - half), float(rs.mean() + half))

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pnl_net_usd > 0) / len(self.trades)

    @property
    def max_drawdown_pct(self) -> float:
        curve = np.asarray(self.equity_curve)
        if len(curve) == 0:
            return 0.0
        peaks = np.maximum.accumulate(curve)
        dd = 1.0 - curve / peaks
        return float(np.max(dd[np.isfinite(dd)])) if len(dd) else 0.0


def _simulate_trade(
    signal: BreakoutSignal,
    ohlc: pd.DataFrame,
    *,
    symbol: str,
    equity: float,
    risk_pct: float,
    costs_cfg: ForexCostsConfig,
    lots: float,
    near_high_impact_event: bool = False,
    time_stop_hours: int | None = None,
) -> ScmTrade | None:
    entry_ts = signal.entry_bar_ts
    post = ohlc.loc[ohlc.index > entry_ts]
    if post.empty:
        return None

    stop = signal.stop_price
    target = signal.target_price
    entry = signal.entry_price
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return None

    stop_pct = stop_dist / entry
    risk_amount = equity * risk_pct
    notional = risk_amount / stop_pct
    cost = forex_round_trip_costs(
        costs_cfg, symbol, lots=lots, near_high_impact_event=near_high_impact_event
    ).total_usd

    exit_price = entry
    exit_ts = entry_ts
    exit_reason = "time_end"
    time_deadline = (
        entry_ts + pd.Timedelta(hours=time_stop_hours) if time_stop_hours else None
    )

    for ts, row in post.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        if signal.direction == "long":
            if low <= stop:
                exit_price, exit_ts, exit_reason = stop, ts, "stop"
                break
            if high >= target:
                exit_price, exit_ts, exit_reason = target, ts, "target"
                break
        else:
            if high >= stop:
                exit_price, exit_ts, exit_reason = stop, ts, "stop"
                break
            if low <= target:
                exit_price, exit_ts, exit_reason = target, ts, "target"
                break
        if time_deadline is not None and ts >= time_deadline:
            exit_price, exit_ts, exit_reason = float(row["close"]), ts, "time_stop"
            break
        # Session end: flat at NY close (21:00 UTC same day or next bars same utc_date evening)
        if ts.hour >= 21:
            exit_price, exit_ts, exit_reason = float(row["close"]), ts, "session_end"
            break

    return ScmTrade(
        symbol=symbol,
        direction=signal.direction,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        entry_price=entry,
        exit_price=exit_price,
        stop_price=stop,
        target_price=target,
        exit_reason=exit_reason,
        risk_amount_usd=risk_amount,
        notional_usd=notional,
        costs_usd=cost,
    )


def run_scm_backtest(
    ohlc: pd.DataFrame,
    cfg: ForexConfig,
    *,
    symbol: str = "EURUSD",
    starting_equity: float = 100.0,
    risk_pct: float = 0.0075,
    lots: float = 0.01,
    use_confirms: bool = True,
    dxy_ohlc: pd.DataFrame | None = None,
    calendar_times_ms: list[int] | None = None,
    near_high_impact_event: bool = False,
) -> ScmBacktestResult:
    result = ScmBacktestResult(use_confirms=use_confirms)
    equity = starting_equity
    result.equity_curve.append(equity)

    ranges = compute_asian_ranges(ohlc, cfg.sessions)
    raw = detect_scm_signals(
        ohlc,
        cfg.scm,
        cfg.sessions,
        asian_ranges=ranges,
        event_times_ms=calendar_times_ms,
    )
    result.raw_signals = len(raw)

    signals = raw
    if use_confirms:
        dxy = dxy_ohlc if dxy_ohlc is not None else pd.DataFrame()
        ctx = build_confirm_context(ohlc, dxy, cfg, calendar_times_ms=calendar_times_ms)
        signals, skips = filter_signals_with_confirms(raw, ohlc, ranges, ctx, cfg)
        result.confirm_skips = skips

    for signal in signals:
        event_near = False  # confirmed signals already passed calendar gate
        trade = _simulate_trade(
            signal,
            ohlc,
            symbol=symbol,
            equity=equity,
            risk_pct=risk_pct,
            costs_cfg=cfg.costs,
            lots=lots,
            near_high_impact_event=event_near or near_high_impact_event,
        )
        if trade is None:
            result.skipped_no_range += 1
            continue
        result.trades.append(trade)
        equity += trade.pnl_net_usd
        result.equity_curve.append(equity)

    return result


def run_signals_backtest(
    ohlc: pd.DataFrame,
    cfg: ForexConfig,
    signals: list[BreakoutSignal],
    *,
    symbol: str = "EURUSD",
    starting_equity: float = 100.0,
    risk_pct: float = 0.0075,
    lots: float = 0.01,
    time_stop_hours: int | None = None,
) -> ScmBacktestResult:
    result = ScmBacktestResult(use_confirms=False)
    equity = starting_equity
    result.equity_curve.append(equity)
    result.raw_signals = len(signals)

    for signal in signals:
        trade = _simulate_trade(
            signal,
            ohlc,
            symbol=symbol,
            equity=equity,
            risk_pct=risk_pct,
            costs_cfg=cfg.costs,
            lots=lots,
            time_stop_hours=time_stop_hours,
        )
        if trade is None:
            result.skipped_no_range += 1
            continue
        result.trades.append(trade)
        equity += trade.pnl_net_usd
        result.equity_curve.append(equity)

    return result


def passes_fx1_window(result: ScmBacktestResult, cfg: ForexConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    n = len(result.trades)
    min_trades = cfg.scm.backtest_min_trades_per_window
    min_wr = cfg.scm.backtest_min_win_rate
    lo, hi = result.expectancy_ci90()

    if n < min_trades:
        reasons.append(f"trades {n} < {min_trades}")
    if result.win_rate < min_wr:
        reasons.append(f"win rate {result.win_rate:.1%} < {min_wr:.0%}")
    if n >= 2 and (math.isnan(lo) or lo <= 0):
        reasons.append(f"expectancy CI lower {lo:+.3f}R not > 0")
    if n < 2 and n > 0:
        reasons.append("too few trades for CI — need >= 2")
    return (len(reasons) == 0, reasons)
