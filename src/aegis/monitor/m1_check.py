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
MIN_HOURLY_COVERAGE = 0.90  # ≥90% of hours in the 72h window must have a scan batch
MAX_GAP_HOURS = 3.0  # one missed hour + slack; restarts void the gate


def _collection_span_hours(conn) -> float | None:
    row = conn.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM market_snapshots").fetchone()
    if not row or row[0] is None:
        return None
    return (row[1] - row[0]) / HOUR_MS


def _snapshot_continuity(
    conn, *, window_hours: int = REQUIRED_HOURS, now_ms: int | None = None
) -> tuple[bool, str]:
    """Hourly scanner batches with bounded gaps — enforces uninterrupted collection."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    since_ms = now_ms - window_hours * HOUR_MS
    rows = conn.execute(
        "SELECT DISTINCT ts_ms FROM market_snapshots WHERE ts_ms >= ? ORDER BY ts_ms ASC",
        (since_ms,),
    ).fetchall()
    if not rows:
        return False, "no snapshots in last 72h"
    batches = [r[0] for r in rows]
    min_expected = int(window_hours * MIN_HOURLY_COVERAGE)
    if len(batches) < min_expected:
        return (
            False,
            f"hourly coverage {len(batches)}/{window_hours} batches "
            f"(need ≥{min_expected})",
        )
    if len(batches) < 2:
        return False, "need ≥2 hourly batches for gap check"
    max_gap_h = max((batches[i + 1] - batches[i]) / HOUR_MS for i in range(len(batches) - 1))
    if max_gap_h > MAX_GAP_HOURS:
        return False, f"max gap {max_gap_h:.1f}h exceeds {MAX_GAP_HOURS}h limit"
    return True, f"{len(batches)} hourly batches, max gap {max_gap_h:.1f}h"


async def run_m1_check(cfg_path: str, *, skip_reconcile: bool, notify: bool = False) -> int:
    cfg = load_config(cfg_path)
    conn = db.connect(cfg.sqlite_path)
    failures: list[str] = []
    span_h: float | None = None
    flags = 0

    try:
        span_h = _collection_span_hours(conn)
        if span_h is None or span_h < REQUIRED_HOURS:
            failures.append(
                f"72h collection: FAIL ({span_h:.1f}h span"
                f"{' — no snapshots' if span_h is None else ''})"
            )
        else:
            print(f"72h collection: PASS ({span_h:.1f}h snapshot span)")

        cont_ok, cont_detail = _snapshot_continuity(conn)
        if not cont_ok:
            failures.append(f"hourly continuity: FAIL ({cont_detail})")
        else:
            print(f"hourly continuity: PASS ({cont_detail})")

        flags = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]
        print(f"scanner flags: {flags} total (quiet market OK — continuity is the gate)")

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
    if notify and span_h is not None:
        from aegis.monitor.milestones import notify_m1_passed

        await notify_m1_passed(cfg, span_hours=span_h, flag_count=flags)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="M1 milestone gate check")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--skip-reconcile", action="store_true")
    parser.add_argument("--notify", action="store_true", help="Telegram on pass")
    args = parser.parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    sys.exit(
        asyncio.run(
            run_m1_check(args.config, skip_reconcile=args.skip_reconcile, notify=args.notify)
        )
    )


if __name__ == "__main__":
    main()
