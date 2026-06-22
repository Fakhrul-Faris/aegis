"""H11b follow-up — Event Spike Fade on 15m, expanded calendar, per-event breakdown.

Usage:
    aegis-forex-h11b-sweep
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from aegis.backtest.forex_data import load_ohlc, slice_ohlc
from aegis.backtest.forex_scm_engine import ScmBacktestResult, run_signals_backtest
from aegis.backtest.forex_scm_run import _auto_windows
from aegis.config_forex import ForexConfig, load_forex_config
from aegis.data import db
from aegis.data.forex_calendar import seed_economic_calendar
from aegis.data.forex_download import import_histdata_csv
from aegis.log import setup_logging
from aegis.strategy.forex_confirms import CalendarEventRow, load_calendar_events
from aegis.strategy.forex_hypotheses import HypothesisParams, detect_event_spike_fade_h11b
from aegis.strategy.forex_session import compute_asian_ranges

FOREXSB_DIR = Path("data/forexsb")

EVENT_CODES = ("NFP", "CPI", "FOMC", "ECB", "BOE", "RETAIL", "GDP", "UKCPI")


@dataclass(frozen=True)
class H11bVariant:
    vid: str
    label: str
    timeframe: str
    tiers: tuple[int, ...]
    params: HypothesisParams
    event_filter: tuple[str, ...] | None = None


def import_forexsb(db_path: str) -> None:
    if not FOREXSB_DIR.exists():
        return
    for path in FOREXSB_DIR.glob("*.csv"):
        stem = path.stem.upper()
        if stem.endswith("_H1"):
            import_histdata_csv(db_path, path, stem[:-3], timeframe="1h")
        elif stem.endswith("_M15"):
            import_histdata_csv(db_path, path, stem[:-4], timeframe="15m")


def build_variants() -> list[H11bVariant]:
    return [
        H11bVariant(
            "H11b-1",
            "15m tier3 RR1.0 fade45",
            "15m",
            (3,),
            HypothesisParams(
                spike_wait_minutes=30,
                spike_fade_minutes=45,
                reward_risk=1.0,
                target_mode="fixed_rr",
                min_spike_pips=3.0,
            ),
        ),
        H11bVariant(
            "H11b-2",
            "15m tier2+3 retrace50 fade45",
            "15m",
            (2, 3),
            HypothesisParams(
                spike_wait_minutes=30,
                spike_fade_minutes=45,
                target_mode="retrace",
                spike_retrace_pct=0.5,
                min_spike_pips=3.0,
            ),
        ),
        H11bVariant(
            "H11b-3",
            "15m tier2+3 RR0.8 fade30",
            "15m",
            (2, 3),
            HypothesisParams(
                spike_wait_minutes=20,
                spike_fade_minutes=30,
                reward_risk=0.8,
                target_mode="fixed_rr",
                min_spike_pips=2.0,
            ),
        ),
        H11bVariant(
            "H11b-4",
            "1h tier2+3 retrace50 fade60",
            "1h",
            (2, 3),
            HypothesisParams(
                spike_wait_minutes=30,
                spike_fade_minutes=60,
                target_mode="retrace",
                spike_retrace_pct=0.5,
                min_spike_pips=5.0,
            ),
        ),
        H11bVariant(
            "H11b-5",
            "15m tier2+3 retrace50 fade45 NFP-only",
            "15m",
            (2, 3),
            HypothesisParams(
                spike_wait_minutes=30,
                spike_fade_minutes=45,
                target_mode="retrace",
                spike_retrace_pct=0.5,
                min_spike_pips=3.0,
            ),
            event_filter=("NFP",),
        ),
        H11bVariant(
            "H11b-6",
            "15m tier2+3 retrace50 fade45 CPI-only",
            "15m",
            (2, 3),
            HypothesisParams(
                spike_wait_minutes=30,
                spike_fade_minutes=45,
                target_mode="retrace",
                spike_retrace_pct=0.5,
                min_spike_pips=3.0,
            ),
            event_filter=("CPI",),
        ),
        H11bVariant(
            "H11b-7",
            "15m tier2+3 retrace50 fade45 FOMC-only",
            "15m",
            (2, 3),
            HypothesisParams(
                spike_wait_minutes=30,
                spike_fade_minutes=45,
                target_mode="retrace",
                spike_retrace_pct=0.5,
                min_spike_pips=3.0,
            ),
            event_filter=("FOMC",),
        ),
        H11bVariant(
            "H11b-8",
            "15m tier2+3 retrace50 fade45 ECB-only",
            "15m",
            (2, 3),
            HypothesisParams(
                spike_wait_minutes=30,
                spike_fade_minutes=45,
                target_mode="retrace",
                spike_retrace_pct=0.5,
                min_spike_pips=3.0,
            ),
            event_filter=("ECB",),
        ),
    ]


def passes_standard_gate(result: ScmBacktestResult, cfg: ForexConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    n = len(result.trades)
    min_trades = cfg.scm.backtest_min_trades_per_window
    min_wr = cfg.scm.backtest_min_win_rate
    lo, _ = result.expectancy_ci90()
    if n < min_trades:
        reasons.append(f"trades {n} < {min_trades}")
    if result.win_rate < min_wr:
        reasons.append(f"WR {result.win_rate:.1%} < {min_wr:.0%}")
    if n >= 2 and (math.isnan(lo) or lo <= 0):
        reasons.append(f"CI lower {lo:+.3f}R <= 0")
    return len(reasons) == 0, reasons


def passes_event_gate(
    result: ScmBacktestResult,
    *,
    min_trades: int = 30,
    min_wr: float = 0.55,
) -> tuple[bool, list[str]]:
    """Research gate for low-frequency event strategies."""
    reasons: list[str] = []
    n = len(result.trades)
    lo, _ = result.expectancy_ci90()
    if n < min_trades:
        reasons.append(f"trades {n} < {min_trades}")
    if result.win_rate < min_wr:
        reasons.append(f"WR {result.win_rate:.1%} < {min_wr:.0%}")
    if n >= 2 and (math.isnan(lo) or lo <= 0):
        reasons.append(f"CI lower {lo:+.3f}R <= 0")
    return len(reasons) == 0, reasons


def _load_events(
    db_path: str,
    cfg: ForexConfig,
    variant: H11bVariant,
) -> list[CalendarEventRow]:
    currencies = ("USD", "EUR", "GBP")
    codes = variant.event_filter
    return load_calendar_events(
        db_path,
        cfg.calendar,
        currencies=currencies,
        tiers=variant.tiers,
        event_codes=codes,
    )


def run_variant_window(
    variant: H11bVariant,
    ohlc,
    events: list[CalendarEventRow],
    cfg: ForexConfig,
    start: str,
    end: str,
) -> dict:
    panel = slice_ohlc(ohlc, start, end)
    if panel.empty:
        return {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0}

    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    event_panel = [
        e
        for e in events
        if start_ts <= pd.Timestamp(e.ts_ms, unit="ms", tz="UTC") <= end_ts
    ]
    ranges = compute_asian_ranges(panel, cfg.sessions)
    pip = cfg.costs.pip_size_for("EURUSD")
    signals = detect_event_spike_fade_h11b(
        panel,
        cfg.sessions,
        variant.params,
        event_times_ms=None,
        asian_ranges=ranges,
        events=event_panel,
        pip_size=pip,
    )
    result = run_signals_backtest(panel, cfg, signals, symbol="EURUSD")
    std_ok, std_reasons = passes_standard_gate(result, cfg)
    evt_ok, evt_reasons = passes_event_gate(result)
    lo, hi = result.expectancy_ci90()
    return {
        "trades": len(result.trades),
        "raw_signals": len(signals),
        "win_rate": result.win_rate,
        "expectancy_r": result.expectancy_r,
        "ci_lo": lo,
        "ci_hi": hi,
        "pass_standard": std_ok,
        "pass_event": evt_ok,
        "fail_reasons": std_reasons,
        "event_fail_reasons": evt_reasons,
    }


def run_h11b_sweep(cfg: ForexConfig) -> tuple[list[dict], int]:
    db_path = cfg.research.sqlite_path
    import_forexsb(db_path)
    conn = db.connect(db_path)
    try:
        event_count = seed_economic_calendar(conn, year_start=2010, year_end=2027)
    finally:
        conn.close()

    ohlc_15m = load_ohlc(db_path, "EURUSD", timeframe="15m")
    ohlc_1h = load_ohlc(db_path, "EURUSD", timeframe="1h")

    rows: list[dict] = []
    for variant in build_variants():
        ohlc = ohlc_15m if variant.timeframe == "15m" else ohlc_1h
        if ohlc.empty:
            continue
        events = _load_events(db_path, cfg, variant)
        windows = _auto_windows(ohlc)
        window_results = []
        std_pass = 0
        evt_pass = 0
        for label, start, end in windows:
            wr = run_variant_window(variant, ohlc, events, cfg, start, end)
            wr["window"] = label
            window_results.append(wr)
            if wr["pass_standard"]:
                std_pass += 1
            if wr["pass_event"]:
                evt_pass += 1

        n = len(window_results)
        rows.append(
            {
                "vid": variant.vid,
                "label": variant.label,
                "timeframe": variant.timeframe,
                "tiers": variant.tiers,
                "event_filter": variant.event_filter or ("ALL",),
                "events_in_db": len(events),
                "windows_pass_standard": std_pass,
                "windows_pass_event": evt_pass,
                "windows_total": n,
                "total_trades": sum(w["trades"] for w in window_results),
                "total_raw_signals": sum(w["raw_signals"] for w in window_results),
                "avg_win_rate": sum(w["win_rate"] for w in window_results) / max(n, 1),
                "avg_expectancy_r": sum(w["expectancy_r"] for w in window_results) / max(n, 1),
                "window_detail": window_results,
            }
        )

    return rows, event_count


def write_report(rows: list[dict], event_count: int, path: Path) -> None:
    std_winners = [r for r in rows if r["windows_pass_standard"] >= 2]
    evt_winners = [r for r in rows if r["windows_pass_event"] >= 2]

    lines = [
        "# H11b Event Spike Fade — Follow-up Report",
        "",
        f"*Generated {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        f"Calendar events seeded: **{event_count}** (tier 2+3, USD/EUR/GBP)",
        "",
        f"**Standard gate (≥80 trades, ≥60% WR):** {len(std_winners)} variants pass ≥2/3 windows",
        f"**Event gate (≥30 trades, ≥55% WR):** {len(evt_winners)} variants pass ≥2/3 windows",
        "",
        "## Variant summary",
        "",
        "| ID | Variant | Events | W std | W evt | Trades | Raw sig | Avg WR | Avg Exp |",
        "| -- | ------- | ------ | ----- | ----- | ------ | ------- | ------ | ------- |",
    ]
    for r in sorted(rows, key=lambda x: (-x["windows_pass_event"], -x["avg_expectancy_r"])):
        ev = ",".join(r["event_filter"])
        lines.append(
            f"| {r['vid']} | {r['label']} | {r['events_in_db']} ({ev}) | "
            f"{r['windows_pass_standard']}/{r['windows_total']} | "
            f"{r['windows_pass_event']}/{r['windows_total']} | "
            f"{r['total_trades']} | {r['total_raw_signals']} | "
            f"{r['avg_win_rate']:.1%} | {r['avg_expectancy_r']:+.3f} |"
        )

    lines.extend(["", "## Per-window detail (all variants)", ""])
    for r in rows:
        lines.append(f"### {r['vid']} — {r['label']}")
        for w in r["window_detail"]:
            lines.append(
                f"- {w['window']}: {w['trades']} trades ({w['raw_signals']} signals), "
                f"WR {w['win_rate']:.1%}, {w['expectancy_r']:+.3f}R, "
                f"std={w['pass_standard']} evt={w['pass_event']}"
            )
            if w["fail_reasons"]:
                lines.append(f"  - std fail: {', '.join(w['fail_reasons'])}")
        lines.append("")

    if evt_winners:
        lines.extend(["## Event gate winners (≥2/3 windows)", ""])
        for r in evt_winners:
            lines.append(
                f"- **{r['vid']}** {r['label']} — evt {r['windows_pass_event']}/{r['windows_total']}, "
                f"WR {r['avg_win_rate']:.1%}, {r['avg_expectancy_r']:+.3f}R"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="H11b event spike fade follow-up")
    parser.add_argument("--forex-config", default="config/forex.yaml")
    parser.add_argument("--report", default="research/forex/forex-h11b-report.md")
    parser.add_argument("--verdict", default="research/forex/forex-h11b-verdict.md")
    args = parser.parse_args()

    setup_logging("logs", "INFO")
    cfg = load_forex_config(args.forex_config)
    rows, event_count = run_h11b_sweep(cfg)
    write_report(rows, event_count, Path(args.report))

    evt_winners = [r for r in rows if r["windows_pass_event"] >= 2]
    std_winners = [r for r in rows if r["windows_pass_standard"] >= 2]
    best = max(rows, key=lambda x: (x["windows_pass_event"], x["avg_expectancy_r"]), default=None)

    verdict = [
        "# H11b Verdict",
        "",
        f"*Generated {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        f"Calendar: **{event_count}** events (expanded tier 2+3 + BoE/Retail/GDP/UK CPI).",
        "",
    ]
    if best:
        verdict.append(
            f"Best variant: **{best['vid']}** — event gate {best['windows_pass_event']}/"
            f"{best['windows_total']}, WR {best['avg_win_rate']:.1%}, "
            f"{best['avg_expectancy_r']:+.3f}R, {best['total_trades']} trades"
        )
    if evt_winners:
        verdict.extend(["", "## Recommendation", "", "Promote to FX-A.7 frozen recipe candidate:"])
        for r in evt_winners:
            verdict.append(f"- {r['vid']}: {r['label']}")
    elif std_winners:
        verdict.extend(["", "Passes standard gate only — review before demo."])
    else:
        verdict.extend(
            [
                "",
                "## Verdict",
                "",
                "No variant passes event gate on ≥2/3 windows. H11b does not unblock FX3.",
                "Consider: further event expansion, GBPUSD event fade, or live paper with tiny size.",
            ]
        )
    Path(args.verdict).write_text("\n".join(verdict))

    print(f"H11b sweep: {len(rows)} variants, {len(evt_winners)} pass event gate")
    if best:
        print(
            f"Best: {best['vid']} — evt {best['windows_pass_event']}/{best['windows_total']}, "
            f"WR {best['avg_win_rate']:.1%}, {best['avg_expectancy_r']:+.3f}R, "
            f"{best['total_trades']} trades"
        )
    print(f"Report → {args.report}")
    sys.exit(0 if evt_winners else 1)


if __name__ == "__main__":
    main()
