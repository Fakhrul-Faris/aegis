"""Historical kline downloader for backtest research (P1.6).

Hyperliquid serves ~5,000 candles per series (~208 days of 1h) and Kraken's
OHLC endpoint only 720 rows - neither covers a multi-year walk-forward.
Binance's public data archive (data.binance.vision) provides complete USDT-
perp kline history as monthly CSV zips, no API key, no rate-limit drama.

Symbols are stored under their BASE name (BTCUSDT -> BTC) with
venue='binance', so research panels line up with Hyperliquid coin naming.
This venue exists for research only; nothing here can trade.

Usage:
    aegis-download --db data/research.sqlite --start 2021-01
    aegis-download --db data/research.sqlite --symbols BTC ETH SOL --start 2020-01
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import zipfile
from datetime import UTC, datetime

import httpx

from aegis.core.models import Candle, Venue
from aegis.data import db
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

ARCHIVE_URL = (
    "https://data.binance.vision/data/futures/um/monthly/klines/"
    "{pair}/{timeframe}/{pair}-{timeframe}-{year}-{month:02d}.zip"
)

# Liquid USDT perps with multi-year history, overlapping Hyperliquid's universe.
DEFAULT_BASES = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "DOGE",
    "ADA",
    "AVAX",
    "LINK",
    "DOT",
    "LTC",
    "BCH",
    "UNI",
    "ATOM",
    "NEAR",
    "FIL",
    "ETC",
    "INJ",
    "APT",
    "ARB",
    "OP",
    "SUI",
    "TIA",
    "SEI",
    "AAVE",
    "CRV",
    "SAND",
    "GALA",
    "EOS",
    "XLM",
]


def parse_kline_csv(content: bytes, base: str, timeframe: str) -> list[Candle]:
    """Parse a Binance kline CSV (header optional, open time in ms or us)."""
    candles = []
    for row in csv.reader(io.StringIO(content.decode())):
        if not row or not row[0].isdigit():
            continue  # header line
        open_time = int(row[0])
        if open_time > 10**14:  # microseconds (newer archives) -> ms
            open_time //= 1000
        candles.append(
            Candle(
                venue=Venue.BINANCE,
                symbol=base,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(open_time / 1000, tz=UTC),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        )
    return candles


def month_range(start: str, end: str | None = None) -> list[tuple[int, int]]:
    """Inclusive (year, month) range; end defaults to LAST month (archives lag)."""
    year, month = (int(p) for p in start.split("-"))
    now = datetime.now(tz=UTC)
    if end is not None:
        end_year, end_month = (int(p) for p in end.split("-"))
    else:
        end_year, end_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    months = []
    while (year, month) <= (end_year, end_month):
        months.append((year, month))
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    return months


def download_history(
    db_path: str,
    bases: list[str],
    timeframe: str,
    start: str,
    end: str | None = None,
) -> int:
    conn = db.connect(db_path)
    total = 0
    try:
        with httpx.Client(timeout=60.0) as client:
            for base in bases:
                pair = f"{base}USDT"
                inserted = 0
                for year, month in month_range(start, end):
                    url = ARCHIVE_URL.format(pair=pair, timeframe=timeframe, year=year, month=month)
                    response = client.get(url)
                    if response.status_code == 404:
                        continue  # symbol not listed yet that month
                    response.raise_for_status()
                    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                        content = archive.read(archive.namelist()[0])
                    candles = parse_kline_csv(content, base, timeframe)
                    inserted += db.upsert_candles(conn, candles)
                logger.info(
                    "history downloaded",
                    extra={"symbol": base, "timeframe": timeframe, "inserted": inserted},
                )
                total += inserted
    finally:
        conn.close()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Binance kline history for research")
    parser.add_argument("--db", required=True, help="research SQLite path")
    parser.add_argument("--symbols", nargs="*", default=None, help="base symbols (default: 30)")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--start", default="2021-01", help="YYYY-MM")
    parser.add_argument("--end", default=None, help="YYYY-MM (default: last full month)")
    args = parser.parse_args()

    setup_logging()
    bases = args.symbols or DEFAULT_BASES
    total = download_history(args.db, bases, args.timeframe, args.start, args.end)
    print(f"inserted {total} candles for {len(bases)} symbols into {args.db}")


if __name__ == "__main__":
    main()
