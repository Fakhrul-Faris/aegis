# FX5 Demo Paper Launch

## Telegram + scheduling — Fly.io (`aegis-collector`)

Your Aegis Telegram bot runs on **Fly**, not on your Mac. Secrets live there:

```bash
fly secrets list -a aegis-collector
# TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID must be set
```

**Do not** run `aegis-telegram-bot` locally while Fly is polling (one listener per token).

### What Fly runs automatically (after `fly deploy`)

| Task | Schedule | Telegram |
| ---- | -------- | -------- |
| Crypto scan + ingest | Hourly :01:30 | — |
| **Forex paper** (Yahoo ingest + event fade) | Same hourly cycle | — |
| **Calendar WATCH** alerts | Every 15 min sidecar | Same bot |
| **Daily summary** (crypto + forex) | 16:00 UTC | Same bot |
| **Forex weekly KPI** | Sunday 17:00 UTC | Same bot |
| **`/forex`, `/status`, …** | 24/7 long-poll | Same bot |

Local `.env` Telegram vars are **optional** (debug only). Production path is Fly secrets.

## Demo data — no OANDA

Default: **Yahoo Finance** (`demo.data_source: yahoo`). No broker signup.

On Fly, forex uses the **same SQLite volume** as crypto:

```
AEGIS_FOREX_DEMO_SQLITE_PATH=/data/aegis.sqlite   # set in Dockerfile
```

## Deploy forex to Fly

```bash
fly deploy -a aegis-collector    # after M1 gate allows restart
fly logs -a aegis-collector      # look for "Forex event-fade paper active"
```

Startup Telegram message should include: `Forex event-fade paper active.`

## Validate from your Mac

```bash
# Telegram commands (Fly must be running)
# Open Telegram → send /forex or /status to your bot

fly logs -a aegis-collector --no-tail | tail -30
uv run aegis-forex-fx5-check     # local DB check (optional)
```

Ping test **on Fly** (uses Fly secrets):

```bash
fly ssh console -a aegis-collector -C "aegis-telegram-ping"
```

## Local Mac cron (optional)

Only if you want forex paper **without** redeploying Fly. Otherwise skip
`scripts/forex-crontab.example` — Fly handles it.

## Paper clock

- Frozen hash `6eaf09bf78b0d905`
- **30–60 days**, **≥15 closed trades**
- `fly deploy` / collector restart does not reset the paper clock (SQLite on volume)
