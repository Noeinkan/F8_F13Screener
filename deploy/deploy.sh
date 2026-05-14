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
if command -v rsync >/dev/null 2>&1; then
    rsync -az \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude 'core/data/' \
        --exclude 'core/logs/' \
        --exclude 'core/*.csv' \
        src/ "$VPS:$APP_DIR/src/"
else
    find src -type f \
        ! -path '*/__pycache__/*' \
        ! -name '*.pyc' \
        ! -path 'src/core/data/*' \
        ! -path 'src/core/logs/*' \
        ! -path 'src/core/*.csv' \
        -print0 \
        | tar --null -T - -cf - \
        | ssh "$VPS" "cd '$APP_DIR' && tar -xf -"
fi

echo "→ Syncing root files to VPS..."
scp requirements.txt "$VPS:$APP_DIR/requirements.txt"

echo "→ Syncing service files to VPS..."
scp deploy/f8-screener.service deploy/f8-dashboard.service "$VPS:$APP_DIR/deploy/"

echo "→ Deploying to VPS ($VPS)..."
ssh "$VPS" bash <<REMOTE
set -euo pipefail
cd "$APP_DIR"
# Sync code (caller must scp or the repo must be public for git pull)
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r requirements.txt
sed -i 's/\r$//' deploy/f8-screener.service deploy/f8-dashboard.service
cp deploy/f8-screener.service /etc/systemd/system/
cp deploy/f8-dashboard.service /etc/systemd/system/
sed -i 's/\r$//' /etc/systemd/system/f8-screener.service /etc/systemd/system/f8-dashboard.service
if command -v ufw >/dev/null 2>&1; then
    ufw allow 8502/tcp >/dev/null 2>&1 || true
fi
systemctl daemon-reload
systemctl enable f8-screener f8-dashboard >/dev/null 2>&1 || true
systemctl restart f8-screener
systemctl restart f8-dashboard
echo "✓ VPS aggiornato"
REMOTE

echo "✓ Deploy completato"
echo "   Log live: ssh $VPS 'journalctl -u f8-screener -f'"
echo "   Dashboard log: ssh $VPS 'journalctl -u f8-dashboard -f'"
echo "   Dashboard URL: http://77.42.70.26:8502"
