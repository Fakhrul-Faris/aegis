"""Configuration loading and validation.

Layering, lowest to highest precedence:
1. config/config.yaml - all non-secret defaults, committed to git.
2. Environment variables - secrets (from .env via python-dotenv) and
   AEGIS_-prefixed overrides for deploy-time switches.

Validation is strict and fails at startup: a trading bot must never run
with a half-understood configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

VALID_MODES = ("paper", "testnet", "live")


class ConfigError(Exception):
    """Raised when configuration is missing, malformed, or unsafe."""


@dataclass(frozen=True)
class RiskTiers:
    passive: float
    mid: float
    aggressive: float


@dataclass(frozen=True)
class RiskConfig:
    tiers: RiskTiers
    max_concurrent_risk_r: float
    correlation_trigger: float
    correlation_release: float
    correlation_min_observations: int
    slippage_gate_pct: float
    daily_breaker_multiple: float
    kill_switch_drawdown_pct: float | None


@dataclass(frozen=True)
class StrategyBConfig:
    universe_size: int
    history_min_days: int
    selection_window_days: int
    fdr_alpha: float
    stability_subwindows: int
    oos_check_days: int
    half_life_min_hours: float
    half_life_max_hours: float
    z_window_half_life_multiple: float
    z_entry_percentile: float
    z_hard_stop: float
    z_scale_out: float
    time_stop_half_life_multiple: float
    min_edge_to_cost_ratio: float
    bar_timeframe: str


@dataclass(frozen=True)
class StrategyAConfig:
    ema_fast: int
    ema_slow: int
    rsi_period: int
    rsi_max_entry: float
    take_profit_pct: float
    stop_loss_pct: float
    signal_timeframe: str


@dataclass(frozen=True)
class ScannerConfig:
    top_n_coins: int
    volume_multiple: float
    average_window_days: int
    interval_minutes: int
    min_history_hours: int
    price_up_threshold_pct: float
    price_down_threshold_pct: float


@dataclass(frozen=True)
class RegimeConfig:
    adx_trend_threshold: float
    adx_sideways_threshold: float
    trend_size_factor: float
    timeframe: str


@dataclass(frozen=True)
class ExchangeFees:
    maker_fee: float
    taker_fee: float


@dataclass(frozen=True)
class HyperliquidConfig:
    testnet: bool
    min_order_usd: float
    fees: ExchangeFees


@dataclass(frozen=True)
class DataConfig:
    timeframes: tuple[str, ...]
    initial_backfill_days: int
    hyperliquid_top_n: int
    kraken_symbols: tuple[str, ...]


@dataclass(frozen=True)
class MonitoringConfig:
    telegram_enabled: bool
    daily_summary_hour_utc: int
    log_dir: str
    log_level: str


@dataclass(frozen=True)
class Secrets:
    """Secrets sourced exclusively from the environment / .env file."""

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    hyperliquid_wallet_address: str | None = None
    hyperliquid_private_key: str | None = field(default=None, repr=False)
    kraken_api_key: str | None = field(default=None, repr=False)
    kraken_api_secret: str | None = field(default=None, repr=False)
    coingecko_api_key: str | None = None


@dataclass(frozen=True)
class AegisConfig:
    mode: str
    risk: RiskConfig
    strategy_b: StrategyBConfig
    strategy_a: StrategyAConfig
    scanner: ScannerConfig
    regime: RegimeConfig
    data: DataConfig
    hyperliquid: HyperliquidConfig
    kraken_fees: ExchangeFees
    monitoring: MonitoringConfig
    sqlite_path: str
    secrets: Secrets = field(repr=False, default_factory=Secrets)


def _require(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ConfigError(f"Missing required config key: {key!r}")
    return raw[key]


def _validate(cfg: AegisConfig) -> None:
    if cfg.mode not in VALID_MODES:
        raise ConfigError(f"mode must be one of {VALID_MODES}, got {cfg.mode!r}")

    tiers = cfg.risk.tiers
    for name, value in (
        ("passive", tiers.passive),
        ("mid", tiers.mid),
        ("aggressive", tiers.aggressive),
    ):
        if not 0 < value <= 0.02:
            raise ConfigError(
                f"risk tier {name!r} = {value} outside sane bounds (0, 0.02]. "
                "Risking more than 2% of equity per trade is not this system."
            )
    if not tiers.passive <= tiers.mid <= tiers.aggressive:
        raise ConfigError("risk tiers must be ordered: passive <= mid <= aggressive")

    if cfg.risk.correlation_release >= cfg.risk.correlation_trigger:
        raise ConfigError("correlation_release must be below correlation_trigger (hysteresis)")

    if cfg.mode == "live" and cfg.risk.kill_switch_drawdown_pct is None:
        raise ConfigError(
            "kill_switch_drawdown_pct is unset. It must be calibrated from the "
            "Monte Carlo drawdown envelope (Concept §9.6) before going live."
        )

    if cfg.strategy_b.half_life_min_hours >= cfg.strategy_b.half_life_max_hours:
        raise ConfigError("half_life_min_hours must be below half_life_max_hours")

    if not 0.5 < cfg.strategy_b.z_entry_percentile < 1.0:
        raise ConfigError("z_entry_percentile must be in (0.5, 1.0)")

    if cfg.strategy_b.z_hard_stop <= cfg.strategy_b.z_scale_out:
        raise ConfigError("z_hard_stop must exceed z_scale_out")

    if cfg.strategy_a.take_profit_pct <= cfg.strategy_a.stop_loss_pct:
        raise ConfigError("Strategy A take_profit_pct must exceed stop_loss_pct (positive R:R)")

    from aegis.core.timeframes import TIMEFRAME_MS

    for timeframe in cfg.data.timeframes:
        if timeframe not in TIMEFRAME_MS:
            raise ConfigError(f"Unknown data timeframe {timeframe!r}")
    if cfg.data.initial_backfill_days < 1:
        raise ConfigError("initial_backfill_days must be >= 1")


def load_config(
    config_path: str | Path = "config/config.yaml",
    env_file: str | Path | None = ".env",
) -> AegisConfig:
    """Load, layer, and validate configuration. Fails loudly on any problem."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path.resolve()}")

    with path.open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    if env_file is not None and Path(env_file).exists():
        load_dotenv(env_file, override=False)

    mode = os.environ.get("AEGIS_MODE", _require(raw, "mode"))

    risk_raw = _require(raw, "risk")
    sb_raw = _require(raw, "strategy_b")
    sa_raw = _require(raw, "strategy_a")
    scan_raw = _require(raw, "scanner")
    regime_raw = _require(raw, "regime")
    data_raw = _require(raw, "data")
    ex_raw = _require(raw, "exchanges")
    mon_raw = _require(raw, "monitoring")

    hl_raw = _require(ex_raw, "hyperliquid")
    kraken_raw = _require(ex_raw, "kraken")

    cfg = AegisConfig(
        mode=mode,
        risk=RiskConfig(
            tiers=RiskTiers(**_require(risk_raw, "tiers")),
            max_concurrent_risk_r=risk_raw["max_concurrent_risk_r"],
            correlation_trigger=risk_raw["correlation_trigger"],
            correlation_release=risk_raw["correlation_release"],
            correlation_min_observations=risk_raw["correlation_min_observations"],
            slippage_gate_pct=risk_raw["slippage_gate_pct"],
            daily_breaker_multiple=risk_raw["daily_breaker_multiple"],
            kill_switch_drawdown_pct=risk_raw.get("kill_switch_drawdown_pct"),
        ),
        strategy_b=StrategyBConfig(**sb_raw),
        strategy_a=StrategyAConfig(**sa_raw),
        scanner=ScannerConfig(**scan_raw),
        regime=RegimeConfig(**regime_raw),
        data=DataConfig(
            timeframes=tuple(data_raw["timeframes"]),
            initial_backfill_days=data_raw["initial_backfill_days"],
            hyperliquid_top_n=data_raw["hyperliquid_top_n"],
            kraken_symbols=tuple(data_raw["kraken_symbols"]),
        ),
        hyperliquid=HyperliquidConfig(
            testnet=hl_raw["testnet"],
            min_order_usd=hl_raw["min_order_usd"],
            fees=ExchangeFees(maker_fee=hl_raw["maker_fee"], taker_fee=hl_raw["taker_fee"]),
        ),
        kraken_fees=ExchangeFees(
            maker_fee=kraken_raw["maker_fee"], taker_fee=kraken_raw["taker_fee"]
        ),
        monitoring=MonitoringConfig(
            telegram_enabled=mon_raw["telegram_enabled"],
            daily_summary_hour_utc=mon_raw["daily_summary_hour_utc"],
            # Path overrides let containers relocate writable state to a
            # mounted volume without touching the committed YAML.
            log_dir=os.environ.get("AEGIS_LOG_DIR", mon_raw["log_dir"]),
            log_level=mon_raw["log_level"],
        ),
        sqlite_path=os.environ.get(
            "AEGIS_SQLITE_PATH", _require(raw, "persistence")["sqlite_path"]
        ),
        secrets=Secrets(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
            hyperliquid_wallet_address=os.environ.get("HYPERLIQUID_WALLET_ADDRESS") or None,
            hyperliquid_private_key=os.environ.get("HYPERLIQUID_PRIVATE_KEY") or None,
            kraken_api_key=os.environ.get("KRAKEN_API_KEY") or None,
            kraken_api_secret=os.environ.get("KRAKEN_API_SECRET") or None,
            coingecko_api_key=os.environ.get("COINGECKO_API_KEY") or None,
        ),
    )

    _validate(cfg)
    return cfg
