"""Strategy A swing engine tests (M2-style synthetic validation)."""

import numpy as np
import pytest

from aegis.config import load_config
from aegis.strategy.swing import (
    SwingExit,
    SwingTier,
    detect_ema_cross_up,
    ema,
    evaluate_entry,
    evaluate_exit,
    rsi,
)


@pytest.fixture(scope="module")
def cfg_a():
    return load_config(config_path="config/config.yaml", env_file=None).strategy_a


class TestIndicators:
    def test_ema_constant_series(self):
        values = np.full(50, 100.0)
        result = ema(values, 9)
        assert result[48] == pytest.approx(100.0)

    def test_rsi_overbought_on_monotonic_rise(self):
        values = np.linspace(100, 200, 50)
        result = rsi(values, 14)
        assert result[-1] > 70


class TestEntry:
    def test_ema_cross_with_room_on_rsi_fires(self, cfg_a):
        # Craft a series where fast crosses above slow with RSI < 70.
        closes = np.concatenate(
            [
                np.linspace(100, 90, 30),  # dip
                np.linspace(91, 110, 30),  # recovery triggers cross
            ]
        )
        # Search backward for a cross bar
        fast = ema(closes, cfg_a.ema_fast)
        slow = ema(closes, cfg_a.ema_slow)
        cross_bar = next(
            i for i in range(cfg_a.ema_slow + 2, len(closes)) if detect_ema_cross_up(fast, slow, i)
        )
        entry = evaluate_entry(cross_bar, closes, cfg_a)
        assert entry is not None
        assert entry.tier is SwingTier.PASSIVE

    def test_rsi_too_high_blocks_entry(self, cfg_a, monkeypatch):
        closes = np.linspace(100, 110, 50)
        bar = 30
        monkeypatch.setattr("aegis.strategy.swing.rsi", lambda _v, _p: np.full(50, 80.0))
        monkeypatch.setattr(
            "aegis.strategy.swing.ema",
            lambda _v, p: np.full(50, 105.0) if p == cfg_a.ema_fast else np.full(50, 100.0),
        )
        assert evaluate_entry(bar, closes, cfg_a) is None

    def test_anomaly_promotes_tier(self, cfg_a):
        closes = np.concatenate([np.linspace(100, 85, 35), np.linspace(86, 105, 35)])
        flags = np.zeros(len(closes), dtype=bool)
        fast = ema(closes, cfg_a.ema_fast)
        slow = ema(closes, cfg_a.ema_slow)
        cross_bar = next(
            i for i in range(cfg_a.ema_slow + 2, len(closes)) if detect_ema_cross_up(fast, slow, i)
        )
        flags[cross_bar] = True
        entry = evaluate_entry(cross_bar, closes, cfg_a, anomaly_flags=flags)
        assert entry is not None
        assert entry.tier is SwingTier.AGGRESSIVE


class TestExit:
    def test_stop_loss_fires_first(self, cfg_a):
        entry = 100.0
        assert (
            evaluate_exit(entry, 96.0, 10, np.linspace(100, 96, 11), cfg_a) is SwingExit.STOP_LOSS
        )

    def test_take_profit_at_six_percent(self, cfg_a):
        entry = 100.0
        assert (
            evaluate_exit(entry, 106.5, 10, np.linspace(100, 106.5, 11), cfg_a)
            is SwingExit.TAKE_PROFIT
        )
