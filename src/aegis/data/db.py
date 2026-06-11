"""SQLite persistence layer (P0.3).

One database file holds everything the system ever learns: candles, scanner
flags, signals (taken AND skipped), orders, fills, positions, funding,
slippage measurements, equity snapshots, and regime labels. The dataset is
the asset (Concept §11) - schemas exist from day one even though most tables
fill up in later phases.

All timestamps are integer epoch milliseconds, UTC.
"""

from __future__ import annotations

import itertools
import sqlite3
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from aegis.core.models import Candle, Venue

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS candles (
        venue        TEXT    NOT NULL,
        symbol       TEXT    NOT NULL,
        timeframe    TEXT    NOT NULL,
        open_time_ms INTEGER NOT NULL,
        open         REAL    NOT NULL,
        high         REAL    NOT NULL,
        low          REAL    NOT NULL,
        close        REAL    NOT NULL,
        volume       REAL    NOT NULL,
        inserted_ms  INTEGER NOT NULL,
        PRIMARY KEY (venue, symbol, timeframe, open_time_ms)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scanner_flags (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms                INTEGER NOT NULL,
        coin_id              TEXT    NOT NULL,
        symbol               TEXT,
        vol_1h_usd           REAL,
        vol_avg_1h_usd       REAL,
        volume_multiple      REAL,
        price_change_1h_pct  REAL,
        price_change_24h_pct REAL,
        variant              TEXT,
        on_kraken            INTEGER,
        context_json         TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms        INTEGER NOT NULL,
        strategy     TEXT    NOT NULL,
        venue        TEXT    NOT NULL,
        symbol       TEXT    NOT NULL,
        direction    TEXT    NOT NULL,
        tier         TEXT,
        z_score      REAL,
        taken        INTEGER NOT NULL,
        skip_reason  TEXT,
        context_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        client_order_id  TEXT UNIQUE,
        venue_order_id   TEXT,
        ts_ms            INTEGER NOT NULL,
        venue            TEXT    NOT NULL,
        symbol           TEXT    NOT NULL,
        side             TEXT    NOT NULL,
        order_type       TEXT    NOT NULL,
        quantity         REAL    NOT NULL,
        price            REAL,
        reduce_only      INTEGER NOT NULL DEFAULT 0,
        status           TEXT    NOT NULL,
        context_json     TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fills (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms           INTEGER NOT NULL,
        venue           TEXT    NOT NULL,
        symbol          TEXT    NOT NULL,
        venue_order_id  TEXT,
        client_order_id TEXT,
        side            TEXT    NOT NULL,
        quantity        REAL    NOT NULL,
        price           REAL    NOT NULL,
        fee             REAL    NOT NULL,
        is_maker        INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        opened_ts_ms    INTEGER NOT NULL,
        closed_ts_ms    INTEGER,
        strategy        TEXT    NOT NULL,
        venue           TEXT    NOT NULL,
        symbol          TEXT    NOT NULL,
        side            TEXT    NOT NULL,
        quantity        REAL    NOT NULL,
        entry_price     REAL    NOT NULL,
        exit_price      REAL,
        realized_pnl    REAL,
        risk_amount_usd REAL,
        r_multiple      REAL,
        pair_id         TEXT,
        context_json    TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS funding_payments (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms     INTEGER NOT NULL,
        venue     TEXT    NOT NULL,
        symbol    TEXT    NOT NULL,
        amount_usd REAL   NOT NULL,
        rate      REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slippage_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms          INTEGER NOT NULL,
        venue          TEXT    NOT NULL,
        symbol         TEXT    NOT NULL,
        side           TEXT    NOT NULL,
        expected_price REAL    NOT NULL,
        fill_price     REAL,
        slippage_pct   REAL,
        gate_triggered INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS equity_snapshots (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms     INTEGER NOT NULL,
        venue     TEXT    NOT NULL,
        equity_usd REAL   NOT NULL,
        mode      TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS regime_labels (
        venue        TEXT    NOT NULL,
        symbol       TEXT    NOT NULL,
        timeframe    TEXT    NOT NULL,
        open_time_ms INTEGER NOT NULL,
        regime       TEXT    NOT NULL,
        adx          REAL,
        ema_fast     REAL,
        ema_slow     REAL,
        bb_width     REAL,
        PRIMARY KEY (venue, symbol, timeframe, open_time_ms)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_snapshots (
        ts_ms                INTEGER NOT NULL,
        coin_id              TEXT    NOT NULL,
        symbol               TEXT,
        price_usd            REAL,
        vol24h_usd           REAL,
        market_cap_usd       REAL,
        price_change_1h_pct  REAL,
        price_change_24h_pct REAL,
        PRIMARY KEY (ts_ms, coin_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_snapshots_coin ON market_snapshots (coin_id, ts_ms)",
    "CREATE INDEX IF NOT EXISTS idx_scanner_flags_ts ON scanner_flags (ts_ms)",
    "CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals (ts_ms)",
    "CREATE INDEX IF NOT EXISTS idx_fills_ts ON fills (ts_ms)",
    "CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_snapshots (ts_ms)",
)


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the database with WAL mode and schema applied."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()
    return conn


# --- Candle repository -----------------------------------------------------


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def upsert_candles(conn: sqlite3.Connection, candles: Iterable[Candle]) -> int:
    """Insert candles, replacing on conflict. Returns number of NEW rows."""
    now_ms = int(time.time() * 1000)
    before = candle_count_total(conn)
    conn.executemany(
        """
        INSERT INTO candles
            (venue, symbol, timeframe, open_time_ms, open, high, low, close,
             volume, inserted_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (venue, symbol, timeframe, open_time_ms) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low,
            close=excluded.close, volume=excluded.volume
        """,
        [
            (
                c.venue.value,
                c.symbol,
                c.timeframe,
                _to_ms(c.open_time),
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
                now_ms,
            )
            for c in candles
        ],
    )
    conn.commit()
    return candle_count_total(conn) - before


def candle_count_total(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]


def last_candle_open_ms(
    conn: sqlite3.Connection, venue: Venue, symbol: str, timeframe: str
) -> int | None:
    row = conn.execute(
        """
        SELECT MAX(open_time_ms) FROM candles
        WHERE venue = ? AND symbol = ? AND timeframe = ?
        """,
        (venue.value, symbol, timeframe),
    ).fetchone()
    return row[0]


def first_candle_open_ms(
    conn: sqlite3.Connection, venue: Venue, symbol: str, timeframe: str
) -> int | None:
    row = conn.execute(
        """
        SELECT MIN(open_time_ms) FROM candles
        WHERE venue = ? AND symbol = ? AND timeframe = ?
        """,
        (venue.value, symbol, timeframe),
    ).fetchone()
    return row[0]


def load_candles(
    conn: sqlite3.Connection,
    venue: Venue,
    symbol: str,
    timeframe: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[Candle]:
    query = """
        SELECT open_time_ms, open, high, low, close, volume FROM candles
        WHERE venue = ? AND symbol = ? AND timeframe = ?
    """
    params: list[object] = [venue.value, symbol, timeframe]
    if start_ms is not None:
        query += " AND open_time_ms >= ?"
        params.append(start_ms)
    if end_ms is not None:
        query += " AND open_time_ms < ?"
        params.append(end_ms)
    query += " ORDER BY open_time_ms"
    return [
        Candle(
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            open_time=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
            open=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
        )
        for row in conn.execute(query, params)
    ]


# --- Market snapshot / scanner repository ----------------------------------


def insert_market_snapshots(conn: sqlite3.Connection, ts_ms: int, rows: Iterable[dict]) -> int:
    cursor = conn.executemany(
        """
        INSERT OR REPLACE INTO market_snapshots
            (ts_ms, coin_id, symbol, price_usd, vol24h_usd, market_cap_usd,
             price_change_1h_pct, price_change_24h_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                ts_ms,
                r["coin_id"],
                r["symbol"],
                r["price_usd"],
                r["vol24h_usd"],
                r["market_cap_usd"],
                r["price_change_1h_pct"],
                r["price_change_24h_pct"],
            )
            for r in rows
        ],
    )
    conn.commit()
    return cursor.rowcount


def previous_snapshot(
    conn: sqlite3.Connection, coin_id: str, before_ms: int, not_older_than_ms: int
) -> tuple[int, float] | None:
    """(ts_ms, vol24h_usd) of the most recent snapshot before ``before_ms``."""
    row = conn.execute(
        """
        SELECT ts_ms, vol24h_usd FROM market_snapshots
        WHERE coin_id = ? AND ts_ms < ? AND ts_ms >= ?
        ORDER BY ts_ms DESC LIMIT 1
        """,
        (coin_id, before_ms, not_older_than_ms),
    ).fetchone()
    return (row[0], row[1]) if row else None


def baseline_vol24h(
    conn: sqlite3.Connection, coin_id: str, since_ms: int, before_ms: int
) -> tuple[float | None, int]:
    """(average 24h volume, snapshot count) over the baseline window."""
    row = conn.execute(
        """
        SELECT AVG(vol24h_usd), COUNT(*) FROM market_snapshots
        WHERE coin_id = ? AND ts_ms >= ? AND ts_ms < ?
        """,
        (coin_id, since_ms, before_ms),
    ).fetchone()
    return row[0], row[1]


def insert_scanner_flag(
    conn: sqlite3.Connection,
    ts_ms: int,
    coin_id: str,
    symbol: str,
    vol_1h_usd: float,
    vol_avg_1h_usd: float,
    volume_multiple: float,
    price_change_1h_pct: float | None,
    price_change_24h_pct: float | None,
    variant: str,
    on_kraken: bool,
    context_json: str,
) -> None:
    conn.execute(
        """
        INSERT INTO scanner_flags
            (ts_ms, coin_id, symbol, vol_1h_usd, vol_avg_1h_usd, volume_multiple,
             price_change_1h_pct, price_change_24h_pct, variant, on_kraken,
             context_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_ms,
            coin_id,
            symbol,
            vol_1h_usd,
            vol_avg_1h_usd,
            volume_multiple,
            price_change_1h_pct,
            price_change_24h_pct,
            variant,
            int(on_kraken),
            context_json,
        ),
    )
    conn.commit()


def find_gaps(
    conn: sqlite3.Connection,
    venue: Venue,
    symbol: str,
    timeframe: str,
    interval_ms: int,
) -> list[tuple[int, int]]:
    """Missing bar ranges as (first_missing_ms, end_exclusive_ms) tuples.

    Note: some venues legitimately omit bars with zero trades; gaps are
    logged and re-fetched once, and only repeat offenders warrant attention.
    """
    rows = conn.execute(
        """
        SELECT open_time_ms FROM candles
        WHERE venue = ? AND symbol = ? AND timeframe = ?
        ORDER BY open_time_ms
        """,
        (venue.value, symbol, timeframe),
    ).fetchall()
    gaps: list[tuple[int, int]] = []
    for (prev,), (cur,) in itertools.pairwise(rows):
        if cur - prev > interval_ms:
            gaps.append((prev + interval_ms, cur))
    return gaps


# --- Execution audit trail -------------------------------------------------


def insert_order(
    conn: sqlite3.Connection,
    *,
    client_order_id: str | None,
    venue_order_id: str | None,
    ts_ms: int,
    venue: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: float | None,
    reduce_only: bool,
    status: str,
    context_json: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO orders
            (client_order_id, venue_order_id, ts_ms, venue, symbol, side,
             order_type, quantity, price, reduce_only, status, context_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            client_order_id,
            venue_order_id,
            ts_ms,
            venue,
            symbol,
            side,
            order_type,
            quantity,
            price,
            int(reduce_only),
            status,
            context_json,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def update_order_status(conn: sqlite3.Connection, venue_order_id: str, status: str) -> None:
    conn.execute(
        "UPDATE orders SET status = ? WHERE venue_order_id = ?",
        (status, venue_order_id),
    )
    conn.commit()


def insert_fill(
    conn: sqlite3.Connection,
    *,
    ts_ms: int,
    venue: str,
    symbol: str,
    venue_order_id: str | None,
    client_order_id: str | None,
    side: str,
    quantity: float,
    price: float,
    fee: float,
    is_maker: bool,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO fills
            (ts_ms, venue, symbol, venue_order_id, client_order_id, side,
             quantity, price, fee, is_maker)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_ms,
            venue,
            symbol,
            venue_order_id,
            client_order_id,
            side,
            quantity,
            price,
            fee,
            int(is_maker),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def fills_for_order(conn: sqlite3.Connection, venue_order_id: str) -> list[tuple]:
    return conn.execute(
        """
        SELECT quantity, price, fee, is_maker FROM fills
        WHERE venue_order_id = ?
        """,
        (venue_order_id,),
    ).fetchall()


def insert_slippage(
    conn: sqlite3.Connection,
    *,
    ts_ms: int,
    venue: str,
    symbol: str,
    side: str,
    expected_price: float,
    fill_price: float | None,
    slippage_pct: float | None,
    gate_triggered: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO slippage_log
            (ts_ms, venue, symbol, side, expected_price, fill_price,
             slippage_pct, gate_triggered)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_ms,
            venue,
            symbol,
            side,
            expected_price,
            fill_price,
            slippage_pct,
            int(gate_triggered),
        ),
    )
    conn.commit()


def insert_equity_snapshot(
    conn: sqlite3.Connection,
    *,
    ts_ms: int,
    venue: str,
    equity_usd: float,
    mode: str,
) -> None:
    conn.execute(
        """
        INSERT INTO equity_snapshots (ts_ms, venue, equity_usd, mode)
        VALUES (?, ?, ?, ?)
        """,
        (ts_ms, venue, equity_usd, mode),
    )
    conn.commit()


def count_fills(conn: sqlite3.Connection, venue: str | None = None) -> int:
    if venue is None:
        return conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM fills WHERE venue = ?", (venue,)).fetchone()[0]
