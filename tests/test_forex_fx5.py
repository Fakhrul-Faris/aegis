"""FX5 unit tests — scorecard, KPI, calendar alerts."""

import time

from aegis.config_forex import load_forex_config
from aegis.data import db
from aegis.data.forex_calendar import seed_economic_calendar
from aegis.execution.forex_paper import FOREX_DEMO_VENUE
from aegis.monitor.forex_calendar_alerts import build_calendar_alerts
from aegis.monitor.forex_kpi import build_forex_weekly_kpi, format_forex_weekly_kpi
from aegis.monitor.forex_scorecard import build_forex_daily_scorecard, format_forex_daily_scorecard


def test_forex_daily_scorecard_empty_db(tmp_path):
    cfg = load_forex_config("config/forex.yaml")
    db_path = tmp_path / "demo.sqlite"
    conn = db.connect(db_path)
    try:
        seed_economic_calendar(conn)
        now_ms = int(time.time() * 1000)
        card = build_forex_daily_scorecard(conn, cfg, now_ms)
        assert card.equity_now_usd == cfg.demo.equity_usd
        assert card.closed_trades_cum == 0
        text = format_forex_daily_scorecard(card, conn)
        assert "Event Spike Fade" in text
        assert "Health:" in text
    finally:
        conn.close()


def test_forex_weekly_kpi_empty(tmp_path):
    cfg = load_forex_config("config/forex.yaml")
    conn = db.connect(tmp_path / "demo.sqlite")
    try:
        kpi = build_forex_weekly_kpi(conn, cfg)
        text = format_forex_weekly_kpi(kpi)
        assert "Aegis Forex KPI" in text
        assert kpi.trades_cum == 0
    finally:
        conn.close()


def test_calendar_alerts_no_crash(tmp_path):
    cfg = load_forex_config("config/forex.yaml")
    conn = db.connect(tmp_path / "demo.sqlite")
    try:
        seed_economic_calendar(conn, year_start=2025, year_end=2027)
        msgs = build_calendar_alerts(cfg, conn, db_path=str(tmp_path / "demo.sqlite"))
        assert isinstance(msgs, list)
    finally:
        conn.close()


def test_equity_snapshot_venue_constant():
    assert FOREX_DEMO_VENUE == "forex_demo"
