"""Unified collector daemon (P0.5) - the single process a server runs.

Every hour, on the hour (+ a small offset): scan, then ingest. Once a day at
the configured UTC hour: Telegram summary. Each task is individually
guarded - one failing run alerts Telegram and the loop carries on. This is
what the Fly.io container executes; locally it can be run in a terminal for
testing with ``--once``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from aegis.config import AegisConfig, load_config
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

_OFFSET_SECONDS = 90  # run at :01:30 so venue/CoinGecko hourly data is settled
_STATE_FILE = "collector_state.json"


def _state_path(cfg: AegisConfig) -> Path:
    return Path(cfg.sqlite_path).parent / _STATE_FILE


def _read_last_summary_day(cfg: AegisConfig) -> str | None:
    path = _state_path(cfg)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text()).get("last_summary_day")
    except (json.JSONDecodeError, OSError):
        return None


def _write_last_summary_day(cfg: AegisConfig, day_key: str) -> None:
    path = _state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_summary_day": day_key}))


def seconds_until_next_tick(now_s: float, offset_s: int = _OFFSET_SECONDS) -> float:
    """Seconds until the next hour boundary plus offset."""
    next_hour = (int(now_s) // 3600 + 1) * 3600
    return max(1.0, next_hour + offset_s - now_s)


def summary_due(now_s: float, summary_hour_utc: int, last_sent_day: str | None) -> tuple[bool, str]:
    """(due, day_key). Due when we are at/past the summary hour for a new day."""
    dt = datetime.fromtimestamp(now_s, tz=UTC)
    day_key = dt.strftime("%Y-%m-%d")
    return (dt.hour >= summary_hour_utc and day_key != last_sent_day), day_key


async def _guarded(cfg: AegisConfig, name: str, coro) -> None:
    from aegis.monitor.telegram import notify_crash

    try:
        await coro
    except Exception as exc:
        logger.exception("collector task failed", extra={"task": name})
        await notify_crash(cfg, name, exc)


async def run_cycle(cfg: AegisConfig) -> None:
    from aegis.data.ingest import run_once as ingest_once
    from aegis.data.scanner import run as scan_once

    # Scanner first: its snapshots are unrecoverable if an hour is missed,
    # while candle ingestion can always backfill.
    await _guarded(cfg, "scanner", scan_once(cfg))
    await _guarded(cfg, "ingest", ingest_once(cfg))


async def _telegram_bot_sidecar(cfg: AegisConfig) -> None:
    """Long-poll command bot — runs on Fly alongside collector (no Mac required)."""
    from aegis.monitor.telegram import notify_crash
    from aegis.monitor.telegram_bot import command_bot_enabled, run_bot

    if not command_bot_enabled(cfg):
        return
    try:
        await run_bot(cfg)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("telegram command bot crashed")
        await notify_crash(cfg, "telegram-bot", exc)


async def collector_main(cfg: AegisConfig, once: bool = False) -> None:
    from aegis.monitor.post_m1_deploy import maybe_post_m1_deploy
    from aegis.monitor.summary import send_daily_summary
    from aegis.monitor.telegram import notifier_from_config
    from aegis.monitor.telegram_bot import command_bot_enabled

    notifier = notifier_from_config(cfg)
    startup = "Aegis collector online - hourly scan+ingest active."
    if command_bot_enabled(cfg) and not once:
        startup += " Telegram /commands active on this host."
    await notifier.send(startup)
    await notifier.close()

    bot_task: asyncio.Task | None = None
    if command_bot_enabled(cfg) and not once:
        bot_task = asyncio.create_task(_telegram_bot_sidecar(cfg), name="telegram-bot")
        logger.info("telegram command bot started alongside collector")

    last_summary_day = _read_last_summary_day(cfg)
    try:
        while True:
            await run_cycle(cfg)
            await _guarded(cfg, "post-m1-deploy", maybe_post_m1_deploy(cfg))

            due, day_key = summary_due(
                time.time(), cfg.monitoring.daily_summary_hour_utc, last_summary_day
            )
            if due:
                await _guarded(cfg, "summary", send_daily_summary(cfg))
                last_summary_day = day_key
                _write_last_summary_day(cfg, day_key)

            if once:
                return
            delay = seconds_until_next_tick(time.time())
            logger.info("collector sleeping", extra={"seconds": round(delay)})
            await asyncio.sleep(delay)
    finally:
        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis collector daemon")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--once", action="store_true", help="single cycle, then exit")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    asyncio.run(collector_main(cfg, once=args.once))


if __name__ == "__main__":
    main()
