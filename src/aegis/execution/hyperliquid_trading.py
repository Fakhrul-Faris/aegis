"""Hyperliquid order execution + account state via ccxt (signed portion of P0.2).

Market data stays on the lightweight httpx adapter (`hyperliquid.py`) - the
collector on Fly.io depends on it and needs no signing. This module carries
everything that requires the wallet key: orders, cancels, fills, balances,
positions. ccxt handles the EIP-712 action signing; we never roll our own
crypto.

The maker-then-IOC two-leg sequencing lives in P2.3 - this layer only knows
how to express single orders faithfully (post-only, IOC, reduce-only,
isolated margin is venue default for our account).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import ccxt.async_support as ccxt

from aegis.core.interfaces import AccountState, OrderExecutor
from aegis.core.models import Balance, Fill, OrderRequest, OrderType, Position, Side, Venue

logger = logging.getLogger(__name__)


# Hyperliquid perps quote and settle in USDC under ccxt's unified symbols.
def _market_symbol(coin: str) -> str:
    return f"{coin}/USDC:USDC"


_STATUS_MAP = {
    "open": "open",
    "closed": "filled",
    "canceled": "canceled",
    "rejected": "rejected",
    "expired": "canceled",
}


class HyperliquidTrading(OrderExecutor, AccountState):
    """One authenticated ccxt client serving both executor and account roles."""

    def __init__(
        self,
        wallet_address: str,
        private_key: str,
        testnet: bool = True,
        exchange: Any | None = None,
    ):
        if exchange is None:
            exchange = ccxt.hyperliquid(
                {
                    "walletAddress": wallet_address,
                    "privateKey": private_key,
                    "enableRateLimit": True,
                }
            )
            if testnet:
                exchange.set_sandbox_mode(True)
        self._exchange = exchange
        self._markets_loaded = False

    async def close(self) -> None:
        await self._exchange.close()

    async def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            await self._exchange.load_markets()
            self._markets_loaded = True

    # ---- OrderExecutor -------------------------------------------------

    async def place_order(self, request: OrderRequest) -> str:
        await self._ensure_markets()
        symbol = _market_symbol(request.symbol)

        params: dict[str, Any] = {}
        if request.order_type is OrderType.LIMIT_POST_ONLY:
            order_type = "limit"
            params["postOnly"] = True
        elif request.order_type is OrderType.LIMIT_IOC:
            order_type = "limit"
            params["timeInForce"] = "IOC"
        elif request.order_type is OrderType.MARKET:
            order_type = "market"
        else:
            # Venue-native stops are attached by the two-leg executor (P2.3).
            raise NotImplementedError(f"order type {request.order_type} arrives with P2.3")

        if request.reduce_only:
            params["reduceOnly"] = True
        if request.client_order_id:
            params["clientOrderId"] = request.client_order_id

        amount = float(self._exchange.amount_to_precision(symbol, request.quantity))
        price = (
            float(self._exchange.price_to_precision(symbol, request.price))
            if request.price is not None
            else None
        )

        order = await self._exchange.create_order(
            symbol, order_type, request.side.value, amount, price, params
        )
        order_id = str(order["id"])
        logger.info(
            "order placed",
            extra={
                "venue": "hyperliquid",
                "symbol": request.symbol,
                "side": request.side.value,
                "type": request.order_type.value,
                "qty": amount,
                "price": price,
                "order_id": order_id,
            },
        )
        return order_id

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        await self._ensure_markets()
        await self._exchange.cancel_order(order_id, _market_symbol(symbol))
        logger.info(
            "order canceled",
            extra={"venue": "hyperliquid", "symbol": symbol, "order_id": order_id},
        )

    async def fetch_order_status(self, symbol: str, order_id: str) -> str:
        await self._ensure_markets()
        order = await self._exchange.fetch_order(order_id, _market_symbol(symbol))
        return _STATUS_MAP.get(order.get("status"), "unknown")

    async def fetch_fills(self, symbol: str, order_id: str) -> list[Fill]:
        await self._ensure_markets()
        trades = await self._exchange.fetch_my_trades(_market_symbol(symbol))
        fills = []
        for trade in trades:
            if str(trade.get("order")) != order_id:
                continue
            fee = trade.get("fee") or {}
            fills.append(
                Fill(
                    venue=Venue.HYPERLIQUID,
                    symbol=symbol,
                    order_id=order_id,
                    client_order_id=trade.get("clientOrderId"),
                    side=Side(trade["side"]),
                    quantity=float(trade["amount"]),
                    price=float(trade["price"]),
                    fee=float(fee.get("cost") or 0.0),
                    is_maker=trade.get("takerOrMaker") == "maker",
                    timestamp=datetime.fromtimestamp(trade["timestamp"] / 1000, tz=UTC),
                )
            )
        return fills

    # ---- AccountState --------------------------------------------------

    async def fetch_equity_usd(self) -> float:
        await self._ensure_markets()
        balance = await self._exchange.fetch_balance()
        # Perp account value (margin + unrealized PnL) - the risk-sizing base.
        return float(balance["info"]["marginSummary"]["accountValue"])

    async def fetch_balances(self) -> list[Balance]:
        await self._ensure_markets()
        balance = await self._exchange.fetch_balance()
        out = []
        for asset, total in (balance.get("total") or {}).items():
            if not total:
                continue
            available = (balance.get("free") or {}).get(asset, 0.0)
            out.append(
                Balance(
                    venue=Venue.HYPERLIQUID,
                    asset=asset,
                    total=float(total),
                    available=float(available or 0.0),
                )
            )
        return out

    async def fetch_positions(self) -> list[Position]:
        await self._ensure_markets()
        raw = await self._exchange.fetch_positions()
        positions = []
        for item in raw:
            quantity = float(item.get("contracts") or 0.0)
            if quantity == 0:
                continue
            positions.append(
                Position(
                    venue=Venue.HYPERLIQUID,
                    symbol=str(item["symbol"]).split("/")[0],
                    side=Side.BUY if item.get("side") == "long" else Side.SELL,
                    quantity=quantity,
                    entry_price=float(item.get("entryPrice") or 0.0),
                    unrealized_pnl=float(item.get("unrealizedPnl") or 0.0),
                    isolated_margin=(
                        float(item["collateral"])
                        if item.get("marginMode") == "isolated" and item.get("collateral")
                        else None
                    ),
                )
            )
        return positions
