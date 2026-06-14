"""Realistic forex fill model — spread, slippage, latency, requotes (FX4).

Research backtests use Fusion spread + commission via ``forex_costs``. Demo
paper and stress backtests layer per-fill slippage (1–3 pips), VPS latency,
and broker requote simulation on top.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from aegis.config_forex import ForexConfig, ForexCostsConfig, ForexExecutionConfig
from aegis.core.models import Side
from aegis.risk.forex_costs import ForexTradeCostsUsd, forex_round_trip_costs


@dataclass(frozen=True)
class ForexQuote:
    pair: str
    bid: float
    ask: float
    mid: float
    spread_pips: float
    ts_ms: int


@dataclass(frozen=True)
class ForexFillQuote:
    """Executable price after spread touch + slippage."""

    pair: str
    side: Side
    expected_price: float
    fill_price: float
    slippage_pips: float
    spread_pips: float
    latency_ms: int
    requoted: bool
    skipped: bool
    skip_reason: str | None = None


def pair_to_oanda(pair: str) -> str:
    return f"{pair[:3]}_{pair[3:]}"


def quote_from_mid(
    pair: str,
    mid: float,
    costs: ForexCostsConfig,
    *,
    ts_ms: int,
    event_multiplier: float = 1.0,
) -> ForexQuote:
    pip = costs.pip_size_for(pair)
    half_spread = costs.spread_pips_for(pair) * pip * event_multiplier / 2.0
    return ForexQuote(
        pair=pair,
        bid=mid - half_spread,
        ask=mid + half_spread,
        mid=mid,
        spread_pips=costs.spread_pips_for(pair) * event_multiplier,
        ts_ms=ts_ms,
    )


def _slippage_pips(exec_cfg: ForexExecutionConfig, *, rng: random.Random) -> float:
    if exec_cfg.use_worst_case_slippage:
        return exec_cfg.slippage_pips_max
    lo, hi = exec_cfg.slippage_pips_min, exec_cfg.slippage_pips_max
    return max(lo, min(hi, rng.gauss(exec_cfg.slippage_pips_mean, 0.5)))


def simulate_fill(
    quote: ForexQuote,
    side: Side,
    costs: ForexCostsConfig,
    exec_cfg: ForexExecutionConfig,
    *,
    near_event: bool = False,
    rng: random.Random | None = None,
) -> ForexFillQuote:
    """One leg fill at touch + slippage; may skip on requote / wide spread."""
    rng = rng or random.Random()
    pip = costs.pip_size_for(quote.pair)

    if quote.spread_pips > exec_cfg.max_spread_pips_event and near_event:
        return ForexFillQuote(
            pair=quote.pair,
            side=side,
            expected_price=quote.ask if side is Side.BUY else quote.bid,
            fill_price=0.0,
            slippage_pips=0.0,
            spread_pips=quote.spread_pips,
            latency_ms=exec_cfg.vps_latency_ms,
            requoted=True,
            skipped=True,
            skip_reason="spread_too_wide",
        )

    requote_prob = exec_cfg.requote_prob_event if near_event else exec_cfg.requote_prob_base
    if rng.random() < requote_prob:
        return ForexFillQuote(
            pair=quote.pair,
            side=side,
            expected_price=quote.ask if side is Side.BUY else quote.bid,
            fill_price=0.0,
            slippage_pips=0.0,
            spread_pips=quote.spread_pips,
            latency_ms=exec_cfg.vps_latency_ms,
            requoted=True,
            skipped=True,
            skip_reason="broker_requote",
        )

    slip_pips = _slippage_pips(exec_cfg, rng=rng)
    slip_px = slip_pips * pip
    if side is Side.BUY:
        expected = quote.ask
        fill = expected + slip_px
    else:
        expected = quote.bid
        fill = expected - slip_px

    return ForexFillQuote(
        pair=quote.pair,
        side=side,
        expected_price=expected,
        fill_price=fill,
        slippage_pips=slip_pips,
        spread_pips=quote.spread_pips,
        latency_ms=exec_cfg.vps_latency_ms,
        requoted=False,
        skipped=False,
    )


def realistic_round_trip_costs_usd(
    cfg: ForexConfig,
    pair: str,
    lots: float,
    *,
    near_event: bool = False,
    rng: random.Random | None = None,
) -> tuple[ForexTradeCostsUsd, float]:
    """Fusion base costs + extra slippage USD from execution model (both legs)."""
    base = forex_round_trip_costs(
        cfg.costs, pair, lots=lots, near_high_impact_event=near_event
    )
    rng = rng or random.Random()
    pip_value = cfg.costs.usd_per_pip_for(pair)
    slip_per_leg = _slippage_pips(cfg.execution, rng=rng)
    extra_slip_usd = slip_per_leg * pip_value * lots * 4  # 2 legs × in+out touch
    return base, extra_slip_usd


def slippage_pct(side: Side, fill_price: float, bid: float, ask: float) -> float:
    if side is Side.BUY:
        touch = ask
        return (fill_price - touch) / touch if touch else 0.0
    touch = bid
    return (touch - fill_price) / touch if touch else 0.0
