"""Progress report tests."""

from dataclasses import replace
from datetime import UTC, datetime

from aegis.config import load_config
from aegis.data import db
from aegis.monitor.progress import build_progress_report, build_milestones


def _cfg(**kwargs):
    return replace(load_config(env_file=None), **kwargs)


def test_progress_includes_milestones(tmp_path):
    cfg = _cfg(sqlite_path=str(tmp_path / "t.sqlite"))
    db.connect(tmp_path / "t.sqlite").close()
    report = build_progress_report(cfg)
    assert "M0" in report and "M3" in report
    assert "Strategy B cointegration closed" in report
    assert "NO-GO" in report
    assert "aegis-testnet-soak" in report


def test_m1_wait_when_span_short(tmp_path):
    cfg = _cfg(sqlite_path=str(tmp_path / "t.sqlite"))
    conn = db.connect(tmp_path / "t.sqlite")
    db.insert_market_snapshots(
        conn,
        1_700_000_000_000,
        [
            {
                "coin_id": "btc",
                "symbol": "BTC",
                "price_usd": 1.0,
                "vol24h_usd": 1.0,
                "market_cap_usd": 1.0,
                "price_change_1h_pct": 0.0,
                "price_change_24h_pct": 0.0,
            }
        ],
    )
    milestones = build_milestones(cfg, conn)
    conn.close()
    m1 = next(m for m in milestones if m.code == "M1")
    assert m1.icon == "⏳"
