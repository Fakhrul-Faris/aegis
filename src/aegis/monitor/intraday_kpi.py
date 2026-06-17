"""Weekly intraday KPI — Phase 1 proof gate tracking."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from aegis.config_intraday import IntradayConfig
from aegis.execution.intraday_paper import INTRADAY_PAPER_VENUE, STRATEGY_C
from aegis.monitor.intraday_scorecard import (
    DAY_MS,
    WEEK_MS,
    _count_win_days,
    _equity_at_or_before,
    format_pnl_usd,
)

TIER_ORDER = ("aggressive", "unknown")


@dataclass(frozen=True)
class IntradayWeeklyKpi:
    week_of: str
    equity_usd: float
    pnl_week_usd: float
    win_days_week: int
    trades_week: int
    trades_cum: int
    win_rate: float | None
    expectancy_r: float | None
    phase1_week_pass: bool
    consecutive_proof_weeks: int


def _closed_r(conn: sqlite3.Connection, since_ms: int) -> list[float]:
    rows = conn.execute(
        """
        SELECT r_multiple FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
          AND closed_ts_ms >= ? AND r_multiple IS NOT NULL
        """,
        (STRATEGY_C, INTRADAY_PAPER_VENUE, since_ms),
    ).fetchall()
    return [float(r[0]) for r in rows]


def _week_pass(conn: sqlite3.Connection, cfg: IntradayConfig, week_start: int, week_end: int) -> bool:
    default = cfg.demo.equity_usd
    eq_start = _equity_at_or_before(conn, week_start - 1, default)
    eq_end = _equity_at_or_before(conn, week_end, default)
    pnl = eq_end - eq_start
    win_days, _ = _count_win_days(conn, week_start, week_end)
    return (
        pnl >= cfg.demo.weekly_profit_target_usd
        and win_days >= cfg.demo.weekly_win_days_min
    )


def _consecutive_proof_weeks(conn: sqlite3.Connection, cfg: IntradayConfig, now_ms: int) -> int:
    streak = 0
    for w in range(cfg.demo.proof_weeks_consecutive):
        week_end = now_ms - w * WEEK_MS
        week_start = week_end - WEEK_MS
        if _week_pass(conn, cfg, week_start, week_end):
            streak += 1
        else:
            break
    return streak


def build_intraday_weekly_kpi(conn: sqlite3.Connection, cfg: IntradayConfig) -> IntradayWeeklyKpi:
    now_ms = int(time.time() * 1000)
    week_start = now_ms - WEEK_MS
    default = cfg.demo.equity_usd
    equity = _equity_at_or_before(conn, now_ms, default)
    eq_week = _equity_at_or_before(conn, week_start - 1, default)
    win_days, _ = _count_win_days(conn, week_start, now_ms)

    rs_week = _closed_r(conn, week_start)
    rs_cum = _closed_r(conn, 0)
    trades_week = len(rs_week)
    trades_cum = len(rs_cum)
    win_rate = sum(1 for r in rs_week if r > 0) / trades_week if trades_week else None
    expectancy = float(np.mean(rs_week)) if rs_week else None

    week_pass = _week_pass(conn, cfg, week_start, now_ms)
    streak = _consecutive_proof_weeks(conn, cfg, now_ms)

    dt = datetime.fromtimestamp(week_start / 1000, tz=UTC)
    return IntradayWeeklyKpi(
        week_of=dt.strftime("%Y-%m-%d"),
        equity_usd=equity,
        pnl_week_usd=equity - eq_week,
        win_days_week=win_days,
        trades_week=trades_week,
        trades_cum=trades_cum,
        win_rate=win_rate,
        expectancy_r=expectancy,
        phase1_week_pass=week_pass,
        consecutive_proof_weeks=streak,
    )


def format_intraday_weekly_kpi(kpi: IntradayWeeklyKpi, cfg: IntradayConfig) -> str:
    wr = f"{kpi.win_rate:.0%}" if kpi.win_rate is not None else "n/a"
    exp = f"{kpi.expectancy_r:+.3f}R" if kpi.expectancy_r is not None else "n/a"
    proof_need = cfg.demo.proof_weeks_consecutive
    gate = (
        kpi.consecutive_proof_weeks >= proof_need
        and kpi.trades_cum >= cfg.demo.min_closed_trades_cum
    )
    return "\n".join(
        [
            "Aegis Intraday KPI (Strategy C)",
            f"Week of {kpi.week_of}",
            "",
            f"Equity:           ${kpi.equity_usd:,.2f}",
            f"Week P&L:         {format_pnl_usd(kpi.pnl_week_usd)}",
            f"Win days (7d):    {kpi.win_days_week}/7",
            f"Trades (week):    {kpi.trades_week}",
            f"Trades (cum):     {kpi.trades_cum}",
            f"Win rate (week):  {wr}",
            f"Expectancy (week): {exp}",
            "",
            f"This week pass:   {'YES' if kpi.phase1_week_pass else 'NO'}",
            f"Proof streak:     {kpi.consecutive_proof_weeks}/{proof_need} weeks",
            f"ID4 gate:         {'PASS' if gate else 'FAIL'}",
        ]
    )


def main() -> None:
    import argparse

    from aegis.config_intraday import load_intraday_config
    from aegis.data import db

    parser = argparse.ArgumentParser(description="Intraday weekly KPI")
    parser.add_argument("--intraday-config", default="config/intraday.yaml")
    args = parser.parse_args()

    cfg = load_intraday_config(args.intraday_config)
    conn = db.connect(cfg.demo.sqlite_path)
    try:
        kpi = build_intraday_weekly_kpi(conn, cfg)
        print(format_intraday_weekly_kpi(kpi, cfg))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
