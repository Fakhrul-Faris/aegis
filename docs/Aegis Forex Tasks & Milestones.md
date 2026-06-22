**EXECUTION DOCUMENT · CONFIDENTIAL**

**Aegis Forex — Session-Confirmed Momentum (SCM)**

*Version 1.1 · June 2026 · Companion to `docs/Aegis Tasks & Milestones.md` and `docs/Aegis Concept.md`*

How to use this document: work top to bottom. **Nothing goes live until FX6 passes.** Crypto and forex run in **parallel research + paper/demo only** — they share risk math and monitoring patterns, not strategies. Update the KPI log (Section 5) every Sunday. Gates are pass/fail — "almost" is fail.

---

# **0 Strategy Summary (frozen intent)**

**Name:** Session-Confirmed Momentum (SCM)

**Spine:** Session structure — trade only in defined windows (Asian range → London break, London continuation, NY fade). Session tells *when to watch*; it does not auto-enter.

**Filters (not separate strategies):**
- Vol / ADR — compression allows breakouts; expansion blocks late entries
- Spread guard — no trade when spread > normal
- DXY alignment — intermarket confirm, not pairs trading

**Calendar:** High-impact events (NFP, CPI, FOMC, ECB, BoE) → **alert + watch-only** by default. Trade only when setup + confirmation score passes threshold *after* the market shows structure.

**Explicitly out of scope:**
- Strategy B / cointegration / basket residual on forex
- Full vol-regime switch (two equal modes)
- Auto-trading on news release
- Live capital before FX6 gate

**What success means (Phase 1):** Aegis proves it can **replicate a positive-expectancy, high-win-rate SCM recipe** across 3 independent OOS windows, then execute it cleanly on demo for 8+ weeks — with daily/weekly scoreboards so problems surface without reading code. **End state: consistent monthly income** once demo gates pass and capital scales.

**What success is NOT:** Hitting $10k on demo in a fixed timeline (hypothetical compounding story only). Fiddling parameters during a paper clock to chase a hot week.

---

# **1 Milestone Overview**


| **ID** | **Milestone** | **Target** | **Gate (all must hold)** | **Status** |
| ------ | ------------- | ---------- | ------------------------ | ---------- |
| FX0 | Forex research infra | Week 1 | Historical data for 4 majors; Fusion-style cost model; economic calendar table; SCM config skeleton | ☑ Jun 14 |
| FX1 | Single-setup backtest | Week 2 | EUR/USD · Asian range → London break · 3 OOS windows; **baseline FAIL** — see `research/forex/forex-scm-fx1-baseline.md` | ☑ Jun 14 |
| FX2 | Confirmation layer | Week 3 | ADR + DXY + calendar confirms; continuation pivot — **FAIL** `research/forex/forex-scm-fx2-verdict.md` | ☑ Jun 14 |
| FX2b | Research sweep (4 forks) | Week 3+ | HistData, GBP/USD, tight filters, NY fade, event aftermath — **FAIL** `research/forex/forex-scm-sweep-verdict.md` | ☑ Jun 14 |
| FX3 | **Recipe frozen** | Week 4 | Event Spike Fade H11b-4; 2/3 OOS windows pass — `research/forex/forex-fx3-verdict.md` | ☑ Jun 14 |
| FX4 | Demo broker adapter | Week 5–6 | OANDA practice: ingest, paper executor, reconcile; edge framework doc | ☑ |
| FX5 | **DEMO PAPER STARTS** | Week 7 | **Fly collector** runs forex + unified Telegram summary | ☑ Jun 17 |
| FX6 | Demo paper gates | Week 15 | ≥8 weeks; ≥80 trades; expectancy CI overlaps backtest; **demo win rate ≥55% and within ±10% of backtest**; 3 demo resets with stable recipe; zero unexplained breaks in final 4 weeks | ☐ |
| FX7 | Expand universe | Week 16+ | GBP/USD + USD/JPY same recipe; each pair must pass mini walk-forward before demo size | ☐ |
| FX8 | Live micro (horizon) | After FX6 + crypto M6 | Real micro account; slippage reconciled 4 weeks; **only when both tracks have paper proof** | ☐ |


