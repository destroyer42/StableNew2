"""The check between a staging deploy and a production deploy (PHONE-CORE PS-1): PASS or FAIL.

    python -m tools.review_gateway_deploy --target staging request <sha>
    python -m tools.review_gateway_promote <sha>

It deploys and promotes nothing. Against staging only, it checks that:

* the gateway's deployer reports ``<sha>``;
* the phone page and its modules load, labelled as an environment;
* the page's static version is the one ``<sha>``'s files give (so run it from a checkout that holds that commit);
* a temporary phone can pair, and the session reports ``<sha>`` and that version;
* a freshly seeded item is listed, shows its thumbnail, and a decision on it reaches the outbox;
* ``/sw.js`` is served, when ``<sha>`` has a service worker.

The temporary phone is revoked afterwards and its decision is acknowledged. The phone page is on the tailnet only, so
this PC needs Tailscale. Promotion stays a separate, explicit command:
``python -m tools.review_gateway_deploy request <sha>``.

Exit codes: 0 PASS; 1 FAIL; 2 usage.
"""

from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from src.app import review_gateway_protocol as protocol
from src.app.review_gateway_client import GatewayClient, GatewayError
from tools import review_gateway_stage as stage
from tools import review_gateway_targets as targets

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_PATH = "services/review_gateway/review_gateway/static"
STATIC_FILES = REPO_ROOT / "services" / "review_gateway" / "review_gateway" / "static_files.py"
_SHA = re.compile(r"[0-9a-f]{40}")
_VERSION = re.compile(r'src="/s/([0-9a-f]{12})/core/main\.js"')
#: As the gateway's settings allow it; anything else is not shown on this PC's console.
_LABEL = re.compile(r'<span id="environment">([A-Za-z0-9 _.-]{1,24})</span>')
_REPLY_LIMIT = 4 * 1024 * 1024
_TIMEOUT = 20.0
_GIT_TIMEOUT = 60.0
_OUTBOX_PAGES = 200


class CheckFailed(Exception):
    pass


def require(condition: object, problem: str) -> None:
    if not condition:
        raise CheckFailed(problem)


