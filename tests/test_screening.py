"""P1.1 validation (M2 gate): the screener must reject noise and recover truth.

Two non-negotiable properties from the tasks doc:
- Fed pure random walks, the pipeline returns ~zero survivors.
- Fed a synthetic cointegrated pair, it recovers the pair, the planted
  hedge ratio, and a half-life in the planted range.
"""

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from aegis.config import load_config
from aegis.strategy.screening import (
    benjamini_hochberg,
    ols_beta,
    ou_half_life_bars,
    screen_pairs,
)

BARS_PER_DAY = 24  # 1h bars


@pytest.fixture(scope="module")
def cfg_b():
    """Strategy B config shrunk so tests run on 50 days of synthetic data."""
    cfg = load_config(config_path="config/config.yaml", env_file=None)
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


def ou_series(rng, n, half_life_bars, sigma=1.0):
    """Ornstein-Uhlenbeck around 0 with a known half-life."""
    phi = 0.5 ** (1.0 / half_life_bars)
    s = np.zeros(n)
    for i in range(1, n):
        s[i] = phi * s[i - 1] + rng.normal(0, sigma)
    return s


class TestPrimitives:
    def test_bh_against_hand_computed_example(self):
        # m=5, alpha=0.25: thresholds 0.05, 0.10, 0.15, 0.20, 0.25.
        # Sorted ps: 0.01<=0.05 ok, 0.04<=0.10 ok, 0.16>0.15, 0.51, 0.81.
        ps = np.array([0.51, 0.01, 0.16, 0.04, 0.81])
        mask = benjamini_hochberg(ps, alpha=0.25)
        assert mask.tolist() == [False, True, False, True, False]

    def test_bh_rejects_nothing_on_uniform_noise(self):
        rng = np.random.default_rng(7)
        ps = rng.uniform(0, 1, 500)
        assert benjamini_hochberg(ps, alpha=0.05).sum() <= 2

    def test_ou_half_life_recovers_planted_value(self):
        rng = np.random.default_rng(11)
        planted = 24.0
        s = ou_series(rng, 5000, half_life_bars=planted)
        estimate = ou_half_life_bars(s)
        assert planted * 0.7 < estimate < planted * 1.4

    def test_half_life_infinite_for_random_walk(self):
        rng = np.random.default_rng(13)
        rw = np.cumsum(rng.normal(0, 1, 5000))
        assert ou_half_life_bars(rw) > 500 or math.isinf(ou_half_life_bars(rw))

    def test_ols_beta_exact_on_noiseless_relation(self):
        x = np.linspace(50, 150, 200)
        assert ols_beta(2.5 * x, x) == pytest.approx(2.5, abs=1e-9)


class TestPipeline:
    def test_random_walks_yield_no_candidates(self, cfg_b):
        """1,225 chance-level tests would pass ~61 pairs at raw alpha;
        the stacked pipeline must pass none."""
        rng = np.random.default_rng(42)
        n = 50 * BARS_PER_DAY
        prices = pd.DataFrame({f"RW{i}": random_walk(rng, n, scale=0.5) for i in range(18)})
        report = screen_pairs(prices, cfg_b)
        assert report.tested == 18 * 17 // 2
        assert report.candidates == []

    def test_recovers_planted_cointegrated_pair(self, cfg_b):
        rng = np.random.default_rng(99)
        n = 50 * BARS_PER_DAY
        planted_beta = 1.5
        # Fast reversion relative to the (shrunk) test sub-windows, mirroring
        # how a real 24h half-life relates to the production 60-day windows.
        # EG has low power when a sub-window holds few half-lives - the
        # screener is REQUIRED to reject those, so the planted pair must be
        # unambiguous.
        planted_half_life = 6.0  # bars = hours on 1h bars

        base = random_walk(rng, n, scale=1.0, start=200.0)
        partner = planted_beta * base + ou_series(rng, n, planted_half_life, sigma=0.4) + 30.0
        prices = pd.DataFrame(
            {
                "AAA": partner,  # alphabetically first -> dependent leg
                "BBB": base,
                "RW1": random_walk(rng, n),
                "RW2": random_walk(rng, n),
                "RW3": random_walk(rng, n),
            }
        )

        report = screen_pairs(prices, cfg_b)
        found = {(c.symbol_a, c.symbol_b): c for c in report.candidates}
        assert ("AAA", "BBB") in found

        candidate = found[("AAA", "BBB")]
        assert candidate.beta == pytest.approx(planted_beta, rel=0.10)
        assert cfg_b.half_life_min_hours <= candidate.half_life_hours <= cfg_b.half_life_max_hours
        assert candidate.oos_adf_pvalue <= cfg_b.fdr_alpha

    def test_short_history_is_skipped_not_guessed(self, cfg_b):
        rng = np.random.default_rng(3)
        prices = pd.DataFrame(
            {
                "AAA": random_walk(rng, 200),
                "BBB": random_walk(rng, 200),
            }
        )
        report = screen_pairs(prices, cfg_b)
        assert report.tested == 0
        assert report.candidates == []
