"""``python -m review_gateway``: run the service, or administer it on the gateway itself (S11)."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .app import Gateway
from .config import (
    ConfigError,
    Settings,
    certificate_fingerprint,
    create_secret,
    load_settings,
)
from .immich import MINIMUM_MAJOR, PERMISSIONS, ImmichClient, ImmichError, read_key
from .server import serve

DEFAULT_CONFIG = "/etc/review-gateway/config.toml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review_gateway", description=__doc__)
    parser.add_argument("--config", default=os.environ.get("REVIEW_GATEWAY_CONFIG", DEFAULT_CONFIG))
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("serve", "run the phone app and the sync API"),
        ("check-config", "validate the settings and exit"),
        ("init-secret", "create the sync secret if there is none"),
        ("fingerprint", "the sync certificate's SHA-256, for the desktop's pairing settings"),
        ("devices", "list enrolled phones"),
        ("status", "counts and cache size"),
        ("purge", "run retention now"),
        ("immich-check", "check the Immich address, key and permissions; changes nothing"),
    ):
        commands.add_parser(name, help=text)
    revoke = commands.add_parser("revoke", help="refuse a phone from its next request")
    revoke.add_argument("device_id")
    return parser


def _immich_check(settings: Settings) -> int:
    path = settings.immich_key_path
    try:
        key = read_key(path)
    except (OSError, ValueError) as error:
        print(f"Immich key not usable: {error}")
        return 1
    if not settings.immich_url or key is None:
        print(f"Immich is not configured: set immich_url and put the API key in {path}")
        return 1
    try:
        client = ImmichClient(settings.immich_url, key)
        version = client.version()
        print(f"Immich {'.'.join(map(str, version))}")
        if version[0] < MINIMUM_MAJOR:
            print(f"version {MINIMUM_MAJOR} or newer is required")
            return 1
        granted = set(client.key_permissions())
    except ImmichError as error:
        print(f"Immich check failed: {error.code}")
        return 1
    needed = ", ".join(PERMISSIONS)
    if "all" in granted:
        print(f"the key has all permissions; replace it with one that has only: {needed}")
        return 1
    missing, extra = sorted(set(PERMISSIONS) - granted), sorted(granted - set(PERMISSIONS))
    if missing:
        print(f"missing: {', '.join(missing)}")
    if extra:
        print(f"not needed: {', '.join(extra)}")
    if not (missing or extra):
        print(f"the key has exactly the needed permissions: {needed}")
    return 1 if missing or extra else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(Path(args.config))
        if args.command == "serve":
            return serve(settings)
        if args.command == "check-config":
            settings.check_listeners()
            print("configuration OK")
            return 0
        if args.command == "init-secret":
            created = create_secret(settings.secret_file)
            print(
                f"{'created' if created else 'kept the existing'} sync secret: {settings.secret_file}"
            )
            return 0
        if args.command == "immich-check":
            return _immich_check(settings)
        if args.command == "fingerprint":
            print(certificate_fingerprint(settings.sync_tls_cert))
            return 0
        store = Gateway(settings).store
    except ConfigError as error:
        print(f"review_gateway: {error}", file=sys.stderr)
        return 2
    if args.command == "revoke":
        if not store.revoke_device(args.device_id):
            print(f"no such device: {args.device_id}", file=sys.stderr)
            return 1
        print(f"revoked {args.device_id}")
        return 0
    if args.command == "devices":
        for device in store.devices():
            state = f"revoked {device['revoked_at']}" if device["revoked_at"] else "active"
            print(
                f"{device['device_id']}  {state}  scopes={','.join(device['scopes'])}  "
                f"enrolled={device['enrolled_at']}  last_seen={device['seen_at'] or '-'}  "
                f"label={device['label'] or '-'!r}"
            )
        return 0
    result = store.status() if args.command == "status" else store.retention()
    for name, value in result.items():
        print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
