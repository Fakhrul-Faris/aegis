# Aegis Study Notes

*For non-finance readers · June 2026 · Companion to `docs/Aegis Concept.md` and `docs/Aegis Tasks & Milestones.md`*

Read top to bottom once, then use **flashcards** for memory and the **cheat sheet** before Telegram checks or milestone reviews.

---

## Part 1 — Flashcards (20 terms)

Cover the **Answer** column, quiz yourself, then check.

| # | Term | Answer |
|---|------|--------|
| 1 | **Crypto exchange** | A website/app where you buy and sell coins (Kraken, Hyperliquid, Luno). |
| 2 | **Spot trading** | You actually buy the coin and hold it (Strategy A on Kraken). |
| 3 | **Perp / futures** | A bet on price without owning the coin; can bet up or down (Strategy B venue). |
| 4 | **USDT** | A “digital dollar” (~$1) used to trade on international exchanges. |
| 5 | **Candle / 4h chart** | A price summary for a time window (open, high, low, close). Bot reads these, not news. |
| 6 | **EMA crossover** | Two moving averages; fast crossing above slow = possible uptrend (Strategy A entry hint). |
| 7 | **RSI** | “Is it already overbought?” filter — avoid buying when price ran too far too fast. |
| 8 | **Volume anomaly** | Today’s volume is ~3× normal → something unusual happened (Strategy A’s special ingredient). |
| 9 | **Paper trading** | Fake money, real prices — practice without losing cash. |
| 10 | **Backtest** | Pretend to trade on **old** data to see if rules would have worked. |
| 11 | **Walk-forward** | Re-pick rules on past data, test on **future** data — honest test, harder to cheat. |
| 12 | **Pairs trading / spread** | Watch two coins that usually move together; bet they snap back when one runs ahead. |
| 13 | **Z-score** | “How weird is this gap?” — 2 = pretty weird, 3 = very weird (Strategy B). |
| 14 | **Cointegration** | Stats test: “Do these two coins stay linked over time?” (Strategy B screening). |
| 15 | **Expectancy** | Average profit/loss per trade over many trades — the real “is this worth it?” number. |
| 16 | **R-multiple (1R)** | Profit measured in “units of risk.” 1R = one normal bet size; +2R = won twice your risk. |
| 17 | **Drawdown** | Drop from your account’s highest point — “how bad was the worst slump?” |
| 18 | **Circuit breaker / kill switch** | Auto-pause when losses hit a limit — daily pause vs full emergency stop. |
| 19 | **Regime** | Market “weather”: trending up, sideways, or trending down — changes how much we bet. |
| 20 | **Gate / milestone** | Checklist step; **all** must pass before next phase (pass/fail, no “almost”). |

---

## Part 2 — Explain like I’m 12

### What is Aegis?

Imagine a **robot helper** for crypto trading. It watches prices 24/7, follows rules you wrote in code, writes everything in a diary (SQLite), and texts you on Telegram. It does **not** guess the news or “feel” the market — it follows recipes.

Right now the robot’s job is **homework** (collect data, practice trades with fake money), not **earning pocket money** yet.

---

### The three places money moves

| Place | Simple job |
|-------|------------|
| **Luno** | Change ringgit (MYR) ↔ crypto. Like a money changer. No trading bot here. |
| **Kraken** | Buy/sell coins for real (Strategy A — spot). |
| **Hyperliquid** | Bet on prices (Strategy B used this — perps). |

Flow: **MYR → Luno → USDT → trading exchanges → profits back later (not every week — fees add up).**

---

### Strategy A — “Catch the wave” 🏄

**Story:** Sometimes a coin gets quiet attention (volume spikes) before the price jumps. The bot watches for that plus a simple “trend turning up” signal (EMA cross).

**Tiers (how excited the bot is):**

| Tier | Meaning |
|------|---------|
| Passive | Trend only — logged, usually **not** traded in paper (baseline comparison). |
| Aggressive | Trend **plus** volume spike — the one that gets **simulated buys** in paper. |

**Exits:** Take profit (+6%), stop loss (−3%), or trend turns back down.

**What we learned:** EMA + RSI **alone** lost money in backtest. The **hope** is volume anomaly helps — we’re **testing that live** because old volume data isn’t free to backtest.

**Status:** Paper mode running; scanner logging every hour.

---

### Strategy B — “Two friends on a leash” 🐕🐕

**Story:** BTC and ETH often walk together. Sometimes one runs ahead. Strategy B bet they’d **come back together** — so you don’t care if the whole market goes up or down.

**What happened:** We checked thousands of coin pairs over years. Many looked linked in the past but **broke apart** when we tested honestly on new data. **Result: NO-GO.** The test worked; the market didn’t give stable pairs.

**Status:** Signal path **closed**. Testnet “soak” still runs to prove the **machine** (orders, risk, alerts) — not that Strategy B makes money.

---

### The six layers (factory line)

