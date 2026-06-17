"""Strategy C intraday paper pipeline (ID2).

Scanner flag + 4h regime + 15m breakout on Hyperliquid perps (simulated).
"""

from __future__ import annotations

import json
import logging
import time

import numpy as np

from aegis.config import AegisConfig
from aegis.config_intraday import IntradayConfig
from aegis.core.models import OrderRequest, OrderType, Side, Venue
from aegis.data import db
from aegis.execution import build_market_data
from aegis.execution.intraday_paper import INTRADAY_PAPER_VENUE, STRATEGY_C, IntradayPaperExecutor
from aegis.risk.sizing import size_position
from aegis.strategy.intraday_momentum import (
    IntradayExit,
    evaluate_entry_at_bar,
    evaluate_exit,
    is_past_flat_hour,
    regime_trending_up,
    scanner_flag_recent,
)
from aegis.strategy.regime import detect_regime

logger = logging.getLogger(__name__)


def _utc_day_start_ms(now_ms: int) -> int:
    from datetime import UTC, datetime

    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    day_start = datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
    return int(day_start.timestamp() * 1000)


def _daily_closed_r(conn, day_start_ms: int) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(r_multiple), 0) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
          AND closed_ts_ms >= ?
        """,
        (STRATEGY_C, INTRADAY_PAPER_VENUE, day_start_ms),
    ).fetchone()
    return float(row[0] or 0.0)


def _daily_trade_count(conn, day_start_ms: int) -> int:
    return conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE strategy = ? AND venue = ? AND opened_ts_ms >= ?
        """,
        (STRATEGY_C, INTRADAY_PAPER_VENUE, day_start_ms),
    ).fetchone()[0]


def _insert_signal(
    conn,
    *,
    symbol: str,
    taken: bool,
    skip_reason: str | None,
    context: dict,
) -> None:
    ts_ms = int(time.time() * 1000)
    conn.execute(
        """
        INSERT INTO signals
            (ts_ms, strategy, venue, symbol, direction, tier, taken, skip_reason, context_json)
        VALUES (?, ?, ?, ?, 'long', 'aggressive', ?, ?, ?)
        """,
        (
            ts_ms,
            STRATEGY_C,
            INTRADAY_PAPER_VENUE,
            symbol,
            int(taken),
            skip_reason,
            json.dumps(context),
        ),
    )
    conn.commit()


def _intraday_equity(conn, icfg: IntradayConfig, marks: dict[str, float]) -> float:
    realized = conn.execute(
        """
        SELECT COALESCE(SUM(realized_pnl), 0) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
        """,
        (STRATEGY_C, INTRADAY_PAPER_VENUE),
    ).fetchone()[0]
    unrealized = 0.0
    open_fees = 0.0
    for pos in db.open_strategy_positions(conn, strategy=STRATEGY_C, venue=INTRADAY_PAPER_VENUE):
        mark = marks.get(pos.symbol, pos.entry_price)
        unrealized += (mark - pos.entry_price) * pos.quantity
        open_fees += float(pos.context.get("entry_fee", 0.0))
    return icfg.demo.equity_usd + float(realized or 0) + unrealized - open_fees


async def _check_exits(
    icfg: IntradayConfig,
    acfg: AegisConfig,
    conn,
    md,
    symbol: str,
) -> None:
    open_for = [
        p for p in db.open_strategy_positions(conn, strategy=STRATEGY_C, venue=INTRADAY_PAPER_VENUE)
        if p.symbol == symbol
    ]
    if not open_for:
        return

    md_cfg = icfg.momentum_day
    candles = await md.fetch_candles(symbol, md_cfg.signal_timeframe, limit=120)
    if len(candles) < md_cfg.breakout_lookback_bars + 2:
        return

    bar = len(candles) - 1
    current = candles[bar].close
    bar_open_ms = int(candles[bar].open_time.timestamp() * 1000)

    for pos in open_for:
        reason = evaluate_exit(pos.entry_price, current, bar_open_ms, md_cfg)
        if reason is IntradayExit.HOLD and not is_past_flat_hour(bar_open_ms, md_cfg):
            continue
        if reason is IntradayExit.HOLD and is_past_flat_hour(bar_open_ms, md_cfg):
            reason = IntradayExit.EOD_FLAT

        paper = IntradayPaperExecutor(conn, md, icfg.costs, symbol=symbol)
        order_id = await paper.place_order(
            OrderRequest(
                venue=Venue.HYPERLIQUID,
                symbol=symbol,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=pos.quantity,
            )
        )
        fills = await paper.fetch_fills(order_id)
        exit_fill = fills[0]
        entry_fee = float(pos.context.get("entry_fee", 0.0))
        gross = (exit_fill.price - pos.entry_price) * pos.quantity
        net_pnl = gross - entry_fee - exit_fill.fee
        risk = pos.risk_amount_usd or 1.0
        r_mult = net_pnl / risk
        db.close_strategy_position(
            conn,
            pos.id,
            closed_ts_ms=int(time.time() * 1000),
            exit_price=exit_fill.price,
            realized_pnl=net_pnl,
            r_multiple=r_mult,
            exit_reason=reason.value,
        )
        _insert_signal(
            conn,
            symbol=symbol,
            taken=True,
            skip_reason=None,
            context={"action": "exit", "exit_reason": reason.value, "r_multiple": r_mult},
        )
        logger.info(
            "intraday paper exit",
            extra={"symbol": symbol, "reason": reason.value, "r": round(r_mult, 3)},
        )


