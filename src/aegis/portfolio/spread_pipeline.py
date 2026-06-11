"""Spread dispatch through risk engine + persistence (P2.4 / P2.5)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass

import numpy as np

from aegis.config import AegisConfig
from aegis.core.interfaces import AccountState, MarketData, OrderExecutor
from aegis.core.models import Fill, OrderRequest, OrderType, Side, Venue
from aegis.data import db
from aegis.execution.hyperliquid_trading import HyperliquidTrading
from aegis.execution.spread import SpreadExecutionResult, SpreadExecutor, SpreadLeg
from aegis.execution.testnet_pairs import (
    TestnetSpreadPair,
    leg_price,
    pair_passes_oracle_check,
)
from aegis.risk.engine import RiskEngine
from aegis.risk.sizing import BASE_R_PCT, size_position

logger = logging.getLogger(__name__)


@dataclass
class SpreadTradeResult:
    spread_id: str
    approved: bool
    skip_reason: str | None
    execution: SpreadExecutionResult | None
    reconciled: bool
    closed: bool


def _liquid_first(
    leg_a: SpreadLeg, leg_b: SpreadLeg, liquidity_rank: dict[str, float]
) -> tuple[SpreadLeg, SpreadLeg]:
    rank_a = liquidity_rank.get(leg_a.symbol, 0.0)
    rank_b = liquidity_rank.get(leg_b.symbol, 0.0)
    return (leg_a, leg_b) if rank_a >= rank_b else (leg_b, leg_a)


async def _fetch_returns(md: MarketData, symbol: str, *, limit: int = 120) -> np.ndarray:
    candles = await md.fetch_candles(symbol, "1h", limit=limit)
    if len(candles) < 2:
        return np.array([])
    closes = np.array([c.close for c in candles], dtype=float)
    return np.diff(closes) / closes[:-1]


async def _open_risk_by_symbol(trading: AccountState) -> dict[str, float]:
    out: dict[str, float] = {}
    for pos in await trading.fetch_positions():
        if pos.quantity <= 0:
            continue
        notional = pos.quantity * pos.entry_price
        out[pos.symbol] = out.get(pos.symbol, 0.0) + notional * 0.03 / BASE_R_PCT
    return out


async def build_spread_legs(
    *,
    pair: TestnetSpreadPair,
    order_usd: float,
    md: MarketData,
    trading: HyperliquidTrading,
) -> tuple[SpreadLeg, SpreadLeg] | str:
    long_sym, short_sym = pair.long_symbol, pair.short_symbol
    long_bid, long_ask = await md.fetch_top_of_book(long_sym)
    short_bid, short_ask = await md.fetch_top_of_book(short_sym)
    long_oracle = await trading.fetch_oracle_price(long_sym)
    short_oracle = await trading.fetch_oracle_price(short_sym)

    if not pair_passes_oracle_check(
        long_ask=long_ask,
        long_oracle=long_oracle,
        short_ask=short_ask,
        short_oracle=short_oracle,
    ):
        return "oracle_book_gap"

    long_qty = order_usd / long_ask
    short_qty = order_usd / short_ask
    long_leg = SpreadLeg(
        long_sym,
        Side.BUY,
        long_qty,
        leg_price(Side.BUY, long_bid, long_ask, long_oracle),
    )
    short_leg = SpreadLeg(
        short_sym,
        Side.SELL,
        short_qty,
        leg_price(Side.SELL, short_bid, short_ask, short_oracle),
    )
    return long_leg, short_leg


async def run_spread_trade(
    *,
    cfg: AegisConfig,
    conn,
    risk: RiskEngine,
    trading: HyperliquidTrading,
    md: MarketData,
    executor: SpreadExecutor,
    pair: TestnetSpreadPair,
    order_usd: float,
    equity: float,
) -> SpreadTradeResult:
    spread_id = uuid.uuid4().hex[:12]
    legs_or_skip = await build_spread_legs(pair=pair, order_usd=order_usd, md=md, trading=trading)
    if isinstance(legs_or_skip, str):
        return SpreadTradeResult(spread_id, False, legs_or_skip, None, False, False)

    long_leg, short_leg = legs_or_skip
    long_bid, long_ask = await md.fetch_top_of_book(long_leg.symbol)
    short_bid, short_ask = await md.fetch_top_of_book(short_leg.symbol)

    sizing = size_position(
        equity,
        cfg.risk.tiers.passive,
        stop_distance_pct=0.03,
        min_notional=cfg.hyperliquid.min_order_usd,
    )
    new_risk_r = sizing.risk_r if sizing.approved else 0.01

    open_risk = await _open_risk_by_symbol(trading)
    open_total = sum(open_risk.values())
    returns: dict[str, np.ndarray] = {}
    for sym in (long_leg.symbol, short_leg.symbol):
        returns[sym] = await _fetch_returns(md, sym)

    for sym, side, touch, bid, ask in (
        (long_leg.symbol, Side.BUY, long_ask, long_bid, long_ask),
        (short_leg.symbol, Side.SELL, short_bid, short_bid, short_ask),
    ):
        leg_approval = risk.approve_trade(
            equity=equity,
            symbol=sym,
            new_risk_r=new_risk_r / 2,
            open_risk_r=open_total,
            open_risk_by_symbol=open_risk,
            returns_by_symbol=returns,
            side=side,
            limit_price=touch,
            best_bid=bid,
            best_ask=ask,
        )
        if not leg_approval.approved:
            _log_signal(conn, spread_id, pair, taken=False, skip_reason=leg_approval.reason)
            return SpreadTradeResult(spread_id, False, leg_approval.reason, None, False, False)

    _log_signal(conn, spread_id, pair, taken=True, skip_reason=None)
    execution = await executor.execute_ioc_spread(long_leg, short_leg, venue=Venue.HYPERLIQUID)
    first, second = _liquid_first(long_leg, short_leg, pair.liquidity_rank)
    await _persist_execution(conn, spread_id, first, second, execution, trading)

    reconciled = await reconcile_spread_fills(conn, trading, execution)
    closed = False
    if (
        execution.leg1_status.value == "filled"
        and execution.leg2_status.value == "filled"
        and not execution.flattened
    ):
        closed = await close_spread(conn, spread_id, pair, trading)

    return SpreadTradeResult(
        spread_id,
        True,
        execution.error,
        execution,
        reconciled,
        closed,
    )


def _log_signal(
    conn,
    spread_id: str,
    pair: TestnetSpreadPair,
    *,
    taken: bool,
    skip_reason: str | None,
) -> None:
    ts_ms = int(time.time() * 1000)
    conn.execute(
        """
        INSERT INTO signals
            (ts_ms, strategy, venue, symbol, direction, tier, taken, skip_reason, context_json)
        VALUES (?, 'B_testnet', 'hyperliquid', ?, 'spread', '', ?, ?, ?)
        """,
        (
            ts_ms,
            f"{pair.long_symbol}/{pair.short_symbol}",
            int(taken),
            skip_reason,
            json.dumps({"spread_id": spread_id, "pair": f"{pair.long_symbol}/{pair.short_symbol}"}),
        ),
    )
    conn.commit()


async def _persist_order_and_fills(
    conn,
    spread_id: str,
    leg_name: str,
    leg: SpreadLeg,
    order_id: str,
    order_type: str,
    trading: OrderExecutor,
    *,
    reduce_only: bool = False,
) -> None:
    ts_ms = int(time.time() * 1000)
    status = await trading.fetch_order_status(leg.symbol, order_id)
    db.insert_order(
        conn,
        client_order_id=f"{spread_id}-{leg_name}",
        venue_order_id=order_id,
        ts_ms=ts_ms,
        venue=Venue.HYPERLIQUID.value,
        symbol=leg.symbol,
        side=leg.side.value,
        order_type=order_type,
        quantity=leg.quantity,
        price=leg.limit_price,
        reduce_only=reduce_only,
        status=status,
        context_json=json.dumps({"spread_id": spread_id, "leg": leg_name}),
    )
    for fill in await trading.fetch_fills(leg.symbol, order_id):
        _persist_fill(conn, fill)


async def _persist_execution(
    conn,
    spread_id: str,
    first: SpreadLeg,
    second: SpreadLeg,
    result: SpreadExecutionResult,
    trading: OrderExecutor,
) -> None:
    if result.leg1_order_id:
        await _persist_order_and_fills(
            conn, spread_id, "leg1", first, result.leg1_order_id, "limit_ioc", trading
        )
    if result.leg2_order_id:
        await _persist_order_and_fills(
            conn, spread_id, "leg2", second, result.leg2_order_id, "limit_ioc", trading
        )
    if result.flattened and result.flatten_order_id:
        await _persist_order_and_fills(
            conn,
            spread_id,
            "flatten",
            first,
            result.flatten_order_id,
            "market",
            trading,
            reduce_only=True,
        )


def _persist_fill(conn, fill: Fill) -> None:
    db.insert_fill(
        conn,
        ts_ms=int(fill.timestamp.timestamp() * 1000),
        venue=fill.venue.value,
        symbol=fill.symbol,
        venue_order_id=fill.order_id,
        client_order_id=fill.client_order_id,
        side=fill.side.value,
        quantity=fill.quantity,
        price=fill.price,
        fee=fill.fee,
        is_maker=fill.is_maker,
    )


async def reconcile_spread_fills(
    conn, trading: OrderExecutor, result: SpreadExecutionResult
) -> bool:
    ok = True
    for oid in (result.leg1_order_id, result.leg2_order_id, result.flatten_order_id):
        if oid is None:
            continue
        row = conn.execute("SELECT symbol FROM orders WHERE venue_order_id = ?", (oid,)).fetchone()
        if not row:
            ok = False
            continue
        symbol = row[0]
        venue_fills = await trading.fetch_fills(symbol, oid)
        if not db.fills_for_order(conn, oid):
            for fill in venue_fills:
                _persist_fill(conn, fill)
        venue_qty = sum(f.quantity for f in venue_fills)
        db_qty = sum(r[0] for r in db.fills_for_order(conn, oid))
        if venue_qty > 0 and abs(venue_qty - db_qty) > 1e-6:
            logger.warning(
                "fill qty mismatch",
                extra={"order_id": oid, "venue": venue_qty, "db": db_qty},
            )
            ok = False
    return ok


async def close_spread(
    conn, spread_id: str, pair: TestnetSpreadPair, trading: HyperliquidTrading
) -> bool:
    try:
        for pos in await trading.fetch_positions():
            if pos.symbol not in (pair.long_symbol, pair.short_symbol):
                continue
            oracle = await trading.fetch_oracle_price(pos.symbol)
            close_side = Side.SELL if pos.side is Side.BUY else Side.BUY
            leg = SpreadLeg(pos.symbol, close_side, pos.quantity, oracle)
            oid = await trading.place_order(
                OrderRequest(
                    venue=Venue.HYPERLIQUID,
                    symbol=pos.symbol,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=pos.quantity,
                    price=oracle,
                    reduce_only=True,
                )
            )
            await _persist_order_and_fills(
                conn,
                spread_id,
                f"close_{pos.symbol}",
                leg,
                oid,
                "market",
                trading,
                reduce_only=True,
            )
        remaining = [
            p
            for p in await trading.fetch_positions()
            if p.symbol in (pair.long_symbol, pair.short_symbol) and p.quantity > 0
        ]
        return len(remaining) == 0
    except Exception:
        logger.exception("close_spread failed")
        return False


async def ensure_flat(trading: AccountState, symbols: set[str]) -> bool:
    positions = await trading.fetch_positions()
    open_syms = {p.symbol for p in positions if p.quantity > 0 and p.symbol in symbols}
    return len(open_syms) == 0
