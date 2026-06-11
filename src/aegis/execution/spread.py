"""Two-leg spread execution — maker-then-IOC (P2.3, Concept §8).

Leg 1: post-only on the more liquid symbol (tighter spread / higher volume).
Leg 2: IOC on fill with a price bound. Any miss → immediately flatten leg 1
at market and log the full event. This is the execution path Strategy B would
have used; it remains available if the strategy pivots to basket/stat-arb.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from aegis.core.interfaces import OrderExecutor
from aegis.core.models import OrderRequest, OrderType, Side, Venue

logger = logging.getLogger(__name__)


class SpreadLegStatus(StrEnum):
    PENDING = "pending"
    RESTING = "resting"
    FILLED = "filled"
    CANCELED = "canceled"
    FLATTENED = "flattened"
    FAILED = "failed"


@dataclass(frozen=True)
class SpreadLeg:
    symbol: str
    side: Side
    quantity: float
    limit_price: float


@dataclass
class SpreadExecutionResult:
    leg1_order_id: str | None = None
    leg2_order_id: str | None = None
    leg1_status: SpreadLegStatus = SpreadLegStatus.PENDING
    leg2_status: SpreadLegStatus = SpreadLegStatus.PENDING
    flattened: bool = False
    error: str | None = None


class SpreadExecutor:
    def __init__(
        self,
        executor: OrderExecutor,
        *,
        max_leg2_slippage_pct: float = 0.0008,
        liquidity_rank: dict[str, float] | None = None,
    ):
        self._executor = executor
        self._max_leg2_slippage = max_leg2_slippage_pct
        self._liquidity = liquidity_rank or {}

    def _order_liquid_first(
        self, leg_a: SpreadLeg, leg_b: SpreadLeg
    ) -> tuple[SpreadLeg, SpreadLeg]:
        rank_a = self._liquidity.get(leg_a.symbol, 0.0)
        rank_b = self._liquidity.get(leg_b.symbol, 0.0)
        return (leg_a, leg_b) if rank_a >= rank_b else (leg_b, leg_a)

    async def execute(
        self,
        leg_a: SpreadLeg,
        leg_b: SpreadLeg,
        *,
        venue: Venue = Venue.HYPERLIQUID,
    ) -> SpreadExecutionResult:
        result = SpreadExecutionResult()
        first, second = self._order_liquid_first(leg_a, leg_b)

        try:
            leg1_id = await self._executor.place_order(
                OrderRequest(
                    venue=venue,
                    symbol=first.symbol,
                    side=first.side,
                    order_type=OrderType.LIMIT_POST_ONLY,
                    quantity=first.quantity,
                    price=first.limit_price,
                )
            )
            result.leg1_order_id = leg1_id
            status = await self._executor.fetch_order_status(first.symbol, leg1_id)
            if status != "filled":
                # Resting maker — in live, we'd wait for fill event; for testnet
                # proof we treat open as resting and return (caller polls/cancels).
                result.leg1_status = (
                    SpreadLegStatus.FILLED if status == "filled" else SpreadLegStatus.RESTING
                )
                if result.leg1_status is SpreadLegStatus.RESTING:
                    return result

            result.leg1_status = SpreadLegStatus.FILLED
            ioc_price = second.limit_price * (
                1 + self._max_leg2_slippage
                if second.side is Side.BUY
                else 1 - self._max_leg2_slippage
            )
            leg2_id = await self._executor.place_order(
                OrderRequest(
                    venue=venue,
                    symbol=second.symbol,
                    side=second.side,
                    order_type=OrderType.LIMIT_IOC,
                    quantity=second.quantity,
                    price=ioc_price,
                )
            )
            result.leg2_order_id = leg2_id
            leg2_status = await self._executor.fetch_order_status(second.symbol, leg2_id)
            if leg2_status == "filled":
                result.leg2_status = SpreadLegStatus.FILLED
                return result

            # Leg 2 missed — flatten leg 1 immediately (Concept §8).
            await self._executor.place_order(
                OrderRequest(
                    venue=venue,
                    symbol=first.symbol,
                    side=Side.SELL if first.side is Side.BUY else Side.BUY,
                    order_type=OrderType.MARKET,
                    quantity=first.quantity,
                    reduce_only=True,
                )
            )
            result.flattened = True
            result.leg2_status = SpreadLegStatus.FAILED
            result.leg1_status = SpreadLegStatus.FLATTENED
            logger.warning(
                "spread leg2 miss — leg1 flattened",
                extra={"leg1": first.symbol, "leg2": second.symbol},
            )
        except Exception as exc:
            result.error = repr(exc)
            result.leg1_status = SpreadLegStatus.FAILED
            logger.exception("spread execution failed")
        return result
