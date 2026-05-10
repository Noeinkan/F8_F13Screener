#!/usr/bin/env bash
# Continuous deployment: push to GitHub then update the VPS.
# Usage (from Git Bash / WSL / Mac terminal):
#   bash deploy/deploy.sh
#   bash deploy/deploy.sh --skip-push   # only restart VPS, no git push
set -euo pipefail

VPS="root@77.42.70.26"
APP_DIR="/opt/F8_F13Screener"
SKIP_PUSH=false

for arg in "$@"; do
    [ "$arg" = "--skip-push" ] && SKIP_PUSH=true
done

if [ "$SKIP_PUSH" = false ]; then
    echo "→ Pushing to GitHub..."
    git push origin main
fi

echo "→ Syncing source files to VPS..."
rsync -az --exclude '__pycache__' --exclude '*.pyc' src/ "$VPS:$APP_DIR/src/" 2>/dev/null \
    || scp -r src/ "$VPS:$APP_DIR/src/"

echo "→ Deploying to VPS ($VPS)..."
ssh "$VPS" bash <<REMOTE
set -euo pipefail
cd "$APP_DIR"
# Sync code (caller must scp or the repo must be public for git pull)
"$APP_DIR/venv/bin/pip" install --quiet -r requirements.txt
systemctl restart f8-screener
if systemctl is-active --quiet f8-dashboard; then
    systemctl restart f8-dashboard
fi
echo "✓ VPS aggiornato"
REMOTE

echo "✓ Deploy completato"
echo "   Log live: ssh $VPS 'journalctl -u f8-screener -f'"
