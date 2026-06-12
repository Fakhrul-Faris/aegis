"""Weekly KPI report for paper trading (P3.1 / Section 5)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from aegis.config import AegisConfig, load_config
from aegis.data import db
from aegis.log import setup_logging

WEEK_MS = 7 * 86_400_000
# Strategy A EMA-only baseline (research/2026-06-strategy_a_baseline_backtest.md).
BASELINE_EMA_ONLY_R = -0.213
TIER_ORDER = ("passive", "mid", "aggressive", "unknown")


@dataclass(frozen=True)
class KpiSegment:
    key: str
    trades: int
    win_rate: float | None
    expectancy_r: float | None
    expectancy_ci_low: float | None
    expectancy_ci_high: float | None


@dataclass(frozen=True)
class SignalLogRow:
    tier: str
    logged: int
    taken: int


@dataclass(frozen=True)
class WeeklyKpi:
    week_of: str
    equity_usd: float
    trades_week: int
    trades_cum: int
    win_rate: float | None
    expectancy_r: float | None
    expectancy_ci_low: float | None
    expectancy_ci_high: float | None
    max_dd_pct: float | None
    scanner_flags_cum: int
    gates_breached: int
    tier_breakdown: tuple[KpiSegment, ...]
    variant_breakdown: tuple[KpiSegment, ...]
    signal_log: tuple[SignalLogRow, ...]


def _closed_r_multiples(conn: sqlite3.Connection, since_ms: int | None = None) -> list[float]:
    if since_ms is None:
        rows = conn.execute(
            """
            SELECT r_multiple FROM positions
            WHERE strategy = 'A' AND closed_ts_ms IS NOT NULL AND r_multiple IS NOT NULL
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT r_multiple FROM positions
            WHERE strategy = 'A' AND closed_ts_ms IS NOT NULL AND closed_ts_ms >= ?
              AND r_multiple IS NOT NULL
            """,
            (since_ms,),
        ).fetchall()
    return [float(r[0]) for r in rows]


def _bootstrap_ci(values: list[float], *, n_boot: int = 2000, alpha: float = 0.10) -> tuple[float, float, float]:
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if len(arr) < 2:
        return mean, mean, mean
    rng = np.random.default_rng(42)
    means = []
    for _ in range(n_boot):
        sample = rng.choice(arr, size=len(arr), replace=True)
        means.append(float(sample.mean()))
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return mean, float(lo), float(hi)


def _max_drawdown_pct(conn: sqlite3.Connection) -> float | None:
    rows = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = 'paper' ORDER BY ts_ms
        """
    ).fetchall()
    if not rows:
        return None
    peak = rows[0][0]
    max_dd = 0.0
    for (equity,) in rows:
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd * 100.0


def _closed_trade_rows(conn: sqlite3.Connection) -> list[tuple[float, str, str]]:
    rows = conn.execute(
        """
        SELECT r_multiple, context_json FROM positions
        WHERE strategy = 'A' AND closed_ts_ms IS NOT NULL AND r_multiple IS NOT NULL
        """
    ).fetchall()
    out: list[tuple[float, str, str]] = []
    for r_mult, ctx_raw in rows:
        ctx = json.loads(ctx_raw) if ctx_raw else {}
        tier = str(ctx.get("tier") or "unknown")
        scanner = ctx.get("scanner") or {}
        variant = str(scanner.get("variant") or "no_anomaly")
        out.append((float(r_mult), tier, variant))
    return out


def _segment_from_rs(key: str, rs: list[float]) -> KpiSegment:
    if not rs:
        return KpiSegment(key, 0, None, None, None, None)
    wins = sum(1 for r in rs if r > 0)
    exp_r, exp_lo, exp_hi = _bootstrap_ci(rs)
    return KpiSegment(
        key=key,
        trades=len(rs),
        win_rate=wins / len(rs),
        expectancy_r=exp_r,
        expectancy_ci_low=exp_lo,
        expectancy_ci_high=exp_hi,
    )


