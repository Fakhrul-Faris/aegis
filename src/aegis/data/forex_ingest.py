"""Forex demo candle ingest (FX4).

Ingests 1h bars for event-spike-fade pairs into SQLite under ``venue=forex_demo``.
Default source: Yahoo Finance (open-source, no API key).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from aegis.config import load_config
from aegis.config_forex import ForexConfig, load_forex_config
from aegis.core.models import Venue
from aegis.core.timeframes import timeframe_ms
from aegis.data import db
from aegis.execution.forex_market_data import build_forex_market_data
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

_PAGE_LIMIT = 500


@dataclass
class ForexIngestStats:
    pair: str
    timeframe: str
    inserted: int = 0
    gaps_found: int = 0
    gaps_unfilled: int = 0
    error: str | None = None


@dataclass
class ForexIngestReport:
    series: list[ForexIngestStats] = field(default_factory=list)

    @property
    def inserted(self) -> int:
        return sum(s.inserted for s in self.series)

    @property
    def unfilled_gaps(self) -> int:
        return sum(s.gaps_unfilled for s in self.series)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _closed_only(candles, interval_ms: int, now_ms: int):
    return [c for c in candles if int(c.open_time.timestamp() * 1000) + interval_ms <= now_ms]


async def ingest_pair_series(
    conn,
    md,
    pair: str,
    timeframe: str,
    *,
    backfill_days: int = 14,
) -> ForexIngestStats:
    stats = ForexIngestStats(pair=pair, timeframe=timeframe)
    interval_ms = timeframe_ms(timeframe)
    now_ms = _now_ms()

    last_ms = db.last_candle_open_ms(conn, Venue.FOREX_DEMO, pair, timeframe)
    if last_ms is None:
        since = datetime.now(tz=UTC) - timedelta(days=backfill_days)
    else:
        since = datetime.fromtimestamp((last_ms + interval_ms) / 1000, tz=UTC)

    try:
        batch = await md.fetch_candles(pair, timeframe, since=since, limit=_PAGE_LIMIT)
        closed = _closed_only(batch, interval_ms, now_ms)
        if closed:
            stats.inserted = db.upsert_candles(conn, closed)
    except Exception as exc:
        stats.error = str(exc)
        logger.exception("forex ingest failed", extra={"pair": pair, "tf": timeframe})
        return stats

    gaps = db.find_gaps(conn, Venue.FOREX_DEMO, pair, timeframe, interval_ms)
    stats.gaps_found = len(gaps)
    for gap_start_ms, _gap_end_ms in gaps[:3]:
        gap_since = datetime.fromtimestamp(gap_start_ms / 1000, tz=UTC)
        try:
            refill = await md.fetch_candles(pair, timeframe, since=gap_since, limit=_PAGE_LIMIT)
            closed = _closed_only(refill, interval_ms, now_ms)
            if closed:
                db.upsert_candles(conn, closed)
        except Exception:
            stats.gaps_unfilled += 1
    remaining = db.find_gaps(conn, Venue.FOREX_DEMO, pair, timeframe, interval_ms)
    stats.gaps_unfilled = max(stats.gaps_unfilled, len(remaining))
    return stats


async def run_forex_ingest(
    cfg: ForexConfig,
    *,
    pairs: list[str] | None = None,
    timeframes: tuple[str, ...] = ("1h",),
    backfill_days: int = 14,
    sqlite_path: str | None = None,
) -> ForexIngestReport:
    aegis_cfg = load_config()
    db_path = sqlite_path or cfg.demo.sqlite_path
    conn = db.connect(db_path)
    md = build_forex_market_data(cfg, aegis_cfg.secrets, conn=conn)
    target_pairs = pairs or list(cfg.event_spike_fade.pairs)
    report = ForexIngestReport()
    try:
        for pair in target_pairs:
            for tf in timeframes:
                stats = await ingest_pair_series(
                    conn, md, pair, tf, backfill_days=backfill_days
                )
                report.series.append(stats)
    finally:
        conn.close()
    return report


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Forex demo candle ingest (FX4)")
    parser.add_argument("--config", default="config/forex.yaml")
    parser.add_argument("--pairs", default=None, help="comma-separated, default frozen pairs")
    parser.add_argument("--timeframes", default="1h", help="comma-separated")
    parser.add_argument("--backfill-days", type=int, default=14)
    parser.add_argument("--loop", type=int, default=0, help="repeat every N seconds")
    args = parser.parse_args()

    cfg = load_forex_config(args.config)
    pairs = args.pairs.split(",") if args.pairs else None
    tfs = tuple(args.timeframes.split(","))

    async def _once():
        report = await run_forex_ingest(
            cfg, pairs=pairs, timeframes=tfs, backfill_days=args.backfill_days
        )
        print(f"forex ingest: inserted={report.inserted} unfilled_gaps={report.unfilled_gaps}")
        for s in report.series:
            line = f"  {s.pair} {s.timeframe}: +{s.inserted} gaps={s.gaps_found}"
            if s.error:
                line += f" ERR={s.error}"
            print(line)

    if args.loop > 0:
        while True:
            asyncio.run(_once())
            time.sleep(args.loop)
    else:
        asyncio.run(_once())


if __name__ == "__main__":
    main()
