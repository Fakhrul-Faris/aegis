#!/usr/bin/env bash
# Post-M1 deploy — run manually or from GitHub Actions after the 72h gate.
# Safe to run multiple times: exits 0 if deploy marker already exists on volume.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="${AEGIS_FLY_APP:-aegis-collector}"
BUFFER_MINUTES="${M1_DEPLOY_BUFFER_MINUTES:-30}"

cd "$REPO"

if ! command -v flyctl >/dev/null 2>&1; then
  echo "flyctl not found. Install: https://fly.io/docs/hands-on/install-flyctl/"
  exit 1
fi

if [[ -z "${FLY_API_TOKEN:-}" ]]; then
  echo "FLY_API_TOKEN unset. Run: export FLY_API_TOKEN=\$(fly auth token)"
  exit 1
fi

echo "Checking M1 gate on Fly ($APP)..."
if ! flyctl ssh console -a "$APP" -C "aegis-m1-check --skip-reconcile --config config/config.yaml"; then
  echo "M1 check failed on collector DB — deploy aborted (clock protected)."
  exit 1
fi

if flyctl ssh console -a "$APP" -C "test -f /data/post_m1_deploy.done.json"; then
  echo "Post-M1 deploy already completed (marker on volume). Nothing to do."
  exit 0
fi

echo "M1 passed. Deploying $APP..."
flyctl deploy -a "$APP" --remote-only --ha=false

echo "Done. Try /status in Telegram."
