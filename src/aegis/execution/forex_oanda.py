"""OANDA v20 market data adapter (FX4 demo).

Practice REST API for candles and pricing. Falls back to SQLite/Yahoo when
credentials are absent so FX4 infra can be tested offline.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from aegis.config import Secrets
from aegis.core.interfaces import MarketData
from aegis.core.models import Candle, Venue
from aegis.risk.forex_execution_model import pair_to_oanda, quote_from_mid

logger = logging.getLogger(__name__)

_PRACTICE_BASE = "https://api-fxpractice.oanda.com/v3"
_LIVE_BASE = "https://api-fxtrade.oanda.com/v3"

_GRANULARITY = {
    "1h": "H1",
    "15m": "M15",
    "4h": "H4",
}


def _parse_oanda_time(ts: str) -> datetime:
    # OANDA returns "2024-01-02T12:00:00.000000000Z"
    clean = ts.replace("Z", "+00:00")
    if "." in clean:
        head, tail = clean.split(".", 1)
        frac, tz = tail.split("+", 1)
        clean = f"{head}.{frac[:6]}+{tz}"
    return datetime.fromisoformat(clean).astimezone(UTC)


class OandaMarketData(MarketData):
    def __init__(
        self,
        secrets: Secrets,
        *,
        costs_cfg=None,
        conn=None,
    ):
        self._token = secrets.oanda_api_token
        self._account_id = secrets.oanda_account_id
        self._practice = secrets.oanda_practice
        self._base = _PRACTICE_BASE if self._practice else _LIVE_BASE
        self._costs = costs_cfg
        self._conn = conn

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise ValueError("OANDA_API_TOKEN not set")
        return {"Authorization": f"Bearer {self._token}"}

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[Candle]:
        if self._token:
            return await self._fetch_oanda_candles(symbol, timeframe, since=since, limit=limit)
        return self._fetch_sqlite_candles(symbol, timeframe, since=since, limit=limit)

    async def _fetch_oanda_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        since: datetime | None,
        limit: int,
    ) -> list[Candle]:
        gran = _GRANULARITY.get(timeframe)
        if gran is None:
            raise ValueError(f"Unsupported timeframe for OANDA: {timeframe!r}")

        params: dict[str, str | int] = {"granularity": gran, "price": "M", "count": limit}
        if since is not None:
            params["from"] = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        instrument = pair_to_oanda(symbol)
        url = f"{self._base}/instruments/{instrument}/candles"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            payload = resp.json()

        out: list[Candle] = []
        for row in payload.get("candles", []):
            if not row.get("complete", True):
                continue
            mid = row["mid"]
            out.append(
                Candle(
                    venue=Venue.FOREX_DEMO,
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=_parse_oanda_time(row["time"]),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=float(row.get("volume", 0)),
                )
            )
        return out

    def _fetch_sqlite_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        since: datetime | None,
        limit: int,
    ) -> list[Candle]:
        if self._conn is None:
            return []
        since_ms = int(since.timestamp() * 1000) if since else None
        rows = self._conn.execute(
            """
            SELECT open_time_ms, open, high, low, close, volume
            FROM candles
            WHERE venue = ? AND symbol = ? AND timeframe = ?
              AND (? IS NULL OR open_time_ms >= ?)
            ORDER BY open_time_ms DESC
            LIMIT ?
            """,
            (
                Venue.FOREX_DEMO.value,
                symbol,
                timeframe,
                since_ms,
                since_ms,
                limit,
            ),
        ).fetchall()
        candles = [
            Candle(
                venue=Venue.FOREX_DEMO,
                symbol=symbol,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(r[0] / 1000, tz=UTC),
                open=r[1],
                high=r[2],
                low=r[3],
                close=r[4],
                volume=r[5],
            )
            for r in reversed(rows)
        ]
        return candles

    async def fetch_top_of_book(self, symbol: str) -> tuple[float, float]:
        if self._token and self._account_id:
            instrument = pair_to_oanda(symbol)
            url = f"{self._base}/accounts/{self._account_id}/pricing"
            params = {"instruments": instrument}
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=self._headers(), params=params)
                resp.raise_for_status()
                prices = resp.json().get("prices", [])
            if prices:
                bid = float(prices[0]["bids"][0]["price"])
                ask = float(prices[0]["asks"][0]["price"])
                return bid, ask

        # Fallback: last stored close + modeled spread
        candles = self._fetch_sqlite_candles(symbol, "1h", since=None, limit=1)
        if not candles and self._conn is not None:
            candles = self._load_research_close(symbol)
        if not candles:
            # Last resort for FX4 smoke: synthetic mid from config spread only
            if self._costs is not None:
                mid = 1.1000 if symbol.startswith("EUR") else 1.2500
                q = quote_from_mid(
                    symbol, mid, self._costs, ts_ms=int(datetime.now(tz=UTC).timestamp() * 1000)
                )
                return q.bid, q.ask
            raise ValueError(f"No quote source for {symbol}")
        mid = candles[-1].close
        if self._costs is None:
            return mid * 0.9999, mid * 1.0001
        q = quote_from_mid(
            symbol, mid, self._costs, ts_ms=int(datetime.now(tz=UTC).timestamp() * 1000)
        )
        return q.bid, q.ask

    def _load_research_close(self, symbol: str) -> list[Candle]:
        row = self._conn.execute(
            """
            SELECT open_time_ms, open, high, low, close, volume
            FROM candles
            WHERE venue = ? AND symbol = ? AND timeframe = '1h'
            ORDER BY open_time_ms DESC LIMIT 1
            """,
            (Venue.FOREX.value, symbol),
        ).fetchone()
        if not row:
            return []
        return [
            Candle(
                venue=Venue.FOREX_DEMO,
                symbol=symbol,
                timeframe="1h",
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
        ]
