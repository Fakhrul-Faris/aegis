"""Strategy C — intraday momentum (H-C1).

Scanner flag + 4h trending-up regime + 15m higher-high breakout.
Pure functions shared by backtest and live paper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np

from aegis.config_intraday import MomentumDayConfig
from aegis.strategy.regime import Regime, detect_regime


class IntradayExit(StrEnum):
    HOLD = "hold"
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    EOD_FLAT = "eod_flat"


@dataclass(frozen=True)
class IntradayEntry:
    bar: int
    price: float
    bar_open_ms: int


def higher_high_breakout(highs: np.ndarray, bar: int, lookback: int) -> bool:
    """Current bar prints a higher high vs the prior ``lookback`` bars."""
    if bar < lookback + 1:
        return False
    window = highs[bar - lookback : bar]
    if len(window) == 0:
        return False
    return highs[bar] > float(np.max(window))


def volume_spike_proxy(
    volumes: np.ndarray,
    bar: int,
    *,
    window: int = 20,
    multiple: float = 3.0,
) -> bool:
    """Backtest stand-in for the CoinGecko scanner (no historical scanner log)."""
    if bar < window:
        return False
    baseline = volumes[bar - window : bar]
    if np.any(baseline <= 0):
        return False
    avg = float(np.mean(baseline))
    if avg <= 0:
        return False
    return float(volumes[bar]) >= multiple * avg


def scanner_flag_recent(
    conn,
    symbol: str,
    bar_open_ms: int,
    bar_timeframe: str,
    *,
    lookback_hours: int = 6,
) -> bool:
    """Live/paper: any scanner flag on symbol in the lookback window."""
    from aegis.core.timeframes import timeframe_ms
    from aegis.data.scanner_join import scanner_flags_in_window

    end_ms = bar_open_ms + timeframe_ms(bar_timeframe)
    start_ms = end_ms - lookback_hours * 3_600_000
    rows = conn.execute(
        """
        SELECT 1 FROM scanner_flags
        WHERE UPPER(symbol) = UPPER(?)
          AND ts_ms >= ? AND ts_ms < ?
        LIMIT 1
        """,
        (symbol, start_ms, end_ms),
    ).fetchone()
    if rows:
        return True
    return bool(scanner_flags_in_window(conn, symbol, bar_open_ms, bar_timeframe))


def regime_trending_up(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    regime_cfg,
) -> bool:
    return detect_regime(highs, lows, closes, regime_cfg) is Regime.TRENDING_UP


def evaluate_entry_at_bar(
    bar: int,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    bar_open_ms: int,
    cfg: MomentumDayConfig,
    *,
    anomaly: bool,
    trending_up: bool,
) -> IntradayEntry | None:
    if not trending_up:
        return None
    if cfg.scanner_required and not anomaly:
        return None
    if not higher_high_breakout(highs, bar, cfg.breakout_lookback_bars):
        return None
    return IntradayEntry(bar=bar, price=float(closes[bar]), bar_open_ms=bar_open_ms)


def evaluate_exit(
    entry_price: float,
    current_price: float,
    bar_open_ms: int,
    cfg: MomentumDayConfig,
) -> IntradayExit:
    if current_price >= entry_price * (1 + cfg.take_profit_pct):
        return IntradayExit.TAKE_PROFIT
    if current_price <= entry_price * (1 - cfg.stop_loss_pct):
        return IntradayExit.STOP_LOSS
    dt = datetime.fromtimestamp(bar_open_ms / 1000, tz=UTC)
    if dt.hour >= cfg.flat_by_hour_utc:
        return IntradayExit.EOD_FLAT
    return IntradayExit.HOLD


def is_past_flat_hour(bar_open_ms: int, cfg: MomentumDayConfig) -> bool:
    dt = datetime.fromtimestamp(bar_open_ms / 1000, tz=UTC)
    return dt.hour >= cfg.flat_by_hour_utc
