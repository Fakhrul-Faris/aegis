"""Deterministic adversarial review lanes (FX-R3 — bull/bear without LLM)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdversarialVerdict:
    for_points: tuple[str, ...]
    against_points: tuple[str, ...]
    confidence: float
    approved: bool

    @property
    def rationale(self) -> str:
        if self.approved:
            return f"confirm score {self.confidence:.2f}; {len(self.for_points)} for / {len(self.against_points)} against"
        top = self.against_points[0] if self.against_points else "rejected"
        return f"blocked: {top}"


def review_event_spike_entry(
    *,
    pair: str,
    direction: str,
    has_candles: bool,
    has_open_position: bool,
    min_spike_met: bool = True,
    spread_ok: bool = True,
) -> AdversarialVerdict:
    for_pts: list[str] = []
    against_pts: list[str] = []

    if has_candles:
        for_pts.append("ohlc available")
    else:
        against_pts.append("no_candles")

    if not has_open_position:
        for_pts.append("no duplicate open position")
    else:
        against_pts.append("position already open")

    if min_spike_met:
        for_pts.append("spike threshold met")
    else:
        against_pts.append("spike below min_pips")

    if spread_ok:
        for_pts.append("spread within model")
    else:
        against_pts.append("spread too wide")

    for_pts.append(f"frozen recipe H11c-3 on {pair}")
    for_pts.append(f"direction {direction} aligns with fade")

    n_for = len(for_pts)
    n_against = len(against_pts)
    confidence = max(0.0, min(1.0, (n_for - n_against) / max(n_for + n_against, 1)))
    approved = not against_pts and n_for >= 3
    return AdversarialVerdict(
        for_points=tuple(for_pts),
        against_points=tuple(against_pts),
        confidence=confidence,
        approved=approved,
    )
