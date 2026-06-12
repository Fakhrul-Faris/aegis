"""Portfolio brain — one cycle loop (P2.4, Concept §5).

Orchestrates: fee verification → equity update → breaker checks → signal
ranking → risk approval → dispatch. Strategies produce signals; this layer
decides what actually trades.

Paper mode runs Strategy A with scanner-flag joins and simulated Kraken fills.
Testnet spread dispatch is separate (``aegis-testnet-campaign`` / soak).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from aegis.config import load_config
from aegis.data import db
from aegis.execution.fees import verify_fees_at_startup
from aegis.log import setup_logging
from aegis.portfolio.paper_swing import run_paper_cycle
from aegis.risk.breakers import BreakerState
from aegis.risk.engine import RiskEngine

logger = logging.getLogger(__name__)


async def run_cycle(cfg, conn, risk: RiskEngine) -> None:
    """One portfolio cycle."""
    if cfg.mode == "paper":
        await run_paper_cycle(cfg, conn, risk)
        return

    logger.warning("non-paper cycle not implemented in brain — use testnet tools")
    alerts = risk.update_equity(1000.0)
    for msg in alerts:
        logger.critical(msg)


async def run_once(cfg_path: str = "config/config.yaml") -> None:
    cfg = load_config(cfg_path)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    await verify_fees_at_startup(cfg)

    conn = db.connect(cfg.sqlite_path)
    risk = RiskEngine(cfg.risk, BreakerState())
    try:
        await run_cycle(cfg, conn, risk)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis portfolio brain (one cycle)")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument(
        "--loop",
        type=int,
        metavar="SECONDS",
        help="run continuously (4h strategy → default 14400s poll)",
    )
    args = parser.parse_args()

    if args.loop:
        while True:
            asyncio.run(run_once(args.config))
            time.sleep(args.loop)
    else:
        asyncio.run(run_once(args.config))


if __name__ == "__main__":
    main()
