"""Forex SCM research sweep — runs all fork variants and writes a report.

Executes:
  1. HistData import attempt + manual zip import
  2. Yahoo refresh for EURUSD + GBPUSD
  3. All setups × filter profiles × pairs
  4. 3 OOS windows per combination

Usage:
    aegis-forex-research-sweep
    aegis-forex-research-sweep --quick   # EURUSD only, 2 windows
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from aegis.backtest.forex_data import load_ohlc, slice_ohlc
from aegis.backtest.forex_scm_engine import passes_fx1_window, run_scm_backtest
from aegis.backtest.forex_scm_run import _auto_windows
from aegis.config_forex import ForexConfig, load_forex_config
from aegis.data.forex_download import aggregate_4h_from_1h, download_yahoo_all, import_histdata_csv
from aegis.data.forex_dxy import upsert_dxy_all_timeframes
from aegis.data.forex_histdata import (
    import_histdata_directory,
    try_download_histdata_range,
)
from aegis.log import setup_logging
from aegis.strategy.forex_confirms import load_calendar_event_times

FOREXSB_DIR = Path("data/forexsb")

SETUPS = (
    "london_breakout",
    "london_continuation",
    "ny_fade",
    "event_aftermath",
)

FILTER_PROFILES: dict[str, tuple[float, int]] = {
    "default": (0.40, 3),
    "tight": (0.25, 4),
}

PAIRS = ("EURUSD", "GBPUSD")


def import_forexsb_directory(db_path: str, directory: Path | None = None) -> int:
    """Import ``{PAIR}_H1.csv`` files from ``data/forexsb/``."""
    root = directory or FOREXSB_DIR
    if not root.exists():
        return 0
    total = 0
    for path in sorted(root.glob("*_H1.csv")):
        pair = path.stem.replace("_H1", "").upper()
        try:
            n = import_histdata_csv(db_path, path, pair)
            total += n
        except Exception:
            continue
    return total


def _clone_cfg(cfg: ForexConfig, *, setup: str, adr_pct: float, score: int) -> ForexConfig:
    scm = replace(
        cfg.scm,
        setup=setup,
        asian_range_max_adr_pct=adr_pct,
        confirm_score_threshold=score,
    )
    return replace(cfg, scm=scm)


def _run_variant(
    ohlc,
    dxy_ohlc,
    calendar_times,
    cfg: ForexConfig,
    pair: str,
    window_label: str,
    start: str,
    end: str,
) -> dict:
    panel = slice_ohlc(ohlc, start, end)
    dxy_panel = slice_ohlc(dxy_ohlc, start, end) if not dxy_ohlc.empty else dxy_ohlc
    if panel.empty:
        return {
            "window": window_label,
            "trades": 0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "ci_lo": float("nan"),
            "ci_hi": float("nan"),
            "pass": False,
            "raw_signals": 0,
        }
    result = run_scm_backtest(
        panel,
        cfg,
        symbol=pair,
        use_confirms=True,
        dxy_ohlc=dxy_panel,
        calendar_times_ms=calendar_times,
    )
    lo, hi = result.expectancy_ci90()
    ok, _ = passes_fx1_window(result, cfg)
    return {
        "window": window_label,
        "trades": len(result.trades),
        "win_rate": result.win_rate,
        "expectancy_r": result.expectancy_r,
        "ci_lo": lo,
        "ci_hi": hi,
        "pass": ok,
        "raw_signals": result.raw_signals,
        "skips": dict(result.confirm_skips),
    }


def run_sweep(cfg: ForexConfig, *, quick: bool = False) -> list[dict]:
    db_path = cfg.research.sqlite_path
    pairs = ("EURUSD",) if quick else PAIRS
    setups = ("london_continuation", "ny_fade") if quick else SETUPS

    # --- Deep history: ForexSB CSV + HistData zips ---
    forexsb_bars = import_forexsb_directory(db_path)
    auto_dl = try_download_histdata_range(db_path, "EURUSD", 2015, 2022)
    manual = import_histdata_directory(db_path, "EURUSD")
    manual += import_histdata_directory(db_path, "GBPUSD")
    histdata_bars = forexsb_bars + auto_dl + manual

    # Refresh Yahoo + DXY
    download_yahoo_all(cfg, pairs=list(pairs) + list(cfg.dxy_pairs))
    aggregate_4h_from_1h(db_path, list(pairs) + list(cfg.dxy_pairs))
    upsert_dxy_all_timeframes(cfg)

    calendar_times = load_calendar_event_times(db_path, cfg.calendar)
    dxy_ohlc = load_ohlc(db_path, cfg.dxy.symbol, timeframe="1h")

    rows: list[dict] = []
    for pair in pairs:
        ohlc = load_ohlc(db_path, pair, timeframe="1h")
        if ohlc.empty:
            continue
        windows = _auto_windows(ohlc)
        if quick and len(windows) > 2:
            windows = windows[:2]

        for setup in setups:
            for profile_name, (adr_pct, score) in FILTER_PROFILES.items():
                variant_cfg = _clone_cfg(cfg, setup=setup, adr_pct=adr_pct, score=score)
                window_passes = 0
                window_results = []
                for label, start, end in windows:
                    wr = _run_variant(
                        ohlc,
                        dxy_ohlc,
                        calendar_times,
                        variant_cfg,
                        pair,
                        label,
                        start,
                        end,
                    )
                    window_results.append(wr)
                    if wr["pass"]:
                        window_passes += 1

                avg_wr = sum(w["win_rate"] for w in window_results) / max(len(window_results), 1)
                avg_exp = sum(w["expectancy_r"] for w in window_results) / max(len(window_results), 1)
                total_trades = sum(w["trades"] for w in window_results)

                rows.append(
                    {
                        "pair": pair,
                        "setup": setup,
                        "filters": profile_name,
                        "adr_pct": adr_pct,
                        "score_threshold": score,
                        "windows_pass": window_passes,
                        "windows_total": len(windows),
                        "total_trades": total_trades,
                        "avg_win_rate": avg_wr,
                        "avg_expectancy_r": avg_exp,
                        "window_detail": window_results,
                        "histdata_bars_imported": histdata_bars,
                    }
                )
    return rows


def write_report(rows: list[dict], path: Path) -> None:
    lines = [
        "# Forex SCM Research Sweep",
        "",
        f"*Generated {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        "## Summary table",
        "",
        "| Pair | Setup | Filters | W pass | Trades | Avg WR | Avg Exp (R) |",
        "| ---- | ----- | ------- | ------ | ------ | ------ | ----------- |",
    ]
    for r in sorted(rows, key=lambda x: (-x["windows_pass"], -x["avg_expectancy_r"])):
        lines.append(
            f"| {r['pair']} | {r['setup']} | {r['filters']} | "
            f"{r['windows_pass']}/{r['windows_total']} | {r['total_trades']} | "
            f"{r['avg_win_rate']:.1%} | {r['avg_expectancy_r']:+.3f} |"
        )

    best = max(rows, key=lambda x: (x["windows_pass"], x["avg_expectancy_r"]), default=None)
    lines.extend(["", "## Best variant", ""])
    if best:
        lines.append(
            f"**{best['pair']} · {best['setup']} · {best['filters']}** — "
            f"{best['windows_pass']}/{best['windows_total']} windows, "
            f"avg {best['avg_expectancy_r']:+.3f}R, WR {best['avg_win_rate']:.1%}"
        )
    else:
        lines.append("No results.")

    lines.extend(["", "## Deep history import", ""])
    hist = rows[0]["histdata_bars_imported"] if rows else 0
    lines.append(
        f"ForexSB + HistData bars imported: **{hist}**. "
        "Place ForexSB CSVs at `data/forexsb/{PAIR}_H1.csv`."
    )

    lines.extend(["", "## Per-window detail (top 5 variants)", ""])
    top5 = sorted(rows, key=lambda x: (-x["windows_pass"], -x["avg_expectancy_r"]))[:5]
    for r in top5:
        lines.append(f"### {r['pair']} {r['setup']} {r['filters']}")
        for w in r["window_detail"]:
            lines.append(
                f"- {w['window']}: {w['trades']} trades, WR {w['win_rate']:.1%}, "
                f"{w['expectancy_r']:+.3f}R, pass={w['pass']}"
            )
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex SCM full research sweep")
    parser.add_argument("--forex-config", default="config/forex.yaml")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--report", default="research/forex/forex-scm-sweep-report.md")
    args = parser.parse_args()

    setup_logging("logs", "INFO")
    cfg = load_forex_config(args.forex_config)
    rows = run_sweep(cfg, quick=args.quick)
    write_report(rows, Path(args.report))

    if not rows:
        print("No sweep results — check data/forex_research.sqlite")
        sys.exit(1)

    best = max(rows, key=lambda x: (x["windows_pass"], x["avg_expectancy_r"]))
    print(f"Sweep complete: {len(rows)} variants, report → {args.report}")
    print(
        f"Best: {best['pair']} {best['setup']} {best['filters']} — "
        f"{best['windows_pass']}/{best['windows_total']} windows, "
        f"avg {best['avg_expectancy_r']:+.3f}R"
    )
    # Exit 0 if any variant passes >=2 windows
    any_pass = any(r["windows_pass"] >= 2 for r in rows)
    sys.exit(0 if any_pass else 1)


if __name__ == "__main__":
    main()
