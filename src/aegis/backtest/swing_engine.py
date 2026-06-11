"""Strategy A walk-forward backtest (P1 extension).

Single-asset long-only swing on 4h closes. Scanner anomaly flags are NOT
available historically — this backtest measures the EMA+RSI baseline the
Concept expects to be roughly break-even after Kraken costs. Live paper
trading joins real scanner flags via ``evaluate_entry(..., anomaly_flags=)``.

Costs: one round trip = maker entry + taker exit (conservative for spot).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from aegis.config import ExchangeFees, RiskConfig, StrategyAConfig
from aegis.risk.sizing import concurrent_risk_allows, size_position
from aegis.strategy.swing import SwingExit, evaluate_entry, evaluate_exit


@dataclass(frozen=True)
class SwingTrade:
    symbol: str
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    exit_reason: str
    tier: str
    risk_amount: float
    notional: float
    costs: float

    @property
    def pnl_gross(self) -> float:
        return (self.exit_price - self.entry_price) / self.entry_price * self.notional

    @property
    def pnl_net(self) -> float:
        return self.pnl_gross - self.costs

    @property
    def r_multiple(self) -> float:
        return self.pnl_net / self.risk_amount if self.risk_amount else 0.0


@dataclass
class SwingBacktestResult:
    trades: list[SwingTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    skipped_below_min_notional: int = 0
    skipped_risk_budget: int = 0

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


def _round_trip_cost_pct(fees: ExchangeFees, slippage_pct: float) -> float:
    return fees.maker_fee + fees.taker_fee + slippage_pct


def run_swing_backtest(
    prices: pd.DataFrame,
    cfg_a: StrategyAConfig,
    risk_cfg: RiskConfig,
    fees: ExchangeFees,
    *,
    initial_equity: float = 1000.0,
    tier_risk_pct: float = 0.0075,
    min_notional_usd: float = 10.0,
    slippage_pct: float = 0.0008,
    one_position_per_symbol: bool = True,
) -> SwingBacktestResult:
    """Backtest Strategy A across a panel of 4h close prices."""
    result = SwingBacktestResult()
    equity = initial_equity
    open_risk_r = 0.0
    cost_pct = _round_trip_cost_pct(fees, slippage_pct)
    warmup = max(cfg_a.ema_slow, cfg_a.rsi_period) + 2

    open_pos: dict[str, tuple[int, float, float, float, str]] = {}
    # symbol -> (entry_bar, entry_price, risk_amount, risk_r, tier)

    for bar in range(warmup, len(prices)):
        for symbol in prices.columns:
            closes = prices[symbol].to_numpy(dtype=float)
            if np.isnan(closes[bar]):
                continue

            if symbol in open_pos:
                entry_bar, entry_price, risk_amt, risk_r, tier = open_pos[symbol]
                action = evaluate_exit(entry_price, float(closes[bar]), bar, closes, cfg_a)
                if action is SwingExit.HOLD:
                    continue
                exit_price = float(closes[bar])
                notional = risk_amt / cfg_a.stop_loss_pct
                trade = SwingTrade(
                    symbol=symbol,
                    entry_bar=entry_bar,
                    exit_bar=bar,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    exit_reason=action.value,
                    tier=tier,
                    risk_amount=risk_amt,
                    notional=notional,
                    costs=notional * cost_pct,
                )
                result.trades.append(trade)
                equity += trade.pnl_net
                open_risk_r -= risk_r
                del open_pos[symbol]
                continue

            if one_position_per_symbol and symbol in open_pos:
                continue

            entry = evaluate_entry(bar, closes, cfg_a)
            if entry is None:
                continue

            decision = size_position(
                equity=equity,
                tier_risk_pct=tier_risk_pct,
                stop_distance_pct=cfg_a.stop_loss_pct,
                min_notional=min_notional_usd,
            )
            if not decision.approved:
                result.skipped_below_min_notional += 1
                continue
            if not concurrent_risk_allows(
                open_risk_r, decision.risk_r, risk_cfg.max_concurrent_risk_r
            ):
                result.skipped_risk_budget += 1
                continue

            open_pos[symbol] = (
                bar,
                entry.price,
                decision.risk_amount,
                decision.risk_r,
                entry.tier.value,
            )
            open_risk_r += decision.risk_r

        result.equity_curve.append(equity)

    return result
