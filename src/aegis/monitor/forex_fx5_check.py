"""FX5 gate check — demo paper launch readiness.

Usage:
    aegis-forex-fx5-check
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from aegis.config import load_config
from aegis.config_forex import load_forex_config
from aegis.data import db
from aegis.data.forex_calendar import seed_economic_calendar
from aegis.execution.forex_paper import FOREX_DEMO_VENUE
from aegis.monitor.forex_config_freeze import verify_or_freeze_forex_config
from aegis.monitor.forex_scorecard import build_forex_daily_scorecard


def run_fx5_check(config_path: str = "config/forex.yaml") -> int:
    cfg = load_forex_config(config_path)
    aegis_cfg = load_config()
    failures: list[str] = []
    warnings: list[str] = []

    print("FX5 paper launch check")
    print(f"  strategy: {cfg.active_strategy}")
    print(f"  pairs: {', '.join(cfg.event_spike_fade.pairs)}")
    print(f"  demo db: {cfg.demo.sqlite_path}")

    fly_app = os.environ.get("FLY_APP_NAME")
    if fly_app:
        print(f"  fly app: {fly_app} (Telegram via fly secrets)")
    elif not aegis_cfg.secrets.telegram_bot_token:
        warnings.append(
            "Telegram not in local .env — OK if aegis-collector on Fly has "
            "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID"
        )

    print(f"  demo data: {cfg.demo.data_source} (yahoo = no broker signup)")

    conn = db.connect(cfg.demo.sqlite_path)
    try:
        seed_economic_calendar(conn)
        digest = verify_or_freeze_forex_config(conn, cfg)
        print(f"  config freeze: {digest}")

        cal_count = db.count_calendar_events(conn, impact_tier=3)
        if cal_count < 50:
            failures.append(f"calendar thin ({cal_count} tier-3 events)")

        now_ms = int(time.time() * 1000)
        card = build_forex_daily_scorecard(conn, cfg, now_ms)
        print(f"  equity: ${card.equity_now_usd:.2f}")
        print(f"  ingest: {'OK' if card.ingest_ok else 'FAIL'}")
        print(f"  reconcile: {'OK' if card.reconcile_ok else 'FAIL'}")

        if not card.ingest_ok:
            failures.append("ingest unhealthy — run aegis-forex-ingest")
        if not card.reconcile_ok:
            failures.append("reconcile failed")

        fills = db.count_fills(conn, FOREX_DEMO_VENUE)
        if fills == 0:
            warnings.append("no paper fills yet — run aegis-forex-paper-run after funding demo")
    finally:
        conn.close()

    for w in warnings:
        print(f"  WARN: {w}")

    if failures:
        print("\nFX5 GATE: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nFX5 GATE: PASS — start cron (see scripts/forex-crontab.example)")
    print(f"  paper target: {cfg.demo.paper_days_min}–{cfg.demo.paper_days_max} days, "
          f">= {cfg.demo.min_closed_trades} closed trades")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="FX5 demo paper launch gate")
    parser.add_argument("--config", default="config/forex.yaml")
    args = parser.parse_args()
    sys.exit(run_fx5_check(args.config))


if __name__ == "__main__":
    main()
