"""Read-only inventory of installed assets and pinned runtimes against the ledger.

For each ledger capability that names a model file, look for it under the given model roots and report whether a file with
that name exists, whether its size matches and (only with ``hash_files=True``) whether its SHA-256 matches.  Nothing is
downloaded, moved, imported or modified; a missing model is reported, never fetched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.operator_journey.workspace import REPO_ROOT
from tools.qualification.system840.ledger import Ledger

RUNTIME_CONFIGS = (
    "config/managed_forge_runtime.json",
    "config/managed_comfy_runtime.json",
    "config/managed_ai_runtime.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_pins(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    pins: dict[str, Any] = {}
    for rel in RUNTIME_CONFIGS:
        path = repo_root / rel
        pins[rel] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    return pins


def installed_assets(
    ledger: Ledger, roots: list[Path], *, hash_files: bool = False
) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    index: dict[str, list[Path]] = {}
    for root in roots:
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    index.setdefault(path.name.lower(), []).append(path)
    for entry in ledger:
        filename = str(entry.identity.get("model") or "")
        if not filename or "/" in filename or " " in filename:
            continue  # a repository id or a descriptive label, not a local file name
        expected_sha = entry.identity.get("model_sha256")
        expected_size = entry.identity.get("size")
        candidates = index.get(filename.lower(), [])
        item: dict[str, Any] = {
            "capability": entry.id,
            "file": filename,
            "found": [str(p) for p in candidates],
        }
        if not candidates:
            item.update(
                state="MISSING",
                note="not installed under the given roots; nothing is ever downloaded",
            )
        else:
            best = candidates[0]
            size = best.stat().st_size
            item["size"] = size
            item["size_matches"] = None if expected_size is None else size == expected_size
            if hash_files and expected_sha:
                item["sha256_matches"] = _sha256(best) == expected_sha
            ok = item["size_matches"] in (None, True) and item.get("sha256_matches", True)
            item["state"] = "PRESENT" if ok else "IDENTITY_MISMATCH"
        report.append(item)
    return report
