**EXECUTION DOCUMENT · CONFIDENTIAL**

**Aegis - Development Task List & Milestone Tracker**

*Version 1.0 · June 2026 · Companion to Aegis Concept.md v3.0*

How to use this document: work top to bottom, check tasks off as they complete, and never start a phase before the previous milestone's gate criteria are ALL met. Update the KPI log (Section 5) every Sunday. Gates are pass/fail - "almost" is fail.

**Forex track (parallel, demo/paper only):** see `Aegis Forex Tasks & Milestones.md` — Event Spike Fade (H11c-3). Independent gates (FX0–FX8).

**Intraday track (parallel, paper only):** see `Aegis Intraday Tasks & Milestones.md` — Strategy C day momentum + D scalp. Independent gates (ID0–ID5).

**Fly.io (24/7):** `aegis-collector` (sin) — scanner, ingest, forex paper, intraday paper, Telegram `/commands`, HTML daily summary. `aegis-testnet-soak` — M4 soak (→ Jun 18). **Do not** run local `com.aegis.telegrambot` while Fly is polling.

---

# **1 Milestone Overview**


| **ID** | **Milestone**                      | **Target**  | **Gate (all must hold)**                                                                                              | **Status** |
| ------ | ---------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------- | ---------- |
| M0     | Dev environment ready              | Week 1      | Repo, config, secrets handling, CI test runner all working                                                            | ☑ Jun 11   |
| M1     | Data layer live + scanner logging  | Week 3      | 72h uninterrupted collection; candles reconcile vs exchange UI; scanner flags in SQLite                               | ☑ Jun 17   |
| M2     | Math engine validated              | Week 6      | All unit tests pass incl. synthetic-data tests for every pillar (Concept §9)                                          | ☑ Jun 11   |
| M3     | Backtest gates passed              | Week 8      | Walk-forward 2020-2026: ≥300 trades, expectancy 90% CI > 0 net of full cost model, max DD inside Monte Carlo envelope | ☐          |
| M4     | Risk engine + testnet execution    | Week 12     | 20+ testnet spread trades; leg-2-miss drill passed; breaker drill passed                                              | ⏳ Jun 18   |
| M5     | **PAPER TRADING STARTS**           | Month 3     | M1-M4 complete; paper config frozen; review ritual scheduled                                                          | ⏳         |
| M6     | Paper gates passed                 | Month 5     | ≥8 weeks, ≥40 trades, expectancy CI consistent with backtest, slippage within model                                   | ☐          |
| M7     | Strategy B LIVE (RM400-500)        | Month 5-6   | M6 passed; capital deposited; kill-switch values configured from MC calibration                                       | ☐          |
| M8     | RM2,000 equity + Strategy A review | Month 10-14 | Contributions on schedule; A's 3-gate promotion check (Concept §7) evaluated                                          | ☐          |
| M9     | RM3,000-5,000 + v2 ML experiments  | Month 15+   | Live expectancy CI > 0 over 150+ trades; ML trained on candle-level labels only                                       | ☐          |


---

# **2 Task List**

## **Phase 0 - Foundations (Weeks 1-3) → M0, M1**

### P0.1 Project skeleton

- [x] Init git repo `aegis/`, Python 3.12 (via uv), `pyproject.toml`, ruff + pytest configured
- [x] Folder layout: `data/`, `strategy/`, `risk/`, `execution/`, `portfolio/`, `monitor/`, `research/`, `tests/` (src layout)
- [x] Config system (`config.yaml` + env vars). Secrets NEVER in git: `.env` + `.gitignore` from commit one. Bonus: refuses `live` mode until kill switch is MC-calibrated
- [x] Structured logging (JSON lines) with rotation - every module logs through it
- [x] GitHub Actions CI (ruff + pytest) - pushed as `ec8da16`

### P0.2 Exchange abstraction layer (Concept §15, §18)

