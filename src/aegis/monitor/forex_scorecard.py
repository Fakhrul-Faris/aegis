"""Forex demo daily scorecard (FX5).

Plain-language USD metrics for Telegram and ``aegis-forex-summary``. Strategy:
event_spike_fade on venue forex_demo.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from aegis.config_forex import ForexConfig, load_forex_config
from aegis.core.models import Venue
from aegis.core.timeframes import timeframe_ms
from aegis.data import db
from aegis.execution.forex_paper import FOREX_DEMO_VENUE
from aegis.monitor.daily_scorecard import format_pnl_usd, format_win_record
from aegis.monitor.forex_reconcile import reconcile_forex_demo

STRATEGY_ID = "event_spike_fade"
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS


@dataclass(frozen=True)
class ForexDailyScorecard:
    day_label: str
    pnl_today_usd: float
    closed_pnl_today_usd: float
    wins_today: int
    losses_today: int
    closed_today: int
    equity_now_usd: float
    pnl_week_usd: float
    pnl_month_usd: float
    wins_week: int
    losses_week: int
    wins_month: int
    losses_month: int
    open_positions: int
    calendar_watches_today: int
    calendar_trades_today: int
    top_skip_reason: str | None
    ingest_ok: bool
    reconcile_ok: bool
    paper_days_elapsed: int | None
    closed_trades_cum: int
    config_hash: str | None


def _utc_day_start_ms(now_ms: int) -> int:
    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    day_start = datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
    return int(day_start.timestamp() * 1000)


def _month_start_ms(now_ms: int) -> int:
    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    month_start = datetime(dt.year, dt.month, 1, tzinfo=UTC)
    return int(month_start.timestamp() * 1000)


def _equity_at_or_before(conn: sqlite3.Connection, ts_ms: int, default: float) -> float:
    row = conn.execute(
        """
        SELECT equity_usd FROM equity_snapshots
        WHERE venue = ? AND ts_ms <= ?
        ORDER BY ts_ms DESC LIMIT 1
        """,
        (FOREX_DEMO_VENUE, ts_ms),
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
        (STRATEGY_ID, FOREX_DEMO_VENUE, since_ms, until_ms),
    ).fetchall()
    return [float(r[0]) for r in rows]


def _win_loss(pnls: list[float]) -> tuple[int, int]:
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    return wins, losses


def _ingest_healthy(conn: sqlite3.Connection, pairs: tuple[str, ...], now_ms: int) -> bool:
    for pair in pairs:
        last = db.last_candle_open_ms(conn, Venue.FOREX_DEMO, pair, "1h")
        if last is None or now_ms - last > 72 * 3_600_000:
            return False
        gaps = db.find_gaps(conn, Venue.FOREX_DEMO, pair, "1h", timeframe_ms("1h"))
        recent = [g for g in gaps if g[0] >= now_ms - 72 * 3_600_000]
        if len(recent) > 2:
            return False
    return True


def _top_skip_reason(conn: sqlite3.Connection, since_ms: int) -> str | None:
    row = conn.execute(
        """
        SELECT skip_reason, COUNT(*) AS n FROM signals
        WHERE strategy = ? AND taken = 0 AND skip_reason IS NOT NULL
          AND ts_ms >= ?
        GROUP BY skip_reason ORDER BY n DESC LIMIT 1
        """,
        (STRATEGY_ID, since_ms),
    ).fetchone()
    if not row:
        return None
    return f"{row[0]}: {row[1]}"


def _calendar_counts(conn: sqlite3.Connection, since_ms: int) -> tuple[int, int]:
    watches = conn.execute(
        """
        SELECT COUNT(*) FROM signals
        WHERE strategy = ? AND ts_ms >= ?
          AND (context_json LIKE '%watch%' OR skip_reason LIKE '%watch%')
        """,
        (STRATEGY_ID, since_ms),
    ).fetchone()[0]
    trades = conn.execute(
        """
        SELECT COUNT(*) FROM signals
        WHERE strategy = ? AND taken = 1 AND ts_ms >= ?
        """,
        (STRATEGY_ID, since_ms),
    ).fetchone()[0]
    return int(watches), int(trades)


def _paper_start_ms(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        """
        SELECT MIN(ts_ms) FROM equity_snapshots
        WHERE venue = ? AND mode = 'forex_paper'
        """,
        (FOREX_DEMO_VENUE,),
    ).fetchone()
    return int(row[0]) if row and row[0] else None


def _config_hash(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute(
            "SELECT config_hash FROM config_freeze WHERE scope = 'forex_event_spike_fade'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def build_forex_daily_scorecard(
    conn: sqlite3.Connection,
    cfg: ForexConfig,
    now_ms: int,
) -> ForexDailyScorecard:
    day_start = _utc_day_start_ms(now_ms)
    week_start = now_ms - WEEK_MS
    month_start = _month_start_ms(now_ms)
    default_equity = cfg.demo.equity_usd

    equity_now = _equity_at_or_before(conn, now_ms, default_equity)
    equity_day_start = _equity_at_or_before(conn, day_start - 1, default_equity)
    equity_week_start = _equity_at_or_before(conn, week_start - 1, default_equity)
    equity_month_start = _equity_at_or_before(conn, month_start - 1, default_equity)

    today_pnls = _closed_pnls(conn, since_ms=day_start, until_ms=now_ms)
    week_pnls = _closed_pnls(conn, since_ms=week_start, until_ms=now_ms)
    month_pnls = _closed_pnls(conn, since_ms=month_start, until_ms=now_ms)
    wins_today, losses_today = _win_loss(today_pnls)
    wins_week, losses_week = _win_loss(week_pnls)
    wins_month, losses_month = _win_loss(month_pnls)

    open_positions = conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NULL
        """,
        (STRATEGY_ID, FOREX_DEMO_VENUE),
    ).fetchone()[0]

    closed_cum = conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NOT NULL
        """,
        (STRATEGY_ID, FOREX_DEMO_VENUE),
    ).fetchone()[0]

    watches, trades = _calendar_counts(conn, since_ms=day_start)
    ingest_ok = _ingest_healthy(conn, cfg.event_spike_fade.pairs, now_ms)
    reconcile_ok, _ = reconcile_forex_demo(conn, starting_equity=default_equity)

    paper_start = _paper_start_ms(conn)
    paper_days = None
    if paper_start is not None:
        paper_days = max(0, (now_ms - paper_start) // DAY_MS)

    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    return ForexDailyScorecard(
        day_label=dt.strftime("%A %b %d, %Y"),
        pnl_today_usd=equity_now - equity_day_start,
        closed_pnl_today_usd=sum(today_pnls),
        wins_today=wins_today,
        losses_today=losses_today,
        closed_today=len(today_pnls),
        equity_now_usd=equity_now,
        pnl_week_usd=equity_now - equity_week_start,
        pnl_month_usd=equity_now - equity_month_start,
        wins_week=wins_week,
        losses_week=losses_week,
        wins_month=wins_month,
        losses_month=losses_month,
        open_positions=open_positions,
        calendar_watches_today=watches,
        calendar_trades_today=trades,
        top_skip_reason=_top_skip_reason(conn, day_start),
        ingest_ok=ingest_ok,
        reconcile_ok=reconcile_ok,
        paper_days_elapsed=paper_days,
        closed_trades_cum=closed_cum,
        config_hash=_config_hash(conn),
    )


def _format_open_positions(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT symbol, side, entry_price, context_json FROM positions
        WHERE strategy = ? AND venue = ? AND closed_ts_ms IS NULL
        """,
        (STRATEGY_ID, FOREX_DEMO_VENUE),
    ).fetchall()
    lines: list[str] = []
    for symbol, side, entry, ctx_raw in rows:
        ctx = json.loads(ctx_raw) if ctx_raw else {}
        target = ctx.get("target")
        pair = f"{symbol[:3]}/{symbol[3:]}" if len(symbol) == 6 else symbol
        target_s = f" · target {target:.5f}" if target else ""
        lines.append(f"  {pair} {side} @ {entry:.5f}{target_s}")
    return lines


