"""Timeframe utilities shared by data, strategy, and execution layers."""

from __future__ import annotations

TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def timeframe_ms(timeframe: str) -> int:
    try:
        return TIMEFRAME_MS[timeframe]
    except KeyError:
        raise ValueError(
            f"Unknown timeframe {timeframe!r}; known: {sorted(TIMEFRAME_MS)}"
        ) from None
