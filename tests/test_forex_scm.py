"""FX1 tests — session labels, Asian range, breakout detection, backtest."""

from datetime import UTC, datetime, timedelta

import pandas as pd

from aegis.backtest.forex_scm_engine import run_scm_backtest
from aegis.config_forex import load_forex_config
from aegis.strategy.forex_session import (
    SessionName,
    compute_asian_ranges,
    detect_london_breakout,
    label_sessions,
    session_at,
)


def _hourly_day(base: datetime, hours: list[int], price: float = 1.10) -> pd.DataFrame:
    rows = []
    for h in hours:
        ts = base.replace(hour=h, minute=0, second=0, microsecond=0)
        rows.append(
            {
                "open": price,
                "high": price + 0.0010,
                "low": price - 0.0010,
                "close": price,
                "volume": 100.0,
            }
        )
    index = pd.DatetimeIndex(
        [base.replace(hour=h, minute=0, second=0, microsecond=0) for h in hours],
        tz="UTC",
    )
    return pd.DataFrame(rows, index=index)


def test_session_at_london_open():
    cfg = load_forex_config("config/forex.yaml")
    ts = pd.Timestamp("2024-06-10 07:00", tz="UTC")
    assert session_at(ts, cfg.sessions) == SessionName.LONDON
    ts_asian = pd.Timestamp("2024-06-10 03:00", tz="UTC")
    assert session_at(ts_asian, cfg.sessions) == SessionName.ASIAN


def test_asian_range_and_long_breakout():
    cfg = load_forex_config("config/forex.yaml")
    day = datetime(2024, 6, 10, tzinfo=UTC)
    # Asian hours tight range around 1.1000
    asian = _hourly_day(day, [0, 1, 2, 3, 4, 5, 6], price=1.1000)
    # London 07:00 breaks above Asian high
    london = pd.DataFrame(
        [
            {
                "open": 1.1005,
                "high": 1.1020,
                "low": 1.1000,
                "close": 1.1015,
                "volume": 100.0,
            }
        ],
        index=pd.DatetimeIndex([pd.Timestamp("2024-06-10 07:00", tz="UTC")]),
    )
    follow = _hourly_day(day, [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], price=1.1020)
    ohlc = pd.concat([asian, london, follow])
    ranges = compute_asian_ranges(ohlc, cfg.sessions)
    assert len(ranges) == 1
    signals = detect_london_breakout(ohlc, cfg.scm, cfg.sessions, asian_ranges=ranges)
    assert len(signals) == 1
    assert signals[0].direction == "long"
    assert signals[0].entry_price == 1.1015


def test_scm_backtest_runs_on_synthetic():
    cfg = load_forex_config("config/forex.yaml")
    start = datetime(2024, 1, 2, tzinfo=UTC)
    frames = []
    for d in range(40):
        day = start + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        asian = _hourly_day(day, list(range(0, 7)), price=1.1000 + d * 0.0001)
        if d % 2 == 0:
            close = 1.1025 + d * 0.0001
            open_p = close - 0.0008
        else:
            close = 1.0975 + d * 0.0001
            open_p = close + 0.0008
        london = pd.DataFrame(
            [{"open": open_p, "high": close + 0.0005, "low": close - 0.0005, "close": close, "volume": 1.0}],
            index=pd.DatetimeIndex([day.replace(hour=7)]),
        )
        rest = _hourly_day(day, list(range(8, 21)), price=close)
        frames.append(pd.concat([asian, london, rest]))
    ohlc = pd.concat(frames)
    result = run_scm_backtest(ohlc, cfg, starting_equity=100.0, use_confirms=False)
    assert len(result.trades) >= 5
