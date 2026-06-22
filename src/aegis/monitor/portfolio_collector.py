"""Fly collector hook for Strategy A swing paper (M5/M6).

Runs inside ``aegis-collector`` hourly after ingest so scanner flags and
Kraken candles are fresh. Disabled when ``AEGIS_PORTFOLIO_ENABLED=0``.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def portfolio_collector_enabled() -> bool:
    if os.environ.get("AEGIS_PORTFOLIO_ENABLED", "1") in ("0", "false", "False"):
        return False
    try:
        from aegis.config import load_config

        return load_config().mode == "paper"
    except Exception:
        return False


async def run_portfolio_paper_if_enabled() -> None:
    if not portfolio_collector_enabled():
        return
    from aegis.config import load_config
    from aegis.data import db
    from aegis.monitor.config_freeze import verify_or_freeze_paper_config
    from aegis.portfolio.paper_swing import run_paper_cycle
    from aegis.risk.breakers import BreakerState
    from aegis.risk.engine import RiskEngine

    cfg = load_config()
    conn = db.connect(cfg.sqlite_path)
    try:
        verify_or_freeze_paper_config(conn, cfg)
        risk = RiskEngine(cfg.risk, BreakerState())
        await run_paper_cycle(cfg, conn, risk)
    finally:
        conn.close()
    logger.info("strategy A paper cycle")
