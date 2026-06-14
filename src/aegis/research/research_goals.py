"""Research goals — structured parking lot (FX-R1)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

GOALS_DIR = Path("research/goals")


@dataclass
class ResearchGoal:
    hypothesis_id: str
    title: str
    acceptance_criteria: str
    falsifier: str
    status: str  # exploring | parked | frozen_candidate | frozen
    evidence: list[str]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _goal_path(hypothesis_id: str) -> Path:
    safe = hypothesis_id.replace("/", "_")
    return GOALS_DIR / f"{safe}.json"


def list_goals() -> list[ResearchGoal]:
    if not GOALS_DIR.exists():
        return []
    goals: list[ResearchGoal] = []
    for path in sorted(GOALS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        goals.append(ResearchGoal(**data))
    return goals


def load_goal(hypothesis_id: str) -> ResearchGoal | None:
    path = _goal_path(hypothesis_id)
    if not path.exists():
        return None
    return ResearchGoal(**json.loads(path.read_text()))


def save_goal(goal: ResearchGoal) -> Path:
    GOALS_DIR.mkdir(parents=True, exist_ok=True)
    path = _goal_path(goal.hypothesis_id)
    path.write_text(json.dumps(goal.to_dict(), indent=2))
    return path


def add_goal(
    hypothesis_id: str,
    title: str,
    acceptance_criteria: str,
    falsifier: str,
    *,
    status: str = "exploring",
) -> ResearchGoal:
    now = datetime.now(tz=UTC).isoformat()
    goal = ResearchGoal(
        hypothesis_id=hypothesis_id,
        title=title,
        acceptance_criteria=acceptance_criteria,
        falsifier=falsifier,
        status=status,
        evidence=[],
        created_at=now,
        updated_at=now,
    )
    save_goal(goal)
    return goal


def append_evidence(hypothesis_id: str, note: str) -> ResearchGoal:
    goal = load_goal(hypothesis_id)
    if goal is None:
        raise KeyError(f"unknown goal: {hypothesis_id}")
    goal.evidence.append(note)
    goal.updated_at = datetime.now(tz=UTC).isoformat()
    save_goal(goal)
    return goal
