"""Hypothesis registry and post-detection filters (FX-A.6)."""

from __future__ import annotations

from dataclasses import dataclass, field

from aegis.strategy.forex_confirms import ConfirmContext, score_signal, signal_passes_confirms
from aegis.strategy.forex_hypotheses import DETECTORS, HypothesisParams
from aegis.strategy.forex_session import BreakoutSignal


@dataclass(frozen=True)
class HypothesisSpec:
    hid: str
    name: str
    pair: str
    timeframe: str
    detector: str
    params: HypothesisParams = field(default_factory=HypothesisParams)
    use_confirms: bool = False
    dxy_mandatory: bool = False
    event_mode: str = "all"  # all | skip | only
    weekday_mode: str = "all"  # all | mon_fri | tue_thu
    time_stop_hours: int | None = None
    min_stop_pips: float | None = None
    calendar_currencies: tuple[str, ...] = ("USD", "EUR")
    skipped: bool = False
    skip_reason: str = ""


def build_hypothesis_matrix() -> list[HypothesisSpec]:
    """All H1–H26 specs (skipped ones marked)."""
    p_ler = HypothesisParams(asian_max_adr_pct=0.30, london_spent_adr_pct=0.60, target_mode="asian_mid")
    p_ler_tight = HypothesisParams(asian_max_adr_pct=0.25, london_spent_adr_pct=0.60, target_mode="asian_mid")
    p_rev08 = HypothesisParams(
        asian_max_adr_pct=0.30,
        london_spent_adr_pct=0.60,
        target_mode="retrace",
        reward_risk=0.8,
    )
    p_m15 = HypothesisParams(london_entry_minutes=90, reward_risk=1.0)
    p_event_1r = HypothesisParams(reward_risk=1.0, stop_risk_mult=0.6)

    specs: list[HypothesisSpec] = [
        HypothesisSpec("H1", "London Exhaustion Reversion", "EURUSD", "1h", "ler", p_ler),
        HypothesisSpec("H2", "NY Fade v2", "EURUSD", "1h", "ny_fade_v2", p_ler),
        HypothesisSpec("H3", "London Close Fade", "EURUSD", "1h", "london_close_fade", p_rev08),
        HypothesisSpec("H4", "Asian Box Fade", "EURUSD", "1h", "asian_box_fade", p_ler),
        HypothesisSpec("H5", "Double Session Exhaustion", "EURUSD", "1h", "double_exhaustion", p_ler),
        HypothesisSpec("H6", "15m London Breakout", "EURUSD", "15m", "m15_breakout", p_m15),
        HypothesisSpec("H7", "15m London Continuation", "EURUSD", "15m", "m15_continuation", p_m15),
        HypothesisSpec("H8", "15m LER", "EURUSD", "15m", "m15_ler", p_ler),
        HypothesisSpec("H9", "15m Post-London Box", "EURUSD", "15m", "post_london_box", p_m15),
        HypothesisSpec("H10", "Event Box 1R/0.6R", "EURUSD", "1h", "event_box_rr", p_event_1r),
        HypothesisSpec("H11", "Event Spike Fade", "EURUSD", "1h", "event_spike_fade", p_ler),
        HypothesisSpec(
            "H12a", "Skip Event Days", "EURUSD", "1h", "ler", p_ler, event_mode="skip"
        ),
        HypothesisSpec(
            "H12b", "Only Event Days", "EURUSD", "1h", "event_box_rr", p_event_1r, event_mode="only"
        ),
        HypothesisSpec("H13", "LER + DXY Mandatory", "EURUSD", "1h", "ler", p_ler, dxy_mandatory=True),
        HypothesisSpec(
            "H14", "DXY Divergence Fade", "EURUSD", "1h", "dxy_divergence", p_ler
        ),
        HypothesisSpec(
            "H15",
            "Risk-on Regime",
            "EURUSD",
            "1h",
            "ler",
            skipped=True,
            skip_reason="needs VIX/gold feed",
        ),
        HypothesisSpec(
            "H16",
            "USDJPY Tokyo-London LER",
            "USDJPY",
            "1h",
            "usdjpy_ler",
            p_ler,
            calendar_currencies=("USD", "JPY"),
        ),
        HypothesisSpec("H17", "GBPUSD LER", "GBPUSD", "1h", "ler", p_ler),
        HypothesisSpec(
            "H18",
            "EURGBP Cross",
            "EURGBP",
            "1h",
            "ler",
            skipped=True,
            skip_reason="no EURGBP data",
        ),
        HypothesisSpec("H19a", "Breakout 1.0R", "EURUSD", "1h", "breakout_1r", p_m15),
        HypothesisSpec("H19b", "Continuation 1.0R", "EURUSD", "1h", "continuation_1r", p_m15),
        HypothesisSpec(
            "H20", "Reversion 0.8R Fixed", "EURUSD", "1h", "ler", p_rev08
        ),
        HypothesisSpec(
            "H21",
            "Partial 0.5R Target",
            "EURUSD",
            "1h",
            "ler",
            HypothesisParams(target_mode="fixed_rr", reward_risk=0.5),
        ),
        HypothesisSpec("H22", "LER + 4h Time Stop", "EURUSD", "1h", "ler", p_ler, time_stop_hours=4),
        HypothesisSpec(
            "H23", "LER Asian <20% ADR", "EURUSD", "1h", "ler", p_ler_tight
        ),
        HypothesisSpec(
            "H24",
            "LER Pre-London Drift Cap",
            "EURUSD",
            "1h",
            "ler",
            HypothesisParams(asian_max_adr_pct=0.30, pre_london_max_adr_pct=0.50),
        ),
        HypothesisSpec(
            "H25", "LER Min Stop 5 Pips", "EURUSD", "1h", "ler", p_ler, min_stop_pips=5.0
        ),
        HypothesisSpec(
            "H26a", "LER Mon/Fri Only", "EURUSD", "1h", "ler", p_ler, weekday_mode="mon_fri"
        ),
        HypothesisSpec(
            "H26b", "LER Tue-Thu Only", "EURUSD", "1h", "ler", p_ler, weekday_mode="tue_thu"
        ),
    ]
    return specs


