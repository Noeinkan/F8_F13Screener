#!/usr/bin/env bash
# One-time setup on the VPS. Run as ubuntu@77.42.70.26.
# Usage: bash deploy/install.sh
set -euo pipefail

APP_DIR="/opt/F8_F13Screener"
REPO_URL="https://github.com/Noeinkan/F8_F13Screener.git"   # update if different
APP_OWNER="$(id -un)"

echo "=== F8 F13 Screener — VPS install ==="

# 1. System packages
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv git

# 2. Clone repo (or pull if already present)
if [ -d "$APP_DIR/.git" ]; then
    echo "→ Repo già presente, aggiorno..."
    cd "$APP_DIR" && git pull
else
    echo "→ Clono il repo in $APP_DIR..."
    sudo git clone "$REPO_URL" "$APP_DIR"
    sudo chown -R "$APP_OWNER:$APP_OWNER" "$APP_DIR"
fi

cd "$APP_DIR"

# 3. Python dependencies
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r requirements.txt

# 4. Config secret (must be created manually)
if [ ! -f "$APP_DIR/config_secret.py" ]; then
    echo ""
    echo "⚠️  ATTENZIONE: crea $APP_DIR/config_secret.py"
    echo "   Usa config_secret.template.py come riferimento."
    echo ""
fi

# 5. Data directories (paths.py creates them on import, but let's be safe)
"$APP_DIR/venv/bin/python" -c "import sys; sys.path.insert(0, '$APP_DIR'); from src.core import paths" || true

# 5b. Expose Streamlit dashboard port when UFW is present
if command -v ufw >/dev/null 2>&1; then
    sudo ufw allow 8502/tcp >/dev/null 2>&1 || true
fi

# 6. Install systemd services
echo "→ Installo i servizi systemd..."
sudo sed -i 's/\r$//' "$APP_DIR/deploy/f8-screener.service" "$APP_DIR/deploy/f8-dashboard.service"
sudo cp "$APP_DIR/deploy/f8-screener.service"   /etc/systemd/system/
sudo cp "$APP_DIR/deploy/f8-dashboard.service"  /etc/systemd/system/
sudo sed -i 's/\r$//' /etc/systemd/system/f8-screener.service /etc/systemd/system/f8-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable f8-screener f8-dashboard

echo ""
echo "✓ Installazione completata."
echo ""
echo "Prossimi passi:"
echo "  1. Crea/verifica $APP_DIR/config_secret.py"
echo "  2. sudo systemctl start f8-screener"
echo "  3. sudo systemctl start f8-dashboard"
echo "  4. dashboard: http://<server-ip>:8502"
echo "  5. journalctl -u f8-screener -f        # per i log live"
echo "  6. journalctl -u f8-dashboard -f       # per il dashboard"
