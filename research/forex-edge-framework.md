# Forex edge framework — design principles (FX4+)

Every forex strategy in Aegis must declare its edge type, hypothesis, and validation path before demo allocation.

## 1. Edge taxonomy

| # | Edge type | Mechanism | Aegis status |
| - | --------- | --------- | ------------ |
| 1 | Statistical / mean reversion | Fade stretched prices to fair value | LER family (H1–H5) **parked** — ~11% WR |
| 2 | Momentum / trend | Ride session or macro direction | SCM v1 **parked** — 0/16 sweep, 0/3 FX2 |
| 3 | Microstructure | Spread, liquidity, order-flow asymmetry | **not pursued** (no tick data in FX0) |
| 4 | Information / sentiment | Trade predictable reaction to scheduled news | **active** — Event Spike Fade H11c-3 |

**Frozen recipe (FX3):** H11c-3 Event Spike Fade on EURUSD + GBPUSD. Edge = **#4 information/sentiment** — fade the initial post-event spike after tier 2–3 calendar events.

## 2. Hypothesis with reason (required)

Before any new recipe enters walk-forward:

- **Hypothesis:** one sentence testable claim.
- **Reason:** why the market should still pay for it (participant behaviour, not curve shape).
- **Falsifier:** what observation would park it.

**H11c-3 example:**
- *Hypothesis:* After tier 2–3 USD/EUR/GBP releases, the first 30m spike mean-reverts ~50% within 60m.
- *Reason:* Liquidity providers widen then mean-revert; fast money overshoots on headline vs revision.
- *Falsifier:* 2/3 OOS windows fail expectancy CI or WR gate.

## 3. Walk-forward validation

- Research uses `_auto_windows()` — three non-overlapping OOS slices on chronological data.
- FX3 gate: frozen config hash + 3/3 windows (event gate: ≥30 trades, ≥55% WR, CI lower > 0).
- **No in-sample tuning after seeing OOS results** — new variant = new hypothesis ID.

## 4. Realistic backtest (not mid-price fantasy)

`risk/forex_execution_model.py` layers on Fusion spread + commission:

| Cost layer | Default | Notes |
| ---------- | ------- | ----- |
| Spread | Fusion RAW per pair | Bid/ask, not mid |
| Slippage | 1–3 pips per fill | Worst-case tier for stress; 1.5 pip mean for base |
| VPS latency | 200 ms (fly.io) | Quote stale → worse fill |
| Event volatility | spread × 2.5 | Near calendar events |
| Requotes | 8% base, 25% in event window | Trade skipped, logged |

CLI: `aegis-backtest-forex-realistic` — same frozen recipe, execution stress overlay.

## 5. Paper trade live (30–60 days)

User recommendation adopted for FX5–FX6 (replaces 8-week / ≥80-trade SCM gate for event-only frequency):

- **Duration:** 30–60 calendar days on frozen config.
- **Trades:** ≥15 closed event-fade trades cumulative (~6.8/mo × 2 pairs).
- **Behaviour:** expectancy CI overlaps backtest; WR within ±10% of backtest mean.
- **Monthly P&L:** ≥2 of last 3 months green before FX6 pass.

## 6. Future-proof infra

- **Pluggable strategies:** `strategy/forex_strategy_registry.py` — edge type + validation contract per strategy.
- **Config freeze:** `monitor/forex_config_freeze.py` — hash drift blocks silent retuning.
- **Research vs demo DB:** `venue=forex` (history) vs `venue=forex_demo` (live ingest).
- **Adaptation rule:** new confirms/hypotheses tested in research fork; production recipe changes only after gate failure or quarterly review.

## 7. Overfitting guards

| Risk | Mitigation |
| ---- | ---------- |
| Parameter fit to one window | 3 OOS windows + frozen hash |
| Fit to noise not structure | Hypothesis + reason doc before sweep |
| Demo luck streak | 30–60 day paper + optional demo resets |
| Mid-clock tuning | Config freeze; param change restarts paper clock |
| Execution optimism | Realistic backtest + slippage log vs model in demo |

Walk-forward and out-of-sample validation do not *guarantee* future edge — they raise the bar for believing we learned signal, not noise.