- [x] Define venue-agnostic interfaces: `MarketData`, `OrderExecutor`, `AccountState` (strategy code may ONLY import these - rule enforced mechanically by `tests/test_core_boundary.py`)
- [x] Implement `KrakenAdapter` (ccxt): candles, balances, order placement stubs (stubs fail loudly until M8 - read-only key stays read-only)
- [x] Implement `HyperliquidAdapter`: candles, order book, signed orders (post-only/IOC), fills, equity, positions (`hyperliquid_trading.py` via ccxt; WebSocket + funding stream land with P2.3 two-leg execution)
- [x] Testnet wallet + Hyperliquid testnet connectivity proven (one manual order placed and cancelled via code) - **passed Jun 11, full perp variant**: `aegis-testnet-check` placed post-only BTC order 54795730660 20% below market, rested open, canceled, zero fills, via authorized API wallet (master key never on dev machine). Account uses **unified mode**: spot USDC margins perps directly (no class transfer exists); equity reader handles both unified and classic payloads

### P0.3 Data layer + persistence

- [x] SQLite schemas: `candles`, `scanner_flags`, `signals` (incl. skipped + reason), `orders`, `fills`, `positions`, `funding_payments`, `slippage_log`, `equity_snapshots`, `regime_labels` - all created day one (commit `9030f1a`)
- [x] 1h + 4h candle ingestion for top 50 Hyperliquid assets and Kraken majors, with gap-detection + backfill on restart (`aegis-ingest`, resume-from-last, closed-bars-only). Jun 11: backfill deepened 30d → 210d with backward extension (existing DBs deepen in place; HL serves ~208d max). *Deploy to Fly.io only AFTER the M1 72h clock completes Jun 13 - a restart mid-window voids the gate*
- [x] Reconciliation script: stored candles vs exchange spot-check (`aegis-reconcile`, random samples, exit 1 on mismatch) - live smoke test clean on both venues

### P0.4 Volume anomaly scanner - LOGGING STARTS DAY ONE (Concept §7)

- [x] CoinGecko client with rate limiting + retry/backoff (top 300 = 2 calls, far under limits) - commit `566d61f`
- [x] Hourly job: hourly volume ESTIMATED from rolling-24h snapshots (free tier has no true 1h volume; raw snapshots stored forever so the estimator is recomputable); rolling 20-day baseline; flag at 3x; 48h min history per coin
- [x] Log ALL flags with full context (price 1h/24h change, on-Kraken availability) and variant tags: `price_up_5`, `price_flat`, `price_down`. Regime label joins the context once P2.2 exists
- [x] Supervised 24/7 collection: `aegis-collect` daemon deployed on Fly.io (`aegis-collector`, sin region, volume-backed SQLite) - hourly scan+ingest, crash alerts, restart policy. Local launchd agents also loaded as redundancy while the Mac is awake. **M1 72h clock started Jun 10 ~16:00 UTC**

### P0.5 Monitoring

- [x] Telegram bot: error/crash alerts (live delivery confirmed). Daily heartbeat with collection stats at 16:00 UTC (midnight MYT) - first summary delivered Jun 10
- [x] Daily summary job: candles/snapshots/flags in 24h (by variant), unfilled gap count, DB size, silent-scanner warning (`aegis-summary` + automatic in collector)

**M0 gate check:** ☑ repo + config + tests run end-to-end (167+ tests, CI green, testnet connectivity proven)
**M1 gate check:** ☑ **PASS Jun 17** — `aegis-m1-check`: 166h snapshot span, 65 hourly batches, 2310 scanner flags, 7200 snapshots/24h. Fly collector redeployed Jun 17 (v10) with intraday + HTML Telegram summary.

## **Phase 1 - Strategy B Research & Math Engine (Weeks 3-8) → M2, M3**

### P1.1 Pairs screening pipeline (Concept §8, §9.2)

- [x] Engle-Granger test wrapper (statsmodels) over all C(50,2) pairs, 6-month window (`strategy/screening.py`, one test per unordered pair, alphabetical dependent leg)
- [x] Benjamini-Hochberg FDR correction across the full scan
- [x] Stability check: relationship holds on 3 non-overlapping 60-day sub-windows
- [x] OU half-life fit; filter to 4h ≤ half-life ≤ 3 days
- [x] Out-of-sample stationarity check on most recent 30 days (excluded from selection)
- [ ] Weekly re-test job + removal logic (close at next |Z|=1.0 touch or time stop) - *needs live position state; wired up with the Phase 2 portfolio loop*
- [x] Unit test: feed random walks → post-FDR survivors = 0; feed synthetic cointegrated pairs → recovered with planted beta ±10% and half-life in range (`tests/test_screening.py`)