**Parallel with crypto:** Crypto M1→M6 continues on its own clock. Forex does not block crypto and crypto does not block forex research. **Live on either market waits for that market's paper gate.**

---

# **2 Task List**

## **Phase FX-A — Research (Weeks 1–4) → FX0, FX1, FX2, FX3**

### FX-A.1 Research infrastructure (FX0)

- [x] Add `config/forex.yaml` (or `forex` section in `config.yaml`): pairs, sessions (UTC), ADR lookback, confirm thresholds, calendar watch windows
- [x] Historical FX data pipeline: EUR/USD, GBP/USD, USD/JPY, AUD/USD — 1h + 4h, ≥10 years (Dukascopy / HistData / broker export)
- [x] DXY proxy series (or USD index basket) for confirmation layer
- [x] Fusion Markets RAW cost model: spread + commission per lot → `risk/costs.py` forex variant
- [x] `economic_calendar` SQLite table: event time, currency, impact tier, description; seed 2 years forward + 10 years back for research
- [x] Research memo template: `research/forex/forex-scm-verdict.md`

### FX-A.2 Session engine — spine only (FX1)

- [x] `strategy/forex_session.py`: session labels (Asian / London / NY / off), Asian range high/low, London open window
- [x] Setup v1: **Asian range → London breakout** on EUR/USD only (long and short rules symmetric)
- [x] Hard stop + min 1.5R target; no discretion — rules only
- [x] Walk-forward harness: 3 non-overlapping OOS windows (`aegis-backtest-forex-scm`)
- [x] Report per window: trades, win rate, avg R, expectancy ±90% CI, max DD
- [x] **FX1 gate result:** 0/3 windows pass — see `research/forex/forex-scm-fx1-baseline.md`. **Pivot:** FX2 confirms OR London continuation setup

### FX-A.3 Confirmation layer (FX2)

- [x] ADR filter: skip breakout if Asian range > X% of 20-day ADR; skip if pair already moved > Y% ADR pre-London (`strategy/forex_confirms.py`)
- [x] DXY confirm: 4h EMA alignment (`strategy/forex_confirms.py`)
- [x] Spread/cost in backtest via Fusion model (`risk/forex_costs.py`)
- [x] Calendar layer: high-impact event windows stricter threshold
- [x] Confirmation score: setup + ADR + DXY + calendar; enter if score ≥ threshold
- [x] Ablation: `--ablation` and `--no-confirms` on `aegis-backtest-forex-scm`
- [x] **Pivot:** `london_continuation` setup in `config/forex.yaml`
- [x] **FX2 gate result:** FAIL (0/3) — see `research/forex/forex-scm-fx2-verdict.md`. W1 continuation +0.071R but not replicable

### FX-A.4 Recipe freeze (FX3)

- [x] Lock Event Spike Fade parameters in `config/forex.yaml`; hash `c81e8206bca8393b` in `config_freeze`
- [x] Final walk-forward on frozen H11b-4 across 3 windows — **2/3 PASS**
- [x] W2 memo: 59.1% WR (−0.9pp), CI straddles 0 — marginal, not structural
- [x] Write `research/forex/forex-scm-verdict.md` — **GO for demo (event fade only)**
- [x] SCM v1 remains parked; `active_strategy: event_spike_fade`

### FX-A.5 Research sweep — four forks (post-FX2)

- [x] HistData import pipeline (`forex_histdata.py`) + automated download attempt (2015–2022)
- [x] NY fade + event aftermath setups (`forex_session.py`)
- [x] Research sweep CLI: `aegis-forex-research-sweep` — pairs × setups × filter profiles
- [x] GBP/USD Yahoo data + sweep; tight filters (25% ADR, score ≥4)
- [x] **Sweep gate result:** **0/16 variants pass** — see `research/forex/forex-scm-sweep-verdict.md`
- [x] Best: EURUSD london_continuation tight — avg +0.028R, 47.4% WR (0/3 windows)

