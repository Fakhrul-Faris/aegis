"""Fee verification tests."""

from aegis.config import ExchangeFees
from aegis.execution.fees import compare_fees


class TestCompareFees:
    def test_no_mismatch_within_tolerance(self):
        cfg = ExchangeFees(maker_fee=0.00015, taker_fee=0.00045)
        live = ExchangeFees(maker_fee=0.00016, taker_fee=0.00046)
        assert compare_fees("hyperliquid", cfg, live) == []

    def test_flags_large_drift(self):
        cfg = ExchangeFees(maker_fee=0.00015, taker_fee=0.00045)
        live = ExchangeFees(maker_fee=0.00030, taker_fee=0.00045)
        mismatches = compare_fees("hyperliquid", cfg, live)
        assert len(mismatches) == 1
        assert mismatches[0].leg == "maker"
