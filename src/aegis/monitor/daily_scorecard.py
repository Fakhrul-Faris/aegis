"""Human-readable daily P&L scorecard (USD only).

Plain-language metrics for Telegram daily summary and /paper — no R-multiples
or confidence intervals. Answers: did we make money today, and is the bot alive?
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from aegis.data import db
from aegis.monitor.milestone_schedule import build_path_to_live, format_path_to_live_section

DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
PAPER_STARTING_EQUITY_USD = 1000.0


@dataclass(frozen=True)
class DailyScorecard:
    day_label: str
    pnl_today_usd: float
    closed_pnl_today_usd: float
    wins_today: int
    losses_today: int
    closed_today: int
    equity_now_usd: float
    pnl_week_usd: float
    wins_week: int
    losses_week: int
    all_time_pnl_usd: float
    scanner_ok: bool
    gaps_ok: bool
    snapshots_24h: int
    total_gaps: int


def _utc_day_start_ms(now_ms: int) -> int:
    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    day_start = datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
    return int(day_start.timestamp() * 1000)


def _equity_at_or_before(conn: sqlite3.Connection, ts_ms: int) -> float:
    row = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = 'paper' AND ts_ms <= ?
        ORDER BY ts_ms DESC LIMIT 1
        """,
        (ts_ms,),
    ).fetchone()
    return float(row[0]) if row else PAPER_STARTING_EQUITY_USD


def _closed_pnls(
    conn: sqlite3.Connection,
    *,
    since_ms: int,
    until_ms: int,
) -> list[float]:
    rows = conn.execute(
        """
        SELECT realized_pnl FROM positions
        WHERE strategy = 'A' AND closed_ts_ms IS NOT NULL
          AND closed_ts_ms >= ? AND closed_ts_ms <= ?
          AND realized_pnl IS NOT NULL
        """,
        (since_ms, until_ms),
    ).fetchall()
    return [float(r[0]) for r in rows]


def _win_loss(pnls: list[float]) -> tuple[int, int]:
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    return wins, losses


def _count_gaps(conn: sqlite3.Connection) -> int:
    from aegis.core.models import Venue
    from aegis.core.timeframes import timeframe_ms

    series = conn.execute("SELECT DISTINCT venue, symbol, timeframe FROM candles").fetchall()
    total = 0
    for venue_s, symbol, timeframe in series:
        total += len(
            db.find_gaps(conn, Venue(venue_s), symbol, timeframe, timeframe_ms(timeframe))
        )
    return total


def build_daily_scorecard(conn: sqlite3.Connection, now_ms: int) -> DailyScorecard:
    day_start = _utc_day_start_ms(now_ms)
    week_start = now_ms - WEEK_MS

    equity_now = db.latest_paper_equity(conn, default=PAPER_STARTING_EQUITY_USD)
    equity_day_start = _equity_at_or_before(conn, day_start - 1)
    equity_week_start = _equity_at_or_before(conn, week_start - 1)

    today_pnls = _closed_pnls(conn, since_ms=day_start, until_ms=now_ms)
    week_pnls = _closed_pnls(conn, since_ms=week_start, until_ms=now_ms)
    wins_today, losses_today = _win_loss(today_pnls)
    wins_week, losses_week = _win_loss(week_pnls)

    snapshots_24h = conn.execute(
        "SELECT COUNT(*) FROM market_snapshots WHERE ts_ms >= ?",
        (now_ms - DAY_MS,),
    ).fetchone()[0]
    total_gaps = _count_gaps(conn)

    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    day_label = dt.strftime("%A %b %d, %Y")

    return DailyScorecard(
        day_label=day_label,
        pnl_today_usd=equity_now - equity_day_start,
        closed_pnl_today_usd=sum(today_pnls),
        wins_today=wins_today,
        losses_today=losses_today,
        closed_today=len(today_pnls),
        equity_now_usd=equity_now,
        pnl_week_usd=equity_now - equity_week_start,
        wins_week=wins_week,
        losses_week=losses_week,
        all_time_pnl_usd=equity_now - PAPER_STARTING_EQUITY_USD,
        scanner_ok=snapshots_24h > 0,
        gaps_ok=total_gaps == 0,
        snapshots_24h=snapshots_24h,
        total_gaps=total_gaps,
    )


def format_pnl_usd(amount: float) -> str:
    if amount > 0:
        return f"+${amount:,.2f}"
    if amount < 0:
        return f"-${abs(amount):,.2f}"
    return "$0.00"


def format_win_record(wins: int, losses: int) -> str:
    total = wins + losses
    if total == 0:
        return "no trades"
    pct = wins / total * 100
    return f"{wins}W / {losses}L ({pct:.0f}%)"


def format_daily_scorecard(card: DailyScorecard, conn: sqlite3.Connection, now_ms: int) -> str:
    """Full scorecard block for daily summary and /paper."""
    scanner = "OK" if card.scanner_ok else "DOWN"
    gaps = "OK" if card.gaps_ok else f"{card.total_gaps} gaps"
    path_lines = format_path_to_live_section(build_path_to_live(conn, now_ms))
    return "\n".join(
        [
            f"Aegis — {card.day_label}",
            "",
            "--- TODAY'S MONEY ---",
            f"P&L today:      {format_pnl_usd(card.pnl_today_usd)}",
            f"Closed P&L:    {format_pnl_usd(card.closed_pnl_today_usd)}",
            f"Win rate today: {format_win_record(card.wins_today, card.losses_today)}",
            f"Closed trades:  {card.closed_today}",
            f"Equity now:     ${card.equity_now_usd:,.2f} "
            f"(started ${PAPER_STARTING_EQUITY_USD:,.2f})",
            "",
            "--- THIS WEEK (7d) ---",
            f"Week P&L:       {format_pnl_usd(card.pnl_week_usd)}",
            f"Week record:    {format_win_record(card.wins_week, card.losses_week)}",
            f"All-time P&L:   {format_pnl_usd(card.all_time_pnl_usd)}",
            "",
            *path_lines,
            "",
            "--- IS THE BOT ALIVE? ---",
            f"Scanner (24h):  {scanner} ({card.snapshots_24h} snapshots)",
            f"Data gaps:      {gaps}",
        ]
    )
