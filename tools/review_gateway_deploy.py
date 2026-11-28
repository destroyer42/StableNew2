"""Deploy a commit of ``main`` to the phone review gateway from the PC, over the authenticated sync channel (DEPLOY-2).

    python -m tools.review_gateway_deploy [--target production|staging] request <merge sha> [--no-wait] [--timeout S]
    python -m tools.review_gateway_deploy [--target production|staging] status
    python -m tools.review_gateway_deploy --target staging configure

It reads the gateway address, pinned certificate and sync secret that StableNew's Phone review gateway dialog stored for
this Windows user (DPAPI), and nothing else: not the live checkout, the sync ledger or the running app. It sends one
request holding only the commit id; the gateway hands it to its root deployer, which checks with GitHub that the commit
is a signed merge on ``main`` and newer than the deployed one, installs it, health-checks it and rolls back by itself.
The console switch on the gateway (``review-gateway-deploy remote on|off``) decides whether the request is taken.

``--target`` (PHONE-CORE PS-1) is ``production`` (the default, described above) or ``staging``. ``configure`` asks for
the staging gateway's address, certificate fingerprint, sync secret and phone address and stores them in a separate
DPAPI file that only the tools read; the secret is never an argument, so it reaches no shell history.

Exit codes: 0 deployed or already current; 1 refused, failed or rolled back; 2 usage or no gateway settings; 3 still
running after the time limit; 4 the gateway is unreachable. Design: ``docs/work_packages/DEPLOY-PROXMOX_containers.md``.
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from src.app.review_gateway_client import (
    GatewayClient,
    GatewayError,
    GatewayUnauthorized,
    GatewayUnavailable,
    PinnedHttpsTransport,
)
from src.app.review_gateway_protocol import SCHEMA_VERSION
from src.app.review_gateway_store import GatewaySettings, GatewaySettingsStore
from tools import review_gateway_targets as targets

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_TIMEOUT = 3
EXIT_UNREACHABLE = 4
POLL_SECONDS = 5.0
DEFAULT_TIMEOUT = 30 * 60.0
SUCCESS = frozenset({"deployed", "already_current"})
_SHA = re.compile(r"[0-9a-f]{40}")
_REFUSALS = {
    "remote_deploy_disabled": "Remote deploy is off on the gateway. At its console: review-gateway-deploy remote on",
    "deploy_pending": "The gateway refused: another deploy request is waiting for its deployer.",
    "not_supported": "The gateway does not offer remote deploy yet: install a release with DEPLOY-2 at its console.",
    "invalid_request": "The gateway refused the request as malformed.",
}


def default_client(target: str = targets.PRODUCTION) -> GatewayClient:
    if target == targets.STAGING:
        return targets.staging_client()
    settings = GatewaySettingsStore().load()
    if settings is None:
        raise targets.NoSettings
    return GatewayClient(PinnedHttpsTransport(settings), settings.secret)


def _configure(prompt: Callable[[str], str], secret_prompt: Callable[[str], str]) -> int:
    """Ask for the staging gateway's values and save them where only the tools read. Nothing is echoed back."""

    try:
        address = prompt("Staging sync address (host:port): ")
        fingerprint = prompt("Staging certificate SHA-256 fingerprint: ")
        secret = secret_prompt("Staging sync secret (hidden): ")
        phone_url = targets.parse_phone_url(prompt("Staging phone address (https://...): "))
        settings = GatewaySettings.build(address, fingerprint, secret)
        targets.check_separate(settings, GatewaySettingsStore())
        GatewaySettingsStore(name=targets.STAGING).save(settings)
        targets.StagingPhoneStore().save(phone_url)
    except targets.TargetMixup as error:
        print(error, file=sys.stderr)
        return EXIT_USAGE
    except (EOFError, KeyboardInterrupt):
        print("Nothing was saved.", file=sys.stderr)
        return EXIT_USAGE
    except (OSError, ValueError) as error:
        print(f"Nothing was saved: {error}", file=sys.stderr)
        return EXIT_USAGE
    print("Saved the staging gateway settings for this Windows user. StableNew does not use them.")
    return EXIT_OK


def _short(value: object) -> str:
    return value[:12] if isinstance(value, str) else "unknown"


def _describe(last: Mapping[str, Any]) -> list[str]:
    outcome = last.get("outcome")
    lines = []
    if outcome == "deployed":
        lines.append(
            f"deployed {_short(last.get('old_commit'))} -> {_short(last.get('new_commit'))}"
        )
    elif outcome == "already_current":
        lines.append(f"{_short(last.get('target'))} was already deployed")
    else:
        lines.append(
            f"not deployed ({outcome}); details on the gateway: review-gateway-deploy status"
        )
    if last.get("schema_changed") is True:
        lines.append("The sync schema changed: update StableNew on the PC to the same commit.")
    return lines


