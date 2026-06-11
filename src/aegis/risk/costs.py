"""Per-trade cost model (P1.5, Concept §13).

An expectancy figure quoted without costs is fiction. This module prices a
full spread round trip so the entry gate can demand that expected
convergence clears total cost by ``min_edge_to_cost_ratio`` (default 2x).

Assumptions, stated plainly:
- Entry: leg 1 post-only (maker), leg 2 IOC (taker) - the maker-then-IOC
  execution of Concept §8.
- Exit: same maker+taker pattern; partial exits cost proportionally the
  same, so the percentage model is unchanged.
- Slippage: the gate allowance is charged on each taker leg as a worst case.
- Funding: largely nets across a spread's two legs but is passed in as an
  estimate, never assumed zero. Live positions log actual funding.

Fees are config DEFAULTS verified against the venue at startup - schedules
change, and a stale fee model silently corrupts every gate downstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from aegis.config import ExchangeFees


@dataclass(frozen=True)
class SpreadTradeCosts:
    """All values are fractions of one leg's notional."""

    fees_pct: float
    slippage_pct: float
    funding_est_pct: float

    @property
    def total_pct(self) -> float:
        return self.fees_pct + self.slippage_pct + self.funding_est_pct


def spread_round_trip_costs(
    fees: ExchangeFees,
    slippage_allowance_pct: float,
    funding_est_pct: float = 0.0,
) -> SpreadTradeCosts:
    """Cost of opening AND closing a two-leg spread position."""
    fees_pct = 2.0 * (fees.maker_fee + fees.taker_fee)  # entry pair + exit pair
    slippage_pct = 2.0 * slippage_allowance_pct  # one taker leg each way
    return SpreadTradeCosts(
        fees_pct=fees_pct,
        slippage_pct=slippage_pct,
        funding_est_pct=funding_est_pct,
    )


def expected_convergence_pct(
    z_entry: float, z_take_profit: float, spread_std: float, leg_notional: float
) -> float:
    """Expected favorable spread move as a fraction of leg notional.

    A move from z_entry back to z_take_profit is |z_entry - z_tp| spread
    standard deviations, in the dependent leg's price units.
    """
    if leg_notional <= 0:
        return 0.0
    return abs(z_entry - z_take_profit) * spread_std / leg_notional


def edge_clears_costs(
    expected_move_pct: float, costs: SpreadTradeCosts, min_edge_to_cost_ratio: float
) -> bool:
    """The entry gate: no trade unless expected edge >= ratio x total cost."""
    return expected_move_pct >= min_edge_to_cost_ratio * costs.total_pct
