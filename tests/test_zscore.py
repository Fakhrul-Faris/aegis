"""P1.3 validation (M2 gate): signal logic on synthetic OU spreads with
known parameters, plus the full exit decision table for both directions."""

import numpy as np
import pytest

from aegis.strategy.zscore import (
    Direction,
    ExitAction,
    PairPosition,
    compute_spread,
    empirical_entry_threshold,
    evaluate_entry,
    evaluate_exit,
    zscore,
)


def make_position(direction: Direction, scaled_out: bool = False) -> PairPosition:
    return PairPosition(
        symbol_a="AAA",
        symbol_b="BBB",
        direction=direction,
        beta=1.5,
        entry_z=-2.2 if direction is Direction.LONG_SPREAD else 2.2,
        entry_bar=100,
        half_life_bars=24.0,
        z_entry_threshold=2.2,
        scaled_out=scaled_out,
    )


class TestZscoreMath:
    def test_zscore_of_known_series(self):
        spread = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        # mean 2, std (ddof=1) ~1.5811; z of last = (4-2)/1.5811
        assert zscore(spread, window=5) == pytest.approx(1.2649, abs=1e-3)

    def test_zscore_zero_when_flat(self):
        assert zscore(np.full(50, 3.7), window=20) == 0.0

    def test_compute_spread(self):
        a = np.array([10.0, 12.0])
        b = np.array([4.0, 5.0])
        np.testing.assert_allclose(compute_spread(a, b, 2.0), [2.0, 2.0])

    def test_empirical_threshold_from_distribution(self):
        rng = np.random.default_rng(17)
        z_history = rng.standard_t(df=3, size=20_000)  # fat-tailed on purpose
        threshold = empirical_entry_threshold(z_history, percentile=0.95)
        gaussian_95 = 1.96
        # Fat tails must push the empirical threshold beyond the Gaussian table.
        assert threshold > gaussian_95

    def test_threshold_floor_guards_quiet_windows(self):
        quiet = np.full(1000, 0.1)
        assert empirical_entry_threshold(quiet, percentile=0.95, floor=1.5) == 1.5


class TestEntries:
    def test_entry_directions(self):
        assert evaluate_entry(-2.5, threshold=2.2) is Direction.LONG_SPREAD
        assert evaluate_entry(2.5, threshold=2.2) is Direction.SHORT_SPREAD
        assert evaluate_entry(1.0, threshold=2.2) is None
        assert evaluate_entry(-2.1, threshold=2.2) is None


class TestExits:
    """Decision table, long side; the short side must mirror exactly."""

    @pytest.mark.parametrize(
        ("z_long", "scaled_out", "bars_held", "expected"),
        [
            (-1.8, False, 10, ExitAction.HOLD),
            (-0.9, False, 10, ExitAction.SCALE_OUT),  # crossed |z| <= 1
            (-0.9, True, 10, ExitAction.HOLD),  # only scales out once
            (0.05, False, 10, ExitAction.TAKE_PROFIT),  # z crossed 0
            (-3.1, False, 10, ExitAction.HARD_STOP),  # diverged to 3 sigma
            (-1.8, False, 48, ExitAction.TIME_STOP),  # 2 x 24-bar half-life
            (-3.1, False, 48, ExitAction.HARD_STOP),  # stop outranks time stop
        ],
    )
    def test_decision_table_both_directions(self, z_long, scaled_out, bars_held, expected):
        for direction, z in (
            (Direction.LONG_SPREAD, z_long),
            (Direction.SHORT_SPREAD, -z_long),
        ):
            action = evaluate_exit(
                make_position(direction, scaled_out=scaled_out),
                z=z,
                current_bar=100 + bars_held,
                z_scale_out=1.0,
                z_hard_stop=3.0,
                time_stop_half_life_multiple=2.0,
            )
            assert action is expected, f"{direction}: z={z}"

    def test_entry_freeze_beta_survives_scale_out(self):
        position = make_position(Direction.LONG_SPREAD)
        after = position.with_scale_out()
        assert after.beta == position.beta
        assert after.scaled_out and not position.scaled_out


class TestOnSyntheticOU:
    def test_signals_fire_and_revert_on_ou_spread(self):
        """End-to-end on a synthetic OU spread: entries occur, and a position
        opened at the empirical threshold reaches take-profit before the
        time stop more often than not (that IS mean reversion)."""
        rng = np.random.default_rng(123)
        half_life = 24.0
        phi = 0.5 ** (1.0 / half_life)
        n = 6000
        spread = np.zeros(n)
        for i in range(1, n):
            spread[i] = phi * spread[i - 1] + rng.normal(0, 1.0)

        window = int(4 * half_life)
        zs = np.array([zscore(spread[: i + 1], window) for i in range(window, n)])
        threshold = empirical_entry_threshold(zs[:2000], percentile=0.95)

        outcomes = []
        i = 2000
        while i < len(zs):
            direction = evaluate_entry(zs[i], threshold)
            if direction is None:
                i += 1
                continue
            position = PairPosition("A", "B", direction, 1.0, zs[i], i, half_life, threshold)
            for j in range(i + 1, len(zs)):
                action = evaluate_exit(position, zs[j], j, 1.0, 3.0, 2.0)
                if action in (ExitAction.SCALE_OUT,):
                    position = position.with_scale_out()
                    continue
                if action is not ExitAction.HOLD:
                    outcomes.append(action)
                    i = j
                    break
            else:
                break
            i += 1

        assert len(outcomes) >= 10, "entries should fire on an OU spread"
        good = sum(1 for o in outcomes if o is ExitAction.TAKE_PROFIT)
        assert good / len(outcomes) > 0.5
