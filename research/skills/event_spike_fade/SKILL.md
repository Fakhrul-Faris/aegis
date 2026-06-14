# Event Spike Fade H11c-3 — gate contract (FX-R)

**Recipe ID:** `event_spike_fade`  
**Config hash:** `6eaf09bf78b0d905` (frozen Jun 2026)  
**Edge type:** #4 information / sentiment

## Hypothesis

After tier 2–3 USD/EUR/GBP releases, the initial 30m spike mean-reverts ~50% within 60m.

## Falsifier

2/3 OOS windows fail expectancy CI or win-rate gate on frozen params.

## Acceptance criteria (FX6)

- 30–60 calendar days on frozen config
- ≥15 closed trades cumulative
- Win rate ≥55%, within ±10% of backtest mean
- Expectancy 90% CI overlaps backtest CI
- ≥2 of last 3 months P&L positive

## Decision pipeline stages

1. **Context** — calendar event, OHLC, equity, open positions
2. **Adversarial** — for/against checklist (no LLM)
3. **Approver** — config freeze + confirm score
4. **Executor** — `ForexPaperExecutor` with Fusion cost model

## Research commands

```bash
aegis-forex-recipe-list
aegis-forex-recipe-compare event_spike_fade scm --null-control
aegis-backtest-forex-grid --start 2024-01-01 --end 2024-06-30
aegis-forex-fx-r-check
```
