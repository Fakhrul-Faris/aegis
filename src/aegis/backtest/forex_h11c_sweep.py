"""H11c — multi-pair Event Spike Fade frequency sweep (H11b-4 params).

Tests per-pair replication and combined portfolio trade frequency.

Usage:
    aegis-forex-h11c-sweep
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from aegis.backtest.forex_data import load_ohlc, slice_ohlc
from aegis.backtest.forex_h11b_sweep import (
    FOREXSB_DIR,
    import_forexsb,
    passes_event_gate,
    passes_standard_gate,
)
from aegis.backtest.forex_scm_engine import ScmBacktestResult, ScmTrade, run_signals_backtest
from aegis.backtest.forex_scm_run import _auto_windows
from aegis.config_forex import ForexConfig, load_forex_config
from aegis.data import db
from aegis.data.forex_calendar import seed_economic_calendar
from aegis.log import setup_logging
from aegis.strategy.forex_confirms import CalendarEventRow, load_calendar_events
from aegis.strategy.forex_hypotheses import HypothesisParams, detect_event_spike_fade_h11b
from aegis.strategy.forex_session import compute_asian_ranges

# H11b-4 frozen baseline
H11B4_PARAMS = HypothesisParams(
    spike_wait_minutes=30,
    spike_fade_minutes=60,
    target_mode="retrace",
    spike_retrace_pct=0.5,
    min_spike_pips=5.0,
)


def events_for_pair(pair: str, events: list[CalendarEventRow]) -> list[CalendarEventRow]:
    """Map calendar events to tradable pair."""
    if pair == "EURUSD":
        return [e for e in events if e.currency in ("USD", "EUR")]
    if pair == "GBPUSD":
        return [e for e in events if e.currency in ("USD", "GBP")]
    if pair == "USDJPY":
        return [e for e in events if e.currency == "USD"]
    return []


def merge_results(results: list[ScmBacktestResult]) -> ScmBacktestResult:
    """Combine per-pair backtests into one portfolio result."""
    merged = ScmBacktestResult(use_confirms=False)
    trades: list[ScmTrade] = []
    raw = 0
    equity = 100.0
    merged.equity_curve.append(equity)
    for r in results:
        raw += r.raw_signals
        trades.extend(r.trades)
    trades.sort(key=lambda t: t.entry_ts)
    merged.trades = trades
    merged.raw_signals = raw
    for t in trades:
        equity += t.pnl_net_usd
        merged.equity_curve.append(equity)
    return merged


@dataclass(frozen=True)
class H11cVariant:
    vid: str
    label: str
    pairs: tuple[str, ...]
    params: HypothesisParams
    timeframe: str = "1h"


def build_h11c_variants() -> list[H11cVariant]:
    amp_params = HypothesisParams(
        spike_wait_minutes=30,
        spike_fade_minutes=45,
        target_mode="retrace",
        spike_retrace_pct=0.5,
        min_spike_pips=3.0,
    )
    return [
        H11cVariant("H11c-1", "GBPUSD solo (H11b-4 params)", ("GBPUSD",), H11B4_PARAMS),
        H11cVariant("H11c-2", "USDJPY solo USD events", ("USDJPY",), H11B4_PARAMS),
        H11cVariant("H11c-3", "EURUSD + GBPUSD portfolio", ("EURUSD", "GBPUSD"), H11B4_PARAMS),
        H11cVariant(
            "H11c-4",
            "EURUSD + GBPUSD + USDJPY portfolio",
            ("EURUSD", "GBPUSD", "USDJPY"),
            H11B4_PARAMS,
        ),
        H11cVariant(
            "H11c-5",
            "EUR+GBP min spike 3 pip fade45",
            ("EURUSD", "GBPUSD"),
            amp_params,
        ),
    ]


def run_pair_signals(
    pair: str,
    ohlc: pd.DataFrame,
    events: list[CalendarEventRow],
    cfg: ForexConfig,
    params: HypothesisParams,
) -> list:
    ranges = compute_asian_ranges(ohlc, cfg.sessions)
    pip = cfg.costs.pip_size_for(pair)
    pair_events = events_for_pair(pair, events)
    return detect_event_spike_fade_h11b(
        ohlc,
        cfg.sessions,
        params,
        asian_ranges=ranges,
        events=pair_events,
        pip_size=pip,
    )


def run_variant_window(
    variant: H11cVariant,
    ohlc_by_pair: dict[str, pd.DataFrame],
    all_events: list[CalendarEventRow],
    cfg: ForexConfig,
    start: str,
    end: str,
) -> dict:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    event_panel = [
        e
        for e in all_events
        if start_ts <= pd.Timestamp(e.ts_ms, unit="ms", tz="UTC") <= end_ts
    ]

    pair_results: list[ScmBacktestResult] = []
    per_pair: dict[str, dict] = {}
    esf = cfg.event_spike_fade

    for pair in variant.pairs:
        ohlc = slice_ohlc(ohlc_by_pair.get(pair, pd.DataFrame()), start, end)
        if ohlc.empty:
            per_pair[pair] = {"trades": 0, "signals": 0}
            continue
        signals = run_pair_signals(pair, ohlc, event_panel, cfg, variant.params)
        result = run_signals_backtest(
            ohlc,
            cfg,
            signals,
            symbol=pair,
            risk_pct=esf.risk_pct,
            lots=esf.lots,
        )
        pair_results.append(result)
        per_pair[pair] = {
            "trades": len(result.trades),
            "signals": len(signals),
            "win_rate": result.win_rate,
            "expectancy_r": result.expectancy_r,
        }

    if not pair_results:
        empty = ScmBacktestResult()
        std_ok, std_reasons = passes_standard_gate(empty, cfg)
        evt_ok, evt_reasons = passes_event_gate(empty)
        return {
            "trades": 0,
            "raw_signals": 0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "pass_standard": std_ok,
            "pass_event": evt_ok,
            "per_pair": per_pair,
        }

    combined = merge_results(pair_results) if len(pair_results) > 1 else pair_results[0]
    std_ok, std_reasons = passes_standard_gate(combined, cfg)
    evt_ok, evt_reasons = passes_event_gate(combined)
    lo, hi = combined.expectancy_ci90()
    years = max((end_ts - start_ts).days / 365.25, 0.1)
    trades_per_month = len(combined.trades) / (years * 12)

    return {
        "trades": len(combined.trades),
        "raw_signals": combined.raw_signals,
        "win_rate": combined.win_rate,
        "expectancy_r": combined.expectancy_r,
        "ci_lo": lo,
        "ci_hi": hi,
        "trades_per_month": trades_per_month,
        "pass_standard": std_ok,
        "pass_event": evt_ok,
        "std_reasons": std_reasons,
        "evt_reasons": evt_reasons,
        "per_pair": per_pair,
    }


def run_h11c_sweep(cfg: ForexConfig) -> list[dict]:
    db_path = cfg.research.sqlite_path
    import_forexsb(db_path)
    conn = db.connect(db_path)
    try:
        seed_economic_calendar(conn, year_start=2010, year_end=2027)
    finally:
        conn.close()

    all_events = load_calendar_events(
        db_path,
        cfg.calendar,
        currencies=cfg.calendar.event_spike_currencies,
        tiers=cfg.calendar.event_spike_tiers,
    )

    pairs_needed = {p for v in build_h11c_variants() for p in v.pairs}
    ohlc_by_pair: dict[str, pd.DataFrame] = {}
    for pair in pairs_needed:
        ohlc_by_pair[pair] = load_ohlc(db_path, pair, timeframe="1h")

    ref_ohlc = ohlc_by_pair.get("EURUSD")
    if ref_ohlc is None or ref_ohlc.empty:
        return []
    windows = _auto_windows(ref_ohlc)

    rows: list[dict] = []
    for variant in build_h11c_variants():
        window_results = []
        std_pass = evt_pass = 0
        for label, start, end in windows:
            wr = run_variant_window(variant, ohlc_by_pair, all_events, cfg, start, end)
            wr["window"] = label
            window_results.append(wr)
            if wr["pass_standard"]:
                std_pass += 1
            if wr["pass_event"]:
                evt_pass += 1

        n = len(window_results)
        total_trades = sum(w["trades"] for w in window_results)
        span_years = (
            ref_ohlc.index.max() - ref_ohlc.index.min()
        ).days / 365.25
        rows.append(
            {
                "vid": variant.vid,
                "label": variant.label,
                "pairs": variant.pairs,
                "windows_pass_standard": std_pass,
                "windows_pass_event": evt_pass,
                "windows_total": n,
                "total_trades": total_trades,
                "trades_per_month": total_trades / max(span_years * 12, 1),
                "avg_win_rate": sum(w["win_rate"] for w in window_results) / max(n, 1),
                "avg_expectancy_r": sum(w["expectancy_r"] for w in window_results) / max(n, 1),
                "window_detail": window_results,
            }
        )
    return rows


def write_report(rows: list[dict], path: Path) -> None:
    std_winners = [r for r in rows if r["windows_pass_standard"] >= 2]
    evt_winners = [r for r in rows if r["windows_pass_event"] >= 2]

    lines = [
        "# H11c Multi-Pair Event Spike Fade Sweep",
        "",
        f"*Generated {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        "Baseline params: H11b-4 (1h, retrace 50%, fade 60m, min spike 5 pip).",
        "",
        f"**Standard gate winners (≥2/3):** {len(std_winners)}",
        f"**Event gate winners (≥2/3):** {len(evt_winners)}",
        "",
        "## Summary",
        "",
        "| ID | Variant | Pairs | W std | W evt | Total trades | Trades/mo | Avg WR | Avg Exp |",
        "| -- | ------- | ----- | ----- | ----- | ------------ | --------- | ------ | ------- |",
    ]
    for r in sorted(rows, key=lambda x: (-x["trades_per_month"], -x["windows_pass_standard"])):
        pairs = "+".join(r["pairs"])
        lines.append(
            f"| {r['vid']} | {r['label']} | {pairs} | "
            f"{r['windows_pass_standard']}/{r['windows_total']} | "
            f"{r['windows_pass_event']}/{r['windows_total']} | "
            f"{r['total_trades']} | {r['trades_per_month']:.1f} | "
            f"{r['avg_win_rate']:.1%} | {r['avg_expectancy_r']:+.3f} |"
        )

    lines.extend(["", "## Per-window detail", ""])
    for r in rows:
        lines.append(f"### {r['vid']} — {r['label']}")
        for w in r["window_detail"]:
            pp = w.get("per_pair", {})
            breakdown = ", ".join(
                f"{p}:{d.get('trades', 0)}" for p, d in pp.items()
            ) if pp else ""
            lines.append(
                f"- {w['window']}: {w['trades']} trades ({w.get('trades_per_month', 0):.1f}/mo), "
                f"WR {w['win_rate']:.1%}, {w['expectancy_r']:+.3f}R, "
                f"std={w['pass_standard']} evt={w['pass_event']}"
                + (f" [{breakdown}]" if breakdown else "")
            )
        lines.append("")

    if std_winners:
        lines.extend(["## Recommended for FX3 update", ""])
        for r in std_winners:
            lines.append(
                f"- **{r['vid']}** {r['label']} — {r['trades_per_month']:.1f} trades/mo, "
                f"WR {r['avg_win_rate']:.1%}"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="H11c multi-pair frequency sweep")
    parser.add_argument("--forex-config", default="config/forex.yaml")
    parser.add_argument("--report", default="research/forex/forex-h11c-report.md")
    parser.add_argument("--verdict", default="research/forex/forex-h11c-verdict.md")
    args = parser.parse_args()

    setup_logging("logs", "INFO")
    cfg = load_forex_config(args.forex_config)
    rows = run_h11c_sweep(cfg)
    write_report(rows, Path(args.report))

    std_winners = [r for r in rows if r["windows_pass_standard"] >= 2]
    best_freq = max(rows, key=lambda x: (x["windows_pass_standard"], x["trades_per_month"]), default=None)
    best = max(rows, key=lambda x: (x["windows_pass_standard"], x["avg_expectancy_r"]), default=None)

    verdict_lines = [
        "# H11c Verdict",
        "",
        f"*Generated {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
    ]
    if best:
        verdict_lines.append(
            f"**Best gate pass:** {best['vid']} — {best['windows_pass_standard']}/"
            f"{best['windows_total']} windows, {best['trades_per_month']:.1f} trades/mo, "
            f"WR {best['avg_win_rate']:.1%}, {best['avg_expectancy_r']:+.3f}R"
        )
    if best_freq and best_freq != best:
        verdict_lines.append(
            f"**Highest frequency (passing):** {best_freq['vid']} — "
            f"{best_freq['trades_per_month']:.1f} trades/mo"
        )
    baseline = next((r for r in rows if r["vid"] == "H11c-3"), None)
    eurusd_only_trades_pm = 752 / max(
        (load_ohlc(cfg.research.sqlite_path, "EURUSD", "1h").index.max()
         - load_ohlc(cfg.research.sqlite_path, "EURUSD", "1h").index.min()).days / 365.25 * 12,
        1,
    ) if rows else 4.0
    if baseline:
        verdict_lines.extend(
            [
                "",
                "## Frequency vs H11b-4 EURUSD-only",
                "",
                f"- EURUSD solo (H11b-4): ~{eurusd_only_trades_pm:.1f} trades/mo",
                f"- H11c-3 EUR+GBP: **{baseline['trades_per_month']:.1f} trades/mo** "
                f"({baseline['trades_per_month'] / max(eurusd_only_trades_pm, 0.1):.1f}×)",
            ]
        )
    if std_winners:
        verdict_lines.extend(["", "## Action", "", "Re-freeze FX3 with winning pair list."])
    else:
        verdict_lines.extend(["", "## Action", "", "Stay on EURUSD-only frozen recipe."])
    Path(args.verdict).write_text("\n".join(verdict_lines))

    print(f"H11c sweep: {len(rows)} variants, {len(std_winners)} pass standard gate")
    if best:
        print(
            f"Best: {best['vid']} — {best['trades_per_month']:.1f} trades/mo, "
            f"WR {best['avg_win_rate']:.1%}, std {best['windows_pass_standard']}/"
            f"{best['windows_total']}"
        )
    print(f"Report → {args.report}")
    sys.exit(0 if std_winners else 1)


if __name__ == "__main__":
    main()
