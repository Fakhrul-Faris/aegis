"""Forex SCM configuration (FX0).

Loaded from ``config/forex.yaml`` independently of the crypto ``AegisConfig``
so the forex research track can evolve without touching live crypto settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from aegis.config import ConfigError


@dataclass(frozen=True)
class SessionWindow:
    start: str  # HH:MM UTC
    end: str


@dataclass(frozen=True)
class SessionsConfig:
    asian: SessionWindow
    london: SessionWindow
    new_york: SessionWindow


@dataclass(frozen=True)
class ScmConfig:
    setup: str
    adr_lookback_days: int
    asian_range_max_adr_pct: float
    pre_london_max_adr_pct: float
    london_entry_window_minutes: int
    ny_fade_london_adr_pct: float
    event_wait_hours: int
    event_box_hours: int
    min_reward_risk: float
    confirm_score_threshold: int
    min_confirm_checks: int
    backtest_min_trades_per_window: int
    backtest_min_win_rate: float
    demo_min_win_rate: float


@dataclass(frozen=True)
class CalendarConfig:
    watch_minutes_before: int
    watch_minutes_after: int
    high_impact_tiers: tuple[int, ...]
    event_spike_tiers: tuple[int, ...] = (2, 3)
    event_spike_currencies: tuple[str, ...] = ("USD", "EUR", "GBP")


@dataclass(frozen=True)
class EventSpikeFadeConfig:
    enabled: bool
    pairs: tuple[str, ...]
    timeframe: str
    spike_wait_minutes: int
    spike_fade_minutes: int
    spike_retrace_pct: float
    min_spike_pips: float
    target_mode: str
    flat_by_hour_utc: int
    risk_pct: float
    lots: float


@dataclass(frozen=True)
class DxyConfig:
    symbol: str
    weights: dict[str, float]
    constant: float


@dataclass(frozen=True)
class ForexCostsConfig:
    spread_pips: dict[str, float]
    commission_usd_per_lot_round_turn: float
    slippage_pips: float
    event_spread_multiplier: float
    pip_size: dict[str, float]
    usd_per_pip_per_lot: dict[str, float]

    def spread_pips_for(self, pair: str) -> float:
        return self.spread_pips.get(pair, self.spread_pips.get("default", 0.3))

    def pip_size_for(self, pair: str) -> float:
        return self.pip_size.get(pair, self.pip_size.get("default", 0.0001))

    def usd_per_pip_for(self, pair: str) -> float:
        return self.usd_per_pip_per_lot.get(pair, self.usd_per_pip_per_lot.get("default", 10.0))


@dataclass(frozen=True)
class ForexExecutionConfig:
    """Realistic fill model for demo paper and stress backtests (FX4)."""

    vps_latency_ms: int
    slippage_pips_min: float
    slippage_pips_max: float
    slippage_pips_mean: float
    requote_prob_base: float
    requote_prob_event: float
    max_spread_pips_event: float
    use_worst_case_slippage: bool


@dataclass(frozen=True)
class ForexDemoConfig:
    """FX5–FX6 paper gate parameters (event-only strategy)."""

    equity_usd: float
    paper_days_min: int
    paper_days_max: int
    min_closed_trades: int
    sqlite_path: str
    data_source: str  # yahoo | oanda | sqlite


@dataclass(frozen=True)
class ForexResearchConfig:
    sqlite_path: str
    timeframes: tuple[str, ...]
    download_start: str
    dukascopy_point_decimals: dict[str, int]


@dataclass(frozen=True)
class ForexConfig:
    broker: str
    active_strategy: str
    pairs: tuple[str, ...]
    dxy_pairs: tuple[str, ...]
    dxy: DxyConfig
    sessions: SessionsConfig
    scm: ScmConfig
    calendar: CalendarConfig
    event_spike_fade: EventSpikeFadeConfig
    costs: ForexCostsConfig
    execution: ForexExecutionConfig
    demo: ForexDemoConfig
    research: ForexResearchConfig


def _require(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ConfigError(f"Missing required forex config key: {key!r}")
    return raw[key]


def _session_window(raw: dict[str, Any], name: str) -> SessionWindow:
    block = _require(raw, name)
    return SessionWindow(start=block["start"], end=block["end"])


def _validate(cfg: ForexConfig) -> None:
    if not cfg.pairs:
        raise ConfigError("forex.pairs must not be empty")
    if cfg.scm.min_reward_risk < 1.0:
        raise ConfigError("scm.min_reward_risk must be >= 1.0")
    if cfg.scm.setup not in (
        "london_breakout",
        "london_continuation",
        "ny_fade",
        "event_aftermath",
    ):
        raise ConfigError(
            "scm.setup must be london_breakout, london_continuation, ny_fade, or event_aftermath"
        )
    if not 0 < cfg.scm.backtest_min_win_rate < 1:
        raise ConfigError("scm.backtest_min_win_rate must be in (0, 1)")
    if cfg.costs.commission_usd_per_lot_round_turn < 0:
        raise ConfigError("costs.commission_usd_per_lot_round_turn must be >= 0")
    if cfg.active_strategy not in ("event_spike_fade", "scm"):
        raise ConfigError("active_strategy must be event_spike_fade or scm")
    if cfg.event_spike_fade.enabled and cfg.event_spike_fade.target_mode not in (
        "retrace",
        "fixed_rr",
    ):
        raise ConfigError("event_spike_fade.target_mode must be retrace or fixed_rr")
    if cfg.execution.slippage_pips_min > cfg.execution.slippage_pips_max:
        raise ConfigError("execution.slippage_pips_min must be <= slippage_pips_max")
    if not 0 <= cfg.execution.requote_prob_base <= 1:
        raise ConfigError("execution.requote_prob_base must be in [0, 1]")
    if cfg.demo.paper_days_min > cfg.demo.paper_days_max:
        raise ConfigError("demo.paper_days_min must be <= paper_days_max")
    if cfg.demo.data_source not in ("yahoo", "oanda", "sqlite"):
        raise ConfigError("demo.data_source must be yahoo, oanda, or sqlite")


def load_forex_config(
    config_path: str | Path = "config/forex.yaml",
) -> ForexConfig:
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"Forex config not found: {path.resolve()}")

    with path.open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    sessions_raw = _require(raw, "sessions")
    scm_raw = _require(raw, "scm")
    cal_raw = _require(raw, "calendar")
    costs_raw = _require(raw, "costs")
    exec_raw = raw.get("execution", {})
    demo_raw = raw.get("demo", {})
    research_raw = _require(raw, "research")
    dxy_raw = _require(raw, "dxy")
    esf_raw = raw.get("event_spike_fade", {})

    cfg = ForexConfig(
        broker=_require(raw, "broker"),
        active_strategy=str(raw.get("active_strategy", "scm")),
        pairs=tuple(_require(raw, "pairs")),
        dxy_pairs=tuple(raw.get("dxy_pairs", ())),
        dxy=DxyConfig(
            symbol=dxy_raw["symbol"],
            weights={k: float(v) for k, v in dxy_raw["weights"].items()},
            constant=float(dxy_raw["constant"]),
        ),
        sessions=SessionsConfig(
            asian=_session_window(sessions_raw, "asian"),
            london=_session_window(sessions_raw, "london"),
            new_york=_session_window(sessions_raw, "new_york"),
        ),
        scm=ScmConfig(
            setup=str(scm_raw.get("setup", "london_breakout")),
            adr_lookback_days=int(scm_raw["adr_lookback_days"]),
            asian_range_max_adr_pct=float(scm_raw["asian_range_max_adr_pct"]),
            pre_london_max_adr_pct=float(scm_raw["pre_london_max_adr_pct"]),
            london_entry_window_minutes=int(scm_raw["london_entry_window_minutes"]),
            ny_fade_london_adr_pct=float(scm_raw.get("ny_fade_london_adr_pct", 0.50)),
            event_wait_hours=int(scm_raw.get("event_wait_hours", 2)),
            event_box_hours=int(scm_raw.get("event_box_hours", 2)),
            min_reward_risk=float(scm_raw["min_reward_risk"]),
            confirm_score_threshold=int(scm_raw["confirm_score_threshold"]),
            min_confirm_checks=int(scm_raw["min_confirm_checks"]),
            backtest_min_trades_per_window=int(scm_raw["backtest_min_trades_per_window"]),
            backtest_min_win_rate=float(scm_raw["backtest_min_win_rate"]),
            demo_min_win_rate=float(scm_raw["demo_min_win_rate"]),
        ),
        calendar=CalendarConfig(
            watch_minutes_before=int(cal_raw["watch_minutes_before"]),
            watch_minutes_after=int(cal_raw["watch_minutes_after"]),
            high_impact_tiers=tuple(int(x) for x in cal_raw["high_impact_tiers"]),
            event_spike_tiers=tuple(int(x) for x in cal_raw.get("event_spike_tiers", [2, 3])),
            event_spike_currencies=tuple(
                str(x) for x in cal_raw.get("event_spike_currencies", ["USD", "EUR", "GBP"])
            ),
        ),
        event_spike_fade=EventSpikeFadeConfig(
            enabled=bool(esf_raw.get("enabled", False)),
            pairs=tuple(
                esf_raw.get("pairs")
                or ([esf_raw["pair"]] if "pair" in esf_raw else ["EURUSD"])
            ),
            timeframe=str(esf_raw.get("timeframe", "1h")),
            spike_wait_minutes=int(esf_raw.get("spike_wait_minutes", 30)),
            spike_fade_minutes=int(esf_raw.get("spike_fade_minutes", 60)),
            spike_retrace_pct=float(esf_raw.get("spike_retrace_pct", 0.50)),
            min_spike_pips=float(esf_raw.get("min_spike_pips", 5.0)),
            target_mode=str(esf_raw.get("target_mode", "retrace")),
            flat_by_hour_utc=int(esf_raw.get("flat_by_hour_utc", 21)),
            risk_pct=float(esf_raw.get("risk_pct", 0.0075)),
            lots=float(esf_raw.get("lots", 0.01)),
        ),
        costs=ForexCostsConfig(
            spread_pips=dict(costs_raw["spread_pips"]),
            commission_usd_per_lot_round_turn=float(
                costs_raw["commission_usd_per_lot_round_turn"]
            ),
            slippage_pips=float(costs_raw["slippage_pips"]),
            event_spread_multiplier=float(costs_raw["event_spread_multiplier"]),
            pip_size=dict(costs_raw["pip_size"]),
            usd_per_pip_per_lot=dict(costs_raw["usd_per_pip_per_lot"]),
        ),
        execution=ForexExecutionConfig(
            vps_latency_ms=int(exec_raw.get("vps_latency_ms", 200)),
            slippage_pips_min=float(exec_raw.get("slippage_pips_min", 1.0)),
            slippage_pips_max=float(exec_raw.get("slippage_pips_max", 3.0)),
            slippage_pips_mean=float(exec_raw.get("slippage_pips_mean", 1.5)),
            requote_prob_base=float(exec_raw.get("requote_prob_base", 0.08)),
            requote_prob_event=float(exec_raw.get("requote_prob_event", 0.25)),
            max_spread_pips_event=float(exec_raw.get("max_spread_pips_event", 3.0)),
            use_worst_case_slippage=bool(exec_raw.get("use_worst_case_slippage", False)),
        ),
        demo=ForexDemoConfig(
            equity_usd=float(demo_raw.get("equity_usd", 100.0)),
            paper_days_min=int(demo_raw.get("paper_days_min", 30)),
            paper_days_max=int(demo_raw.get("paper_days_max", 60)),
            min_closed_trades=int(demo_raw.get("min_closed_trades", 15)),
            sqlite_path=os.environ.get(
                "AEGIS_FOREX_DEMO_SQLITE_PATH", demo_raw.get("sqlite_path", "data/aegis.sqlite")
            ),
            data_source=str(demo_raw.get("data_source", "yahoo")),
        ),
        research=ForexResearchConfig(
            sqlite_path=os.environ.get(
                "AEGIS_FOREX_SQLITE_PATH", research_raw["sqlite_path"]
            ),
            timeframes=tuple(research_raw["timeframes"]),
            download_start=research_raw["download_start"],
            dukascopy_point_decimals={
                k: int(v) for k, v in research_raw["dukascopy_point_decimals"].items()
            },
        ),
    )
    _validate(cfg)
    return cfg