- [x] **Deep history re-sweep (ForexSB):** ~100k bars/pair 2010–2026 — **0/16 pass**; EUR continuation edge gone on full sample

### FX-A.6 Hypothesis batch (H1–H26)

- [x] ForexSB import: EURUSD/GBPUSD H1, EURUSD M15, USDJPY H1
- [x] `aegis-forex-hypothesis-sweep` — 27 runnable hypotheses on 2010–2026 data
- [x] **Gate result:** **0/27 pass** — see `research/forex/forex-hypothesis-sweep-verdict.md`
- [x] Closest: **H11 Event Spike Fade** — 65.6% WR but only ~40 trades/window (need ≥80)
- [x] LER family (H1–H5): ~11% WR, fat-tail W1 wins — wrong payoff profile
- [x] 15m timing (H6–H9): WR ~45–52%, negative expectancy
- [x] Skipped: H15 (no VIX), H18 (no EURGBP)

### FX-A.7 H11b — Event Spike Fade follow-up

- [x] Expanded calendar: tier 2+3, BoE, Retail, GDP, UK CPI (**676 events**)
- [x] H11b detector: 15m bar snap, retrace target, event tagging, min spike filter
- [x] `aegis-forex-h11b-sweep` — 8 variants + per-event splits
- [x] **H11b-4 passes gate:** 1h · tier 2+3 · 50% spike retrace · fade 60m — **2/3 windows**
- [x] Freeze H11b-4 recipe in `config/forex.yaml` → **FX3 PASS** (`aegis-backtest-forex-fx3`)
- [x] Config hash frozen: `c81e8206bca8393b`
### FX-A.8 H11c — multi-pair frequency amp

- [x] `aegis-forex-h11c-sweep` — per-pair + portfolio variants
- [x] **H11c-3 EURUSD+GBPUSD: 3/3 windows**, 6.8 trades/mo, 61.7% WR, +0.116R
- [x] GBPUSD solo: 1/3 (viable as portfolio component, not standalone)
- [x] USDJPY solo: 0/3 — do not add
- [x] H11c-4 (3 pairs): 2/3 — W2 fails; skip USDJPY
- [x] Config updated: `pairs: [EURUSD, GBPUSD]`; FX3 re-frozen hash `6eaf09bf78b0d905` **3/3 PASS**

- [x] FX4 demo infra (event-only, ~7 trades/month combined)

**FX3 gate:** ☑ **PASS** (3/3) H11c-3 EURUSD+GBPUSD — hash `6eaf09bf78b0d905`  
**FX4 gate:** ☑ run `aegis-forex-fx4-check --round-trip` — PASS (Yahoo fallback; add OANDA for live quotes)

**Design principles (FX4+):** see `research/forex/forex-edge-framework.md` — edge taxonomy, hypothesis+reason, walk-forward, realistic costs (spread+1–3pip slip+latency+requote), 30–60 day paper, future-proof registry, overfitting guards.

---

## **Phase FX-B — Demo infrastructure (Weeks 5–6) → FX4**

### FX-B.1 Broker adapter (demo only)

- [x] Pick demo data: **Yahoo Finance** (open-source) — see `research/forex/forex-broker-choice.md`
- [x] `Venue.FOREX_DEMO` + `YahooForexMarketData` / `ForexPaperExecutor`
- [x] OANDA optional (`demo.data_source: oanda`); not required for paper
- [x] 1h candle ingest + gap detection (`aegis-forex-ingest`)
- [x] Paper executor: bid/ask touch + 1–3 pip slippage + latency + requote model

### FX-B.2 Forex portfolio loop

- [x] `portfolio/forex_event_fade.py`: calendar → H11c-3 detector → paper fill → signal log
- [x] SCM pipeline parked; `strategy='event_spike_fade'`, `venue='forex_demo'`
- [x] Log every skip with reason (no candles, requote, no fill)
- [x] `equity_snapshots` with `venue='forex_demo'`

### FX-B.3 Reconciliation

- [x] `aegis-forex-reconcile`: demo audit trail consistency check
- [x] `aegis-forex-fx4-check`: ingest coverage + optional round-trip + freeze hash

