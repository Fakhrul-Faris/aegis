"""SQLite-backed market data for intraday paper — avoids HL /info on every 60s tick.

Candles come from the local DB (filled by throttled ingest). Marks for paper
fills use the latest stored bar close with a tiny synthetic spread.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from aegis.core.interfaces import MarketData
from aegis.core.models import Candle, Venue
from aegis.data import db

_SPREAD_HALF = 0.00005  # 0.5 bps synthetic bid/ask around last close


class SqliteIntradayMarketData(MarketData):
    """Read-only marks from SQLite — no live Hyperliquid calls in the paper loop."""

    def __init__(self, conn: sqlite3.Connection, *, venue: Venue = Venue.HYPERLIQUID):
        self._conn = conn
        self._venue = venue

    async def close(self) -> None:
        return None

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[Candle]:
        if since is not None:
            start_ms = int(since.timestamp() * 1000)
            candles = db.load_candles(
                self._conn, self._venue, symbol, timeframe, start_ms=start_ms
            )
            return candles[:limit]
        return db.load_candles_recent(self._conn, self._venue, symbol, timeframe, limit)

    async def fetch_top_of_book(self, symbol: str) -> tuple[float, float]:
        candles = db.load_candles_recent(self._conn, self._venue, symbol, "15m", 1)
        if not candles:
            raise RuntimeError(f"No cached 15m candles for {symbol} — run intraday ingest")
        mid = candles[-1].close
        return mid * (1 - _SPREAD_HALF), mid * (1 + _SPREAD_HALF)
