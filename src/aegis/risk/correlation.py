"""Pearson correlation guard (P2.1, Concept §9.5 / Guardrail A).

Correlated positions collapse into ONE shared 1R budget. Hysteresis on
trigger (0.85) and release (0.75) prevents flapping when r hovers at the
threshold — four trades at r=0.96 is one trade with 4x risk, not diversification.
"""

from __future__ import annotations

import numpy as np


def pearson_r(returns_a: np.ndarray, returns_b: np.ndarray) -> float:
    """Pearson r on aligned return series. Requires equal length >= 2."""
    a = np.asarray(returns_a, dtype=float)
    b = np.asarray(returns_b, dtype=float)
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    a_std = a.std(ddof=1)
    b_std = b.std(ddof=1)
    if a_std == 0 or b_std == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def assign_correlation_buckets(
    symbols: list[str],
    returns_by_symbol: dict[str, np.ndarray],
    *,
    trigger: float,
    release: float,
    min_observations: int,
    previous_buckets: dict[str, str] | None = None,
) -> dict[str, str]:
    """Greedy bucket assignment with hysteresis.

      Returns ``symbol -> bucket_id``. Symbols in the same bucket share one
      1R risk budget. A pair above ``trigger`` merges; below ``release`` they
    may split only if no other member still binds them.
    """
    previous_buckets = previous_buckets or {}
    buckets: dict[str, str] = {s: s for s in symbols}
    if len(symbols) < 2:
        return buckets

    for i, sym_a in enumerate(symbols):
        ret_a = returns_by_symbol.get(sym_a)
        if ret_a is None or len(ret_a) < min_observations:
            continue
        for sym_b in symbols[i + 1 :]:
            ret_b = returns_by_symbol.get(sym_b)
            if ret_b is None or len(ret_b) < min_observations:
                continue
            n = min(len(ret_a), len(ret_b))
            r = pearson_r(ret_a[-n:], ret_b[-n:])
            prev_same = previous_buckets.get(sym_a) == previous_buckets.get(sym_b)
            threshold = release if prev_same else trigger
            if r > threshold:
                # Merge sym_b's bucket into sym_a's bucket.
                target = buckets[sym_a]
                old = buckets[sym_b]
                for sym, bid in list(buckets.items()):
                    if bid == old:
                        buckets[sym] = target
    return buckets


def bucket_open_risk(
    buckets: dict[str, str], open_risk_by_symbol: dict[str, float]
) -> dict[str, float]:
    """Sum open risk-R per correlation bucket."""
    totals: dict[str, float] = {}
    for sym, risk_r in open_risk_by_symbol.items():
        bid = buckets.get(sym, sym)
        totals[bid] = totals.get(bid, 0.0) + risk_r
    return totals


def correlation_allows_new_risk(
    buckets: dict[str, str],
    open_risk_by_symbol: dict[str, float],
    candidate_symbol: str,
    new_risk_r: float,
    max_bucket_r: float = 1.0,
) -> bool:
    """A correlated bucket may hold at most ``max_bucket_r`` (1R) open."""
    bid = buckets.get(candidate_symbol, candidate_symbol)
    current = bucket_open_risk(buckets, open_risk_by_symbol).get(bid, 0.0)
    return current + new_risk_r <= max_bucket_r + 1e-9