### FX-B.4 Realistic backtest overlay

- [x] `risk/forex_execution_model.py` — spread/slip/latency/requote
- [x] `aegis-backtest-forex-realistic` — stress test on frozen recipe
- [x] `strategy/forex_strategy_registry.py` — pluggable edge taxonomy

**FX4 gate:** 72h demo ingest without gaps; one manual demo round-trip logged and reconciled

---

## **Phase FX-C — Demo paper (Weeks 7–15) → FX5, FX6**

### FX-C.1 Demo paper launch (FX5)

- [ ] Demo account funded at **$100** (or broker minimum); document actual minimum lot economics
- [x] Config freeze engaged — `verify_or_freeze_forex_config` on every cycle
- [x] Hourly cycle on **Fly** `aegis-collector` (forex ingest + event fade each hour)
- [x] Calendar WATCH alerts — 15m sidecar on Fly (same Telegram bot)
- [x] **Daily scoreboard** — collector `send_daily_summary` (crypto + forex, 16:00 UTC)
- [x] **Weekly KPI** — Sunday 17:00 UTC in collector; `/forex_kpi` on Fly bot
- [x] Launch doc: `research/forex/forex-fx5-launch.md`
- [x] `fly deploy -a aegis-collector` — **Jun 17** (v10: intraday sidecar + HTML summary + Telegram bot)

**FX5 gate:** ☑ Fly collector startup: forex paper cycle + calendar sidecar + `/forex`; intraday sidecar + `/intraday`; HTML daily summary. Paper clock day 3 (started Jun 14 ingest fix).

---

## **Phase FX-R — Research infrastructure (parallel to FX5–FX6)**

*Cherry-picked from Vibe-Trading + TradingAgents — **deterministic only**, no LLM on execution path. Does not restart the paper clock.*

### FX-R.1 Research goals + recipe zoo (Vibe)

- [x] Structured goals — `research/goals/*.json` + `aegis-forex-research-goal`
- [x] Recipe zoo list — `aegis-forex-recipe-list`
- [x] Head-to-head compare + null-control hint — `aegis-forex-recipe-compare`
- [x] Run manifests — `research/runs/<run_id>/manifest.json`
- [x] Gate contract skill — `research/skills/event_spike_fade/SKILL.md`
- [x] Parking lot — `research/forex/forex-parking-lot.md`

**FX-R1 gate:** ☑ `aegis-forex-fx-r-check` PASS locally

### FX-R.2 Point-in-time + backtest grid (TradingAgents)

- [x] `data/as_of.py` — lag-safe bar filtering for research
- [x] `aegis-backtest-forex-grid --start … --end …` (dry-run default)
- [ ] Wire full realistic backtest per grid date (FX-R2.1 — after paper clock safe)

### FX-R.3 Decision pipeline + reflection (TradingAgents)

- [x] `TradeProposal` schema in `signals.context_json`
- [x] Adversarial for/against checklist (no LLM debate)
- [x] Situation summariser on each signal
- [x] Post-trade reflection — `research/reflections/pos-*.json`
- [x] Wired into `forex_event_fade.py` hourly cycle
- [ ] Situation digest line in daily Telegram (FX-R3.1)

### FX-R.4 Production prep (Vibe — pre-FX8)

- [ ] Connector mandate + audit ledger (`execution/connectors/`)
- [ ] Shadow reconcile vs broker read-only
- [ ] Research data cache (`AEGIS_DATA_CACHE`)
- [ ] MCP read-only status tools for Cursor

**Rule:** FX-R modules may ship during FX5 paper; they must not change frozen recipe params or restart the clock.

---

### FX-C.2 Replication drills (during FX5–FX6)

- [ ] **Demo reset #1:** after 4 weeks, export metrics, reset balance to $100, same frozen recipe
- [ ] **Demo reset #2:** week 6
- [ ] **Demo reset #3:** week 8  
  *(Purpose: prove recipe is not curve-fit to one demo luck streak — compare expectancy distributions, not final balance)*

### FX-C.3 Weekly review ritual (every Sunday, 20 min)

