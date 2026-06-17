"""Intraday Strategy C daily scorecard — USD + win-day tracking (Phase 1)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from aegis.config_intraday import IntradayConfig
from aegis.core.models import Venue
from aegis.core.timeframes import timeframe_ms
from aegis.data import db
from aegis.execution.intraday_paper import INTRADAY_PAPER_VENUE, STRATEGY_C
from aegis.monitor.daily_scorecard import format_pnl_usd, format_win_record

DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS


@dataclass(frozen=True)
class IntradayDailyScorecard:
    day_label: str
    pnl_today_usd: float
    closed_pnl_today_usd: float
    wins_today: int
    losses_today: int
    closed_today: int
    equity_now_usd: float
    pnl_week_usd: float
    win_days_week: int
    days_elapsed_week: int
    wins_week: int
    losses_week: int
    open_positions: int
    closed_trades_cum: int
    ingest_ok: bool
    phase1_weekly_target_usd: float
    phase1_win_days_target: int
    config_hash: str | None


def _utc_day_start_ms(now_ms: int) -> int:
    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    day_start = datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
    return int(day_start.timestamp() * 1000)


def _equity_at_or_before(conn: sqlite3.Connection, ts_ms: int, default: float) -> float:
    row = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = ? AND ts_ms <= ?
        ORDER BY ts_ms DESC LIMIT 1
        """,
        (INTRADAY_PAPER_VENUE, ts_ms),
    ).fetchone()
    return float(row[0]) if row else default


def _closed_pnls(conn: sqlite3.Connection, *, since_ms: int, until_ms: int) -> list[float]:
    rows = conn.execute(
        """
        SELECT realized_pnl FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
          AND closed_ts_ms >= ? AND closed_ts_ms <= ?
          AND realized_pnl IS NOT NULL
        """,
        (STRATEGY_C, INTRADAY_PAPER_VENUE, since_ms, until_ms),
    ).fetchall()
    return [float(r[0]) for r in rows]


def _win_loss(pnls: list[float]) -> tuple[int, int]:
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    return wins, losses


def _count_win_days(conn: sqlite3.Connection, week_start_ms: int, now_ms: int) -> tuple[int, int]:
    """Return (win_days, days_with_data) in the rolling 7d window."""
    win_days = 0
    days_with_data = 0
    for offset in range(7):
        day_start = week_start_ms + offset * DAY_MS
        if day_start > now_ms:
            break
        day_end = day_start + DAY_MS - 1
        eq_start = _equity_at_or_before(conn, day_start - 1, default=-1.0)
        eq_end = _equity_at_or_before(conn, min(day_end, now_ms), default=-1.0)
        if eq_start < 0 or eq_end < 0:
            continue
        days_with_data += 1
        if eq_end > eq_start:
            win_days += 1
    return win_days, days_with_data


def _ingest_healthy(conn: sqlite3.Connection, symbols: tuple[str, ...], now_ms: int) -> bool:
    tf = "15m"
    for symbol in symbols:
        last = db.last_candle_open_ms(conn, Venue.HYPERLIQUID, symbol, tf)
        if last is None or now_ms - last > 2 * timeframe_ms(tf):
            return False
    return True


def _config_hash(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute(
            "SELECT config_hash FROM config_freeze WHERE scope = 'intraday_momentum_day'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def build_intraday_daily_scorecard(
    conn: sqlite3.Connection,
    cfg: IntradayConfig,
    now_ms: int,
) -> IntradayDailyScorecard:
    day_start = _utc_day_start_ms(now_ms)
    week_start = now_ms - WEEK_MS
    default_equity = cfg.demo.equity_usd

    equity_now = db.latest_equity_for_venue(conn, INTRADAY_PAPER_VENUE, default=default_equity)
    equity_day_start = _equity_at_or_before(conn, day_start - 1, default_equity)
    equity_week_start = _equity_at_or_before(conn, week_start - 1, default_equity)

    today_pnls = _closed_pnls(conn, since_ms=day_start, until_ms=now_ms)
    week_pnls = _closed_pnls(conn, since_ms=week_start, until_ms=now_ms)
    wins_today, losses_today = _win_loss(today_pnls)
    wins_week, losses_week = _win_loss(week_pnls)
    win_days_week, days_elapsed_week = _count_win_days(conn, week_start, now_ms)

    open_positions = conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NULL
        """,
        (STRATEGY_C, INTRADAY_PAPER_VENUE),
    ).fetchone()[0]

    closed_cum = conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
        """,
        (STRATEGY_C, INTRADAY_PAPER_VENUE),
    ).fetchone()[0]

    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    return IntradayDailyScorecard(
        day_label=dt.strftime("%A %b %d, %Y"),
        pnl_today_usd=equity_now - equity_day_start,
        closed_pnl_today_usd=sum(today_pnls),
        wins_today=wins_today,
        losses_today=losses_today,
        closed_today=len(today_pnls),
        equity_now_usd=equity_now,
        pnl_week_usd=equity_now - equity_week_start,
        win_days_week=win_days_week,
        days_elapsed_week=days_elapsed_week,
        wins_week=wins_week,
        losses_week=losses_week,
        open_positions=open_positions,
        closed_trades_cum=closed_cum,
        ingest_ok=_ingest_healthy(conn, cfg.momentum_day.symbols, now_ms),
        phase1_weekly_target_usd=cfg.demo.weekly_profit_target_usd,
        phase1_win_days_target=cfg.demo.weekly_win_days_min,
        config_hash=_config_hash(conn),
    )


