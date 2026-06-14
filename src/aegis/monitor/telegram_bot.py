"""Read-only Telegram command bot — status on demand (P0.5 extension).

Long-polls Telegram for commands from the configured chat only. No trading
or config changes — query handlers reuse summary, KPI, and doctor logic.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from aegis.config import AegisConfig, load_config
from aegis.data import db
from aegis.log import setup_logging
from aegis.monitor.config_freeze import FREEZE_SCOPE, config_hash
from aegis.monitor.daily_scorecard import build_daily_scorecard, format_daily_scorecard
from aegis.monitor.doctor import format_doctor_report
from aegis.monitor.kpi import build_weekly_kpi, format_weekly_kpi
from aegis.monitor.progress import build_progress_report
from aegis.monitor.summary import build_summary
from aegis.monitor.telegram import TelegramNotifier, notifier_from_config

logger = logging.getLogger(__name__)

POLL_TIMEOUT_S = 25
OFFSET_FILE = "telegram_bot.offset"

BOT_COMMANDS = [
    {"command": "status", "description": "Daily-style heartbeat"},
    {"command": "paper", "description": "Paper equity and positions"},
    {"command": "scanner", "description": "Volume anomaly flags"},
    {"command": "health", "description": "Stack health check"},
    {"command": "progress", "description": "Milestones and project status"},
    {"command": "kpi", "description": "Weekly KPI snapshot"},
    {"command": "forex", "description": "Forex demo scoreboard"},
    {"command": "forex_kpi", "description": "Forex weekly KPI"},
    {"command": "help", "description": "Command list"},
]

MENU_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "Progress", "callback_data": "progress"},
            {"text": "Paper", "callback_data": "paper"},
        ],
        [
            {"text": "Scanner", "callback_data": "scanner"},
            {"text": "Health", "callback_data": "health"},
        ],
        [{"text": "KPI", "callback_data": "kpi"}],
        [{"text": "Forex", "callback_data": "forex"}],
    ]
}

HELP_TEXT = (
    "Aegis bot — read-only status\n\n"
    "/status — heartbeat + menu buttons\n"
    "/progress — milestones and where we are\n"
    "/paper — paper equity, positions, config freeze\n"
    "/scanner — anomaly flags\n"
    "/health — doctor checks (no live Kraken ping)\n"
    "/kpi — weekly KPI for Section 5\n"
    "/forex — forex demo scoreboard (event spike fade)\n"
    "/forex_kpi — forex weekly KPI\n"
    "/help — this message\n\n"
    "Alerts still push automatically. This bot only answers queries."
)


def _offset_path(cfg: AegisConfig) -> Path:
    return Path(cfg.monitoring.log_dir) / OFFSET_FILE


def _load_offset(cfg: AegisConfig) -> int | None:
    path = _offset_path(cfg)
    if not path.exists():
        return None
    try:
        value = int(path.read_text().strip())
        return value if value > 0 else None
    except ValueError:
        return None


def _save_offset(cfg: AegisConfig, offset: int) -> None:
    path = _offset_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset))


def _authorized(cfg: AegisConfig, chat_id: int | str) -> bool:
    allowed = cfg.secrets.telegram_chat_id
    return allowed is not None and str(chat_id) == str(allowed)


def parse_command(text: str) -> str | None:
    if not text or not text.startswith("/"):
        return None
    token = text.split()[0].lower()
    if "@" in token:
        token = token.split("@", 1)[0]
    name = token.lstrip("/")
    return name if name else None


def _config_freeze_line(conn: sqlite3.Connection, cfg: AegisConfig) -> str:
    from aegis.monitor.config_freeze import _ensure_table

    _ensure_table(conn)
    row = conn.execute(
        "SELECT config_hash, frozen_at_ms FROM config_freeze WHERE scope = ?",
        (FREEZE_SCOPE,),
    ).fetchone()
    if not row:
        return "Config freeze: not set (first paper run will freeze)"
    frozen_at = datetime.fromtimestamp(row[1] / 1000, tz=UTC).strftime("%Y-%m-%d UTC")
    current = config_hash(cfg)
    status = "match" if row[0] == current else "MISMATCH — fix config or reset freeze"
    return f"Config freeze: {row[0]} ({status}), since {frozen_at}"


def build_paper_report(cfg: AegisConfig) -> str:
    conn = db.connect(cfg.sqlite_path)
    try:
        now_ms = int(time.time() * 1000)
        card = build_daily_scorecard(conn, now_ms)
        open_positions = db.open_paper_positions(conn)
        taken = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE strategy='A' AND taken=1"
        ).fetchone()[0]
        skipped = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE strategy='A' AND taken=0"
        ).fetchone()[0]

        lines = [
            format_daily_scorecard(card, conn, now_ms),
            "",
            f"Mode: {cfg.mode}",
            f"Signals: {taken} taken / {skipped} skipped",
            _config_freeze_line(conn, cfg),
        ]
        if open_positions:
            lines.append("")
            lines.append("Open positions:")
            for pos in open_positions:
                lines.append(
                    f"  {pos.symbol} qty={pos.quantity:.6f} @ ${pos.entry_price:,.2f}"
                )
        return "\n".join(lines)
    finally:
        conn.close()


def build_scanner_report(cfg: AegisConfig) -> str:
    conn = db.connect(cfg.sqlite_path)
    try:
        now = int(time.time() * 1000)
        since = now - 86_400_000
        flags_24h = conn.execute(
            "SELECT COUNT(*) FROM scanner_flags WHERE ts_ms >= ?", (since,)
        ).fetchone()[0]
        flags_total = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]
        variants = conn.execute(
            """
            SELECT variant, COUNT(*) FROM scanner_flags
            WHERE ts_ms >= ? GROUP BY variant ORDER BY variant
            """,
            (since,),
        ).fetchall()
        last_flag = conn.execute("SELECT MAX(ts_ms) FROM scanner_flags").fetchone()[0]
        snapshots_24h = conn.execute(
            "SELECT COUNT(*) FROM market_snapshots WHERE ts_ms >= ?", (since,)
        ).fetchone()[0]

        variant_line = ", ".join(f"{v}: {n}" for v, n in variants) or "none"
        last_line = (
            datetime.fromtimestamp(last_flag / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
            if last_flag
            else "never"
        )
        return (
            f"Aegis scanner\n"
            f"Snapshots (24h): {snapshots_24h}\n"
            f"Flags (24h): {flags_24h} ({variant_line})\n"
            f"Flags (all time): {flags_total}\n"
            f"Last flag: {last_line}\n"
            f"Threshold: {cfg.scanner.volume_multiple}x vs 20d baseline"
        )
    finally:
        conn.close()


def build_forex_report() -> str:
    import time

    from aegis.config_forex import load_forex_config
    from aegis.monitor.forex_config_freeze import forex_config_hash
    from aegis.monitor.forex_scorecard import build_forex_summary_text

    cfg = load_forex_config()
    conn = db.connect(cfg.demo.sqlite_path)
    try:
        text = build_forex_summary_text(conn, cfg, int(time.time() * 1000))
        return f"{text}\n\nFreeze hash: {forex_config_hash(cfg)}"
    finally:
        conn.close()


def build_forex_kpi_report() -> str:
    from aegis.config_forex import load_forex_config
    from aegis.monitor.forex_kpi import build_forex_weekly_kpi, format_forex_weekly_kpi

    cfg = load_forex_config()
    conn = db.connect(cfg.demo.sqlite_path)
    try:
        return format_forex_weekly_kpi(build_forex_weekly_kpi(conn, cfg))
    finally:
        conn.close()


async def dispatch_command(cfg: AegisConfig, command: str) -> tuple[str, dict | None]:
    """Return message text and optional reply_markup."""
    if command in ("start", "help"):
        return HELP_TEXT, MENU_KEYBOARD
    if command == "status":
        conn = db.connect(cfg.sqlite_path)
        try:
            text = build_summary(conn)
        finally:
            conn.close()
        return f"{text}\n\nReply via buttons or /commands.", MENU_KEYBOARD
    if command == "paper":
        return build_paper_report(cfg), None
    if command == "scanner":
        return build_scanner_report(cfg), None
    if command == "health":
        text, ok = await format_doctor_report(cfg, check_kraken=False)
        prefix = "Health: OK" if ok else "Health: ISSUES"
        return f"{prefix}\n\n{text}", None
    if command == "kpi":
        conn = db.connect(cfg.sqlite_path)
        try:
            return format_weekly_kpi(build_weekly_kpi(conn)), None
        finally:
            conn.close()
    if command == "progress":
        return build_progress_report(cfg), None
    if command == "forex":
        return build_forex_report(), None
    if command == "forex_kpi":
        return build_forex_kpi_report(), None
    return f"Unknown command /{command}. Try /help.", None


async def handle_update(cfg: AegisConfig, notifier: TelegramNotifier, update: dict) -> int | None:
    """Process one update. Returns new offset (update_id + 1) if handled."""
    update_id = update.get("update_id")
    if update_id is None:
        return None

    callback = update.get("callback_query")
    if callback:
        chat_id = callback.get("message", {}).get("chat", {}).get("id")
        if not _authorized(cfg, chat_id):
            logger.warning("ignored callback from unauthorized chat", extra={"chat_id": chat_id})
            return update_id + 1
        data = callback.get("data") or ""
        query_id = callback.get("id", "")
        text, markup = await dispatch_command(cfg, data)
        await notifier.answer_callback_query(query_id)
        await notifier.send(text, chat_id=str(chat_id), reply_markup=markup)
        return update_id + 1

    message = update.get("message") or update.get("edited_message")
    if not message:
        return update_id + 1

    chat_id = message.get("chat", {}).get("id")
    if not _authorized(cfg, chat_id):
        logger.warning("ignored message from unauthorized chat", extra={"chat_id": chat_id})
        return update_id + 1

    text = message.get("text") or ""
    command = parse_command(text)
    if command is None:
        if text.strip():
            await notifier.send(
                "Send /help for commands. This bot is read-only status only.",
                chat_id=str(chat_id),
            )
        return update_id + 1

    reply, markup = await dispatch_command(cfg, command)
    await notifier.send(reply, chat_id=str(chat_id), reply_markup=markup)
    return update_id + 1


def command_bot_enabled(cfg: AegisConfig) -> bool:
    """True when long-poll command bot can run (token + chat id configured)."""
    return bool(
        cfg.monitoring.telegram_enabled
        and cfg.secrets.telegram_bot_token
        and cfg.secrets.telegram_chat_id
    )


async def run_bot(cfg: AegisConfig, *, once: bool = False) -> None:
    notifier = notifier_from_config(cfg)
    if not notifier.enabled:
        raise SystemExit("Telegram bot requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    await notifier.set_commands(BOT_COMMANDS)
    offset = _load_offset(cfg)
    logger.info("telegram bot listening", extra={"chat_id": cfg.secrets.telegram_chat_id})

    try:
        while True:
            updates = await notifier.get_updates(offset=offset, timeout=POLL_TIMEOUT_S)
            for update in updates:
                new_offset = await handle_update(cfg, notifier, update)
                if new_offset is not None:
                    offset = new_offset
                    _save_offset(cfg, offset)
            if once:
                break
            if not updates:
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("telegram bot stopped")
        raise
    finally:
        await notifier.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis read-only Telegram command bot")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--once", action="store_true", help="process one poll batch then exit")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    asyncio.run(run_bot(cfg, once=args.once))


if __name__ == "__main__":
    main()