def _ordered_segments(groups: dict[str, list[float]], order: tuple[str, ...]) -> tuple[KpiSegment, ...]:
    keys = [k for k in order if k in groups]
    keys.extend(sorted(k for k in groups if k not in order))
    return tuple(_segment_from_rs(k, groups[k]) for k in keys)


def build_tier_breakdown(conn: sqlite3.Connection) -> tuple[KpiSegment, ...]:
    by_tier: dict[str, list[float]] = {}
    for r_mult, tier, _variant in _closed_trade_rows(conn):
        by_tier.setdefault(tier, []).append(r_mult)
    return _ordered_segments(by_tier, TIER_ORDER)


def build_variant_breakdown(conn: sqlite3.Connection) -> tuple[KpiSegment, ...]:
    by_variant: dict[str, list[float]] = {}
    for r_mult, _tier, variant in _closed_trade_rows(conn):
        by_variant.setdefault(variant, []).append(r_mult)
    variant_order = ("price_flat", "price_up_5", "price_down", "no_anomaly")
    return _ordered_segments(by_variant, variant_order)


def build_signal_log(conn: sqlite3.Connection) -> tuple[SignalLogRow, ...]:
    rows = conn.execute(
        """
        SELECT tier, taken, COUNT(*) FROM signals
        WHERE strategy = 'A' GROUP BY tier, taken
        """
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for tier, taken, n in rows:
        key = tier or "unknown"
        bucket = counts.setdefault(key, {"logged": 0, "taken": 0})
        bucket["logged"] += n
        if taken:
            bucket["taken"] += n
    keys = [k for k in TIER_ORDER if k in counts]
    keys.extend(sorted(k for k in counts if k not in TIER_ORDER))
    return tuple(
        SignalLogRow(tier=k, logged=counts[k]["logged"], taken=counts[k]["taken"]) for k in keys
    )


def _format_segment_line(seg: KpiSegment) -> str:
    if seg.trades == 0:
        return f"  {seg.key}: n=0"
    win = f"{seg.win_rate * 100:.1f}%" if seg.win_rate is not None else "n/a"
    if seg.expectancy_r is not None and seg.expectancy_ci_low is not None:
        exp = f"{seg.expectancy_r:+.3f}R ({seg.expectancy_ci_low:+.3f} to {seg.expectancy_ci_high:+.3f})"
    else:
        exp = f"{seg.expectancy_r:+.3f}R" if seg.expectancy_r is not None else "n/a"
    vs = ""
    if seg.expectancy_r is not None:
        delta = seg.expectancy_r - BASELINE_EMA_ONLY_R
        vs = f" · vs baseline {delta:+.3f}R"
    return f"  {seg.key}: n={seg.trades} win={win} exp={exp}{vs}"


def _format_breakdown_section(title: str, segments: tuple[KpiSegment, ...]) -> list[str]:
    lines = [title]
    if not segments or all(s.trades == 0 for s in segments):
        lines.append("  n/a (need closed trades)")
        return lines
    lines.extend(_format_segment_line(seg) for seg in segments if seg.trades > 0)
    if len(lines) == 1:
        lines.append("  n/a (need closed trades)")
    return lines


def build_weekly_kpi(conn: sqlite3.Connection, now_ms: int | None = None) -> WeeklyKpi:
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    since = now - WEEK_MS
    week_of = datetime.fromtimestamp(now / 1000, tz=UTC).strftime("%Y-%m-%d")

    week_rs = _closed_r_multiples(conn, since_ms=since)
    cum_rs = _closed_r_multiples(conn)
    flags_cum = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]

    win_rate = None
    exp_r = exp_lo = exp_hi = None
    if cum_rs:
        wins = sum(1 for r in cum_rs if r > 0)
        win_rate = wins / len(cum_rs)
        exp_r, exp_lo, exp_hi = _bootstrap_ci(cum_rs)

    return WeeklyKpi(
        week_of=week_of,
        equity_usd=db.latest_paper_equity(conn),
        trades_week=len(week_rs),
        trades_cum=len(cum_rs),
        win_rate=win_rate,
        expectancy_r=exp_r,
        expectancy_ci_low=exp_lo,
        expectancy_ci_high=exp_hi,
        max_dd_pct=_max_drawdown_pct(conn),
        scanner_flags_cum=flags_cum,
        gates_breached=0,
        tier_breakdown=build_tier_breakdown(conn),
        variant_breakdown=build_variant_breakdown(conn),
        signal_log=build_signal_log(conn),
    )


