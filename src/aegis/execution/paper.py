"""Paper trading executor (P3.1) — simulated fills at touch + modeled costs.

Implements ``OrderExecutor`` without touching exchange APIs. Fills at the
touch price with configurable slippage and taker/maker fees from config.
Every order and fill is persisted to SQLite for reconciliation.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime

from aegis.config import ExchangeFees
from aegis.core.interfaces import MarketData, OrderExecutor
from aegis.core.models import Fill, OrderRequest, OrderType, Side, Venue
from aegis.data import db
from aegis.risk.slippage import limit_slippage_pct

logger = logging.getLogger(__name__)


class PaperExecutor(OrderExecutor):
    """Simulated Kraken spot execution for Strategy A paper mode."""

    def __init__(
        self,
        conn,
        market_data: MarketData,
        fees: ExchangeFees,
        *,
        slippage_pct: float = 0.0008,
        kraken_pair: str,
    ):
        self._conn = conn
        self._md = market_data
        self._fees = fees
        self._slippage = slippage_pct
        self._pair = kraken_pair
        self._fills: dict[str, list[Fill]] = {}

    async def place_order(self, request: OrderRequest) -> str:
        bid, ask = await self._md.fetch_top_of_book(self._pair)
        ts_ms = int(time.time() * 1000)
        order_id = f"paper-{uuid.uuid4().hex[:12]}"

        if request.side is Side.BUY:
            touch = ask
            fill_price = ask * (1 + self._slippage)
            is_maker = request.order_type is OrderType.LIMIT_POST_ONLY
        else:
            touch = bid
            fill_price = bid * (1 - self._slippage)
            is_maker = request.order_type is OrderType.LIMIT_POST_ONLY

        fee_rate = self._fees.maker_fee if is_maker else self._fees.taker_fee
        fee = fill_price * request.quantity * fee_rate
        slip = limit_slippage_pct(request.side, fill_price, bid, ask)

        db.insert_order(
            self._conn,
            client_order_id=request.client_order_id,
            venue_order_id=order_id,
            ts_ms=ts_ms,
            venue=Venue.KRAKEN.value,
            symbol=request.symbol,
            side=request.side.value,
            order_type=request.order_type.value,
            quantity=request.quantity,
            price=fill_price,
            reduce_only=request.reduce_only,
            status="filled",
            context_json='{"mode": "paper"}',
        )

        fill = Fill(
            venue=Venue.KRAKEN,
            symbol=request.symbol,
            order_id=order_id,
            client_order_id=request.client_order_id,
            side=request.side,
            quantity=request.quantity,
            price=fill_price,
            fee=fee,
            is_maker=is_maker,
            timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
        )
        self._fills[order_id] = [fill]
        db.insert_fill(
            self._conn,
            ts_ms=ts_ms,
            venue=Venue.KRAKEN.value,
            symbol=request.symbol,
            venue_order_id=order_id,
            client_order_id=request.client_order_id,
            side=request.side.value,
            quantity=request.quantity,
            price=fill_price,
            fee=fee,
            is_maker=is_maker,
        )
        db.insert_slippage(
            self._conn,
            ts_ms=ts_ms,
            venue=Venue.KRAKEN.value,
            symbol=request.symbol,
            side=request.side.value,
            expected_price=touch,
            fill_price=fill_price,
            slippage_pct=slip,
            gate_triggered=False,
        )
        logger.info(
            "paper fill",
            extra={
                "symbol": request.symbol,
                "side": request.side.value,
                "qty": request.quantity,
                "price": fill_price,
                "fee": fee,
            },
        )
        return order_id

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        db.update_order_status(self._conn, order_id, "canceled")

    async def fetch_order_status(self, symbol: str, order_id: str) -> str:
        return "filled"

    async def fetch_fills(self, symbol: str, order_id: str) -> list[Fill]:
        return self._fills.get(order_id, [])
