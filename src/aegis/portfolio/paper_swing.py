"""Strategy A paper pipeline (P1.7 / P3.1).

Joins live scanner flags → tier classification → risk gate → simulated Kraken
fills. PASSIVE (EMA-only) signals are logged for baseline comparison;
AGGRESSIVE (EMA + anomaly) entries get paper fills when risk approves.
"""

from __future__ import annotations

import json
import logging
import time

import numpy as np

from aegis.config import AegisConfig
from aegis.core.interfaces import MarketData
from aegis.core.models import OrderRequest, OrderType, Side, Venue
from aegis.data import db
from aegis.data.scanner_join import latest_anomaly_in_window
from aegis.execution import build_market_data
from aegis.execution.paper import PaperExecutor
from aegis.risk.engine import RiskEngine
from aegis.risk.sizing import concurrent_risk_allows, size_position
from aegis.strategy.regime import detect_regime, strategy_a_active, strategy_b_size_factor
from aegis.strategy.swing import (
    SwingExit,
    SwingTier,
    evaluate_entry_at_bar,
    evaluate_exit,
    precompute_indicators,
)

logger = logging.getLogger(__name__)

KRAKEN_MIN_NOTIONAL_USD = 10.0
PAPER_TRADE_TIERS = frozenset({SwingTier.AGGRESSIVE})


def _tier_risk_pct(cfg: AegisConfig, tier: SwingTier) -> float:
    tiers = cfg.risk.tiers
    if tier is SwingTier.AGGRESSIVE:
        return tiers.aggressive
    if tier is SwingTier.MID:
        return tiers.mid
    return tiers.passive


def _open_risk_r(conn) -> tuple[float, dict[str, float]]:
    by_symbol: dict[str, float] = {}
    for pos in db.open_paper_positions(conn):
        risk_r = float(pos.context.get("risk_r", 0.5))
        by_symbol[pos.symbol] = by_symbol.get(pos.symbol, 0.0) + risk_r
    return sum(by_symbol.values()), by_symbol


def _insert_signal(
    conn,
    *,
    symbol: str,
    tier: str,
    taken: bool,
    skip_reason: str | None,
    context: dict,
) -> None:
    ts_ms = int(time.time() * 1000)
    conn.execute(
        """
        INSERT INTO signals
            (ts_ms, strategy, venue, symbol, direction, tier, taken, skip_reason, context_json)
        VALUES (?, 'A', 'kraken', ?, 'long', ?, ?, ?, ?)
        """,
        (ts_ms, symbol, tier, int(taken), skip_reason, json.dumps(context)),
    )
    conn.commit()


async def _check_exits(
    cfg: AegisConfig,
    conn,
    md: MarketData,
    kraken_symbol: str,
    base: str,
) -> None:
    open_for_symbol = [p for p in db.open_paper_positions(conn) if p.symbol == base]
    if not open_for_symbol:
        return

    candles = await md.fetch_candles(kraken_symbol, cfg.strategy_a.signal_timeframe, limit=250)
    if len(candles) < cfg.strategy_a.ema_slow + 2:
        return

    closes = np.array([c.close for c in candles])
    fast, slow, _ = precompute_indicators(closes, cfg.strategy_a)
    bar = len(closes) - 1
    current = closes[bar]

    for pos in open_for_symbol:
        exit_reason = evaluate_exit(
            pos.entry_price, current, bar, closes, cfg.strategy_a, fast=fast, slow=slow
        )
        if exit_reason is SwingExit.HOLD:
            continue

        paper = PaperExecutor(
            conn,
            md,
            cfg.kraken_fees,
            slippage_pct=cfg.risk.slippage_gate_pct,
            kraken_pair=kraken_symbol,
        )
        await paper.place_order(
            OrderRequest(
                venue=Venue.KRAKEN,
                symbol=base,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=pos.quantity,
            )
        )

        gross_pnl = (current - pos.entry_price) * pos.quantity
        risk = pos.risk_amount_usd or 1.0
        r_mult = gross_pnl / risk
        db.close_paper_position(
            conn,
            pos.id,
            closed_ts_ms=int(time.time() * 1000),
            exit_price=current,
            realized_pnl=gross_pnl,
            r_multiple=r_mult,
            exit_reason=exit_reason.value,
        )
        _insert_signal(
            conn,
            symbol=base,
            tier=pos.context.get("tier", ""),
            taken=True,
            skip_reason=None,
            context={
                "action": "exit",
                "exit_reason": exit_reason.value,
                "r_multiple": r_mult,
                "position_id": pos.id,
            },
        )
        logger.info(
            "paper exit",
            extra={"symbol": base, "reason": exit_reason.value, "r": round(r_mult, 3)},
        )


