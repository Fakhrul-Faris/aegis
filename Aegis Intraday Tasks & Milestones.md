**EXECUTION DOCUMENT · CONFIDENTIAL**

**Aegis Intraday — Strategy C (Day) + D (Scalp)**

*Version 1.1 · June 2026 · Additive track; does not replace crypto swing or forex*

Phase 1 targets: **≥$50/week** simulated profit and **≥5/7 win days**, on a **$400** paper account.

**Fly.io:** `aegis-collector` runs intraday paper sidecar (60s) with `AEGIS_INTRADAY_ENABLED=1`. Unified HTML Telegram daily summary + `/intraday` command. **Do not** run local `com.aegis.intraday` or `com.aegis.telegrambot` while Fly is polling.

---

# **1 Milestone Overview**

| **ID** | **Milestone** | **Gate** | **Status** |
| ------ | ------------- | -------- | ---------- |
| ID0 | 15m HL ingest live | 14 days clean 15m data for top 10 symbols | ⏳ Jun 17 |
| ID1 | H-C1 backtest | ≥80 trades; expectancy 90% CI > 0 net of HL costs | ☒ FAIL (0 trades) |
| ID2 | Paper C starts | Config frozen; `aegis-intraday-paper-run --loop 60` | ☑ Jun 17 |
| ID3 | Paper D (optional) | 2 weeks C watchlist stable; scalp enabled in config | ☐ |
| ID4 | **Phase 1 proof** | 4 consecutive weeks: ≥$50/wk + ≥5/7 win days; ≥80 closed trades | ☐ |
| ID5 | Live micro $400 | ID4 pass; HL perp account; 4-week live proof | ☐ |

Crypto M6 and forex FX6 **do not block** ID0–ID3.

**ID0 gate check:** ⏳ 28,800 15m candles ingested locally; Fly collector hourly ingest includes 15m path. 14-day clock started Jun 17.

**ID1 gate check:** ☒ **FAIL** — `aegis-backtest-intraday` on BTC/ETH/SOL: 0 trades. Need more history or param review before ID4 clock.

**ID2 gate check:** ☑ Config frozen hash `70704535a659be0d`; Fly sidecar logging `intraday paper cycle` every 60s (deployed Jun 17 v10).

---

# **2 Strategy C — H-C1 (frozen for ID2)**

| Parameter | Value |
| --------- | ----- |
| Venue | Hyperliquid perps (paper sim, mainnet prices) |
| Signal TF | 15m |
| Regime TF | 4h trending up |
| Trigger | CoinGecko scanner flag + 15m higher-high breakout |
| Stop / TP | 0.4% / 0.8% (~0.5R / 1R at 0.75% risk) |
| Flat | 21:00 UTC |
| Daily caps | +3R profit / −2R loss; max 8 trades/day |

Strategy D (5m scalp) **disabled** in `config/intraday.yaml` until ID3.

---

# **3 Commands**

```bash
# ID0 — ingest 15m candles (Fly collector does this hourly; local optional)
uv run aegis-intraday-ingest
uv run aegis-intraday-ingest --loop 900

# ID1 — backtest (needs 15m data in research DB)
uv run aegis-intraday-ingest --intraday-config config/intraday.yaml
uv run aegis-backtest-intraday --db data/intraday_research.sqlite

# ID2 — paper trading (Fly: AEGIS_INTRADAY_ENABLED=1 on aegis-collector)
uv run aegis-intraday-paper-run --loop 60

# Scoreboards (included in unified daily Telegram summary)
uv run aegis-intraday-scorecard
uv run aegis-intraday-kpi
```

---

# **4 Phase 1 proof gate (ID4)**

All must hold for **4 consecutive weeks**:

- [ ] Paper equity starts at **$400**
- [ ] Weekly net P&L ≥ **$50**
- [ ] ≥ **5 win days** per week (net day P&L > $0)
- [ ] ≥ **80** closed trades cumulative
- [ ] Max weekly drawdown ≤ **8%**
- [ ] Config frozen — no param tweaks mid-clock

Fail any week → reset the 4-week proof clock.

---

# **5 KPI log**

| Week of | Week P&L | Win days | Trades | Expectancy | Pass? | Notes |
| ------- | -------- | -------- | ------ | ---------- | ----- | ----- |
| 2026-06-17 | — | — | 0 | — | — | ID2 live on Fly; ID1 backtest fail (0 trades); paper clock day 0 |

---

# **6 Immediate Next Actions**

1. Let ID0 14-day ingest clock run on Fly (no collector restarts).
2. Revisit ID1 after 30+ days 15m data — widen universe or relax breakout if still 0 trades.
3. Sunday KPI row; watch `/intraday` and daily HTML summary for first closed trades.
4. ID3 only after 2 weeks stable C watchlist.

*Last updated: June 17, 2026*
