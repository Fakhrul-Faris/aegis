**STRATEGY DOCUMENT · CONFIDENTIAL**

**Autonomous Crypto Trading System**

Multi-strategy, self-learning bot · Staged capital plan · Luno · Kraken · Hyperliquid

*Version 3.0 · June 2026 · Personal Reference / Investor Overview / Technical Spec*

*v3.0 changes: unified risk-based sizing, verified fee schedules, Monte Carlo-derived kill thresholds, hardened pairs selection (FDR + half-life + Kalman beta), z-unit spread stops, maker-then-IOC execution, regime contradictions resolved, ML deferred to v2, Strategy-B-first rollout, contribution-based capital plan, multi-market evolution path.*

# **1 Executive Summary**

This document describes the architecture, strategy logic, mathematical foundations, and capital plan for an autonomous cryptocurrency trading system built by a solo developer. The system manages a single USDT pool across two strategies - a swing momentum strategy on Kraken and a statistical arbitrage (pairs trading) strategy on Hyperliquid perpetual futures - governed by a unified risk engine, a market regime detector, and (in v2) an adaptive learning layer.

**The rollout is staged, not simultaneous.** Strategy B (pairs trading) goes live first - it is the only strategy executable at small capital, and it is market-neutral. Strategy A (swing momentum) runs paper-only from day one, collecting the volume-anomaly dataset that cannot be backtested, and goes live only when capital reaches RM1,500-2,000 and its paper expectancy is confirmed positive.


| Core thesis: A developer with coding skills has a structural edge over non-technical retail traders - |
| ----------------------------------------------------------------------------------------------------- |
| not in execution speed (HFT territory), but in strategy iteration speed, backtesting discipline,      |
| and the ability to build infrastructure that adapts. The edge compounds over time.                    |
| Corollary: at small capital, the system's product is DATA and PROOF, not income.                      |


# **2 The Problem asdfghasdfgh**

Retail investors seeking active income from crypto markets face three compounding structural problems:

- **Emotional execution:** humans buy at euphoric peaks and sell at fearful troughs. A systematic bot removes this variable entirely.
- **Time dependency:** crypto trades 24/7. No human can monitor this effectively. A bot never sleeps, fatigues, or misses a 3am breakout.
- **Capital constraints:** without significant capital, returns are numerically small AND fixed costs (exchange minimums, transfer fees, infrastructure) consume a large fraction of the account. The levers available to a small account are strategy quality, cost discipline, and a realistic contribution plan.

Most retail crypto bots also apply a single fixed strategy regardless of market conditions. A momentum strategy in a sideways market generates false signals. A mean-reversion strategy can be run in most conditions but needs size discipline in strong trends. The fix is regime-aware sizing and strategy selection - a core feature of this system.

# **3 The Solution - Staged Two-Strategy System asdfghasdf**

An autonomous Python-based trading system. Both strategies are built; they go live in stages.

## **Strategy B - Statistical Arbitrage / Pairs Trading (Hyperliquid) - LIVE FIRST**

- **What:** a Kalman-filtered hedge ratio defines the spread between two cointegrated assets. When the spread's Z-score exceeds an empirically calibrated threshold (~2.0), the bot enters a market-neutral spread position.
- **Edge:** market-neutral - profits from convergence regardless of overall market direction. Runs in all regimes with regime-scaled size.
- **Hold time:** hours to 2 days per spread, bounded by a time stop at 2x the pair's mean-reversion half-life.
- **Why first:** executable at small capital (minimum ~$20 notional per spread trade), market-neutral, and fully backtestable from exchange data alone.

## **Strategy A - Swing Momentum (Kraken) - PAPER FIRST, LIVE AT RM1,500+**

- **What:** EMA crossover + RSI filter + volume anomaly scanner on 4h candles across Kraken pairs.
- **Edge hypothesis:** volume anomaly detection identifies coins under accumulation before price fully reflects the move. This is a HYPOTHESIS until live scanner data proves it - historical hourly volume across 300 coins is not available on free data tiers, so the scanner cannot be backtested. It must be paper-traded forward.
- **Hold time:** 1 to 5 days per position.
- **Why later:** at small capital, lot-size rounding and per-pair minimums distort risk; the EMA-cross component alone is a weak, widely-arbitraged signal; the anomaly component needs months of logged data before it earns trust.


