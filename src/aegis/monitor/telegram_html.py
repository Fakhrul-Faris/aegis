"""HTML helpers for Telegram messages (parse_mode=HTML)."""

from __future__ import annotations

import html


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


def bold(text: str) -> str:
    return f"<b>{esc(text)}</b>"


def italic(text: str) -> str:
    return f"<i>{esc(text)}</i>"


def code(text: str) -> str:
    return f"<code>{esc(text)}</code>"


def pre_block(text: str) -> str:
    return f"<pre>{esc(text)}</pre>"


def pnl_emoji(amount: float) -> str:
    if amount > 0:
        return "🟢"
    if amount < 0:
        return "🔴"
    return "⚪"


def status_emoji(ok: bool) -> str:
    return "✅" if ok else "⚠️"


def format_pnl_html(amount: float) -> str:
    if amount > 0:
        return f"+${amount:,.2f}"
    if amount < 0:
        return f"-${abs(amount):,.2f}"
    return "$0.00"
