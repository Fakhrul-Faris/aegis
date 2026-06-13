"""Project progression report for Telegram /status commands."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aegis.config import AegisConfig
from aegis.data import db
from aegis.monitor.config_freeze import FREEZE_SCOPE, _ensure_table
from aegis.monitor.m1_check import REQUIRED_HOURS, _collection_span_hours, _snapshot_continuity

from aegis.monitor.milestone_schedule import (
    M1_GATE_TARGET_UTC,
    SOAK_DURATION_DAYS,
    SOAK_FLY_STARTED_UTC,
    soak_end_utc,
)

ICON_PASS = "✅"
ICON_FAIL = "❌"
ICON_WAIT = "⏳"
ICON_TODO = "☐"


@dataclass(frozen=True)
class MilestoneLine:
    code: str
    title: str
    icon: str
    detail: str


def _soak_fly_progress(now: datetime | None = None) -> tuple[float, str]:
    now = now or datetime.now(tz=UTC)
    elapsed = (now - SOAK_FLY_STARTED_UTC).total_seconds() / 86400
    end = SOAK_FLY_STARTED_UTC.timestamp() + SOAK_DURATION_DAYS * 86400
    end_dt = datetime.fromtimestamp(end, tz=UTC)
    detail = (
        f"Fly aegis-testnet-soak · day {elapsed:.1f}/{SOAK_DURATION_DAYS} "
        f"(verdict ~{end_dt.strftime('%b %d %H:%M UTC')})"
    )
    return elapsed, detail


def _soak_verdict_icon(cfg: AegisConfig, elapsed_days: float) -> tuple[str, str]:
    """Read persisted soak verdict; never auto-pass M4 on elapsed time alone."""
    if elapsed_days < SOAK_DURATION_DAYS:
        return ICON_WAIT, ""
    path = Path(cfg.sqlite_path).parent / "soak_verdict.json"
    if not path.exists():
        return ICON_WAIT, " · awaiting FINAL Telegram verdict"
    try:
        verdict = json.loads(path.read_text())
        passed = bool(verdict.get("passed"))
        spreads_fail = verdict.get("spreads_fail", 0)
        anomalies = verdict.get("anomalies", 0)
        suffix = f" · spreads_fail={spreads_fail} anomalies={anomalies}"
        return (ICON_PASS if passed else ICON_FAIL), suffix
    except (json.JSONDecodeError, OSError):
        return ICON_WAIT, " · soak_verdict.json unreadable"


def _m1_status(conn: sqlite3.Connection) -> tuple[str, str]:
    span = _collection_span_hours(conn)
    if span is None:
        return ICON_WAIT, "no snapshot span yet"
    recent = conn.execute(
        "SELECT COUNT(*) FROM market_snapshots WHERE ts_ms >= ?",
        (int(time.time() * 1000) - 86_400_000,),
    ).fetchone()[0]
    flags = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]
    cont_ok, cont_detail = _snapshot_continuity(conn)
    if span >= REQUIRED_HOURS and recent >= 20 and cont_ok:
        flag_note = f"{flags} flags" if flags else "0 flags (quiet market OK)"
        return ICON_PASS, f"{span:.0f}h span · {cont_detail} · {flag_note}"
    parts = [f"{span:.1f}h / {REQUIRED_HOURS}h span", f"{recent} snapshots/24h"]
    if not cont_ok:
        parts.append(cont_detail)
    return ICON_WAIT, " · ".join(parts)


def _config_freeze_status(conn: sqlite3.Connection) -> tuple[bool, str]:
    _ensure_table(conn)
    row = conn.execute(
        "SELECT frozen_at_ms FROM config_freeze WHERE scope = ?", (FREEZE_SCOPE,)
    ).fetchone()
    if not row:
        return False, "not frozen yet (first portfolio run freezes)"
    frozen_at = datetime.fromtimestamp(row[0] / 1000, tz=UTC)
    days = (datetime.now(tz=UTC) - frozen_at).total_seconds() / 86400
    weeks = days / 7
    return True, f"frozen since {frozen_at.strftime('%Y-%m-%d')} ({weeks:.1f}w / 8w paper gate)"


def _local_soak_note(cfg: AegisConfig) -> str | None:
    path = Path(cfg.sqlite_path).parent / "soak_state.json"
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text())
        cycles = state.get("cycle", 0)
        return f"Local soak_state.json exists ({cycles} cycles) — ignore; Fly soak is authoritative"
    except (json.JSONDecodeError, OSError):
        return "Local soak_state.json present but unreadable"


def build_milestones(cfg: AegisConfig, conn: sqlite3.Connection) -> list[MilestoneLine]:
    m1_icon, m1_detail = _m1_status(conn)
    soak_elapsed, soak_detail = _soak_fly_progress()
    soak_icon, soak_suffix = _soak_verdict_icon(cfg, soak_elapsed)
    frozen, freeze_detail = _config_freeze_status(conn)
    paper_running = cfg.mode == "paper"

    m4_detail = f"{soak_detail}{soak_suffix} · 20+ spreads + leg-2 drill done"

    m5_icon = ICON_WAIT if paper_running and frozen else ICON_TODO
    m5_detail = freeze_detail if frozen else "paper pipeline running; formal 8w clock after M4"

    return [
        MilestoneLine("M0", "Dev environment", ICON_PASS, "repo, CI, testnet connectivity"),
        MilestoneLine("M1", "Data + scanner 72h", m1_icon, m1_detail),
        MilestoneLine("M2", "Math engine tests", ICON_PASS, "unit + synthetic validations"),
        MilestoneLine("M3", "Strategy B backtest", ICON_FAIL, "cointegration NO-GO — see research memo"),
        MilestoneLine("M4", "Risk + testnet soak", soak_icon, m4_detail),
        MilestoneLine("M5", "Paper trading start", m5_icon, m5_detail),
        MilestoneLine("M6", "Paper gates (8w)", ICON_TODO, "≥40 trades · expectancy CI · slippage check"),
        MilestoneLine("M7", "Live (Strategy B)", ICON_TODO, "blocked — B path closed"),
        MilestoneLine("M8", "Strategy A promotion", ICON_TODO, "RM2k + 3-gate check (Concept §7)"),
    ]


def build_progress_report(cfg: AegisConfig) -> str:
    conn = db.connect(cfg.sqlite_path)
    try:
        milestones = build_milestones(cfg, conn)
        now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            f"Aegis progression — {now}",
            "",
            "Path: Strategy A paper (primary) · Strategy B cointegration closed",
            "",
            "Milestones:",
        ]
        for m in milestones:
            lines.append(f"  {m.icon} {m.code} {m.title}")
            lines.append(f"      {m.detail}")

        end_dt = soak_end_utc()
        lines.extend(
            [
                "",
                "Strategy research:",
                "  A baseline (EMA+RSI): -0.21R — anomaly edge unproven",
                "  B pairs (2021-26): 0 walk-forward trades — NO-GO",
                "",
                "What's running:",
                "  Mac: ingest, scanner, portfolio (optional while awake)",
                "  Fly: aegis-collector (data + Telegram /commands), aegis-testnet-soak (M4)",
                "",
                "Next gates:",
                f"  M1 check ~{M1_GATE_TARGET_UTC.strftime('%b %d')} — aegis-m1-check",
                f"  M4 soak verdict ~{end_dt.strftime('%b %d %H:%M UTC')}",
                "  Then formal 8-week Strategy A paper clock (M5/M6)",
                "",
                "Do not: restart Fly collector before M1 · local HL soak · change paper config without reset",
            ]
        )

        local_soak = _local_soak_note(cfg)
        if local_soak:
            lines.extend(["", f"Note: {local_soak}"])

        return "\n".join(lines)
    finally:
        conn.close()
