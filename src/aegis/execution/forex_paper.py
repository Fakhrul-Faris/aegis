"""Forex demo paper executor (FX4).

Fills at bid/ask touch with ``forex_execution_model`` slippage, latency logging,
and requote skips. Persists to SQLite under ``venue=forex_demo``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime

from aegis.config_forex import ForexConfig
from aegis.core.interfaces import MarketData, OrderExecutor
from aegis.core.models import Fill, OrderRequest, Side, Venue
from aegis.data import db
from aegis.risk.forex_execution_model import (
    quote_from_mid,
    simulate_fill,
    slippage_pct,
)

logger = logging.getLogger(__name__)

FOREX_DEMO_VENUE = Venue.FOREX_DEMO.value


class ForexPaperExecutor(OrderExecutor):
    """Simulated forex fills for event-spike-fade demo paper."""

    def __init__(
        self,
        conn,
        market_data: MarketData,
        cfg: ForexConfig,
        *,
        near_event: bool = False,
    ):
        self._conn = conn
        self._md = market_data
        self._cfg = cfg
        self._near_event = near_event
        self._fills: dict[str, list[Fill]] = {}

    async def place_order(self, request: OrderRequest) -> str:
        bid, ask = await self._md.fetch_top_of_book(request.symbol)
        mid = (bid + ask) / 2.0
        ts_ms = int(time.time() * 1000)
        order_id = f"fxpaper-{uuid.uuid4().hex[:12]}"

        quote = quote_from_mid(
            request.symbol,
            mid,
            self._cfg.costs,
            ts_ms=ts_ms,
            event_multiplier=self._cfg.costs.event_spread_multiplier
            if self._near_event
            else 1.0,
        )
        fill_quote = simulate_fill(
            quote,
            request.side,
            self._cfg.costs,
            self._cfg.execution,
            near_event=self._near_event,
        )

        if fill_quote.skipped:
            db.insert_order(
                self._conn,
                client_order_id=request.client_order_id,
                venue_order_id=order_id,
                ts_ms=ts_ms,
                venue=FOREX_DEMO_VENUE,
                symbol=request.symbol,
                side=request.side.value,
                order_type=request.order_type.value,
                quantity=request.quantity,
                price=None,
                reduce_only=request.reduce_only,
                status="rejected",
                context_json=json.dumps(
                    {"mode": "forex_paper", "skip_reason": fill_quote.skip_reason}
                ),
            )
            raise RuntimeError(f"forex paper fill skipped: {fill_quote.skip_reason}")

        fill_price = fill_quote.fill_price
        commission = (
            self._cfg.costs.commission_usd_per_lot_round_turn
            * request.quantity
            / 2.0
        )
        slip = slippage_pct(request.side, fill_price, quote.bid, quote.ask)

        db.insert_order(
            self._conn,
            client_order_id=request.client_order_id,
            venue_order_id=order_id,
            ts_ms=ts_ms,
            venue=FOREX_DEMO_VENUE,
            symbol=request.symbol,
            side=request.side.value,
            order_type=request.order_type.value,
            quantity=request.quantity,
            price=fill_price,
            reduce_only=request.reduce_only,
            status="filled",
            context_json=json.dumps(
                {
                    "mode": "forex_paper",
                    "latency_ms": fill_quote.latency_ms,
                    "slippage_pips": fill_quote.slippage_pips,
                    "spread_pips": fill_quote.spread_pips,
                }
            ),
        )

        fill = Fill(
            venue=Venue.FOREX_DEMO,
            symbol=request.symbol,
            order_id=order_id,
            client_order_id=request.client_order_id,
            side=request.side,
            quantity=request.quantity,
            price=fill_price,
            fee=commission,
            is_maker=False,
            timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
        )
        self._fills[order_id] = [fill]
        db.insert_fill(
            self._conn,
            ts_ms=ts_ms,
            venue=FOREX_DEMO_VENUE,
            symbol=request.symbol,
            venue_order_id=order_id,
            client_order_id=request.client_order_id,
            side=request.side.value,
            quantity=request.quantity,
            price=fill_price,
            fee=commission,
            is_maker=False,
        )
        touch = quote.ask if request.side is Side.BUY else quote.bid
        db.insert_slippage(
            self._conn,
            ts_ms=ts_ms,
            venue=FOREX_DEMO_VENUE,
            symbol=request.symbol,
            side=request.side.value,
            expected_price=touch,
            fill_price=fill_price,
            slippage_pct=slip,
            gate_triggered=False,
        )
        logger.info(
            "forex paper fill",
            extra={
                "symbol": request.symbol,
                "side": request.side.value,
                "lots": request.quantity,
                "price": fill_price,
                "slip_pips": fill_quote.slippage_pips,
            },
        )
        return order_id

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        db.update_order_status(self._conn, order_id, "canceled")

    async def fetch_order_status(self, symbol: str, order_id: str) -> str:
        row = self._conn.execute(
            "SELECT status FROM orders WHERE venue_order_id = ?", (order_id,)
        ).fetchone()
        return row[0] if row else "unknown"

    async def fetch_fills(self, symbol: str, order_id: str) -> list[Fill]:
        return self._fills.get(order_id, [])
