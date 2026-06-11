"""P2.5 Hyperliquid testnet spread campaign — full pipeline proof.

Runs N two-leg IOC spreads through: fee verify → risk engine → SpreadExecutor
→ SQLite audit trail → fill reconciliation → position close.

    uv run aegis-testnet-campaign --count 20

Refuses mainnet. Uses oracle-aligned alt pairs (SOL/DOGE, SOL/ARB, DOGE/ARB).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from aegis.config import load_config
from aegis.core.models import Venue
from aegis.data import db
from aegis.execution import build_market_data, build_trading
from aegis.execution.fees import verify_fees_at_startup
from aegis.execution.spread import SpreadExecutor
from aegis.execution.testnet_pairs import CAMPAIGN_PAIRS
from aegis.log import setup_logging
from aegis.portfolio.spread_pipeline import (
    ensure_flat,
    run_spread_trade,
)
from aegis.risk.breakers import BreakerState
from aegis.risk.engine import RiskEngine

logger = logging.getLogger(__name__)

DEFAULT_ORDER_USD = 12.0
DEFAULT_COUNT = 20
DEFAULT_DELAY_S = 2.0


async def run_campaign(
    *,
    count: int,
    order_usd: float,
    delay_s: float,
    config_path: str,
) -> int:
    cfg = load_config(config_path)
    if not cfg.hyperliquid.testnet:
        raise SystemExit("REFUSING: exchanges.hyperliquid.testnet is false in config")

    await verify_fees_at_startup(cfg)
    conn = db.connect(cfg.sqlite_path)
    risk = RiskEngine(cfg.risk, BreakerState())
    md = build_market_data(Venue.HYPERLIQUID, testnet=True)
    trading = build_trading(Venue.HYPERLIQUID, cfg.secrets, testnet=True)

    successes = 0
    skipped = 0
    failed = 0
    symbols = {s for p in CAMPAIGN_PAIRS for s in (p.long_symbol, p.short_symbol)}

    try:
        equity = await trading.fetch_equity_usd()
        logger.info("campaign start", extra={"equity_usd": equity, "target": count})
        db.insert_equity_snapshot(
            conn,
            ts_ms=int(time.time() * 1000),
            venue="hyperliquid",
            equity_usd=equity,
            mode=cfg.mode,
        )

        for i in range(count):
            pair = CAMPAIGN_PAIRS[i % len(CAMPAIGN_PAIRS)]
            executor = SpreadExecutor(trading, liquidity_rank=pair.liquidity_rank)
            equity = await trading.fetch_equity_usd()
            risk.update_equity(equity)

            if risk.state.killed or risk.state.halted_daily:
                logger.critical("breaker active — stopping campaign")
                break

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

            if not result.approved:
                skipped += 1
                logger.info(
                    "spread skipped",
                    extra={"i": i + 1, "reason": result.skip_reason},
                )
            elif (
                result.execution
                and result.execution.leg2_status.value == "filled"
                and result.reconciled
                and result.closed
            ):
                successes += 1
                logger.info(
                    "spread ok",
                    extra={"i": i + 1, "spread_id": result.spread_id, "successes": successes},
                )
            else:
                failed += 1
                logger.warning(
                    "spread failed",
                    extra={
                        "i": i + 1,
                        "error": result.execution.error if result.execution else None,
                        "reconciled": result.reconciled,
                        "closed": result.closed,
                    },
                )

            if delay_s > 0 and i + 1 < count:
                await asyncio.sleep(delay_s)

        flat = await ensure_flat(trading, symbols)
        fill_count = db.count_fills(conn, Venue.HYPERLIQUID.value)
        equity_end = await trading.fetch_equity_usd()
        db.insert_equity_snapshot(
            conn,
            ts_ms=int(time.time() * 1000),
            venue="hyperliquid",
            equity_usd=equity_end,
            mode=cfg.mode,
        )

        print("=" * 64)
        print("TESTNET SPREAD CAMPAIGN")
        print("=" * 64)
        print(f"requested:     {count}")
        print(f"successes:     {successes}")
        print(f"skipped:       {skipped}")
        print(f"failed:        {failed}")
        print(f"fills in db:   {fill_count}")
        print(f"flat:          {flat}")
        print(f"equity start:  ${equity:,.2f}")
        print(f"equity end:    ${equity_end:,.2f}")
        print("=" * 64)

        if successes < count:
            return 1
        return 0
    finally:
        await trading.close()
        await md.close()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyperliquid testnet spread campaign (P2.5)")
    parser.add_argument(
        "--count", type=int, default=DEFAULT_COUNT, help="target successful spreads"
    )
    parser.add_argument("--order-usd", type=float, default=DEFAULT_ORDER_USD)
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY_S, help="seconds between attempts"
    )
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    setup_logging()
    try:
        code = asyncio.run(
            run_campaign(
                count=args.count,
                order_usd=args.order_usd,
                delay_s=args.delay,
                config_path=args.config,
            )
        )
        sys.exit(code)
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("campaign failed")
        sys.exit(f"FAILED: {exc}")


if __name__ == "__main__":
    main()
