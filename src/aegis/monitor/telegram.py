"""Telegram notifications (P0.5).

Disabled gracefully when credentials are missing (e.g. tests, CI): messages
are logged instead of sent, and nothing crashes. Monitoring must never be
the thing that takes the system down.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from aegis.config import AegisConfig

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        client: httpx.AsyncClient | None = None,
    ):
        self.enabled = bool(bot_token and chat_id)
        self._token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=30.0)

    def _api_url(self, method: str) -> str:
        return f"{TELEGRAM_API}/bot{self._token}/{method}"

    async def close(self) -> None:
        await self._client.aclose()

    async def send(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> bool:
        """Send a message. Returns True on confirmed delivery; never raises."""
        if not self.enabled:
            logger.info("telegram disabled; message not sent", extra={"text": text})
            return False
        payload: dict[str, Any] = {
            "chat_id": chat_id or self._chat_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            response = await self._client.post(self._api_url("sendMessage"), json=payload)
            response.raise_for_status()
            return bool(response.json().get("ok"))
        except Exception:
            logger.exception("telegram send failed")
            return False

    async def set_commands(self, commands: list[dict[str, str]]) -> bool:
        if not self.enabled:
            return False
        try:
            response = await self._client.post(
                self._api_url("setMyCommands"),
                json={"commands": commands},
            )
            response.raise_for_status()
            return bool(response.json().get("ok"))
        except Exception:
            logger.exception("telegram setMyCommands failed")
            return False

    async def get_updates(self, *, offset: int | None = None, timeout: int = 25) -> list[dict]:
        if not self.enabled:
            return []
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        try:
            response = await self._client.get(self._api_url("getUpdates"), params=params)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                return []
            return list(body.get("result") or [])
        except Exception:
            logger.exception("telegram getUpdates failed")
            return []

    async def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        if not self.enabled:
            return
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            await self._client.post(self._api_url("answerCallbackQuery"), json=payload)
        except Exception:
            logger.exception("telegram answerCallbackQuery failed")


def notifier_from_config(cfg: AegisConfig) -> TelegramNotifier:
    if not cfg.monitoring.telegram_enabled:
        return TelegramNotifier(None, None)
    return TelegramNotifier(cfg.secrets.telegram_bot_token, cfg.secrets.telegram_chat_id)


async def notify_crash(cfg: AegisConfig, component: str, exc: Exception) -> None:
    notifier = notifier_from_config(cfg)
    try:
        await notifier.send(f"CRITICAL - aegis {component} crashed: {exc!r}")
    finally:
        await notifier.close()
