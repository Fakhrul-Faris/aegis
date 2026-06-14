"""Load OHLC panels for forex SCM backtests."""

from __future__ import annotations

import sqlite3

import pandas as pd


def load_ohlc(
    db_path: str,
    symbol: str,
    timeframe: str = "1h",
    venue: str = "forex",
) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT open_time_ms, open, high, low, close, volume
            FROM candles
            WHERE venue = ? AND symbol = ? AND timeframe = ?
            ORDER BY open_time_ms ASC
            """,
            conn,
            params=(venue, symbol, timeframe),
        )
    finally:
        conn.close()
    if df.empty:
        return df
    df["open_time"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)
    return df.set_index("open_time").drop(columns=["open_time_ms"])


def slice_ohlc(
    ohlc: pd.DataFrame,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    out = ohlc
    if start:
        out = out.loc[out.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        out = out.loc[out.index <= pd.Timestamp(end, tz="UTC")]
    return out
