"""Historical FX data for SCM research (FX0).

Sources (in priority order):
1. **Yahoo Finance** (``yfinance``) — 1h bars for the last ~730 days; daily back to 2000.
2. **HistData CSV import** — 1h/M1 history beyond Yahoo's hourly cap (manual download).
3. **Dukascopy** (optional fallback) — public datafeed; often 404 from some networks.

Stored under ``venue='forex'``.

Usage:
    aegis-forex-download --pair EURUSD --yahoo
    aegis-forex-download --all-pairs --yahoo
    aegis-forex-download --import-csv data/histdata/EURUSD_H1.csv --pair EURUSD
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import struct
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import lzma
import pandas as pd
import yfinance as yf

from aegis.config_forex import ForexConfig, load_forex_config
from aegis.core.models import Candle, Venue
from aegis.data import db
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

YAHOO_SYMBOL = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "USDCHF": "USDCHF=X",
}

DUKASCOPY_URL = (
    "https://datafeed.dukascopy.com/datafeed/{pair}/{year}/{month}/{day}/"
    "{hour}h_ticks.bi5"
)
DUKASCOPY_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.dukascopy.com/",
}
HOUR_MS = 3_600_000
POINT = 0.00001  # EURUSD tick point for Dukascopy ticks


# --- Yahoo -----------------------------------------------------------------


def _df_to_candles(df: pd.DataFrame, pair: str, timeframe: str) -> list[Candle]:
    if df.empty:
        return []
    # yfinance may return MultiIndex columns.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() if isinstance(c, tuple) else c for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]

    candles: list[Candle] = []
    for ts, row in df.iterrows():
        dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        candles.append(
            Candle(
                venue=Venue.FOREX,
                symbol=pair,
                timeframe=timeframe,
                open_time=dt,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0) or 0.0),
            )
        )
    return candles


def download_yahoo_hourly(pair: str, *, period: str = "730d") -> list[Candle]:
    ticker = YAHOO_SYMBOL.get(pair, f"{pair}=X")
    df = yf.download(ticker, interval="1h", period=period, progress=False, auto_adjust=False)
    return _df_to_candles(df, pair, "1h")


def download_yahoo_daily(pair: str, *, start: str = "2015-01-01") -> list[Candle]:
    ticker = YAHOO_SYMBOL.get(pair, f"{pair}=X")
    df = yf.download(
        ticker, interval="1d", start=start, progress=False, auto_adjust=False
    )
    return _df_to_candles(df, pair, "1d")


def upsert_candles_to_db(db_path: str, candles: list[Candle]) -> int:
    if not candles:
        return 0
    conn = db.connect(db_path)
    try:
        return db.upsert_candles(conn, candles)
    finally:
        conn.close()


# --- HistData CSV import ---------------------------------------------------


_HISTDATA_RE = re.compile(
    r"^(\d{4})[.\-/](\d{2})[.\-/](\d{2})[ ,](\d{2}):(\d{2})"
)


def parse_histdata_csv(path: Path, pair: str, timeframe: str = "1h") -> list[Candle]:
    """Parse HistData / MT4 / ForexSB CSV: Date,Time,O,H,L,C,V or compact datetime."""
    candles: list[Candle] = []
    with path.open(newline="") as fh:
        sample = fh.readline()
        if not sample:
            return []
        delimiter = "\t" if "\t" in sample else ","
        fh.seek(0)
        reader = csv.reader(fh, delimiter=delimiter)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if row[0].lower() in ("date", "datetime", "timestamp"):
                continue
            try:
                if len(row) >= 7:
                    dt = datetime.strptime(f"{row[0]} {row[1]}", "%Y.%m.%d %H:%M").replace(
                        tzinfo=UTC
                    )
                    o, h, l, c, vol = map(float, row[2:7])
                elif len(row) >= 6:
                    m = _HISTDATA_RE.match(row[0])
                    if m:
                        y, mo, d, hh, mm = map(int, m.groups())
                        dt = datetime(y, mo, d, hh, mm, tzinfo=UTC)
                        o, h, l, c, vol = map(float, row[1:6])
                    else:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                            try:
                                dt = datetime.strptime(row[0], fmt).replace(tzinfo=UTC)
                                break
                            except ValueError:
                                dt = None
                        if dt is None:
                            continue
                        o, h, l, c, vol = map(float, row[1:6])
                else:
                    continue
            except (ValueError, IndexError):
                continue
            candles.append(
                Candle(
                    venue=Venue.FOREX,
                    symbol=pair,
                    timeframe=timeframe,
                    open_time=dt,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=vol,
                )
            )
    return candles


def import_histdata_csv(db_path: str, csv_path: Path, pair: str, timeframe: str = "1h") -> int:
    candles = parse_histdata_csv(csv_path, pair, timeframe=timeframe)
    return upsert_candles_to_db(db_path, candles)


# --- Dukascopy ticks (optional; aggregate to 1h) ---------------------------


def parse_bi5_ticks(raw: bytes, hour_start_ms: int, point: float = POINT) -> list[tuple[int, float]]:
    if not raw:
        return []
    try:
        data = lzma.decompress(raw)
    except lzma.LZMAError:
        return []
    out: list[tuple[int, float]] = []
    stride = 20
    for offset in range(0, len(data) - stride + 1, stride):
        chunk = data[offset : offset + stride]
        t_off_ms, ask_i, bid_i, _ask_vol, _bid_vol = struct.unpack(">IIIff", chunk)
        mid = ((ask_i + bid_i) / 2.0) * point
        out.append((hour_start_ms + int(t_off_ms), mid))
    return out


def fetch_dukascopy_hour_ticks(
    client: httpx.Client, pair: str, dt: datetime, *, point: float = POINT
) -> list[tuple[int, float]]:
    url = DUKASCOPY_URL.format(
        pair=pair,
        year=dt.year,
        month=dt.month - 1,
        day=dt.day - 1,
        hour=dt.hour,
    )
    hour_start_ms = int(dt.replace(minute=0, second=0, microsecond=0).timestamp() * 1000)
    try:
        response = client.get(url)
        if response.status_code != 200 or not response.content:
            return []
    except httpx.HTTPError:
        return []
    return parse_bi5_ticks(response.content, hour_start_ms, point=point)


def ticks_to_hourly_candle(ticks: list[tuple[int, float]], pair: str, hour_start_ms: int) -> Candle | None:
    if not ticks:
        return None
    prices = [p for _, p in sorted(ticks)]
    return Candle(
        venue=Venue.FOREX,
        symbol=pair,
        timeframe="1h",
        open_time=datetime.fromtimestamp(hour_start_ms / 1000, tz=UTC),
        open=prices[0],
        high=max(prices),
        low=min(prices),
        close=prices[-1],
        volume=float(len(prices)),
    )


def download_dukascopy_range(
    db_path: str,
    pair: str,
    start: datetime,
    end: datetime,
    *,
    pause_sec: float = 0.02,
) -> int:
    conn = db.connect(db_path)
    inserted = 0
    batch: list[Candle] = []
    try:
        with httpx.Client(timeout=30.0, headers=DUKASCOPY_HEADERS) as client:
            cursor = start.replace(minute=0, second=0, microsecond=0)
            end = end.replace(minute=0, second=0, microsecond=0)
            while cursor <= end:
                hour_ms = int(cursor.timestamp() * 1000)
                ticks = fetch_dukascopy_hour_ticks(client, pair, cursor)
                candle = ticks_to_hourly_candle(ticks, pair, hour_ms)
                if candle:
                    batch.append(candle)
                if len(batch) >= 200:
                    inserted += db.upsert_candles(conn, batch)
                    batch.clear()
                cursor += timedelta(hours=1)
                if pause_sec:
                    time.sleep(pause_sec)
            if batch:
                inserted += db.upsert_candles(conn, batch)
    finally:
        conn.close()
    return inserted


# --- 4h aggregate ----------------------------------------------------------


def aggregate_4h_from_1h(db_path: str, pairs: list[str]) -> int:
    conn = db.connect(db_path)
    total = 0
    try:
        for pair in pairs:
            rows = conn.execute(
                """
                SELECT open_time_ms, open, high, low, close, volume
                FROM candles
                WHERE venue = ? AND symbol = ? AND timeframe = '1h'
                ORDER BY open_time_ms ASC
                """,
                (Venue.FOREX.value, pair),
            ).fetchall()
            if not rows:
                continue
            bucket: list = []
            bucket_start: int | None = None
            candles_4h: list[Candle] = []
            for open_ms, o, h, l, c, vol in rows:
                aligned = open_ms - (open_ms % (4 * HOUR_MS))
                if bucket_start is None:
                    bucket_start = aligned
                if aligned != bucket_start:
                    if bucket:
                        candles_4h.append(_make_4h_bar(pair, bucket_start, bucket))
                    bucket = [(open_ms, o, h, l, c, vol)]
                    bucket_start = aligned
                else:
                    bucket.append((open_ms, o, h, l, c, vol))
            if bucket and bucket_start is not None:
                candles_4h.append(_make_4h_bar(pair, bucket_start, bucket))
            total += db.upsert_candles(conn, candles_4h)
    finally:
        conn.close()
    return total


def _make_4h_bar(pair: str, bucket_start: int, bucket: list) -> Candle:
    o = bucket[0][1]
    h = max(row[2] for row in bucket)
    l = min(row[3] for row in bucket)
    c = bucket[-1][4]
    vol = sum(row[5] for row in bucket)
    return Candle(
        venue=Venue.FOREX,
        symbol=pair,
        timeframe="4h",
        open_time=datetime.fromtimestamp(bucket_start / 1000, tz=UTC),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=vol,
    )


def download_yahoo_all(cfg: ForexConfig, pairs: list[str] | None = None) -> int:
    all_pairs = list(pairs or cfg.pairs) + list(cfg.dxy_pairs)
    total = 0
    for pair in all_pairs:
        hourly = download_yahoo_hourly(pair)
        daily = download_yahoo_daily(pair, start=cfg.research.download_start + "-01")
        total += upsert_candles_to_db(cfg.research.sqlite_path, hourly)
        total += upsert_candles_to_db(cfg.research.sqlite_path, daily)
        logger.info(
            "yahoo forex downloaded",
            extra={"pair": pair, "hourly": len(hourly), "daily": len(daily)},
        )
    agg = aggregate_4h_from_1h(cfg.research.sqlite_path, all_pairs)
    logger.info("forex 4h aggregate complete", extra={"inserted": agg})
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Download / import FX history for research")
    parser.add_argument("--config", default="config/forex.yaml")
    parser.add_argument("--pair", default=None)
    parser.add_argument("--all-pairs", action="store_true")
    parser.add_argument("--yahoo", action="store_true", help="Yahoo Finance (default path)")
    parser.add_argument("--import-csv", type=Path, default=None, help="HistData CSV path")
    args = parser.parse_args()

    cfg = load_forex_config(args.config)
    setup_logging("logs", "INFO")

    pairs = None
    if args.all_pairs:
        pairs = list(cfg.pairs) + list(cfg.dxy_pairs)
    elif args.pair:
        pairs = [args.pair.upper()]

    if args.import_csv:
        if not args.pair:
            parser.error("--import-csv requires --pair")
        n = import_histdata_csv(cfg.research.sqlite_path, args.import_csv, args.pair.upper())
        aggregate_4h_from_1h(cfg.research.sqlite_path, [args.pair.upper()])
        print(f"imported {n} 1h candles from {args.import_csv}")
        return

    if not pairs:
        parser.error("specify --pair or --all-pairs")

    total = download_yahoo_all(cfg, pairs=pairs)
    print(f"upserted {total} candles into {cfg.research.sqlite_path}")


if __name__ == "__main__":
    main()