class Phone:
    """The staging phone page's HTTP, as a browser would send it. Certificates are verified; no redirect is followed."""

    def __init__(self, url: str) -> None:
        parts = urlsplit(targets.parse_phone_url(url))
        self._secure = parts.scheme == "https"
        self._host = parts.hostname or ""
        self._port = parts.port
        self.cookie = ""

    def request(
        self, method: str, path: str, body: Mapping[str, Any] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        connection: http.client.HTTPConnection = (
            http.client.HTTPSConnection(
                self._host, self._port, timeout=_TIMEOUT, context=ssl.create_default_context()
            )
            if self._secure
            else http.client.HTTPConnection(self._host, self._port, timeout=_TIMEOUT)
        )
        headers = {"X-Review-Gateway": "1"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            reply = response.read(_REPLY_LIMIT + 1)
            require(len(reply) <= _REPLY_LIMIT, f"{path} answered too much")
            found = {name.lower(): value for name, value in response.getheaders()}
            return response.status, found, reply
        except (OSError, http.client.HTTPException) as error:
            raise CheckFailed(
                f"the phone page is unreachable ({type(error).__name__}): is Tailscale on?"
            ) from error
        finally:
            connection.close()

    def get(self, path: str, content_type: str) -> bytes:
        status, headers, reply = self.request("GET", path)
        require(status == 200, f"{path} answered {status}")
        kind = headers.get("content-type", "").split(";")[0].strip()
        require(kind.startswith(content_type), f"{path} is served as {kind[:60]!r}")
        return reply

    def json(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        status, headers, reply = self.request(method, path, body)
        require(status == 200, f"{path} answered {status}")
        if "set-cookie" in headers:
            self.cookie = headers["set-cookie"].split(";", 1)[0]
        try:
            value = json.loads(reply)
        except ValueError:
            value = None
        require(isinstance(value, dict), f"{path} did not answer with an object")
        return value


# --- what the commit says the page should be ----------------------------------------------------------------------


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    done = subprocess.run(
        ["git", *args], cwd=repo, input=data, capture_output=True, timeout=_GIT_TIMEOUT, check=False
    )
    require(done.returncode == 0, "git cannot read that commit here: run git fetch origin")
    return done.stdout


def static_tree(sha: str, destination: Path, repo: Path = REPO_ROOT) -> None:
    """Write ``<sha>``'s page files below ``destination``, byte for byte as the repository stores them."""

    require(_SHA.fullmatch(sha), "not a commit id")
    listed = _git(repo, "ls-tree", "-r", "-z", "--full-tree", sha, "--", STATIC_PATH)
    entries = []
    for line in listed.split(b"\0"):
        if not line:
            continue
        head, _, name = line.partition(b"\t")
        mode, _kind, blob = head.split()
        if mode in (b"100644", b"100755"):  # links are not served, as on the gateway
            entries.append((blob, name.decode("utf-8")))
    require(entries, "that commit has no page files")
    batch = _git(repo, "cat-file", "--batch", data=b"".join(blob + b"\n" for blob, _ in entries))
    offset = 0
    for _blob, name in entries:
        end = batch.index(b"\n", offset)
        size = int(batch[offset:end].split()[2])
        relative = Path(name).relative_to(STATIC_PATH)
        require(
            not any(part == ".." or ":" in part or "\\" in part for part in relative.parts),
            "an unexpected path in that commit",
        )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(batch[end + 1 : end + 1 + size])
        offset = end + 1 + size + 1


def _static_files() -> Any:
    """This checkout's ``static_files.py`` (standard library only): the gateway's own version rule."""

    spec = importlib.util.spec_from_file_location("rg_static_files", STATIC_FILES)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


def expected_page(
    sha: str, label: str, tree: Callable[[str, Path], None] = static_tree
) -> tuple[str, bool]:
    """``(static version, has a service worker)`` of ``<sha>``'s page under the environment label ``label``."""

    with tempfile.TemporaryDirectory(prefix="rg-promote-") as folder:
        root = Path(folder)
        tree(sha, root)
        site = _static_files().load_static(root, environment_label=label)
        return site.version, (root / "sw.js").is_file()


# --- the checks ---------------------------------------------------------------------------------------------------


def _publish_smoke_item(sync: GatewayClient) -> tuple[dict[str, str], str]:
    name = f"stage-smoke-{secrets.token_hex(6)}"
    run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_stage_smoke")
    manifest, blobs = stage.image_item(name, run_id=run_id, source="testing", colour=0)
    require(stage.publish(sync, manifest, blobs) != "purged", "the gateway refused the smoke item")
    return manifest["item"], run_id


def _pending(sync: GatewayClient, record_id: str) -> dict[str, Any] | None:
    cursor: str | None = None
    for _page in range(_OUTBOX_PAGES):
        page = sync.outbox(cursor, limit=500)
        for record in page.get("records", []):
            if record.get("record_id") == record_id:
                return record
        cursor = page.get("next_cursor")
        if not cursor:
            return None
    return None


def _round_trip(sync: GatewayClient, phone: Phone) -> None:
    item, run_id = _publish_smoke_item(sync)
    listed = phone.json("GET", f"/api/runs/{quote(run_id)}").get("items", [])
    require(
        any(entry.get("library_id") == item["library_id"] for entry in listed),
        "the phone does not list the seeded item",
    )
    phone.get(f"/media/{item['library_id']}/{item['sha256']}/thumb", "image/")
    # "delete": a kept item would wait for Immich, which staging does not have.
    decision = {
        **item,
        "verdict": "delete",
        "favorite": False,
        "idempotency_key": str(uuid.uuid4()),
    }
    record_id = phone.json("POST", "/api/decisions", decision).get("record_id")
    record = _pending(sync, str(record_id))
    require(
        record is not None and record.get("target") == item,
        "the decision did not reach the PC's outbox",
    )
    sync.acknowledge(protocol.acknowledgement(str(record_id), "applied"))
    require(_pending(sync, str(record_id)) is None, "the gateway did not take the acknowledgement")


def check(
    sha: str,
    *,
    sync: GatewayClient,
    phone: Phone,
    tree: Callable[[str, Path], None] = static_tree,
    report: Callable[[str], None] = print,
) -> None:
    """Raise ``CheckFailed`` at the first thing that is wrong."""

    status = sync.deploy_status()
    deployed = status.get("deployed_commit") if status else None
    require(
        deployed == sha, f"staging runs {str(deployed or 'an unknown commit')[:40]!r}, not {sha}"
    )
    report(f"ok: the deployer reports {sha[:12]}")

    page = phone.get("/", "text/html").decode("utf-8", "replace")
    found, label = _VERSION.search(page), _LABEL.search(page)
    require(found, "the page names no static version")
    require(label, "the page shows no environment label: set environment_label on staging")
    version = found[1]
    phone.get(f"/s/{version}/core/main.js", "text/javascript")
    phone.get(f"/s/{version}/core/core.css", "text/css")
    report(f"ok: the page loads, labelled {label[1]!r}")

    expected, has_worker = expected_page(sha, label[1], tree)
    require(
        version == expected,
        f"the page's version is {version}, {sha[:12]}'s files give {expected} (is this checkout at that commit?)",
    )
    report(f"ok: static version {version}")

    offer = protocol.new_pairing_offer(label="Staging check", scopes=("review",))
    require(sync.send_pairing_offer(offer.payload()), "the gateway refused the pairing offer")
    paired = phone.json("POST", "/api/pair", {"code": offer.code, "label": "Staging check"})
    device_id = paired.get("device_id")
    require(isinstance(device_id, str) and device_id, "pairing named no device")
    try:
        session = phone.json("GET", "/api/session")
        require(session.get("commit") == sha, "the session reports another commit")
        require(
            session.get("static_version") == version, "the session reports another static version"
        )
        report("ok: the session reports the commit and the version")
        _round_trip(sync, phone)
        report("ok: a seeded item round-trips a decision")
        if has_worker:
            worker = phone.get("/sw.js", "text/javascript")
            require(version.encode() in worker, "/sw.js does not name this version")
            report("ok: /sw.js is served")
        else:
            report("skipped: this commit has no service worker (/sw.js)")
    finally:
        sync.send_revocation(protocol.device_revocation(device_id))


def main(
    argv: Sequence[str] | None = None,
    *,
    sync: GatewayClient | None = None,
    phone_url: str | None = None,
    tree: Callable[[str, Path], None] = static_tree,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.review_gateway_promote", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "sha", help="the commit staging should be running: 40 hexadecimal characters"
    )
    parser.add_argument(
        "--target", choices=targets.TARGETS, default=targets.STAGING, help="staging only"
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_USAGE if exit_.code else EXIT_PASS
    if args.target != targets.STAGING:
        print(
            "Refused: the check writes test items, so it runs on staging only. To promote:"
            " python -m tools.review_gateway_deploy request <sha>",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if not _SHA.fullmatch(args.sha):
        print(
            "The commit must be the full commit id: 40 lowercase hexadecimal characters.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        sync = sync or targets.staging_client()
        phone_url = phone_url or targets.StagingPhoneStore().load()
        if phone_url is None:
            raise targets.NoSettings
        check(args.sha, sync=sync, phone=Phone(phone_url), tree=tree)
    except targets.NoSettings:
        print(f"No staging gateway settings: {targets.CONFIGURE_HINT}", file=sys.stderr)
        return EXIT_USAGE
    except targets.TargetMixup as error:
        print(error, file=sys.stderr)
        return EXIT_USAGE
    except CheckFailed as error:
        print(f"FAIL: {error}")
        return EXIT_FAIL
    except (GatewayError, protocol.ProtocolError) as error:
        print(f"FAIL: the staging sync port: {error}")
        return EXIT_FAIL
    except (OSError, ValueError, AttributeError, TypeError, subprocess.SubprocessError) as error:
        print(f"FAIL: {type(error).__name__}")
        return EXIT_FAIL
    print("PASS")
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
