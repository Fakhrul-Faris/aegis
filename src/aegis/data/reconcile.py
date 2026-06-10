"""Stored-vs-venue candle reconciliation (P0.3).

Samples random stored candles (old enough to be immutable), refetches them
from the venue, and compares OHLCV field by field. Run after the first
backfill and any time data integrity is in doubt:

    aegis-reconcile --samples 10

Exit code 1 on any mismatch - this script is a gate, not a suggestion.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from aegis.config import AegisConfig, load_config
from aegis.core.models import Venue
from aegis.core.timeframes import timeframe_ms
from aegis.data import db
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

REL_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Mismatch:
    venue: str
    symbol: str
    timeframe: str
    open_time_ms: int
    field: str
    stored: float
    fetched: float | None  # None = candle missing on venue


def _sample_rows(conn, samples_per_venue: int) -> list[tuple]:
    """Random stored candles at least 2 intervals old (immutable by now)."""
    now_ms = int(time.time() * 1000)
    rows: list[tuple] = []
    for venue in Venue:
        for timeframe_row in conn.execute(
            "SELECT DISTINCT timeframe FROM candles WHERE venue = ?", (venue.value,)
        ).fetchall():
            timeframe = timeframe_row[0]
            cutoff = now_ms - 2 * timeframe_ms(timeframe)
            rows.extend(
                conn.execute(
                    """
                    SELECT venue, symbol, timeframe, open_time_ms,
                           open, high, low, close, volume
                    FROM candles
                    WHERE venue = ? AND timeframe = ? AND open_time_ms < ?
                    ORDER BY RANDOM() LIMIT ?
                    """,
                    (venue.value, timeframe, cutoff, samples_per_venue),
                ).fetchall()
            )
    return rows


async def reconcile(cfg: AegisConfig, samples_per_venue: int = 5) -> list[Mismatch]:
    from aegis.execution import build_market_data

    conn = db.connect(cfg.sqlite_path)
    adapters: dict[Venue, object] = {}
    mismatches: list[Mismatch] = []

    try:
        for row in _sample_rows(conn, samples_per_venue):
            venue_s, symbol, timeframe, open_ms, *stored_ohlcv = row
            venue = Venue(venue_s)
            if venue not in adapters:
                adapters[venue] = build_market_data(venue)
            md = adapters[venue]

            candles = await md.fetch_candles(
                symbol,
                timeframe,
                since=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
                limit=2,
            )
            match = next(
                (c for c in candles if int(c.open_time.timestamp() * 1000) == open_ms),
                None,
            )
            if match is None:
                mismatches.append(
                    Mismatch(venue_s, symbol, timeframe, open_ms, "candle", 0.0, None)
                )
                continue

            fetched_ohlcv = (match.open, match.high, match.low, match.close, match.volume)
            for name, stored, fetched in zip(
                ("open", "high", "low", "close", "volume"),
                stored_ohlcv,
                fetched_ohlcv,
                strict=True,
            ):
                if not math.isclose(stored, fetched, rel_tol=REL_TOLERANCE, abs_tol=1e-12):
                    mismatches.append(
                        Mismatch(venue_s, symbol, timeframe, open_ms, name, stored, fetched)
                    )
    finally:
        for adapter in adapters.values():
            await adapter.close()
        conn.close()

    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis candle reconciliation")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--samples", type=int, default=5, help="samples per venue/timeframe")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)

    mismatches = asyncio.run(reconcile(cfg, args.samples))
    if mismatches:
        for m in mismatches:
            logger.error("reconciliation mismatch", extra=m.__dict__)
            print(f"MISMATCH {m}")
        raise SystemExit(1)
    print("Reconciliation clean - stored candles match venue data.")


if __name__ == "__main__":
    main()
