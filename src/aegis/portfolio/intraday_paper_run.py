"""ID2 paper runner — ingest + Strategy C cycle.

Usage:
    aegis-intraday-paper-run
    aegis-intraday-paper-run --loop 60
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from aegis.config import load_config
from aegis.config_intraday import load_intraday_config
from aegis.data import db
from aegis.data.intraday_ingest import run_intraday_ingest
from aegis.log import setup_logging
from aegis.monitor.intraday_config_freeze import verify_or_freeze_intraday_config
from aegis.portfolio.intraday_pipeline import run_intraday_cycle

logger = logging.getLogger(__name__)


async def run_intraday_paper_cycle(*, intraday_config: str = "config/intraday.yaml") -> dict:
    icfg = load_intraday_config(intraday_config)
    acfg = load_config()
    conn = db.connect(icfg.demo.sqlite_path)
    try:
        verify_or_freeze_intraday_config(conn, icfg)
        ingest = await run_intraday_ingest(
            intraday_config=intraday_config,
            sqlite_path=icfg.demo.sqlite_path,
        )
        await run_intraday_cycle(icfg, acfg, conn)
    finally:
        conn.close()

    return {
        "ingest_inserted": ingest.inserted,
        "ingest_gaps": ingest.unfilled_gaps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Intraday Strategy C paper runner (ID2)")
    parser.add_argument("--intraday-config", default="config/intraday.yaml")
    parser.add_argument("--loop", type=int, default=0, help="repeat every N seconds")
    parser.add_argument(
        "--reset-config-freeze",
        action="store_true",
        help="reset intraday paper config hash (restarts proof clock)",
    )
    args = parser.parse_args()

    acfg = load_config()
    setup_logging(acfg.monitoring.log_dir, acfg.monitoring.log_level)

    async def _once(reset: bool):
        icfg = load_intraday_config(args.intraday_config)
        conn = db.connect(icfg.demo.sqlite_path)
        try:
            if reset:
                verify_or_freeze_intraday_config(conn, icfg, reset=True)
        finally:
            conn.close()
        result = await run_intraday_paper_cycle(intraday_config=args.intraday_config)
        print(f"intraday paper: {result}")

    reset = args.reset_config_freeze
    if args.loop > 0:
        while True:
            asyncio.run(_once(reset))
            reset = False
            time.sleep(args.loop)
    else:
        asyncio.run(_once(reset))


if __name__ == "__main__":
    main()
