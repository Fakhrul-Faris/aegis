"""P2.1 risk engine: correlation, slippage, breakers."""

import numpy as np
import pytest

from aegis.config import load_config
from aegis.core.models import Side
from aegis.risk.breakers import (
    BreakerState,
    daily_loss_trips_breaker,
    kill_switch_trips,
    resume_after_manual_review,
    trip_kill_switch,
)
from aegis.risk.correlation import (
    assign_correlation_buckets,
    correlation_allows_new_risk,
    pearson_r,
)
from aegis.risk.engine import RiskEngine
from aegis.risk.slippage import limit_slippage_pct, passes_slippage_gate


@pytest.fixture(scope="module")
def risk_cfg():
    return load_config(config_path="config/config.yaml", env_file=None).risk


class TestCorrelation:
    def test_perfect_correlation(self):
        r = np.linspace(0.01, 0.02, 100)
        assert pearson_r(r, r * 2 + 0.001) == pytest.approx(1.0, abs=1e-6)

    def test_correlated_symbols_share_bucket(self, risk_cfg):
        rng = np.random.default_rng(1)
        base = rng.normal(0, 0.01, 100)
        returns = {
            "BTC": base,
            "ETH": base + rng.normal(0, 0.001, 100),
            "SOL": rng.normal(0, 0.02, 100),
        }
        buckets = assign_correlation_buckets(
            list(returns),
            returns,
            trigger=risk_cfg.correlation_trigger,
            release=risk_cfg.correlation_release,
            min_observations=90,
        )
        assert buckets["BTC"] == buckets["ETH"]
        assert buckets["SOL"] != buckets["BTC"]

    def test_bucket_caps_at_one_r(self, risk_cfg):
        buckets = {"BTC": "b1", "ETH": "b1"}
        open_risk = {"BTC": 0.6}
        assert not correlation_allows_new_risk(buckets, open_risk, "ETH", 0.5)
        assert correlation_allows_new_risk(buckets, open_risk, "ETH", 0.4)


class TestSlippage:
    def test_buy_at_ask_is_zero_slippage(self):
        assert limit_slippage_pct(Side.BUY, 100.0, 99.0, 100.0) == 0.0

    def test_buy_above_ask_counts_slippage(self):
        slip = limit_slippage_pct(Side.BUY, 100.08, 99.0, 100.0)
        assert slip == pytest.approx(0.0008, rel=1e-3)

    def test_gate_blocks_wide_slippage(self):
        assert not passes_slippage_gate(0.001, 0.0008)


class TestBreakers:
    def test_daily_breaker_trips_on_three_r_loss(self):
        assert daily_loss_trips_breaker(
            daily_pnl=-30.0, max_single_trade_risk_usd=10.0, breaker_multiple=3.0
        )

    def test_kill_switch_at_threshold(self):
        assert kill_switch_trips(equity=750, peak_equity=1000, kill_switch_drawdown_pct=0.25)

    def test_manual_resume_blocked_when_killed(self):
        state = BreakerState(killed=True)
        trip_kill_switch(state)
        with pytest.raises(RuntimeError):
            resume_after_manual_review(state)


class TestRiskEngine:
    def test_slippage_gate_rejects_trade(self, risk_cfg):
        engine = RiskEngine(risk_cfg)
        approval = engine.approve_trade(
            equity=1000,
            symbol="BTC",
            new_risk_r=0.75,
            open_risk_r=0,
            open_risk_by_symbol={},
            returns_by_symbol={"BTC": np.zeros(100)},
            side=Side.BUY,
            limit_price=101.0,
            best_bid=99.0,
            best_ask=100.0,
        )
        assert not approval.approved
        assert "slippage" in approval.reason

    def test_breaker_drill_halts_trading(self, risk_cfg):
        state = BreakerState(halted_daily=True)
        engine = RiskEngine(risk_cfg, state)
        approval = engine.approve_trade(
            equity=1000,
            symbol="BTC",
            new_risk_r=0.75,
            open_risk_r=0,
            open_risk_by_symbol={},
            returns_by_symbol={"BTC": np.zeros(100)},
            side=Side.BUY,
            limit_price=100.0,
            best_bid=99.5,
            best_ask=100.0,
        )
        assert not approval.approved
        assert approval.reason == "daily_halt_active"
