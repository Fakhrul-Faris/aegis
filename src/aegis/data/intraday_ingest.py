"""15m Hyperliquid candle ingest for intraday track (ID0)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass, field

from aegis.config import load_config
from aegis.config_intraday import load_intraday_config
from aegis.core.models import Venue
from aegis.data import db
from aegis.data.ingest import SeriesStats, ingest_series
from aegis.execution import build_market_data
from aegis.log import setup_logging

logger = logging.getLogger(__name__)


@dataclass
class IntradayIngestReport:
    series: list[SeriesStats] = field(default_factory=list)

    @property
    def inserted(self) -> int:
        return sum(s.inserted for s in self.series)

    @property
    def unfilled_gaps(self) -> int:
        return sum(s.gaps_unfilled for s in self.series)


async def run_intraday_ingest(
    *,
    intraday_config: str = "config/intraday.yaml",
    sqlite_path: str | None = None,
) -> IntradayIngestReport:
    icfg = load_intraday_config(intraday_config)
    path = sqlite_path or icfg.demo.sqlite_path
    report = IntradayIngestReport()
    conn = db.connect(path)
    md = build_market_data(Venue.HYPERLIQUID, testnet=False)
    try:
        for symbol in icfg.momentum_day.symbols:
            for timeframe in icfg.data.timeframes:
                try:
                    stats = await ingest_series(
                        md,
                        conn,
                        Venue.HYPERLIQUID,
                        symbol,
                        timeframe,
                        icfg.data.initial_backfill_days,
                    )
                except Exception as exc:
                    stats = SeriesStats(
                        venue=Venue.HYPERLIQUID,
                        symbol=symbol,
                        timeframe=timeframe,
                        error=repr(exc),
                    )
                    logger.error(
                        "intraday ingest failed",
                        extra={"symbol": symbol, "timeframe": timeframe, "error": repr(exc)},
                    )
                report.series.append(stats)
    finally:
        await md.close()
        conn.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Intraday 15m HL ingest (ID0)")
    parser.add_argument("--intraday-config", default="config/intraday.yaml")
    parser.add_argument("--loop", type=int, default=0, help="repeat every N seconds")
    args = parser.parse_args()

    acfg = load_config()
    setup_logging(acfg.monitoring.log_dir, acfg.monitoring.log_level)

    async def _once():
        report = await run_intraday_ingest(intraday_config=args.intraday_config)
        print(f"intraday ingest: inserted={report.inserted} gaps={report.unfilled_gaps}")

    if args.loop > 0:
        while True:
            asyncio.run(_once())
            time.sleep(args.loop)
    else:
        asyncio.run(_once())


if __name__ == "__main__":
    main()