async def _try_entry(
    cfg: AegisConfig,
    conn,
    md: MarketData,
    risk: RiskEngine,
    kraken_symbol: str,
    base: str,
    equity: float,
) -> None:
    if any(p.symbol == base for p in db.open_paper_positions(conn)):
        return

    candles = await md.fetch_candles(kraken_symbol, cfg.strategy_a.signal_timeframe, limit=250)
    if len(candles) < 210:
        return

    bar = len(candles) - 1
    bar_open_ms = int(candles[bar].open_time.timestamp() * 1000)
    if db.signal_exists_for_bar(conn, base, bar_open_ms):
        return

    highs = np.array([c.high for c in candles])
    lows = np.array([c.low for c in candles])
    closes = np.array([c.close for c in candles])
    regime = detect_regime(highs, lows, closes, cfg.regime)

    anomaly = latest_anomaly_in_window(conn, base, bar_open_ms, cfg.strategy_a.signal_timeframe)
    flags = np.zeros(len(closes), dtype=bool)
    if anomaly:
        flags[bar] = True

    fast, slow, rs = precompute_indicators(closes, cfg.strategy_a)
    entry = evaluate_entry_at_bar(bar, closes, fast, slow, rs, cfg.strategy_a, flags)
    if entry is None:
        return

    ctx = {
        "rsi": entry.rsi,
        "regime": regime.value,
        "mode": cfg.mode,
        "bar_open_ms": bar_open_ms,
        "anomaly": anomaly is not None,
    }
    if anomaly:
        ctx["scanner"] = {
            "variant": anomaly.variant,
            "volume_multiple": anomaly.volume_multiple,
            "on_kraken": anomaly.on_kraken,
        }

    if not strategy_a_active(regime):
        _insert_signal(
            conn,
            symbol=base,
            tier=entry.tier.value,
            taken=False,
            skip_reason=f"regime_{regime.value}",
            context=ctx,
        )
        return

    if entry.tier not in PAPER_TRADE_TIERS:
        _insert_signal(
            conn,
            symbol=base,
            tier=entry.tier.value,
            taken=False,
            skip_reason="passive_baseline_only",
            context=ctx,
        )
        logger.info(
            "strategy A signal (baseline)",
            extra={"symbol": base, "tier": entry.tier.value},
        )
        return

    bid, ask = await md.fetch_top_of_book(kraken_symbol)
    tier_pct = _tier_risk_pct(cfg, entry.tier)
    regime_factor = strategy_b_size_factor(regime, cfg.regime)
    sizing = size_position(
        equity,
        tier_pct,
        stop_distance_pct=cfg.strategy_a.stop_loss_pct,
        min_notional=KRAKEN_MIN_NOTIONAL_USD,
        regime_size_factor=regime_factor,
    )
    if not sizing.approved:
        _insert_signal(
            conn,
            symbol=base,
            tier=entry.tier.value,
            taken=False,
            skip_reason=sizing.reason,
            context=ctx,
        )
        return

    open_total, open_by_symbol = _open_risk_r(conn)
    if not concurrent_risk_allows(open_total, sizing.risk_r, cfg.risk.max_concurrent_risk_r):
        _insert_signal(
            conn,
            symbol=base,
            tier=entry.tier.value,
            taken=False,
            skip_reason="max_concurrent_risk",
            context=ctx,
        )
        return

    approval = risk.approve_trade(
        equity=equity,
        symbol=base,
        new_risk_r=sizing.risk_r,
        open_risk_r=open_total,
        open_risk_by_symbol=open_by_symbol,
        returns_by_symbol={base: np.array([])},
        side=Side.BUY,
        limit_price=ask,
        best_bid=bid,
        best_ask=ask,
    )
    if not approval.approved:
        _insert_signal(
            conn,
            symbol=base,
            tier=entry.tier.value,
            taken=False,
            skip_reason=approval.reason,
            context=ctx,
        )
        return

    quantity = sizing.notional / ask
    paper = PaperExecutor(
        conn,
        md,
        cfg.kraken_fees,
        slippage_pct=cfg.risk.slippage_gate_pct,
        kraken_pair=kraken_symbol,
    )
    await paper.place_order(
        OrderRequest(
            venue=Venue.KRAKEN,
            symbol=base,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            client_order_id=f"a-{base}-{bar_open_ms}",
        )
    )

    ctx["risk_r"] = sizing.risk_r
    db.insert_paper_position(
        conn,
        opened_ts_ms=int(time.time() * 1000),
        symbol=base,
        quantity=quantity,
        entry_price=ask,
        risk_amount_usd=sizing.risk_amount,
        tier=entry.tier.value,
        context=ctx,
    )
    _insert_signal(
        conn,
        symbol=base,
        tier=entry.tier.value,
        taken=True,
        skip_reason=None,
        context=ctx,
    )
    logger.info(
        "paper entry",
        extra={
            "symbol": base,
            "tier": entry.tier.value,
            "notional": round(sizing.notional, 2),
            "anomaly_multiple": anomaly.volume_multiple if anomaly else None,
        },
    )


