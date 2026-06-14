"""FX2 confirmation layer tests."""

import pandas as pd

from aegis.config_forex import load_forex_config
from aegis.strategy.forex_confirms import (
    build_confirm_context,
    score_signal,
    signal_passes_confirms,
)
from aegis.strategy.forex_session import AsianRange, BreakoutSignal


def test_score_signal_requires_threshold():
    cfg = load_forex_config("config/forex.yaml")
    idx = pd.date_range("2024-06-01", periods=24 * 30, freq="1h", tz="UTC")
    ohlc = pd.DataFrame(
        {
            "open": 1.10,
            "high": 1.101,
            "low": 1.099,
            "close": 1.10,
            "volume": 1.0,
        },
        index=idx,
    )
    ctx = build_confirm_context(ohlc, pd.DataFrame(), cfg, calendar_times_ms=[])
    asian = AsianRange(date=pd.Timestamp("2024-06-10", tz="UTC"), high=1.101, low=1.099, bars=6)
    signal = BreakoutSignal(
        date=pd.Timestamp("2024-06-10", tz="UTC"),
        direction="long",
        entry_bar_ts=pd.Timestamp("2024-06-10 07:00", tz="UTC"),
        entry_price=1.102,
        stop_price=1.099,
        target_price=1.1065,
        asian_high=1.101,
        asian_low=1.099,
    )
    day_df = ohlc.loc["2024-06-10":"2024-06-10"]
    bd = score_signal(signal, asian, day_df, ctx, cfg.scm, cfg.calendar)
    assert bd.setup
    assert signal_passes_confirms(bd, cfg.scm, cfg.calendar) or bd.score < cfg.scm.confirm_score_threshold
