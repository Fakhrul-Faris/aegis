#!/bin/bash
# Install Aegis collectors as hourly launchd agents (macOS).
# Idempotent: re-running replaces existing agents.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
AGENTS_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$AGENTS_DIR" "$REPO/logs"

for name in ingest scanner portfolio kpi; do
    label="com.aegis.$name"
    plist="$AGENTS_DIR/$label.plist"
    sed -e "s|__REPO__|$REPO|g" -e "s|__UV__|$UV|g" \
        "$REPO/deploy/launchd/$label.plist.template" > "$plist"
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load "$plist"
    echo "loaded $label (logs in $REPO/logs/)"
done

echo
echo "Verify with: launchctl list | grep com.aegis"
echo "Uninstall with: launchctl unload ~/Library/LaunchAgents/com.aegis.*.plist"