1. **Data** — Cameras + notebooks (prices, scanner flags).
2. **Regime** — Weather report (trending up / sideways / down).
3. **Strategy** — Recipe (“should we trade?”).
4. **Risk** — Fire marshal (“how much? too many bets?”).
5. **Execution** — Waiter sends order to exchange.
6. **Monitor** — Manager (Telegram, logs, `/status` bot).

**Portfolio brain** = shift supervisor each cycle.

---

### Risk rules (why the robot can say “no”)

| Rule | Like… |
|------|--------|
| Bet 0.5–1% per trade | Only risk one slice of pizza, not the whole pie. |
| Max 3 open bets | Don’t enter every game at once. |
| Slippage gate | Price moved too much — deal’s off. |
| Daily breaker | Bad day — stop until a human checks. |
| Kill switch | Emergency stop — needs manual restart. |
| Config freeze | Changing the recipe **restarts the 8-week test clock**. |

**A good day** can be zero trades and zero loss. The bot doesn’t have to play every hand.

---

### Where we are now (June 2026)

| ✅ Done | ⏳ Running | ❌ Not yet |
|--------|-----------|------------|
| Code, tests, data pipeline | M1 72h data gate (~Jun 13) | Live real money |
| B research → failed (cheap lesson) | 7-day testnet soak on Fly | 8-week formal paper verdict |
| A paper + Telegram bot | Scanner + Mac agents | “Go live” on A |

**One sentence:** Prove Strategy A on paper + prove the machine works; don’t add new strategies until that’s answered.

---

## Part 3 — One-page cheat sheet

Print or keep this open on your phone.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ AEGIS CHEAT SHEET · June 2026                                           │
├─────────────────────────────────────────────────────────────────────────┤
│ WHAT IT IS     Autonomous crypto bot: data → rules → risk → trade/log   │
│ GOAL NOW       Proof + data, NOT income. Gates before live money.       │
├─────────────────────────────────────────────────────────────────────────┤
│ STRATEGY A (ACTIVE PATH)          │ STRATEGY B (CLOSED)                  │
│ Kraken spot · swing momentum      │ HL perps · pairs mean reversion      │
│ EMA + RSI + volume anomaly        │ Cointegration research → NO-GO       │
│ Paper now · live only if gates pass│ Soak = test machine, not profit      │
├─────────────────────────────────────────────────────────────────────────┤
│ KEY NUMBERS (Strategy A)          │ KEY NUMBERS (Risk)                   │
│ TP +6% · SL −3% · 4h candles      │ 0.5 / 0.75 / 1.0% equity per trade   │
│ Anomaly = 3× volume vs 20d avg    │ Max 3R open · slippage gate 0.08%      │
│ Baseline EMA-only: −0.21R (bad)   │ Daily halt · MC kill switch (unset)  │
├─────────────────────────────────────────────────────────────────────────┤
│ EXCHANGES                         │ MODES                                │
│ Luno = MYR ↔ crypto               │ paper = fake fills, real prices        │
│ Kraken = Strategy A               │ testnet = fake HL money, real API    │
│ Hyperliquid = B infra / soak      │ live = blocked until gates + kill cal│
├─────────────────────────────────────────────────────────────────────────┤
│ TELEGRAM (read-only)              │ TERMINAL (when needed)               │
│ /status  heartbeat + buttons      │ uv run aegis-doctor                  │
│ /progress milestones + where we are│ uv run aegis-summary                 │
│ /paper   equity, positions        │ fly logs -a aegis-testnet-soak       │
│ /scanner flags                    │ launchctl list | grep com.aegis      │
│ /health  stack check              │                                      │
│ /kpi     weekly stats + tier/variant│                                      │
├─────────────────────────────────────────────────────────────────────────┤
│ MILESTONES (simplified)                                                 │
│ M0 M2 ✅  ·  M3 B ❌  ·  M1 ~Jun 13  ·  M4 soak → Jun 18  ·  M5–M6 paper│
├─────────────────────────────────────────────────────────────────────────┤
│ DO NOT (plan rules)                                                     │
│ · Change paper config without reset → restarts 8-week clock              │
│ · Run local + Fly soak on same HL wallet                                 │
│ · Sync DB while agents writing (use sync-collector-db.sh)                │
│ · Add new strategy before A paper verdict                                │
│ · Treat Telegram crash as soak failure (check Fly for soak)             │
├─────────────────────────────────────────────────────────────────────────┤
│ READ ORDER                                                              │
│ 1. This file  2. strategy_b_verdict.md  3. strategy_a_baseline_backtest  │
│ 4. Concept §1-2,5,7,10,14  5. Tasks & Milestones overview               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Quick reference — files

| File | Use when |
|------|----------|
| `docs/Aegis Concept.md` | Full strategy + math spec |
| `docs/Aegis Tasks & Milestones.md` | What’s done, gates, dates |
| `aegis/research/2026-06-strategy_b_verdict.md` | Why B stopped |
| `aegis/research/2026-06-strategy_a_baseline_backtest.md` | Why EMA-only isn’t enough |
| `aegis/deploy/ops.md` | Daily ops commands |

---

*Last updated: June 2026 — aligns with project state at M4 soak + Strategy A paper path.*
