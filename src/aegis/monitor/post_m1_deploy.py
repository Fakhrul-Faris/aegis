"""One-shot Fly deploy after M1 passes — enables Telegram /commands on collector."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aegis.config import AegisConfig
from aegis.data import db
from aegis.monitor.milestone_schedule import M1_GATE_TARGET_UTC, m1_db_passes

logger = logging.getLogger(__name__)

DEPLOY_DONE_FILE = "post_m1_deploy.done.json"
DEPLOY_FAIL_FILE = "post_m1_deploy.last_fail.json"
GATE_BUFFER = timedelta(minutes=30)
RETRY_INTERVAL = timedelta(hours=6)
FLY_APP = "aegis-collector"


def _marker_path(cfg: AegisConfig, name: str) -> Path:
    return Path(cfg.sqlite_path).parent / name


def deploy_already_done(cfg: AegisConfig) -> bool:
    return _marker_path(cfg, DEPLOY_DONE_FILE).exists()


def _should_retry_after_fail(cfg: AegisConfig) -> bool:
    path = _marker_path(cfg, DEPLOY_FAIL_FILE)
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text())
        last = datetime.fromtimestamp(data["ts_ms"] / 1000, tz=UTC)
        return datetime.now(tz=UTC) - last >= RETRY_INTERVAL
    except (json.JSONDecodeError, KeyError, OSError):
        return True


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


async def _notify(cfg: AegisConfig, text: str) -> None:
    from aegis.monitor.telegram import notifier_from_config

    notifier = notifier_from_config(cfg)
    try:
        await notifier.send(text)
    finally:
        await notifier.close()


async def _run_fly_deploy(cfg: AegisConfig) -> tuple[bool, str]:
    token = cfg.secrets.fly_api_token
    if not token:
        return False, "FLY_API_TOKEN not set on Fly secrets"

    env = os.environ.copy()
    env["FLY_API_TOKEN"] = token
    proc = await asyncio.create_subprocess_exec(
        "flyctl",
        "deploy",
        "-a",
        FLY_APP,
        "--remote-only",
        "--ha=false",
        cwd="/app",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    detail = (stderr or stdout or b"").decode(errors="replace")[-500:]
    return proc.returncode == 0, detail


async def maybe_post_m1_deploy(cfg: AegisConfig) -> None:
    """After M1 gate time + DB pass, deploy once so /commands run on Fly."""
    if deploy_already_done(cfg):
        return

    now = datetime.now(tz=UTC)
    if now < M1_GATE_TARGET_UTC + GATE_BUFFER:
        return

    if not _should_retry_after_fail(cfg):
        return

    conn = db.connect(cfg.sqlite_path)
    try:
        if not m1_db_passes(conn):
            return
    finally:
        conn.close()

    await _notify(
        cfg,
        "Aegis M1 gate PASSED on collector DB. Starting post-M1 Fly deploy "
        "(Telegram /commands + scorecard updates)...",
    )

    ok, detail = await _run_fly_deploy(cfg)
    if ok:
        _write_json(
            _marker_path(cfg, DEPLOY_DONE_FILE),
            {"ts_ms": int(now.timestamp() * 1000), "app": FLY_APP},
        )
        _marker_path(cfg, DEPLOY_FAIL_FILE).unlink(missing_ok=True)
        await _notify(
            cfg,
            "Post-M1 deploy SUCCEEDED. Telegram /status /paper should work 24/7 on Fly.",
        )
        logger.info("post-M1 fly deploy succeeded")
        return

    _write_json(
        _marker_path(cfg, DEPLOY_FAIL_FILE),
        {"ts_ms": int(now.timestamp() * 1000), "detail": detail},
    )
    await _notify(
        cfg,
        "Post-M1 deploy FAILED. Set FLY_API_TOKEN on Fly secrets:\n"
        "  fly secrets set FLY_API_TOKEN=$(fly auth token) -a aegis-collector\n"
        "Or run GitHub Action / deploy/post-m1-deploy.sh manually.\n"
        f"Detail: {detail[:200]}",
    )
    logger.error("post-M1 fly deploy failed", extra={"detail": detail})
