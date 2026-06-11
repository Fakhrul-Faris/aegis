"""Spread pipeline unit tests (fake executor)."""

import numpy as np
import pytest

from aegis.config import load_config
from aegis.core.interfaces import OrderExecutor
from aegis.core.models import Fill, OrderRequest, Side, Venue
from aegis.data import db
from aegis.execution.spread import SpreadExecutor, SpreadLeg, SpreadLegStatus
from aegis.execution.testnet_pairs import CAMPAIGN_PAIRS
from aegis.portfolio.spread_pipeline import reconcile_spread_fills
from aegis.risk.engine import RiskEngine


class FakeMd:
    async def fetch_candles(self, symbol, timeframe, since=None, limit=500):
        from datetime import UTC, datetime

        from aegis.core.models import Candle

        base = 100.0 + hash(symbol) % 10
        return [
            Candle(
                venue=Venue.HYPERLIQUID,
                symbol=symbol,
                timeframe="1h",
                open_time=datetime.fromtimestamp(1_700_000_000 + i * 3600, tz=UTC),
                open=base,
                high=base + 1,
                low=base - 1,
                close=base + 0.1 * (i % 3 - 1),
                volume=1e6,
            )
            for i in range(100)
        ]

    async def fetch_top_of_book(self, symbol: str):
        return 99.0, 101.0

    async def close(self):
        pass


class FakeHl(OrderExecutor):
    def __init__(self):
        self.orders = 0
        self._fills: dict[str, list[Fill]] = {}

    async def fetch_oracle_price(self, symbol: str) -> float:
        return 100.0

    async def place_order(self, request: OrderRequest) -> str:
        self.orders += 1
        return f"oid-{self.orders}"

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        pass

    async def fetch_order_status(self, symbol: str, order_id: str) -> str:
        return "filled"

    async def fetch_fills(self, symbol: str, order_id: str) -> list[Fill]:
        return self._fills.get(order_id, [])

    async def fetch_equity_usd(self) -> float:
        return 1000.0

    async def fetch_balances(self):
        return []

    async def fetch_positions(self):
        return []


@pytest.mark.asyncio
async def test_reconcile_persists_venue_fills(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    trading = FakeHl()
    from datetime import UTC, datetime

    trading._fills["oid-1"] = [
        Fill(
            venue=Venue.HYPERLIQUID,
            symbol="SOL",
            order_id="oid-1",
            client_order_id=None,
            side=Side.BUY,
            quantity=0.1,
            price=100.0,
            fee=0.01,
            is_maker=False,
            timestamp=datetime.now(tz=UTC),
        )
    ]
    db.insert_order(
        conn,
        client_order_id="s-leg1",
        venue_order_id="oid-1",
        ts_ms=1,
        venue="hyperliquid",
        symbol="SOL",
        side="buy",
        order_type="limit_ioc",
        quantity=0.1,
        price=100.0,
        reduce_only=False,
        status="filled",
    )
    from aegis.execution.spread import SpreadExecutionResult

    result = SpreadExecutionResult(leg1_order_id="oid-1")
    ok = await reconcile_spread_fills(conn, trading, result)
    assert ok
    assert db.count_fills(conn) == 1


def test_risk_approves_tiny_testnet_spread():
    cfg = load_config()
    risk = RiskEngine(cfg.risk)
    approval = risk.approve_trade(
        equity=1000.0,
        symbol="SOL",
        new_risk_r=0.01,
        open_risk_r=0.0,
        open_risk_by_symbol={},
        returns_by_symbol={"SOL": np.random.default_rng(0).normal(0, 0.01, 100)},
        side=Side.BUY,
        limit_price=100.2,
        best_bid=99.0,
        best_ask=101.0,
    )
    assert approval.approved


@pytest.mark.asyncio
async def test_ioc_spread_both_legs_fill():
    ex = FakeHl()
    spread = SpreadExecutor(ex, liquidity_rank=CAMPAIGN_PAIRS[0].liquidity_rank)
    result = await spread.execute_ioc_spread(
        SpreadLeg("DOGE", Side.SELL, 100.0, 99.0),
        SpreadLeg("SOL", Side.BUY, 0.1, 101.0),
    )
    assert result.leg2_status is SpreadLegStatus.FILLED
    assert not result.flattened
