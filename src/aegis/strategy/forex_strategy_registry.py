"""Forex strategy registry — edge taxonomy and validation contract (FX4).

Future strategies register here with edge type, hypothesis metadata, and gate
functions so demo infra stays pluggable as markets evolve.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from aegis.backtest.forex_h11b_sweep import passes_event_gate, passes_standard_gate
from aegis.backtest.forex_scm_engine import ScmBacktestResult
from aegis.config_forex import ForexConfig


class ForexEdgeType(StrEnum):
    MEAN_REVERSION = "statistical_mean_reversion"
    MOMENTUM = "momentum_trend"
    MICROSTRUCTURE = "microstructure"
    INFORMATION = "information_sentiment"


@dataclass(frozen=True)
class ForexStrategySpec:
    strategy_id: str
    edge_type: ForexEdgeType
    hypothesis: str
    reason: str
    falsifier: str
    status: str  # active | parked | research
    gate_fn: Callable[[ScmBacktestResult, ForexConfig], tuple[bool, list[str]]]
    event_frequency: bool  # True = use event gate thresholds in research


REGISTRY: dict[str, ForexStrategySpec] = {
    "event_spike_fade": ForexStrategySpec(
        strategy_id="event_spike_fade",
        edge_type=ForexEdgeType.INFORMATION,
        hypothesis="Post tier-2/3 USD/EUR/GBP releases, the initial 30m spike "
        "mean-reverts ~50% within 60m.",
        reason="LP widening + headline overshoot vs revision; fast money fades.",
        falsifier="2/3 OOS windows fail expectancy CI or WR gate on frozen params.",
        status="active",
        gate_fn=passes_event_gate,
        event_frequency=True,
    ),
    "scm": ForexStrategySpec(
        strategy_id="scm",
        edge_type=ForexEdgeType.MOMENTUM,
        hypothesis="London session continuation after compressed Asian range.",
        reason="Institutional flow follows London open after Asia consolidation.",
        falsifier="Walk-forward fails on full 2010–2026 sample (occurred FX2).",
        status="parked",
        gate_fn=passes_standard_gate,
        event_frequency=False,
    ),
}


def active_strategy_spec(cfg: ForexConfig) -> ForexStrategySpec:
    spec = REGISTRY.get(cfg.active_strategy)
    if spec is None:
        raise ValueError(f"Unknown active_strategy: {cfg.active_strategy!r}")
    return spec


def evaluate_gate(result: ScmBacktestResult, cfg: ForexConfig) -> tuple[bool, list[str]]:
    spec = active_strategy_spec(cfg)
    if spec.event_frequency:
        return passes_event_gate(
            result,
            min_trades=cfg.demo.min_closed_trades,
            min_wr=cfg.scm.demo_min_win_rate,
        )
    return spec.gate_fn(result, cfg)
