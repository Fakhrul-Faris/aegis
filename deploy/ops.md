# Aegis operations runbook

Daily and milestone commands for running the stack smoothly. See
`Aegis Tasks & Milestones.md` for gate criteria.

## First boot / after clone

```bash
uv sync --dev
cp .env.example .env   # fill secrets
uv run aegis-doctor    # fix any issues before trusting the stack
./deploy/install-launchd.sh
```

## Health checks

| Command | When | Pass |
|---------|------|------|
| `uv run aegis-doctor` | Daily or after changes | exit 0, no critical issues |
| `launchctl list \| grep com.aegis` | Daily | second column `0` for each agent |
| `uv run aegis-summary` | Daily (or read Telegram) | snapshots > 0, flags accumulating |
| `fly status -a aegis-collector` | Weekly | machine started |
| `fly logs -a aegis-testnet-soak` | During soak (→ Jun 18) | no crash loops |

## Agents (macOS launchd)

| Label | Interval | Role |
|-------|----------|------|
| `com.aegis.ingest` | 1h | Candle backfill + gap repair |
| `com.aegis.scanner` | 1h | CoinGecko anomaly flags |
| `com.aegis.portfolio` | 4h | Strategy A paper cycle |

Install/reload: `./deploy/install-launchd.sh`

Paper cycle manual run:

```bash
uv run aegis-portfolio              # one cycle
uv run aegis-portfolio --loop 14400 # same as launchd agent
```

## Config freeze (P3.1)

First paper run freezes Strategy A + risk tier parameters in SQLite.
Any later config change without reset raises `ConfigError`.

Document the change, then:

```bash
uv run aegis-portfolio --reset-config-freeze
```

This starts a **new 8-week paper clock**.

## M1 gate (~Jun 13)

Do **not** redeploy the Fly collector or restart it mid-window — that voids
the 72h clock.

After Jun 13:

```bash
./deploy/sync-collector-db.sh   # optional: refresh local DB from Fly
uv run aegis-m1-check           # full gate incl. reconcile
uv run aegis-m1-check --skip-reconcile   # if offline
```

Mark M1 in Tasks & Milestones when all checks pass.

## Testnet soak (M4, running → Jun 18)

- Fly app: `aegis-testnet-soak` (sin)
- **Do not** run local soak or manual testnet trades on the soak wallet
- Verdict Jun 18: clean logs, no orphan orders, Telegram summaries received

## Sync collector DB

**Stop launchd agents first** (the script does this automatically). Copying over a
live WAL file corrupts SQLite.

```bash
./deploy/sync-collector-db.sh
```

Do not sync while ingest/scanner/portfolio are writing unless you use the script.

Paper AGGRESSIVE entries need `scanner_flags` when a 3x volume anomaly occurs
(zero flags so far is normal in quiet markets). Strategy A uses Kraken live
quotes; no HL testnet needed for paper.

## Incident response

| Symptom | Action |
|---------|--------|
| Scanner silent 24h | Check `com.aegis.scanner`, CoinGecko rate limits, Telegram |
| `aegis-doctor` flags empty candles | Run ingest or sync-collector-db |
| Paper config changed error | Intentional → `--reset-config-freeze`; else revert config |
| Breaker / kill switch in logs | Investigate equity path; do not override without memo |
| Soak crash | `fly logs -a aegis-testnet-soak`; do not restart wallet blindly |

## Logs

```bash
tail -f logs/aegis.jsonl
tail -f logs/launchd-portfolio.err
```
