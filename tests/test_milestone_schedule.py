"""Milestone schedule and path-to-live tests."""

from datetime import UTC, datetime

from aegis.data import db
from aegis.monitor.milestone_schedule import (
    M1_GATE_TARGET_UTC,
    build_path_to_live,
    format_path_to_live_section,
    m1_db_passes,
    soak_end_utc,
)


def test_soak_end_after_start():
    assert soak_end_utc() > M1_GATE_TARGET_UTC


def test_path_to_live_before_m1(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    now = int(datetime(2026, 6, 12, 12, 0, tzinfo=UTC).timestamp() * 1000)
    path = build_path_to_live(conn, now)
    assert not path.m1_passed
    assert "M1" in path.next_gate
    assert path.days_to_live_earliest > 0
    lines = format_path_to_live_section(path)
    assert any("Days to live" in line for line in lines)


def test_m1_db_passes_with_hourly_snapshots(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    now_ms = int(datetime(2026, 6, 13, 18, 0, tzinfo=UTC).timestamp() * 1000)
    start = now_ms - 73 * 3_600_000
    for i in range(73):
        db.insert_market_snapshots(
            conn,
            start + i * 3_600_000,
            [
                {
                    "coin_id": "btc",
                    "symbol": "BTC",
                    "price_usd": 1.0,
                    "vol24h_usd": 1e9,
                    "market_cap_usd": 1e12,
                    "price_change_1h_pct": 0.0,
                    "price_change_24h_pct": 0.0,
                }
            ],
        )
    assert m1_db_passes(conn, now_ms=now_ms)
