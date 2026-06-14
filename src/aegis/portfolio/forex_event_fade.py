"""Event Spike Fade demo portfolio loop (FX4).

Calendar-driven signal scan on frozen H11c-3 recipe. SCM session pipeline is
parked — this module is the active forex demo strategy runner.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta

import pandas as pd

from aegis.config import load_config
from aegis.config_forex import ForexConfig, load_forex_config
from aegis.core.models import OrderRequest, OrderType, Side, Venue
from aegis.data import db
from aegis.execution.forex_market_data import build_forex_market_data
from aegis.execution.forex_paper import FOREX_DEMO_VENUE, ForexPaperExecutor
from aegis.monitor.forex_config_freeze import verify_or_freeze_forex_config
from aegis.monitor.trade_reflection import reflect_closed_position
from aegis.research.decision_pipeline import (
    build_entry_proposal,
    build_skip_proposal,
    merge_context,
)
from aegis.strategy.forex_confirms import load_calendar_events
from aegis.strategy.forex_hypotheses import detect_event_spike_fade_h11b
from aegis.strategy.forex_session import compute_asian_ranges

logger = logging.getLogger(__name__)

STRATEGY_ID = "event_spike_fade"


def _candles_to_ohlc(conn, pair: str, timeframe: str, *, lookback_days: int = 30) -> pd.DataFrame:
    start_ms = int((datetime.now(tz=UTC) - timedelta(days=lookback_days)).timestamp() * 1000)
    rows = db.load_candles(
        conn, Venue.FOREX_DEMO, pair, timeframe, start_ms=start_ms
    )
    if not rows:
        rows = db.load_candles(conn, Venue.FOREX, pair, timeframe, start_ms=start_ms)
    if not rows:
        return pd.DataFrame()
    data = {
        "open": [c.open for c in rows],
        "high": [c.high for c in rows],
        "low": [c.low for c in rows],
        "close": [c.close for c in rows],
    }
    idx = pd.DatetimeIndex([c.open_time for c in rows], tz="UTC")
    return pd.DataFrame(data, index=idx)


def _events_for_pair(pair: str, events) -> list:
    if pair == "EURUSD":
        return [e for e in events if e.currency in ("USD", "EUR")]
    if pair == "GBPUSD":
        return [e for e in events if e.currency in ("USD", "GBP")]
    return list(events)


def _log_signal(conn, *, ts_ms: int, pair: str, direction: str, taken: bool, reason: str, ctx: dict):
    conn.execute(
        """
        INSERT INTO signals
            (ts_ms, strategy, venue, symbol, direction, tier, z_score, taken, skip_reason, context_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_ms,
            STRATEGY_ID,
            FOREX_DEMO_VENUE,
            pair,
            direction,
            None,
            None,
            int(taken),
            None if taken else reason,
            json.dumps(ctx),
        ),
    )
    conn.commit()


def _open_forex_positions(conn) -> list[tuple[db.PaperPositionRow, str]]:
    rows = conn.execute(
        """
        SELECT id, symbol, side, quantity, entry_price, risk_amount_usd, opened_ts_ms, context_json
        FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NULL
        """,
        (STRATEGY_ID, FOREX_DEMO_VENUE),
    ).fetchall()
    out: list[tuple[db.PaperPositionRow, str]] = []
    for row in rows:
        pos = db.PaperPositionRow(
            id=row[0],
            symbol=row[1],
            quantity=row[3],
            entry_price=row[4],
            risk_amount_usd=row[5] or 0.0,
            opened_ts_ms=row[6],
            context=json.loads(row[7]) if row[7] else {},
        )
        out.append((pos, str(row[2])))
    return out


