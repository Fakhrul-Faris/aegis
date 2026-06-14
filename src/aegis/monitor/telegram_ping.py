"""Send a one-line Telegram ping to verify bot + chat id (FX5 / crypto).

Usage:
    aegis-telegram-ping
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from aegis.config import load_config
from aegis.log import setup_logging


async def send_ping() -> bool:
    from aegis.monitor.telegram import notifier_from_config

    cfg = load_config()
    notifier = notifier_from_config(cfg)
    if not notifier.enabled:
        print("FAIL: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        print("      (same bot for crypto + forex — see research/forex-fx5-launch.md)")
        return False
    try:
        ok = await notifier.send(
            "Aegis ping OK\n"
            "This bot delivers crypto + forex daily summaries and /forex commands."
        )
        if ok:
            print("OK: message delivered to Telegram")
        else:
            print("FAIL: Telegram API returned not ok — check token and chat id")
        return ok
    finally:
        await notifier.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram connectivity ping")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    ok = asyncio.run(send_ping())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