| The two strategies are structurally complementary. Strategy A profits in trending markets.  |
| ------------------------------------------------------------------------------------------- |
| Strategy B profits from mean reversion in any market. Strategy B carries the account early; |
| Strategy A is promoted from paper to live only after it proves itself on logged data.       |


# **4 Exchange Architecture**

Three exchanges serve distinct roles. Fee figures below are verified against current public schedules (June 2026) at the volume tier this account will actually occupy.


| **Exchange**           | **Role**                                                                                                                                                                                       |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Luno (Malaysia)        | MYR fiat gateway. SC-licensed. Direct bank transfer, TNG. Convert MYR to USDT and back. No active trading here.                                                                                |
| Kraken (International) | Strategy A venue (paper first). REST + WebSocket API, native conditional orders. Base tier fees: 0.25% maker / 0.40% taker (the lowest tiers require $1M+ monthly volume). Accepts Malaysians. |
| Hyperliquid (DEX)      | Strategy B venue. On-chain perp DEX - no KYC, isolated margin, native stop-loss. Base tier fees: 0.015% maker / 0.045% taker (rebates only at $500M+ volume). Minimum order: $10 notional.     |


## **Capital Flow**

MYR (Luno) → USDT → Hyperliquid wallet (Strategy B) and later Kraken wallet (Strategy A) → USDT profits → back to Luno → MYR.

**Withdraw quarterly, not monthly.** Every hop costs flat fees (Hyperliquid withdrawal: 1 USDC; plus Kraken/Luno withdrawal and network fees). At small account size, a monthly withdrawal loop can consume an entire month's profit. Transfers are batched: contributions go in monthly with at most one hop; profits come out quarterly at most.

# **5 System Architecture**

Six layers, each with a single responsibility:


| **Layer**                | **Responsibility**                                                                                                                                             |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 - Data                 | OHLCV via ccxt (Kraken) and Hyperliquid WebSocket. Volume data from CoinGecko API for the anomaly scanner. ALL scanner output logged to SQLite from day one.   |
| 2 - Regime Detector      | Classifies each traded asset (plus a global BTC regime) as Trending Up / Sideways / Trending Down on every 4h close using ADX + EMA slope + BB width.          |
| 3 - Strategy Engine      | Strategy A: EMA(9/21) + RSI(14) + volume anomaly. Strategy B: Kalman spread + Z-score trigger. Both feed the Risk Engine; only approved strategies trade live. |
| 4 - Risk Engine          | Risk-based sizing (% of equity). Minimum-notional floor check. Z-unit + time stops. Pearson r guard. Monte Carlo-derived circuit breakers.                     |
| 5 - Execution            | ccxt for Kraken spot. Hyperliquid WebSocket for perps. Maker-then-IOC two-leg execution for pairs (see 8). Slippage gate on every order.                       |
| 6 - Logging + Monitoring | v1: NO ML gate - exhaustive logging only (signals, fills, slippage, funding, regime labels). Nightly P&L to Telegram. SQLite persistence. ML arrives in v2.    |


## **Portfolio Brain**

Above all layers, the Portfolio Brain runs every cycle: ranks active signals, checks the correlation matrix, allocates risk budget across approved trades, enforces the concurrent-position cap, and tracks realised P&L against the capital plan. A profit milestone triggers a review notification; it never hard-stops trading.

# **6 Market Regime Detection**

Regime is computed **per traded asset**, with a **global BTC regime** as an override that can only *reduce* risk, never increase it. (v2.0 never specified which asset the regime applied to - across hundreds of pairs, per-asset and global regimes disagree constantly.)


| **Regime (per asset)** | **Detection Logic**                           | **Strategy A (when live)**    | **Strategy B**                                                          |
| ---------------------- | --------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------- |
| Trending Up            | EMA(9) > EMA(21), ADX > 25, price above 200MA | Active, Mid-Aggressive tier   | Active at 50% size (cointegration breaks more often in strong trends)   |
| Sideways               | ADX < 20, BB width tight, no clear slope      | Inactive (no momentum edge)   | Active at full size, tiers per Z-score                                  |
| Trending Down          | EMA(9) < EMA(21), price below 200MA, ADX > 25 | Inactive. Long-only strategy. | Active at 50% size - market-neutral positions do not need a bull market |


Strategy B trading all regimes is a deliberate v3.0 correction: pausing a market-neutral strategy in downtrends (as v2.0 did) discards the entire reason it exists. Full pause is reserved for the circuit breakers.

