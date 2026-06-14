"""Forex daily summary — uses the same Aegis Telegram bot as crypto.

Prefer the unified daily message via ``aegis-summary`` (crypto + forex).
This CLI prints or sends the forex block only (debug / manual).

Usage:
    aegis-forex-summary --print-only
    aegis-forex-summary   # sends forex-only via same TELEGRAM_BOT_TOKEN
"""

from __future__ import annotations

import argparse
import asyncio

from aegis.config import load_config
from aegis.log import setup_logging
from aegis.monitor.forex_scorecard import build_forex_section


async def send_forex_only_summary() -> str:
    from aegis.monitor.telegram import notifier_from_config

    text = build_forex_section()
    if not text:
        return "forex section unavailable"

    aegis_cfg = load_config()
    notifier = notifier_from_config(aegis_cfg)
    if notifier.enabled:
        try:
            await notifier.send(text)
        finally:
            await notifier.close()
    return text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Forex scoreboard (same Telegram bot; use aegis-summary for unified daily)"
    )
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    aegis_cfg = load_config()
    setup_logging(aegis_cfg.monitoring.log_dir, aegis_cfg.monitoring.log_level)

    text = build_forex_section()
    if not text:
        print("forex section unavailable")
        return

    if args.print_only:
        print(text)
    else:
        print(asyncio.run(send_forex_only_summary()))


if __name__ == "__main__":
    main()
