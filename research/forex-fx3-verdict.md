# Forex FX3 Verdict — Event Spike Fade (H11b-4)

*Generated 2026-06-14 07:00 UTC*

**Config hash:** `6eaf09bf78b0d905`

## Frozen recipe

| Parameter | Value |
| --------- | ----- |
| Pairs | EURUSD + GBPUSD (H11c-3) |
| Timeframe | 1h |
| Events | Tier 2+3 (USD/EUR/GBP) |
| Spike window | 30 min |
| Fade entry | 60 min post-event |
| Target | 50% spike retrace |
| Min spike | 5 pips |
| Flat | 21:00 UTC |

## Gate result: **PASS** (3/3 windows)

- **W1-oldest:** PASS
- **W2-mid:** PASS
- **W3-newest:** PASS

## Go/no-go

**GO for FX4 demo infrastructure** — event-only, ~6.8 trades/month.
SCM v1 remains parked. Demo uses `active_strategy: event_spike_fade` only.