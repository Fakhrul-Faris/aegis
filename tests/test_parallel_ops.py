"""Breaker drill and KPI report tests."""

import pytest

from aegis.config import load_config
from aegis.data import db
from aegis.monitor.kpi import build_weekly_kpi, format_weekly_kpi, kpi_due
from aegis.risk.breaker_drill import run_breaker_drill


def test_breaker_drill_passes():
    cfg = load_config(env_file=None)
    result = run_breaker_drill(cfg)
    assert result.passed


def test_kpi_empty_db(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    kpi = build_weekly_kpi(conn, now_ms=1_700_000_000_000)
    text = format_weekly_kpi(kpi)
    assert "Equity: $1,000.00" in text
    assert "Trades (wk/cum): 0 / 0" in text
    assert "n/a (need closed trades)" in text


def test_kpi_with_closed_trades(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    now = 1_700_000_000_000
    conn.execute(
        """
        INSERT INTO positions
            (opened_ts_ms, closed_ts_ms, strategy, venue, symbol, side, quantity,
             entry_price, exit_price, realized_pnl, r_multiple, context_json)
        VALUES (?, ?, 'A', 'kraken', 'BTC', 'long', 1, 100, 106, 6, 1.2, '{}')
        """,
        (now - 3_600_000, now - 1000),
    )
    conn.commit()
    kpi = build_weekly_kpi(conn, now_ms=now)
    assert kpi.trades_cum == 1
    assert kpi.expectancy_r == pytest.approx(1.2)


def test_kpi_due_once_per_week():
    # 2026-06-14 is a Sunday UTC
    sunday = 1_750_000_000.0  # approximate - use known Sunday
    from datetime import UTC, datetime

    dt = datetime(2026, 6, 14, 17, 0, tzinfo=UTC)
    ts = dt.timestamp()
    due, week = kpi_due(ts, kpi_weekday=6, last_sent_week=None)
    assert due and week.startswith("2026-W")

    due2, _ = kpi_due(ts + 3600, kpi_weekday=6, last_sent_week=week)
    assert not due2
