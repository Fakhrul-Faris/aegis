"""Hyperliquid intraday paper executor (Strategy C).

Simulated perp fills at touch + HL fee schedule. Persists under venue
``intraday_paper``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime

from aegis.config_intraday import IntradayCostsConfig
from aegis.core.interfaces import MarketData
from aegis.core.models import Fill, OrderRequest, Side, Venue
from aegis.data import db
from aegis.risk.slippage import limit_slippage_pct

logger = logging.getLogger(__name__)

INTRADAY_PAPER_VENUE = "intraday_paper"
STRATEGY_C = "C"


class IntradayPaperExecutor:
    """Simulated HL perp execution for Strategy C paper."""

    def __init__(
        self,
        conn,
        market_data: MarketData,
        costs: IntradayCostsConfig,
        *,
        symbol: str,
    ):
        self._conn = conn
        self._md = market_data
        self._costs = costs
        self._symbol = symbol
        self._fills: dict[str, list[Fill]] = {}

    async def place_order(self, request: OrderRequest) -> str:
        bid, ask = await self._md.fetch_top_of_book(self._symbol)
        ts_ms = int(time.time() * 1000)
        order_id = f"icpaper-{uuid.uuid4().hex[:12]}"

        if request.side is Side.BUY:
            fill_price = ask * (1 + self._costs.slippage_pct)
            fee_rate = self._costs.taker_fee
        else:
            fill_price = bid * (1 - self._costs.slippage_pct)
            fee_rate = self._costs.taker_fee

        fee = fill_price * request.quantity * fee_rate
        slip = limit_slippage_pct(request.side, fill_price, bid, ask)

        db.insert_order(
            self._conn,
            client_order_id=request.client_order_id,
            venue_order_id=order_id,
            ts_ms=ts_ms,
            venue=INTRADAY_PAPER_VENUE,
            symbol=self._symbol,
            side=request.side.value,
            order_type=request.order_type.value,
            quantity=request.quantity,
            price=fill_price,
            reduce_only=request.reduce_only,
            status="filled",
            context_json=json.dumps({"mode": "intraday_paper", "strategy": STRATEGY_C}),
        )
        fill = Fill(
            venue=Venue.HYPERLIQUID,
            symbol=self._symbol,
            order_id=order_id,
            client_order_id=request.client_order_id,
            side=request.side,
            quantity=request.quantity,
            price=fill_price,
            fee=fee,
            is_maker=False,
            timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
        )
        db.insert_fill(
            self._conn,
            ts_ms=ts_ms,
            venue=INTRADAY_PAPER_VENUE,
            order_id=order_id,
            symbol=self._symbol,
            side=request.side.value,
            price=fill_price,
            quantity=request.quantity,
            fee=fee,
            is_maker=False,
        )
        self._fills[order_id] = [fill]
        return order_id

    async def fetch_fills(self, order_id: str) -> list[Fill]:
        return self._fills.get(order_id, [])
