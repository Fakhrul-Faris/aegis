"""Paper executor and swing pipeline tests."""

import pytest

from aegis.config import ExchangeFees
from aegis.core.models import OrderRequest, OrderType, Side, Venue
from aegis.data import db
from aegis.data.scanner_join import has_anomaly_in_window
from aegis.execution.paper import PaperExecutor
from aegis.strategy.swing import SwingTier, classify_tier


class FakeMd:
    def __init__(self, bid: float = 99.0, ask: float = 101.0):
        self.bid = bid
        self.ask = ask

    async def fetch_top_of_book(self, symbol: str):
        return self.bid, self.ask

    async def fetch_candles(self, symbol, timeframe, since=None, limit=500):
        return []

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_paper_executor_persists_fill(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    md = FakeMd()
    fees = ExchangeFees(maker_fee=0.0025, taker_fee=0.004)
    paper = PaperExecutor(conn, md, fees, kraken_pair="BTC/USDT")
    oid = await paper.place_order(
        OrderRequest(
            venue=Venue.KRAKEN,
            symbol="BTC",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
        )
    )
    assert oid.startswith("paper-")
    assert db.count_fills(conn, Venue.KRAKEN.value) == 1


def test_classify_tier_with_anomaly():
    assert classify_tier(True, True) is SwingTier.AGGRESSIVE
    assert classify_tier(True, False) is SwingTier.PASSIVE


def test_scanner_join_case_insensitive(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    bar_open = 1_700_000_000_000
    db.insert_scanner_flag(
        conn,
        ts_ms=bar_open + 1000,
        coin_id="solana",
        symbol="sol",
        vol_1h_usd=1e6,
        vol_avg_1h_usd=1e5,
        volume_multiple=5.0,
        price_change_1h_pct=1.0,
        price_change_24h_pct=2.0,
        variant="price_flat",
        on_kraken=True,
        context_json="{}",
    )
    assert has_anomaly_in_window(conn, "SOL", bar_open, "4h")


def test_sqlite_cached_market_data_reads_db(tmp_path):
    import asyncio
    import time
    from datetime import UTC, datetime

    from aegis.core.models import Candle, Venue
    from aegis.execution.sqlite_market_data import SqliteCachedMarketData

    conn = db.connect(tmp_path / "t.sqlite")
    try:
        db.upsert_candles(
            conn,
            [
                Candle(
                    venue=Venue.KRAKEN,
                    symbol="MANA/USDT",
                    timeframe="4h",
                    open_time=datetime.fromtimestamp(time.time(), tz=UTC),
                    open=0.3,
                    high=0.31,
                    low=0.29,
                    close=0.305,
                    volume=1000.0,
                )
            ],
        )
        md = SqliteCachedMarketData(conn, Venue.KRAKEN)
        candles = asyncio.run(md.fetch_candles("MANA/USDT", "4h", limit=5))
        assert len(candles) == 1
        bid, ask = asyncio.run(md.fetch_top_of_book("MANA/USDT"))
        assert bid < 0.305 < ask
    finally:
        conn.close()