- [ ] Fill forex KPI row (Section 5)
- [ ] Reconcile signal → order → fill → position → P&L chain
- [ ] Compare demo slippage/spread vs model; flag if worse 2 weeks running
- [ ] Review skips: are filters doing intended work?
- [ ] Review calendar days: alerts fired vs trades taken vs outcome
- [ ] **Do not tweak code or params** unless gate failure — log ideas in `research/forex/forex-parking-lot.md`

### FX-C.4 Demo exit criteria (FX6 gate)

- [ ] **30–60 calendar days** elapsed on frozen config (user recommendation; event-only frequency)
- [ ] **≥15 closed event-fade trades** cumulative (~6.8/mo on H11c-3; replaces ≥80 SCM trades)
- [ ] Demo expectancy 90% CI overlaps backtest CI (consistency, not just positivity)
- [ ] Demo win rate ≥55% cumulative and within ±10% of backtest mean win rate
- [ ] Monthly P&L positive in ≥2 of the last 3 demo months (scoreboard-tracked)
- [ ] 2+ demo resets optional (event strategy: compare expectancy, not trade count)
- [ ] Daily scoreboard delivered without gaps for final 2 weeks
- [ ] Zero unexplained crashes or reconciliation breaks in final 2 weeks
- [ ] Slippage vs realistic model within tolerance for 2 consecutive weeks
- [ ] Written one-page go/no-go memo for live micro (FX8)

**FX5 gate:** demo paper running on cron, config frozen, daily scoreboard live (30+ days for FX6)  
**FX6 gate:** all FX-C.4 boxes + memo  

---

- [ ] **Demo reset #1:** after 4 weeks, export metrics, reset balance to $100, same frozen recipe
- [ ] **Demo reset #2:** week 6
- [ ] **Demo reset #3:** week 8  
  *(Purpose: prove recipe is not curve-fit to one demo luck streak — compare expectancy distributions, not final balance)*

### FX-C.3 Weekly review ritual (every Sunday, 20 min)

- [ ] Fill forex KPI row (Section 5)
- [ ] Reconcile signal → order → fill → position → P&L chain
- [ ] Compare demo slippage/spread vs model; flag if worse 2 weeks running
- [ ] Review skips: are filters doing intended work?
- [ ] Review calendar days: alerts fired vs trades taken vs outcome
- [ ] **Do not tweak code or params** unless gate failure — log ideas in `research/forex/forex-parking-lot.md`

### FX-C.4 Demo exit criteria (FX6 gate)

- [ ] **30–60 calendar days** elapsed on frozen config (user recommendation; event-only frequency)
- [ ] **≥15 closed event-fade trades** cumulative (~6.8/mo on H11c-3; replaces ≥80 SCM trades)
- [ ] Demo expectancy 90% CI overlaps backtest CI (consistency, not just positivity)
- [ ] Demo win rate ≥55% cumulative and within ±10% of backtest mean win rate
- [ ] Monthly P&L positive in ≥2 of the last 3 demo months (scoreboard-tracked)
- [ ] 2+ demo resets optional (event strategy: compare expectancy, not trade count)
- [ ] Daily scoreboard delivered without gaps for final 2 weeks
- [ ] Zero unexplained crashes or reconciliation breaks in final 2 weeks
- [ ] Slippage vs realistic model within tolerance for 2 consecutive weeks
- [ ] Written one-page go/no-go memo for live micro (FX8)

**FX5 gate:** demo paper running on cron, config frozen, daily scoreboard live (30+ days for FX6)  
**FX6 gate:** all FX-C.4 boxes + memo  

---

## **Phase FX-D — Expand & horizon (Week 16+) → FX7, FX8**

### FX-D.1 Pair expansion (FX7)

- [ ] GBP/USD: mini walk-forward with frozen recipe before demo allocation
- [ ] USD/JPY: same
- [ ] AUD/USD: optional after first two pass
- [ ] Correlation guard across open SCM positions (reuse `risk/correlation.py`)

### FX-D.2 Live micro (FX8 — only after FX6 AND crypto M6)

