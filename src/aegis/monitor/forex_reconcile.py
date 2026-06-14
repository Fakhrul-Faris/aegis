"""Forex demo reconciliation (FX4).

Compares SQLite audit trail (orders, fills, positions, equity) for the
``forex_demo`` venue against internal consistency checks.
"""

from __future__ import annotations

import argparse
import sys

from aegis.config_forex import load_forex_config
from aegis.data import db
from aegis.execution.forex_paper import FOREX_DEMO_VENUE


def reconcile_forex_demo(conn, *, starting_equity: float) -> tuple[bool, list[str]]:
    issues: list[str] = []

    fill_count = db.count_fills(conn, FOREX_DEMO_VENUE)
    order_rows = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE venue = ?", (FOREX_DEMO_VENUE,)
    ).fetchone()[0]
    if order_rows and fill_count == 0:
        issues.append("orders exist but no fills")

    open_pos = conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE venue = ? AND strategy = 'event_spike_fade' AND closed_ts_ms IS NULL
        """,
        (FOREX_DEMO_VENUE,),
    ).fetchone()[0]

    snap = conn.execute(
        """
        SELECT equity_usd, ts_ms FROM equity_snapshots
        WHERE venue = ? ORDER BY ts_ms DESC LIMIT 1
        """,
        (FOREX_DEMO_VENUE,),
    ).fetchone()
    if snap is None and fill_count > 0:
        issues.append("fills logged but no equity snapshot")

    slip_rows = conn.execute(
        "SELECT COUNT(*) FROM slippage_log WHERE venue = ?", (FOREX_DEMO_VENUE,)
    ).fetchone()[0]
    if fill_count and slip_rows < fill_count:
        issues.append(f"slippage_log ({slip_rows}) < fills ({fill_count})")

    realized = conn.execute(
        """
        SELECT COALESCE(SUM(realized_pnl), 0) FROM positions
        WHERE venue = ? AND closed_ts_ms IS NOT NULL
        """,
        (FOREX_DEMO_VENUE,),
    ).fetchone()[0]
    fees = conn.execute(
        "SELECT COALESCE(SUM(fee), 0) FROM fills WHERE venue = ?",
        (FOREX_DEMO_VENUE,),
    ).fetchone()[0]
    expected_equity = starting_equity + float(realized) - float(fees)
    if snap and abs(float(snap[0]) - expected_equity) > max(1.0, starting_equity * 0.05):
        issues.append(
            f"equity snapshot ${snap[0]:.2f} vs modeled ${expected_equity:.2f} "
            f"(open_positions={open_pos})"
        )

    return len(issues) == 0, issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex demo reconcile")
    parser.add_argument("--config", default="config/forex.yaml")
    args = parser.parse_args()
    cfg = load_forex_config(args.config)
    conn = db.connect(cfg.demo.sqlite_path)
    try:
        ok, issues = reconcile_forex_demo(conn, starting_equity=cfg.demo.equity_usd)
        print(f"forex reconcile venue={FOREX_DEMO_VENUE}")
        print(f"  fills: {db.count_fills(conn, FOREX_DEMO_VENUE)}")
        if ok:
            print("RECONCILE: PASS")
            sys.exit(0)
        print("RECONCILE: FAIL")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
