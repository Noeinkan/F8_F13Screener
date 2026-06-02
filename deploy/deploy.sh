#!/usr/bin/env bash
# Continuous deployment: push the current commit, then update the VPS from Git.
# Usage (from Git Bash / WSL / Mac terminal):
#   bash deploy/deploy.sh
#   bash deploy/deploy.sh --skip-push   # deploy current commit if it is already on origin/main
#   bash deploy/deploy.sh --skip-tests  # skip local test gate
#   bash deploy/deploy.sh --tests "tests/test_storage.py -q"
#   bash deploy/deploy.sh --rebuild-db  # rebuild DuckDB used by dashboard
#   bash deploy/deploy.sh --rebuild-db --workers 2
set -euo pipefail

VPS="root@77.42.70.26"
APP_DIR="/opt/F8_F13Screener"
DEPLOY_BRANCH="main"
SKIP_PUSH=false
SKIP_TESTS=false
TEST_ARGS="tests/"
REBUILD_DB=false
WORKERS=1

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-push)
            SKIP_PUSH=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --tests)
            if [ $# -lt 2 ]; then
                echo "Errore: --tests richiede una stringa argomenti pytest"
                exit 1
            fi
            TEST_ARGS="$2"
            shift 2
            ;;
        --rebuild-db)
            REBUILD_DB=true
            shift
            ;;
        --workers)
            if [ $# -lt 2 ]; then
                echo "Errore: --workers richiede un valore numerico"
                exit 1
            fi
            WORKERS="$2"
            shift 2
            ;;
        *)
            echo "Argomento non riconosciuto: $1"
            echo "Uso: bash deploy/deploy.sh [--skip-push] [--skip-tests] [--tests \"...\"] [--rebuild-db] [--workers N]"
            exit 1
            ;;
    esac
done

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
LOCAL_COMMIT="$(git rev-parse HEAD)"
REPO_URL="$(git remote get-url origin)"
DEPLOY_REPO_URL="${DEPLOY_REPO_URL:-}"
DEPLOY_GITHUB_TOKEN="${DEPLOY_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}"
GITHUB_REPO_PATH=""

