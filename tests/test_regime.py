"""P2.2 regime detector tests."""

import numpy as np

from aegis.config import load_config
from aegis.strategy.regime import Regime, adx, detect_regime, strategy_a_active


def test_adx_produces_values_on_trending_series():
    n = 300
    close = np.linspace(100, 200, n) + np.random.default_rng(0).normal(0, 0.5, n)
    high = close + 1
    low = close - 1
    values = adx(high, low, close)
    assert np.isfinite(values[-1])


def test_uptrend_classified_trending_up():
    cfg = load_config(config_path="config/config.yaml", env_file=None).regime
    n = 300
    close = np.linspace(80, 180, n)
    high = close + 2
    low = close - 2
    regime = detect_regime(high, low, close, cfg)
    assert regime is Regime.TRENDING_UP
    assert strategy_a_active(regime)
