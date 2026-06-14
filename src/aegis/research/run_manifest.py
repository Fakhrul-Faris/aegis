"""Reproducible research run manifests (FX-R1 + checkpoint resume)."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

RUNS_DIR = Path("research/runs")


@dataclass
class RunManifest:
    run_id: str
    pipeline: str
    hypothesis_id: str | None
    started_at: str
    git_sha: str | None
    config_hash: str | None
    as_of: str | None
    status: str  # running | complete | failed
    checkpoint_step: str | None = None
    metrics_path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def start_run(
    pipeline: str,
    *,
    hypothesis_id: str | None = None,
    config_hash: str | None = None,
    as_of: str | None = None,
) -> tuple[Path, RunManifest]:
    run_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(
        run_id=run_id,
        pipeline=pipeline,
        hypothesis_id=hypothesis_id,
        started_at=datetime.now(tz=UTC).isoformat(),
        git_sha=_git_sha(),
        config_hash=config_hash,
        as_of=as_of,
        status="running",
    )
    (run_dir / "manifest.json").write_text(json.dumps(manifest.to_dict(), indent=2))
    return run_dir, manifest


def update_checkpoint(run_dir: Path, step: str) -> None:
    manifest_path = run_dir / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["checkpoint_step"] = step
    manifest_path.write_text(json.dumps(data, indent=2))


def complete_run(run_dir: Path, metrics: dict) -> None:
    manifest_path = run_dir / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["status"] = "complete"
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    data["metrics_path"] = str(metrics_path)
    manifest_path.write_text(json.dumps(data, indent=2))


def fail_run(run_dir: Path, error: str) -> None:
    manifest_path = run_dir / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["status"] = "failed"
    (run_dir / "error.txt").write_text(error)
    manifest_path.write_text(json.dumps(data, indent=2))
