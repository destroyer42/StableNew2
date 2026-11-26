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
# After the first install, deploy later commits with review-gateway-deploy <sha>, which runs this script with
# SOURCE_COMMIT and SOURCE_ARCHIVE_SHA256 set (docs/work_packages/DEPLOY-PROXMOX_containers.md).
set -euo pipefail
umask 022

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_NAME="stablenew.review-gateway-sync.v1.json"
SCHEMA="$SOURCE/../../docs/schemas/$SCHEMA_NAME"
DEPLOYER="$SOURCE/../deploy/stablenew_deploy.py"
SERVICE_USER="review-gateway"
PREFIX="/opt/review-gateway"
ETC="/etc/review-gateway"
CONFIG="$ETC/config.toml"
SECRET_FILE="$ETC/sync_secret"
IMMICH_KEY_FILE="$ETC/immich_api_key"
STATE="/var/lib/review-gateway"
DEPLOY_STATE="/var/lib/review-gateway-deploy"

fail() { echo "install: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "run as root"
[ -f "$SCHEMA" ] || fail "missing $SCHEMA (copy docs/schemas/ with the service)"
[ -f "$DEPLOYER" ] || fail "missing $DEPLOYER (copy services/deploy/ with the service)"
# Set by review-gateway-deploy; written into the release's source.json, so only lowercase hexadecimal is accepted.
case "${SOURCE_COMMIT:-}" in
    "") ;;
    *[!0-9a-f]*) fail "SOURCE_COMMIT must be 40 lowercase hexadecimal characters" ;;
    *) [ "${#SOURCE_COMMIT}" -eq 40 ] || fail "SOURCE_COMMIT must be 40 lowercase hexadecimal characters" ;;
esac
case "${SOURCE_ARCHIVE_SHA256:-}" in
    "") ;;
    *[!0-9a-f]*) fail "SOURCE_ARCHIVE_SHA256 must be 64 lowercase hexadecimal characters" ;;
    *) [ "${#SOURCE_ARCHIVE_SHA256}" -eq 64 ] || fail "SOURCE_ARCHIVE_SHA256 must be 64 lowercase hexadecimal characters" ;;
esac
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
# The deployer's state: readable by the service for the PC's deploy status (no secrets in it), backups root-only.
install -d -m 0755 "$DEPLOY_STATE"
install -d -m 0700 "$DEPLOY_STATE/backups"
# DEPLOY-2: the one place the service writes for the deployer. Root reads it without following links.
install -d -m 0770 -o root -g "$SERVICE_USER" "$DEPLOY_STATE/inbox"

# Build the new version beside the running one; nothing live changes until it has been checked.
RELEASE="$PREFIX/releases/$(date -u +%Y%m%dT%H%M%SZ)-$$"
APP="$RELEASE/app"
VENV="$RELEASE/venv"
SWITCHED=0
trap '[ "$SWITCHED" -eq 1 ] || rm -rf "$RELEASE"' EXIT
install -d -m 0755 "$RELEASE" "$APP" "$APP/schema" "$APP/review_gateway" "$APP/review_gateway/static" "$APP/deploy"
install -m 0644 "$SOURCE"/review_gateway/*.py "$APP/review_gateway/"
install -m 0644 "$SOURCE"/review_gateway/static/* "$APP/review_gateway/static/"
install -m 0644 "$SOURCE/requirements.txt" "$APP/requirements.txt"
install -m 0644 "$SOURCE/review-gateway.service" "$APP/review-gateway.service"
install -m 0644 "$SOURCE/review-gateway-deploy.path" "$SOURCE/review-gateway-deploy.service" "$APP/"
install -m 0644 "$SCHEMA" "$APP/schema/$SCHEMA_NAME"
install -m 0644 "$DEPLOYER" "$APP/deploy/stablenew_deploy.py"
json_or_null() { if [ -n "$1" ]; then printf '"%s"' "$1"; else printf 'null'; fi; }
printf '{"commit": %s, "archive_sha256": %s, "installed_at": "%s"}\n' "$(json_or_null "${SOURCE_COMMIT:-}")" \
    "$(json_or_null "${SOURCE_ARCHIVE_SHA256:-}")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RELEASE/source.json"
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

# DEPLOY-2 (owner decision 2): the PC may start deploys unless the console turned it off with
# review-gateway-deploy remote off. Written only when missing, so an upgrade never turns it back on.
[ -e "$ETC/remote-deploy" ] || printf 'enabled\n' > "$ETC/remote-deploy"
chown root:root "$ETC/remote-deploy"
chmod 0644 "$ETC/remote-deploy"

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

# A consistent copy of the database from before this release first opens it, so a rollback after a migration can
# restore it (review-gateway-deploy). The service is stopped here, so nothing is written after the copy.
if [ -f "$DATA_DIR/gateway.sqlite3" ]; then
    (umask 077 && "$VENV/bin/python" -I -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' \
        "$DATA_DIR/gateway.sqlite3" "$DEPLOY_STATE/backups/$(basename "$RELEASE").sqlite3")
fi

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

# Deploy later commits of main: root, the container's own Python, isolated from the current directory.
cat > /usr/local/sbin/review-gateway-deploy <<EOF
#!/bin/sh
# Deploy a commit of StableNew's main to this gateway: review-gateway-deploy <sha> | status | rollback
exec $(command -v python3) -I $PREFIX/current/app/deploy/stablenew_deploy.py "\$@"
EOF
chmod 0755 /usr/local/sbin/review-gateway-deploy

install -m 0644 "$APP/review-gateway.service" /etc/systemd/system/review-gateway.service
install -m 0644 "$APP/review-gateway-deploy.path" /etc/systemd/system/review-gateway-deploy.path
install -m 0644 "$APP/review-gateway-deploy.service" /etc/systemd/system/review-gateway-deploy.service
install -d -m 0755 /etc/systemd/system/review-gateway.service.d
# If the media mount is missing, do not start and fill the root disk instead.
printf '[Unit]\nRequiresMountsFor="%s"\n' "$MEDIA_DIR" > /etc/systemd/system/review-gateway.service.d/media.conf
systemctl daemon-reload
systemctl enable review-gateway
systemctl enable --now review-gateway-deploy.path
systemctl restart review-gateway

# Keep the new release and the one before it, and the database backups taken for them.
for old in "$PREFIX"/releases/*; do
    if [ "$old" != "$RELEASE" ] && [ "$old" != "$PREVIOUS" ]; then
        rm -rf "$old"
    fi
done
for backup in "$DEPLOY_STATE"/backups/*.sqlite3; do
    [ -e "$backup" ] || continue
    kept="$PREFIX/releases/$(basename "$backup" .sqlite3)"
    if [ "$kept" != "$RELEASE" ] && [ "$kept" != "$PREVIOUS" ]; then
        rm -f "$backup"
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
echo "  release:     $RELEASE (commit ${SOURCE_COMMIT:-not recorded})"
echo "  deploy:      review-gateway-deploy <sha> | status | rollback | remote on|off"
echo "  from the PC: remote deploy is $(cat "$ETC/remote-deploy") (python -m tools.review_gateway_deploy request <sha>)"
