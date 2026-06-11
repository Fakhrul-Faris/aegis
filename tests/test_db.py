"""SQLite persistence tests (P0.3)."""

from datetime import UTC, datetime

from aegis.core.models import Candle, Venue
from aegis.core.timeframes import timeframe_ms
from aegis.data import db

H1 = timeframe_ms("1h")


def _candle(open_ms: int, close: float = 100.0) -> Candle:
    return Candle(
        venue=Venue.HYPERLIQUID,
        symbol="ETH",
        timeframe="1h",
        open_time=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1000.0,
    )


def test_schema_creates_all_tables(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "candles",
        "scanner_flags",
        "signals",
        "orders",
        "fills",
        "positions",
        "funding_payments",
        "slippage_log",
        "equity_snapshots",
        "regime_labels",
        "soak_log",
    }
    assert expected <= tables


def test_upsert_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    base = 1_700_000_400_000  # aligned to the hour
    candles = [_candle(base + i * H1) for i in range(5)]

    assert db.upsert_candles(conn, candles) == 5
    assert db.upsert_candles(conn, candles) == 0  # replace, not duplicate
    assert db.candle_count_total(conn) == 5


def test_upsert_updates_changed_values(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    base = 1_700_000_400_000
    db.upsert_candles(conn, [_candle(base, close=100.0)])
    db.upsert_candles(conn, [_candle(base, close=105.0)])

    loaded = db.load_candles(conn, Venue.HYPERLIQUID, "ETH", "1h")
    assert len(loaded) == 1
    assert loaded[0].close == 105.0


def test_last_candle_open_ms(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    assert db.last_candle_open_ms(conn, Venue.HYPERLIQUID, "ETH", "1h") is None

    base = 1_700_000_400_000
    db.upsert_candles(conn, [_candle(base), _candle(base + 3 * H1)])
    assert db.last_candle_open_ms(conn, Venue.HYPERLIQUID, "ETH", "1h") == base + 3 * H1


def test_find_gaps_detects_missing_bars(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    base = 1_700_000_400_000
    # bars at 0,1,2 then 5,6 -> gap covering bars 3 and 4
    db.upsert_candles(conn, [_candle(base + i * H1) for i in (0, 1, 2, 5, 6)])
    gaps = db.find_gaps(conn, Venue.HYPERLIQUID, "ETH", "1h", H1)
    assert gaps == [(base + 3 * H1, base + 5 * H1)]


def test_find_gaps_clean_series(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    base = 1_700_000_400_000
    db.upsert_candles(conn, [_candle(base + i * H1) for i in range(10)])
    assert db.find_gaps(conn, Venue.HYPERLIQUID, "ETH", "1h", H1) == []
