"""Circuit breakers and kill switch (P2.1, Concept Guardrails C & D).

Guardrail C: daily loss > 3x max single-trade risk → halt until manual resume.
Guardrail D: account drawdown > MC-calibrated threshold → permanent stop until
written review. A kill switch inside normal variance executes the system for
being unlucky, not for failing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class BreakerState:
    """Mutable runtime state persisted across cycles (in-memory until P3)."""

    halted_daily: bool = False
    killed: bool = False
    manual_resume_required: bool = False
    peak_equity: float = 0.0
    session_start_equity: float = 0.0
    session_date: str = field(default_factory=lambda: datetime.now(tz=UTC).strftime("%Y-%m-%d"))
    daily_pnl: float = 0.0

    def reset_session_if_new_day(self, equity: float, today: str | None = None) -> None:
        today = today or datetime.now(tz=UTC).strftime("%Y-%m-%d")
        if today != self.session_date:
            self.session_date = today
            self.session_start_equity = equity
            self.daily_pnl = 0.0
            if not self.killed:
                self.halted_daily = False
                self.manual_resume_required = False

    def update_peak(self, equity: float) -> None:
        self.peak_equity = max(self.peak_equity, equity)


def daily_loss_trips_breaker(
    daily_pnl: float,
    max_single_trade_risk_usd: float,
    breaker_multiple: float,
) -> bool:
    """True when today's loss exceeds N x the largest allowed single-trade risk."""
    if daily_pnl >= 0:
        return False
    return abs(daily_pnl) >= breaker_multiple * max_single_trade_risk_usd


def kill_switch_trips(
    equity: float, peak_equity: float, kill_switch_drawdown_pct: float | None
) -> bool:
    if kill_switch_drawdown_pct is None or peak_equity <= 0:
        return False
    drawdown = 1.0 - equity / peak_equity
    return drawdown >= kill_switch_drawdown_pct


def trip_daily_halt(state: BreakerState) -> None:
    state.halted_daily = True
    state.manual_resume_required = True


def trip_kill_switch(state: BreakerState) -> None:
    state.killed = True
    state.halted_daily = True
    state.manual_resume_required = True


def resume_after_manual_review(state: BreakerState) -> None:
    """Operator acknowledges review — clears daily halt only, never kill."""
    if state.killed:
        raise RuntimeError("Kill switch active — requires full system restart after written review")
    state.halted_daily = False
    state.manual_resume_required = False
