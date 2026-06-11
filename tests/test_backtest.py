"""P1.6 validation: the walk-forward engine on synthetic data with known
answers, and the Monte Carlo envelope's arithmetic properties."""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from aegis.backtest.engine import BacktestParams, run_backtest
from aegis.backtest.montecarlo import simulate_drawdown_envelope
from aegis.config import load_config

BARS_PER_DAY = 24


@pytest.fixture(scope="module")
def cfg():
    return load_config(config_path="config/config.yaml", env_file=None)


@pytest.fixture(scope="module")
def cfg_b(cfg):
    return dataclasses.replace(
        cfg.strategy_b,
        selection_window_days=40,
        oos_check_days=10,
        stability_subwindows=3,
        half_life_min_hours=4,
        half_life_max_hours=72,
    )


def random_walk(rng, n, scale=1.0, start=100.0):
    return start + np.cumsum(rng.normal(0, scale, n))


def ou_series(rng, n, half_life_bars, sigma):
    phi = 0.5 ** (1.0 / half_life_bars)
    s = np.zeros(n)
    for i in range(1, n):
        s[i] = phi * s[i - 1] + rng.normal(0, sigma)
    return s


def synthetic_panel(rng, n):
    """Two planted cointegrated pairs among noise symbols."""
    base1 = random_walk(rng, n, scale=1.0, start=200.0)
    base2 = random_walk(rng, n, scale=0.8, start=150.0)
    return pd.DataFrame(
        {
            "AAA": 1.5 * base1 + ou_series(rng, n, 6.0, sigma=0.8) + 30.0,
            "BBB": base1,
            "CCC": 0.9 * base2 + ou_series(rng, n, 8.0, sigma=0.6) + 10.0,
            "DDD": base2,
            "RW1": random_walk(rng, n),
            "RW2": random_walk(rng, n),
        }
    )


class TestWalkForward:
    @pytest.fixture(scope="class")
    def result(self, cfg, cfg_b):
        rng = np.random.default_rng(404)
        n = 75 * BARS_PER_DAY  # 50d warmup + 25d trading
        panel = synthetic_panel(rng, n)
        return run_backtest(
            panel,
            cfg_b,
            cfg.risk,
            cfg.hyperliquid.fees,
            BacktestParams(initial_equity=1000.0),
        )

    def test_trades_happen_on_planted_pairs(self, result):
        assert len(result.trades) >= 5
        traded_pairs = {(t.symbol_a, t.symbol_b) for t in result.trades}
        assert traded_pairs <= {("AAA", "BBB"), ("CCC", "DDD")}

    def test_positive_expectancy_on_genuine_mean_reversion(self, result):
        # Planted OU spreads with low costs MUST be profitable - if this
        # fails, the engine (not the market) is broken.
        assert result.expectancy_r > 0
        assert result.win_rate > 0.5

    def test_equity_curve_consistent_with_trades(self, result):
        pnl_sum = sum(t.pnl_net for t in result.trades)
        open_unrealized_absent = result.equity_curve[-1] - 1000.0
        # Curve moves only by closed-trade P&L (no marking of open positions).
        assert open_unrealized_absent == pytest.approx(pnl_sum, abs=1e-6)

    def test_costs_charged_on_every_trade(self, result):
        assert all(t.costs > 0 for t in result.trades)
        # Full round trip: 2x(maker+taker) + 2x slippage = 0.28% of leg notional.
        for trade in result.trades:
            assert trade.costs == pytest.approx(trade.leg_notional * 0.0028, rel=1e-6)

    def test_exit_reasons_are_legal(self, result):
        legal = {"take_profit", "hard_stop", "time_stop"}
        assert {t.exit_reason for t in result.trades} <= legal

    def test_refits_happened(self, result):
        assert result.refits >= 2

    def test_random_walks_produce_no_trades(self, cfg, cfg_b):
        rng = np.random.default_rng(11)
        n = 60 * BARS_PER_DAY
        panel = pd.DataFrame({f"RW{i}": random_walk(rng, n) for i in range(6)})
        result = run_backtest(panel, cfg_b, cfg.risk, cfg.hyperliquid.fees)
        assert result.trades == []

    def test_min_notional_skips_at_tiny_equity(self, cfg, cfg_b):
        rng = np.random.default_rng(404)
        n = 75 * BARS_PER_DAY
        panel = synthetic_panel(rng, n)
        result = run_backtest(
            panel,
            cfg_b,
            cfg.risk,
            cfg.hyperliquid.fees,
            # 50 cents of risk per trade derives a notional far below this
            # floor: every signal must be skipped, never rounded up into
            # oversized risk.
            BacktestParams(initial_equity=100.0, tier_risk_pct=0.005, min_notional_usd=50_000.0),
        )
        assert result.trades == []
        assert result.skipped_below_min_notional > 0


class TestMonteCarlo:
    def test_envelope_percentiles_ordered(self):
        rng = np.random.default_rng(5)
        rs = rng.choice([1.0, -1.0], size=200, p=[0.55, 0.45])
        env = simulate_drawdown_envelope(rs, n_paths=2000, trades_per_path=300)
        assert (
            env.median_max_dd_pct <= env.p90_max_dd_pct <= env.p95_max_dd_pct <= env.p99_max_dd_pct
        )
        assert env.kill_switch_dd_pct == pytest.approx(env.p99_max_dd_pct * 1.25)

    def test_all_winning_trades_mean_no_drawdown(self):
        env = simulate_drawdown_envelope(np.full(100, 1.0), n_paths=500)
        assert env.p99_max_dd_pct == 0.0
        assert env.median_final_return_pct > 0

    def test_risk_scaling_deepens_drawdowns(self):
        rng = np.random.default_rng(9)
        rs = rng.normal(0.1, 1.0, 300)
        low = simulate_drawdown_envelope(rs, risk_pct=0.005, n_paths=1000)
        high = simulate_drawdown_envelope(rs, risk_pct=0.01, n_paths=1000)
        assert high.p95_max_dd_pct > low.p95_max_dd_pct

    def test_refuses_thin_samples(self):
        with pytest.raises(ValueError, match="30"):
            simulate_drawdown_envelope(np.ones(10))

    def test_deterministic_with_seed(self):
        rs = np.array([1.0, -0.5, 2.0, -1.0] * 20)
        a = simulate_drawdown_envelope(rs, seed=42, n_paths=500)
        b = simulate_drawdown_envelope(rs, seed=42, n_paths=500)
        assert a == b
