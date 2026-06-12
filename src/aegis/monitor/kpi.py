"""Weekly KPI report for paper trading (P3.1 / Section 5)."""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from aegis.config import AegisConfig, load_config
from aegis.data import db
from aegis.log import setup_logging

WEEK_MS = 7 * 86_400_000


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
    )


def format_weekly_kpi(kpi: WeeklyKpi) -> str:
    win = f"{kpi.win_rate * 100:.1f}%" if kpi.win_rate is not None else "n/a"
    if kpi.expectancy_r is not None and kpi.expectancy_ci_low is not None:
        exp = f"{kpi.expectancy_r:+.3f}R ({kpi.expectancy_ci_low:+.3f} to {kpi.expectancy_ci_high:+.3f} 90% CI)"
    else:
        exp = "n/a (need closed trades)"
    dd = f"{kpi.max_dd_pct:.1f}%" if kpi.max_dd_pct is not None else "n/a"
    return (
        f"Aegis weekly KPI — week of {kpi.week_of}\n"
        f"Mode: paper | Equity: ${kpi.equity_usd:,.2f}\n"
        f"Trades (wk/cum): {kpi.trades_week} / {kpi.trades_cum}\n"
        f"Win rate (cum): {win}\n"
        f"Expectancy: {exp}\n"
        f"Max DD: {dd}\n"
        f"Scanner flags (cum): {kpi.scanner_flags_cum}\n"
        f"Gates breached: {kpi.gates_breached}\n"
        f"→ Copy row to Tasks & Milestones Section 5"
    )


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
