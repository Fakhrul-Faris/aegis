"""Situation summariser — compress context before decision (FX-R3)."""

from __future__ import annotations

from typing import Any


def build_situation_summary(
    *,
    pair: str,
    direction: str,
    event_code: str | None,
    stop: float | None,
    target: float | None,
    equity_usd: float,
    open_positions: int,
    ingest_ok: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "pair": pair,
        "direction": direction,
        "event_code": event_code,
        "stop": stop,
        "target": target,
        "equity_usd": round(equity_usd, 2),
        "open_positions": open_positions,
    }
    if ingest_ok is not None:
        base["ingest_ok"] = ingest_ok
    if extra:
        base.update(extra)
    return base
