"""P0.2 connectivity proof: one order placed and cancelled on Hyperliquid
testnet, entirely through our own adapter stack.

What it proves, in order:
1. The wallet credentials in .env sign valid actions (auth works).
2. Account equity is readable (risk sizing has a base to work from).
3. A post-only limit order far below market rests on the book (it can
   never fill - this script must not leave residue even if interrupted
   between place and cancel; a 20%-below-bid buy guarantees that).
4. The order is visible via status query (state tracking works).
5. Cancel works and the status reflects it.

Exit code 0 = P0.2 gate item passed. Any exception = fail, loudly.
Refuses to run against mainnet, unconditionally.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aegis.config import load_config
from aegis.core.models import OrderRequest, OrderType, Side, Venue
from aegis.execution import build_market_data, build_trading
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

COIN = "BTC"
ORDER_USD = 12.0  # just above the $10 venue minimum
PRICE_DISCOUNT = 0.80  # 20% below best bid: rests, never fills


async def run_check() -> None:
    cfg = load_config()
    if not cfg.hyperliquid.testnet:
        raise SystemExit("REFUSING: exchanges.hyperliquid.testnet is false in config")

    market_data = build_market_data(Venue.HYPERLIQUID, testnet=True)
    trading = build_trading(Venue.HYPERLIQUID, cfg.secrets, testnet=True)
    try:
        equity = await trading.fetch_equity_usd()
        logger.info("testnet equity", extra={"equity_usd": equity})
        if equity <= 0:
            raise SystemExit("Testnet equity is zero - faucet funds not visible yet")

        best_bid, best_ask = await market_data.fetch_top_of_book(COIN)
        logger.info("top of book", extra={"coin": COIN, "bid": best_bid, "ask": best_ask})

        price = best_bid * PRICE_DISCOUNT
        quantity = ORDER_USD / price
        order_id = await trading.place_order(
            OrderRequest(
                venue=Venue.HYPERLIQUID,
                symbol=COIN,
                side=Side.BUY,
                order_type=OrderType.LIMIT_POST_ONLY,
                quantity=quantity,
                price=price,
            )
        )

        status = await trading.fetch_order_status(COIN, order_id)
        logger.info("order resting", extra={"order_id": order_id, "status": status})
        if status != "open":
            raise SystemExit(f"Expected resting order, got status {status!r}")

        await trading.cancel_order(COIN, order_id)
        status = await trading.fetch_order_status(COIN, order_id)
        logger.info("order after cancel", extra={"order_id": order_id, "status": status})
        if status != "canceled":
            raise SystemExit(f"Expected canceled order, got status {status!r}")

        fills = await trading.fetch_fills(COIN, order_id)
        if fills:
            raise SystemExit(f"Order should never have filled, found {len(fills)} fills")

        print(
            f"P0.2 CONNECTIVITY PROOF PASSED\n"
            f"  equity:  ${equity:,.2f} (testnet)\n"
            f"  order:   {order_id} BUY {quantity:.5f} {COIN} @ {price:,.0f} (post-only)\n"
            f"  lifecycle: placed -> open -> canceled, zero fills"
        )
    finally:
        await trading.close()
        await market_data.close()


def main() -> None:
    setup_logging()
    try:
        asyncio.run(run_check())
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("testnet check failed")
        sys.exit(f"FAILED: {exc}")


if __name__ == "__main__":
    main()
