"""Kalman-filter hedge ratio (P1.2, Concept §9.1).

State model: beta follows a random walk; each bar observes
``price_a = beta * price_b + noise``. The filter yields a smooth online
estimate that tracks slow drift without the weekly-refresh jumps of batch
OLS - the v2.0 design this replaces.

The intercept (alpha) is deliberately not modeled: it only shifts the
spread's level, which the rolling z-score mean absorbs.

THE ENTRY-FREEZE RULE lives at the position level (see strategy.zscore):
an open position keeps the beta it was entered with for its whole life.
The filter keeps updating for NEW entries only. A hedge ratio that re-marks
open positions turns logged R-multiples into fiction.
"""

from __future__ import annotations

import numpy as np


class KalmanBeta:
    """Scalar Kalman filter for a random-walk hedge ratio.

    ``process_var`` (q): how fast beta is allowed to drift per bar.
    ``observation_var`` (r): price noise around the linear relation,
    in squared price units of the dependent leg.
    """

    def __init__(
        self,
        process_var: float = 1e-6,
        observation_var: float = 1.0,
        initial_beta: float = 1.0,
        initial_var: float = 1.0,
    ):
        self.q = process_var
        self.r = observation_var
        self.beta = initial_beta
        self.p = initial_var

    def update(self, price_a: float, price_b: float) -> float:
        """Advance one bar; returns the updated beta estimate."""
        self.p += self.q  # predict: random walk widens uncertainty
        innovation = price_a - self.beta * price_b
        innovation_var = price_b * price_b * self.p + self.r
        gain = self.p * price_b / innovation_var
        self.beta += gain * innovation
        self.p *= 1.0 - gain * price_b
        return self.beta

    def fit_series(self, prices_a: np.ndarray, prices_b: np.ndarray) -> np.ndarray:
        """Run the filter over aligned series; returns beta per bar."""
        betas = np.empty(len(prices_a))
        for i, (a, b) in enumerate(zip(prices_a, prices_b, strict=True)):
            betas[i] = self.update(float(a), float(b))
        return betas


def rolling_ols_beta(prices_a: np.ndarray, prices_b: np.ndarray, window: int) -> float:
    """Batch fallback (first backtest iteration only): OLS on the last window."""
    y = np.asarray(prices_a, dtype=float)[-window:]
    x = np.asarray(prices_b, dtype=float)[-window:]
    x_centered = x - x.mean()
    return float(x_centered @ (y - y.mean()) / (x_centered @ x_centered))
