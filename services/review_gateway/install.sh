#!/usr/bin/env bash
# Install or upgrade the review gateway in its Debian container. Run as root from a copy of the repository
# that holds services/review_gateway/ and docs/schemas/ (see docs/runbooks/review_gateway.md). Safe to run
# again: the settings, the sync secret, the certificate and the data are kept, and a failed upgrade leaves
# the running version in place.
#
#   SYNC_HOST=192.168.1.50 MEDIA_DIR=/mnt/review-media IMMICH_URL=http://192.168.1.20:2283 \
#       bash services/review_gateway/install.sh
#
# SYNC_HOST (the container's LAN address), MEDIA_DIR and IMMICH_URL apply only when the settings file is first
# written. The Immich API key is never given to the installer: paste it into the file named at the end.
set -euo pipefail
umask 022

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_NAME="stablenew.review-gateway-sync.v1.json"
SCHEMA="$SOURCE/../../docs/schemas/$SCHEMA_NAME"
SERVICE_USER="review-gateway"
PREFIX="/opt/review-gateway"
ETC="/etc/review-gateway"
CONFIG="$ETC/config.toml"
SECRET_FILE="$ETC/sync_secret"
IMMICH_KEY_FILE="$ETC/immich_api_key"
STATE="/var/lib/review-gateway"