### P1.2 Kalman hedge ratio (Concept §9.1)

- [x] Kalman filter beta (hand-rolled 1D filter, dependency-free); rolling-OLS fallback behind same interface (`strategy/kalman.py`)
- [x] Entry-freeze rule: open positions keep entry beta + Z-series; new beta applies to new entries only (frozen on `PairPosition`, tested)
- [x] Unit test: synthetic pair with drifting true beta → Kalman tracks within 0.05, OLS lags (documents why Kalman) (`tests/test_kalman.py`)

### P1.3 Z-score engine (Concept §9.3)

- [x] Rolling Z with window = 4x pair half-life on 1h bars (`strategy/zscore.py`, pure functions shared by backtest + live)
- [x] Per-pair empirical thresholds: entry = 97.5th percentile of |Z| with 1.5 floor, hard stop calibrated alongside (~3.0)
- [x] Time stop at 2x half-life
- [x] Unit test: synthetic OU process → entries fire, >50% reach take-profit before time stop; full exit decision table both directions (`tests/test_zscore.py`)

### P1.4 Sizing engine (Concept §9.4, §10)

- [x] Risk-based sizing: `risk = tier_pct × equity`, notional from stop distance (`risk/sizing.py`)
- [x] Minimum-notional floor check ($10/order HL, per-pair Kraken) → SKIP + log, never round up
- [x] Tier assignment (Passive 0.50% / Mid 0.75% / Aggressive 1.00%) + regime size scaling (50% in trends)
- [x] Max concurrent open risk 3R enforcement (1R ≡ 1% equity; tier mixes accumulate fractionally)
- [x] Unit tests: floor-skip behaviour; risk never exceeds tier under rounding; leverage changes collateral, never risk (`tests/test_sizing_costs.py`)

### P1.5 Cost model (Concept §13)

- [x] Per-trade cost function: fees (0.015%/0.045% HL; 0.25%/0.40% Kraken), funding estimate, slippage allowance (`risk/costs.py`; round trip = 2x(maker+taker) + 2x slippage)
- [x] Entry-threshold check: expected convergence ≥ 2x total round-trip cost
- [x] Verify live fee schedule via API at startup (`execution/fees.py`; wired at Phase 2 portfolio startup)

### P1.6 Backtest (Concept §17 Phase 1)

- [x] Walk-forward harness wired to the same strategy/sizing/cost code paths as live (`backtest/engine.py` - calls the identical M2-validated functions; custom harness instead of Jesse, zero duplicate logic). Weekly re-screen on strictly-prior data, Kalman beta between refits, entry-freeze, removal logic (failed re-test = manage to close, no re-entry). Validated on synthetic OU pairs (positive expectancy required) and random walks (zero trades required)
- [x] Walk-forward 2021-2026, Binance USDT-perp panel via `aegis-download` (HL serves only ~208d so research data comes from Binance archives). **30 majors (Jun 11): ZERO trades in 253 weekly refits** - in-sample EG survivors (up to 54/435 post-FDR) systematically fail stability + OOS. **Widened to 116 symbols / 4.26M hourly candles (Jun 11): funnel diagnostic at era end = 1 survivor (`1INCH/BB`) out of 6,490 pairs tested; 784 post-FDR collapse to 1 OOS pass.** Same story at scale: episodic in-sample relationships, not a tradeable universe. Full 116-symbol walk-forward deferred (expected <<300 trades). **VERDICT: Strategy B cointegration premise dead on 116 assets × 5 years.** Next fork: cross-sectional mean reversion OR Strategy A promotion
- [x] Monte Carlo: 10,000 paths × 300 trades bootstrap → drawdown envelope; kill value = p99 × 1.25 buffer (`backtest/montecarlo.py`; refuses samples < 30 trades)
- [x] Report: go/no-go memo `research/2026-06-strategy_b_verdict.md` — M3 **FAILED** (0 trades majors, 1 OOS survivor / 116 alts). Kill switch remains unset until a strategy produces ≥30 trades for MC calibration

