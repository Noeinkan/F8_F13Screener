#!/usr/bin/env bash
# Publishes the live dashboard at https://13f.noeinsolutions.com through the
# shared nginx edge on the VPS: certificate, vhost and password.
#
# Run it BEFORE deploy/deploy.sh on a host that does not have the vhost yet:
# the deploy closes the raw ports 5173 and 9002, and until this vhost exists
# that would leave the dashboard with no way in at all. deploy.sh checks.
#
# Usage (from Git Bash / WSL / Mac terminal, in the repo):
#   bash deploy/edge-install.sh                  install or refresh the vhost
#   bash deploy/edge-install.sh --set-password   (re)set the login first; asks for it
#
# Environment:
#   F8_DASHBOARD_USER       login name (default: beta)
#   F8_DASHBOARD_PASSWORD   password, instead of the prompt (for scripted runs)
#
# The password never leaves this machine in clear: it is hashed here (apr1,
# which nginx reads natively) and only the hash is written on the server.
set -euo pipefail

VPS="root@77.42.70.26"
DOMAIN="13f.noeinsolutions.com"
SERVER_IP="77.42.70.26"
SET_PASSWORD=false
LOGIN="${F8_DASHBOARD_USER:-beta}"

while [ $# -gt 0 ]; do
    case "$1" in
        --set-password) SET_PASSWORD=true; shift ;;
        *)
            echo "Argomento non riconosciuto: $1"
            echo "Uso: bash deploy/edge-install.sh [--set-password]"
            exit 1
            ;;
    esac
done

cd "$(dirname "$0")/.."

HASH=""
if [ "$SET_PASSWORD" = true ]; then
    command -v openssl >/dev/null 2>&1 || { echo "Errore: serve openssl per calcolare l'hash della password"; exit 1; }
    PASSWORD="${F8_DASHBOARD_PASSWORD:-}"
    if [ -z "$PASSWORD" ]; then
        read -r -s -p "Password per l'utente '$LOGIN' (non visualizzata): " PASSWORD
        echo
    fi
    [ -n "$PASSWORD" ] || { echo "Errore: password vuota"; exit 1; }
    HASH="$(printf '%s' "$PASSWORD" | openssl passwd -apr1 -stdin)"
    unset PASSWORD
fi

# ssh joins its arguments into one string that the remote shell parses again:
# an apr1 hash ("$apr1$salt$...") would be expanded as variables and an empty
# argument would vanish. Base64 has no characters the shell cares about, and
# "-" stands in for "no new password".
HASH_B64="-"
[ -n "$HASH" ] && HASH_B64="$(printf '%s' "$HASH" | base64 | tr -d '\n')"

echo "→ Uploading vhosts"
scp -q deploy/edge/f8-live.conf deploy/edge/f8-live.bootstrap.conf "$VPS:/tmp/"

ssh "$VPS" bash -s -- "$DOMAIN" "$SERVER_IP" "$LOGIN" "$HASH_B64" <<'REMOTE'
set -euo pipefail
DOMAIN="$1"; SERVER_IP="$2"; LOGIN="$3"; HASH_B64="$4"
HASH=""
[ "$HASH_B64" = "-" ] || HASH="$(printf '%s' "$HASH_B64" | base64 -d)"

VHOSTS="/opt/sites/_vhosts"
EDGE_NGINX="bep-generator-nginx-1"
CAPSAR_HEALTH="https://app.noeinsolutions.com/health"
CONF="$VHOSTS/f8-live.conf"
PASSWD="$VHOSTS/f8-live.htpasswd"

nginx_test() { docker exec "$EDGE_NGINX" nginx -t >/dev/null 2>&1; }
nginx_reload() { nginx_test && docker exec "$EDGE_NGINX" nginx -s reload >/dev/null 2>&1; }
http_code() { curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "$@" || true; }

echo "==> 1/6 DNS"
RESOLVED="$( (getent ahostsv4 "$DOMAIN" || true) | awk 'NR==1 {print $1}')"
if [ "$RESOLVED" != "$SERVER_IP" ]; then
    echo "ERRORE: $DOMAIN risolve a '${RESOLVED:-niente}', non a $SERVER_IP."
    echo "        Aggiungi il record A su Cloudflare (DNS only, nuvola grigia) e riprova."
    exit 1
fi
echo "    $DOMAIN -> $RESOLVED"

