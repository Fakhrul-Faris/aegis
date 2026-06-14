"""FX5 paper runner — hourly ingest + strategy cycle.

Single entry point for cron / fly.io scheduler.

Usage:
    aegis-forex-paper-run              # one shot: ingest + event fade
    aegis-forex-paper-run --loop 3600  # hourly loop
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from aegis.config import load_config
from aegis.config_forex import load_forex_config
from aegis.data.forex_ingest import run_forex_ingest
from aegis.log import setup_logging
from aegis.monitor.forex_config_freeze import verify_or_freeze_forex_config
from aegis.portfolio.forex_event_fade import run_event_fade_cycle

logger = logging.getLogger(__name__)


async def run_forex_paper_cycle(*, forex_config: str = "config/forex.yaml") -> dict:
    cfg = load_forex_config(forex_config)
    aegis_cfg = load_config()

    from aegis.data import db

    conn = db.connect(cfg.demo.sqlite_path)
    try:
        verify_or_freeze_forex_config(conn, cfg)
    finally:
        conn.close()

    ingest = await run_forex_ingest(cfg, timeframes=("1h",), backfill_days=14)
    fade = await run_event_fade_cycle(cfg)

    return {
        "ingest_inserted": ingest.inserted,
        "ingest_gaps": ingest.unfilled_gaps,
        "fade": fade,
        "telegram": aegis_cfg.secrets.telegram_bot_token is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex demo paper hourly runner (FX5)")
    parser.add_argument("--forex-config", default="config/forex.yaml")
    parser.add_argument("--loop", type=int, default=0, help="repeat every N seconds")
    args = parser.parse_args()

    aegis_cfg = load_config()
    setup_logging(aegis_cfg.monitoring.log_dir, aegis_cfg.monitoring.log_level)

    async def _once():
        result = await run_forex_paper_cycle(forex_config=args.forex_config)
        print(f"forex paper run: {result}")

    if args.loop > 0:
        while True:
            asyncio.run(_once())
            time.sleep(args.loop)
    else:
        asyncio.run(_once())


if __name__ == "__main__":
    main()
