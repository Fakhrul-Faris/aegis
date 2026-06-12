#!/bin/bash
# Pull the Fly collector SQLite to local aegis.sqlite for paper/scanner joins.
# Stop launchd agents first — copying over a live WAL file corrupts the DB.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="${AEGIS_FLY_APP:-aegis-collector}"
REMOTE_PATH="${AEGIS_REMOTE_DB:-/data/aegis.sqlite}"
LOCAL="${AEGIS_SQLITE:-$REPO/aegis.sqlite}"
STAGING="${LOCAL}.fly-sync"
AGENTS=(com.aegis.ingest com.aegis.scanner com.aegis.portfolio com.aegis.kpi com.aegis.telegrambot)

cd "$REPO"

if ! command -v fly >/dev/null 2>&1; then
    echo "fly CLI not found — install from https://fly.io/docs/flyctl/install/" >&2
    exit 1
fi

for label in "${AGENTS[@]}"; do
    plist="$HOME/Library/LaunchAgents/$label.plist"
    if launchctl list 2>/dev/null | grep -q "$label"; then
        echo "Stopping $label ..."
        launchctl unload "$plist" 2>/dev/null || true
    fi
done

echo "Fetching $REMOTE_PATH from $APP ..."
fly ssh sftp get "$REMOTE_PATH" "$STAGING" -a "$APP"

if [[ -f "$LOCAL" ]]; then
    cp "$LOCAL" "${LOCAL}.bak.$(date +%Y%m%d-%H%M%S)"
fi
rm -f "${LOCAL}" "${LOCAL}-wal" "${LOCAL}-shm"
mv "$STAGING" "$LOCAL"

if ! sqlite3 "$LOCAL" "PRAGMA integrity_check;" | grep -qx "ok"; then
    echo "ERROR: downloaded DB failed integrity_check" >&2
    exit 1
fi

for label in "${AGENTS[@]}"; do
    plist="$HOME/Library/LaunchAgents/$label.plist"
    if [[ -f "$plist" ]]; then
        launchctl load "$plist" 2>/dev/null || true
    fi
done

echo "Synced to $LOCAL"
echo "Run: uv run aegis-doctor"
