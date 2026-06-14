"""Typed trade proposal schema (FX-R3 — TradingAgents-inspired, deterministic)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

Signal = Literal["long", "short", "skip", "hold"]
Stage = Literal["context", "adversarial", "risk", "approver", "executor", "done"]


@dataclass(frozen=True)
class TradeProposal:
    strategy_id: str
    symbol: str
    signal: Signal
    size_fraction: float
    stop_loss: float | None
    target: float | None
    confidence: float
    rationale: str
    stage_reached: Stage
    for_points: tuple[str, ...]
    against_points: tuple[str, ...]
    situation: dict[str, Any]

    def to_context(self) -> dict[str, Any]:
        return {
            "proposal": {
                **{k: v for k, v in asdict(self).items() if k != "situation"},
                "for_points": list(self.for_points),
                "against_points": list(self.against_points),
            },
            "situation": self.situation,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_context(), separators=(",", ":"))
