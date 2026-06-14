"""Forex weekly KPI report (FX5 — Section 5).

Usage:
    aegis-forex-kpi-report
    aegis-forex-kpi-report --print-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from aegis.config import load_config
from aegis.config_forex import ForexConfig, load_forex_config
from aegis.data import db
from aegis.execution.forex_paper import FOREX_DEMO_VENUE
from aegis.log import setup_logging
from aegis.monitor.daily_scorecard import format_win_record
from aegis.monitor.forex_scorecard import STRATEGY_ID

WEEK_MS = 7 * 86_400_000


@dataclass(frozen=True)
class ForexWeeklyKpi:
    week_of: str
    equity_usd: float
    trades_week: int
    trades_cum: int
    wins_week: int
    losses_week: int
    pnl_week_usd: float
    pnl_month_usd: float
    win_rate_cum: float | None
    expectancy_r: float | None
    expectancy_ci_low: float | None
    expectancy_ci_high: float | None
    max_dd_pct: float | None
    slippage_vs_model: str
    paper_days: int | None
    gates_breached: int


def _bootstrap_ci(values: list[float]) -> tuple[float, float, float]:
    arr = np.asarray(values, dtype=float)
    if len(arr) == 0:
        return 0.0, 0.0, 0.0
    mean = float(arr.mean())
    if len(arr) < 2:
        return mean, mean, mean
    rng = np.random.default_rng(42)
    means = [float(rng.choice(arr, size=len(arr), replace=True).mean()) for _ in range(2000)]
    lo, hi = np.percentile(means, [5, 95])
    return mean, float(lo), float(hi)


def _closed_r(conn: sqlite3.Connection, since_ms: int | None = None) -> list[float]:
    if since_ms is None:
        rows = conn.execute(
            """
            SELECT r_multiple FROM positions
            WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
              AND r_multiple IS NOT NULL
            """,
            (STRATEGY_ID, FOREX_DEMO_VENUE),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT r_multiple FROM positions
            WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
              AND closed_ts_ms >= ? AND r_multiple IS NOT NULL
            """,
            (STRATEGY_ID, FOREX_DEMO_VENUE, since_ms),
        ).fetchall()
    return [float(r[0]) for r in rows]


def _max_dd_pct(conn: sqlite3.Connection) -> float | None:
    rows = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = ? ORDER BY ts_ms
        """,
        (FOREX_DEMO_VENUE,),
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


def _slippage_summary(conn: sqlite3.Connection, cfg: ForexConfig) -> str:
    rows = conn.execute(
        """
        SELECT slippage_pct FROM slippage_log
        WHERE venue = ? AND fill_price IS NOT NULL
        ORDER BY ts_ms DESC LIMIT 20
        """,
        (FOREX_DEMO_VENUE,),
    ).fetchall()
    if not rows:
        return "no fills yet"
    avg_pct = sum(float(r[0]) for r in rows) / len(rows)
    model_pips = cfg.execution.slippage_pips_mean
    return f"avg {avg_pct * 10000:.1f}bp last {len(rows)} fills (model ~{model_pips:.1f}pip)"


def build_forex_weekly_kpi(conn: sqlite3.Connection, cfg: ForexConfig) -> ForexWeeklyKpi:
    now_ms = int(time.time() * 1000)
    week_start = now_ms - WEEK_MS
    month_start = int(
        datetime(
            datetime.fromtimestamp(now_ms / 1000, tz=UTC).year,
            datetime.fromtimestamp(now_ms / 1000, tz=UTC).month,
            1,
            tzinfo=UTC,
        ).timestamp()
        * 1000
    )

    equity_row = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = ? ORDER BY ts_ms DESC LIMIT 1
        """,
        (FOREX_DEMO_VENUE,),
    ).fetchone()
    equity = float(equity_row[0]) if equity_row else cfg.demo.equity_usd

    week_start_equity = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = ? AND ts_ms <= ? ORDER BY ts_ms DESC LIMIT 1
        """,
        (FOREX_DEMO_VENUE, week_start),
    ).fetchone()
    month_start_equity = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = ? AND ts_ms <= ? ORDER BY ts_ms DESC LIMIT 1
        """,
        (FOREX_DEMO_VENUE, month_start),
    ).fetchone()

    trades_week = conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
          AND closed_ts_ms >= ?
        """,
        (STRATEGY_ID, FOREX_DEMO_VENUE, week_start),
    ).fetchone()[0]
    trades_cum = conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
        """,
        (STRATEGY_ID, FOREX_DEMO_VENUE),
    ).fetchone()[0]

    week_pnls = conn.execute(
        """
        SELECT realized_pnl FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
          AND closed_ts_ms >= ? AND realized_pnl IS NOT NULL
        """,
        (STRATEGY_ID, FOREX_DEMO_VENUE, week_start),
    ).fetchall()
    wins_week = sum(1 for (p,) in week_pnls if p > 0)
    losses_week = sum(1 for (p,) in week_pnls if p <= 0)

    all_r = _closed_r(conn)
    week_r = _closed_r(conn, since_ms=week_start)
    exp, lo, hi = _bootstrap_ci(all_r)
    win_rate = None
    if all_r:
        win_rate = sum(1 for r in all_r if r > 0) / len(all_r)

    paper_start = conn.execute(
        "SELECT MIN(ts_ms) FROM equity_snapshots WHERE venue = ? AND mode = 'forex_paper'",
        (FOREX_DEMO_VENUE,),
    ).fetchone()[0]
    paper_days = (now_ms - paper_start) // 86_400_000 if paper_start else None

    week_of = datetime.fromtimestamp(week_start / 1000, tz=UTC).strftime("%Y-%m-%d")
    eq_week = float(week_start_equity[0]) if week_start_equity else cfg.demo.equity_usd
    eq_month = float(month_start_equity[0]) if month_start_equity else cfg.demo.equity_usd

    return ForexWeeklyKpi(
        week_of=week_of,
        equity_usd=equity,
        trades_week=trades_week,
        trades_cum=trades_cum,
        wins_week=wins_week,
        losses_week=losses_week,
        pnl_week_usd=equity - eq_week,
        pnl_month_usd=equity - eq_month,
        win_rate_cum=win_rate,
        expectancy_r=exp if all_r else None,
        expectancy_ci_low=lo if all_r else None,
        expectancy_ci_high=hi if all_r else None,
        max_dd_pct=_max_dd_pct(conn),
        slippage_vs_model=_slippage_summary(conn, cfg),
        paper_days=int(paper_days) if paper_days is not None else None,
        gates_breached=0,
    )


