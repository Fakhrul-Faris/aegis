"""Structured logging tests (P0.1)."""

import json
import logging

from aegis.log import setup_logging


def _read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_log_lines_are_valid_json_with_extras(tmp_path):
    setup_logging(log_dir=tmp_path, level="INFO")
    logger = logging.getLogger("aegis.test")

    logger.info(
        "order placed",
        extra={"symbol": "ETH", "venue": "hyperliquid", "notional_usd": 25.0},
    )
    logging.shutdown()

    records = _read_jsonl(tmp_path / "aegis.jsonl")
    assert len(records) == 1
    rec = records[0]
    assert rec["msg"] == "order placed"
    assert rec["level"] == "INFO"
    assert rec["logger"] == "aegis.test"
    assert rec["symbol"] == "ETH"
    assert rec["notional_usd"] == 25.0
    assert "ts" in rec


def test_exceptions_are_captured(tmp_path):
    setup_logging(log_dir=tmp_path, level="INFO")
    logger = logging.getLogger("aegis.test.exc")

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("leg 2 failed")
    logging.shutdown()

    records = _read_jsonl(tmp_path / "aegis.jsonl")
    assert records[-1]["msg"] == "leg 2 failed"
    assert "ValueError: boom" in records[-1]["exc"]


def test_setup_is_idempotent(tmp_path):
    setup_logging(log_dir=tmp_path)
    setup_logging(log_dir=tmp_path)  # second call must not duplicate handlers
    logger = logging.getLogger("aegis.test.idem")
    logger.info("once")
    logging.shutdown()

    records = _read_jsonl(tmp_path / "aegis.jsonl")
    assert len([r for r in records if r["msg"] == "once"]) == 1
