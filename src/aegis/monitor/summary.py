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
from aegis.monitor.daily_scorecard import build_daily_scorecard, format_daily_scorecard

DAY_MS = 86_400_000


def _collection_lines(conn: sqlite3.Connection, now_ms: int) -> list[str]:
    since = now_ms - DAY_MS

    candle_rows = conn.execute(
        """
        SELECT venue, COUNT(*) FROM candles
        WHERE inserted_ms >= ? GROUP BY venue ORDER BY venue
        """,
        (since,),
    ).fetchall()
    candles_24h = ", ".join(f"{v}: {n}" for v, n in candle_rows) or "none"

    flag_rows = conn.execute(
        """
        SELECT variant, COUNT(*) FROM scanner_flags
        WHERE ts_ms >= ? GROUP BY variant ORDER BY variant
        """,
        (since,),
    ).fetchall()
    flags_24h = ", ".join(f"{v}: {n}" for v, n in flag_rows) or "none"
    flags_total = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]

    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    db_mb = page_count * page_size / 1_048_576

    open_positions = len(db.open_paper_positions(conn))
    taken_signals = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE strategy='A' AND taken=1"
    ).fetchone()[0]

    return [
        "--- DATA COLLECTION (24h) ---",
        f"Candles:        {candles_24h}",
        f"Flags:          {flags_24h} (all time: {flags_total})",
        f"Paper:          {open_positions} open | {taken_signals} signals taken",
        f"DB size:        {db_mb:.1f} MB",
    ]


def build_summary(conn: sqlite3.Connection, now_ms: int | None = None) -> str:
    now = now_ms if now_ms is not None else int(time.time() * 1000)

    card = build_daily_scorecard(conn, now)
    lines = [format_daily_scorecard(card, conn, now), "", *_collection_lines(conn, now)]

    if not card.scanner_ok:
        lines.append("")
        lines.append("WARNING: zero snapshots in 24h — scanner down?")

    stamp = datetime.fromtimestamp(now / 1000, tz=UTC).strftime("%H:%M UTC")
    lines.append("")
    lines.append(f"Report time: {stamp}")
    return "\n".join(lines)


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