async def _try_entry(
    icfg: IntradayConfig,
    acfg: AegisConfig,
    conn,
    md,
    symbol: str,
    equity: float,
    now_ms: int,
) -> None:
    md_cfg = icfg.momentum_day
    if not md_cfg.enabled:
        return

    open_all = db.open_strategy_positions(conn, strategy=STRATEGY_C, venue=INTRADAY_PAPER_VENUE)
    if len(open_all) >= md_cfg.max_open_positions:
        return
    if any(p.symbol == symbol for p in open_all):
        return

    day_start = _utc_day_start_ms(now_ms)
    if _daily_trade_count(conn, day_start) >= md_cfg.max_trades_per_day:
        return
    daily_r = _daily_closed_r(conn, day_start)
    if daily_r >= md_cfg.daily_profit_cap_r:
        return
    if daily_r <= -md_cfg.daily_loss_cap_r:
        return

    signal_candles = await md.fetch_candles(symbol, md_cfg.signal_timeframe, limit=120)
    regime_candles = await md.fetch_candles(symbol, md_cfg.regime_timeframe, limit=250)
    if len(signal_candles) < md_cfg.breakout_lookback_bars + 5:
        return
    if len(regime_candles) < 210:
        return

    bar = len(signal_candles) - 1
    bar_open_ms = int(signal_candles[bar].open_time.timestamp() * 1000)
    if db.intraday_signal_exists(conn, strategy=STRATEGY_C, symbol=symbol, bar_open_ms=bar_open_ms):
        return
    if is_past_flat_hour(bar_open_ms, md_cfg):
        return

    highs = np.array([c.high for c in signal_candles])
    lows = np.array([c.low for c in signal_candles])
    closes = np.array([c.close for c in signal_candles])

    rh = np.array([c.high for c in regime_candles])
    rl = np.array([c.low for c in regime_candles])
    rc = np.array([c.close for c in regime_candles])
    trending = regime_trending_up(rh, rl, rc, acfg.regime)

    anomaly = scanner_flag_recent(conn, symbol, bar_open_ms, md_cfg.signal_timeframe)
    entry = evaluate_entry_at_bar(
        bar,
        highs,
        lows,
        closes,
        bar_open_ms,
        md_cfg,
        anomaly=anomaly,
        trending_up=trending,
    )
    if entry is None:
        return

    ctx = {
        "bar_open_ms": bar_open_ms,
        "anomaly": anomaly,
        "regime": detect_regime(rh, rl, rc, acfg.regime).value,
        "mode": "intraday_paper",
    }

    if not trending:
        _insert_signal(
            conn,
            symbol=symbol,
            taken=False,
            skip_reason="regime_not_trending_up",
            context=ctx,
        )
        return
    if md_cfg.scanner_required and not anomaly:
        _insert_signal(conn, symbol=symbol, taken=False, skip_reason="no_scanner_flag", context=ctx)
        return

    _, ask = await md.fetch_top_of_book(symbol)
    sizing = size_position(
        equity,
        md_cfg.risk_pct,
        stop_distance_pct=md_cfg.stop_loss_pct,
        min_notional=icfg.costs.min_order_usd,
    )
    if not sizing.approved:
        _insert_signal(conn, symbol=symbol, taken=False, skip_reason=sizing.reason, context=ctx)
        return

    quantity = sizing.notional / ask
    paper = IntradayPaperExecutor(conn, md, icfg.costs, symbol=symbol)
    order_id = await paper.place_order(
        OrderRequest(
            venue=Venue.HYPERLIQUID,
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            client_order_id=f"c-{symbol}-{bar_open_ms}",
        )
    )
    fills = await paper.fetch_fills(order_id)
    fill = fills[0]
    ctx["risk_r"] = sizing.risk_r
    ctx["entry_fee"] = fill.fee
    db.insert_strategy_position(
        conn,
        strategy=STRATEGY_C,
        venue=INTRADAY_PAPER_VENUE,
        opened_ts_ms=int(time.time() * 1000),
        symbol=symbol,
        quantity=quantity,
        entry_price=fill.price,
        risk_amount_usd=sizing.risk_amount,
        tier="aggressive",
        context=ctx,
    )
    _insert_signal(conn, symbol=symbol, taken=True, skip_reason=None, context=ctx)
    logger.info(
        "intraday paper entry",
        extra={"symbol": symbol, "notional": round(sizing.notional, 2), "anomaly": anomaly},
    )


async def run_intraday_cycle(
    icfg: IntradayConfig,
    acfg: AegisConfig,
    conn,
) -> None:
    """One Strategy C paper cycle."""
    if not icfg.momentum_day.enabled:
        logger.info("intraday momentum_day disabled")
        return

    now_ms = int(time.time() * 1000)
    marks: dict[str, float] = {}
    md = build_market_data(Venue.HYPERLIQUID, testnet=False)
    try:
        for symbol in icfg.momentum_day.symbols:
            await _check_exits(icfg, acfg, conn, md, symbol)

        equity = _intraday_equity(conn, icfg, marks)

        for symbol in icfg.momentum_day.symbols:
            await _try_entry(icfg, acfg, conn, md, symbol, equity, now_ms)
            try:
                _, ask = await md.fetch_top_of_book(symbol)
                marks[symbol] = ask
            except Exception:
                pass
    finally:
        await md.close()

    equity = _intraday_equity(conn, icfg, marks)
    db.insert_equity_snapshot(
        conn,
        ts_ms=now_ms,
        venue=INTRADAY_PAPER_VENUE,
        equity_usd=equity,
        mode="intraday_paper",
    )
