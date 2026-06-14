"""Forex demo market data — open-source first (FX4/FX5).

Default backend: **Yahoo Finance** via ``yfinance`` (Apache-2.0). Candles and
quotes are research/demo inputs only; paper fills use the Fusion spread model in
``forex_paper.py``, not broker touch prices.

Optional backends (set ``demo.data_source`` in ``config/forex.yaml``):
- ``yahoo``  — default, no API key
- ``oanda``  — if ``OANDA_API_TOKEN`` set (broker signup; parked if blocked)
- ``sqlite`` — last ingested bars only (offline)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aegis.config import Secrets
from aegis.config_forex import ForexCostsConfig, ForexConfig
from aegis.core.interfaces import MarketData
from aegis.core.models import Candle, Venue
from aegis.risk.forex_execution_model import quote_from_mid

logger = logging.getLogger(__name__)

# Reference mids when no stored candles exist (smoke tests only).
_SMOKE_MID: dict[str, float] = {
    "EURUSD": 1.1000,
    "GBPUSD": 1.2500,
    "USDJPY": 150.00,
    "AUDUSD": 0.6500,
}


def yahoo_fetch_candles(
    pair: str,
    timeframe: str,
    *,
    days: int = 30,
) -> list[Candle]:
    """Download OHLC from Yahoo Finance (``{PAIR}=X`` tickers)."""
    import yfinance as yf

    ticker = f"{pair}=X"
    interval = "1h" if timeframe == "1h" else "15m"
    hist = yf.download(ticker, period=f"{days}d", interval=interval, progress=False)
    if hist.empty:
        return []
    if hasattr(hist.columns, "levels"):
        hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
    out: list[Candle] = []
    for ts, row in hist.iterrows():
        open_time = ts.to_pydatetime()
        if open_time.tzinfo is None:
            open_time = open_time.replace(tzinfo=UTC)
        else:
            open_time = open_time.astimezone(UTC)

        def _val(col: str) -> float:
            v = row[col]
            if hasattr(v, "iloc"):
                v = v.iloc[0]
            return float(v)

        out.append(
            Candle(
                venue=Venue.FOREX_DEMO,
                symbol=pair,
                timeframe=timeframe,
                open_time=open_time,
                open=_val("Open"),
                high=_val("High"),
                low=_val("Low"),
                close=_val("Close"),
                volume=float(_val("Volume")) if "Volume" in row.index else 0.0,
            )
        )
    return out


class YahooForexMarketData(MarketData):
    """Yahoo + SQLite cache + modeled bid/ask for demo paper."""

    def __init__(
        self,
        costs_cfg: ForexCostsConfig,
        *,
        conn=None,
        yahoo_days: int = 30,
    ):
        self._costs = costs_cfg
        self._conn = conn
        self._yahoo_days = yahoo_days

    def _sqlite_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        since: datetime | None,
        limit: int,
    ) -> list[Candle]:
        if self._conn is None:
            return []
        since_ms = int(since.timestamp() * 1000) if since else None
        rows = self._conn.execute(
            """
            SELECT open_time_ms, open, high, low, close, volume
            FROM candles
            WHERE venue = ? AND symbol = ? AND timeframe = ?
              AND (? IS NULL OR open_time_ms >= ?)
            ORDER BY open_time_ms DESC
            LIMIT ?
            """,
            (
                Venue.FOREX_DEMO.value,
                symbol,
                timeframe,
                since_ms,
                since_ms,
                limit,
            ),
        ).fetchall()
        return [
            Candle(
                venue=Venue.FOREX_DEMO,
                symbol=symbol,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(r[0] / 1000, tz=UTC),
                open=r[1],
                high=r[2],
                low=r[3],
                close=r[4],
                volume=r[5],
            )
            for r in reversed(rows)
        ]

    def _research_close(self, symbol: str) -> list[Candle]:
        if self._conn is None:
            return []
        row = self._conn.execute(
            """
            SELECT open_time_ms, open, high, low, close, volume
            FROM candles
            WHERE venue = ? AND symbol = ? AND timeframe = '1h'
            ORDER BY open_time_ms DESC LIMIT 1
            """,
            (Venue.FOREX.value, symbol),
        ).fetchone()
        if not row:
            return []
        return [
            Candle(
                venue=Venue.FOREX_DEMO,
                symbol=symbol,
                timeframe="1h",
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
        ]

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[Candle]:
        batch: list[Candle] = []
        if self._yahoo_days > 0:
            batch = yahoo_fetch_candles(symbol, timeframe, days=self._yahoo_days)
            if since is not None:
                batch = [c for c in batch if c.open_time >= since]
            if batch:
                return batch[-limit:]
        return self._sqlite_candles(symbol, timeframe, since=since, limit=limit)

    async def fetch_top_of_book(self, symbol: str) -> tuple[float, float]:
        candles = self._sqlite_candles(symbol, "1h", since=None, limit=1)
        if not candles:
            candles = self._research_close(symbol)
        if not candles and self._yahoo_days > 0:
            try:
                fresh = yahoo_fetch_candles(symbol, "1h", days=5)
                if fresh:
                    candles = [fresh[-1]]
            except Exception as exc:
                logger.warning("yahoo quote fallback failed", extra={"pair": symbol, "err": str(exc)})
        if not candles:
            mid = _SMOKE_MID.get(symbol, 1.0)
        else:
            mid = candles[-1].close
        q = quote_from_mid(
            symbol, mid, self._costs, ts_ms=int(datetime.now(tz=UTC).timestamp() * 1000)
        )
        return q.bid, q.ask


# Back-compat alias used across FX4 modules.
ForexDemoMarketData = YahooForexMarketData


def build_forex_market_data(
    cfg: ForexConfig,
    secrets: Secrets,
    *,
    conn=None,
) -> MarketData:
    """Composition root — picks demo data backend from config."""
    source = cfg.demo.data_source
    if source == "oanda" and secrets.oanda_api_token:
        from aegis.execution.forex_oanda import OandaMarketData

        return OandaMarketData(secrets, costs_cfg=cfg.costs, conn=conn)
    if source == "sqlite":
        return YahooForexMarketData(cfg.costs, conn=conn, yahoo_days=0)
    return YahooForexMarketData(cfg.costs, conn=conn)
