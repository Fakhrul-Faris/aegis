"""Portfolio brain — one cycle loop (P2.4, Concept §5).

Orchestrates: fee verification → equity update → breaker checks → signal
ranking → risk approval → dispatch. Strategies produce signals; this layer
decides what actually trades.

Phase 2 ships the skeleton with Strategy A paper signal logging on Kraken
4h data. Live order dispatch wires in as testnet/paper modes mature.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time

import numpy as np

from aegis.config import load_config
from aegis.core.models import Venue
from aegis.data import db
from aegis.execution import build_market_data
from aegis.execution.fees import verify_fees_at_startup
from aegis.log import setup_logging
from aegis.risk.breakers import BreakerState
from aegis.risk.engine import RiskEngine
from aegis.strategy.regime import detect_regime, strategy_a_active
from aegis.strategy.swing import evaluate_entry_at_bar, precompute_indicators

logger = logging.getLogger(__name__)


def _insert_equity_snapshot(conn, equity: float, mode: str) -> None:
    db.insert_equity_snapshot(
        conn,
        ts_ms=int(time.time() * 1000),
        venue="portfolio",
        equity_usd=equity,
        mode=mode,
    )


def _insert_signal(
    conn,
    *,
    strategy: str,
    venue: str,
    symbol: str,
    tier: str,
    taken: bool,
    skip_reason: str | None,
    context: dict,
) -> None:
    ts_ms = int(time.time() * 1000)
    conn.execute(
        """
        INSERT INTO signals
            (ts_ms, strategy, venue, symbol, direction, tier, taken, skip_reason, context_json)
        VALUES (?, ?, ?, ?, 'long', ?, ?, ?, ?)
        """,
        (ts_ms, strategy, venue, symbol, tier, int(taken), skip_reason, json.dumps(context)),
    )
    conn.commit()


async def run_cycle(cfg, conn, risk: RiskEngine, equity: float = 1000.0) -> None:
    """One portfolio cycle: scan Strategy A symbols, log signals, snapshot equity."""
    alerts = risk.update_equity(equity)
    for msg in alerts:
        logger.critical(msg)

    if risk.state.killed or risk.state.halted_daily:
        logger.warning("cycle skipped — breaker active")
        return

    md = build_market_data(Venue.KRAKEN)
    try:
        for symbol in cfg.data.kraken_symbols:
            base = symbol.split("/")[0]
            candles = await md.fetch_candles(symbol, cfg.strategy_a.signal_timeframe, limit=250)
            if len(candles) < 210:
                continue
            highs = np.array([c.high for c in candles])
            lows = np.array([c.low for c in candles])
            closes = np.array([c.close for c in candles])
            regime = detect_regime(highs, lows, closes, cfg.regime)
            if not strategy_a_active(regime):
                _insert_signal(
                    conn,
                    strategy="A",
                    venue="kraken",
                    symbol=base,
                    tier="",
                    taken=False,
                    skip_reason=f"regime_{regime.value}",
                    context={"regime": regime.value},
                )
                continue

            fast, slow, rs = precompute_indicators(closes, cfg.strategy_a)
            bar = len(closes) - 1
            entry = evaluate_entry_at_bar(bar, closes, fast, slow, rs, cfg.strategy_a)
            if entry is None:
                continue

            _insert_signal(
                conn,
                strategy="A",
                venue="kraken",
                symbol=base,
                tier=entry.tier.value,
                taken=True,
                skip_reason=None,
                context={"rsi": entry.rsi, "regime": regime.value, "mode": cfg.mode},
            )
            logger.info(
                "strategy A signal",
                extra={"symbol": base, "tier": entry.tier.value, "rsi": entry.rsi},
            )
    finally:
        await md.close()

    _insert_equity_snapshot(conn, equity, cfg.mode)


async def run_once(cfg_path: str = "config/config.yaml") -> None:
    cfg = load_config(cfg_path)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    await verify_fees_at_startup(cfg)

    conn = db.connect(cfg.sqlite_path)
    risk = RiskEngine(cfg.risk, BreakerState())
    try:
        await run_cycle(cfg, conn, risk)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis portfolio brain (one cycle)")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument(
        "--loop",
        type=int,
        metavar="SECONDS",
        help="run continuously (4h strategy → default 3600s poll)",
    )
    args = parser.parse_args()

    if args.loop:
        while True:
            asyncio.run(run_once(args.config))
            time.sleep(args.loop)
    else:
        asyncio.run(run_once(args.config))


if __name__ == "__main__":
    main()
