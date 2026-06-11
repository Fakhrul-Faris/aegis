"""P2.5 leg-2-miss drill on Hyperliquid testnet.

Proves the maker-then-IOC failure path end-to-end:
1. Leg 1 (more liquid symbol) fills via aggressive IOC.
2. Leg 2 is deliberately unfillable (IOC limit far from market).
3. Leg 1 is flattened at market within 1s.
4. Account returns flat on the drilled symbol.

Uses SOL + DOGE on testnet: majors often have L2 books >3% off oracle and
reject IOC; these alts track oracle closely enough to place real orders.

Refuses mainnet. Exit 0 = M4 drill item passed.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aegis.config import load_config
from aegis.core.models import Side, Venue
from aegis.execution import build_market_data, build_trading
from aegis.execution.spread import SpreadExecutor, SpreadLeg, SpreadLegStatus
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

ORDER_USD = 12.0
FLATTEN_BUDGET_MS = 1000.0
MAX_BOOK_ORACLE_GAP = 0.02
LIQUID = "SOL"
ILLIQUID = "DOGE"


def _position_qty(positions, symbol: str) -> float:
    for pos in positions:
        if pos.symbol == symbol:
            return pos.quantity if pos.side.value == "buy" else -pos.quantity
    return 0.0


def _book_oracle_gap(ask: float, oracle: float) -> float:
    return abs(ask / oracle - 1.0)


async def run_drill() -> None:
    cfg = load_config()
    if not cfg.hyperliquid.testnet:
        raise SystemExit("REFUSING: exchanges.hyperliquid.testnet is false in config")

    market_data = build_market_data(Venue.HYPERLIQUID, testnet=True)
    trading = build_trading(Venue.HYPERLIQUID, cfg.secrets, testnet=True)
    try:
        equity = await trading.fetch_equity_usd()
        logger.info("testnet equity", extra={"equity_usd": equity})
        if equity <= 0:
            raise SystemExit("Testnet equity is zero — faucet funds not visible yet")

        positions = await trading.fetch_positions()
        if abs(_position_qty(positions, LIQUID)) > 1e-6:
            raise SystemExit(f"Refusing drill: existing {LIQUID} position — flatten manually first")

        sol_bid, sol_ask = await market_data.fetch_top_of_book(LIQUID)
        doge_bid, doge_ask = await market_data.fetch_top_of_book(ILLIQUID)
        sol_oracle = await trading.fetch_oracle_price(LIQUID)
        doge_oracle = await trading.fetch_oracle_price(ILLIQUID)

        for coin, ask, oracle in (
            (LIQUID, sol_ask, sol_oracle),
            (ILLIQUID, doge_ask, doge_oracle),
        ):
            gap = _book_oracle_gap(ask, oracle)
            if gap > MAX_BOOK_ORACLE_GAP:
                raise SystemExit(
                    f"{coin} book/oracle gap {gap:.1%} exceeds {MAX_BOOK_ORACLE_GAP:.0%} "
                    "— pick another testnet pair or retry later"
                )

        logger.info(
            "oracle and book",
            extra={
                "sol_oracle": sol_oracle,
                "sol_book": (sol_bid, sol_ask),
                "doge_oracle": doge_oracle,
                "doge_book": (doge_bid, doge_ask),
            },
        )

        spread = SpreadExecutor(
            trading,
            liquidity_rank={LIQUID: 10.0, ILLIQUID: 1.0},
        )
        result = None
        for attempt in range(3):
            sol_bid, sol_ask = await market_data.fetch_top_of_book(LIQUID)
            sol_qty = ORDER_USD / sol_ask
            doge_qty = ORDER_USD / doge_oracle
            sol_ioc = min(sol_ask * 1.002, sol_oracle * 1.019)
            result = await spread.execute_leg2_miss_drill(
                SpreadLeg(ILLIQUID, Side.BUY, doge_qty, doge_oracle * 0.97),
                SpreadLeg(LIQUID, Side.BUY, sol_qty, sol_ioc),
                venue=Venue.HYPERLIQUID,
            )
            if result.error != "leg1_did_not_fill":
                break
            logger.warning(
                "leg1 IOC miss — retrying with fresh book", extra={"attempt": attempt + 1}
            )
            await asyncio.sleep(0.3)
        assert result is not None

        if result.error == "leg2_unexpectedly_filled":
            raise SystemExit("Leg 2 filled when it should have missed — widen unfillable price")
        if result.error:
            raise SystemExit(f"Drill failed: {result.error}")
        if not result.flattened:
            raise SystemExit("Leg 2 missed but leg 1 was not flattened")
        if result.leg1_status is not SpreadLegStatus.FLATTENED:
            raise SystemExit(f"Expected FLATTENED leg1, got {result.leg1_status}")
        if result.flatten_elapsed_ms is None or result.flatten_elapsed_ms > FLATTEN_BUDGET_MS:
            raise SystemExit(
                f"Flatten took {result.flatten_elapsed_ms}ms — budget is {FLATTEN_BUDGET_MS}ms"
            )

        positions = await trading.fetch_positions()
        net_sol = _position_qty(positions, LIQUID)
        if abs(net_sol) > sol_qty * 0.1:
            raise SystemExit(f"Position not flat after drill: {LIQUID} net={net_sol}")

        print(
            "P2.5 LEG-2-MISS DRILL PASSED\n"
            f"  equity:      ${equity:,.2f} (testnet)\n"
            f"  leg1:        {result.leg1_order_id} {LIQUID} IOC fill\n"
            f"  leg2:        {result.leg2_order_id or 'rejected'} {ILLIQUID} IOC miss (expected)\n"
            f"  flatten:     {result.flatten_elapsed_ms:.0f}ms (< {FLATTEN_BUDGET_MS:.0f}ms)\n"
            f"  {LIQUID} position after: {net_sol:.6f} (flat)"
        )
    finally:
        await trading.close()
        await market_data.close()


def main() -> None:
    setup_logging()
    try:
        asyncio.run(run_drill())
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("leg2 miss drill failed")
        sys.exit(f"FAILED: {exc}")


if __name__ == "__main__":
    main()
