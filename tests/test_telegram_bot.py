"""Telegram command bot tests."""

import asyncio
import json
from dataclasses import replace

import httpx

from aegis.config import load_config
from aegis.data import db
from aegis.monitor.telegram import TelegramNotifier
from aegis.monitor.telegram_bot import (
    HELP_TEXT,
    build_paper_report,
    build_scanner_report,
    dispatch_command,
    handle_update,
    parse_command,
)


def _cfg(**kwargs):
    return replace(load_config(env_file=None), **kwargs)


def test_parse_command_strips_bot_suffix():
    assert parse_command("/status@AegisBot") == "status"
    assert parse_command("/help") == "help"
    assert parse_command("hello") is None


def test_dispatch_help():
    text, markup = asyncio.run(dispatch_command(_cfg(), "help"))
    assert "read-only" in text
    assert "/progress" in text
    assert markup is not None


def test_dispatch_progress(tmp_path):
    cfg = _cfg(sqlite_path=str(tmp_path / "t.sqlite"))
    db.connect(tmp_path / "t.sqlite").close()
    text, markup = asyncio.run(dispatch_command(cfg, "progress"))
    assert "Aegis progression" in text
    assert "M4" in text
    assert markup is None


def test_build_paper_report(tmp_path):
    cfg = _cfg(sqlite_path=str(tmp_path / "t.sqlite"), mode="paper")
    db.connect(tmp_path / "t.sqlite").close()
    report = build_paper_report(cfg)
    assert "TODAY'S MONEY" in report
    assert "Equity now:" in report
    assert "Config freeze" in report


def test_build_scanner_report(tmp_path):
    cfg = _cfg(sqlite_path=str(tmp_path / "t.sqlite"))
    conn = db.connect(tmp_path / "t.sqlite")
    now = int(__import__("time").time() * 1000)
    db.insert_market_snapshots(
        conn,
        now - 1000,
        [
            {
                "coin_id": "btc",
                "symbol": "BTC",
                "price_usd": 1.0,
                "vol24h_usd": 1.0,
                "market_cap_usd": 1.0,
                "price_change_1h_pct": 0.0,
                "price_change_24h_pct": 0.0,
            }
        ],
    )
    conn.close()
    report = build_scanner_report(cfg)
    assert "Snapshots (24h): 1" in report


def test_handle_update_ignores_unauthorized_chat():
    cfg = _cfg()
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier("TOKEN", "12345", client=client)
    update = {
        "update_id": 9,
        "message": {"chat": {"id": 99999}, "text": "/status"},
    }
    offset = asyncio.run(handle_update(cfg, notifier, update))
    assert offset == 10
    assert "sendMessage" not in captured.get("url", "")


def test_handle_update_runs_status_for_authorized_chat(tmp_path):
    cfg = _cfg(
        sqlite_path=str(tmp_path / "t.sqlite"),
        secrets=replace(load_config(env_file=None).secrets, telegram_chat_id="12345"),
    )
    db.connect(tmp_path / "t.sqlite").close()
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier("TOKEN", "12345", client=client)
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 12345}, "text": "/help"},
    }
    offset = asyncio.run(handle_update(cfg, notifier, update))
    assert offset == 2
    assert sent[0]["text"] == HELP_TEXT
