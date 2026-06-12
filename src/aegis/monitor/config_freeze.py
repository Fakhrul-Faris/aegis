"""Paper config freeze (P3.1) — parameter changes restart the paper clock."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from aegis.config import AegisConfig, ConfigError

FREEZE_SCOPE = "strategy_a_paper"


def _paper_blob(cfg: AegisConfig) -> str:
    payload = {
        "strategy_a": {
            "ema_fast": cfg.strategy_a.ema_fast,
            "ema_slow": cfg.strategy_a.ema_slow,
            "rsi_period": cfg.strategy_a.rsi_period,
            "rsi_max_entry": cfg.strategy_a.rsi_max_entry,
            "take_profit_pct": cfg.strategy_a.take_profit_pct,
            "stop_loss_pct": cfg.strategy_a.stop_loss_pct,
            "signal_timeframe": cfg.strategy_a.signal_timeframe,
        },
        "risk_tiers": {
            "passive": cfg.risk.tiers.passive,
            "mid": cfg.risk.tiers.mid,
            "aggressive": cfg.risk.tiers.aggressive,
        },
        "regime": {
            "adx_trend_threshold": cfg.regime.adx_trend_threshold,
            "adx_sideways_threshold": cfg.regime.adx_sideways_threshold,
            "trend_size_factor": cfg.regime.trend_size_factor,
        },
        "scanner_volume_multiple": cfg.scanner.volume_multiple,
    }
    return json.dumps(payload, sort_keys=True)


def config_hash(cfg: AegisConfig) -> str:
    return hashlib.sha256(_paper_blob(cfg).encode()).hexdigest()[:16]


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config_freeze (
            scope       TEXT PRIMARY KEY,
            config_hash TEXT NOT NULL,
            frozen_at_ms INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def verify_or_freeze_paper_config(
    conn: sqlite3.Connection, cfg: AegisConfig, *, reset: bool = False
) -> None:
    """On first paper run, freeze. Later runs must match or fail loudly."""
    _ensure_table(conn)
    digest = config_hash(cfg)
    row = conn.execute(
        "SELECT config_hash FROM config_freeze WHERE scope = ?", (FREEZE_SCOPE,)
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
            (FREEZE_SCOPE, digest, int(time.time() * 1000)),
        )
        conn.commit()
        return

    if row[0] != digest:
        raise ConfigError(
            "Paper config changed since freeze. Any parameter change restarts the "
            "8-week paper clock (Concept §17). Re-freeze explicitly with "
            "aegis-portfolio --reset-config-freeze after documenting the change."
        )
