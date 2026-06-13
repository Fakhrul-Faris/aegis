"""Daily scorecard tests."""

from datetime import UTC, datetime

from aegis.data import db
from aegis.monitor.daily_scorecard import (
    PAPER_STARTING_EQUITY_USD,
    build_daily_scorecard,
    format_daily_scorecard,
    format_pnl_usd,
)

# Wednesday 2026-06-10 18:00 UTC
NOW_MS = int(datetime(2026, 6, 10, 18, 0, tzinfo=UTC).timestamp() * 1000)
DAY_START_MS = int(datetime(2026, 6, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)


def test_format_pnl_usd():
    assert format_pnl_usd(0.42) == "+$0.42"
    assert format_pnl_usd(-1.5) == "-$1.50"
    assert format_pnl_usd(0.0) == "$0.00"


def test_scorecard_flat_day(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    card = build_daily_scorecard(conn, NOW_MS)
    text = format_daily_scorecard(card, conn, NOW_MS)

    assert card.pnl_today_usd == 0.0
    assert card.closed_today == 0
    assert card.equity_now_usd == PAPER_STARTING_EQUITY_USD
    assert "PATH TO LIVE" in text
    assert "Win rate today: no trades" in text
    assert "Scanner (24h):  DOWN" in text


def test_scorecard_winning_day(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")

    db.insert_equity_snapshot(
        conn,
        ts_ms=DAY_START_MS - 3_600_000,
        venue="paper",
        equity_usd=1000.0,
        mode="paper",
    )
    db.insert_equity_snapshot(
        conn,
        ts_ms=NOW_MS - 60_000,
        venue="paper",
        equity_usd=1005.50,
        mode="paper",
    )
    pos_id = db.insert_paper_position(
        conn,
        opened_ts_ms=DAY_START_MS + 3_600_000,
        symbol="BTC",
        quantity=0.01,
        entry_price=50_000.0,
        risk_amount_usd=10.0,
        tier="aggressive",
        context={"tier": "aggressive"},
    )
    db.close_paper_position(
        conn,
        pos_id,
        closed_ts_ms=DAY_START_MS + 7_200_000,
        exit_price=51_000.0,
        realized_pnl=5.50,
        r_multiple=0.55,
        exit_reason="take_profit",
    )
    db.insert_market_snapshots(
        conn,
        NOW_MS - 1000,
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

    card = build_daily_scorecard(conn, NOW_MS)
    text = format_daily_scorecard(card, conn, NOW_MS)

    assert card.pnl_today_usd == 5.50
    assert card.closed_pnl_today_usd == 5.50
    assert card.wins_today == 1
    assert card.losses_today == 0
    assert card.closed_today == 1
    assert card.all_time_pnl_usd == 5.50
    assert "P&L today:      +$5.50" in text
    assert "1W / 0L (100%)" in text
    assert "Scanner (24h):  OK" in text
