"""Ingestion tests with a fake venue (P0.3) - no network involved."""

import asyncio
from datetime import UTC, datetime

from aegis.core.interfaces import MarketData
from aegis.core.models import Candle, Venue
from aegis.core.timeframes import timeframe_ms
from aegis.data import db
from aegis.data.ingest import _cached_hl_symbols, _resolve_hl_universe, ingest_series

H1 = timeframe_ms("1h")
BASE = 1_700_000_400_000  # hour-aligned epoch ms


class FakeVenue(MarketData):
    """Serves a deterministic in-memory candle series like a real venue."""

    def __init__(self, candles: dict[int, Candle]):
        self.candles = candles
        self.calls = 0

    async def fetch_candles(self, symbol, timeframe, since=None, limit=500):
        self.calls += 1
        since_ms = int(since.timestamp() * 1000) if since else 0
        selected = sorted(
            (c for ms, c in self.candles.items() if ms >= since_ms),
            key=lambda c: c.open_time,
        )
        return selected[:limit]

    async def fetch_top_of_book(self, symbol):
        return (99.0, 101.0)


def _series(start_ms: int, count: int, skip: set[int] = frozenset()) -> dict[int, Candle]:
    out = {}
    for i in range(count):
        if i in skip:
            continue
        ms = start_ms + i * H1
        out[ms] = Candle(
            venue=Venue.HYPERLIQUID,
            symbol="ETH",
            timeframe="1h",
            open_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=10.0,
        )
    return out


def test_initial_backfill_and_resume(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    now_ms = BASE + 48 * H1  # "now" = 48 bars after BASE
    venue = FakeVenue(_series(BASE, 48))

    stats = asyncio.run(
        ingest_series(
            venue,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=2,
            now_ms=now_ms,
        )
    )
    assert stats.inserted == 48
    assert stats.gaps_unfilled == 0

    # Second run: nothing new -> nothing inserted.
    stats2 = asyncio.run(
        ingest_series(
            venue,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=2,
            now_ms=now_ms,
        )
    )
    assert stats2.inserted == 0


def test_open_candle_is_excluded(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    # 10 closed bars plus one whose interval has not elapsed yet
    now_ms = BASE + 10 * H1 + H1 // 2
    venue = FakeVenue(_series(BASE, 11))

    asyncio.run(
        ingest_series(
            venue,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=2,
            now_ms=now_ms,
        )
    )
    assert db.last_candle_open_ms(conn, Venue.HYPERLIQUID, "ETH", "1h") == BASE + 9 * H1


def test_backward_extension_deepens_existing_series(tmp_path):
    """Raising initial_backfill_days must deepen an existing DB, not just
    roll it forward - the screening/backtest history depends on it."""
    conn = db.connect(tmp_path / "t.sqlite")
    now_ms = BASE + 96 * H1
    venue = FakeVenue(_series(BASE, 96))

    # First run with a shallow setting: only the last 24h get stored.
    asyncio.run(
        ingest_series(
            venue,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=1,
            now_ms=now_ms,
        )
    )
    assert db.first_candle_open_ms(conn, Venue.HYPERLIQUID, "ETH", "1h") == BASE + 72 * H1

    # Config deepened to 4 days: the same series must extend BACKWARD.
    stats = asyncio.run(
        ingest_series(
            venue,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=4,
            now_ms=now_ms,
        )
    )
    assert stats.inserted == 72
    assert db.first_candle_open_ms(conn, Venue.HYPERLIQUID, "ETH", "1h") == BASE
    assert stats.gaps_unfilled == 0
    assert db.candle_count_total(conn) == 96


def test_backward_extension_stops_when_venue_has_no_older_data(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    now_ms = BASE + 48 * H1
    venue = FakeVenue(_series(BASE, 48))  # venue history starts at BASE

    asyncio.run(
        ingest_series(
            venue,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=2,
            now_ms=now_ms,
        )
    )
    calls_before = venue.calls
    # Ask for 30 days the venue cannot serve: one probe, no loop, no crash.
    stats = asyncio.run(
        ingest_series(
            venue,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=30,
            now_ms=now_ms,
        )
    )
    assert stats.inserted == 0
    assert venue.calls <= calls_before + 2  # catch-up check + single probe
    assert db.candle_count_total(conn) == 48


def test_gap_repair_refetches_missing_bars(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    now_ms = BASE + 24 * H1

    # First pass sees a venue outage: bars 10-12 missing.
    gappy = FakeVenue(_series(BASE, 24, skip={10, 11, 12}))
    stats = asyncio.run(
        ingest_series(
            gappy,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=1,
            now_ms=now_ms,
        )
    )
    assert stats.gaps_found >= 1
    assert stats.gaps_unfilled >= 1  # venue still missing them

    # Venue recovered: repair pass fills the hole.
    healed = FakeVenue(_series(BASE, 24))
    stats2 = asyncio.run(
        ingest_series(
            healed,
            conn,
            Venue.HYPERLIQUID,
            "ETH",
            "1h",
            initial_backfill_days=1,
            now_ms=now_ms,
        )
    )
    assert stats2.gaps_unfilled == 0
    assert db.candle_count_total(conn) == 24


def test_cached_hl_symbols_ranks_by_volume(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    for symbol, vol in (("BTC", 100.0), ("ETH", 50.0), ("SOL", 200.0)):
        ms = BASE
        db.upsert_candles(
            conn,
            [
                Candle(
                    venue=Venue.HYPERLIQUID,
                    symbol=symbol,
                    timeframe="1h",
                    open_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
                    open=1.0,
                    high=1.0,
                    low=1.0,
                    close=1.0,
                    volume=vol,
                )
            ],
        )
    assert _cached_hl_symbols(conn, 2) == ["SOL", "BTC"]


class _UniverseFails(FakeVenue):
    async def fetch_top_coins_by_volume(self, top_n: int) -> list[str]:
        raise RuntimeError("502 Bad Gateway")


def test_resolve_hl_universe_falls_back_to_cache(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.upsert_candles(
        conn,
        [
            Candle(
                venue=Venue.HYPERLIQUID,
                symbol="ETH",
                timeframe="1h",
                open_time=datetime.fromtimestamp(BASE / 1000, tz=UTC),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=10.0,
            )
        ],
    )
    coins = asyncio.run(_resolve_hl_universe(_UniverseFails({}), conn, top_n=5))
    assert coins == ["ETH"]
