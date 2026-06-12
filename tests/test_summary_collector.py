"""Daily summary and collector scheduling tests (P0.5)."""

from datetime import UTC, datetime

from aegis.collector import seconds_until_next_tick, summary_due
from aegis.data import db
from aegis.monitor.summary import build_summary

NOW = 1_700_000_400_000


def test_summary_reports_counts(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.insert_market_snapshots(
        conn,
        NOW - 1000,
        [
            {
                "coin_id": "btc",
                "symbol": "BTC",
                "price_usd": 50_000.0,
                "vol24h_usd": 1e10,
                "market_cap_usd": 1e12,
                "price_change_1h_pct": 0.1,
                "price_change_24h_pct": 1.0,
            }
        ],
    )
    db.insert_scanner_flag(
        conn,
        ts_ms=NOW - 1000,
        coin_id="btc",
        symbol="BTC",
        vol_1h_usd=1e9,
        vol_avg_1h_usd=1e8,
        volume_multiple=10.0,
        price_change_1h_pct=6.0,
        price_change_24h_pct=12.0,
        variant="price_up_5",
        on_kraken=True,
        context_json="{}",
    )

    text = build_summary(conn, now_ms=NOW)
    assert "Snapshots (24h): 1" in text
    assert "price_up_5: 1" in text
    assert "Flags (all time): 1" in text
    assert "Paper: equity $1,000.00" in text
    assert "WARNING" not in text


def test_summary_warns_on_silent_scanner(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    text = build_summary(conn, now_ms=NOW)
    assert "WARNING" in text


def test_seconds_until_next_tick():
    # 10:00:00 exactly -> next tick at 11:00:00 + offset 90s
    on_the_hour = 3600.0 * 100
    assert seconds_until_next_tick(on_the_hour) == 3600 + 90
    # 10:59:00 -> 60s to the hour + 90 offset
    assert seconds_until_next_tick(on_the_hour + 3540) == 60 + 90


def test_summary_due_once_per_day():
    hour = 16
    ts = datetime(2026, 6, 10, 16, 1, tzinfo=UTC).timestamp()

    due, day_key = summary_due(ts, hour, last_sent_day=None)
    assert due and day_key == "2026-06-10"

    # Same day, later hour: already sent.
    due2, _ = summary_due(ts + 3600, hour, last_sent_day="2026-06-10")
    assert not due2

    # Before the summary hour: not yet due.
    early = datetime(2026, 6, 11, 8, 0, tzinfo=UTC).timestamp()
    due3, _ = summary_due(early, hour, last_sent_day="2026-06-10")
    assert not due3

    # Next day at the hour: due again.
    next_day = datetime(2026, 6, 11, 16, 30, tzinfo=UTC).timestamp()
    due4, day4 = summary_due(next_day, hour, last_sent_day="2026-06-10")
    assert due4 and day4 == "2026-06-11"
