"""Risk-based position sizing with a minimum-notional floor (P1.4, Concept §9.4).

One unit system for everything: 1R = the tier's risk fraction of CURRENT
equity. Notional is derived from stop distance - never chosen first. When
the exchange minimum exceeds the derived notional, the trade is SKIPPED and
logged; rounding up would silently multiply risk, which is how 1% intentions
become 3% realities. Leverage never appears here: it reduces collateral
locked, not risk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 1R for the concurrent-risk budget = 1% of equity (the Aggressive tier), so
# "max 3R open" means at most 3% of equity at risk across all positions
# regardless of tier mix (Concept §10).
BASE_R_PCT = 0.01


@dataclass(frozen=True)
class SizingDecision:
    approved: bool
    reason: str
    risk_amount: float = 0.0
    notional: float = 0.0
    risk_r: float = 0.0  # in units of base tier risk (for the 3R budget)


def size_position(
    equity: float,
    tier_risk_pct: float,
    stop_distance_pct: float,
    min_notional: float,
    regime_size_factor: float = 1.0,
) -> SizingDecision:
    """Derive notional from risk; enforce the exchange floor.

    ``stop_distance_pct``: adverse move to the stop as a fraction of notional
    (for spreads: dollar distance between entry and stop spread / leg notional).
    ``regime_size_factor``: e.g. 0.5 for Strategy B in trending regimes.
    """
    if equity <= 0:
        return SizingDecision(False, "no_equity")
    if not 0 < stop_distance_pct < 1:
        return SizingDecision(False, f"invalid_stop_distance:{stop_distance_pct}")

    risk_amount = equity * tier_risk_pct * regime_size_factor
    notional = risk_amount / stop_distance_pct

    if notional < min_notional:
        logger.info(
            "trade skipped: below exchange minimum",
            extra={
                "notional": round(notional, 2),
                "min_notional": min_notional,
                "risk_amount": round(risk_amount, 2),
            },
        )
        return SizingDecision(
            False,
            "below_min_notional",
            risk_amount=risk_amount,
            notional=notional,
        )

    return SizingDecision(
        True,
        "ok",
        risk_amount=risk_amount,
        notional=notional,
        risk_r=(tier_risk_pct * regime_size_factor) / BASE_R_PCT,
    )


def concurrent_risk_allows(
    open_risk_r: float, new_risk_r: float, max_concurrent_risk_r: float
) -> bool:
    """The portfolio-wide open-risk budget (Concept §10): default cap 3R."""
    return open_risk_r + new_risk_r <= max_concurrent_risk_r + 1e-9
