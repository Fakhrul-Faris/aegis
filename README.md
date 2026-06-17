# Aegis

Autonomous crypto trading system. Staged two-strategy bot:

- **Strategy B - statistical arbitrage** (Hyperliquid perps): Kalman-filtered
  hedge ratios, FDR-corrected cointegration screening, Z-score entries with
  time stops. Goes live first.
- **Strategy A - swing momentum** (Kraken spot): EMA/RSI plus a volume anomaly
  scanner. Paper-only until promoted on logged evidence.

Both governed by a risk-based sizing engine (0.5-1.0% of equity per trade),
a per-asset regime detector, correlation guards, and Monte Carlo-calibrated
circuit breakers.

The full specification lives in the repo root:

- [`Aegis Concept.md`](Aegis%20Concept.md) v3.0 — architecture and math
- [`Aegis Tasks & Milestones.md`](Aegis%20Tasks%20%26%20Milestones.md) — task list, gates, KPI log
- [`Aegis Intraday Tasks & Milestones.md`](Aegis%20Intraday%20Tasks%20%26%20Milestones.md) — Strategy C/D day & scalp paper track

## Setup

Requires [uv](https://docs.astral.sh/uv/) (manages Python 3.12 automatically):

```bash
uv sync --dev          # create venv + install deps
cp .env.example .env   # then fill in secrets (never committed)
```

## Development

```bash
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
```

## Architecture rules (enforced by tests)

1. **Venue boundary:** only `aegis/execution/` may import exchange client
   libraries. Everything else talks to venues through the interfaces in
   `aegis/core/` (`MarketData`, `OrderExecutor`, `AccountState`).
   `tests/test_core_boundary.py` fails the build on violations.
2. **Config safety:** the bot refuses to start in `live` mode until the
   kill-switch drawdown threshold has been calibrated from the Monte Carlo
   envelope (deliberately `null` in `config/config.yaml`).
3. **Secrets:** environment/`.env` only. The config loader never reads
   secrets from YAML.

## Layout

```
src/aegis/
  core/        domain models + venue-agnostic interfaces
  data/        candle ingestion, anomaly scanner, SQLite persistence
  strategy/    Strategy B (pairs) and Strategy A (momentum, paper)
  risk/        sizing, correlation guard, breakers
  execution/   venue adapters, maker-then-IOC two-leg execution
  portfolio/   signal ranking and risk budget allocation
  monitor/     Telegram alerts, daily summaries
research/      offline studies (screening runs, calibrations) - see its README
config/        non-secret runtime configuration
tests/
```

## Status

Phase 2 complete; Phase 3 paper trading in progress. Milestones:

- **M0, M2:** passed
- **M3 (Strategy B cointegration):** failed — Strategy A is the primary path
- **M4:** 20+ testnet spreads + leg-2 drill done; **7-day soak running on Fly** (→ Jun 18)
- **M1 gate:** ~Jun 13 — run `uv run aegis-m1-check` (do not restart Fly collector before then)

Mode: `paper`. Ops:

```bash
uv run aegis-doctor              # health check
uv run aegis-portfolio --loop 14400
./deploy/install-launchd.sh      # ingest + scanner + portfolio
./deploy/sync-collector-db.sh    # pull Fly DB for local paper
```

Runbook: `deploy/ops.md`
