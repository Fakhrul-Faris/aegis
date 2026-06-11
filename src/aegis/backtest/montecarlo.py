"""Monte Carlo drawdown envelope (P1.6, Concept §9.6).

Resamples the backtest's R-multiples into thousands of alternative orderings
to answer the question a single backtest cannot: how deep can drawdowns get
when THE SAME edge meets different luck? The 99th-percentile drawdown (plus
buffer) becomes the account kill switch - hit it live and the system is
behaving unlike anything its own edge can explain, so it stops permanently
pending written review.

Equity compounds multiplicatively: each trade risks ``risk_pct`` of CURRENT
equity, matching how the sizing engine actually behaves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DrawdownEnvelope:
    n_paths: int
    trades_per_path: int
    risk_pct: float
    median_max_dd_pct: float
    p90_max_dd_pct: float
    p95_max_dd_pct: float
    p99_max_dd_pct: float
    kill_switch_dd_pct: float  # p99 x buffer - the Guardrail D value
    median_final_return_pct: float
    prob_ruin_20pct: float  # P(max DD >= 20%) - a sanity number for the docs


def simulate_drawdown_envelope(
    r_multiples: np.ndarray,
    risk_pct: float = 0.0075,
    n_paths: int = 10_000,
    trades_per_path: int = 300,
    kill_buffer: float = 1.25,
    seed: int | None = 7,
) -> DrawdownEnvelope:
    """Bootstrap-resample R-multiples into equity paths; report the envelope."""
    rs = np.asarray(r_multiples, dtype=float)
    if len(rs) < 30:
        raise ValueError(
            f"Only {len(rs)} trades - resampling fewer than 30 manufactures "
            "false confidence. Get more trades first."
        )

    rng = np.random.default_rng(seed)
    samples = rng.choice(rs, size=(n_paths, trades_per_path), replace=True)
    # equity_t = prod(1 + r_t * risk_pct); per-trade returns are small, exact.
    growth = 1.0 + samples * risk_pct
    equity = np.cumprod(growth, axis=1)
    peaks = np.maximum.accumulate(equity, axis=1)
    max_dd = np.max(1.0 - equity / peaks, axis=1)

    p99 = float(np.percentile(max_dd, 99))
    return DrawdownEnvelope(
        n_paths=n_paths,
        trades_per_path=trades_per_path,
        risk_pct=risk_pct,
        median_max_dd_pct=float(np.percentile(max_dd, 50)),
        p90_max_dd_pct=float(np.percentile(max_dd, 90)),
        p95_max_dd_pct=float(np.percentile(max_dd, 95)),
        p99_max_dd_pct=p99,
        kill_switch_dd_pct=p99 * kill_buffer,
        median_final_return_pct=float(np.percentile(equity[:, -1] - 1.0, 50)),
        prob_ruin_20pct=float(np.mean(max_dd >= 0.20)),
    )