**Known limitation:** a 4h ADX+EMA detector lags reversals by 1-2 candles (4-8 hours). A faster confirmation input (1h structure break or realized-volatility spike) can cut size intraday without waiting for the 4h close. Regime flips never widen existing stops.


| A day with zero trades and zero loss is a good day. The bot does not force trades. |
| ---------------------------------------------------------------------------------- |


# **7 Strategy A - Swing Momentum (Kraken) - Paper Phase**

## **Volume Anomaly Scanner - Data Collection Mission**

Every hour, the scanner queries CoinGecko for 1h volume across the top 300 pairs by market cap. A flag fires when 1h volume exceeds 3x its 20-day average. **Every flag, with full market context, is logged to SQLite whether or not any other condition is met.** This dataset is the whole point of the paper phase: free data tiers provide no deep historical hourly volume, so the anomaly edge can only be measured forward, not backtested.

The scanner also logs variants for later comparison: anomaly with price up >5% (the v2.0 trigger - note this enters *after* the move), anomaly with price flat (potential accumulation - possibly the better signal), and anomaly with price down (distribution/panic). Which variant has edge is an empirical question the log will answer.

## **Entry Signal (paper, later live)**

- **Primary:** EMA(9) crosses above EMA(21) on 4h chart.
- **Filter:** RSI(14) below 70.
- **Confirmation:** volume anomaly flag on the same asset within the same 4h window.
- **Tier:** anomaly alone = Mid. Anomaly + EMA cross = Aggressive. EMA cross alone = Passive (and expected to be roughly break-even after costs - it is logged to prove or disprove this, not because it is trusted).

## **Exit Logic**

- **Take profit:** 6% above entry (2:1 reward/risk at a 3% stop).
- **Stop loss:** 3% below entry, ATR-adjusted to current volatility.
- **Strategy exit:** EMA(9) crosses back below EMA(21) before TP/SL.

## **Go-Live Gate for Strategy A**

All three required: (1) account equity ≥ RM1,500-2,000, where per-pair minimums and lot rounding distort intended risk by <5%; (2) ≥3 months of paper trades with the 90% confidence interval of expectancy above 0R; (3) the anomaly variant being traded shows positive expectancy in the scanner log independently of the EMA cross.

# **8 Strategy B - Statistical Arbitrage (Hyperliquid)**

## **Pairs Selection - Hardened**

Naive screening creates a statistical trap: testing the top 50 assets pairwise is C(50,2) = 1,225 Engle-Granger tests, and at p < 0.05 roughly 61 "cointegrated" pairs would appear by pure chance. Crypto's shared BTC factor makes this worse - in-sample p-values look excellent and decouple live. The v3.0 pipeline:

1. **Universe:** top 50 Hyperliquid assets by volume, minimum 12 months of history.
2. **Cointegration test:** Engle-Granger on a 6-month window, with **Benjamini-Hochberg false-discovery-rate correction** across all pairs tested.
3. **Stability:** the relationship must hold (post-correction) on at least 3 non-overlapping 60-day sub-windows.
4. **Half-life filter:** fit an Ornstein-Uhlenbeck process to each surviving spread. Trade only pairs with mean-reversion half-life between 4 hours and 3 days - far shorter than this and fees dominate; longer and the time stop can never be satisfied within the intended holding period.
5. **Out-of-sample check:** the spread must have remained stationary on the most recent 30 days, which were excluded from the selection window.
6. **Weekly re-test:** any pair that fails is immediately removed. Open positions in a removed pair are closed at the next Z-touch of 1.0 or at the time stop, whichever comes first.

## **Hedge Ratio - Kalman Filter**

Beta is estimated with a Kalman filter - a smooth, online estimate updated every bar - replacing v2.0's weekly OLS refresh, which left beta stale for up to a week and then re-marked every open position when it jumped. **Each open position freezes its entry beta and Z-series for its lifetime;** updated betas apply to new entries only. (Fallback implementation: rolling OLS is acceptable for the first backtest iteration, with the same entry-freeze rule.)

## **Entry Signal**