if [[ "$REPO_URL" =~ ^https://github\.com/(.+)$ ]]; then
    GITHUB_REPO_PATH="${BASH_REMATCH[1]}"
elif [[ "$REPO_URL" =~ ^git@github\.com:(.+)$ ]]; then
    GITHUB_REPO_PATH="${BASH_REMATCH[1]}"
fi

if [ -z "$DEPLOY_REPO_URL" ]; then
    if [ -n "$DEPLOY_GITHUB_TOKEN" ] && [ -n "$GITHUB_REPO_PATH" ]; then
        DEPLOY_REPO_URL="https://x-access-token:${DEPLOY_GITHUB_TOKEN}@github.com/${GITHUB_REPO_PATH}"
    elif [ -n "$GITHUB_REPO_PATH" ]; then
        DEPLOY_REPO_URL="git@github.com:${GITHUB_REPO_PATH}"
    else
        DEPLOY_REPO_URL="$REPO_URL"
    fi
fi

if [ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]; then
    echo "Errore: deploy consentito solo da '$DEPLOY_BRANCH' (branch corrente: '$CURRENT_BRANCH')"
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "Errore: working tree non pulito. Commit/stash le modifiche prima del deploy."
    git status --short
    exit 1
fi

if [ "$SKIP_TESTS" = false ]; then
    echo "→ Running local tests before deploy..."

    if [ -x ".venv/Scripts/python.exe" ]; then
        TEST_PYTHON=".venv/Scripts/python.exe"
    elif [ -x "venv/Scripts/python.exe" ]; then
        TEST_PYTHON="venv/Scripts/python.exe"
    elif [ -x ".venv/bin/python" ]; then
        TEST_PYTHON=".venv/bin/python"
    elif [ -x "venv/bin/python" ]; then
        TEST_PYTHON="venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        TEST_PYTHON="python3"
    elif command -v python >/dev/null 2>&1; then
        TEST_PYTHON="python"
    else
        echo "Errore: nessun interprete Python trovato per eseguire pytest"
        exit 1
    fi

    # shellcheck disable=SC2086
    $TEST_PYTHON -m pytest $TEST_ARGS
    echo "✓ Test gate passed"
fi

if [ "$SKIP_PUSH" = false ]; then
    echo "→ Pushing $DEPLOY_BRANCH to GitHub..."
    git push origin "$DEPLOY_BRANCH"
fi

echo "→ Deploying commit ${LOCAL_COMMIT:0:12} to VPS ($VPS)..."
if [ -n "$GITHUB_REPO_PATH" ]; then
    if [ -n "$DEPLOY_GITHUB_TOKEN" ]; then
        echo "→ VPS repository auth: HTTPS token (repo: $GITHUB_REPO_PATH)"
    else
        echo "→ VPS repository auth: SSH key (repo: $GITHUB_REPO_PATH)"
    fi
else
    echo "→ VPS repository URL configured from origin"
fi
ssh "$VPS" bash -s -- "$APP_DIR" "$DEPLOY_REPO_URL" "$DEPLOY_BRANCH" "$LOCAL_COMMIT" "$REBUILD_DB" "$WORKERS" <<'REMOTE'
set -euo pipefail
APP_DIR="$1"
REPO_URL="$2"
DEPLOY_BRANCH="$3"
LOCAL_COMMIT="$4"
REBUILD_DB="$5"
WORKERS="$6"

if [ ! -d "$APP_DIR/.git" ]; then
    BACKUP_DIR=""
    if [ -e "$APP_DIR" ]; then
        BACKUP_DIR="${APP_DIR}.pre-git.$(date +%Y%m%d%H%M%S)"
        echo "→ Existing non-Git app directory found; moving it to $BACKUP_DIR"
        mv "$APP_DIR" "$BACKUP_DIR"
    fi

    git clone "$REPO_URL" "$APP_DIR"

    if [ -n "$BACKUP_DIR" ]; then
        for item in config_secret.py config data cache logs src/core/data src/core/logs; do
            if [ -e "$BACKUP_DIR/$item" ]; then
                mkdir -p "$APP_DIR/$(dirname "$item")"
                rm -rf "$APP_DIR/$item"
                cp -a "$BACKUP_DIR/$item" "$APP_DIR/$item"
            fi
        done
    fi
fi
cd "$APP_DIR"
git remote set-url origin "$REPO_URL"
git fetch --prune origin "$DEPLOY_BRANCH"
git cat-file -e "$LOCAL_COMMIT^{commit}"
git reset --hard "$LOCAL_COMMIT"
SERVER_COMMIT="$(git rev-parse HEAD)"
if [ "$SERVER_COMMIT" != "$LOCAL_COMMIT" ]; then
    echo "Errore: commit server $SERVER_COMMIT diverso da commit deploy $LOCAL_COMMIT"
    exit 1
fi
echo "→ VPS source now at $(git rev-parse --short HEAD)"
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r requirements.txt
if [ "$REBUILD_DB" = true ]; then
    echo "→ Rebuild storico + DB dashboard (workers=$WORKERS)..."
    "${APP_DIR}/venv/bin/python" -m src.cli.process_historical_13f full --yes --full-refresh --save-db --workers "$WORKERS"
    echo "→ Export CSV dashboard in data/exports..."
    "${APP_DIR}/venv/bin/python" -m src.cli.process_historical_13f export --export-scope both --output-dir data/exports
fi
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
echo "   Commit: $LOCAL_COMMIT"
echo "   Log live: ssh $VPS 'journalctl -u f8-screener -f'"
echo "   Dashboard log: ssh $VPS 'journalctl -u f8-dashboard -f'"
echo "   Dashboard URL: http://77.42.70.26:8502"
if [ "$REBUILD_DB" = true ]; then
    echo "   DB rebuilt: $APP_DIR/src/core/data/13f_dashboard.duckdb"
fi
