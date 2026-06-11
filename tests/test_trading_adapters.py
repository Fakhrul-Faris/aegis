"""P0.2 trading adapters: request mapping, status normalization, and the
Kraken stub gate - all against a fake ccxt client, no network."""

import pytest

from aegis.core.models import OrderRequest, OrderType, Side, Venue
from aegis.execution.hyperliquid_trading import HyperliquidTrading
from aegis.execution.kraken import KrakenTrading


class FakeCcxt:
    def __init__(self):
        self.created: list[tuple] = []
        self.canceled: list[tuple] = []
        self.order_status = "open"
        self.trades: list[dict] = []
        self.balance = {
            "info": {"marginSummary": {"accountValue": "987.65"}},
            "total": {"USDC": 987.65},
            "free": {"USDC": 900.0},
        }
        self.spot_balance = {"total": {"USDC": 0.0}, "free": {}}

    async def load_markets(self):
        return {}

    async def close(self):
        pass

    def amount_to_precision(self, symbol, amount):
        return f"{amount:.5f}"

    def price_to_precision(self, symbol, price):
        return f"{price:.0f}"

    async def create_order(self, symbol, order_type, side, amount, price, params):
        self.created.append((symbol, order_type, side, amount, price, params))
        return {"id": "oid-1"}

    async def cancel_order(self, order_id, symbol):
        self.canceled.append((order_id, symbol))

    async def fetch_order(self, order_id, symbol):
        return {"id": order_id, "status": self.order_status}

    async def fetch_my_trades(self, symbol):
        return self.trades

    async def fetch_balance(self, params=None):
        if params and params.get("type") == "spot":
            return self.spot_balance
        return self.balance

    async def fetch_positions(self):
        return [
            {
                "symbol": "ETH/USDC:USDC",
                "side": "long",
                "contracts": 0.5,
                "entryPrice": 2500.0,
                "unrealizedPnl": 12.5,
                "marginMode": "isolated",
                "collateral": 125.0,
            },
            {"symbol": "SOL/USDC:USDC", "side": "long", "contracts": 0.0},
        ]


@pytest.fixture
def fake():
    return FakeCcxt()


@pytest.fixture
def trading(fake):
    return HyperliquidTrading("0xabc", "0xkey", testnet=True, exchange=fake)


def request_of(order_type, price=50000.0, reduce_only=False):
    return OrderRequest(
        venue=Venue.HYPERLIQUID,
        symbol="BTC",
        side=Side.BUY,
        order_type=order_type,
        quantity=0.0002,
        price=price,
        reduce_only=reduce_only,
    )


class TestHyperliquidOrders:
    async def test_post_only_mapping(self, trading, fake):
        order_id = await trading.place_order(request_of(OrderType.LIMIT_POST_ONLY))
        assert order_id == "oid-1"
        symbol, order_type, side, _amount, _price, params = fake.created[0]
        assert symbol == "BTC/USDC:USDC"
        assert order_type == "limit"
        assert side == "buy"
        assert params["postOnly"] is True
        assert "timeInForce" not in params

    async def test_ioc_mapping(self, trading, fake):
        await trading.place_order(request_of(OrderType.LIMIT_IOC))
        *_, params = fake.created[0]
        assert params["timeInForce"] == "IOC"
        assert "postOnly" not in params

    async def test_reduce_only_flag(self, trading, fake):
        await trading.place_order(request_of(OrderType.LIMIT_IOC, reduce_only=True))
        *_, params = fake.created[0]
        assert params["reduceOnly"] is True

    async def test_stop_orders_deferred_to_p23(self, trading):
        with pytest.raises(NotImplementedError):
            await trading.place_order(request_of(OrderType.STOP))

    async def test_precision_applied(self, trading, fake):
        await trading.place_order(request_of(OrderType.LIMIT_POST_ONLY, price=50000.4))
        _, _, _, amount, price, _ = fake.created[0]
        assert amount == 0.0002
        assert price == 50000.0

    async def test_cancel_and_status_normalization(self, trading, fake):
        await trading.cancel_order("BTC", "oid-1")
        assert fake.canceled == [("oid-1", "BTC/USDC:USDC")]
        fake.order_status = "canceled"
        assert await trading.fetch_order_status("BTC", "oid-1") == "canceled"
        fake.order_status = "closed"
        assert await trading.fetch_order_status("BTC", "oid-1") == "filled"
        fake.order_status = "weird-new-status"
        assert await trading.fetch_order_status("BTC", "oid-1") == "unknown"

    async def test_fills_filtered_by_order_id(self, trading, fake):
        fake.trades = [
            {
                "order": "oid-1",
                "side": "buy",
                "amount": 0.0002,
                "price": 50000.0,
                "fee": {"cost": 0.0045},
                "takerOrMaker": "maker",
                "timestamp": 1_750_000_000_000,
            },
            {"order": "other", "side": "sell", "amount": 1, "price": 1, "timestamp": 0},
        ]
        fills = await trading.fetch_fills("BTC", "oid-1")
        assert len(fills) == 1
        assert fills[0].is_maker
        assert fills[0].fee == pytest.approx(0.0045)


class TestHyperliquidAccount:
    async def test_equity_from_margin_summary(self, trading):
        assert await trading.fetch_equity_usd() == pytest.approx(987.65)

    async def test_equity_includes_spot_usdc_for_unified_accounts(self, trading, fake):
        # Unified accounts: collateral lives in spot, and even the swap query
        # returns a spot-style payload without marginSummary.
        fake.balance = {"info": {"balances": []}, "total": {}}
        fake.spot_balance = {"total": {"USDC": 999.0}, "free": {"USDC": 999.0}}
        assert await trading.fetch_equity_usd() == pytest.approx(999.0)

    async def test_balances(self, trading):
        balances = await trading.fetch_balances()
        assert len(balances) == 1
        assert balances[0].asset == "USDC"
        assert balances[0].available == pytest.approx(900.0)

    async def test_positions_skip_flat_and_carry_isolated_margin(self, trading):
        positions = await trading.fetch_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "ETH"
        assert positions[0].isolated_margin == pytest.approx(125.0)


class TestKrakenStub:
    async def test_order_methods_fail_loudly(self, fake):
        trading = KrakenTrading("key", "secret", exchange=fake)
        request = OrderRequest(Venue.KRAKEN, "BTC/USD", Side.BUY, OrderType.MARKET, 1.0)
        with pytest.raises(NotImplementedError):
            await trading.place_order(request)
        with pytest.raises(NotImplementedError):
            await trading.cancel_order("BTC/USD", "x")

    async def test_balances_and_usd_equity(self, fake):
        fake.balance = {"total": {"ZUSD": 100.0, "USDT": 50.0, "ETH": 1.0}, "free": {}}
        trading = KrakenTrading("key", "secret", exchange=fake)
        assert await trading.fetch_equity_usd() == pytest.approx(150.0)
        assert await trading.fetch_positions() == []
