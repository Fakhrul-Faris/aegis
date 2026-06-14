"""Fly collector hooks for forex demo paper (FX5).

Runs inside ``aegis-collector`` on Fly.io — same Telegram secrets and SQLite
volume as crypto. Disabled when ``AEGIS_FOREX_ENABLED=0``.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def forex_collector_enabled() -> bool:
    if os.environ.get("AEGIS_FOREX_ENABLED", "1") in ("0", "false", "False"):
        return False
    try:
        from aegis.config_forex import load_forex_config

        cfg = load_forex_config()
        return cfg.active_strategy == "event_spike_fade" and cfg.event_spike_fade.enabled
    except Exception:
        return False


async def run_forex_paper_if_enabled() -> dict | None:
    if not forex_collector_enabled():
        return None
    from aegis.portfolio.forex_paper_run import run_forex_paper_cycle

    result = await run_forex_paper_cycle()
    logger.info(
        "forex paper cycle",
        extra={
            "ingest": result.get("ingest_inserted"),
            "fade": result.get("fade"),
        },
    )
    return result


async def run_forex_calendar_alerts_if_enabled() -> list[str]:
    if not forex_collector_enabled():
        return []
    from aegis.monitor.forex_calendar_alerts import send_calendar_alerts

    return await send_calendar_alerts()


async def send_forex_weekly_kpi_if_enabled() -> str | None:
    if not forex_collector_enabled():
        return None
    from aegis.monitor.forex_kpi import send_forex_weekly_kpi

    return await send_forex_weekly_kpi()
