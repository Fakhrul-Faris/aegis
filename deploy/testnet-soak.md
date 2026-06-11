# Testnet 7-day soak (P2.5)

Runs `aegis-testnet-soak` on Fly.io: hourly health checks, one spread every
6 hours, daily Telegram summary, auto-stop after 7 days.

## First deploy

```bash
# Create app + volume (once)
fly apps create aegis-testnet-soak
fly volumes create aegis_soak_data --size 1 -a aegis-testnet-soak --region sin

# Secrets (copy from local .env)
fly secrets set \
  TELEGRAM_BOT_TOKEN=... \
  TELEGRAM_CHAT_ID=... \
  HYPERLIQUID_WALLET_ADDRESS=... \
  HYPERLIQUID_PRIVATE_KEY=... \
  -a aegis-testnet-soak

fly deploy --config fly.testnet-soak.toml
```

## Local run (Mac awake)

```bash
uv run aegis-testnet-soak --once          # smoke test
uv run aegis-testnet-soak                 # full 7-day loop (hourly ticks)
```

State persists in `soak_state.json` next to SQLite. Soak log: `soak_log` table.

## M4 gate

Soak **started** when deploy succeeds and Telegram shows "Aegis testnet soak (daily)".
Soak **passes** when the day-7 FINAL message shows `verdict: PASS`.

Clock: 7 × 24h from first `soak_start` event in SQLite.