def _near_event(ts, event_times_ms: list[int], window_min: int = 90) -> bool:
    entry_ms = int(ts.timestamp() * 1000)
    win = window_min * 60_000
    return any(abs(entry_ms - e) <= win for e in event_times_ms)


def _weekday_ok(ts, mode: str) -> bool:
    if mode == "all":
        return True
    dow = ts.dayofweek
    if mode == "mon_fri":
        return dow in (0, 4)
    if mode == "tue_thu":
        return dow in (1, 2, 3)
    return True


def apply_filters(
    signals: list[BreakoutSignal],
    spec: HypothesisSpec,
    *,
    ohlc,
    asian_ranges: dict,
    ctx: ConfirmContext | None,
    cfg,
    event_times_ms: list[int],
) -> list[BreakoutSignal]:
    out: list[BreakoutSignal] = []
    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()
    pip = cfg.costs.pip_size_for(spec.pair)

    for sig in signals:
        if not _weekday_ok(sig.entry_bar_ts, spec.weekday_mode):
            continue
        near = _near_event(sig.entry_bar_ts, event_times_ms)
        if spec.event_mode == "skip" and near:
            continue
        if spec.event_mode == "only" and not near:
            continue
        if spec.min_stop_pips is not None:
            if abs(sig.entry_price - sig.stop_price) / pip < spec.min_stop_pips:
                continue
        if spec.dxy_mandatory and ctx is not None:
            asian = asian_ranges.get(sig.date)
            if asian is None:
                continue
            day_df = df.loc[df["utc_date"] == sig.date]
            bd = score_signal(sig, asian, day_df, ctx, cfg.scm, cfg.calendar)
            if not bd.dxy_align:
                continue
        if spec.use_confirms and ctx is not None:
            asian = asian_ranges.get(sig.date)
            if asian is None:
                continue
            day_df = df.loc[df["utc_date"] == sig.date]
            bd = score_signal(sig, asian, day_df, ctx, cfg.scm, cfg.calendar)
            if not signal_passes_confirms(bd, cfg.scm, cfg.calendar):
                continue
        out.append(sig)
    return out


def detect_for_spec(
    spec: HypothesisSpec,
    ohlc,
    sessions,
    event_times_ms: list[int],
    asian_ranges: dict,
    dxy_ohlc=None,
) -> list[BreakoutSignal]:
    fn = DETECTORS[spec.detector]
    if spec.detector == "dxy_divergence":
        return fn(
            ohlc,
            sessions,
            spec.params,
            event_times_ms,
            asian_ranges,
            dxy_ohlc=dxy_ohlc,
        )
    return fn(ohlc, sessions, spec.params, event_times_ms, asian_ranges)