def format_forex_daily_scorecard(card: ForexDailyScorecard, conn: sqlite3.Connection) -> str:
    health = []
    health.append("ingest OK" if card.ingest_ok else "ingest FAIL")
    health.append("reconcile OK" if card.reconcile_ok else "reconcile FAIL")

    lines = [
        f"Aegis Forex — {card.day_label}",
        "Strategy: Event Spike Fade (H11c-3)",
        "",
        "--- TODAY ---",
        f"P&L today:       {format_pnl_usd(card.pnl_today_usd)}",
        f"Wins / losses:   {format_win_record(card.wins_today, card.losses_today)}",
        f"Closed trades:   {card.closed_today}",
        f"Equity (demo):   ${card.equity_now_usd:,.2f}",
        "",
        "--- WEEK / MONTH ---",
        f"P&L this week:   {format_pnl_usd(card.pnl_week_usd)}",
        f"Week record:     {format_win_record(card.wins_week, card.losses_week)}",
        f"P&L this month: {format_pnl_usd(card.pnl_month_usd)}",
        f"Win rate (mo):   {format_win_record(card.wins_month, card.losses_month)}",
        "",
        "--- POSITIONS ---",
        f"Open:            {card.open_positions}",
    ]
    lines.extend(_format_open_positions(conn) or ["  (none)"])
    lines.extend(
        [
            "",
            "--- CALENDAR ---",
            f"Alerts today:    {card.calendar_watches_today} watch · {card.calendar_trades_today} trade",
        ]
    )
    if card.top_skip_reason:
        lines.append(f"Skips today:     {card.top_skip_reason}")
    lines.extend(
        [
            "",
            "--- PAPER CLOCK ---",
            f"Days elapsed:    {card.paper_days_elapsed if card.paper_days_elapsed is not None else 'not started'}",
            f"Closed (cum):    {card.closed_trades_cum}",
        ]
    )
    if card.config_hash:
        lines.append(f"Config hash:     {card.config_hash}")
    lines.extend(["", f"Health:          {' · '.join(health)}"])
    return "\n".join(lines)


def build_forex_summary_text(
    conn: sqlite3.Connection,
    cfg: ForexConfig,
    now_ms: int,
    *,
    include_stamp: bool = True,
) -> str:
    import time

    now_ms = now_ms or int(time.time() * 1000)
    card = build_forex_daily_scorecard(conn, cfg, now_ms)
    body = format_forex_daily_scorecard(card, conn)
    if not include_stamp:
        return body
    stamp = datetime.fromtimestamp(now_ms / 1000, tz=UTC).strftime("%H:%M UTC")
    return f"{body}\n\nReport time: {stamp}"


def build_forex_section(*, now_ms: int | None = None, forex_config: str = "config/forex.yaml") -> str | None:
    """Forex scoreboard block for the unified Aegis daily Telegram summary."""
    import time

    from aegis.config_forex import load_forex_config

    try:
        cfg = load_forex_config(forex_config)
    except Exception:
        return None
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    conn = db.connect(cfg.demo.sqlite_path)
    try:
        return build_forex_summary_text(conn, cfg, ts, include_stamp=False)
    finally:
        conn.close()
