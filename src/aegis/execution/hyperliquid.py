"""Hyperliquid market-data adapter (read-only portion of P0.2).

Uses the public ``/info`` REST endpoint - no signing required for market
data. Order placement (signed ``/exchange`` actions) arrives with the
two-leg execution work in P2.3.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from aegis.core.interfaces import MarketData
from aegis.core.models import Candle, Venue
from aegis.core.timeframes import timeframe_ms

logger = logging.getLogger(__name__)

MAINNET_URL = "https://api.hyperliquid.xyz"
TESTNET_URL = "https://api.hyperliquid-testnet.xyz"

# /info is weight-limited; modest concurrency is deliberate politeness.
_MAX_CONCURRENT_REQUESTS = 3


class HyperliquidMarketData(MarketData):
    def __init__(self, testnet: bool = False, client: httpx.AsyncClient | None = None):
        self._base_url = TESTNET_URL if testnet else MAINNET_URL
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)

    async def close(self) -> None:
        await self._client.aclose()

    async def _info(self, payload: dict[str, Any]) -> Any:
        async with self._semaphore:
            response = await self._client.post(f"{self._base_url}/info", json=payload)
        response.raise_for_status()
        return response.json()

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[Candle]:
        interval = timeframe_ms(timeframe)
        end_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
        start_ms = int(since.timestamp() * 1000) if since is not None else end_ms - limit * interval
        raw = await self._info(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": timeframe,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            }
        )
        candles = [
            Candle(
                venue=Venue.HYPERLIQUID,
                symbol=symbol,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(item["t"] / 1000, tz=UTC),
                open=float(item["o"]),
                high=float(item["h"]),
                low=float(item["l"]),
                close=float(item["c"]),
                volume=float(item["v"]),
            )
            for item in raw
        ]
        candles.sort(key=lambda c: c.open_time)
        return candles[:limit] if since is not None else candles[-limit:]

    async def fetch_top_of_book(self, symbol: str) -> tuple[float, float]:
        book = await self._info({"type": "l2Book", "coin": symbol})
        bids, asks = book["levels"]
        if not bids or not asks:
            raise RuntimeError(f"Empty order book for {symbol}")
        return float(bids[0]["px"]), float(asks[0]["px"])

    async def fetch_top_coins_by_volume(self, top_n: int) -> list[str]:
        """Active (non-delisted) perp coins ranked by 24h notional volume."""
        meta, asset_ctxs = await self._info({"type": "metaAndAssetCtxs"})
        ranked = sorted(
            (
                (float(ctx.get("dayNtlVlm", 0.0)), asset["name"])
                for asset, ctx in zip(meta["universe"], asset_ctxs, strict=True)
                if not asset.get("isDelisted")
            ),
            reverse=True,
        )
        coins = [name for _volume, name in ranked[:top_n]]
        logger.info(
            "hyperliquid universe ranked",
            extra={"total_assets": len(ranked), "selected": len(coins)},
        )
        return coins
