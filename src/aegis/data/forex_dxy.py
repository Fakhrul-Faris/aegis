"""Synthetic DXY series from stored forex candles (FX0).

Computes ICE USD Index from configured pair weights and stores as
``symbol=DXY`` under ``venue=forex``. USDSEK omitted — weights used as-is
from config (FX2 may refine).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aegis.config_forex import DxyConfig, ForexConfig, load_forex_config
from aegis.core.models import Candle, Venue
from aegis.data import db

logger = logging.getLogger(__name__)


def _load_closes(
    conn,
    pair: str,
    timeframe: str,
) -> dict[int, float]:
    rows = conn.execute(
        """
        SELECT open_time_ms, close FROM candles
        WHERE venue = ? AND symbol = ? AND timeframe = ?
        ORDER BY open_time_ms ASC
        """,
        (Venue.FOREX.value, pair, timeframe),
    ).fetchall()
    return {int(r[0]): float(r[1]) for r in rows}


def compute_dxy_level(weights: DxyConfig, prices: dict[str, float]) -> float | None:
    """ICE geometric USD index from pair levels (not returns)."""
    if not all(p in prices and prices[p] > 0 for p in weights.weights):
        return None
    product = weights.constant
    for pair, exponent in weights.weights.items():
        product *= prices[pair] ** exponent
    return product


def build_dxy_candles(
    conn,
    cfg: ForexConfig,
    timeframe: str = "1h",
) -> list[Candle]:
    series: dict[str, dict[int, float]] = {}
    for pair in cfg.dxy.weights:
        series[pair] = _load_closes(conn, pair, timeframe)
    if not series:
        return []

    # Align on timestamps present in all legs.
    common_ts = None
    for closes in series.values():
        keys = set(closes)
        common_ts = keys if common_ts is None else common_ts & keys
    if not common_ts:
        return []

    candles: list[Candle] = []
    prev_level: float | None = None
    for ts_ms in sorted(common_ts):
        prices = {pair: series[pair][ts_ms] for pair in cfg.dxy.weights}
        level = compute_dxy_level(cfg.dxy, prices)
        if level is None:
            continue
        if prev_level is None:
            o = level
        else:
            o = prev_level
        h = max(o, level)
        l = min(o, level)
        c = level
        prev_level = level
        candles.append(
            Candle(
                venue=Venue.FOREX,
                symbol=cfg.dxy.symbol,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
                open=o,
                high=h,
                low=l,
                close=c,
                volume=0.0,
            )
        )
    return candles


def upsert_dxy(conn, cfg: ForexConfig, timeframe: str = "1h") -> int:
    candles = build_dxy_candles(conn, cfg, timeframe=timeframe)
    if not candles:
        return 0
    n = db.upsert_candles(conn, candles)
    logger.info(
        "dxy synthetic series upserted",
        extra={"timeframe": timeframe, "bars": len(candles), "inserted": n},
    )
    return n


def upsert_dxy_all_timeframes(cfg: ForexConfig) -> int:
    conn = db.connect(cfg.research.sqlite_path)
    try:
        total = 0
        for tf in cfg.research.timeframes:
            total += upsert_dxy(conn, cfg, timeframe=tf)
        return total
    finally:
        conn.close()