def _insert_forex_position(
    conn,
    *,
    opened_ts_ms: int,
    symbol: str,
    quantity: float,
    entry_price: float,
    risk_amount_usd: float,
    side: str,
    context: dict,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO positions
            (opened_ts_ms, strategy, venue, symbol, side, quantity, entry_price,
             risk_amount_usd, context_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            opened_ts_ms,
            STRATEGY_ID,
            FOREX_DEMO_VENUE,
            symbol,
            side,
            quantity,
            entry_price,
            risk_amount_usd,
            json.dumps(context),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


async def run_event_fade_cycle(cfg: ForexConfig, *, sqlite_path: str | None = None) -> dict:
    """One hourly scan: manage exits, detect signals, paper-fill entries."""
    from aegis.monitor.forex_config_freeze import params_from_esf_config

    aegis_cfg = load_config()
    db_path = sqlite_path or cfg.demo.sqlite_path
    conn = db.connect(db_path)
    summary = {"signals": 0, "entries": 0, "exits": 0, "skips": 0, "open_positions": 0}
    try:
        from aegis.data.forex_calendar import seed_economic_calendar

        seed_economic_calendar(conn, year_start=datetime.now(tz=UTC).year - 1, year_end=datetime.now(tz=UTC).year + 1)
        verify_or_freeze_forex_config(conn, cfg)
        md = build_forex_market_data(cfg, aegis_cfg.secrets, conn=conn)
        executor = ForexPaperExecutor(conn, md, cfg)
        esf = cfg.event_spike_fade
        params = params_from_esf_config(cfg)
        ts_ms = int(time.time() * 1000)

        events = load_calendar_events(
            db_path,
            cfg.calendar,
            currencies=cfg.calendar.event_spike_currencies,
            tiers=cfg.calendar.event_spike_tiers,
        )
        ohlc_cache: dict[str, pd.DataFrame] = {}

        summary["exits"] = await _manage_open_positions(
            conn, cfg, executor, esf, ohlc_cache, ts_ms=ts_ms
        )
        equity = _compute_demo_equity(conn, cfg.demo.equity_usd)
        open_list = _open_forex_positions(conn)
        open_symbols = {p.symbol for p, _ in open_list}

        for pair in esf.pairs:
            if pair in open_symbols:
                continue
            ohlc = _candles_to_ohlc(conn, pair, esf.timeframe)
            ohlc_cache[pair] = ohlc
            if ohlc.empty:
                summary["skips"] += 1
                skip = build_skip_proposal(
                    pair=pair,
                    reason="no_candles",
                    equity_usd=equity,
                    open_positions=len(open_list),
                )
                _log_signal(
                    conn,
                    ts_ms=ts_ms,
                    pair=pair,
                    direction="none",
                    taken=False,
                    reason="no_candles",
                    ctx=skip.to_context(),
                )
                continue

            pair_events = _events_for_pair(pair, events)
            ranges = compute_asian_ranges(ohlc, cfg.sessions)
            pip_size = cfg.costs.pip_size_for(pair)
            signals = detect_event_spike_fade_h11b(
                ohlc,
                cfg.sessions,
                params,
                events=pair_events,
                asian_ranges=ranges,
                pip_size=pip_size,
            )
            latest_bar = ohlc.index[-1]
            fresh = [s for s in signals if s.entry_bar_ts == latest_bar]
            summary["signals"] += len(fresh)

            for sig in fresh:
                if _signal_already_logged(conn, pair, sig.entry_bar_ts):
                    continue
                base_ctx = {
                    "stop": sig.stop_price,
                    "target": sig.target_price,
                    "event_code": getattr(sig, "event_code", None),
                }
                proposal = build_entry_proposal(
                    pair=pair,
                    direction=sig.direction,
                    stop=sig.stop_price,
                    target=sig.target_price,
                    event_code=getattr(sig, "event_code", None),
                    equity_usd=equity,
                    open_positions=len(open_list),
                    has_candles=True,
                    has_open_position=pair in open_symbols,
                )
                ctx = merge_context(base_ctx, proposal)
                if proposal.signal == "skip":
                    summary["skips"] += 1
                    _log_signal(
                        conn,
                        ts_ms=ts_ms,
                        pair=pair,
                        direction=sig.direction,
                        taken=False,
                        reason=proposal.rationale,
                        ctx=ctx,
                    )
                    continue
                side = Side.BUY if sig.direction == "long" else Side.SELL
                risk_amount = equity * esf.risk_pct
                try:
                    order_id = await executor.place_order(
                        OrderRequest(
                            venue=Venue.FOREX_DEMO,
                            symbol=pair,
                            side=side,
                            order_type=OrderType.MARKET,
                            quantity=esf.lots,
                            client_order_id=f"esf-{pair}-{int(sig.entry_bar_ts.timestamp())}",
                        )
                    )
                    fills = await executor.fetch_fills(pair, order_id)
                    if not fills:
                        summary["skips"] += 1
                        _log_signal(conn, ts_ms=ts_ms, pair=pair, direction=sig.direction, taken=False, reason="no_fill", ctx=ctx)
                        continue
                    fill = fills[0]
                    _insert_forex_position(
                        conn,
                        opened_ts_ms=ts_ms,
                        symbol=pair,
                        quantity=esf.lots,
                        entry_price=fill.price,
                        risk_amount_usd=risk_amount,
                        side=sig.direction,
                        context=ctx,
                    )
                    summary["entries"] += 1
                    _log_signal(conn, ts_ms=ts_ms, pair=pair, direction=sig.direction, taken=True, reason="", ctx=ctx)
                except Exception as exc:
                    summary["skips"] += 1
                    _log_signal(
                        conn,
                        ts_ms=ts_ms,
                        pair=pair,
                        direction=sig.direction,
                        taken=False,
                        reason=str(exc),
                        ctx=ctx,
                    )

        summary["open_positions"] = len(_open_forex_positions(conn))
        equity = _compute_demo_equity(conn, cfg.demo.equity_usd)
        db.insert_equity_snapshot(
            conn,
            ts_ms=ts_ms,
            venue=FOREX_DEMO_VENUE,
            equity_usd=equity,
            mode="forex_paper",
        )
    finally:
        conn.close()
    return summary


def _compute_demo_equity(conn, starting: float) -> float:
    realized = conn.execute(
        """
        SELECT COALESCE(SUM(realized_pnl), 0) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
        """,
        (STRATEGY_ID, FOREX_DEMO_VENUE),
    ).fetchone()[0]
    fees = conn.execute(
        "SELECT COALESCE(SUM(fee), 0) FROM fills WHERE venue = ?",
        (FOREX_DEMO_VENUE,),
    ).fetchone()[0]
    return starting + float(realized) - float(fees)


def _forex_demo_equity(conn, default: float) -> float:
    computed = _compute_demo_equity(conn, default)
    row = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = ? ORDER BY ts_ms DESC LIMIT 1
        """,
        (FOREX_DEMO_VENUE,),
    ).fetchone()
    if row is None:
        return computed
    return computed


async def _manage_open_positions(
    conn,
    cfg: ForexConfig,
    executor: ForexPaperExecutor,
    esf,
    ohlc_cache: dict[str, pd.DataFrame],
    *,
    ts_ms: int,
) -> int:
    exits = 0
    now = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    for pos, side in _open_forex_positions(conn):
        ohlc = ohlc_cache.get(pos.symbol)
        if ohlc is None or ohlc.empty:
            ohlc = _candles_to_ohlc(conn, pos.symbol, esf.timeframe)
            ohlc_cache[pos.symbol] = ohlc
        if ohlc.empty:
            continue
        bar = ohlc.iloc[-1]
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        stop = float(pos.context.get("stop", 0))
        target = float(pos.context.get("target", 0))
        if stop <= 0 or target <= 0:
            continue

        exit_price = None
        exit_reason = None
        if side == "long":
            if low <= stop:
                exit_price, exit_reason = stop, "stop"
            elif high >= target:
                exit_price, exit_reason = target, "target"
        else:
            if high >= stop:
                exit_price, exit_reason = stop, "stop"
            elif low <= target:
                exit_price, exit_reason = target, "target"

        opened = datetime.fromtimestamp(pos.opened_ts_ms / 1000, tz=UTC)
        if exit_price is None and opened.date() == now.date() and now.hour >= esf.flat_by_hour_utc:
            exit_price, exit_reason = close, "flat_time"

        if exit_price is None:
            continue

        close_side = Side.SELL if side == "long" else Side.BUY
        try:
            await executor.place_order(
                OrderRequest(
                    venue=Venue.FOREX_DEMO,
                    symbol=pos.symbol,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=pos.quantity,
                    reduce_only=True,
                    client_order_id=f"esf-exit-{pos.id}-{ts_ms}",
                )
            )
        except Exception as exc:
            logger.warning("exit order failed", extra={"symbol": pos.symbol, "err": str(exc)})
            continue

        stop_dist = abs(pos.entry_price - stop)
        sign = 1.0 if side == "long" else -1.0
        r_mult = sign * (exit_price - pos.entry_price) / stop_dist if stop_dist else 0.0
        realized = r_mult * pos.risk_amount_usd

        db.close_paper_position(
            conn,
            pos.id,
            closed_ts_ms=ts_ms,
            exit_price=exit_price,
            realized_pnl=realized,
            r_multiple=r_mult,
            exit_reason=exit_reason or "exit",
        )
        reflect_closed_position(
            conn,
            position_id=pos.id,
            strategy=STRATEGY_ID,
            venue=FOREX_DEMO_VENUE,
        )
        exits += 1
    return exits


def _signal_already_logged(conn, pair: str, bar_ts: pd.Timestamp) -> bool:
    bar_ms = int(bar_ts.timestamp() * 1000)
    row = conn.execute(
        """
        SELECT 1 FROM signals
        WHERE strategy = ? AND symbol = ? AND ts_ms >= ? AND ts_ms < ?
        LIMIT 1
        """,
        (STRATEGY_ID, pair, bar_ms, bar_ms + 3_600_000),
    ).fetchone()
    return row is not None


def main() -> None:
    import argparse

    from aegis.log import setup_logging

    setup_logging()
    parser = argparse.ArgumentParser(description="Event Spike Fade demo cycle")
    parser.add_argument("--config", default="config/forex.yaml")
    parser.add_argument("--loop", type=int, default=0, help="repeat every N seconds")
    args = parser.parse_args()
    cfg = load_forex_config(args.config)

    async def _once():
        summary = await run_event_fade_cycle(cfg)
        print(f"event_fade cycle: {summary}")

    if args.loop > 0:
        import asyncio

        while True:
            asyncio.run(_once())
            time.sleep(args.loop)
    else:
        import asyncio

        asyncio.run(_once())


if __name__ == "__main__":
    main()
