"""Strategy C intraday engine tests."""

import numpy as np

from aegis.config import load_config
from aegis.config_intraday import load_intraday_config
from aegis.strategy.intraday_momentum import (
    IntradayExit,
    evaluate_entry_at_bar,
    evaluate_exit,
    higher_high_breakout,
    volume_spike_proxy,
)
from aegis.strategy.regime import Regime, detect_regime


def test_higher_high_breakout_detects():
    highs = np.array([10.0, 10.5, 10.2, 10.4, 11.0, 11.5])
    assert not higher_high_breakout(highs, 3, 3)
    assert higher_high_breakout(highs, 5, 3)


def test_volume_spike_proxy():
    vols = np.array([100.0] * 25)
    vols[-1] = 400.0
    assert volume_spike_proxy(vols, 24, multiple=3.0)


def test_evaluate_entry_requires_anomaly_and_trend():
    icfg = load_intraday_config("config/intraday.yaml")
    md = icfg.momentum_day
    n = 30
    highs = np.linspace(100, 110, n)
    lows = highs - 1
    closes = highs - 0.5
    bar = n - 1
    ts = 1_700_000_000_000

    assert (
        evaluate_entry_at_bar(
            bar, highs, lows, closes, ts, md, anomaly=False, trending_up=True
        )
        is None
    )
    entry = evaluate_entry_at_bar(
        bar, highs, lows, closes, ts, md, anomaly=True, trending_up=True
    )
    assert entry is not None
    assert entry.price == closes[bar]


def test_evaluate_exit_take_profit_and_stop():
    icfg = load_intraday_config("config/intraday.yaml")
    md = icfg.momentum_day
    entry = 100.0
    ts = 1_700_000_000_000
    assert evaluate_exit(entry, entry * (1 + md.take_profit_pct + 0.001), ts, md) is IntradayExit.TAKE_PROFIT
    assert evaluate_exit(entry, entry * (1 - md.stop_loss_pct - 0.001), ts, md) is IntradayExit.STOP_LOSS


def test_intraday_config_freeze_roundtrip(tmp_path):
    import sqlite3

    from aegis.monitor.intraday_config_freeze import (
        intraday_config_hash,
        verify_or_freeze_intraday_config,
    )

    cfg = load_intraday_config("config/intraday.yaml")
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    conn.executescript(
        "CREATE TABLE config_freeze (scope TEXT PRIMARY KEY, config_hash TEXT, frozen_at_ms INTEGER)"
    )
    h1 = verify_or_freeze_intraday_config(conn, cfg)
    h2 = verify_or_freeze_intraday_config(conn, cfg)
    assert h1 == h2 == intraday_config_hash(cfg)
    conn.close()


def test_intraday_scorecard_empty(tmp_path):
    import time

    from aegis.data import db
    from aegis.monitor.intraday_scorecard import build_intraday_daily_scorecard

    cfg = load_intraday_config("config/intraday.yaml")
    db_path = tmp_path / "demo.sqlite"
    conn = db.connect(db_path)
    try:
        card = build_intraday_daily_scorecard(conn, cfg, int(time.time() * 1000))
        assert card.equity_now_usd == cfg.demo.equity_usd
        assert card.closed_trades_cum == 0
    finally:
        conn.close()
