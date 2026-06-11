"""P2.3 spread executor tests with fake OrderExecutor."""

import pytest

from aegis.core.interfaces import OrderExecutor
from aegis.core.models import Fill, OrderRequest, Side
from aegis.execution.spread import SpreadExecutor, SpreadLeg, SpreadLegStatus


class FakeExecutor(OrderExecutor):
    def __init__(self, leg2_fills: bool = True):
        self.orders: list[OrderRequest] = []
        self.leg2_fills = leg2_fills
        self._status_by_order: dict[str, str] = {}

    async def place_order(self, request: OrderRequest) -> str:
        self.orders.append(request)
        oid = f"oid-{len(self.orders)}"
        if request.order_type.value == "limit_post_only":
            self._status_by_order[oid] = "filled"
        elif request.order_type.value == "limit_ioc":
            prior_post_only = any(o.order_type.value == "limit_post_only" for o in self.orders[:-1])
            prior_market = any(o.order_type.value == "market" for o in self.orders[:-1])
            ioc_index = sum(1 for o in self.orders if o.order_type.value == "limit_ioc")
            if prior_market or prior_post_only or ioc_index > 1:
                self._status_by_order[oid] = "filled" if self.leg2_fills else "canceled"
            else:
                self._status_by_order[oid] = "filled"
        else:
            self._status_by_order[oid] = "filled"
        return oid

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        pass

    async def fetch_order_status(self, symbol: str, order_id: str) -> str:
        return self._status_by_order.get(order_id, "open")

    async def fetch_fills(self, symbol: str, order_id: str) -> list[Fill]:
        return []


@pytest.mark.asyncio
async def test_maker_then_ioc_both_fill():
    ex = FakeExecutor(leg2_fills=True)
    spread = SpreadExecutor(ex, liquidity_rank={"BTC": 10, "ETH": 5})
    result = await spread.execute(
        SpreadLeg("ETH", Side.BUY, 0.1, 3000.0),
        SpreadLeg("BTC", Side.SELL, 0.01, 60000.0),
    )
    assert result.leg1_status is SpreadLegStatus.FILLED
    assert result.leg2_status is SpreadLegStatus.FILLED
    assert ex.orders[0].symbol == "BTC"  # more liquid leg first
    assert ex.orders[0].order_type.value == "limit_post_only"


@pytest.mark.asyncio
async def test_leg2_miss_flattens_leg1():
    ex = FakeExecutor(leg2_fills=False)
    spread = SpreadExecutor(ex, liquidity_rank={"BTC": 10, "ETH": 5})
    result = await spread.execute(
        SpreadLeg("ETH", Side.BUY, 0.1, 3000.0),
        SpreadLeg("BTC", Side.SELL, 0.01, 60000.0),
    )
    assert result.flattened
    assert result.leg1_status is SpreadLegStatus.FLATTENED
    assert ex.orders[-1].order_type.value == "market"


@pytest.mark.asyncio
async def test_drill_leg2_miss_flattens_within_budget():
    ex = FakeExecutor(leg2_fills=False)
    spread = SpreadExecutor(ex, liquidity_rank={"BTC": 10, "ETH": 5})
    result = await spread.execute_leg2_miss_drill(
        SpreadLeg("ETH", Side.SELL, 0.1, 6000.0),
        SpreadLeg("BTC", Side.BUY, 0.01, 61000.0),
    )
    assert result.flattened
    assert result.flatten_elapsed_ms is not None
    assert result.flatten_elapsed_ms < 1000
    assert ex.orders[0].symbol == "BTC"
    assert ex.orders[0].order_type.value == "limit_ioc"
