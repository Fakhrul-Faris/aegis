"""M5 gate check tests."""

from dataclasses import replace
from unittest.mock import patch

from aegis.config import load_config
from aegis.data import db
from aegis.monitor.config_freeze import verify_or_freeze_paper_config
from aegis.monitor.m5_check import run_m5_check


def test_m5_check_passes_with_frozen_paper(tmp_path):
    db_path = tmp_path / "aegis.sqlite"
    cfg = load_config("config/config.yaml")
    conn = db.connect(str(db_path))
    verify_or_freeze_paper_config(conn, cfg)
    conn.close()

    patched_cfg = replace(load_config("config/config.yaml"), sqlite_path=str(db_path))
    with patch("aegis.monitor.m5_check.load_config", return_value=patched_cfg):
        assert run_m5_check("config/config.yaml") == 0
