"""Intraday Strategy C config freeze (ID2 proof clock)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from aegis.config import ConfigError
from aegis.config_intraday import IntradayConfig

INTRADAY_FREEZE_SCOPE = "intraday_momentum_day"


def intraday_recipe_blob(cfg: IntradayConfig) -> str:
    md = cfg.momentum_day
    payload = {
        "active_strategy": cfg.active_strategy,
        "momentum_day": {
            "enabled": md.enabled,
            "symbols": list(md.symbols),
            "signal_timeframe": md.signal_timeframe,
            "regime_timeframe": md.regime_timeframe,
            "scanner_required": md.scanner_required,
            "breakout_lookback_bars": md.breakout_lookback_bars,
            "stop_loss_pct": md.stop_loss_pct,
            "take_profit_pct": md.take_profit_pct,
            "risk_pct": md.risk_pct,
            "flat_by_hour_utc": md.flat_by_hour_utc,
            "max_open_positions": md.max_open_positions,
            "max_trades_per_day": md.max_trades_per_day,
            "daily_profit_cap_r": md.daily_profit_cap_r,
            "daily_loss_cap_r": md.daily_loss_cap_r,
        },
        "costs": {
            "maker_fee": cfg.costs.maker_fee,
            "taker_fee": cfg.costs.taker_fee,
            "slippage_pct": cfg.costs.slippage_pct,
            "min_order_usd": cfg.costs.min_order_usd,
        },
    }
    return json.dumps(payload, sort_keys=True)


def intraday_config_hash(cfg: IntradayConfig) -> str:
    return hashlib.sha256(intraday_recipe_blob(cfg).encode()).hexdigest()[:16]


def verify_or_freeze_intraday_config(
    conn: sqlite3.Connection,
    cfg: IntradayConfig,
    *,
    reset: bool = False,
) -> str:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config_freeze (
            scope       TEXT PRIMARY KEY,
            config_hash TEXT NOT NULL,
            frozen_at_ms INTEGER NOT NULL
        )
        """
    )
    digest = intraday_config_hash(cfg)
    row = conn.execute(
        "SELECT config_hash FROM config_freeze WHERE scope = ?", (INTRADAY_FREEZE_SCOPE,)
    ).fetchone()

    if reset or row is None:
        conn.execute(
            """
            INSERT INTO config_freeze (scope, config_hash, frozen_at_ms)
            VALUES (?, ?, ?)
            ON CONFLICT (scope) DO UPDATE SET
                config_hash = excluded.config_hash,
                frozen_at_ms = excluded.frozen_at_ms
            """,
            (INTRADAY_FREEZE_SCOPE, digest, int(time.time() * 1000)),
        )
        conn.commit()
        return digest

    if row[0] != digest:
        raise ConfigError(
            f"intraday config changed since freeze ({row[0]} != {digest}); "
            "use --reset-config-freeze to start a new proof clock"
        )
    return digest
