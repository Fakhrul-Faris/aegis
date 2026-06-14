"""Forex SCM backtest CLI (FX1).

Usage:
    aegis-backtest-forex-scm
    aegis-backtest-forex-scm --pair EURUSD --window 2024-01-01 2024-12-31

Default: three OOS windows on available hourly data in forex_research.sqlite.
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from aegis.backtest.forex_data import load_ohlc, slice_ohlc
from aegis.backtest.forex_scm_engine import passes_fx1_window, run_scm_backtest
from aegis.backtest.montecarlo import simulate_drawdown_envelope
from aegis.config_forex import load_forex_config
from aegis.log import setup_logging
from aegis.strategy.forex_confirms import load_calendar_event_times

logger = logging.getLogger(__name__)

# Target OOS windows from milestone; fall back to data-driven splits when hourly
# history is shorter than 10 years (Yahoo 730d cap).
TARGET_WINDOWS: list[tuple[str, str, str]] = [
    ("2015-2017", "2015-01-01", "2017-12-31"),
    ("2019-2021", "2019-01-01", "2021-12-31"),
    ("2023-2025", "2023-01-01", "2025-12-31"),
]


def _auto_windows(ohlc: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Split available hourly span into three equal OOS slices."""
    if ohlc.empty:
        return []
    start = ohlc.index.min()
    end = ohlc.index.max()
    span = end - start
    third = span / 3
    windows = []
    for i, label in enumerate(("W1-oldest", "W2-mid", "W3-newest")):
        w_start = start + third * i
        w_end = start + third * (i + 1) if i < 2 else end
        windows.append(
            (label, w_start.strftime("%Y-%m-%d"), w_end.strftime("%Y-%m-%d"))
        )
    return windows


def _pick_windows(ohlc: pd.DataFrame, use_target: bool) -> list[tuple[str, str, str]]:
    if not use_target:
        auto = _auto_windows(ohlc)
        return auto if auto else TARGET_WINDOWS
    usable = []
    for label, start, end in TARGET_WINDOWS:
        sl = slice_ohlc(ohlc, start, end)
        if len(sl) >= 24 * 30:
            usable.append((label, start, end))
    return usable if usable else _auto_windows(ohlc)


def print_window_report(
    label: str,
    start: str,
    end: str,
    result,
    cfg,
    envelope,
) -> bool:
    lo, hi = result.expectancy_ci90()
    ok, reasons = passes_fx1_window(result, cfg)
    mode = f"{cfg.scm.setup}" + (" + confirms" if result.use_confirms else " spine")
    print("=" * 64)
    print(f"SCM BACKTEST ({mode}) — {label}  [{start} → {end}]")
    print("=" * 64)
    if result.use_confirms:
        print(f"raw signals:       {result.raw_signals}")
        if result.confirm_skips:
            print(f"confirm skips:     {result.confirm_skips}")
    print(f"trades:            {len(result.trades)}  (gate: >= {cfg.scm.backtest_min_trades_per_window})")
    print(f"win rate:          {result.win_rate:.1%}  (gate: >= {cfg.scm.backtest_min_win_rate:.0%})")
    print(f"expectancy:        {result.expectancy_r:+.3f}R  90% CI [{lo:+.3f}, {hi:+.3f}]")
    print(f"max drawdown:      {result.max_drawdown_pct:.2%}")
    if envelope is not None and result.trades:
        print(f"MC kill (p99×1.25): {envelope.kill_switch_dd_pct:.1%}")
    print(f"FX1/FX2 window:    {'PASS' if ok else 'FAIL'}")
    if reasons:
        for r in reasons:
            print(f"  - {r}")
    print("=" * 64)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex SCM session breakout backtest")
    parser.add_argument("--forex-config", default="config/forex.yaml")
    parser.add_argument("--pair", default="EURUSD")
    parser.add_argument("--db", default=None)
    parser.add_argument("--equity", type=float, default=100.0)
    parser.add_argument("--risk-pct", type=float, default=0.0075)
    parser.add_argument("--lots", type=float, default=0.01)
    parser.add_argument(
        "--target-windows",
        action="store_true",
        help="use milestone 2015/2019/2023 windows when enough hourly bars exist",
    )
    parser.add_argument("--window", nargs=2, metavar=("START", "END"), default=None)
    parser.add_argument(
        "--no-confirms",
        action="store_true",
        help="FX1 spine only (disable ADR/DXY/calendar confirms)",
    )
    parser.add_argument("--ablation", action="store_true", help="run spine + confirms side by side")
    args = parser.parse_args()

    cfg = load_forex_config(args.forex_config)
    setup_logging("logs", "INFO")
    db_path = args.db or cfg.research.sqlite_path

    ohlc = load_ohlc(db_path, args.pair.upper(), timeframe="1h")
    if ohlc.empty:
        print(f"No 1h data for {args.pair} in {db_path}. Run aegis-forex-download --yahoo.")
        sys.exit(1)

    dxy_symbol = cfg.dxy.symbol
    dxy_ohlc = load_ohlc(db_path, dxy_symbol, timeframe="1h")
    calendar_times = load_calendar_event_times(db_path, cfg.calendar)

    logger.info(
        "scm panel loaded",
        extra={
            "pair": args.pair,
            "bars": len(ohlc),
            "from": str(ohlc.index.min()),
            "to": str(ohlc.index.max()),
        },
    )

    if args.window:
        windows = [("custom", args.window[0], args.window[1])]
    else:
        windows = _pick_windows(ohlc, args.target_windows)

    passes = 0
    for label, start, end in windows:
        panel = slice_ohlc(ohlc, start, end)
        if panel.empty:
            print(f"SKIP {label}: no data in range")
            continue
        dxy_panel = slice_ohlc(dxy_ohlc, start, end) if not dxy_ohlc.empty else dxy_ohlc

        if args.ablation:
            print("\n--- ABLATION: spine vs confirms ---")
            for use_conf in (False, True):
                tag = "spine" if not use_conf else "confirms"
                result = run_scm_backtest(
                    panel,
                    cfg,
                    symbol=args.pair.upper(),
                    starting_equity=args.equity,
                    risk_pct=args.risk_pct,
                    lots=args.lots,
                    use_confirms=use_conf,
                    dxy_ohlc=dxy_panel,
                    calendar_times_ms=calendar_times,
                )
                envelope = (
                    simulate_drawdown_envelope(result.r_multiples)
                    if len(result.trades) >= 30
                    else None
                )
                print_window_report(f"{label}-{tag}", start, end, result, cfg, envelope)
            continue

        result = run_scm_backtest(
            panel,
            cfg,
            symbol=args.pair.upper(),
            starting_equity=args.equity,
            risk_pct=args.risk_pct,
            lots=args.lots,
            use_confirms=not args.no_confirms,
            dxy_ohlc=dxy_panel,
            calendar_times_ms=calendar_times,
        )
        envelope = None
        if len(result.trades) >= 30:
            envelope = simulate_drawdown_envelope(result.r_multiples)
        if print_window_report(label, start, end, result, cfg, envelope):
            passes += 1

    need = 2
    label = "FX2" if not args.no_confirms else "FX1"
    print(f"\nSUMMARY: {passes}/{len(windows)} windows passed {label} gates (need >={need})")
    sys.exit(0 if passes >= need else 1)


if __name__ == "__main__":
    main()
