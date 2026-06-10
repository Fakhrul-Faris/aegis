"""Telegram notifier tests (P0.5) - transport mocked, no network."""

import asyncio
import json

import httpx

from aegis.monitor.telegram import TelegramNotifier


def test_disabled_without_credentials():
    notifier = TelegramNotifier(None, None)
    assert notifier.enabled is False
    assert asyncio.run(notifier.send("hello")) is False


def test_send_posts_to_bot_api():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier("TOKEN", "CHAT", client=client)

    assert asyncio.run(notifier.send("circuit breaker tripped")) is True
    assert "botTOKEN/sendMessage" in captured["url"]
    assert captured["body"] == {"chat_id": "CHAT", "text": "circuit breaker tripped"}


def test_send_never_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier("TOKEN", "CHAT", client=client)
    assert asyncio.run(notifier.send("boom")) is False
