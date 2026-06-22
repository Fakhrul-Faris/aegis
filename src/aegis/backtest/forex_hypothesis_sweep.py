"""Run all FX-A.6 hypotheses (H1–H26) and write verdict report.

Usage:
    aegis-forex-hypothesis-sweep
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from aegis.backtest.forex_data import load_ohlc, slice_ohlc
from aegis.backtest.forex_scm_engine import passes_fx1_window, run_signals_backtest
from aegis.backtest.forex_scm_run import _auto_windows
from aegis.config_forex import ForexConfig, load_forex_config
from aegis.data.forex_download import aggregate_4h_from_1h, download_yahoo_all, import_histdata_csv
from aegis.data.forex_dxy import upsert_dxy_all_timeframes
from aegis.log import setup_logging
from aegis.strategy.forex_confirms import build_confirm_context, load_calendar_event_times
from aegis.strategy.forex_hypothesis_specs import (
    HypothesisSpec,
    apply_filters,
    build_hypothesis_matrix,
    detect_for_spec,
)
from aegis.strategy.forex_session import compute_asian_ranges

FOREXSB_DIR = Path("data/forexsb")


def import_forexsb_all(db_path: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not FOREXSB_DIR.exists():
        return counts
    for path in sorted(FOREXSB_DIR.glob("*.csv")):
        stem = path.stem.upper()
        if stem.endswith("_H1"):
            pair, tf = stem[:-3], "1h"
        elif stem.endswith("_M15"):
            pair, tf = stem[:-4], "15m"
        else:
            continue
        n = import_histdata_csv(db_path, path, pair, timeframe=tf)
        counts[f"{pair}_{tf}"] = n
    return counts


def _calendar_for_pair(db_path: str, cfg: ForexConfig, spec: HypothesisSpec) -> list[int]:
    return load_calendar_event_times(
        db_path,
        cfg.calendar,
        currencies=spec.calendar_currencies,
    )


def _run_spec_window(
    spec: HypothesisSpec,
    ohlc,
    dxy_ohlc,
    calendar_times,
    cfg: ForexConfig,
    start: str,
    end: str,
) -> dict:
    panel = slice_ohlc(ohlc, start, end)
    if panel.empty:
        return {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "pass": False}

    ranges = compute_asian_ranges(panel, cfg.sessions)
    raw = detect_for_spec(spec, panel, cfg.sessions, calendar_times, ranges, dxy_ohlc)
    ctx = build_confirm_context(panel, dxy_ohlc, cfg, calendar_times_ms=calendar_times)
    signals = apply_filters(
        raw,
        spec,
        ohlc=panel,
        asian_ranges=ranges,
        ctx=ctx,
        cfg=cfg,
        event_times_ms=calendar_times,
    )
    result = run_signals_backtest(
        panel,
        cfg,
        signals,
        symbol=spec.pair,
        time_stop_hours=spec.time_stop_hours,
    )
    lo, hi = result.expectancy_ci90()
    ok, _ = passes_fx1_window(result, cfg)
    return {
        "trades": len(result.trades),
        "raw_signals": len(raw),
        "filtered_signals": len(signals),
        "win_rate": result.win_rate,
        "expectancy_r": result.expectancy_r,
        "ci_lo": lo,
        "ci_hi": hi,
        "pass": ok,
    }


def run_hypothesis_sweep(cfg: ForexConfig) -> tuple[list[dict], dict[str, int]]:
    db_path = cfg.research.sqlite_path
    imports = import_forexsb_all(db_path)

    pairs = sorted({s.pair for s in build_hypothesis_matrix() if not s.skipped})
    download_yahoo_all(cfg, pairs=list(pairs) + list(cfg.dxy_pairs))
    aggregate_4h_from_1h(db_path, list(pairs) + list(cfg.dxy_pairs))
    upsert_dxy_all_timeframes(cfg)

    dxy_ohlc = load_ohlc(db_path, cfg.dxy.symbol, timeframe="1h")
    rows: list[dict] = []

    for spec in build_hypothesis_matrix():
        if spec.skipped:
            rows.append(
                {
                    "hid": spec.hid,
                    "name": spec.name,
                    "pair": spec.pair,
                    "timeframe": spec.timeframe,
                    "skipped": True,
                    "skip_reason": spec.skip_reason,
                    "windows_pass": 0,
                    "windows_total": 0,
                    "total_trades": 0,
                    "avg_win_rate": 0.0,
                    "avg_expectancy_r": 0.0,
                    "window_detail": [],
                }
            )
            continue

        ohlc = load_ohlc(db_path, spec.pair, timeframe=spec.timeframe)
        if ohlc.empty:
            rows.append(
                {
                    "hid": spec.hid,
                    "name": spec.name,
                    "pair": spec.pair,
                    "timeframe": spec.timeframe,
                    "skipped": True,
                    "skip_reason": f"no {spec.timeframe} data for {spec.pair}",
                    "windows_pass": 0,
                    "windows_total": 0,
                    "total_trades": 0,
                    "avg_win_rate": 0.0,
                    "avg_expectancy_r": 0.0,
                    "window_detail": [],
                }
            )
            continue

        cal = _calendar_for_pair(db_path, cfg, spec)
        windows = _auto_windows(ohlc)
        window_results = []
        passes = 0
        for label, start, end in windows:
            wr = _run_spec_window(spec, ohlc, dxy_ohlc, cal, cfg, start, end)
            wr["window"] = label
            window_results.append(wr)
            if wr["pass"]:
                passes += 1

        n = len(window_results)
        rows.append(
            {
                "hid": spec.hid,
                "name": spec.name,
                "pair": spec.pair,
                "timeframe": spec.timeframe,
                "skipped": False,
                "skip_reason": "",
                "windows_pass": passes,
                "windows_total": n,
                "total_trades": sum(w["trades"] for w in window_results),
                "avg_win_rate": sum(w["win_rate"] for w in window_results) / max(n, 1),
                "avg_expectancy_r": sum(w["expectancy_r"] for w in window_results) / max(n, 1),
                "window_detail": window_results,
            }
        )

    return rows, imports


def write_report(rows: list[dict], imports: dict[str, int], path: Path) -> None:
    runnable = [r for r in rows if not r.get("skipped")]
    passed = [r for r in runnable if r["windows_pass"] >= 2]

    lines = [
        "# Forex Hypothesis Sweep (H1–H26)",
        "",
        f"*Generated {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        f"**Runnable:** {len(runnable)} · **Passed gate (≥2/3 windows):** {len(passed)}",
        "",
        "## Data imported",
        "",
    ]
    for k, v in sorted(imports.items()):
        lines.append(f"- `{k}`: {v:,} bars")
    if not imports:
        lines.append("- (re-import skipped — data already in DB)")

    lines.extend(
        [
            "",
            "## Summary (runnable only)",
            "",
            "| ID | Hypothesis | Pair | TF | W pass | Trades | Avg WR | Avg Exp |",
            "| -- | ---------- | ---- | -- | ------ | ------ | ------ | ------- |",
        ]
    )
    for r in sorted(runnable, key=lambda x: (-x["windows_pass"], -x["avg_expectancy_r"])):
        lines.append(
            f"| {r['hid']} | {r['name']} | {r['pair']} | {r['timeframe']} | "
            f"{r['windows_pass']}/{r['windows_total']} | {r['total_trades']} | "
            f"{r['avg_win_rate']:.1%} | {r['avg_expectancy_r']:+.3f} |"
        )

    lines.extend(["", "## Skipped", ""])
    for r in rows:
        if r.get("skipped"):
            lines.append(f"- **{r['hid']}** {r['name']}: {r['skip_reason']}")

    if passed:
        lines.extend(["", "## Passed gate", ""])
        for r in passed:
            lines.append(
                f"- **{r['hid']}** {r['name']} — {r['windows_pass']}/{r['windows_total']} windows, "
                f"WR {r['avg_win_rate']:.1%}, {r['avg_expectancy_r']:+.3f}R"
            )
    else:
        lines.extend(["", "## Passed gate", "", "None."])

    lines.extend(["", "## Top 10 by expectancy", ""])
    for r in sorted(runnable, key=lambda x: -x["avg_expectancy_r"])[:10]:
        lines.append(f"### {r['hid']} — {r['name']}")
        for w in r["window_detail"]:
            lines.append(
                f"- {w['window']}: {w['trades']} trades, WR {w['win_rate']:.1%}, "
                f"{w['expectancy_r']:+.3f}R, pass={w['pass']}"
            )
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex hypothesis sweep H1–H26")
    parser.add_argument("--forex-config", default="config/forex.yaml")
    parser.add_argument("--report", default="research/forex/forex-hypothesis-sweep-report.md")
    parser.add_argument("--verdict", default="research/forex/forex-hypothesis-sweep-verdict.md")
    args = parser.parse_args()

    setup_logging("logs", "INFO")
    cfg = load_forex_config(args.forex_config)
    rows, imports = run_hypothesis_sweep(cfg)
    write_report(rows, imports, Path(args.report))

    runnable = [r for r in rows if not r.get("skipped")]
    passed = [r for r in runnable if r["windows_pass"] >= 2]
    best = max(runnable, key=lambda x: (x["windows_pass"], x["avg_expectancy_r"]), default=None)

    verdict_lines = [
        "# Forex Hypothesis Sweep — Verdict",
        "",
        f"*Generated {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        f"Tested **{len(runnable)}** hypotheses on ForexSB deep history (2010–2026).",
        f"**{len(passed)}** passed FX3 gate (≥2/3 windows, ≥80 trades, ≥60% WR, CI>0).",
        "",
    ]
    if best:
        verdict_lines.append(
            f"Best: **{best['hid']} {best['name']}** — "
            f"{best['windows_pass']}/{best['windows_total']} windows, "
            f"WR {best['avg_win_rate']:.1%}, {best['avg_expectancy_r']:+.3f}R"
        )
    if passed:
        verdict_lines.extend(["", "## Go candidates", ""])
        for r in passed:
            verdict_lines.append(f"- {r['hid']} {r['name']}")
    else:
        verdict_lines.extend(
            [
                "",
                "## Verdict",
                "",
                "**No hypothesis passed.** Forex remains in parking lot.",
                "See `research/forex/forex-hypothesis-sweep-report.md` for full matrix.",
            ]
        )
    Path(args.verdict).write_text("\n".join(verdict_lines))

    print(f"Hypothesis sweep: {len(runnable)} tested, {len(passed)} passed gate")
    if best:
        print(
            f"Best: {best['hid']} {best['name']} — "
            f"{best['windows_pass']}/{best['windows_total']} windows, "
            f"avg {best['avg_expectancy_r']:+.3f}R, WR {best['avg_win_rate']:.1%}"
        )
    print(f"Report → {args.report}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