def _status(client: GatewayClient) -> int:
    status = client.deploy_status()
    if status is None:
        print(_REFUSALS["not_supported"])
        return EXIT_REFUSED
    print(f"remote deploy: {status.get('remote_deploy')}")
    print(f"deployed: {status.get('deployed_commit') or 'unknown'}")
    pending = status.get("pending")
    if isinstance(pending, dict):
        print(f"pending: {pending.get('target_sha')} (request {pending.get('request_id')})")
    last = status.get("last")
    if isinstance(last, dict):
        print(
            f"last: {last.get('outcome')} {last.get('action') or ''} {last.get('target') or ''} "
            f"at {last.get('finished_at') or '-'}".replace("  ", " ")
        )
    else:
        print("last: (no deploy recorded)")
    return EXIT_OK


def _request(
    client: GatewayClient,
    sha: str,
    *,
    wait: bool,
    timeout: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> int:
    request_id = str(uuid.uuid4())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "type": "deploy_request",
        "request_id": request_id,
        "target_sha": sha,
        "requested_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    answer = client.request_deploy(payload)
    if answer != "accepted":
        print(_REFUSALS.get(answer, f"The gateway refused the request ({answer})."))
        return EXIT_REFUSED
    print(f"The gateway took the request for {sha} (request {request_id}).")
    if not wait:
        return EXIT_OK
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        try:
            status = client.deploy_status()
        except GatewayUnavailable:
            status = None  # the gateway restarts into the new release during a deploy
        last = status.get("last") if isinstance(status, dict) else None
        if (
            isinstance(last, dict)
            and last.get("request_id") == request_id
            and last.get("outcome") not in (None, "running")
        ):
            for line in _describe(last):
                print(line)
            print(f"outcome: {last.get('outcome')}")
            return EXIT_OK if last.get("outcome") in SUCCESS else EXIT_REFUSED
        sleep(POLL_SECONDS)
    print(
        f"The deploy is still running after {int(timeout)} s; check again with: python -m tools.review_gateway_deploy status"
    )
    return EXIT_TIMEOUT


def main(
    argv: Sequence[str] | None = None,
    *,
    client: GatewayClient | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    prompt: Callable[[str], str] = input,
    secret_prompt: Callable[[str], str] = getpass.getpass,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.review_gateway_deploy", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--target", choices=targets.TARGETS, default=targets.PRODUCTION, help="which gateway"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request", help="deploy a merge commit of main to the gateway")
    request.add_argument("sha", help="the merge commit, 40 lowercase hexadecimal characters")
    request.add_argument(
        "--no-wait", action="store_true", help="return once the gateway has the request"
    )
    request.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds to wait for the result"
    )
    commands.add_parser("status", help="the switch, the deployed commit and the last result")
    commands.add_parser("configure", help="save the staging gateway's settings (--target staging)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_USAGE if exit_.code else EXIT_OK
    if args.command == "request" and not _SHA.fullmatch(args.sha):
        print(
            "The commit must be the full merge commit id: 40 lowercase hexadecimal characters.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    staging = args.target == targets.STAGING
    if args.command == "configure":
        if staging:
            return _configure(prompt, secret_prompt)
        print(
            "configure is for --target staging only: production's settings are entered in StableNew's Phone review"
            " gateway dialog.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        client = client or default_client(args.target)
    except targets.NoSettings:
        print(
            f"No staging gateway settings for this Windows user: {targets.CONFIGURE_HINT}"
            if staging
            else "No gateway settings for this Windows user: enter them in StableNew's Phone review gateway dialog.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    except targets.TargetMixup as error:
        print(error, file=sys.stderr)
        return EXIT_USAGE
    except (OSError, ValueError) as error:
        print(f"The gateway settings cannot be read: {error}", file=sys.stderr)
        return EXIT_USAGE
    if staging:
        print("target: staging")
    try:
        if args.command == "status":
            return _status(client)
        return _request(
            client,
            args.sha,
            wait=not args.no_wait,
            timeout=args.timeout,
            monotonic=monotonic,
            sleep=sleep,
        )
    except GatewayUnauthorized:
        print(
            f"The gateway refused the sync secret: run {targets.CONFIGURE_HINT} again."
            if staging
            else "The gateway refused the sync secret: check the Phone review gateway settings."
        )
        return EXIT_REFUSED
    except GatewayUnavailable:
        print("The gateway is unreachable from this PC.")
        return EXIT_UNREACHABLE
    except GatewayError as error:
        print(f"The gateway answered unexpectedly: {error}")
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
