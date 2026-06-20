"""M5 gate verification — formal paper clock start (after M1–M4)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from aegis.config import load_config
from aegis.config_intraday import load_intraday_config
from aegis.config_forex import load_forex_config
from aegis.data import db
from aegis.log import setup_logging
from aegis.monitor.config_freeze import FREEZE_SCOPE, config_hash, verify_or_freeze_paper_config
from aegis.monitor.forex_config_freeze import verify_or_freeze_forex_config
from aegis.monitor.intraday_config_freeze import verify_or_freeze_intraday_config

_VERDICT_FILE = "soak_verdict.json"


def _fmt_ms(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def run_m5_check(cfg_path: str) -> int:
    cfg = load_config(cfg_path)
    failures: list[str] = []
    notes: list[str] = []

    if cfg.mode not in ("paper", "testnet"):
        failures.append(f"mode={cfg.mode!r} (expected paper for M5 Strategy A clock)")

    db_path = Path(cfg.sqlite_path)
    if not db_path.is_file():
        failures.append(f"SQLite missing: {db_path}")
        _print_report(failures, notes)
        return 1

    conn = db.connect(str(db_path))
    try:
        # Strategy A paper freeze
        try:
            verify_or_freeze_paper_config(conn, cfg)
            row = conn.execute(
                "SELECT config_hash, frozen_at_ms FROM config_freeze WHERE scope = ?",
                (FREEZE_SCOPE,),
            ).fetchone()
            if row:
                digest, frozen_ms = row
                if digest != config_hash(cfg):
                    failures.append("strategy_a_paper hash mismatch after verify")
                else:
                    notes.append(
                        f"Strategy A freeze: {digest} since {_fmt_ms(frozen_ms)}"
                    )
            else:
                failures.append("strategy_a_paper not frozen — run aegis-portfolio once")
        except Exception as exc:
            failures.append(f"Strategy A config freeze: {exc}")

        # Parallel tracks (informational — do not block M5)
        try:
            fcfg = load_forex_config()
            verify_or_freeze_forex_config(conn, fcfg)
            notes.append("Forex demo freeze: OK")
        except Exception as exc:
            notes.append(f"Forex freeze: {exc}")

        try:
            icfg = load_intraday_config()
            verify_or_freeze_intraday_config(conn, icfg)
            notes.append("Intraday C freeze: OK")
        except Exception as exc:
            notes.append(f"Intraday freeze: {exc}")

        # M4 soak verdict (local copy or note to sync from Fly)
        verdict_path = db_path.parent / _VERDICT_FILE
        if verdict_path.is_file():
            verdict = json.loads(verdict_path.read_text())
            passed = verdict.get("passed") or verdict.get("human_review") == "CONDITIONAL_PASS"
            label = verdict.get("human_review") or ("PASS" if verdict.get("passed") else "FAIL")
            notes.append(f"M4 soak verdict: {label} ({verdict_path})")
            if not passed:
                failures.append(f"M4 soak verdict not passed: {label}")
        else:
            notes.append(
                "M4 soak_verdict.json not on local disk — OK if M4 marked PASS Jun 19 on Fly"
            )

        taken = conn.execute("SELECT COUNT(*) FROM signals WHERE taken = 1").fetchone()[0]
        flags = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]
        notes.append(f"Paper signals taken: {taken} · scanner flags: {flags}")

    finally:
        conn.close()

    _print_report(failures, notes)
    return 0 if not failures else 1


def _print_report(failures: list[str], notes: list[str]) -> None:
    print("M5 gate check (formal Strategy A paper clock)")
    for line in notes:
        print(f"  ✓ {line}")
    if failures:
        print("FAIL:")
        for msg in failures:
            print(f"  ✗ {msg}")
    else:
        print("PASS — schedule Sunday review (deploy/sunday-review.md) and mark M5 in milestones.")


def main() -> None:
    parser = argparse.ArgumentParser(description="M5 paper trading gate check")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    raise SystemExit(run_m5_check(args.config))


if __name__ == "__main__":
    main()