### P1.7 Strategy A swing engine (Concept §7 — paper path after B verdict)

- [x] EMA(9/21) cross + RSI(14) < 70 entry logic (`strategy/swing.py`); tier classification (Passive / Mid / Aggressive with anomaly flag)
- [x] Exit logic: 6% TP, 3% SL, EMA cross-back (`evaluate_exit`)
- [x] Walk-forward backtest harness (`backtest/swing_engine.py`, `aegis-backtest-swing`) — EMA+RSI baseline only; anomaly confirmation requires live scanner log (not backtestable). **Jun 11 baseline (BTC/ETH/SOL, 4h): 589 trades, -0.213R expectancy, 66% max DD** — see `research/2026-06-strategy_a_baseline_backtest.md`. Precompute fix: indicators computed once per symbol (~6s vs minutes)
- [x] Unit tests: indicator math, entry tiers, exit priority (`tests/test_swing.py`)
- [x] Paper signal pipeline: join live scanner flags from SQLite → log simulated fills (`data/scanner_join.py`, `portfolio/paper_swing.py`, `execution/paper.py`; AGGRESSIVE tier fills, PASSIVE logged as baseline)

### P1.5 (completed at startup hook)

- [x] Live fee verification module (`execution/fees.py`) — fetches HL + Kraken schedules, warns on >20% drift, **refuses live mode** if mismatched. Wire into portfolio loop at Phase 2 startup

**M2 gate check:** ☑ all math unit tests green ☑ synthetic-data validations documented
**M3 gate check (Strategy B cointegration):** ☒ FAILED — documented in `research/2026-06-strategy_b_verdict.md`. Phase 1 complete; proceed to Strategy A paper research + Phase 2 infrastructure

## **Phase 2 - Risk Engine & Execution (Weeks 8-12) → M4**

### P2.1 Risk engine integration (Concept §10)

- [x] Pearson correlation guard on returns (min 90 obs): trigger 0.85 / release 0.75, collapse to shared 1R bucket (`risk/correlation.py`)
- [x] Slippage gate: cancel if calculated slippage > 0.08% of notional (`risk/slippage.py`)
- [x] Daily circuit breaker: halt at 3x max single-trade risk, manual-resume flag (`risk/breakers.py`, `risk/engine.py`)
- [x] Account kill switch at MC-derived threshold (from P1.6), permanent until manual restart (`risk/breakers.py`)
- [x] Breaker drill in simulation: force a breach, verify halt + clean state (`tests/test_risk_phase2.py`)

### P2.2 Regime detector (Concept §6)

- [x] Per-asset regime: EMA(9/21), ADX, 200MA, BB width on 4h close (`strategy/regime.py`, `tests/test_regime.py`)
- [ ] Global BTC regime override - may only REDUCE risk
- [ ] Intraday volatility confirmation (1h realized-vol spike) that can cut size without waiting for 4h close
- [x] Rule: regime flips never widen existing stops (enforced in exit logic; sizing factor helper for Strategy B)
- [x] Regime labels logged per asset per 4h candle into `regime_labels` (paper cycle via `regime_snapshot` + `upsert_regime_label`)

### P2.3 Two-leg execution - maker-then-IOC (Concept §8)

- [x] Leg ordering: post-only on more liquid leg first (`execution/spread.py`)
- [x] On fill → IOC on second leg with max-slippage bound
- [x] Miss/violation → immediately flatten leg 1 at market; log full event (`tests/test_spread_executor.py`)
- [ ] Isolated margin on every HL position; native stop orders attached on fill
- [x] Leg-2-miss drill on testnet: deliberately unfillable leg 2 → verify flatten executes within 1s (`aegis-leg2-miss-drill`, SOL+DOGE pair — testnet majors often >3% off oracle; flatten 942ms Jun 11)

### P2.4 Portfolio brain (Concept §5)

- [x] Cycle skeleton: fee verify at startup → regime filter → Strategy A signal logging (`portfolio/brain.py`, `aegis-portfolio`)
- [x] Testnet spread dispatch: risk engine → IOC spread executor → SQLite orders/fills (`portfolio/spread_pipeline.py`, `aegis-testnet-campaign`)
- [x] Equity snapshot per cycle into `equity_snapshots`
- [x] Milestone Telegram notifications (`monitor/milestones.py`; M1/soak/breaker drill)