PAPER_STARTING_EQUITY_USD = 1000.0


def _paper_equity(conn, marks: dict[str, float]) -> float:
    realized = conn.execute(
        """
        SELECT COALESCE(SUM(realized_pnl), 0) FROM positions
        WHERE strategy = 'A' AND closed_ts_ms IS NOT NULL
        """
    ).fetchone()[0]
    unrealized = 0.0
    for pos in db.open_paper_positions(conn):
        mark = marks.get(pos.symbol, pos.entry_price)
        unrealized += (mark - pos.entry_price) * pos.quantity
    return PAPER_STARTING_EQUITY_USD + float(realized or 0) + unrealized


async def run_paper_cycle(cfg: AegisConfig, conn, risk: RiskEngine) -> None:
    """One Strategy A paper cycle: manage exits, scan entries, snapshot equity."""
    equity = db.latest_paper_equity(conn, default=PAPER_STARTING_EQUITY_USD)
    alerts = risk.update_equity(equity)
    for msg in alerts:
        logger.critical(msg)
    if risk.state.killed or risk.state.halted_daily:
        logger.warning("paper cycle skipped — breaker active")
        return

    md = build_market_data(Venue.KRAKEN)
    marks: dict[str, float] = {}
    try:
        for kraken_symbol in cfg.data.kraken_symbols:
            base = kraken_symbol.split("/")[0]
            await _check_exits(cfg, conn, md, kraken_symbol, base)
            await _try_entry(cfg, conn, md, risk, kraken_symbol, base, equity)
            try:
                _, ask = await md.fetch_top_of_book(kraken_symbol)
                marks[base] = ask
            except Exception:
                pass
    finally:
        await md.close()

    equity = _paper_equity(conn, marks)
    db.insert_equity_snapshot(
        conn,
        ts_ms=int(time.time() * 1000),
        venue="paper",
        equity_usd=equity,
        mode=cfg.mode,
    )
