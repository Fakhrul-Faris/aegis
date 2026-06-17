"""Intraday (Strategy C/D) configuration — loaded from ``config/intraday.yaml``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from aegis.config import ConfigError, ExchangeFees


@dataclass(frozen=True)
class MomentumDayConfig:
    enabled: bool
    symbols: tuple[str, ...]
    signal_timeframe: str
    regime_timeframe: str
    scanner_required: bool
    breakout_lookback_bars: int
    stop_loss_pct: float
    take_profit_pct: float
    risk_pct: float
    flat_by_hour_utc: int
    max_open_positions: int
    max_trades_per_day: int
    daily_profit_cap_r: float
    daily_loss_cap_r: float


@dataclass(frozen=True)
class ScalpConfig:
    enabled: bool
    signal_timeframe: str
    risk_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    max_trades_per_day: int


@dataclass(frozen=True)
class IntradayCostsConfig:
    maker_fee: float
    taker_fee: float
    slippage_pct: float
    min_order_usd: float

    def as_exchange_fees(self) -> ExchangeFees:
        return ExchangeFees(maker_fee=self.maker_fee, taker_fee=self.taker_fee)


@dataclass(frozen=True)
class IntradayDemoConfig:
    equity_usd: float
    paper_weeks_min: int
    weekly_profit_target_usd: float
    weekly_win_days_min: int
    proof_weeks_consecutive: int
    min_closed_trades_cum: int
    max_weekly_drawdown_pct: float
    sqlite_path: str


@dataclass(frozen=True)
class IntradayDataConfig:
    timeframes: tuple[str, ...]
    initial_backfill_days: int
    loop_seconds: int


@dataclass(frozen=True)
class IntradayResearchConfig:
    sqlite_path: str
    volume_spike_multiple: float
    backtest_min_trades: int


@dataclass(frozen=True)
class IntradayConfig:
    active_strategy: str
    demo: IntradayDemoConfig
    momentum_day: MomentumDayConfig
    scalp: ScalpConfig
    costs: IntradayCostsConfig
    data: IntradayDataConfig
    research: IntradayResearchConfig


def _require(mapping: dict, key: str) -> object:
    if key not in mapping:
        raise ConfigError(f"intraday config missing required key: {key}")
    return mapping[key]


def load_intraday_config(path: str | Path | None = None) -> IntradayConfig:
    if path is None:
        path = os.environ.get("AEGIS_INTRADAY_CONFIG", "config/intraday.yaml")
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"intraday config not found: {config_path}")

    with config_path.open() as fh:
        raw = yaml.safe_load(fh) or {}

    demo_raw = _require(raw, "demo")
    sqlite_demo = os.environ.get("AEGIS_SQLITE_PATH") or str(demo_raw["sqlite_path"])
    md_raw = _require(raw, "momentum_day")
    scalp_raw = _require(raw, "scalp")
    costs_raw = _require(raw, "costs")
    data_raw = _require(raw, "data")
    research_raw = _require(raw, "research")

    return IntradayConfig(
        active_strategy=str(_require(raw, "active_strategy")),
        demo=IntradayDemoConfig(
            equity_usd=float(demo_raw["equity_usd"]),
            paper_weeks_min=int(demo_raw["paper_weeks_min"]),
            weekly_profit_target_usd=float(demo_raw["weekly_profit_target_usd"]),
            weekly_win_days_min=int(demo_raw["weekly_win_days_min"]),
            proof_weeks_consecutive=int(demo_raw["proof_weeks_consecutive"]),
            min_closed_trades_cum=int(demo_raw["min_closed_trades_cum"]),
            max_weekly_drawdown_pct=float(demo_raw["max_weekly_drawdown_pct"]),
            sqlite_path=sqlite_demo,
        ),
        momentum_day=MomentumDayConfig(
            enabled=bool(md_raw["enabled"]),
            symbols=tuple(md_raw["symbols"]),
            signal_timeframe=str(md_raw["signal_timeframe"]),
            regime_timeframe=str(md_raw["regime_timeframe"]),
            scanner_required=bool(md_raw["scanner_required"]),
            breakout_lookback_bars=int(md_raw["breakout_lookback_bars"]),
            stop_loss_pct=float(md_raw["stop_loss_pct"]),
            take_profit_pct=float(md_raw["take_profit_pct"]),
            risk_pct=float(md_raw["risk_pct"]),
            flat_by_hour_utc=int(md_raw["flat_by_hour_utc"]),
            max_open_positions=int(md_raw["max_open_positions"]),
            max_trades_per_day=int(md_raw["max_trades_per_day"]),
            daily_profit_cap_r=float(md_raw["daily_profit_cap_r"]),
            daily_loss_cap_r=float(md_raw["daily_loss_cap_r"]),
        ),
        scalp=ScalpConfig(
            enabled=bool(scalp_raw["enabled"]),
            signal_timeframe=str(scalp_raw["signal_timeframe"]),
            risk_pct=float(scalp_raw["risk_pct"]),
            stop_loss_pct=float(scalp_raw["stop_loss_pct"]),
            take_profit_pct=float(scalp_raw["take_profit_pct"]),
            max_trades_per_day=int(scalp_raw["max_trades_per_day"]),
        ),
        costs=IntradayCostsConfig(
            maker_fee=float(costs_raw["maker_fee"]),
            taker_fee=float(costs_raw["taker_fee"]),
            slippage_pct=float(costs_raw["slippage_pct"]),
            min_order_usd=float(costs_raw["min_order_usd"]),
        ),
        data=IntradayDataConfig(
            timeframes=tuple(data_raw["timeframes"]),
            initial_backfill_days=int(data_raw["initial_backfill_days"]),
            loop_seconds=int(data_raw["loop_seconds"]),
        ),
        research=IntradayResearchConfig(
            sqlite_path=str(research_raw["sqlite_path"]),
            volume_spike_multiple=float(research_raw["volume_spike_multiple"]),
            backtest_min_trades=int(research_raw["backtest_min_trades"]),
        ),
    )
