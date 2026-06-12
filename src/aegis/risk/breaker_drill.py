"""P2.5 / M4 live breaker drill — exercises halt + kill paths outside unit tests.

Runs the real ``RiskEngine`` update/approve cycle (no testnet orders required).
Exit 0 = daily halt blocks trading, manual resume clears halt, kill switch
blocks until process restart.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, replace

import numpy as np

from aegis.config import load_config
from aegis.core.models import Side
from aegis.log import setup_logging
from aegis.risk.breakers import BreakerState, resume_after_manual_review
from aegis.risk.engine import RiskEngine

logger = logging.getLogger(__name__)

START_EQUITY = 1000.0


@dataclass(frozen=True)
class DrillResult:
    daily_halt_tripped: bool
    trade_blocked_while_halted: bool
    trade_allowed_after_resume: bool
    kill_switch_tripped: bool
    kill_blocks_resume: bool

    @property
    def passed(self) -> bool:
        return all(
            (
                self.daily_halt_tripped,
                self.trade_blocked_while_halted,
                self.trade_allowed_after_resume,
                self.kill_switch_tripped,
                self.kill_blocks_resume,
            )
        )


def _approve_smoke(engine: RiskEngine, equity: float) -> bool:
    approval = engine.approve_trade(
        equity=equity,
        symbol="BTC",
        new_risk_r=0.5,
        open_risk_r=0.0,
        open_risk_by_symbol={},
        returns_by_symbol={"BTC": np.zeros(100)},
        side=Side.BUY,
        limit_price=100.0,
        best_bid=99.5,
        best_ask=100.0,
    )
    return approval.approved


def run_breaker_drill(cfg) -> DrillResult:
    """Simulate daily loss breach, verify halt/resume, then kill switch."""
    state = BreakerState(session_start_equity=START_EQUITY, peak_equity=START_EQUITY)
    engine = RiskEngine(cfg.risk, state)

    # Baseline: trading allowed.
    assert _approve_smoke(engine, START_EQUITY), "pre-drill approve failed"

    # Trip daily breaker: loss >= 3 x max single-trade risk (aggressive tier).
    max_risk_usd = START_EQUITY * cfg.risk.tiers.aggressive
    trip_equity = START_EQUITY - cfg.risk.daily_breaker_multiple * max_risk_usd - 1.0
    alerts = engine.update_equity(trip_equity)
    daily_halt_tripped = engine.state.halted_daily and any("daily circuit breaker" in a for a in alerts)
    trade_blocked = (
        engine.approve_trade(
            equity=trip_equity,
            symbol="BTC",
            new_risk_r=0.5,
            open_risk_r=0.0,
            open_risk_by_symbol={},
            returns_by_symbol={"BTC": np.zeros(100)},
            side=Side.BUY,
            limit_price=100.0,
            best_bid=99.5,
            best_ask=100.0,
        ).reason
        == "daily_halt_active"
    )

    resume_after_manual_review(engine.state)
    trade_allowed = _approve_smoke(engine, trip_equity)

    # Kill switch with temporary threshold (production config keeps this null).
    kill_cfg = replace(cfg.risk, kill_switch_drawdown_pct=0.10)
    kill_state = BreakerState(session_start_equity=START_EQUITY, peak_equity=START_EQUITY)
    kill_engine = RiskEngine(kill_cfg, kill_state)
    kill_engine.update_equity(START_EQUITY)
    kill_alerts = kill_engine.update_equity(START_EQUITY * 0.89)
    kill_tripped = kill_engine.state.killed and any("kill switch" in a for a in kill_alerts)

    kill_blocks = False
    try:
        resume_after_manual_review(kill_engine.state)
    except RuntimeError:
        kill_blocks = True

    return DrillResult(
        daily_halt_tripped=daily_halt_tripped,
        trade_blocked_while_halted=trade_blocked,
        trade_allowed_after_resume=trade_allowed,
        kill_switch_tripped=kill_tripped,
        kill_blocks_resume=kill_blocks,
    )


async def run_and_notify(cfg, *, notify: bool) -> DrillResult:
    result = run_breaker_drill(cfg)
    if notify and result.passed:
        from aegis.monitor.milestones import notify_breaker_drill_passed

        await notify_breaker_drill_passed(cfg, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="M4 risk breaker drill (P2.5)")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--notify", action="store_true", help="Telegram on pass")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)

    result = asyncio.run(run_and_notify(cfg, notify=args.notify))
    logger.info(
        "breaker drill",
        extra={
            "passed": result.passed,
            "daily_halt": result.daily_halt_tripped,
            "kill_switch": result.kill_switch_tripped,
        },
    )

    if not result.passed:
        print("BREAKER DRILL: FAIL", file=sys.stderr)
        print(result, file=sys.stderr)
        raise SystemExit(1)

    print("BREAKER DRILL: PASS — daily halt + kill switch verified")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
