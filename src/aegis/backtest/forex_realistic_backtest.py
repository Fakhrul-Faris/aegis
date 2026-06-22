"""Realistic forex backtest — execution stress overlay on frozen recipe (FX4).

Applies 1–3 pip per-fill slippage on top of Fusion spread + commission.

Usage:
    aegis-backtest-forex-realistic
    aegis-backtest-forex-realistic --worst-case
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from aegis.backtest.forex_data import load_ohlc, slice_ohlc
from aegis.backtest.forex_h11b_sweep import passes_event_gate
from aegis.backtest.forex_h11c_sweep import merge_results, run_pair_signals
from aegis.backtest.forex_scm_engine import ScmBacktestResult, ScmTrade, run_signals_backtest
from aegis.backtest.forex_scm_run import _auto_windows
from aegis.backtest.montecarlo import simulate_drawdown_envelope
from aegis.config_forex import load_forex_config
from aegis.data import db
from aegis.data.forex_calendar import seed_economic_calendar
from aegis.log import setup_logging
from aegis.monitor.forex_config_freeze import params_from_esf_config, verify_or_freeze_forex_config
from aegis.risk.forex_execution_model import realistic_round_trip_costs_usd
from aegis.strategy.forex_confirms import load_calendar_events


def _augment_result(cfg: ForexConfig, result: ScmBacktestResult, pair: str) -> ScmBacktestResult:
    esf = cfg.event_spike_fade
    trades: list[ScmTrade] = []
    for t in result.trades:
        _, extra = realistic_round_trip_costs_usd(cfg, pair, esf.lots, near_event=True)
        trades.append(
            ScmTrade(
                symbol=t.symbol,
                direction=t.direction,
                entry_ts=t.entry_ts,
                exit_ts=t.exit_ts,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                stop_price=t.stop_price,
                target_price=t.target_price,
                exit_reason=t.exit_reason,
                risk_amount_usd=t.risk_amount_usd,
                notional_usd=t.notional_usd,
                costs_usd=t.costs_usd + extra,
            )
        )
    result.trades = trades
    return result


def _run_window_realistic(cfg: ForexConfig, ohlc_by_pair, events, start, end):
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    event_panel = [
        e for e in events if start_ts <= pd.Timestamp(e.ts_ms, unit="ms", tz="UTC") <= end_ts
    ]
    params = params_from_esf_config(cfg)
    esf = cfg.event_spike_fade
    pair_results = []
    breakdown: list[str] = []

    for pair in esf.pairs:
        panel = slice_ohlc(ohlc_by_pair.get(pair, pd.DataFrame()), start, end)
        if panel.empty:
            continue
        signals = run_pair_signals(pair, panel, event_panel, cfg, params)
        result = run_signals_backtest(
            panel,
            cfg,
            signals,
            symbol=pair,
            risk_pct=esf.risk_pct,
            lots=esf.lots,
        )
        pair_results.append(_augment_result(cfg, result, pair))
        breakdown.append(f"{pair}:{len(result.trades)}")

    if not pair_results:
        return None, ""
    combined = merge_results(pair_results) if len(pair_results) > 1 else pair_results[0]
    return combined, " ".join(breakdown)


def _print_window(label, start, end, result, cfg, breakdown: str = "") -> bool:
    lo, hi = result.expectancy_ci90()
    ok, reasons = passes_event_gate(
        result,
        min_trades=cfg.demo.min_closed_trades,
        min_wr=cfg.scm.demo_min_win_rate,
    )
    print("=" * 64)
    print(f"REALISTIC BACKTEST — {label}  [{start} → {end}]")
    if breakdown:
        print(f"pairs:        {breakdown}")
    print(f"trades:       {len(result.trades)}")
    print(f"win rate:     {result.win_rate:.1%}")
    print(f"expectancy:   {result.expectancy_r:+.3f}R  90% CI [{lo:+.3f}, {hi:+.3f}]")
    print(f"max drawdown: {result.max_drawdown_pct:.2%}")
    print(f"window:       {'PASS' if ok else 'FAIL'}")
    for r in reasons:
        print(f"  - {r}")
    print("=" * 64)
    return ok


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Realistic forex backtest (FX4 stress)")
    parser.add_argument("--config", default="config/forex.yaml")
    parser.add_argument("--worst-case", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    cfg = load_forex_config(args.config)
    if args.worst_case:
        cfg = replace(
            cfg,
            execution=replace(cfg.execution, use_worst_case_slippage=True),
        )

    db_path = args.db or cfg.research.sqlite_path
    conn = db.connect(db_path)
    try:
        seed_economic_calendar(conn)
        digest = verify_or_freeze_forex_config(conn, cfg)
    finally:
        conn.close()

    events = load_calendar_events(
        db_path,
        cfg.calendar,
        currencies=cfg.calendar.event_spike_currencies,
        tiers=cfg.calendar.event_spike_tiers,
    )

    esf = cfg.event_spike_fade
    ohlc_by_pair = {p: load_ohlc(db_path, p, esf.timeframe) for p in esf.pairs}
    ref = ohlc_by_pair[esf.pairs[0]]
    if ref.empty:
        print("No OHLC data")
        sys.exit(1)

    mode = "worst-case 3pip" if args.worst_case else "mean 1.5pip"
    print(f"Realistic overlay: {mode}  hash={digest}")

    windows = _auto_windows(ref)
    passes = 0
    for label, start, end in windows:
        result, breakdown = _run_window_realistic(cfg, ohlc_by_pair, events, start, end)
        if result is None:
            print(f"SKIP {label}: no data")
            continue
        if _print_window(label, start, end, result, cfg, breakdown):
            passes += 1

    out = Path("research/forex/forex-realistic-verdict.md")
    out.write_text(
        "\n".join(
            [
                "# Forex realistic backtest verdict",
                "",
                f"*Generated {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
                "",
                f"**Mode:** {mode}",
                f"**Config hash:** `{digest}`",
                f"**Result:** {passes}/{len(windows)} windows pass event gate",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {out}")
    sys.exit(0 if passes >= 2 else 1)


if __name__ == "__main__":
    main()
