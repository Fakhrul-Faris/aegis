"""Join volume-anomaly scanner flags to Strategy A signals (P1.7 / P3.1)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aegis.core.timeframes import timeframe_ms


@dataclass(frozen=True)
class ScannerAnomaly:
    """Most recent scanner flag overlapping a signal bar window."""

    ts_ms: int
    coin_id: str
    symbol: str
    volume_multiple: float
    variant: str
    on_kraken: bool
    context: dict


def scanner_flags_in_window(
    conn: sqlite3.Connection,
    symbol_base: str,
    bar_open_ms: int,
    bar_timeframe: str,
) -> list[ScannerAnomaly]:
    """Return flags for ``symbol_base`` whose ts falls in [bar_open, bar_close)."""
    end_ms = bar_open_ms + timeframe_ms(bar_timeframe)
    rows = conn.execute(
        """
        SELECT ts_ms, coin_id, symbol, volume_multiple, variant, on_kraken, context_json
        FROM scanner_flags
        WHERE UPPER(symbol) = UPPER(?)
          AND ts_ms >= ? AND ts_ms < ?
        ORDER BY ts_ms DESC
        """,
        (symbol_base, bar_open_ms, end_ms),
    ).fetchall()
    out: list[ScannerAnomaly] = []
    for row in rows:
        ctx = json.loads(row[6]) if row[6] else {}
        out.append(
            ScannerAnomaly(
                ts_ms=row[0],
                coin_id=row[1],
                symbol=row[2],
                volume_multiple=row[3],
                variant=row[4],
                on_kraken=bool(row[5]),
                context=ctx,
            )
        )
    return out


def has_anomaly_in_window(
    conn: sqlite3.Connection,
    symbol_base: str,
    bar_open_ms: int,
    bar_timeframe: str,
) -> bool:
    return bool(scanner_flags_in_window(conn, symbol_base, bar_open_ms, bar_timeframe))


def latest_anomaly_in_window(
    conn: sqlite3.Connection,
    symbol_base: str,
    bar_open_ms: int,
    bar_timeframe: str,
) -> ScannerAnomaly | None:
    flags = scanner_flags_in_window(conn, symbol_base, bar_open_ms, bar_timeframe)
    return flags[0] if flags else None
