"""Testnet pair price helpers."""

import pytest

from aegis.core.models import Side
from aegis.execution.testnet_pairs import (
    buy_ioc_price,
    leg_price,
    pair_passes_oracle_check,
    sell_ioc_price,
)


def test_buy_ioc_price_capped_by_oracle_band():
    assert buy_ioc_price(100.0, 100.0) == 100.2
    assert buy_ioc_price(200.0, 100.0) == pytest.approx(101.9)


def test_sell_ioc_price_capped_by_oracle_band():
    assert sell_ioc_price(100.0, 100.0) == 99.8
    assert sell_ioc_price(50.0, 100.0) == pytest.approx(98.1)


def test_pair_oracle_check():
    assert pair_passes_oracle_check(
        long_ask=101.0, long_oracle=100.0, short_ask=50.5, short_oracle=50.0
    )
    assert not pair_passes_oracle_check(
        long_ask=104.0, long_oracle=100.0, short_ask=50.0, short_oracle=50.0
    )


def test_leg_price_sides():
    assert leg_price(Side.BUY, 99.0, 101.0, 100.0) == buy_ioc_price(101.0, 100.0)
    assert leg_price(Side.SELL, 99.0, 101.0, 100.0) == sell_ioc_price(99.0, 100.0)
