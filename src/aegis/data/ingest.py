"""Candle ingestion with backfill and gap repair (P0.3).

Run modes:
- one-shot (cron-friendly):    aegis-ingest
- continuous loop:             aegis-ingest --loop 900

Per series (venue, symbol, timeframe):
1. Resume from the last stored bar (or ``initial_backfill_days`` on first run).
2. Page forward until caught up, storing only CLOSED bars.
3. Detect gaps across the stored series, attempt one refetch per gap, and
   log whatever remains - persistent gaps are a data-quality KPI (weekly log).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aegis.config import AegisConfig, load_config
from aegis.core.interfaces import MarketData
from aegis.core.models import Venue
from aegis.core.timeframes import timeframe_ms
from aegis.data import db
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

_PAGE_LIMIT = 500


@dataclass
class SeriesStats:
    venue: Venue
    symbol: str
    timeframe: str
    inserted: int = 0
    gaps_found: int = 0
    gaps_unfilled: int = 0
    error: str | None = None


@dataclass
class IngestReport:
    series: list[SeriesStats] = field(default_factory=list)

    @property
    def inserted(self) -> int:
        return sum(s.inserted for s in self.series)

    @property
    def errors(self) -> list[SeriesStats]:
        return [s for s in self.series if s.error]

    @property
    def unfilled_gaps(self) -> int:
        return sum(s.gaps_unfilled for s in self.series)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _closed_only(candles, interval_ms: int, now_ms: int):
    return [c for c in candles if int(c.open_time.timestamp() * 1000) + interval_ms <= now_ms]


async def ingest_series(
    market_data: MarketData,
    conn,
    venue: Venue,
    symbol: str,
    timeframe: str,
    initial_backfill_days: int,
    now_ms: int | None = None,
) -> SeriesStats:
    stats = SeriesStats(venue=venue, symbol=symbol, timeframe=timeframe)
    interval = timeframe_ms(timeframe)
    now = now_ms if now_ms is not None else _now_ms()

    last = db.last_candle_open_ms(conn, venue, symbol, timeframe)
    since_ms = last + interval if last is not None else now - initial_backfill_days * 86_400_000

    # Page forward until caught up.
    while since_ms + interval <= now:
        batch = await market_data.fetch_candles(
            symbol,
            timeframe,
            since=datetime.fromtimestamp(since_ms / 1000, tz=UTC),
            limit=_PAGE_LIMIT,
        )
        closed = _closed_only(batch, interval, now)
        if not closed:
            break
        stats.inserted += db.upsert_candles(conn, closed)
        newest_ms = int(closed[-1].open_time.timestamp() * 1000)
        if newest_ms < since_ms:  # venue returned nothing new; avoid looping
            break
        since_ms = newest_ms + interval
        if len(batch) < 2:
            break

    # Gap repair: one refetch attempt per gap, then count what remains.
    gaps = db.find_gaps(conn, venue, symbol, timeframe, interval)
    stats.gaps_found = len(gaps)
    for gap_start, gap_end in gaps:
        batch = await market_data.fetch_candles(
            symbol,
            timeframe,
            since=datetime.fromtimestamp(gap_start / 1000, tz=UTC),
            limit=min(_PAGE_LIMIT, (gap_end - gap_start) // interval + 1),
        )
        in_gap = [
            c
            for c in _closed_only(batch, interval, now)
            if gap_start <= int(c.open_time.timestamp() * 1000) < gap_end
        ]
        if in_gap:
            stats.inserted += db.upsert_candles(conn, in_gap)

    stats.gaps_unfilled = len(db.find_gaps(conn, venue, symbol, timeframe, interval))
    if stats.gaps_unfilled:
        logger.warning(
            "unfilled candle gaps",
            extra={
                "venue": venue.value,
                "symbol": symbol,
                "timeframe": timeframe,
                "gaps": stats.gaps_unfilled,
            },
        )
    return stats


async def run_once(cfg: AegisConfig) -> IngestReport:
    from aegis.execution import build_market_data

    report = IngestReport()
    conn = db.connect(cfg.sqlite_path)

    hyperliquid = build_market_data(Venue.HYPERLIQUID, testnet=False)
    kraken = build_market_data(Venue.KRAKEN)
    try:
        # NOTE: market data always comes from Hyperliquid MAINNET - statistics
        # on testnet prices would be statistics about nothing. The testnet
        # flag applies to order execution only.
        coins = await hyperliquid.fetch_top_coins_by_volume(cfg.data.hyperliquid_top_n)

        for venue, md, symbols in (
            (Venue.HYPERLIQUID, hyperliquid, coins),
            (Venue.KRAKEN, kraken, cfg.data.kraken_symbols),
        ):
            for symbol in symbols:
                for timeframe in cfg.data.timeframes:
                    try:
                        stats = await ingest_series(
                            md,
                            conn,
                            venue,
                            symbol,
                            timeframe,
                            cfg.data.initial_backfill_days,
                        )
                    except Exception as exc:
                        stats = SeriesStats(
                            venue=venue,
                            symbol=symbol,
                            timeframe=timeframe,
                            error=repr(exc),
                        )
                        logger.error(
                            "series ingest failed",
                            extra={
                                "venue": venue.value,
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "error": repr(exc),
                            },
                        )
                    report.series.append(stats)
    finally:
        await hyperliquid.close()
        await kraken.close()
        conn.close()

    logger.info(
        "ingest run complete",
        extra={
            "series": len(report.series),
            "inserted": report.inserted,
            "errors": len(report.errors),
            "unfilled_gaps": report.unfilled_gaps,
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis candle ingestion")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument(
        "--loop",
        type=int,
        metavar="SECONDS",
        help="run continuously, sleeping SECONDS between runs",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)

    if args.loop:
        while True:
            asyncio.run(run_once(cfg))
            time.sleep(args.loop)
    else:
        asyncio.run(run_once(cfg))


if __name__ == "__main__":
    main()
