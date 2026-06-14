"""FX0 unit tests — config, calendar, costs, histdata parser."""

import struct

import lzma

from aegis.config_forex import load_forex_config
from aegis.data import db
from aegis.data.forex_calendar import build_calendar_seed, seed_economic_calendar
from aegis.data.forex_download import parse_bi5_ticks, parse_histdata_csv
from aegis.risk.forex_costs import forex_round_trip_costs


def test_load_forex_config():
    cfg = load_forex_config("config/forex.yaml")
    assert "EURUSD" in cfg.pairs
    assert cfg.scm.backtest_min_win_rate == 0.60
    assert cfg.costs.commission_usd_per_lot_round_turn == 4.50


def test_calendar_seed_covers_range():
    events = build_calendar_seed(2015, 2017)
    codes = {e.event_code for e in events}
    assert "NFP" in codes
    assert "FOMC" in codes
    assert "CPI" in codes
    assert "ECB" in codes
    assert len(events) > 150


def test_seed_economic_calendar_sqlite(tmp_path):
    conn = db.connect(tmp_path / "fx.sqlite")
    try:
        seed_economic_calendar(conn, year_start=2015, year_end=2016)
        n = db.count_calendar_events(conn, impact_tier=3)
        assert n > 50
    finally:
        conn.close()


def test_fusion_cost_model_micro_lot():
    cfg = load_forex_config("config/forex.yaml")
    micro = forex_round_trip_costs(cfg.costs, "EURUSD", lots=0.01)
    assert micro.commission_usd == 0.045  # 4.50 * 0.01
    assert micro.spread_usd > 0
    assert micro.total_usd > micro.commission_usd
    event = forex_round_trip_costs(
        cfg.costs, "EURUSD", lots=0.01, near_high_impact_event=True
    )
    assert event.total_usd > micro.total_usd


def test_parse_histdata_csv(tmp_path):
    path = tmp_path / "eur.csv"
    path.write_text(
        "Date,Time,Open,High,Low,Close,Volume\n"
        "2024.01.02,08:00,1.1000,1.1010,1.0990,1.1005,100\n"
    )
    candles = parse_histdata_csv(path, "EURUSD")
    assert len(candles) == 1
    assert candles[0].close == 1.1005


def test_parse_forexsb_csv(tmp_path):
    path = tmp_path / "eur.csv"
    path.write_text("2010-06-01 10:00\t1.21266\t1.21436\t1.21185\t1.21357\t3720\n")
    candles = parse_histdata_csv(path, "EURUSD")
    assert len(candles) == 1
    assert candles[0].close == 1.21357


def test_parse_bi5_ticks():
    hour_start_ms = 1_700_000_400_000
    point = 0.00001
    raw_chunk = struct.pack(">IIIff", 1000, int(1.10010 / point), int(1.10000 / point), 1.0, 1.0)
    payload = lzma.compress(raw_chunk)
    ticks = parse_bi5_ticks(payload, hour_start_ms, point=point)
    assert len(ticks) == 1
    assert abs(ticks[0][1] - 1.10005) < 1e-6
