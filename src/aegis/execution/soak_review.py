"""Analyze Fly/local testnet soak results and record human M4 verdict."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aegis.config import load_config
from aegis.execution.testnet_soak import SOAK_DURATION_DAYS, _VERDICT_FILE, _save_verdict
from aegis.execution.testnet_soak import SoakState, _state_path


@dataclass(frozen=True)
class SoakWindowStats:
    start_ms: int
    end_ms: int
    events: dict[str, int]
    sample_anomalies: list[str]


def _window_stats(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> SoakWindowStats:
    events = {
        row[0]: row[1]
        for row in conn.execute(
            """
            SELECT event, COUNT(*) FROM soak_log
            WHERE ts_ms >= ? AND ts_ms < ?
            GROUP BY event
            """,
            (start_ms, end_ms),
        )
    }
    samples = [
        row[0]
        for row in conn.execute(
            """
            SELECT detail_json FROM soak_log
            WHERE event = 'anomaly' AND ts_ms >= ? AND ts_ms < ?
            ORDER BY ts_ms LIMIT 5
            """,
            (start_ms, end_ms),
        )
    ]
    return SoakWindowStats(start_ms, end_ms, events, samples)


def analyze_soak(sqlite_path: str) -> str:
    path = Path(sqlite_path)
    if not path.is_file():
        raise SystemExit(f"SQLite not found: {path}")

    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT ts_ms FROM soak_log WHERE event = 'soak_start' ORDER BY ts_ms LIMIT 1"
        ).fetchone()
        if not row:
            raise SystemExit("No soak_start in soak_log")
        start_ms = int(row[0])
        end_ms = start_ms + SOAK_DURATION_DAYS * 86_400_000
        win = _window_stats(conn, start_ms, end_ms)

        state_path = path.parent / "soak_state.json"
        state_note = ""
        if state_path.exists():
            state = SoakState(**json.loads(state_path.read_text()))
            state_note = (
                f"soak_state.json: cycle={state.cycle} "
                f"spreads {state.spreads_ok}ok/{state.spreads_fail}fail "
                f"anomalies={state.anomalies} (may include post-day-7 restarts)"
            )

        lines = [
            "M4 TESTNET SOAK REVIEW",
            f"Window: {datetime.fromtimestamp(start_ms/1000, UTC)} → "
            f"{datetime.fromtimestamp(end_ms/1000, UTC)}",
            "",
            "First 7 days (soak_log):",
        ]
        for event, count in sorted(win.events.items(), key=lambda x: -x[1]):
            lines.append(f"  {event}: {count}")
        if win.sample_anomalies:
            lines.extend(["", "Sample anomalies:"])
            for s in win.sample_anomalies:
                lines.append(f"  {s[:160]}")
        if state_note:
            lines.extend(["", state_note])
        lines.extend(
            [
                "",
                "Auto pass: anomalies=0 AND spreads_fail=0 in 7d window",
                f"  → {'PASS' if win.events.get('anomaly', 0) == 0 and win.events.get('spread_fail', 0) == 0 else 'NEEDS REVIEW'}",
                "",
                "See research/m4-soak-verdict.md for human CONDITIONAL PASS rationale.",
            ]
        )
        return "\n".join(lines)
    finally:
        conn.close()


def record_human_pass(cfg_path: str, *, note: str) -> None:
    cfg = load_config(cfg_path)
    state_path = _state_path(cfg)
    if not state_path.exists():
        raise SystemExit(f"Missing {state_path}")
    state = SoakState(**json.loads(state_path.read_text()))
    _save_verdict(
        cfg,
        passed=True,
        state=state,
        auto_passed=False,
        human_review="CONDITIONAL_PASS",
        review_note=note,
        reviewed_at_ms=int(time.time() * 1000),
    )
    print(f"Wrote human M4 pass to {Path(cfg.sqlite_path).parent / _VERDICT_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="M4 testnet soak review")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--db", help="path to aegis.sqlite (default: config sqlite_path under data/)")
    parser.add_argument(
        "--record-human-pass",
        action="store_true",
        help="write soak_verdict.json with human CONDITIONAL_PASS (M4 machine gate)",
    )
    parser.add_argument(
        "--note",
        default="7d Fly soak; testnet spread/anomaly noise documented in research/m4-soak-verdict.md",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    db_path = args.db
    if not db_path:
        candidate = Path(cfg.sqlite_path)
        db_path = str(candidate if candidate.is_file() else Path("data") / candidate.name)

    print(analyze_soak(db_path))

    if args.record_human_pass:
        record_human_pass(args.config, note=args.note)


if __name__ == "__main__":
    main()
