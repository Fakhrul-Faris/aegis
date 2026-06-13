"""Milestone dates and path-to-live countdown (shared by scorecard + progress)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aegis.monitor.config_freeze import FREEZE_SCOPE, _ensure_table
from aegis.monitor.m1_check import REQUIRED_HOURS, _collection_span_hours, _snapshot_continuity

# Authoritative clocks — update if redeployed / replanned.
SOAK_FLY_STARTED_UTC = datetime(2026, 6, 11, 16, 11, tzinfo=UTC)
SOAK_DURATION_DAYS = 7
M1_GATE_TARGET_UTC = datetime(2026, 6, 13, 16, 0, tzinfo=UTC)
PAPER_GATE_WEEKS = 8
PAPER_GATE_DAYS = PAPER_GATE_WEEKS * 7

# Strategy A live at RM1.5k–2k (Concept §7) — earliest after paper gates.
EST_LIVE_STRATEGY = "Strategy A (volume anomaly swing)"


@dataclass(frozen=True)
class PathToLive:
    next_gate: str
    days_to_next_gate: int
    m4_soak_days_left: int
    paper_weeks_left: float | None
    days_to_live_earliest: int
    live_earliest_label: str
    m1_passed: bool


def soak_end_utc() -> datetime:
    return SOAK_FLY_STARTED_UTC + timedelta(days=SOAK_DURATION_DAYS)


def _days_until(target: datetime, now: datetime) -> int:
    return max(0, int((target - now).total_seconds() // 86400 + 0.999))


def m1_db_passes(conn: sqlite3.Connection, *, now_ms: int | None = None) -> bool:
    """True when local SQLite satisfies M1 span + continuity (no reconcile)."""
    now_ms = now_ms if now_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000)
    span = _collection_span_hours(conn)
    if span is None or span < REQUIRED_HOURS:
        return False
    cont_ok, _ = _snapshot_continuity(conn, now_ms=now_ms)
    if not cont_ok:
        return False
    recent = conn.execute(
        "SELECT COUNT(*) FROM market_snapshots WHERE ts_ms >= ?",
        (now_ms - 86_400_000,),
    ).fetchone()[0]
    return recent >= 20


def _paper_freeze_started_ms(conn: sqlite3.Connection) -> int | None:
    _ensure_table(conn)
    row = conn.execute(
        "SELECT frozen_at_ms FROM config_freeze WHERE scope = ?", (FREEZE_SCOPE,)
    ).fetchone()
    return int(row[0]) if row else None


def build_path_to_live(conn: sqlite3.Connection, now_ms: int | None = None) -> PathToLive:
    now = datetime.fromtimestamp(
        (now_ms if now_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000)) / 1000,
        tz=UTC,
    )
    m1_passed = m1_db_passes(conn, now_ms=int(now.timestamp() * 1000))
    soak_end = soak_end_utc()
    freeze_ms = _paper_freeze_started_ms(conn)

    if not m1_passed:
        next_gate = "M1 data collection (72h)"
        days_next = _days_until(M1_GATE_TARGET_UTC, now) if now < M1_GATE_TARGET_UTC else 0
        live_earliest = soak_end + timedelta(days=PAPER_GATE_DAYS)
    elif now < soak_end:
        next_gate = "M4 testnet soak verdict"
        days_next = _days_until(soak_end, now)
        live_earliest = soak_end + timedelta(days=PAPER_GATE_DAYS)
    elif freeze_ms is None:
        next_gate = "M5 formal paper clock (8w)"
        days_next = 0
        live_earliest = now + timedelta(days=PAPER_GATE_DAYS)
    else:
        frozen_at = datetime.fromtimestamp(freeze_ms / 1000, tz=UTC)
        paper_end = frozen_at + timedelta(days=PAPER_GATE_DAYS)
        next_gate = "M6 paper gates"
        days_next = _days_until(paper_end, now)
        live_earliest = paper_end

    paper_weeks_left: float | None = None
    if freeze_ms is not None:
        frozen_at = datetime.fromtimestamp(freeze_ms / 1000, tz=UTC)
        elapsed_days = (now - frozen_at).total_seconds() / 86400
        paper_weeks_left = max(0.0, PAPER_GATE_WEEKS - elapsed_days / 7)

    return PathToLive(
        next_gate=next_gate,
        days_to_next_gate=days_next,
        m4_soak_days_left=_days_until(soak_end, now),
        paper_weeks_left=paper_weeks_left,
        days_to_live_earliest=_days_until(live_earliest, now),
        live_earliest_label=live_earliest.strftime("%b %d %Y"),
        m1_passed=m1_passed,
    )


def format_path_to_live_section(path: PathToLive) -> list[str]:
    soak_note = (
        f"{path.m4_soak_days_left}d left"
        if path.m4_soak_days_left > 0
        else "complete or in progress"
    )
    if path.paper_weeks_left is not None:
        paper_note = f"{path.paper_weeks_left:.1f}w left of {PAPER_GATE_WEEKS}w"
    elif path.m1_passed and path.m4_soak_days_left == 0:
        paper_note = "starts after M4 (portfolio freeze)"
    else:
        paper_note = f"{PAPER_GATE_WEEKS}w after M4 soak"

    next_days = (
        "due now" if path.days_to_next_gate == 0 else f"{path.days_to_next_gate}d"
    )
    return [
        "--- PATH TO LIVE ---",
        f"Next gate:       {path.next_gate} ({next_days})",
        f"M1 data:         {'PASSED' if path.m1_passed else 'collecting'}",
        f"M4 soak:         {soak_note}",
        f"Paper clock:     {paper_note}",
        f"Days to live:    ~{path.days_to_live_earliest}d earliest ({path.live_earliest_label})",
        f"Live strategy:   {EST_LIVE_STRATEGY}",
    ]
