"""HistData.com zip import for deep 1h FX history (FX research fork).

Automated download from HistData is often blocked (empty responses). Place
monthly zips manually under::

    data/histdata/{PAIR}/HISTDATA_COM_ASCII_{PAIR}_H1_{YYYY}{MM}.zip

This module parses those zips and upserts into the research SQLite DB.
"""

from __future__ import annotations

import logging
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from aegis.core.models import Candle, Venue
from aegis.data import db
from aegis.data.forex_download import upsert_candles_to_db

logger = logging.getLogger(__name__)

HISTDATA_DIR = Path("data/histdata")
HISTDATA_URL = "https://www.histdata.com/get.php?file=ascii/1-hour-bar-quotes/{sym}/{year}/{month}"
HISTDATA_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.histdata.com/download-free-forex-historical-data/",
}

# HistData ASCII: 20240101 000000,open,high,low,close,volume
_LINE_RE = re.compile(
    r"^(\d{8})\s+(\d{6}),([0-9.]+),([0-9.]+),([0-9.]+),([0-9.]+),([0-9.]+)$"
)


def parse_histdata_zip(content: bytes, pair: str) -> list[Candle]:
    candles: list[Candle] = []
    with zipfile.ZipFile(__import__("io").BytesIO(content)) as archive:
        name = archive.namelist()[0]
        text = archive.read(name).decode("utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        ymd, hms, o, h, l, c, vol = m.groups()
        dt = datetime.strptime(f"{ymd}{hms}", "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        candles.append(
            Candle(
                venue=Venue.FOREX,
                symbol=pair.upper(),
                timeframe="1h",
                open_time=dt,
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=float(vol),
            )
        )
    return candles


def import_histdata_zip(path: Path, pair: str, db_path: str) -> int:
    candles = parse_histdata_zip(path.read_bytes(), pair)
    return upsert_candles_to_db(db_path, candles)


def import_histdata_directory(
    db_path: str,
    pair: str,
    directory: Path | None = None,
) -> int:
    """Import all HistData zips for a pair found under ``data/histdata/{PAIR}/``."""
    pair = pair.upper()
    root = directory or (HISTDATA_DIR / pair)
    if not root.exists():
        return 0
    total = 0
    for path in sorted(root.glob("*.zip")):
        try:
            n = import_histdata_zip(path, pair, db_path)
            total += n
            logger.info("histdata imported", extra={"file": str(path), "inserted": n})
        except Exception as exc:
            logger.warning("histdata import failed", extra={"file": str(path), "error": repr(exc)})
    return total


def try_download_histdata_month(sym: str, year: int, month: int) -> bytes | None:
    """Best-effort single-month download; returns None when blocked."""
    url = HISTDATA_URL.format(sym=sym.lower(), year=year, month=month)
    try:
        with httpx.Client(headers=HISTDATA_HEADERS, timeout=60, follow_redirects=True) as client:
            client.get("https://www.histdata.com/download-free-forex-historical-data/")
            response = client.get(url)
            if response.status_code == 200 and len(response.content) > 200:
                return response.content
    except httpx.HTTPError:
        return None
    return None


def try_download_histdata_range(
    db_path: str,
    pair: str,
    year_start: int,
    year_end: int,
) -> int:
    """Attempt automated HistData pulls; usually requires manual zips."""
    sym = pair.lower()
    total = 0
    for year in range(year_start, year_end + 1):
        for month in range(1, 13):
            content = try_download_histdata_month(sym, year, month)
            if not content:
                continue
            try:
                candles = parse_histdata_zip(content, pair)
                total += upsert_candles_to_db(db_path, candles)
            except Exception:
                continue
    return total
