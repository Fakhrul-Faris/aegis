"""Strategy A swing momentum engine (Concept §7).

Paper-first on Kraken spot. The volume-anomaly scanner cannot be backtested
(hourly volume history does not exist in free tiers), so this module exposes
two entry modes:

- ``ema_only`` — EMA(9) crosses above EMA(21), RSI(14) < 70. Logged to
  measure the baseline the Concept expects to be roughly break-even.
- ``with_anomaly`` — same, but requires a scanner flag on the asset within the
  entry bar's 4h window. Used live/paper only; the backtester passes a
  boolean series when studying anomaly+EMA jointly on synthetic data.

Exits: 6% take-profit, 3% stop-loss, or EMA(9) crossing back below EMA(21).
All logic is pure functions of OHLCV arrays — shared by backtest and live.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from aegis.config import StrategyAConfig


class SwingTier(StrEnum):
    PASSIVE = "passive"  # EMA cross alone
    MID = "mid"  # anomaly flag without EMA (logged, rarely traded live)
    AGGRESSIVE = "aggressive"  # EMA cross + anomaly


class SwingExit(StrEnum):
    HOLD = "hold"
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    EMA_CROSS = "ema_cross"


@dataclass(frozen=True)
class SwingEntry:
    bar: int
    price: float
    tier: SwingTier
    rsi: float


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average; NaN until ``period`` bars exist."""
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = values[:period].mean()
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI; NaN until ``period + 1`` bars exist."""
    out = np.full(len(values), np.nan)
    if len(values) < period + 1:
        return out
    deltas = np.diff(values)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def detect_ema_cross_up(fast: np.ndarray, slow: np.ndarray, bar: int) -> bool:
    if bar < 1 or np.isnan(fast[bar]) or np.isnan(slow[bar]):
        return False
    return fast[bar - 1] <= slow[bar - 1] and fast[bar] > slow[bar]


def detect_ema_cross_down(fast: np.ndarray, slow: np.ndarray, bar: int) -> bool:
    if bar < 1 or np.isnan(fast[bar]) or np.isnan(slow[bar]):
        return False
    return fast[bar - 1] >= slow[bar - 1] and fast[bar] < slow[bar]


def classify_tier(ema_cross: bool, anomaly: bool) -> SwingTier | None:
    if ema_cross and anomaly:
        return SwingTier.AGGRESSIVE
    if ema_cross:
        return SwingTier.PASSIVE
    if anomaly:
        return SwingTier.MID
    return None


def evaluate_entry(
    bar: int,
    closes: np.ndarray,
    cfg: StrategyAConfig,
    anomaly_flags: np.ndarray | None = None,
    require_anomaly: bool = False,
) -> SwingEntry | None:
    """Return a long entry signal on ``bar``, or None."""
    fast = ema(closes, cfg.ema_fast)
    slow = ema(closes, cfg.ema_slow)
    rs = rsi(closes, cfg.rsi_period)

    if not detect_ema_cross_up(fast, slow, bar):
        return None
    if np.isnan(rs[bar]) or rs[bar] >= cfg.rsi_max_entry:
        return None

    has_anomaly = bool(anomaly_flags[bar]) if anomaly_flags is not None else False
    if require_anomaly and not has_anomaly:
        return None

    tier = classify_tier(ema_cross=True, anomaly=has_anomaly)
    assert tier is not None
    return SwingEntry(bar=bar, price=float(closes[bar]), tier=tier, rsi=float(rs[bar]))


def evaluate_exit(
    entry_price: float,
    current_price: float,
    bar: int,
    closes: np.ndarray,
    cfg: StrategyAConfig,
) -> SwingExit:
    """Exit checks ordered: stop before profit before signal exit."""
    pnl_pct = (current_price - entry_price) / entry_price
    if pnl_pct <= -cfg.stop_loss_pct:
        return SwingExit.STOP_LOSS
    if pnl_pct >= cfg.take_profit_pct:
        return SwingExit.TAKE_PROFIT

    fast = ema(closes, cfg.ema_fast)
    slow = ema(closes, cfg.ema_slow)
    if detect_ema_cross_down(fast, slow, bar):
        return SwingExit.EMA_CROSS
    return SwingExit.HOLD
