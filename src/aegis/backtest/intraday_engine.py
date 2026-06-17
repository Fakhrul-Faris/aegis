"""Strategy C walk-forward backtest (ID1).

Uses 15m signal bars + 4h regime. Scanner proxy: volume spike on 15m bars.
Costs: HL maker entry + taker exit (round trip).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from aegis.config import RegimeConfig
from aegis.config_intraday import IntradayCostsConfig, IntradayResearchConfig, MomentumDayConfig
from aegis.risk.sizing import size_position
from aegis.strategy.intraday_momentum import (
    IntradayExit,
    evaluate_entry_at_bar,
    evaluate_exit,
    regime_trending_up,
    volume_spike_proxy,
)


@dataclass(frozen=True)
class IntradayTrade:
    symbol: str
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    exit_reason: str
    risk_amount: float
    notional: float
    costs: float

    @property
    def pnl_net(self) -> float:
        gross = (self.exit_price - self.entry_price) / self.entry_price * self.notional
        return gross - self.costs

    @property
    def r_multiple(self) -> float:
        return self.pnl_net / self.risk_amount if self.risk_amount else 0.0


@dataclass
class IntradayBacktestResult:
    trades: list[IntradayTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    skipped_below_min: int = 0
    skipped_daily_cap: int = 0

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
        return sum(1 for t in self.trades if t.pnl_net > 0) / len(self.trades)


def _round_trip_cost(notional: float, costs: IntradayCostsConfig) -> float:
    return notional * (costs.maker_fee + costs.taker_fee + 2 * costs.slippage_pct)


def _resample_regime_frame(
    signal_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    regime_cfg: RegimeConfig,
) -> np.ndarray:
    """Map each 15m bar to trending-up bool from aligned 4h regime bars."""
    trending = np.zeros(len(signal_df), dtype=bool)
    if regime_df.empty:
        return trending

    regime_idx = regime_df.index
    for i, ts in enumerate(signal_df.index):
        prior = regime_idx[regime_idx <= ts]
        if len(prior) == 0:
            continue
        highs = regime_df.loc[: prior[-1], "high"].to_numpy(dtype=float)
        lows = regime_df.loc[: prior[-1], "low"].to_numpy(dtype=float)
        closes = regime_df.loc[: prior[-1], "close"].to_numpy(dtype=float)
        if len(closes) < 210:
            continue
        trending[i] = regime_trending_up(highs, lows, closes, regime_cfg)
    return trending


def run_intraday_backtest(
    symbol: str,
    signal_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    md_cfg: MomentumDayConfig,
    costs: IntradayCostsConfig,
    research: IntradayResearchConfig,
    regime_cfg: RegimeConfig,
    *,
    starting_equity: float = 400.0,
) -> IntradayBacktestResult:
    result = IntradayBacktestResult()
    if len(signal_df) < 50:
        return result

    highs = signal_df["high"].to_numpy(dtype=float)
    lows = signal_df["low"].to_numpy(dtype=float)
    closes = signal_df["close"].to_numpy(dtype=float)
    volumes = signal_df["volume"].to_numpy(dtype=float)
    open_ms = (signal_df.index.astype("int64") // 1_000_000).to_numpy()

    trending = _resample_regime_frame(signal_df, regime_df, regime_cfg)
    equity = starting_equity
    result.equity_curve.append(equity)

    in_position = False
    entry_bar = -1
    entry_price = 0.0
    risk_amount = 0.0
    notional = 0.0
    daily_r = 0.0
    daily_trades = 0
    last_day = -1

    for bar in range(md_cfg.breakout_lookback_bars + 1, len(closes)):
        day = int(open_ms[bar] // 86_400_000)
        if day != last_day:
            daily_r = 0.0
            daily_trades = 0
            last_day = day

        if not in_position:
            if daily_trades >= md_cfg.max_trades_per_day:
                continue
            if daily_r >= md_cfg.daily_profit_cap_r:
                result.skipped_daily_cap += 1
                continue
            if daily_r <= -md_cfg.daily_loss_cap_r:
                result.skipped_daily_cap += 1
                continue

            anomaly = volume_spike_proxy(
                volumes,
                bar,
                multiple=research.volume_spike_multiple,
            )
            entry = evaluate_entry_at_bar(
                bar,
                highs,
                lows,
                closes,
                int(open_ms[bar]),
                md_cfg,
                anomaly=anomaly,
                trending_up=bool(trending[bar]),
            )
            if entry is None:
                continue

            sizing = size_position(
                equity,
                md_cfg.risk_pct,
                stop_distance_pct=md_cfg.stop_loss_pct,
                min_notional=costs.min_order_usd,
            )
            if not sizing.approved:
                result.skipped_below_min += 1
                continue

            in_position = True
            entry_bar = bar
            entry_price = entry.price
            risk_amount = sizing.risk_amount
            notional = sizing.notional
            daily_trades += 1
            continue

        current = closes[bar]
        reason = evaluate_exit(entry_price, current, int(open_ms[bar]), md_cfg)
        if reason is IntradayExit.HOLD:
            continue

        exit_price = current
        trade_costs = _round_trip_cost(notional, costs)
        trade = IntradayTrade(
            symbol=symbol,
            entry_bar=entry_bar,
            exit_bar=bar,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=reason.value,
            risk_amount=risk_amount,
            notional=notional,
            costs=trade_costs,
        )
        result.trades.append(trade)
        equity += trade.pnl_net
        daily_r += trade.r_multiple
        result.equity_curve.append(equity)
        in_position = False

    return result


def merge_backtest_results(results: list[IntradayBacktestResult]) -> IntradayBacktestResult:
    merged = IntradayBacktestResult()
    for r in results:
        merged.trades.extend(r.trades)
        merged.skipped_below_min += r.skipped_below_min
        merged.skipped_daily_cap += r.skipped_daily_cap
        merged.equity_curve.extend(r.equity_curve)
    return merged