### P2.5 Testnet campaign

- [x] 20+ full spread trades on Hyperliquid testnet through the complete pipeline (`aegis-testnet-campaign` — **20/20 Jun 11–12**, SOL/DOGE·ARB pairs, 87 fills in SQLite, flat after each cycle)
- [x] Reconcile fills to SQLite after each spread (`spread_pipeline.reconcile_spread_fills`)
- [ ] Reconcile funding payments + P&L vs testnet UI (manual spot-check)
- [ ] 7-day unattended soak test: no crashes, no orphan orders, no unexplained state — **STARTED Jun 11 16:11 UTC** on Fly.io `aegis-testnet-soak` (sin); ends ~**Jun 18**. Day 6/7 — hourly health OK; spread anomalies logged (expected on testnet). Verdict pending.

**M4 gate check:** ☑ 20+ testnet trades reconciled (87 fills, `aegis.sqlite`) ☑ leg-2 drill passed ☑ breaker drill CLI (`aegis-breaker-drill`) ⏳ 7-day soak verdict **Jun 18**

## **Phase 3 - PAPER TRADING (Months 3-5) → M5, M6**

### P3.1 Paper trading setup

- [x] Paper mode: real market data, simulated fills at touch price + modeled slippage + real fee schedule (`execution/paper.py`, `aegis-portfolio` when `mode=paper`)
- [x] Config freeze: parameters locked at backtest values; any change restarts the 8-week clock (`monitor/config_freeze.py`, `--reset-config-freeze`)
- [x] Strategy A paper pipeline live in parallel (signals + simulated fills logged, zero capital implications)
- [x] Daily summary includes paper equity + open positions (`aegis-summary` / Telegram) — **HTML formatted** Jun 17; includes swing + intraday + forex blocks
- [x] Weekly KPI auto-report (`aegis-kpi-report`, launchd Sunday 17:00 UTC; forex KPI on Fly collector Sunday 17:00 UTC)

### P3.1b Intraday track (parallel — see `Aegis Intraday Tasks & Milestones.md`)

- [x] Strategy C engine + paper pipeline (`strategy/intraday_momentum.py`, `portfolio/intraday_pipeline.py`)
- [x] Fly collector sidecar: 60s loop (`AEGIS_INTRADAY_ENABLED=1`, deployed Jun 17)
- [x] Intraday scorecard in unified daily Telegram summary + `/intraday` command
- [ ] ID4 Phase 1 proof (4 weeks ≥$50/wk + 5/7 win days)

### P3.2 Weekly review ritual (every Sunday, 30 min)

