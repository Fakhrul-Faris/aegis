"""Forex economic calendar watch alerts (FX5).

Sends Telegram WATCH messages for tier 2+3 events approaching within the
configured window. Does not place trades — informational only.

Usage:
    aegis-forex-calendar-alerts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime

from aegis.config import load_config
from aegis.config_forex import load_forex_config
from aegis.data import db
from aegis.data.forex_calendar import seed_economic_calendar
from aegis.execution.forex_paper import FOREX_DEMO_VENUE
from aegis.log import setup_logging
from aegis.strategy.forex_confirms import load_calendar_events

STRATEGY_ID = "event_spike_fade"


def _pairs_for_event(currency: str, pairs: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for pair in pairs:
        if pair == "EURUSD" and currency in ("USD", "EUR"):
            out.append(pair)
        elif pair == "GBPUSD" and currency in ("USD", "GBP"):
            out.append(pair)
        elif currency in pair:
            out.append(pair)
    return out


def _already_alerted(conn, event_ts_ms: int, event_code: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM signals
        WHERE strategy = ? AND ts_ms >= ? AND context_json LIKE ?
        LIMIT 1
        """,
        (STRATEGY_ID, int(time.time() * 1000) - 3_600_000, f'%"event_ts_ms": {event_ts_ms}%'),
    ).fetchone()
    if row:
        return True
    row = conn.execute(
        """
        SELECT 1 FROM signals
        WHERE strategy = ? AND context_json LIKE ? AND context_json LIKE ?
        LIMIT 1
        """,
        (STRATEGY_ID, f'%"watch": true%', f'%{event_code}%'),
    ).fetchone()
    return row is not None


def _log_watch(conn, *, ts_ms: int, pair: str, event_code: str, event_ts_ms: int, minutes: int):
    ctx = {
        "watch": True,
        "event_code": event_code,
        "event_ts_ms": event_ts_ms,
        "minutes_until": minutes,
    }
    conn.execute(
        """
        INSERT INTO signals
            (ts_ms, strategy, venue, symbol, direction, taken, skip_reason, context_json)
        VALUES (?, ?, ?, ?, 'watch', 0, 'calendar_watch', ?)
        """,
        (ts_ms, STRATEGY_ID, FOREX_DEMO_VENUE, pair, json.dumps(ctx)),
    )
    conn.commit()


def build_calendar_alerts(cfg, conn, *, db_path: str) -> list[str]:
    now_ms = int(time.time() * 1000)
    window_ms = cfg.calendar.watch_minutes_before * 60_000
    events = load_calendar_events(
        db_path,
        cfg.calendar,
        currencies=cfg.calendar.event_spike_currencies,
        tiers=cfg.calendar.event_spike_tiers,
    )
    messages: list[str] = []
    for event in events:
        delta_ms = event.ts_ms - now_ms
        if delta_ms < 0 or delta_ms > window_ms:
            continue
        if _already_alerted(conn, event.ts_ms, event.event_code):
            continue
        minutes = int(delta_ms / 60_000)
        pairs = _pairs_for_event(event.currency, cfg.event_spike_fade.pairs)
        if not pairs:
            continue
        when = datetime.fromtimestamp(event.ts_ms / 1000, tz=UTC).strftime("%H:%M UTC")
        pair_s = ", ".join(pairs)
        msg = (
            f"WATCH: {event.event_code} ({event.currency}) in {minutes}m "
            f"at {when} — pairs: {pair_s} — fade setup armed"
        )
        messages.append(msg)
        for pair in pairs:
            _log_watch(
                conn,
                ts_ms=now_ms,
                pair=pair,
                event_code=event.event_code,
                event_ts_ms=event.ts_ms,
                minutes=minutes,
            )
    return messages


async def send_calendar_alerts(*, forex_config: str = "config/forex.yaml") -> list[str]:
    from aegis.monitor.telegram import notifier_from_config

    cfg = load_forex_config(forex_config)
    aegis_cfg = load_config()
    conn = db.connect(cfg.demo.sqlite_path)
    db_path = cfg.demo.sqlite_path
    try:
        seed_economic_calendar(conn, year_start=datetime.now(tz=UTC).year - 1, year_end=datetime.now(tz=UTC).year + 1)
        messages = build_calendar_alerts(cfg, conn, db_path=db_path)
    finally:
        conn.close()

    if not messages:
        return []

    notifier = notifier_from_config(aegis_cfg)
    if notifier.enabled:
        try:
            for msg in messages:
                await notifier.send(msg)
        finally:
            await notifier.close()
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex calendar watch alerts")
    parser.add_argument("--forex-config", default="config/forex.yaml")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    aegis_cfg = load_config()
    setup_logging(aegis_cfg.monitoring.log_dir, aegis_cfg.monitoring.log_level)

    if args.print_only:
        cfg = load_forex_config(args.forex_config)
        conn = db.connect(cfg.demo.sqlite_path)
        try:
            seed_economic_calendar(conn)
            for msg in build_calendar_alerts(cfg, conn, db_path=cfg.demo.sqlite_path):
                print(msg)
        finally:
            conn.close()
    else:
        msgs = asyncio.run(send_calendar_alerts(forex_config=args.forex_config))
        for msg in msgs:
            print(msg)
        if not msgs:
            print("no upcoming events in watch window")


if __name__ == "__main__":
    main()
