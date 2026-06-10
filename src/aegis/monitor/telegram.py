"""Telegram notifications (P0.5).

Disabled gracefully when credentials are missing (e.g. tests, CI): messages
are logged instead of sent, and nothing crashes. Monitoring must never be
the thing that takes the system down.
"""

from __future__ import annotations

import logging

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
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def send(self, text: str) -> bool:
        """Send a message. Returns True on confirmed delivery; never raises."""
        if not self.enabled:
            logger.info("telegram disabled; message not sent", extra={"text": text})
            return False
        try:
            response = await self._client.post(
                f"{TELEGRAM_API}/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
            )
            response.raise_for_status()
            return bool(response.json().get("ok"))
        except Exception:
            logger.exception("telegram send failed")
            return False


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
