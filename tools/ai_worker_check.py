"""Read-only check of the AI worker (CT 110) against ``config/ai_worker_manifest.json``, through the SSH tunnel.

    python -m tools.ai_worker_check            # human-readable
    python -m tools.ai_worker_check --json

It sends two GET requests, ``/api/version`` and ``/api/tags``, through AI Assist's fixed loopback forward
(``127.0.0.1:11435``) and changes nothing anywhere. Exit codes: 0 the worker matches; 1 drift (another Ollama version,
a replaced or missing model); 2 the worker is unreachable; 3 no drift, but a model digest is not recorded in the
manifest yet (the installed one is printed so a pull request can record it). Ollama's limits cannot be read through the
API; the report prints the console line that shows them. Design: ``docs/work_packages/DEPLOY-PROXMOX_containers.md``
(decision 8).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.ai_assist.contracts import AiCancelToken
from src.ai_assist.remote_transport import TransportFailure, loopback_request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "ai_worker_manifest.json"
SCHEMA = "stablenew.ai-worker-manifest.v1"
#: The only settings the manifest may declare: the limits AI Assist's Remote Preview relies on.
ENVIRONMENT_KEYS = frozenset({"OLLAMA_MAX_LOADED_MODELS", "OLLAMA_NUM_PARALLEL"})
LIMITS_COMMAND = "pct exec 110 -- systemctl show ollama --property=Environment"
TIMEOUT_SECONDS = 10.0
RESPONSE_LIMIT = 256 * 1024
EXIT_CODES = {"match": 0, "drift": 1, "unreachable": 2, "unrecorded": 3}

_DIGEST = re.compile(r"[0-9a-f]{64}")
Transport = Callable[[str, bytes | None, AiCancelToken, float, int], tuple[int, bytes]]


@dataclass(frozen=True)
class ModelPin:
    name: str
    digest: str | None


@dataclass(frozen=True)
class Manifest:
    version: str
    environment: dict[str, str]
    models: tuple[ModelPin, ...]


@dataclass
class Report:
    code: str = "match"
    lines: list[str] = field(default_factory=list)
    document: dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.code]


def load_manifest(path: Path) -> Manifest:
    """Parse and validate; a ``ValueError`` names what is wrong."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise ValueError(f"{path} is not a {SCHEMA} document")
    ollama = raw.get("ollama")
    if (
        not isinstance(ollama, dict)
        or not isinstance(ollama.get("version"), str)
        or not ollama["version"]
    ):
        raise ValueError("ollama.version must be a version string")
    environment = ollama.get("environment")
    if (
        not isinstance(environment, dict)
        or not set(environment) <= ENVIRONMENT_KEYS
        or not all(isinstance(value, str) and value.isdigit() for value in environment.values())
    ):
        raise ValueError(
            f"ollama.environment may hold only {sorted(ENVIRONMENT_KEYS)} as whole numbers"
        )
    models = raw.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("models must be a non-empty list")
    pins: list[ModelPin] = []
    for entry in models:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not entry["name"]
        ):
            raise ValueError("every model needs a name")
        digest = entry.get("digest")
        if digest is not None and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
            raise ValueError(
                f"{entry['name']}: digest must be 64 lowercase hexadecimal characters or null"
            )
        pins.append(ModelPin(entry["name"], digest))
    names = [pin.name.casefold() for pin in pins]
    if len(set(names)) != len(names):
        raise ValueError("a model is listed twice")
    return Manifest(ollama["version"], dict(environment), tuple(pins))


def _get(transport: Transport, path: str) -> dict[str, Any]:
    status, raw = transport(path, None, AiCancelToken(), TIMEOUT_SECONDS, RESPONSE_LIMIT)
    if status != 200:
        raise TransportFailure(f"http_{status}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("not a JSON object")
    return value


def _bare(digest: object) -> str | None:
    if not isinstance(digest, str):
        return None
    value = digest.removeprefix("sha256:")
    return value if _DIGEST.fullmatch(value) else None


def check(manifest: Manifest, *, transport: Transport = loopback_request) -> Report:
    report = Report()
    try:
        version = _get(transport, "/api/version").get("version")
        catalog = _get(transport, "/api/tags").get("models")
    except (TransportFailure, ValueError) as error:
        report.code = "unreachable"
        report.lines.append(
            f"The AI worker did not answer through the tunnel ({error}). Is the AI Tunnel task running?"
        )
        report.document = {"outcome": report.code, "error": str(error)}
        return report
    drift = False
    unrecorded = False
    report.lines.append(
        f"Ollama {version}: "
        + ("as recorded" if version == manifest.version else f"expected {manifest.version}")
    )
    drift |= version != manifest.version
    installed: dict[str, list[str | None]] = {}
    for model in catalog if isinstance(catalog, list) else []:
        if isinstance(model, dict) and isinstance(model.get("name"), str):
            installed.setdefault(model["name"].casefold(), []).append(_bare(model.get("digest")))
    models: list[dict[str, Any]] = []
    for pin in manifest.models:
        found = installed.pop(pin.name.casefold(), [])
        if not found:
            state = "not installed"
            drift = True
        elif pin.digest is None:
            state = f"installed as {found[0]}; record this digest in config/ai_worker_manifest.json"
            unrecorded = True
        elif found == [pin.digest]:
            state = "as recorded"
        else:
            state = (
                f"installed as {', '.join(str(digest) for digest in found)}, expected {pin.digest}"
            )
            drift = True
        report.lines.append(f"{pin.name}: {state}")
        models.append(
            {"name": pin.name, "recorded": pin.digest, "installed": found, "state": state}
        )
    others = sorted(installed)
    if others:
        report.lines.append(f"Also installed (not in the manifest): {', '.join(others)}")
    limits = ", ".join(f"{key}={value}" for key, value in sorted(manifest.environment.items()))
    report.lines.append(
        f"Limits are not visible through the tunnel. Expected {limits}; on the Proxmox host: {LIMITS_COMMAND}"
    )
    report.code = "drift" if drift else "unrecorded" if unrecorded else "match"
    report.document = {
        "outcome": report.code,
        "ollama": {"recorded": manifest.version, "installed": version},
        "models": models,
        "other_models": others,
        "limits": {"expected": manifest.environment, "check_with": LIMITS_COMMAND},
    }
    return report


def main(argv: Sequence[str] | None = None, *, transport: Transport = loopback_request) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.ai_worker_check", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--json", action="store_true", help="print one JSON document")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError) as error:
        print(f"ai_worker_check: {error}", file=sys.stderr)
        return 4
    report = check(manifest, transport=transport)
    if args.json:
        print(json.dumps(report.document, indent=2, sort_keys=True))
    else:
        print("\n".join(report.lines))
        print(f"outcome: {report.code}")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
