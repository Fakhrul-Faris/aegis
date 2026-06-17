"""Fly collector hooks for intraday Strategy C paper (ID2).

Runs as a 60s sidecar inside ``aegis-collector`` on Fly.io — same SQLite
volume as crypto/forex. Disabled when ``AEGIS_INTRADAY_ENABLED=0``.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def intraday_collector_enabled() -> bool:
    if os.environ.get("AEGIS_INTRADAY_ENABLED", "0") in ("0", "false", "False"):
        return False
    try:
        from aegis.config_intraday import load_intraday_config

        cfg = load_intraday_config()
        return cfg.momentum_day.enabled
    except Exception:
        return False


async def run_intraday_paper_if_enabled() -> dict | None:
    if not intraday_collector_enabled():
        return None
    from aegis.portfolio.intraday_paper_run import run_intraday_paper_cycle

    result = await run_intraday_paper_cycle()
    logger.info("intraday paper cycle", extra=result)
    return result