def format_weekly_kpi(kpi: WeeklyKpi) -> str:
    win = f"{kpi.win_rate * 100:.1f}%" if kpi.win_rate is not None else "n/a"
    if kpi.expectancy_r is not None and kpi.expectancy_ci_low is not None:
        exp = f"{kpi.expectancy_r:+.3f}R ({kpi.expectancy_ci_low:+.3f} to {kpi.expectancy_ci_high:+.3f} 90% CI)"
        vs_baseline = f" ({kpi.expectancy_r - BASELINE_EMA_ONLY_R:+.3f}R vs EMA-only baseline)"
    else:
        exp = "n/a (need closed trades)"
        vs_baseline = ""
    dd = f"{kpi.max_dd_pct:.1f}%" if kpi.max_dd_pct is not None else "n/a"
    lines = [
        f"Aegis weekly KPI — week of {kpi.week_of}",
        f"Mode: paper | Equity: ${kpi.equity_usd:,.2f}",
        f"Trades (wk/cum): {kpi.trades_week} / {kpi.trades_cum}",
        f"Win rate (cum): {win}",
        f"Expectancy: {exp}{vs_baseline}",
        f"Max DD: {dd}",
        f"Scanner flags (cum): {kpi.scanner_flags_cum}",
        f"Gates breached: {kpi.gates_breached}",
        "",
        *_format_breakdown_section("By tier (closed trades):", kpi.tier_breakdown),
        "",
        *_format_breakdown_section("By anomaly variant (closed):", kpi.variant_breakdown),
    ]
    if kpi.signal_log:
        log_parts = [f"{row.tier} {row.taken}/{row.logged} taken" for row in kpi.signal_log]
        lines.extend(["", f"Signal log (cum): {', '.join(log_parts)}"])
    lines.extend(
        [
            "",
            f"EMA-only baseline: {BASELINE_EMA_ONLY_R:+.3f}R (Jun 2026 backtest)",
            "→ Copy row to Tasks & Milestones Section 5",
        ]
    )
    return "\n".join(lines)


def kpi_due(now_s: float, kpi_weekday: int, last_sent_week: str | None) -> tuple[bool, str]:
    """Due once per ISO week on the configured weekday (Python: Monday=0, Sunday=6)."""
    dt = datetime.fromtimestamp(now_s, tz=UTC)
    iso = dt.isocalendar()
    week_key = f"{iso.year}-W{iso.week:02d}"
    return (dt.weekday() == kpi_weekday and week_key != last_sent_week, week_key)


async def send_weekly_kpi(cfg: AegisConfig) -> str:
    from aegis.monitor.telegram import notifier_from_config

    conn = db.connect(cfg.sqlite_path)
    try:
        text = format_weekly_kpi(build_weekly_kpi(conn))
    finally:
        conn.close()

    notifier = notifier_from_config(cfg)
    try:
        await notifier.send(text)
    finally:
        await notifier.close()
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis weekly KPI report (Section 5)")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--print-only", action="store_true", help="stdout only, no Telegram")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)

    if args.print_only:
        conn = db.connect(cfg.sqlite_path)
        try:
            print(format_weekly_kpi(build_weekly_kpi(conn)))
        finally:
            conn.close()
    else:
        print(asyncio.run(send_weekly_kpi(cfg)))


if __name__ == "__main__":
    main()
