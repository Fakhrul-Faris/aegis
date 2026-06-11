"""Z-score engine: entries, exits, and stops in one unit system (P1.3, Concept §9.3).

Everything here is a pure function of (prices, position state) so the
backtester and the live engine share identical logic - the property that
makes paper results comparable to backtests at all.

Stops are defined in z-units and bars, never as a percentage of the entry
spread: the spread of a cointegrated pair routinely sits near zero and
crosses sign, so percent-of-spread arithmetic blows up exactly when
signals fire (the v2.0 bug this module replaces).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

import numpy as np


class Direction(StrEnum):
    LONG_SPREAD = "long_spread"  # entered at z <= -threshold, profits as z -> 0
    SHORT_SPREAD = "short_spread"  # entered at z >= +threshold


class ExitAction(StrEnum):
    HOLD = "hold"
    SCALE_OUT = "scale_out"  # close 50% at |z| <= z_scale_out
    TAKE_PROFIT = "take_profit"  # close rest at z crossing 0
    HARD_STOP = "hard_stop"  # |z| >= z_hard_stop against us
    TIME_STOP = "time_stop"  # held >= 2x half-life without converging


@dataclass(frozen=True)
class PairPosition:
    """Open spread position. ``beta`` and thresholds are FROZEN at entry."""

    symbol_a: str
    symbol_b: str
    direction: Direction
    beta: float
    entry_z: float
    entry_bar: int
    half_life_bars: float
    z_entry_threshold: float
    scaled_out: bool = False

    def with_scale_out(self) -> PairPosition:
        return replace(self, scaled_out=True)


def compute_spread(prices_a: np.ndarray, prices_b: np.ndarray, beta: float) -> np.ndarray:
    return np.asarray(prices_a, dtype=float) - beta * np.asarray(prices_b, dtype=float)


def zscore(spread: np.ndarray, window: int) -> float:
    """Z of the latest spread value against the trailing window."""
    tail = np.asarray(spread, dtype=float)[-window:]
    if len(tail) < 3:
        return 0.0
    mean = tail.mean()
    std = tail.std(ddof=1)
    # Relative epsilon: a flat series has float-jitter std ~1e-16, not 0.
    if std <= 1e-12 * (1.0 + abs(mean)):
        return 0.0
    return float((tail[-1] - mean) / std)


def empirical_entry_threshold(
    z_history: np.ndarray, percentile: float, floor: float = 1.5
) -> float:
    """Per-pair entry threshold from the pair's own |z| distribution.

    Crypto spreads are fat-tailed; the Gaussian table understates how often
    |z| = 2 occurs. The floor guards against degenerate quiet windows.
    """
    threshold = float(np.quantile(np.abs(z_history), percentile))
    return max(threshold, floor)


def evaluate_entry(z: float, threshold: float) -> Direction | None:
    if z <= -threshold:
        return Direction.LONG_SPREAD
    if z >= threshold:
        return Direction.SHORT_SPREAD
    return None


def evaluate_exit(
    position: PairPosition,
    z: float,
    current_bar: int,
    z_scale_out: float,
    z_hard_stop: float,
    time_stop_half_life_multiple: float,
) -> ExitAction:
    """Exit logic in normalized space: zn = z for long, -z for short.

    A long-spread entry sits at zn ~ -threshold and profits as zn rises to 0;
    the short case mirrors onto the same axis, so one rule set covers both.
    Order of checks: stops before profits - when both could apply on the
    same bar, the conservative action wins.
    """
    zn = z if position.direction is Direction.LONG_SPREAD else -z

    if zn <= -z_hard_stop:
        return ExitAction.HARD_STOP

    bars_held = current_bar - position.entry_bar
    if bars_held >= time_stop_half_life_multiple * position.half_life_bars:
        return ExitAction.TIME_STOP

    if zn >= 0:
        return ExitAction.TAKE_PROFIT

    if not position.scaled_out and zn >= -z_scale_out:
        return ExitAction.SCALE_OUT

    return ExitAction.HOLD
