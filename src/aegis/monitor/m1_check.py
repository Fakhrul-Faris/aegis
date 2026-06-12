"""M1 gate verification — run after the 72h collection window."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from aegis.config import load_config
from aegis.data import db
from aegis.data.reconcile import reconcile
from aegis.log import setup_logging

HOUR_MS = 3_600_000
REQUIRED_HOURS = 72


def _collection_span_hours(conn) -> float | None:
    row = conn.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM market_snapshots").fetchone()
    if not row or row[0] is None:
        return None
    return (row[1] - row[0]) / HOUR_MS


async def run_m1_check(cfg_path: str, *, skip_reconcile: bool) -> int:
    cfg = load_config(cfg_path)
    conn = db.connect(cfg.sqlite_path)
    failures: list[str] = []

    try:
        span_h = _collection_span_hours(conn)
        if span_h is None or span_h < REQUIRED_HOURS:
            failures.append(
                f"72h collection: FAIL ({span_h:.1f}h span"
                f"{' — no snapshots' if span_h is None else ''})"
            )
        else:
            print(f"72h collection: PASS ({span_h:.1f}h snapshot span)")

        flags = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]
        if flags < 1:
            failures.append("scanner flags accumulating: FAIL (zero flags)")
        else:
            print(f"scanner flags: PASS ({flags} total)")

        recent = conn.execute(
            "SELECT COUNT(*) FROM market_snapshots WHERE ts_ms >= ?",
            (int(time.time() * 1000) - 86_400_000,),
        ).fetchone()[0]
        if recent < 20:
            failures.append(f"recent snapshots (24h): FAIL ({recent})")
        else:
            print(f"recent snapshots (24h): PASS ({recent})")

        if not skip_reconcile:
            print("running reconciliation spot-check...")
            mismatches = await reconcile(cfg, samples_per_venue=5)
            if mismatches:
                failures.append(f"reconciliation: FAIL ({len(mismatches)} mismatches)")
            else:
                print("reconciliation: PASS")
        else:
            print("reconciliation: SKIPPED")

    finally:
        conn.close()

    if failures:
        print("\nM1 GATE: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nM1 GATE: PASS (mark checklist in Tasks & Milestones)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="M1 milestone gate check")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--skip-reconcile", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    sys.exit(asyncio.run(run_m1_check(args.config, skip_reconcile=args.skip_reconcile)))


if __name__ == "__main__":
    main()
