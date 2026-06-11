"""Risk engine orchestrator (P2.1).

Single pre-trade gate: correlation bucket → concurrent 3R cap → slippage →
breaker state. Strategies call ``approve_trade()``; they never implement
guardrails themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from aegis.config import RiskConfig
from aegis.core.models import Side
from aegis.risk.breakers import (
    BreakerState,
    daily_loss_trips_breaker,
    kill_switch_trips,
    trip_daily_halt,
    trip_kill_switch,
)
from aegis.risk.correlation import (
    assign_correlation_buckets,
    correlation_allows_new_risk,
)
from aegis.risk.sizing import concurrent_risk_allows
from aegis.risk.slippage import limit_slippage_pct, passes_slippage_gate


@dataclass(frozen=True)
class TradeApproval:
    approved: bool
    reason: str


class RiskEngine:
    def __init__(self, cfg: RiskConfig, state: BreakerState | None = None):
        self.cfg = cfg
        self.state = state or BreakerState()

    def update_equity(self, equity: float) -> list[str]:
        """Call each cycle. Returns critical alert messages."""
        self.state.reset_session_if_new_day(equity)
        self.state.update_peak(equity)
        self.state.daily_pnl = equity - self.state.session_start_equity
        alerts: list[str] = []

        max_risk_usd = equity * self.cfg.tiers.aggressive
        if daily_loss_trips_breaker(
            self.state.daily_pnl, max_risk_usd, self.cfg.daily_breaker_multiple
        ):
            trip_daily_halt(self.state)
            alerts.append("CRITICAL: daily circuit breaker tripped")

        if kill_switch_trips(equity, self.state.peak_equity, self.cfg.kill_switch_drawdown_pct):
            trip_kill_switch(self.state)
            alerts.append("CRITICAL: account kill switch tripped")

        return alerts

    def approve_trade(
        self,
        *,
        equity: float,
        symbol: str,
        new_risk_r: float,
        open_risk_r: float,
        open_risk_by_symbol: dict[str, float],
        returns_by_symbol: dict[str, np.ndarray],
        side: Side,
        limit_price: float,
        best_bid: float,
        best_ask: float,
        previous_buckets: dict[str, str] | None = None,
    ) -> TradeApproval:
        if self.state.killed:
            return TradeApproval(False, "kill_switch_active")
        if self.state.halted_daily:
            return TradeApproval(False, "daily_halt_active")

        slip = limit_slippage_pct(side, limit_price, best_bid, best_ask)
        if not passes_slippage_gate(slip, self.cfg.slippage_gate_pct):
            return TradeApproval(False, f"slippage_gate:{slip:.4%}")

        if not concurrent_risk_allows(open_risk_r, new_risk_r, self.cfg.max_concurrent_risk_r):
            return TradeApproval(False, "max_concurrent_risk")

        symbols = list(set(open_risk_by_symbol) | {symbol})
        ret_map = {s: np.asarray(returns_by_symbol.get(s, []), dtype=float) for s in symbols}
        buckets = assign_correlation_buckets(
            symbols,
            ret_map,
            trigger=self.cfg.correlation_trigger,
            release=self.cfg.correlation_release,
            min_observations=self.cfg.correlation_min_observations,
            previous_buckets=previous_buckets,
        )
        if not correlation_allows_new_risk(
            buckets, open_risk_by_symbol, symbol, new_risk_r, max_bucket_r=1.0
        ):
            return TradeApproval(False, "correlation_bucket_full")

        return TradeApproval(True, "ok")
