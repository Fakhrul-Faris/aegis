"""Config freeze and ops CLI tests."""

from dataclasses import replace

import pytest

from aegis.config import AegisConfig, ConfigError, load_config
from aegis.data import db
from aegis.monitor.config_freeze import config_hash, verify_or_freeze_paper_config
from aegis.monitor.m1_check import _collection_span_hours


def _cfg(**overrides) -> AegisConfig:
    base = load_config()
    if not overrides:
        return base
    return replace(base, **overrides)


def test_config_freeze_blocks_changes(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    cfg = _cfg()
    verify_or_freeze_paper_config(conn, cfg)
    with pytest.raises(ConfigError, match="Paper config changed"):
        verify_or_freeze_paper_config(
            conn,
            _cfg(strategy_a=replace(cfg.strategy_a, ema_fast=8)),
        )


def test_config_freeze_reset_allows_change(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    cfg = _cfg()
    verify_or_freeze_paper_config(conn, cfg)
    changed = _cfg(strategy_a=replace(cfg.strategy_a, ema_fast=8))
    verify_or_freeze_paper_config(conn, changed, reset=True)
    verify_or_freeze_paper_config(conn, changed)


def test_config_hash_stable():
    cfg = _cfg()
    assert config_hash(cfg) == config_hash(_cfg())


def test_m1_collection_span_hours(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    assert _collection_span_hours(conn) is None

    start = 1_700_000_000_000
    end = start + 72 * 3_600_000
    db.insert_market_snapshots(
        conn,
        start,
        [
            {
                "coin_id": "btc",
                "symbol": "BTC",
                "price_usd": 50_000.0,
                "vol24h_usd": 1e10,
                "market_cap_usd": 1e12,
                "price_change_1h_pct": 0.0,
                "price_change_24h_pct": 0.0,
            }
        ],
    )
    db.insert_market_snapshots(
        conn,
        end,
        [
            {
                "coin_id": "btc",
                "symbol": "BTC",
                "price_usd": 51_000.0,
                "vol24h_usd": 1e10,
                "market_cap_usd": 1e12,
                "price_change_1h_pct": 0.0,
                "price_change_24h_pct": 0.0,
            }
        ],
    )
    assert _collection_span_hours(conn) == pytest.approx(72.0)