- **Spread:** Price_A − beta × Price_B, beta from the Kalman filter.
- **Z-score:** spread versus its rolling mean and standard deviation (window = 4x the pair's half-life, bars = 1h; both stated explicitly because every downstream number depends on them).
- **Thresholds:** entry at the pair's empirical 97.5th percentile of |Z| (~2.0 for well-behaved pairs). Thresholds are calibrated per pair from that pair's own Z history - crypto spreads are fat-tailed, so the Gaussian "2σ = 2.3% of observations" intuition understates trigger frequency and overstates per-signal edge.
- **Tier:** |Z| at threshold = Mid. |Z| > threshold + 0.5 with volume anomaly confirming on either leg = Aggressive.

## **Execution - Maker-then-IOC**

v2.0 specified post-only orders on both legs with a 500ms leg window - a contradiction, since post-only orders rest in the book for seconds to minutes and would self-cancel almost every trade. v3.0:

1. Rest a post-only order on the **more liquid leg**.
2. The instant it fills, fire an **IOC (taker) order on the second leg** with a hard max-slippage bound.
3. If the IOC misses or exceeds the slippage bound, immediately flatten leg 1 at market. The cost of one flattening is the price of avoiding a naked directional position.
4. The taker fee on leg 2 is priced into the entry threshold: a signal is only taken if expected convergence profit clears total round-trip cost (maker + taker + funding estimate + slippage allowance) by at least 2:1.

## **Exit Logic**

- **Take profit:** close 50% at |Z| = 1.0, remainder at Z = 0.
- **Hard stop:** |Z| ≥ 3.0 (calibrated per pair alongside the entry threshold). Stops are defined in Z-units, never as a percentage of the entry spread - the spread of a cointegrated pair routinely sits near zero and crosses sign, so percent-of-spread stops (v2.0) divide by ~0 exactly when signals fire.
- **Time stop:** exit at market after 2x the pair's half-life regardless of Z. A spread that has not converged in twice its characteristic time is evidence the relationship has changed.

# **9 The Six Mathematical Pillars (v3.0)**

## **9.1 Hedge Ratio - Kalman Filter (OLS fallback)**


| State equation: beta_t = beta_{t-1} + w_t (random walk)               |
| --------------------------------------------------------------------- |
| Observation: Price_A,t = beta_t × Price_B,t + e_t                     |
| Kalman gain balances responsiveness vs noise; beta updates every bar. |
|                                                                       |
| Open positions freeze their entry beta. Updated beta applies to new   |
| entries only. A hedge ratio that silently re-marks open positions     |
| converts logged R-multiples into fiction.                             |


## **9.2 Cointegration Screening - Engle-Granger with FDR Correction**


| 1,225 pairwise tests at p < 0.05 = ~61 false positives expected.                          |
| ----------------------------------------------------------------------------------------- |
| Benjamini-Hochberg: sort p-values, accept p_(i) ≤ (i/m) × 0.05.                           |
| Then: stability across 3 non-overlapping windows + OU half-life filter                    |
| (4h ≤ half-life ≤ 3 days) + 30-day out-of-sample stationarity check.                      |
|                                                                                           |
| half-life = −ln(2) / lambda, from OU fit: d(spread) = lambda × (mu − spread)dt + sigma dW |


## **9.3 Z-Score - Entry, Exit, and Stop in One Unit System**


| Z = (spread − mu_spread) / sigma_spread                                |
| ---------------------------------------------------------------------- |
| Entry:                                                                 |
| Scale out:                                                             |
| Hard stop:                                                             |
|                                                                        |
| Window = 4 × half-life on 1h bars. Thresholds from each pair's own     |
| empirical distribution, never from the Gaussian table - crypto spreads |
| are fat-tailed and heteroskedastic.                                    |


## **9.4 Risk-Based Position Sizing with Minimum-Notional Floor**

One unit system for both strategies. 1R = the risk fraction of current equity, scaling as the account grows. (v2.0 mixed notional-percentage sizing with fixed-RM1 risk - two incompatible schemes that made logged R-multiples meaningless.)


| risk_amount = tier_risk_pct × current_equity                             |
| ------------------------------------------------------------------------ |
| Strategy A: notional = risk_amount / stop_distance_pct                   |
| Strategy B: notional = risk_amount / (Z-stop distance in spread % terms) |
|                                                                          |
| FLOOR CHECK: if notional < exchange minimum ($10/order on Hyperliquid -  |
| i.e. ~$20 per two-leg spread trade - or the per-pair Kraken minimum):    |
| SKIP THE TRADE and log it. Never round up - rounding up silently         |
| multiplies risk. Leverage on Hyperliquid reduces collateral locked,      |
| never risk: risk = notional × stop distance, and leverage does not       |
| appear in that equation.                                                 |


## **9.5 Pearson r - Correlation Guard**


| r = Cov(returns_X, returns_Y) / (sigma_X × sigma_Y) - on RETURNS, minimum 90 observations |
| ----------------------------------------------------------------------------------------- |
| Trigger at r > 0.85; release at r < 0.75 (hysteresis prevents flapping).                  |
| Correlated positions collapse into ONE shared 1R budget - defined as                      |
| the standard risk fraction of equity, not a fixed RM amount.                              |
| Four trades with r = 0.96 is not diversification. It is one trade with                    |
| 4x the risk.                                                                              |


## **9.6 Expectancy with Confidence Intervals + Monte Carlo Drawdown**


| Expectancy = mean(R-multiples) · SE = sigma_R / sqrt(n)                 |
| ----------------------------------------------------------------------- |
| Decisions use the 90% CI, never the point estimate:                     |
| · Scale capital only when CI lower bound > 0 (needs ~150-200 trades     |
| to confirm +0.3R - a 50-trade gate cannot distinguish +0.3R from 0).    |
| · Pause and review when CI upper bound < 0 over the last 100 trades.    |
|                                                                         |
| Circuit breaker calibration: 10,000 Monte Carlo paths of 300 trades at  |
| the assumed win rate and payoff. Kill threshold = 99th percentile max   |
| drawdown + buffer. A kill switch inside normal variance does not detect |
| failure - it executes the system for being unlucky.                     |


# **10 Risk Management**

## **3-Tier Risk-Based Sizing**

Tier sets the **risk fraction**, not the notional. Notional is derived from stop distance (9.4).


| **Tier**   | **Activation Condition**                   | **Risk per Trade**      |
| ---------- | ------------------------------------------ | ----------------------- |
| Passive    | Single weak signal, or regime-reduced size | 0.50% of current equity |
| Mid        | Volume anomaly alone, OR                   | Z                       |
| Aggressive | Anomaly + EMA cross confirmed, OR          | Z                       |


Maximum concurrent open risk: 3R (e.g. 3 positions at 1%, or 4-6 at lower tiers). Correlated positions share one bucket (9.5).

## **Structural Guardrails**

- **Guardrail A - Correlation Creep:** r > 0.85 across signals → collapse to one 1R bucket (hysteresis release at 0.75).
- **Guardrail B - Slippage Gate:** calculated slippage > 0.08% of notional → cancel. Edge wiped by slippage is not a trade.
- **Guardrail C - Daily Circuit Breaker:** daily drawdown > 3x max single-trade risk (3% at the 1% tier) → halt, clear orders, Telegram alert, manual review before resume. Sized as a multiple of per-trade risk so one routine stop-out cannot trip it.
- **Guardrail D - Account Kill Switch:** drawdown threshold derived from the Monte Carlo calibration in 9.6 (~25% at 0.75% average risk, versus v2.0's 10%, which simulation shows would have fired on ordinary variance long before proving anything). Bot stops until manually restarted after a written review.
- **Guardrail E - Isolated Margin:** every Hyperliquid position uses isolated margin. A losing trade can consume only its allocated collateral.

# **11 The Learning System - Deferred by Design**

**v1 ships with NO ML gate.** This is a correction, not a missing feature: at 15-22 trades/month, six months of live trading produces ~100 trade outcomes - spread across 6+ features and 3 regimes, that guarantees an overfit model whose "confidence" gate randomly skips good trades. v1's learning layer is exhaustive logging: every signal (taken and skipped), fill, slippage measurement, funding payment, regime label, and scanner flag goes to SQLite. The dataset is the asset.

## **v2 - ML Confidence Scoring (conditions, not dates)**

Activated only when ALL hold: 200+ live trades logged; v1 expectancy CI positive; and the model is trained on **candle-level features with forward-return labels at each strategy's actual horizon** - so every historical bar is a training sample, not every trade. FreqAI/LightGBM is the natural fit here (this is what it is designed for - v2.0 misused it as a trainer on the bot's own sparse win/loss outcomes).


| **Confidence Score** | **Action**                                        |
| -------------------- | ------------------------------------------------- |
| 0.70 and above       | Execute at assigned tier                          |
| 0.50 to 0.69         | Downgrade one tier                                |
| Below 0.50           | Skip - and LOG the skip for counterfactual review |


## **Kronos Foundation Model - Logged Experiment Only**

Kronos (shiyu-coder/Kronos, AAAI 2026) outputs a 24h bull_probability. Two hard rules: (1) it runs as a **logged, non-gating experiment** until its score demonstrably adds expectancy on this system's own trades; (2) it **never gates Strategy B** - a market-neutral spread position has no business consulting a directional forecast. Its 24h horizon also mismatches Strategy A's 1-5 day holds; if adopted, it informs entry timing only. GPU VPS cost (~RM90/month) is deferred until account equity makes it <2% monthly drag (RM5,000+).

# **12 Open Source Integration**


| **Project**            | **What we use**                                                                                               | **What we skip**                                                   |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Jesse (jesse-ai)       | Backtesting engine. Monte Carlo stress-testing (also used to calibrate Guardrail D). Walk-forward validation. | Jesse Pro live trading (paid). Build our own execution layer.      |
| Freqtrade + FreqAI     | FreqAI retraining loop in v2 (candle-level labels). Telegram notifications. SQLite persistence patterns.      | Freqtrade core bot. Its exchange connectors.                       |
| Hummingbot             | Hyperliquid WebSocket connector architecture as reference. Order management patterns.                         | The full framework - designed for market making.                   |
| Kronos (shiyu-coder)   | KronosPredictor as a logged v2 experiment (see 11).                                                           | Multi-GPU fine-tuning. Using it as a gate before it proves itself. |
| statsmodels / pykalman | Engle-Granger, OU half-life fitting, Kalman filter beta.                                                      | -                                                                  |


# **13 Cost Model and Financial Projections**

## **Per-Trade Cost Model (verified June 2026)**


| **Cost**                | **Strategy A (Kraken)**                                                                                                                        | **Strategy B (Hyperliquid)**                                                                   |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Round-trip fees         | ~0.50% (0.25% maker x2, base tier)                                                                                                             | ~0.12% (maker in + taker leg + taker out, both legs)                                           |
| Fee drag in R (3% stop) | ~0.17R per trade                                                                                                                               | ~0.04-0.08R per trade                                                                          |
| Funding                 | n/a (spot)                                                                                                                                     | Settled HOURLY. Largely nets across the two legs but never assumed zero - logged per position. |
| Slippage allowance      | 0.08% gate                                                                                                                                     | 0.08% gate per leg                                                                             |
| Transfers               | Batched monthly in / quarterly out. ~RM5-15 per full loop.                                                                                     |                                                                                                |
| Infrastructure          | RM0-5/month below RM2,000 equity (home machine or free-tier cloud). Paid VPS (~RM25/month) only above RM2,000, where it is <1.5% monthly drag. |                                                                                                |


Every backtest and projection includes this cost model. An expectancy figure quoted without costs is fiction - at base-tier Kraken fees, a gross +0.65R system is a net ~+0.45R system before slippage.

## **Honest Return Expectations**


| **Scenario** | **Monthly return** | **What it means**                                               |
| ------------ | ------------------ | --------------------------------------------------------------- |
| Realistic    | −2% to +3%         | A sound retail system in normal conditions. High variance.      |
| Good         | +3% to +5%         | Sustained, this is professional-grade. Verify before believing. |
| Suspicious   | >5% sustained      | Most likely overfit, lucky, or mismeasured. Audit immediately.  |


v2.0's "realistic" 8-12% monthly was 150-290% annualized - beyond nearly every professional quant fund, sustained. Scaling decisions anchored to such numbers fail. **Growth at this stage comes from contributions, not compounding** - see Section 14.


| Reality check, restated: at +2% monthly, RM500 generates RM10 per MONTH. |
| ------------------------------------------------------------------------ |
| The bot's Phase-1 product is proof and data. The contribution schedule,  |
| not the return, is what grows the account in year one.                   |


# **14 Capital Plan - Contribution-Based Scaling**

## **Why not RM100**

Hyperliquid's $10/order minimum means a spread trade is ~~$20 notional minimum. At RM100 (~~$21) equity, one minimum-size trade with a typical stop risks ~2.5-3% of equity - 3-5x the target risk fraction - and permits exactly one concurrent position. The account would be structurally over-risked by exchange minimums alone.

## **The Plan**


| **Stage**           | **Equity**    | **Funding**                                                           | **What runs**                                                                                |
| ------------------- | ------------- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Paper (months 1-3)  | RM0 live      | RM0. Home machine / free-tier cloud.                                  | Strategy B paper + backtest. Strategy A scanner logging.                                     |
| Go-live             | RM400-500     | One deposit                                                           | Strategy B live, 2-3 concurrent minimum-size positions at on-target risk (~0.5-0.75%/trade). |
| Build (months 4-12) | → RM2,000+    | RM100-150/month contributions, paid only if monthly health gates pass | Strategy B live. Strategy A still paper.                                                     |
| Promote A           | RM1,500-2,000 | Continued contributions                                               | Strategy A live alongside B (gate in Section 7).                                             |
| Scale               | RM3,000-5,000 | Contributions + retained profits                                      | Full system. v2 ML experiments begin.                                                        |


**Monthly health gates for contributing fresh capital:** no unexplained guardrail breaches; live slippage within modeled bounds; expectancy CI not deteriorating; all fills and logs reconciled. Contributions are suspended - not the bot - when a gate fails, until the cause is understood.

**Projection with contributions (RM500 start + RM150/month):**


| **Monthly return** | **12-month balance** | **Note**                                      |
| ------------------ | -------------------- | --------------------------------------------- |
| 0%                 | ~RM2,300             | Contributions alone reach the Promote-A gate. |
| +1%                | ~RM2,470             | Realistic positive case.                      |
| +2%                | ~RM2,650             | Good case.                                    |


The plan reaches Strategy A's go-live capital in ~10-12 months **even at zero return**. The bot's job in year one is to prove expectancy; the contribution schedule's job is to grow the account. Neither depends on the other succeeding.

**Budget rules:** never trade borrowed money; never deposit funds needed within 12 months; the contribution amount must be small enough that a 100% loss changes nothing about your life.

# **15 Beyond Crypto - Multi-Market Evolution**

The mathematics is asset-agnostic: cointegration, Kalman hedge ratios, Z-score reversion, regime detection, and expectancy tracking work identically on equities, FX, and futures - pairs trading was invented on stocks. What differs is **access, minimums, and costs**, and that is why Aegis starts in crypto:


| **Market**          | **Assessment for a small Malaysian retail account**                                                                                                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Crypto (current)    | 24/7, no minimum-capital rules, fractional sizing, free API access without broker approval, shorting trivially available via perps. Optimal below ~RM20k.                                                                  |
| US equities (IBKR)  | The natural second market - pairs trading's home turf, deep liquidity, good API. Costs: commissions, market-data fees, FX conversion, share-borrow fees for shorts, US tax paperwork. Sensible at ~RM20k+ equity.          |
| Forex               | Low minimums and high leverage, but retail FX is dealer-spread-dominated, stat-arb in majors is heavily arbitraged, and broker quality for Malaysians varies (many offshore = counterparty risk). Possible, not preferred. |
| Commodities / bonds | Futures contract margins (even micro contracts) run thousands of RM per position. Out of reach below ~RM50k. Bonds are not a retail trading market at all.                                                                 |
| Bursa Malaysia      | No practical retail shorting → no pairs trading. Long-only momentum possible but thin liquidity and limited API access.                                                                                                    |


**Design consequence today:** keep the strategy engine venue-agnostic behind an exchange abstraction layer (the ccxt + custom-connector split already implies this). The strategy code must never import an exchange client directly. That one discipline, costing nothing now, makes the IBKR door a connector-writing exercise later instead of a rewrite.

**Trigger to expand:** 12+ months live, expectancy CI positive, equity ~RM20k+. Before that, a second market adds surface area without adding edge.

# **16 Risk Factors**

- **Cointegration breakdown:** pairs can decouple on fundamental events (exploits, delistings, forks). Weekly FDR-corrected re-testing, the half-life filter, and the time stop together bound exposure to a broken relationship.
- **Funding erosion:** Hyperliquid funding settles hourly. It largely nets across a spread's two legs but is logged per position and included in the entry-threshold cost check - never assumed away.
- **Exchange risk:** Kraken solvency risk; Hyperliquid smart-contract risk. Quarterly profit withdrawal; never hold more than open positions require.
- **Regime misclassification:** the 4h detector lags reversals by 4-8 hours. Mitigated by the intraday volatility confirmation, per-position stops, and the daily breaker.
- **Model overfitting (v2):** monitor expectancy per regime, not just overall. A model with +1.0R in trends and −0.5R in chop is not a good model.
- **Statistical false confidence:** the deepest risk in v2.0 was its own math - uncorrected multiple testing, point-estimate gates, Gaussian assumptions. v3.0's FDR correction, confidence intervals, and empirical thresholds exist because the most dangerous failure mode is a system that looks rigorous.
- **Regulatory:** crypto trading is legal in Malaysia; tax treatment is evolving. Keep Luno exports; consult a tax professional.

# **17 Development Roadmap**


| **Phase** | **Deliverable**                                                                                                                                                       | **Timeline** |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| Phase 0   | Infra on home machine / free-tier cloud. Data layer. Anomaly scanner LOGGING live from day one (its dataset gates Strategy A months later).                           | Weeks 1-3    |
| Phase 1   | Strategy B: FDR pairs screening, Kalman beta, Z/time stops, sizing engine. Jesse walk-forward backtest 2020-2026, multi-asset, incl. delisted coins, full cost model. | Weeks 3-8    |
| Phase 2   | Risk engine, correlation guard, Monte Carlo breaker calibration, regime detector, portfolio brain. Hyperliquid testnet two-leg execution.                             | Weeks 8-12   |
| Phase 3   | Strategy B PAPER trading - minimum 8 weeks. Strategy A paper pipeline live in parallel. Gate: paper expectancy CI consistent with backtest.                           | Months 3-5   |
| Phase 4   | Strategy B LIVE with RM400-500. Contributions begin (RM100-150/month, health-gated). Telegram P&L. Monitor 4 weeks before any size increase.                          | Month 5-6    |
| Phase 5   | Equity RM1,500-2,000 via contributions + returns. Strategy A go-live gate evaluated (Section 7). Promote if passed.                                                   | Months 10-14 |
| Phase 6   | RM3,000-5,000. v2 ML experiments (candle-level FreqAI; Kronos logged-only). Multi-market evaluation begins at RM20k+ (Section 15).                                    | Month 15+    |


v2.0's 10-12 week build-to-live timeline assumed two strategies, six layers, and an ML loop built simultaneously by one person - a 2-3x underestimate. v3.0 ships one strategy end-to-end first. Smaller surface, faster iteration: the document's own stated edge.

# **18 Technology Stack**


| **Component**         | **Technology**                                                                                    |
| --------------------- | ------------------------------------------------------------------------------------------------- |
| Language              | Python 3.11+                                                                                      |
| Exchange (spot)       | Kraken via ccxt                                                                                   |
| Exchange (futures)    | Hyperliquid WebSocket (reference: Hummingbot connector)                                           |
| Abstraction           | Venue-agnostic execution interface - strategy code never imports an exchange client (Section 15)  |
| Fiat gateway          | Luno (MYR on/off ramp)                                                                            |
| Signal indicators     | pandas-ta (EMA, RSI, ATR, Bollinger Bands, ADX)                                                   |
| Statistical engine    | statsmodels (OLS, Engle-Granger), pykalman (Kalman beta), OU half-life fit                        |
| Backtesting           | Jesse - walk-forward, Monte Carlo (also calibrates Guardrail D)                                   |
| Learning layer (v2)   | FreqAI / LightGBM on candle-level labels; Kronos as logged experiment                             |
| Optimisation          | Optuna                                                                                            |
| Trade persistence     | SQLite - trades, signals, skips, slippage, funding, scanner flags                                 |
| Monitoring / alerts   | Telegram Bot API                                                                                  |
| Infrastructure        | Home machine / free-tier cloud below RM2,000 equity; paid VPS (~RM25/month) above                 |
| Market data (anomaly) | CoinGecko API free tier - forward logging only; no historical backfill exists at this granularity |


# **19 Conclusion**

Version 3.0 is the same thesis with the engineering honesty turned up: one unit system for risk, verified costs, statistically defensible gates, and a rollout that sequences proof before capital. Strategy B carries the account because it is the only strategy executable at small size; Strategy A earns its way in with logged data; the learning layer waits until there is something to learn from; and the account grows on a contribution schedule that works even if returns are zero.

The barriers remain non-technical: backtesting rigorously before going live, trusting the system inside its calibrated drawdown envelope, contributing on schedule, and not overriding the circuit breakers.


| Next step: Phase 0 - stand up the data layer and start the anomaly scanner log TODAY.           |
| ----------------------------------------------------------------------------------------------- |
| Then Strategy B walk-forward backtest with the full cost model.                                 |
| Gates: backtest expectancy CI > 0, max drawdown inside Monte Carlo envelope, 8-week paper       |
| trade consistent with backtest. Capital deployed before these gates is tuition, not investment. |


