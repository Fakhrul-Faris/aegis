"""Kraken market-data adapter via ccxt (read-only portion of P0.2).

Order placement arrives only at Strategy A's go-live (Concept §7 gate);
until then Kraken is a data source.
"""

from __future__ import annotations

from datetime import UTC, datetime

import ccxt.async_support as ccxt

from aegis.core.interfaces import MarketData
from aegis.core.models import Candle, Venue


class KrakenMarketData(MarketData):
    def __init__(self, exchange: ccxt.kraken | None = None):
        self._exchange = exchange or ccxt.kraken({"enableRateLimit": True})

    async def close(self) -> None:
        await self._exchange.close()

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[Candle]:
        since_ms = int(since.timestamp() * 1000) if since is not None else None
        # Kraken's OHLC endpoint caps at 720 rows per call.
        rows = await self._exchange.fetch_ohlcv(
            symbol, timeframe, since=since_ms, limit=min(limit, 720)
        )
        return [
            Candle(
                venue=Venue.KRAKEN,
                symbol=symbol,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]

    async def fetch_tradable_bases(self) -> set[str]:
        """Base assets of active spot markets - used by the scanner's on_kraken tag."""
        markets = await self._exchange.load_markets()
        return {
            market["base"]
            for market in markets.values()
            if market.get("spot") and market.get("active") is not False
        }

    async def fetch_top_of_book(self, symbol: str) -> tuple[float, float]:
        book = await self._exchange.fetch_order_book(symbol, limit=1)
        if not book["bids"] or not book["asks"]:
            raise RuntimeError(f"Empty order book for {symbol}")
        return float(book["bids"][0][0]), float(book["asks"][0][0])