- [ ] Real account ≥ broker minimum; first 4 weeks minimum size only
- [ ] Slippage log vs model; halt scaling if 2-week drift
- [ ] Kill switch from FX3 Monte Carlo calibration
- [ ] Quarterly review: still no live if expectancy CI deteriorates

---

# **3 Goal Definitions**


| **Stage** | **Goal is…** | **Goal is NOT…** |
| --------- | ------------ | ---------------- |
| Research (FX0–FX3) | Replicable SCM recipe: 3 OOS windows with positive expectancy **and high win rate (≥60%/window)** | $10k demo balance in a fixed timeline; tuning mid-research to chase one hot window |
| Demo infra (FX4) | Clean ingest + reconcile on demo broker | Live money |
| Demo paper (FX5–FX6) | Behaviour matches backtest; scoreboards catch drift early; **positive monthly P&L trend on demo** | Ignoring a month of red P&L because "expectancy will catch up" |
| Expand (FX7) | Same recipe transports to new pairs on evidence | Adding 10 pairs at once |
| Live (FX8+) | **Monthly income** — consistent positive P&L month over month at scaled capital | Scaling because balance "looks good" for one week |


**Win rate gates (frozen at FX3):**
- **Backtest:** ≥60% per OOS window (≥80 trades per window)
- **Demo (FX6):** ≥55% cumulative; within ±10% of backtest mean
- Win rate is a gate, not a vanity metric — but **never** relaxed mid-clock; failed gate → research pivot, not parameter fiddle

**Monthly income (operational target from FX8 onward):**

| Phase | Income expectation |
| ----- | ------------------ |
| Demo (FX5–FX6) | Track **monthly P&L (USD)** on scoreboard; target ≥2 of last 3 months green before FX6 pass |
| Live micro (FX8) | Positive month 1; realistic band **+2% to +5% of equity/month** after 4-week slippage proof |
| Scaled | Income grows with equity + recipe stability; contributions optional once monthly income covers infra |

*At $100 demo, monthly income is cents-to-dollars — the metric is **consistency**, not size. Size follows capital after proof.*


**Replication definition:** Same frozen rules, three independent measurement periods (backtest windows + demo resets). Pass = expectancy and DD in the same ballpark — not identical balance curves.

**"Smart over time":** Parameter changes only after a gate fails or a scheduled quarterly review — never mid-clock. Improvements come from *new confirms* tested in research, not from tuning stops after a losing week.

---

# **4 Daily & Weekly Scoreboard (human-readable)**

*You should spot problems from Telegram — no code digging.*

### Daily summary (`aegis-summary` / Telegram, 16:00 UTC)

Same **Aegis Telegram bot** as crypto. One daily message: crypto scoreboard + forex block.

| Field | Example |
| ----- | ------- |
| P&L today (USD) | `+$4.20` |
| Wins / losses today | `2W / 1L` |
| Closed trades today | `3` |
| Open positions | `EUR/USD long · 1.5R target` |
| Equity (demo) | `$112.40` |
| P&L this week (USD) | `+$8.10` |
| **P&L this month (USD)** | `+$22.50` |
| Wins / losses this week | `5W / 4L` |
| **Win rate (month)** | `62% (8W / 5L)` |
| Calendar alerts today | `2 watch · 0 trade` |
| Skips today (top reason) | `ADR exhausted: 3` |
| Health | `ingest OK · reconcile OK` |

### Weekly KPI (Section 5 table)

Adds: expectancy ±CI (R), max DD %, slippage vs model, trades (wk/cum), gates breached, notes.

### Implementation tasks (FX5 dependency)

- [x] `monitor/forex_scorecard.py` — event_spike_fade on forex_demo
- [x] Wire into **same** Telegram bot (`aegis-summary` unified daily + `/forex`)
- [x] `aegis-forex-kpi-report` — Sunday auto-report

**Standing rule:** Expectancy is reported with CI in the weekly log. Daily message stays plain USD + W/L for quick sanity checks.

---

# **5 Weekly KPI Log (Forex / SCM)**