def format_forex_weekly_kpi(kpi: ForexWeeklyKpi) -> str:
    wr = f"{kpi.win_rate_cum:.1%}" if kpi.win_rate_cum is not None else "n/a"
    exp = (
        f"{kpi.expectancy_r:+.3f}R [{kpi.expectancy_ci_low:+.3f}, {kpi.expectancy_ci_high:+.3f}]"
        if kpi.expectancy_r is not None
        else "n/a"
    )
    dd = f"{kpi.max_dd_pct:.1f}%" if kpi.max_dd_pct is not None else "n/a"
    return "\n".join(
        [
            f"Aegis Forex KPI — week of {kpi.week_of}",
            f"Equity:          ${kpi.equity_usd:,.2f}",
            f"Trades (wk/cum): {kpi.trades_week} / {kpi.trades_cum}",
            f"W/L (wk):        {format_win_record(kpi.wins_week, kpi.losses_week)}",
            f"P&L (wk/mo USD): ${kpi.pnl_week_usd:+.2f} / ${kpi.pnl_month_usd:+.2f}",
            f"Win rate (cum):  {wr}",
            f"Expectancy ±CI:  {exp}",
            f"Max DD:          {dd}",
            f"Slippage:        {kpi.slippage_vs_model}",
            f"Paper days:      {kpi.paper_days if kpi.paper_days is not None else 'not started'}",
            f"Gates breached:  {kpi.gates_breached}",
        ]
    )


async def send_forex_weekly_kpi(*, forex_config: str = "config/forex.yaml") -> str:
    from aegis.monitor.telegram import notifier_from_config

    cfg = load_forex_config(forex_config)
    aegis_cfg = load_config()
    conn = db.connect(cfg.demo.sqlite_path)
    try:
        text = format_forex_weekly_kpi(build_forex_weekly_kpi(conn, cfg))
    finally:
        conn.close()

    notifier = notifier_from_config(aegis_cfg)
    if notifier.enabled:
        try:
            await notifier.send(text)
        finally:
            await notifier.close()
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex weekly KPI (Section 5)")
    parser.add_argument("--forex-config", default="config/forex.yaml")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    aegis_cfg = load_config()
    setup_logging(aegis_cfg.monitoring.log_dir, aegis_cfg.monitoring.log_level)

    if args.print_only:
        cfg = load_forex_config(args.forex_config)
        conn = db.connect(cfg.demo.sqlite_path)
        try:
            print(format_forex_weekly_kpi(build_forex_weekly_kpi(conn, cfg)))
        finally:
            conn.close()
    else:
        print(asyncio.run(send_forex_weekly_kpi(forex_config=args.forex_config)))


if __name__ == "__main__":
    main()
