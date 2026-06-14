"""FX4 unit tests — execution model, registry, config extensions."""

import random

from aegis.config_forex import load_forex_config
from aegis.core.models import Side
from aegis.risk.forex_execution_model import (
    quote_from_mid,
    realistic_round_trip_costs_usd,
    simulate_fill,
)
from aegis.strategy.forex_strategy_registry import REGISTRY, active_strategy_spec


def test_forex_config_execution_and_demo_blocks():
    cfg = load_forex_config("config/forex.yaml")
    assert cfg.execution.slippage_pips_min == 1.0
    assert cfg.demo.data_source == "yahoo"
    assert cfg.execution.slippage_pips_max == 3.0
    assert cfg.execution.vps_latency_ms == 200
    assert cfg.demo.paper_days_min == 30
    assert cfg.demo.paper_days_max == 60
    assert cfg.demo.min_closed_trades == 15


def test_execution_model_spread_not_mid():
    cfg = load_forex_config("config/forex.yaml")
    q = quote_from_mid("EURUSD", 1.1000, cfg.costs, ts_ms=0)
    assert q.bid < q.mid < q.ask
    assert q.spread_pips == cfg.costs.spread_pips_for("EURUSD")


def test_execution_model_slippage_worsens_buy_fill():
    cfg = load_forex_config("config/forex.yaml")
    q = quote_from_mid("EURUSD", 1.1000, cfg.costs, ts_ms=0)
    rng = random.Random(42)
    fill = simulate_fill(q, Side.BUY, cfg.costs, cfg.execution, rng=rng)
    assert not fill.skipped
    assert fill.fill_price >= fill.expected_price


def test_realistic_costs_exceed_base():
    cfg = load_forex_config("config/forex.yaml")
    base, extra = realistic_round_trip_costs_usd(cfg, "EURUSD", 0.01, near_event=True)
    assert extra > 0
    assert base.total_usd > 0


def test_active_strategy_is_information_edge():
    cfg = load_forex_config("config/forex.yaml")
    spec = active_strategy_spec(cfg)
    assert spec.strategy_id == "event_spike_fade"
    assert spec.edge_type.value == "information_sentiment"
    assert spec.status == "active"
    assert "event_spike_fade" in REGISTRY