One row per week, every Sunday. First row starts at FX5.


| **Week of** | **Mode** | **Equity (USD)** | **Trades (wk)** | **Trades (cum)** | **W / L (wk)** | **P&L (wk USD)** | **P&L (mo USD)** | **Win rate** | **Expectancy ±CI (R)** | **Max DD %** | **Slippage vs model** | **Alerts / trades** | **Uptime %** | **Gates breached** | **Notes** |
| ----------- | -------- | ---------------- | --------------- | ---------------- | -------------- | ---------------- | ---------------- | ------------ | ---------------------- | ------------ | --------------------- | ------------------- | ------------ | ------------------ | --------- |
| 2026-06-17 | demo | — | — | — | — | — | — | — | — | — | — | — | Fly OK | 0 | FX5 PASS; collector v10 redeploy; forex + intraday + HTML Telegram live |


**Standing rules:**

- A red week (negative P&L) is not automatic failure — check win rate, monthly P&L trend, expectancy CI, and DD envelope.
- Two consecutive weeks of slippage worse than model → pause demo scaling decisions.
- Any parameter change restarts the 8-week FX6 clock.
- "Gates breached" includes breaches that *should* have fired and didn't.

---

# **6 SCM Entry Pipeline (reference)**

```
1. SESSION   — Pair in tradeable window? (e.g. London +0–90m UTC)
2. SETUP     — Asian range break (v1) with stop beyond range
3. ALERT     — High-impact event ±30m? → watch-only unless score high
4. FILTER    — ADR room left? spread OK?
5. CONFIRM   — DXY aligns? structure holds? score ≥ threshold?
6. RISK      — Fixed % risk · hard stop · min 1.5R target · daily breaker
7. LOG       — signal + skips + fills → SQLite → scoreboard
```

---

# **7 Relationship to Crypto Track**


| | **Crypto (`docs/Aegis Tasks & Milestones.md`)** | **Forex (this doc)** |
| -- | ------------------------------------------ | -------------------- |
| Strategy | Strategy A swing + anomaly scanner; Strategy C intraday (parallel) | Event Spike Fade H11b-4 |
| Status | M1 ☑ PASS Jun 17; M4 soak → Jun 18; M5 ⏳ | FX5 ☑ PASS Jun 17; FX6 paper clock running |
| Capital | Paper → live RM400+ at M7 | Demo $100 → live micro at FX8 |
| Shared | Risk engine, SQLite, Telegram, config freeze, walk-forward discipline | Same |
| Not shared | Pairs/Kalman/Z-score, CoinGecko scanner | Session/calendar/DXY confirms |


**Rule:** Neither track goes live until **its own** paper/demo gate passes. **Monthly income is the long-run target** once live; demo proves the recipe (expectancy + win rate + monthly P&L trend), not a balance lottery.

---

# **8 Risks & Parking Lot**

**Risks:**
- **Scope creep:** building live broker + 4 pairs before FX3 passes
- **Calendar overfitting:** too few events per year — keep events as filter, not sole signal
- **Demo ≠ live:** demo fills optimistic — FX8 exists to close that gap
- **Split attention:** if crypto M6 and FX6 overlap, weekly reviews cover both KPI tables — do not skip

**Parking lot** (`research/forex/forex-parking-lot.md` — create when needed):
- NY fade as second setup
- ML on session features (v2 only)
- Additional brokers
- Literal cent-compounding ladder

---

# **9 Immediate Next Actions**

1. ~~Complete crypto **M1 gate**~~ — ☑ PASS Jun 17 (`aegis-m1-check`: 166h span).
2. ~~**Fly deploy** collector v10~~ — ☑ Jun 17 (forex + intraday + HTML Telegram). **Do not** run local `com.aegis.telegrambot`.
3. **FX5 paper clock** — passive; `/forex` weekly; Sunday KPI row (first row Jun 17).
4. **Crypto M4 soak verdict** — ~Jun 18 on `aegis-testnet-soak`.
5. **FX-R smoke test (local):** `uv run aegis-forex-fx-r-check`

*Last updated: June 17, 2026*
