"""Config loading and validation tests (P0.1)."""

from pathlib import Path

import pytest
import yaml

from aegis.config import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "config.yaml"


def _load_default_raw() -> dict:
    with DEFAULT_CONFIG.open() as fh:
        return yaml.safe_load(fh)


def _write(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_default_config_loads_and_validates():
    cfg = load_config(DEFAULT_CONFIG, env_file=None)
    assert cfg.mode == "paper"
    assert cfg.risk.tiers.passive == 0.0050
    assert cfg.risk.tiers.aggressive == 0.0100
    assert cfg.hyperliquid.min_order_usd == 10.0
    assert cfg.strategy_b.z_hard_stop == 3.0


def test_env_override_mode(monkeypatch):
    monkeypatch.setenv("AEGIS_MODE", "testnet")
    cfg = load_config(DEFAULT_CONFIG, env_file=None)
    assert cfg.mode == "testnet"


def test_secrets_come_from_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-123")
    cfg = load_config(DEFAULT_CONFIG, env_file=None)
    assert cfg.secrets.telegram_bot_token == "tok-123"


def test_invalid_mode_rejected(tmp_path):
    raw = _load_default_raw()
    raw["mode"] = "yolo"
    with pytest.raises(ConfigError, match="mode"):
        load_config(_write(tmp_path, raw), env_file=None)


def test_oversized_risk_tier_rejected(tmp_path):
    raw = _load_default_raw()
    raw["risk"]["tiers"]["aggressive"] = 0.05  # 5% per trade - never
    with pytest.raises(ConfigError, match="sane bounds"):
        load_config(_write(tmp_path, raw), env_file=None)


def test_unordered_tiers_rejected(tmp_path):
    raw = _load_default_raw()
    raw["risk"]["tiers"]["passive"] = 0.02
    with pytest.raises(ConfigError, match="ordered"):
        load_config(_write(tmp_path, raw), env_file=None)


def test_correlation_hysteresis_enforced(tmp_path):
    raw = _load_default_raw()
    raw["risk"]["correlation_release"] = 0.9  # above trigger 0.85
    with pytest.raises(ConfigError, match="hysteresis"):
        load_config(_write(tmp_path, raw), env_file=None)


def test_live_mode_requires_calibrated_kill_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("AEGIS_MODE", raising=False)
    raw = _load_default_raw()
    raw["mode"] = "live"
    assert raw["risk"]["kill_switch_drawdown_pct"] is None
    with pytest.raises(ConfigError, match="kill_switch"):
        load_config(_write(tmp_path, raw), env_file=None)

    # Once calibrated, live mode loads.
    raw["risk"]["kill_switch_drawdown_pct"] = 0.25
    cfg = load_config(_write(tmp_path, raw), env_file=None)
    assert cfg.mode == "live"


def test_missing_config_file_fails_loudly(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml", env_file=None)
