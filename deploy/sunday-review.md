# Sunday review ritual (P3.2) — ~30 minutes

Run every **Sunday 17:00 UTC** (after auto KPI if configured). Blocks M5/M6 discipline.

## Before you start

```bash
cd aegis
uv run aegis-doctor
uv run aegis-m5-check          # config freeze + M4 reference
uv run aegis-kpi-report --print-only   # draft Section 5 row
```

Optional: sync Fly DB first if local is stale:

```bash
./deploy/sync-collector-db.sh
```

Telegram quick check: `/status` · `/paper` · `/forex` · `/intraday` · `/progress`

---

## Checklist (check each box in the log / KPI notes)

### 1. KPI log (5 min)

- [ ] Fill **crypto** row in `docs/Aegis Tasks & Milestones.md` Section 5
- [ ] Fill **forex** row in `docs/Aegis Forex Tasks & Milestones.md` Section 5 (if FX5+)
- [ ] Fill **intraday** row in `docs/Aegis Intraday Tasks & Milestones.md` Section 5 (if ID2+)

Fields: equity, trades (wk/cum), win rate, expectancy CI, max DD, slippage vs model, uptime, gates breached, notes.

### 2. Reconciliation chain (10 min)

Every **taken** signal should trace: signal → order → fill → position → closed P&L (or open mark).

```bash
uv run python3 -c "
from aegis.config import load_config
from aegis.data import db
c = load_config()
conn = db.connect(c.sqlite_path)
for row in conn.execute('''
  SELECT COUNT(*) FROM signals WHERE taken=1
'''): print('taken signals', row[0])
for row in conn.execute('''
  SELECT COUNT(*) FROM positions WHERE closed_ts_ms IS NULL
'''): print('open positions', row[0])
conn.close()
"
```

- [ ] No orphan open orders (testnet/soak wallet separate — ignore soak app)
- [ ] Open positions have entry + context_json
- [ ] Closed positions have exit_reason + r_multiple

### 3. Slippage vs model (5 min)

- [ ] Compare observed spread/slippage to `risk.slippage_gate_pct` (0.08%)
- [ ] **Two consecutive weeks worse than model → pause scaling decisions** (do not tweak params)

### 4. Skipped trades & gates (5 min)

- [ ] Review `signals WHERE taken=0` — skip_reasons behaving as designed?
- [ ] Scanner: flags accumulating? (`scanner_flags` count trend)
- [ ] Any `CRITICAL` Telegram in the week? Root cause noted in KPI notes column

### 5. Config freeze (2 min)

- [ ] `aegis-m5-check` PASS — **no param changes** this week
- [ ] If you *must* change strategy/risk/scanner thresholds → document + `--reset-config-freeze` (restarts 8-week M6 clock)

### 6. Track-specific notes (3 min)

| Track | Watch |
|-------|--------|
| Strategy A swing | AGGRESSIVE fills after scanner flags; regime labels updating |
| Forex FX5 | Event fade demo trades; calendar WATCH alerts only on high-impact |
| Intraday ID2 | `/intraday` scorecard; 15m ingest clock (ID0); 0 trades OK early |

### 7. Path to live (1 min)

- [ ] `/progress` or `uv run aegis-summary` — M6 weeks remaining if freeze started
- [ ] One sentence: **biggest risk this week** (data, execution, attention split)

---

## M6 clock reminder

Formal **8-week** Strategy A paper gate (M6) starts from **first config freeze** (`strategy_a_paper` in `config_freeze`).

- Freeze hash changes → clock resets
- M6 needs: ≥8 weeks, ≥40 trades, expectancy CI vs backtest, slippage validated, clean final 4 weeks
- Strategy B (M3 failed) is **not** on the live path — Strategy A promotion at M8

---

## After review

1. Commit KPI row updates (optional, when you batch doc updates)
2. If anything broke: `deploy/ops.md` incident table
3. Do **not** restart `aegis-testnet-soak` (M4 closed)

*First ritual: mark M5 ☑ in Tasks & Milestones when this checklist is scheduled recurring.*
