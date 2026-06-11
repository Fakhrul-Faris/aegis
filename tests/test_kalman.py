"""P1.2 validation (M2 gate): the Kalman beta must track a drifting hedge
ratio more closely than batch OLS - that superiority is the whole reason the
filter exists."""

import numpy as np
import pytest

from aegis.strategy.kalman import KalmanBeta, rolling_ols_beta


def make_drifting_pair(rng, n=3000, beta_start=1.0, beta_end=2.0):
    true_beta = np.linspace(beta_start, beta_end, n)
    x = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    y = true_beta * x + rng.normal(0, 0.5, n)
    return y, x, true_beta


class TestKalmanBeta:
    def test_converges_on_constant_beta(self):
        rng = np.random.default_rng(5)
        x = 100.0 + np.cumsum(rng.normal(0, 0.5, 2000))
        y = 1.7 * x + rng.normal(0, 0.5, 2000)
        kf = KalmanBeta(initial_beta=1.0)
        betas = kf.fit_series(y, x)
        assert betas[-1] == pytest.approx(1.7, abs=0.05)

    def test_tracks_drifting_beta(self):
        rng = np.random.default_rng(21)
        y, x, true_beta = make_drifting_pair(rng)
        kf = KalmanBeta(process_var=1e-5, initial_beta=1.0)
        betas = kf.fit_series(y, x)
        # The back half should hug the true path, not the historical average.
        back_half_error = np.abs(betas[1500:] - true_beta[1500:]).mean()
        assert back_half_error < 0.05

    def test_beats_rolling_ols_under_drift(self):
        rng = np.random.default_rng(33)
        y, x, true_beta = make_drifting_pair(rng)
        kf = KalmanBeta(process_var=1e-5, initial_beta=1.0)
        kalman_final = kf.fit_series(y, x)[-1]
        ols_final = rolling_ols_beta(y, x, window=1000)
        kalman_error = abs(kalman_final - true_beta[-1])
        ols_error = abs(ols_final - true_beta[-1])
        assert kalman_error < ols_error

    def test_uncertainty_shrinks_with_data(self):
        rng = np.random.default_rng(8)
        x = 100.0 + np.cumsum(rng.normal(0, 0.5, 500))
        y = 1.2 * x + rng.normal(0, 0.5, 500)
        kf = KalmanBeta(initial_var=1.0)
        kf.fit_series(y, x)
        assert kf.p < 1.0


class TestRollingOls:
    def test_exact_on_clean_relation(self):
        x = np.linspace(10, 20, 300)
        y = 3.0 * x + 5.0
        assert rolling_ols_beta(y, x, window=100) == pytest.approx(3.0, abs=1e-9)
