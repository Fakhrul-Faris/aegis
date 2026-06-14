"""FX0 gate smoke check — config, calendar, costs, optional sample download.

Usage:
    aegis-forex-fx0-check
    aegis-forex-fx0-check --download-sample   # 1 week EURUSD from Dukascopy (network)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aegis.config_forex import load_forex_config
from aegis.data import db
from aegis.data.forex_calendar import seed_economic_calendar
from aegis.data.forex_dxy import upsert_dxy_all_timeframes
from aegis.data.forex_download import aggregate_4h_from_1h, download_yahoo_all
from aegis.risk.forex_costs import forex_round_trip_costs


def run_fx0_check(
    config_path: str = "config/forex.yaml",
    *,
    download_sample: bool = False,
) -> int:
    cfg = load_forex_config(config_path)
    failures: list[str] = []

    print(f"forex config: OK ({config_path})")
    print(f"  broker={cfg.broker} pairs={','.join(cfg.pairs)}")
    print(f"  research db={cfg.research.sqlite_path}")

    # Cost model smoke
    micro = forex_round_trip_costs(cfg.costs, "EURUSD", lots=0.01)
    event = forex_round_trip_costs(cfg.costs, "EURUSD", lots=0.01, near_high_impact_event=True)
    print(
        f"cost model EURUSD 0.01 lot: "
        f"spread=${micro.spread_usd:.4f} comm=${micro.commission_usd:.4f} "
        f"slip=${micro.slippage_usd:.4f} total=${micro.total_usd:.4f}"
    )
    print(f"  event spread x{event.event_multiplier}: total=${event.total_usd:.4f}")
    if micro.total_usd <= 0:
        failures.append("cost model returned zero total")

    # DB + calendar seed
    db_path = Path(cfg.research.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(db_path)
    try:
        seeded = seed_economic_calendar(conn, year_start=2015, year_end=2027)
        high_impact = db.count_calendar_events(conn, impact_tier=3)
        print(f"economic calendar: {high_impact} high-impact events (seeded {seeded} new)")
        if high_impact < 100:
            failures.append(f"calendar too thin ({high_impact} events)")
    finally:
        conn.close()

    # Optional Dukascopy sample
    if download_sample:
        print("downloading sample: all pairs via Yahoo (730d 1h + daily)...")
        download_yahoo_all(cfg, pairs=list(cfg.pairs) + list(cfg.dxy_pairs))
        upsert_dxy_all_timeframes(cfg)
        conn = db.connect(cfg.research.sqlite_path)
        try:
            count, min_ms, max_ms = db.candle_series_stats(conn, "forex", "EURUSD", "1h")
            dxy_count, _, _ = db.candle_series_stats(conn, "forex", cfg.dxy.symbol, "1h")
        finally:
            conn.close()
        print(f"sample download: {count} 1h bars; series span {min_ms}..{max_ms}")
        print(f"synthetic DXY 1h bars: {dxy_count}")
        if count < 100:
            failures.append(f"sample download too few bars ({count})")

    if failures:
        print("\nFX0 GATE: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nFX0 GATE: PASS (ready for FX1 session backtest)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="FX0 infrastructure smoke check")
    parser.add_argument("--config", default="config/forex.yaml")
    parser.add_argument(
        "--download-sample",
        action="store_true",
        help="fetch 1 month EURUSD from Dukascopy (requires network)",
    )
    args = parser.parse_args()
    sys.exit(run_fx0_check(args.config, download_sample=args.download_sample))


if __name__ == "__main__":
    main()
