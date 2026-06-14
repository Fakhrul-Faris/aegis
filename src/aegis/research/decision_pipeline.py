"""Deterministic decision pipeline for forex demo (FX-R3)."""

from __future__ import annotations

from aegis.research.adversarial_review import AdversarialVerdict, review_event_spike_entry
from aegis.research.situation_summary import build_situation_summary
from aegis.research.trade_proposal import TradeProposal


def build_entry_proposal(
    *,
    pair: str,
    direction: str,
    stop: float | None,
    target: float | None,
    event_code: str | None,
    equity_usd: float,
    open_positions: int,
    has_candles: bool,
    has_open_position: bool,
) -> TradeProposal:
    verdict = review_event_spike_entry(
        pair=pair,
        direction=direction,
        has_candles=has_candles,
        has_open_position=has_open_position,
    )
    situation = build_situation_summary(
        pair=pair,
        direction=direction,
        event_code=event_code,
        stop=stop,
        target=target,
        equity_usd=equity_usd,
        open_positions=open_positions,
    )
    signal = direction if verdict.approved else "skip"
    stage = "approver" if verdict.approved else "adversarial"
    return TradeProposal(
        strategy_id="event_spike_fade",
        symbol=pair,
        signal=signal,  # type: ignore[arg-type]
        size_fraction=0.0075,
        stop_loss=stop,
        target=target,
        confidence=verdict.confidence,
        rationale=verdict.rationale,
        stage_reached=stage,  # type: ignore[arg-type]
        for_points=verdict.for_points,
        against_points=verdict.against_points,
        situation=situation,
    )


def build_skip_proposal(
    *,
    pair: str,
    reason: str,
    equity_usd: float,
    open_positions: int,
    extra: dict | None = None,
) -> TradeProposal:
    situation = build_situation_summary(
        pair=pair,
        direction="none",
        event_code=None,
        stop=None,
        target=None,
        equity_usd=equity_usd,
        open_positions=open_positions,
        extra=extra,
    )
    return TradeProposal(
        strategy_id="event_spike_fade",
        symbol=pair,
        signal="skip",
        size_fraction=0.0,
        stop_loss=None,
        target=None,
        confidence=0.0,
        rationale=reason,
        stage_reached="context",
        for_points=(),
        against_points=(reason,),
        situation=situation,
    )


def merge_context(base: dict, proposal: TradeProposal) -> dict:
    ctx = dict(base)
    ctx.update(proposal.to_context())
    return ctx
