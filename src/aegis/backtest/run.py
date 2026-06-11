"""Backtest CLI: load a candle panel from SQLite, walk forward, report.

Usage (research, offline):
    aegis-backtest --db data/research.sqlite --venue binance --top 30
    aegis-backtest --db data/aegis.sqlite --venue hyperliquid

The report prints every M3 gate number: trade count, expectancy with 90% CI
net of costs, max drawdown vs the Monte Carlo envelope, and the per-pair
profit concentration check (no pair > 30%).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3

import pandas as pd

from aegis.backtest.engine import BacktestParams, run_backtest
from aegis.backtest.montecarlo import simulate_drawdown_envelope
from aegis.config import load_config
from aegis.log import setup_logging

logger = logging.getLogger(__name__)


def load_close_panel(
    db_path: str,
    venue: str,
    timeframe: str,
    symbols: list[str] | None = None,
    top: int | None = None,
) -> pd.DataFrame:
    """Close-price panel (rows = bars, columns = symbols) from the candles table."""
    conn = sqlite3.connect(db_path)
    try:
        if symbols is None:
            rows = conn.execute(
                """
                SELECT symbol, COUNT(*) AS n FROM candles
                WHERE venue = ? AND timeframe = ?
                GROUP BY symbol ORDER BY n DESC
                """,
                (venue, timeframe),
            ).fetchall()
            symbols = [r[0] for r in (rows[:top] if top else rows)]
        frames = {}
        for symbol in symbols:
            df = pd.read_sql_query(
                "SELECT open_time_ms, close FROM candles "
                "WHERE venue = ? AND symbol = ? AND timeframe = ? ORDER BY open_time_ms",
                conn,
                params=(venue, symbol, timeframe),
            )
            frames[symbol] = df.set_index("open_time_ms")["close"]
        panel = pd.DataFrame(frames)
        return panel
    finally:
        conn.close()


def print_report(result, envelope) -> None:
    lo, hi = result.expectancy_ci90()
    print("=" * 64)
    print("WALK-FORWARD BACKTEST REPORT")
    print("=" * 64)
    print(f"trades:            {len(result.trades)}  (M3 gate: >= 300)")
    print(f"refits:            {result.refits}")
    print(f"win rate:          {result.win_rate:.1%}")
    print(f"expectancy:        {result.expectancy_r:+.3f}R  90% CI [{lo:+.3f}, {hi:+.3f}]")
    print("  (M3 gate: CI lower bound > 0 net of full cost model)")
    print(f"max drawdown:      {result.max_drawdown_pct:.2%}")
    print(
        f"skips:             min-notional {result.skipped_below_min_notional}, "
        f"risk-budget {result.skipped_risk_budget}, edge-gate {result.skipped_edge_gate}"
    )
    pair_pnl = result.per_pair_pnl()
    total = sum(p for p in pair_pnl.values() if p > 0) or 1.0
    worst = max(pair_pnl.items(), key=lambda kv: kv[1], default=(None, 0))
    print(f"pairs traded:      {len(pair_pnl)}")
    if worst[0] is not None and worst[1] > 0:
        share = worst[1] / total
        print(f"top pair profit:   {worst[0]} = {share:.0%} of gross profit (gate: <= 30%)")
    if envelope is not None:
        print("-" * 64)
        print(
            "MONTE CARLO ENVELOPE "
            f"({envelope.n_paths} paths x {envelope.trades_per_path} trades, "
            f"risk {envelope.risk_pct:.2%})"
        )
        print(
            f"max DD median/p90/p95/p99: "
            f"{envelope.median_max_dd_pct:.1%} / {envelope.p90_max_dd_pct:.1%} / "
            f"{envelope.p95_max_dd_pct:.1%} / {envelope.p99_max_dd_pct:.1%}"
        )
        print(
            f"KILL SWITCH (p99 x 1.25):  {envelope.kill_switch_dd_pct:.1%} "
            "-> risk.kill_switch_drawdown_pct"
        )
        print(f"P(max DD >= 20%):          {envelope.prob_ruin_20pct:.1%}")
        print(f"median final return:       {envelope.median_final_return_pct:+.1%}")
    print("=" * 64)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis walk-forward backtest")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--db", required=True)
    parser.add_argument("--venue", default="hyperliquid")
    parser.add_argument("--timeframe", default=None, help="defaults to strategy_b bar timeframe")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--top", type=int, default=None, help="use top N symbols by bar count")
    parser.add_argument("--equity", type=float, default=1000.0)
    parser.add_argument("--risk-pct", type=float, default=0.0075)
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)

    timeframe = args.timeframe or cfg.strategy_b.bar_timeframe
    panel = load_close_panel(args.db, args.venue, timeframe, args.symbols, args.top)
    logger.info(
        "panel loaded",
        extra={"symbols": panel.shape[1], "bars": panel.shape[0], "venue": args.venue},
    )

    fees = cfg.hyperliquid.fees  # trade costs modeled at the live venue's schedule
    params = BacktestParams(initial_equity=args.equity, tier_risk_pct=args.risk_pct)
    result = run_backtest(panel, cfg.strategy_b, cfg.risk, fees, params)

    envelope = None
    if len(result.trades) >= 30:
        envelope = simulate_drawdown_envelope(result.r_multiples, risk_pct=args.risk_pct)
    print_report(result, envelope)


if __name__ == "__main__":
    main()
