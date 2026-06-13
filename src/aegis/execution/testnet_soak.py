"""7-day testnet soak daemon (P2.5).

Runs unattended on a schedule:
- Hourly health check: equity, positions, open orders
- Every ``spread_interval_hours``: one full spread through the pipeline
- Daily Telegram summary
- Auto-stops after 7 days with a pass/fail report

Exit criteria (M4 soak gate): zero unhandled crashes, no orphan orders at
cycle end, positions flat after each spread cycle.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from aegis.config import AegisConfig, load_config
from aegis.core.models import Venue
from aegis.data import db
from aegis.execution import build_market_data, build_trading
from aegis.execution.fees import verify_fees_at_startup
from aegis.execution.spread import SpreadExecutor
from aegis.execution.testnet_pairs import CAMPAIGN_PAIRS
from aegis.log import setup_logging
from aegis.portfolio.spread_pipeline import ensure_flat, run_spread_trade
from aegis.risk.breakers import BreakerState
from aegis.risk.engine import RiskEngine

logger = logging.getLogger(__name__)

SOAK_DURATION_DAYS = 7
DEFAULT_SPREAD_INTERVAL_HOURS = 6
DEFAULT_ORDER_USD = 12.0
_TICK_SECONDS = 3600
_STATE_FILE = "soak_state.json"
_VERDICT_FILE = "soak_verdict.json"


@dataclass
class SoakState:
    started_at_ms: int
    cycle: int = 0
    spreads_ok: int = 0
    spreads_fail: int = 0
    health_ok: int = 0
    anomalies: int = 0
    last_spread_cycle: int = 0
    pair_index: int = 0


def _state_path(cfg: AegisConfig) -> Path:
    return Path(cfg.sqlite_path).parent / _STATE_FILE


def _load_state(cfg: AegisConfig) -> SoakState:
    path = _state_path(cfg)
    if path.exists():
        return SoakState(**json.loads(path.read_text()))
    return SoakState(started_at_ms=int(time.time() * 1000))


def _save_state(cfg: AegisConfig, state: SoakState) -> None:
    path = _state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2))


def _save_verdict(cfg: AegisConfig, *, passed: bool, state: SoakState) -> None:
    path = Path(cfg.sqlite_path).parent / _VERDICT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "passed": passed,
                "completed_at_ms": int(time.time() * 1000),
                "spreads_ok": state.spreads_ok,
                "spreads_fail": state.spreads_fail,
                "anomalies": state.anomalies,
            },
            indent=2,
        )
    )


def _soak_elapsed_days(state: SoakState) -> float:
    return (time.time() * 1000 - state.started_at_ms) / (86400 * 1000)


def _log_event(conn, event: str, detail: dict) -> None:
    conn.execute(
        "INSERT INTO soak_log (ts_ms, event, detail_json) VALUES (?, ?, ?)",
        (int(time.time() * 1000), event, json.dumps(detail)),
    )
    conn.commit()


async def health_check(cfg: AegisConfig, conn, trading, state: SoakState) -> list[str]:
    anomalies: list[str] = []
    symbols = {s for p in CAMPAIGN_PAIRS for s in (p.long_symbol, p.short_symbol)}

    equity = await trading.fetch_equity_usd()
    db.insert_equity_snapshot(
        conn,
        ts_ms=int(time.time() * 1000),
        venue="testnet_soak",
        equity_usd=equity,
        mode=cfg.mode,
    )

    if not await ensure_flat(trading, symbols):
        positions = await trading.fetch_positions()
        open_pos = [p for p in positions if p.symbol in symbols and p.quantity > 0]
        anomalies.append(f"unexpected_positions:{[(p.symbol, p.quantity) for p in open_pos]}")

    open_orders = await trading.fetch_open_order_count()
    if open_orders > 0:
        anomalies.append(f"orphan_open_orders:{open_orders}")

    if anomalies:
        state.anomalies += len(anomalies)
        for msg in anomalies:
            logger.warning("soak anomaly", extra={"detail": msg})
            _log_event(conn, "anomaly", {"message": msg, "cycle": state.cycle})
    else:
        state.health_ok += 1
        _log_event(conn, "health_ok", {"equity": equity, "cycle": state.cycle})

    return anomalies


async def maybe_run_spread(
    cfg: AegisConfig,
    conn,
    trading,
    md,
    risk: RiskEngine,
    state: SoakState,
    *,
    spread_interval_hours: int,
    order_usd: float,
) -> None:
    cycles_per_spread = max(1, spread_interval_hours)
    if state.last_spread_cycle > 0 and (state.cycle - state.last_spread_cycle) < cycles_per_spread:
        return

    pair = CAMPAIGN_PAIRS[state.pair_index % len(CAMPAIGN_PAIRS)]
    state.pair_index += 1
    state.last_spread_cycle = state.cycle

    executor = SpreadExecutor(trading, liquidity_rank=pair.liquidity_rank)
    equity = await trading.fetch_equity_usd()
    risk.update_equity(equity)

    result = await run_spread_trade(
        cfg=cfg,
        conn=conn,
        risk=risk,
        trading=trading,
        md=md,
        executor=executor,
        pair=pair,
        order_usd=order_usd,
        equity=equity,
    )

    if (
        result.approved
        and result.execution
        and result.execution.leg2_status.value == "filled"
        and result.reconciled
        and result.closed
    ):
        state.spreads_ok += 1
        _log_event(conn, "spread_ok", {"spread_id": result.spread_id, "pair": pair.long_symbol})
        logger.info("soak spread ok", extra={"spread_id": result.spread_id})
    else:
        state.spreads_fail += 1
        _log_event(
            conn,
            "spread_fail",
            {
                "spread_id": result.spread_id,
                "skip": result.skip_reason,
                "error": result.execution.error if result.execution else None,
            },
        )
        logger.warning("soak spread fail", extra={"reason": result.skip_reason})


async def send_soak_summary(cfg: AegisConfig, state: SoakState, *, final: bool = False) -> None:
    from aegis.monitor.telegram import notifier_from_config

    elapsed = _soak_elapsed_days(state)
    label = "FINAL" if final else "daily"
    text = (
        f"Aegis testnet soak ({label})\n"
        f"  day:       {elapsed:.1f} / {SOAK_DURATION_DAYS}\n"
        f"  cycles:    {state.cycle}\n"
        f"  spreads:   {state.spreads_ok} ok / {state.spreads_fail} fail\n"
        f"  health:    {state.health_ok} ok\n"
        f"  anomalies: {state.anomalies}"
    )
    if final:
        passed = state.anomalies == 0 and state.spreads_fail == 0
        text += f"\n  verdict:   {'PASS' if passed else 'NEEDS REVIEW'}"
    notifier = notifier_from_config(cfg)
    try:
        await notifier.send(text)
    finally:
        await notifier.close()


async def soak_main(
    cfg: AegisConfig,
    *,
    once: bool = False,
    spread_interval_hours: int = DEFAULT_SPREAD_INTERVAL_HOURS,
    order_usd: float = DEFAULT_ORDER_USD,
) -> int:
    if not cfg.hyperliquid.testnet:
        raise SystemExit("REFUSING: testnet soak requires exchanges.hyperliquid.testnet=true")

    await verify_fees_at_startup(cfg)
    conn = db.connect(cfg.sqlite_path)
    state = _load_state(cfg)
    if state.cycle == 0:
        _log_event(conn, "soak_start", {"started_at_ms": state.started_at_ms})
        await send_soak_summary(cfg, state)

    risk = RiskEngine(cfg.risk, BreakerState())
    md = build_market_data(Venue.HYPERLIQUID, testnet=True)
    trading = build_trading(Venue.HYPERLIQUID, cfg.secrets, testnet=True)

    last_summary_day: str | None = None
    exit_code = 0

    try:
        while True:
            state.cycle += 1
            logger.info(
                "soak cycle",
                extra={"cycle": state.cycle, "day": round(_soak_elapsed_days(state), 2)},
            )

            try:
                await health_check(cfg, conn, trading, state)
                await maybe_run_spread(
                    cfg,
                    conn,
                    trading,
                    md,
                    risk,
                    state,
                    spread_interval_hours=spread_interval_hours,
                    order_usd=order_usd,
                )
            except Exception as exc:
                state.anomalies += 1
                _log_event(conn, "crash", {"cycle": state.cycle, "error": repr(exc)})
                logger.exception("soak cycle error")
                from aegis.monitor.telegram import notify_crash

                await notify_crash(cfg, "testnet-soak", exc)

            _save_state(cfg, state)

            now = datetime.fromtimestamp(time.time(), tz=UTC)
            day_key = now.strftime("%Y-%m-%d")
            if now.hour >= cfg.monitoring.daily_summary_hour_utc and day_key != last_summary_day:
                await send_soak_summary(cfg, state)
                last_summary_day = day_key

            if _soak_elapsed_days(state) >= SOAK_DURATION_DAYS:
                passed = state.anomalies == 0 and state.spreads_fail == 0
                _save_verdict(cfg, passed=passed, state=state)
                await send_soak_summary(cfg, state, final=True)
                from aegis.monitor.milestones import notify_soak_verdict

                await notify_soak_verdict(
                    cfg,
                    passed=passed,
                    elapsed_days=_soak_elapsed_days(state),
                    spreads_ok=state.spreads_ok,
                    spreads_fail=state.spreads_fail,
                    anomalies=state.anomalies,
                )
                _log_event(conn, "soak_complete", asdict(state))
                if not passed:
                    exit_code = 1
                break

            if once:
                break

            await asyncio.sleep(_TICK_SECONDS)
    finally:
        await trading.close()
        await md.close()
        conn.close()

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyperliquid testnet 7-day soak (P2.5)")
    parser.add_argument("--config", default=os.environ.get("AEGIS_CONFIG", "config/config.yaml"))
    parser.add_argument("--once", action="store_true", help="single cycle then exit")
    parser.add_argument(
        "--spread-interval-hours",
        type=int,
        default=DEFAULT_SPREAD_INTERVAL_HOURS,
        help="run one spread every N hourly cycles",
    )
    parser.add_argument("--order-usd", type=float, default=DEFAULT_ORDER_USD)
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    code = asyncio.run(
        soak_main(
            cfg,
            once=args.once,
            spread_interval_hours=args.spread_interval_hours,
            order_usd=args.order_usd,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
