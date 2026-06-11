"""P1.4 + P1.5 validation (M2 gate): sizing never rounds up to the exchange
minimum, the 3R budget holds, and the cost gate blocks thin edges."""

import pytest

from aegis.config import ExchangeFees
from aegis.risk.costs import (
    edge_clears_costs,
    expected_convergence_pct,
    spread_round_trip_costs,
)
from aegis.risk.sizing import concurrent_risk_allows, size_position

HL_FEES = ExchangeFees(maker_fee=0.00015, taker_fee=0.00045)


class TestSizing:
    def test_notional_derived_from_risk(self):
        # RM3000 equity, 1% tier, 2% stop -> risk RM30, notional RM1500.
        decision = size_position(
            equity=3000, tier_risk_pct=0.01, stop_distance_pct=0.02, min_notional=10
        )
        assert decision.approved
        assert decision.risk_amount == pytest.approx(30.0)
        assert decision.notional == pytest.approx(1500.0)
        assert decision.risk_r == pytest.approx(1.0)

    def test_below_minimum_is_skipped_never_rounded_up(self):
        # The Concept §9.4 failure mode: small account, tight stop.
        decision = size_position(
            equity=400, tier_risk_pct=0.0075, stop_distance_pct=0.04, min_notional=100
        )
        assert not decision.approved
        assert decision.reason == "below_min_notional"
        assert decision.notional == pytest.approx(75.0)  # what it WOULD have been

    def test_regime_factor_halves_risk(self):
        full = size_position(3000, 0.01, 0.02, 10)
        halved = size_position(3000, 0.01, 0.02, 10, regime_size_factor=0.5)
        assert halved.risk_amount == pytest.approx(full.risk_amount / 2)
        assert halved.notional == pytest.approx(full.notional / 2)
        assert halved.risk_r == pytest.approx(0.5)

    def test_rejects_nonsense_inputs(self):
        assert not size_position(0, 0.01, 0.02, 10).approved
        assert not size_position(3000, 0.01, 0.0, 10).approved
        assert not size_position(3000, 0.01, 1.5, 10).approved

    def test_concurrent_risk_budget(self):
        assert concurrent_risk_allows(open_risk_r=2.0, new_risk_r=1.0, max_concurrent_risk_r=3.0)
        assert not concurrent_risk_allows(
            open_risk_r=2.5, new_risk_r=1.0, max_concurrent_risk_r=3.0
        )
        # Tier mixes accumulate fractionally.
        assert concurrent_risk_allows(
            open_risk_r=4 * 0.5, new_risk_r=0.75, max_concurrent_risk_r=3.0
        )


class TestCosts:
    def test_round_trip_fee_arithmetic(self):
        costs = spread_round_trip_costs(HL_FEES, slippage_allowance_pct=0.0008)
        # 2 x (maker + taker) = 2 x 0.06% = 0.12% fees, + 2 x 0.08% slippage.
        assert costs.fees_pct == pytest.approx(0.0012)
        assert costs.slippage_pct == pytest.approx(0.0016)
        assert costs.total_pct == pytest.approx(0.0028)

    def test_funding_estimate_included(self):
        costs = spread_round_trip_costs(HL_FEES, 0.0008, funding_est_pct=0.0005)
        assert costs.total_pct == pytest.approx(0.0033)

    def test_expected_convergence(self):
        # Entry at z=2.2, TP at 0, spread std $4, leg notional $1000 -> 0.88%.
        move = expected_convergence_pct(
            z_entry=2.2, z_take_profit=0.0, spread_std=4.0, leg_notional=1000.0
        )
        assert move == pytest.approx(0.0088)

    def test_edge_gate_blocks_thin_trades(self):
        costs = spread_round_trip_costs(HL_FEES, 0.0008)  # 0.28% total
        # Needs 2x cost = 0.56% expected move.
        assert edge_clears_costs(0.0088, costs, min_edge_to_cost_ratio=2.0)
        assert not edge_clears_costs(0.0040, costs, min_edge_to_cost_ratio=2.0)

    def test_zero_notional_yields_zero_edge(self):
        assert expected_convergence_pct(2.2, 0.0, 4.0, 0.0) == 0.0