fail() { echo "install: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "run as root"
[ -f "$SCHEMA" ] || fail "missing $SCHEMA (copy docs/schemas/ with the service)"
command -v python3 >/dev/null || fail "python3 is required"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail "Python 3.11 or newer is required"
if [ -n "${MEDIA_DIR:-}" ]; then
    case "$MEDIA_DIR" in
        *[\"\\]*) fail "MEDIA_DIR must not contain quotes or backslashes" ;;
        /*) ;;
        *) fail "MEDIA_DIR must be an absolute path" ;;
    esac
fi
case "${IMMICH_URL:-}" in
    *[\"\\[:space:]]*) fail "IMMICH_URL must not contain quotes, backslashes or spaces" ;;
esac
# Written to the settings only once, so a value the service would refuse is stopped before that.
case "${IMMICH_URL:-}" in
    "" | http://* | https://*) ;;
    *) fail "IMMICH_URL must start with http:// or https://" ;;
esac
if ! python3 -c 'import ensurepip' 2>/dev/null || ! command -v openssl >/dev/null; then
    apt-get update
    apt-get install -y --no-install-recommends python3-venv openssl
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$STATE" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -m 0755 "$PREFIX" "$PREFIX/releases"
install -d -m 0750 -o root -g "$SERVICE_USER" "$ETC"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE"

# Build the new version beside the running one; nothing live changes until it has been checked.
RELEASE="$PREFIX/releases/$(date -u +%Y%m%dT%H%M%SZ)-$$"
APP="$RELEASE/app"
VENV="$RELEASE/venv"
SWITCHED=0
trap '[ "$SWITCHED" -eq 1 ] || rm -rf "$RELEASE"' EXIT
install -d -m 0755 "$RELEASE" "$APP" "$APP/schema" "$APP/review_gateway" "$APP/review_gateway/static"
install -m 0644 "$SOURCE"/review_gateway/*.py "$APP/review_gateway/"
install -m 0644 "$SOURCE"/review_gateway/static/* "$APP/review_gateway/static/"
install -m 0644 "$SOURCE/requirements.txt" "$APP/requirements.txt"
install -m 0644 "$SOURCE/review-gateway.service" "$APP/review-gateway.service"
install -m 0644 "$SCHEMA" "$APP/schema/$SCHEMA_NAME"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --require-hashes --only-binary :all: --no-input --disable-pip-version-check -r "$APP/requirements.txt"
find "$APP" -name '*.py' -print0 | xargs -0 "$VENV/bin/python" -m py_compile

if [ ! -f "$CONFIG" ]; then
    SYNC_HOST="${SYNC_HOST:-$(ip -4 -o route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')}"
    [ -n "$SYNC_HOST" ] || fail "could not find the LAN address; run again with SYNC_HOST=<address>"
    cat > "$CONFIG" <<EOF
# StableNew review gateway. See docs/runbooks/review_gateway.md in the StableNew repository.
data_dir = "$STATE/data"
media_dir = "${MEDIA_DIR:-$STATE/media}"
secret_file = "$SECRET_FILE"

# The container's LAN address. Only the PC may reach this port (Proxmox firewall); never a tailnet address.
sync_host = "$SYNC_HOST"
sync_port = 9443
# The PC pins this certificate by the SHA-256 the installer prints.
sync_tls_cert = "$ETC/sync.crt"
sync_tls_key = "$ETC/sync.key"

# Immich, where kept items go; empty means they wait. The API key is read from the file, never from here.
immich_url = "${IMMICH_URL:-}"
immich_key_file = "$IMMICH_KEY_FILE"

# Loopback only; "tailscale serve" publishes it.
phone_host = "127.0.0.1"
phone_port = 8443
EOF
    chown root:"$SERVICE_USER" "$CONFIG"
    chmod 0640 "$CONFIG"
fi

setting() { python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))[sys.argv[2]])' "$CONFIG" "$1"; }
gateway() { (cd "$APP" && "$VENV/bin/python" -B -m review_gateway --config "$CONFIG" "$@"); }

gateway init-secret
chown "$SERVICE_USER":"$SERVICE_USER" "$SECRET_FILE"
chmod 0600 "$SECRET_FILE"

TLS_CERT="$(setting sync_tls_cert)"
TLS_KEY="$(setting sync_tls_key)"
if [ ! -s "$TLS_CERT" ] || [ ! -s "$TLS_KEY" ]; then
    echo "install: creating the sync certificate (a new fingerprint to enter on the PC)"
    (umask 077 && openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
        -subj "/CN=review-gateway" -keyout "$TLS_KEY" -out "$TLS_CERT")
    chown "$SERVICE_USER":"$SERVICE_USER" "$TLS_CERT" "$TLS_KEY"
    chmod 0644 "$TLS_CERT"
    chmod 0600 "$TLS_KEY"
fi

# An empty, owner-only file for the Immich API key; a key already there is kept.
KEY_PATH="$(python3 -c 'import os, sys, tomllib; c = tomllib.load(open(sys.argv[1], "rb")); print(c.get("immich_key_file") or os.path.join(os.path.dirname(c["secret_file"]), "immich_api_key"))' "$CONFIG")"
[ ! -L "$KEY_PATH" ] || fail "$KEY_PATH is a symbolic link; use the real path in $CONFIG"
if [ ! -e "$KEY_PATH" ]; then
    install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" /dev/null "$KEY_PATH"
fi
chown "$SERVICE_USER":"$SERVICE_USER" "$KEY_PATH"
chmod 0600 "$KEY_PATH"

(cd "$APP" && runuser -u "$SERVICE_USER" -- "$VENV/bin/python" -B -m review_gateway --config "$CONFIG" check-config)
FINGERPRINT="$(gateway fingerprint)"

DATA_DIR="$(setting data_dir)"
MEDIA_DIR="$(setting media_dir)"
if systemctl is-active --quiet review-gateway 2>/dev/null; then
    systemctl stop review-gateway
fi
# The service owns these directories' parent, so never follow a link it could have put in their place.
for directory in "$DATA_DIR" "$MEDIA_DIR"; do
    [ ! -L "$directory" ] || fail "$directory is a symbolic link; use the real path in $CONFIG"
done
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR" "$MEDIA_DIR"

PREVIOUS=""
if [ -L "$PREFIX/current" ]; then PREVIOUS="$(readlink -f "$PREFIX/current")"; fi
ln -sfn "$RELEASE" "$PREFIX/current"
SWITCHED=1

cat > /usr/local/bin/review-gateway-admin <<EOF
#!/bin/sh
# Run admin commands as the service user, so the database never gains root-owned files.
cd $PREFIX/current/app && exec runuser -u $SERVICE_USER -- $PREFIX/current/venv/bin/python -B -m review_gateway --config $CONFIG "\$@"
EOF
chmod 0755 /usr/local/bin/review-gateway-admin

install -m 0644 "$APP/review-gateway.service" /etc/systemd/system/review-gateway.service
install -d -m 0755 /etc/systemd/system/review-gateway.service.d
# If the media mount is missing, do not start and fill the root disk instead.
printf '[Unit]\nRequiresMountsFor="%s"\n' "$MEDIA_DIR" > /etc/systemd/system/review-gateway.service.d/media.conf
systemctl daemon-reload
systemctl enable review-gateway
systemctl restart review-gateway

# Keep the new release and the one before it.
for old in "$PREFIX"/releases/*; do
    if [ "$old" != "$RELEASE" ] && [ "$old" != "$PREVIOUS" ]; then
        rm -rf "$old"
    fi
done

sleep 3
systemctl is-active --quiet review-gateway || fail "installed but not running: journalctl -u review-gateway${PREVIOUS:+ (previous version: $PREVIOUS)}"

echo
echo "Review gateway installed."
echo "  settings:    $CONFIG"
echo "  sync URL:    https://$(setting sync_host):9443"
echo "  sync secret: $SECRET_FILE  (enter it once in StableNew's pairing settings)"
echo "  certificate SHA-256: $FINGERPRINT  (enter it with the secret)"
echo "  phone app:   publish with: tailscale serve --bg --https=443 http://127.0.0.1:8443"
echo "  Immich:      1. set immich_url in $CONFIG (add the line if it is not there)"
echo "               2. paste an API key with only asset.upload, asset.update, album.read,"
echo "                  album.create and albumAsset.create into $KEY_PATH"
echo "               3. systemctl restart review-gateway && review-gateway-admin immich-check"
echo "  admin:       review-gateway-admin fingerprint | devices | revoke <id> | status | purge | immich-check"