echo "==> 2/6 dashboard reachable from nginx"
# Vite must answer on the Docker bridge, where nginx looks for it.
UPSTREAM="$(docker exec "$EDGE_NGINX" sh -c 'wget -qO /dev/null --header="Host: localhost:5173" --timeout=5 http://host.docker.internal:5173/ && echo ok || echo ko')"
if [ "$UPSTREAM" != "ok" ]; then
    echo "ERRORE: nginx non raggiunge Vite su host.docker.internal:5173 (systemctl status f8-web)."
    exit 1
fi
echo "    f8-web answers on host.docker.internal:5173"

echo "==> 3/6 password"
if [ -n "$HASH" ]; then
    TMP="$(mktemp "$VHOSTS/.f8-live.htpasswd.XXXXXX")"
    case "$HASH" in
        '$apr1$'*) ;;
        *) echo "ERRORE: l'hash della password e' arrivato malformato"; rm -f "$TMP"; exit 1 ;;
    esac
    printf '%s:%s\n' "$LOGIN" "$HASH" > "$TMP"
    # nginx workers run as uid 101 inside the container and must read it;
    # nobody else needs to.
    chown root:101 "$TMP"
    chmod 640 "$TMP"
    mv "$TMP" "$PASSWD"
    echo "    login '$LOGIN' written"
elif [ -f "$PASSWD" ] && grep -q ':\$apr1\$' "$PASSWD"; then
    echo "    existing login kept"
else
    echo "ERRORE: nessuna password impostata. Rilancia con --set-password."
    exit 1
fi

echo "==> 4/6 certificate"
if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "    already issued"
else
    PREV=""
    [ -f "$CONF" ] && PREV="$(mktemp)" && cp "$CONF" "$PREV"
    cp /tmp/f8-live.bootstrap.conf "$CONF"
    if ! nginx_reload; then
        echo "ERRORE: nginx ha rifiutato il vhost di bootstrap"
        docker exec "$EDGE_NGINX" nginx -t 2>&1 | tail -5
        if [ -n "$PREV" ]; then cp "$PREV" "$CONF"; else rm -f "$CONF"; fi
        nginx_reload || true
        exit 1
    fi
    if ! certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" \
            --cert-name "$DOMAIN" --non-interactive --agree-tos --keep-until-expiring; then
        echo "ERRORE: certbot non ha emesso il certificato per $DOMAIN (dettagli sopra)"
        if [ -n "$PREV" ]; then cp "$PREV" "$CONF"; else rm -f "$CONF"; fi
        nginx_reload || true
        exit 1
    fi
    echo "    certificate issued"
fi

echo "==> 5/6 install vhost"
PREV=""
[ -f "$CONF" ] && PREV="$(mktemp)" && cp "$CONF" "$PREV"
cp /tmp/f8-live.conf "$CONF"
chmod 644 "$CONF"
restore() {
    if [ -n "$PREV" ]; then cp "$PREV" "$CONF"; else rm -f "$CONF"; fi
    nginx_reload || true
}
if ! nginx_reload; then
    echo "ERRORE: nginx -t fallito, vhost precedente ripristinato"
    docker exec "$EDGE_NGINX" nginx -t 2>&1 | tail -5
    restore
    exit 1
fi
echo "    nginx -t passed, reloaded"

echo "==> 6/6 smoke test"
# Without a login the dashboard must refuse; with a wrong one too. A 200 here
# would mean the password is not being enforced.
# `nginx -s reload` only signals the master: for a moment the old workers keep
# answering, and without this vhost the edge's default HTTPS site replies 200
# for any name. Give the new workers a few seconds before judging.
ANON=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
    ANON="$(http_code "https://$DOMAIN/")"
    [ "$ANON" = "401" ] && break
    sleep 1
done
echo "    https://$DOMAIN/ without login -> $ANON"
if [ "$ANON" != "401" ]; then
    echo "ERRORE: atteso 401 senza login, ottenuto $ANON. Vhost rimosso."
    restore
    exit 1
fi
CAPSAR="$(http_code "$CAPSAR_HEALTH")"
echo "    $CAPSAR_HEALTH -> $CAPSAR"
if [ "$CAPSAR" != "200" ]; then
    echo "ERRORE: Capsar non risponde piu' 200 dopo il reload. Vhost rimosso."
    restore
    exit 1
fi

rm -f /tmp/f8-live.conf /tmp/f8-live.bootstrap.conf
echo "==> Live: https://$DOMAIN  (login: $(cut -d: -f1 "$PASSWD"))"
REMOTE
