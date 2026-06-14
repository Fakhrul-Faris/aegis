"""Forex FX3 recipe config freeze — event spike fade (H11b-4)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from aegis.config import ConfigError
from aegis.config_forex import ForexConfig

FOREX_FREEZE_SCOPE = "forex_event_spike_fade"


def forex_recipe_blob(cfg: ForexConfig) -> str:
    esf = cfg.event_spike_fade
    payload = {
        "active_strategy": cfg.active_strategy,
        "event_spike_fade": {
            "enabled": esf.enabled,
            "pairs": list(esf.pairs),
            "timeframe": esf.timeframe,
            "spike_wait_minutes": esf.spike_wait_minutes,
            "spike_fade_minutes": esf.spike_fade_minutes,
            "spike_retrace_pct": esf.spike_retrace_pct,
            "min_spike_pips": esf.min_spike_pips,
            "target_mode": esf.target_mode,
            "flat_by_hour_utc": esf.flat_by_hour_utc,
            "risk_pct": esf.risk_pct,
            "lots": esf.lots,
        },
        "calendar": {
            "event_spike_tiers": cfg.calendar.event_spike_tiers,
            "event_spike_currencies": cfg.calendar.event_spike_currencies,
        },
        "gates": {
            "backtest_min_trades_per_window": cfg.scm.backtest_min_trades_per_window,
            "backtest_min_win_rate": cfg.scm.backtest_min_win_rate,
            "demo_min_win_rate": cfg.scm.demo_min_win_rate,
        },
    }
    return json.dumps(payload, sort_keys=True)


def forex_config_hash(cfg: ForexConfig) -> str:
    return hashlib.sha256(forex_recipe_blob(cfg).encode()).hexdigest()[:16]


def verify_or_freeze_forex_config(
    conn: sqlite3.Connection,
    cfg: ForexConfig,
    *,
    reset: bool = False,
) -> str:
    """Freeze FX3 recipe on first pass; block silent parameter drift."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config_freeze (
            scope       TEXT PRIMARY KEY,
            config_hash TEXT NOT NULL,
            frozen_at_ms INTEGER NOT NULL
        )
        """
    )
    digest = forex_config_hash(cfg)
    row = conn.execute(
        "SELECT config_hash FROM config_freeze WHERE scope = ?", (FOREX_FREEZE_SCOPE,)
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
            (FOREX_FREEZE_SCOPE, digest, int(time.time() * 1000)),
        )
        conn.commit()
        return digest

    if row[0] != digest:
        raise ConfigError(
            "Forex recipe changed since FX3 freeze. Document the change and re-freeze "
            "with aegis-backtest-forex-fx3 --reset-freeze."
        )
    return digest


def params_from_esf_config(cfg: ForexConfig):
    """Build HypothesisParams from frozen event_spike_fade config block."""
    from aegis.strategy.forex_hypotheses import HypothesisParams

    esf = cfg.event_spike_fade
    return HypothesisParams(
        spike_wait_minutes=esf.spike_wait_minutes,
        spike_fade_minutes=esf.spike_fade_minutes,
        spike_retrace_pct=esf.spike_retrace_pct,
        min_spike_pips=esf.min_spike_pips,
        target_mode=esf.target_mode,
    )
