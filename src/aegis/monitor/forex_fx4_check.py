"""FX4 gate check — demo infra smoke.

Validates OANDA/Yahoo ingest, execution model, paper round-trip, reconcile,
and frozen config hash.

Usage:
    aegis-forex-fx4-check
    aegis-forex-fx4-check --round-trip
    aegis-forex-fx4-check --ingest-hours 72
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta

from aegis.config import load_config
from aegis.config_forex import load_forex_config
from aegis.core.models import OrderRequest, OrderType, Side, Venue
from aegis.core.timeframes import timeframe_ms
from aegis.data import db
from aegis.data.forex_ingest import run_forex_ingest
from aegis.execution.forex_market_data import build_forex_market_data
from aegis.execution.forex_paper import FOREX_DEMO_VENUE, ForexPaperExecutor
from aegis.monitor.forex_config_freeze import forex_config_hash, verify_or_freeze_forex_config
from aegis.monitor.forex_reconcile import reconcile_forex_demo
from aegis.risk.forex_execution_model import simulate_fill, quote_from_mid
from aegis.strategy.forex_strategy_registry import active_strategy_spec


def _check_ingest_coverage(conn, pair: str, *, hours: int) -> tuple[bool, str]:
    tf = "1h"
    interval_ms = timeframe_ms(tf)
    last = db.last_candle_open_ms(conn, Venue.FOREX_DEMO, pair, tf)
    first = db.first_candle_open_ms(conn, Venue.FOREX_DEMO, pair, tf)
    if first is None or last is None:
        return False, f"{pair}: no candles"

    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    # Yahoo forex 1h can lag ~1 day; anchor coverage on latest stored bar.
    if now_ms - last > 48 * 3_600_000:
        return False, f"{pair}: latest bar stale ({(now_ms - last) // 3_600_000}h old)"

    window_start = last - hours * 3_600_000
    gaps = db.find_gaps(conn, Venue.FOREX_DEMO, pair, tf, interval_ms)
    recent_gaps = [g for g in gaps if g[0] >= window_start]
    count = conn.execute(
        """
        SELECT COUNT(*) FROM candles
        WHERE venue = ? AND symbol = ? AND timeframe = ?
          AND open_time_ms > ? AND open_time_ms <= ?
        """,
        (Venue.FOREX_DEMO.value, pair, tf, window_start, last),
    ).fetchone()[0]
    expected = max(1, hours - 2)
    if count < expected * 0.75:
        return False, f"{pair}: only {count} bars in latest {hours}h window (expected ~{expected})"
    if len(recent_gaps) > 2:
        return False, f"{pair}: {len(recent_gaps)} gaps in latest {hours}h"
    return True, f"{pair}: {count} bars ending at latest close, {len(recent_gaps)} gaps"


async def _paper_round_trip(cfg, conn) -> tuple[bool, str]:
    aegis_cfg = load_config()
    md = build_forex_market_data(cfg, aegis_cfg.secrets, conn=conn)
    executor = ForexPaperExecutor(conn, md, cfg)
    pair = cfg.event_spike_fade.pairs[0]
    lots = cfg.event_spike_fade.lots
    stamp = int(time.time())

    buy_id = await executor.place_order(
        OrderRequest(
            venue=Venue.FOREX_DEMO,
            symbol=pair,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=lots,
            client_order_id=f"fx4-check-buy-{stamp}",
        )
    )
    sell_id = await executor.place_order(
        OrderRequest(
            venue=Venue.FOREX_DEMO,
            symbol=pair,
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=lots,
            client_order_id=f"fx4-check-sell-{stamp}",
            reduce_only=True,
        )
    )
    buy_fills = await executor.fetch_fills(pair, buy_id)
    sell_fills = await executor.fetch_fills(pair, sell_id)
    if not buy_fills or not sell_fills:
        return False, "round-trip missing fills"
    db.insert_equity_snapshot(
        conn,
        ts_ms=int(time.time() * 1000),
        venue=FOREX_DEMO_VENUE,
        equity_usd=cfg.demo.equity_usd,
        mode="forex_paper",
    )
    return True, f"round-trip {pair} buy@{buy_fills[0].price:.5f} sell@{sell_fills[0].price:.5f}"


def run_fx4_check(
    config_path: str = "config/forex.yaml",
    *,
    ingest_hours: int = 72,
    do_round_trip: bool = False,
    skip_ingest: bool = False,
) -> int:
    cfg = load_forex_config(config_path)
    failures: list[str] = []
    aegis_cfg = load_config()

    print(f"forex FX4 check: active_strategy={cfg.active_strategy}")
    spec = active_strategy_spec(cfg)
    print(f"  edge_type={spec.edge_type.value} status={spec.status}")
    print(f"  hypothesis: {spec.hypothesis[:72]}...")

    # Execution model smoke
    q = quote_from_mid("EURUSD", 1.1000, cfg.costs, ts_ms=int(time.time() * 1000))
    fill = simulate_fill(q, Side.BUY, cfg.costs, cfg.execution)
    print(
        f"execution model: spread={q.spread_pips:.2f}p "
        f"slip={fill.slippage_pips:.2f}p skipped={fill.skipped}"
    )
    if fill.skipped and fill.skip_reason == "broker_requote":
        print("  (requote skip is stochastic — re-run if this fails alone)")

    conn = db.connect(cfg.demo.sqlite_path)
    try:
        digest = verify_or_freeze_forex_config(conn, cfg)
        print(f"config freeze: hash={digest} (expected FX3 recipe)")

        if not skip_ingest:
            print("running ingest for frozen pairs...")
            report = asyncio.run(
                run_forex_ingest(cfg, timeframes=("1h",), backfill_days=max(7, ingest_hours // 24 + 2))
            )
            print(f"  inserted={report.inserted} unfilled_gaps={report.unfilled_gaps}")
            if report.unfilled_gaps > 5:
                failures.append(f"ingest unfilled_gaps={report.unfilled_gaps}")

        for pair in cfg.event_spike_fade.pairs:
            ok, msg = _check_ingest_coverage(conn, pair, hours=ingest_hours)
            print(f"ingest coverage: {msg}")
            if not ok:
                failures.append(msg)

        if do_round_trip:
            try:
                ok, msg = asyncio.run(_paper_round_trip(cfg, conn))
                print(f"paper round-trip: {msg}")
                if not ok:
                    failures.append(msg)
            except Exception as exc:
                failures.append(f"round-trip failed: {exc}")

        # Ensure equity snapshot exists when fills present (smoke / partial runs).
        if db.count_fills(conn, FOREX_DEMO_VENUE) and conn.execute(
            "SELECT 1 FROM equity_snapshots WHERE venue = ? LIMIT 1", (FOREX_DEMO_VENUE,)
        ).fetchone() is None:
            db.insert_equity_snapshot(
                conn,
                ts_ms=int(time.time() * 1000),
                venue=FOREX_DEMO_VENUE,
                equity_usd=cfg.demo.equity_usd,
                mode="forex_paper",
            )

        ok, issues = reconcile_forex_demo(conn, starting_equity=cfg.demo.equity_usd)
        if not ok:
            failures.extend(issues)
        else:
            print(f"reconcile: PASS (fills={db.count_fills(conn, FOREX_DEMO_VENUE)})")

        print(f"Demo data source: {cfg.demo.data_source} (yahoo = open-source default)")
    finally:
        conn.close()

    print(f"\nFX4 principles: see research/forex-edge-framework.md")
    print(f"  paper gate: {cfg.demo.paper_days_min}–{cfg.demo.paper_days_max} days, "
          f">= {cfg.demo.min_closed_trades} trades")

    if failures:
        print("\nFX4 GATE: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nFX4 GATE: PASS (demo infra ready for FX5 paper)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="FX4 demo infrastructure gate")
    parser.add_argument("--config", default="config/forex.yaml")
    parser.add_argument("--ingest-hours", type=int, default=72)
    parser.add_argument("--round-trip", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    args = parser.parse_args()
    sys.exit(
        run_fx4_check(
            args.config,
            ingest_hours=args.ingest_hours,
            do_round_trip=args.round_trip,
            skip_ingest=args.skip_ingest,
        )
    )


if __name__ == "__main__":
    main()