- [ ] Fill KPI log row (Section 5)
- [ ] Reconcile: every signal → order → fill → position → P&L chain complete in SQLite
- [ ] Compare live slippage vs modeled; flag if worse 2 weeks running
- [ ] Review skipped trades (floor checks, gates) - are skips behaving as designed?
- [ ] Review scanner log growth + variant performance (builds Strategy A's case)

### P3.3 Paper exit criteria (M6 gate)

- [ ] ≥8 weeks elapsed, ≥40 Strategy A paper trades
- [ ] Paper expectancy 90% CI overlaps backtest CI (consistency, not just positivity)
- [ ] Simulated slippage assumptions validated against observed spreads
- [ ] Zero unexplained crashes or reconciliation breaks in final 4 weeks

**M5 gate check:** ⏳ paper mode running (Fly + local launchd) ☐ config frozen verified ☐ review ritual on calendar (blocked on M4 soak Jun 18)
**M6 gate check:** ☐ all P3.3 boxes ☐ written go-live decision memo (one page: what the data says)

## **Phase 4+ - Live Operations (tracked at milestone level)**

- [ ] **M7:** Deposit RM400-500 → Strategy B live. First 4 weeks: minimum size only, no parameter changes. Contribution schedule starts (RM100-150/month, health-gated per Concept §14)
- [ ] **M8:** At RM1,500-2,000 equity: evaluate Strategy A's 3-gate promotion (equity ✓ / 3-month paper CI > 0 ✓ / anomaly variant independently positive ✓). Promote or extend paper - both are valid outcomes
- [ ] **M9:** At RM3,000-5,000: begin v2 ML experiments (candle-level labels; Kronos logged-only, never gating Strategy B). Quarterly withdrawal cadence begins
- [ ] **M10 (horizon):** 12+ months live, expectancy CI > 0 over 150+ trades, ~RM20k equity → open multi-market evaluation (IBKR pairs, Concept §15)

---

# **3 Projection Checkpoints**

Measured from go-live (M7). Contribution plan: RM500 start (rounded), +RM150/month. Compare actual equity against this band - falling below the 0% line means contributions are off schedule or losses exceed realistic bounds; investigate either way.


| **Months after go-live** | **0% return** | **+1%/month** | **+2%/month** | **Actual** |
| ------------------------ | ------------- | ------------- | ------------- | ---------- |
| 3                        | RM950         | RM975         | RM1,000       |            |
| 6                        | RM1,400       | RM1,460       | RM1,525       |            |
| 9                        | RM1,850       | RM1,960       | RM2,080       |            |
| 12                       | RM2,300       | RM2,470       | RM2,650       |            |



| The plan reaches Strategy A's promotion capital (~RM2,000) around month 9-12 after go-live |
| ------------------------------------------------------------------------------------------ |
| EVEN AT ZERO RETURN. The bot's job is proving expectancy; the schedule's job is growing    |
| capital. Do not let a good month accelerate the schedule or a bad month panic it.          |


---

# **4 Goal Definitions (what success means at each stage)**


| **Stage**       | **Goal is...**                                                                          | **Goal is NOT...**           |
| --------------- | --------------------------------------------------------------------------------------- | ---------------------------- |
| Build (M0-M4)   | Every math pillar unit-tested; execution drills passed                                  | Speed of completion          |
| Paper (M5-M6)   | Live behaviour consistent with backtest; clean reconciliation                           | Paper profit                 |
| Live yr 1 (M7+) | Expectancy CI > 0 over 150+ trades; contributions on schedule; zero overridden breakers | Monthly income               |
| Scale (M8-M9)   | Strategy A promoted on evidence; risk discipline unchanged at higher equity             | Hitting a projected % return |


---

# **5 Weekly KPI Log**

One row per week, every Sunday. (First rows during paper trading.)


| **Week of** | **Mode** | **Equity (RM)** | **Trades (wk)** | **Trades (cum)** | **Win rate** | **Expectancy ±CI (R)** | **Max DD %** | **Slippage vs model** | **Scanner flags (cum)** | **Uptime %** | **Gates breached** | **Notes** |
| ----------- | -------- | --------------- | --------------- | ---------------- | ------------ | ---------------------- | ------------ | --------------------- | ----------------------- | ------------ | ------------------ | --------- |
| 2026-06-17 | paper | — | 0 | 0 | — | — | — | — | 2310 | Fly OK | 0 | M1 PASS; M4 soak d6/7; intraday ID2 live on Fly; Strategy A paper local launchd |


**Standing rules for the log:**

- Expectancy is always reported with its CI. A point estimate alone is banned from this document.
- "Gates breached" includes breaches that *should* have fired and didn't - those are bugs, the worst kind.
- If two consecutive weeks show slippage worse than model, halt scaling decisions until the cost model is re-fit.

---

# **6 Risks to This Plan (execution-level)**

- **Scope creep:** the single biggest threat. Strategy A improvements, ML ideas, and dashboards are all FORBIDDEN before M6. Write ideas in a `parking-lot.md`, do not build them.
- **Gate erosion:** "7 of 8 weeks is basically 8" is how accounts die. Gates are binary.
- **Silent data rot:** the scanner log only has value if it runs continuously - its gap-free operation is a weekly KPI from week 1.
- **Parameter fiddling during paper:** any parameter change restarts the 8-week paper clock. This rule has no exceptions; it is the only thing that makes the paper result mean anything.
- **Timeline pressure:** if a phase runs long, the phase was mis-estimated - the gate does not move. Month 5-6 go-live is a target, not a promise.

