"""Daily collection summary (P0.5) - the heartbeat that proves the system is alive.

A silent collector is indistinguishable from a dead one; this summary makes
absence of data loud. Sent to Telegram once a day by the collector daemon,
or manually via ``aegis-summary``.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import time
from datetime import UTC, datetime

from aegis.config import AegisConfig, load_config
from aegis.data import db
from aegis.log import setup_logging

DAY_MS = 86_400_000


def build_summary(conn: sqlite3.Connection, now_ms: int | None = None) -> str:
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    since = now - DAY_MS

    candle_rows = conn.execute(
        """
        SELECT venue, COUNT(*) FROM candles
        WHERE inserted_ms >= ? GROUP BY venue ORDER BY venue
        """,
        (since,),
    ).fetchall()
    candles_24h = ", ".join(f"{v}: {n}" for v, n in candle_rows) or "NONE"

    snapshots_24h = conn.execute(
        "SELECT COUNT(*) FROM market_snapshots WHERE ts_ms >= ?", (since,)
    ).fetchone()[0]

    flag_rows = conn.execute(
        """
        SELECT variant, COUNT(*) FROM scanner_flags
        WHERE ts_ms >= ? GROUP BY variant ORDER BY variant
        """,
        (since,),
    ).fetchall()
    flags_24h = ", ".join(f"{v}: {n}" for v, n in flag_rows) or "none"
    flags_total = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]

    series = conn.execute("SELECT DISTINCT venue, symbol, timeframe FROM candles").fetchall()
    total_gaps = 0
    from aegis.core.models import Venue
    from aegis.core.timeframes import timeframe_ms

    for venue_s, symbol, timeframe in series:
        total_gaps += len(
            db.find_gaps(conn, Venue(venue_s), symbol, timeframe, timeframe_ms(timeframe))
        )

    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    db_mb = page_count * page_size / 1_048_576

    stamp = datetime.fromtimestamp(now / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    warning = "" if snapshots_24h else "\nWARNING: zero snapshots in 24h - scanner down?"
    return (
        f"Aegis daily summary - {stamp}\n"
        f"Candles (24h): {candles_24h}\n"
        f"Snapshots (24h): {snapshots_24h}\n"
        f"Flags (24h): {flags_24h}\n"
        f"Flags (all time): {flags_total}\n"
        f"Candle series: {len(series)} | unfilled gaps: {total_gaps}\n"
        f"DB size: {db_mb:.1f} MB"
        f"{warning}"
    )


async def send_daily_summary(cfg: AegisConfig) -> str:
    from aegis.monitor.telegram import notifier_from_config

    conn = db.connect(cfg.sqlite_path)
    try:
        text = build_summary(conn)
    finally:
        conn.close()

    notifier = notifier_from_config(cfg)
    try:
        await notifier.send(text)
    finally:
        await notifier.close()
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis daily summary")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    print(asyncio.run(send_daily_summary(cfg)))


if __name__ == "__main__":
    main()