def format_intraday_daily_scorecard(card: IntradayDailyScorecard) -> str:
    weekly_ok = (
        card.pnl_week_usd >= card.phase1_weekly_target_usd
        and card.win_days_week >= card.phase1_win_days_target
    )
    phase1 = "ON TRACK" if weekly_ok else "BUILDING"
    ingest = "OK" if card.ingest_ok else "STALE"
    return "\n".join(
        [
            f"Intraday Paper (C) — {card.day_label}",
            "",
            "--- TODAY ---",
            f"P&L today:      {format_pnl_usd(card.pnl_today_usd)}",
            f"Closed P&L:     {format_pnl_usd(card.closed_pnl_today_usd)}",
            f"Trades today:   {format_win_record(card.wins_today, card.losses_today)}",
            f"Equity:         ${card.equity_now_usd:,.2f}",
            "",
            "--- PHASE 1 TARGETS (rolling 7d) ---",
            f"Week P&L:       {format_pnl_usd(card.pnl_week_usd)} "
            f"(target ≥${card.phase1_weekly_target_usd:.0f})",
            f"Win days:       {card.win_days_week}/{card.days_elapsed_week} "
            f"(target ≥{card.phase1_win_days_target}/7)",
            f"Phase 1 status: {phase1}",
            "",
            "--- HEALTH ---",
            f"Open positions: {card.open_positions}",
            f"Closed cum:     {card.closed_trades_cum}",
            f"15m ingest:     {ingest}",
            f"Config hash:    {card.config_hash or 'not frozen'}",
        ]
    )


def format_intraday_scorecard_html(card: IntradayDailyScorecard) -> str:
    from aegis.monitor.telegram_html import (
        bold,
        format_pnl_html,
        pnl_emoji,
        pre_block,
        status_emoji,
    )

    weekly_ok = (
        card.pnl_week_usd >= card.phase1_weekly_target_usd
        and card.win_days_week >= card.phase1_win_days_target
    )
    phase1 = "ON TRACK 🎯" if weekly_ok else "BUILDING 🔧"
    phase_emoji = "🎯" if weekly_ok else "🔧"

    body = "\n".join(
        [
            f"{pnl_emoji(card.pnl_today_usd)} Today P&L   {format_pnl_html(card.pnl_today_usd)}",
            f"📋 Closed      {format_pnl_html(card.closed_pnl_today_usd)}",
            f"🎲 Trades      {format_win_record(card.wins_today, card.losses_today)}",
            f"💼 Equity      ${card.equity_now_usd:,.2f}",
            "",
            f"{pnl_emoji(card.pnl_week_usd)} Week P&L     {format_pnl_html(card.pnl_week_usd)}"
            f"  (≥${card.phase1_weekly_target_usd:.0f})",
            f"📅 Win days    {card.win_days_week}/{card.days_elapsed_week}"
            f"  (≥{card.phase1_win_days_target}/7)",
            f"{phase_emoji} Phase 1     {phase1}",
            "",
            f"📂 Open        {card.open_positions}",
            f"✔️  Closed cum  {card.closed_trades_cum}",
            f"{status_emoji(card.ingest_ok)} 15m ingest   {'OK' if card.ingest_ok else 'STALE'}",
            f"🔒 Config      {card.config_hash or 'not frozen'}",
        ]
    )
    return f"{bold('⚡ Intraday Paper (C)')}\n{pre_block(body)}"


def build_intraday_section(
    *,
    now_ms: int | None = None,
    intraday_config: str = "config/intraday.yaml",
    html: bool = False,
) -> str | None:
    """Intraday scoreboard for unified daily summary."""
    import time

    from aegis.config_intraday import load_intraday_config

    try:
        cfg = load_intraday_config(intraday_config)
    except Exception:
        return None
    if not cfg.momentum_day.enabled:
        return None

    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    conn = db.connect(cfg.demo.sqlite_path)
    try:
        card = build_intraday_daily_scorecard(conn, cfg, ts)
        if html:
            return format_intraday_scorecard_html(card)
        return format_intraday_daily_scorecard(card)
    finally:
        conn.close()


def main() -> None:
    import argparse
    import time

    from aegis.config_intraday import load_intraday_config

    parser = argparse.ArgumentParser(description="Intraday daily scorecard")
    parser.add_argument("--intraday-config", default="config/intraday.yaml")
    args = parser.parse_args()

    cfg = load_intraday_config(args.intraday_config)
    conn = db.connect(cfg.demo.sqlite_path)
    try:
        card = build_intraday_daily_scorecard(conn, cfg, int(time.time() * 1000))
        print(format_intraday_daily_scorecard(card))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
