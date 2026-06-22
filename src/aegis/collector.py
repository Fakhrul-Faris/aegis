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


def _read_collector_state(cfg: AegisConfig) -> dict:
    path = _state_path(cfg)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_collector_state(cfg: AegisConfig, state: dict) -> None:
    path = _state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def _read_last_summary_day(cfg: AegisConfig) -> str | None:
    return _read_collector_state(cfg).get("last_summary_day")


def _write_last_summary_day(cfg: AegisConfig, day_key: str) -> None:
    state = _read_collector_state(cfg)
    state["last_summary_day"] = day_key
    _write_collector_state(cfg, state)


def seconds_until_next_tick(now_s: float, offset_s: int = _OFFSET_SECONDS) -> float:
    """Seconds until the next hour boundary plus offset."""
    next_hour = (int(now_s) // 3600 + 1) * 3600
    return max(1.0, next_hour + offset_s - now_s)


def forex_kpi_due(now_s: float, last_kpi_week: str | None) -> tuple[bool, str]:
    """Sunday >= 17:00 UTC, once per ISO week."""
    dt = datetime.fromtimestamp(now_s, tz=UTC)
    week_key = dt.strftime("%G-W%V")
    due = dt.weekday() == 6 and dt.hour >= 17 and week_key != last_kpi_week
    return due, week_key


async def _forex_calendar_sidecar(cfg: AegisConfig) -> None:
    """15-minute calendar WATCH alerts — same Telegram bot as crypto."""
    from aegis.monitor.forex_collector import run_forex_calendar_alerts_if_enabled
    from aegis.monitor.telegram import notify_crash

    try:
        while True:
            await run_forex_calendar_alerts_if_enabled()
            await asyncio.sleep(900)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("forex calendar sidecar crashed")
        await notify_crash(cfg, "forex-calendar", exc)


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
    from aegis.monitor.forex_collector import run_forex_paper_if_enabled

    # Scanner first: its snapshots are unrecoverable if an hour is missed.
    # Forex paper next — must not wait on slow/failing crypto candle ingest.
    await _guarded(cfg, "scanner", scan_once(cfg))
    await _guarded(cfg, "forex-paper", run_forex_paper_if_enabled())
    await _guarded(cfg, "ingest", ingest_once(cfg))
    from aegis.monitor.portfolio_collector import run_portfolio_paper_if_enabled

    await _guarded(cfg, "portfolio-paper", run_portfolio_paper_if_enabled())


async def _intraday_sidecar(cfg: AegisConfig) -> None:
    """Strategy C paper loop — 60s on Fly (``AEGIS_INTRADAY_ENABLED=1``)."""
    from aegis.config_intraday import load_intraday_config
    from aegis.monitor.intraday_collector import run_intraday_paper_if_enabled
    from aegis.monitor.telegram import notify_crash

    if not intraday_collector_enabled():
        return
    icfg = load_intraday_config()
    interval = max(30, icfg.data.loop_seconds)
    failures = 0
    while True:
        try:
            await run_intraday_paper_if_enabled()
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures += 1
            logger.exception(
                "intraday paper cycle failed",
                extra={"consecutive_failures": failures},
            )
            # Alert on first failure and every 10th — avoid Telegram spam on sustained 429s.
            if failures == 1 or failures % 10 == 0:
                await notify_crash(cfg, "intraday-paper", exc)
        await asyncio.sleep(interval)


def intraday_collector_enabled() -> bool:
    from aegis.monitor.intraday_collector import intraday_collector_enabled as _enabled

    return _enabled()


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
    from aegis.execution.fees import verify_fees_at_startup
    from aegis.monitor.forex_collector import forex_collector_enabled, send_forex_weekly_kpi_if_enabled
    from aegis.monitor.portfolio_collector import portfolio_collector_enabled
    from aegis.monitor.post_m1_deploy import maybe_post_m1_deploy
    from aegis.monitor.summary import send_daily_summary
    from aegis.monitor.telegram import notifier_from_config
    from aegis.monitor.telegram_bot import command_bot_enabled

    await verify_fees_at_startup(cfg)

    notifier = notifier_from_config(cfg)
    startup = "Aegis collector online - hourly scan+ingest active."
    if command_bot_enabled(cfg) and not once:
        startup += " Telegram /commands active on this host."
    if forex_collector_enabled():
        startup += " Forex event-fade paper active."
    if intraday_collector_enabled():
        startup += " Intraday Strategy C paper active."
    if portfolio_collector_enabled():
        startup += " Strategy A swing paper active."
    await notifier.send(startup)
    await notifier.close()

    bot_task: asyncio.Task | None = None
    forex_cal_task: asyncio.Task | None = None
    intraday_task: asyncio.Task | None = None
    if command_bot_enabled(cfg) and not once:
        bot_task = asyncio.create_task(_telegram_bot_sidecar(cfg), name="telegram-bot")
        logger.info("telegram command bot started alongside collector")
    if forex_collector_enabled() and not once:
        forex_cal_task = asyncio.create_task(_forex_calendar_sidecar(cfg), name="forex-calendar")
        logger.info("forex calendar alerts sidecar started (15m)")
    if intraday_collector_enabled() and not once:
        intraday_task = asyncio.create_task(_intraday_sidecar(cfg), name="intraday-paper")
        logger.info("intraday paper sidecar started (60s)")

    state = _read_collector_state(cfg)
    last_summary_day = state.get("last_summary_day")
    last_forex_kpi_week = state.get("last_forex_kpi_week")
    try:
        while True:
            await run_cycle(cfg)
            await _guarded(cfg, "post-m1-deploy", maybe_post_m1_deploy(cfg))

            now_s = time.time()
            due, day_key = summary_due(
                now_s, cfg.monitoring.daily_summary_hour_utc, last_summary_day
            )
            if due:
                await _guarded(cfg, "summary", send_daily_summary(cfg))
                last_summary_day = day_key
                state["last_summary_day"] = day_key
                _write_collector_state(cfg, state)

            kpi_due, week_key = forex_kpi_due(now_s, last_forex_kpi_week)
            if kpi_due:
                await _guarded(cfg, "forex-kpi", send_forex_weekly_kpi_if_enabled())
                last_forex_kpi_week = week_key
                state["last_forex_kpi_week"] = week_key
                _write_collector_state(cfg, state)

            if once:
                return
            delay = seconds_until_next_tick(now_s)
            logger.info("collector sleeping", extra={"seconds": round(delay)})
            await asyncio.sleep(delay)
    finally:
        for task in (bot_task, forex_cal_task, intraday_task):
            if task is not None:
                task.cancel()
                try:
                    await task
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
