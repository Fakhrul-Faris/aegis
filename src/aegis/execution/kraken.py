"""Kraken market-data adapter via ccxt (read-only portion of P0.2).

Order placement arrives only at Strategy A's go-live (Concept §7 gate);
until then Kraken is a data source.
"""

from __future__ import annotations

from datetime import UTC, datetime

import ccxt.async_support as ccxt

from aegis.core.interfaces import AccountState, MarketData, OrderExecutor
from aegis.core.models import Balance, Candle, Fill, OrderRequest, Position, Venue


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


class KrakenTrading(OrderExecutor, AccountState):
    """Balances are real; order placement is a DELIBERATE stub.

    Kraken trading unlocks only at Strategy A's promotion gate (Concept §7).
    Until then the read-only API key stays read-only, and these stubs make
    any premature order attempt fail loudly instead of silently trading.
    """

    def __init__(self, api_key: str, api_secret: str, exchange: ccxt.kraken | None = None):
        self._exchange = exchange or ccxt.kraken(
            {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}
        )

    async def close(self) -> None:
        await self._exchange.close()

    async def place_order(self, request: OrderRequest) -> str:
        raise NotImplementedError(
            "Kraken order placement is gated behind Strategy A promotion (M8). "
            "This stub exists so the interface is uniform, not so it gets used."
        )

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        raise NotImplementedError("Kraken trading gated behind Strategy A promotion (M8)")

    async def fetch_order_status(self, symbol: str, order_id: str) -> str:
        raise NotImplementedError("Kraken trading gated behind Strategy A promotion (M8)")

    async def fetch_fills(self, symbol: str, order_id: str) -> list[Fill]:
        raise NotImplementedError("Kraken trading gated behind Strategy A promotion (M8)")

    async def fetch_equity_usd(self) -> float:
        balances = await self.fetch_balances()
        usd_like = {"USD", "ZUSD", "USDT", "USDC"}
        return sum(b.total for b in balances if b.asset in usd_like)

    async def fetch_balances(self) -> list[Balance]:
        balance = await self._exchange.fetch_balance()
        return [
            Balance(
                venue=Venue.KRAKEN,
                asset=asset,
                total=float(total),
                available=float((balance.get("free") or {}).get(asset) or 0.0),
            )
            for asset, total in (balance.get("total") or {}).items()
            if total
        ]

    async def fetch_positions(self) -> list[Position]:
        return []  # spot venue: holdings are balances, not positions
