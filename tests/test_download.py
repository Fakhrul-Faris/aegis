"""Downloader parsing tests - no network, archives are just CSVs in zips."""

from aegis.data.download import month_range, parse_kline_csv

SAMPLE = (
    b"open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    b"taker_buy_volume,taker_buy_quote_volume,ignore\n"
    b"1609459200000,28923.63,29031.34,28690.17,28995.13,2311.811,1609462799999,"
    b"66768279.5,58389,1215.359,35103183.4,0\n"
    b"1609462800000,28995.13,29470.00,28960.35,29409.99,3601.247,1609466399999,"
    b"105283011.1,82177,1898.985,55522255.8,0\n"
)


class TestParse:
    def test_parses_rows_and_skips_header(self):
        candles = parse_kline_csv(SAMPLE, "BTC", "1h")
        assert len(candles) == 2
        first = candles[0]
        assert first.symbol == "BTC"
        assert first.open == 28923.63
        assert first.close == 28995.13
        assert first.open_time.isoformat() == "2021-01-01T00:00:00+00:00"

    def test_handles_microsecond_timestamps(self):
        # 2025+ archives switched open_time to microseconds.
        row = b"1736290800000000,95000,95500,94800,95200,100,0,0,0,0,0,0\n"
        candles = parse_kline_csv(row, "BTC", "1h")
        assert candles[0].open_time.year == 2025


class TestMonthRange:
    def test_inclusive_range(self):
        months = month_range("2023-11", "2024-02")
        assert months == [(2023, 11), (2023, 12), (2024, 1), (2024, 2)]

    def test_single_month(self):
        assert month_range("2024-05", "2024-05") == [(2024, 5)]

    def test_open_ended_excludes_current_month(self):
        months = month_range("2026-01")
        assert months[0] == (2026, 1)
        assert len(months) >= 4  # through at least May 2026 as of today
