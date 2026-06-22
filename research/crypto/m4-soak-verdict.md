# M4 testnet soak verdict — Jun 2026

**App:** `aegis-testnet-soak` (Fly.io sin)  
**Clock:** 2026-06-11 16:12 UTC → 2026-06-18 16:12 UTC (7 days)  
**Review date:** 2026-06-19

## Executive summary

| Criterion | Auto gate | Human M4 gate | Result |
|-----------|-----------|---------------|--------|
| 7 days unattended on Fly | elapsed ≥ 7d | same | **PASS** |
| Process crash loops | exit 0 | no fatal crash loops during 7d | **PASS** (post-day-7 Fly restart bug — fixed) |
| 20+ testnet spread trades | spreads_ok ≥ 20 | 20+ campaign + soak | **PASS** (15 soak + 20 campaign) |
| Leg-2-miss drill | done | done | **PASS** |
| Breaker drill | done | done | **PASS** |
| Zero anomalies | anomalies = 0 | testnet position dust OK if explained | **FAIL auto / PASS human** |
| Zero spread fails | spreads_fail = 0 | testnet illiquidity expected | **FAIL auto / PASS human** |
| No orphan orders | — | no sustained orphan orders | **PASS** |
| Unhandled API crashes | — | caught, logged, loop continued | **3 events, all recovered** |

**Verdict: CONDITIONAL PASS (M4 machine gate)** — infrastructure proved; testnet market quality caused expected noise.

## First 7 days (authoritative window)

| Metric | Count |
|--------|------:|
| Hourly cycles | ~162 |
| Health OK | 90 |
| Anomalies | 76 |
| Spreads OK | 15 |
| Spreads FAIL | 12 |
| Unhandled cycle crashes (logged) | 3 |

### Anomalies (dominant pattern)

From `soak_log` — stuck **SOL 0.17** testnet position from ~Jun 15:

```
unexpected_positions:[('SOL', 0.17)]
```

Likely partial leg / dust on illiquid HL testnet book. Not orphan open orders. **Action:** flatten dust on testnet wallet before any future soak.

### Spread execution

15/27 spread attempts filled both legs (56%). Failures are testnet liquidity / wide book — consistent with campaign notes. **Machine path worked** when book allowed.

### API incidents (recovered)

1. **Jun 14** — HL testnet 502 Bad Gateway (cycle 66)
2. **Jun 15** — `OrderNotFound unknownOid` (cycle 91)
3. **Jun 18** — HL testnet 504 Gateway Timeout (cycle 162)

All caught in cycle `try/except`; soak continued. **No process death during the 7-day window.**

## Post-day-7 incident (ops bug)

After Jun 18 16:12 UTC the soak correctly hit day-7 completion but:

1. Auto verdict = **NEEDS REVIEW** (`anomalies > 0`, `spreads_fail > 0`)
2. Process exited **code 1**
3. Fly `restart = always` → **crash loop** every ~15 min until Jun 19
4. `soak_complete` logged **75 extra times**; `cycle` inflated to 242

**Fixes applied:** `restart = no` on Fly machine; code exits 0 after final verdict; skips re-run if `soak_verdict.json` exists.

## M4 checklist (Tasks & Milestones)

- [x] 20+ testnet spread trades (campaign 20/20 + soak 15 ok)
- [x] Leg-2-miss drill
- [x] Breaker drill
- [x] 7-day unattended soak — **CONDITIONAL PASS** (machine reliability; testnet noise documented)

## What M4 does NOT prove

- Strategy B edge (M3 failed — expected)
- Testnet P&L or fill quality at production spreads
- Live capital readiness (M6+)

## Next steps

1. Stop / leave `aegis-testnet-soak` stopped (`restart=no`)
2. Mark M4 ☑ in Tasks & Milestones
3. Unblock M5 formal paper clock (config freeze + review ritual)
4. Flatten SOL dust on testnet wallet if reusing wallet
