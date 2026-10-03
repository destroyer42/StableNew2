"""Read pinned sources/assets and write exclusive, content-addressed evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def hash_file(path: str | Path) -> str:
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def load_descriptor(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data["package"] != "PR-IMG-FORGE-100" or data["backend_id"] != "forge_webui":
        raise ValueError("Wrong qualification descriptor")
    if data["default_image_backend_id"] != "a1111_webui":
        raise ValueError("Qualification must preserve the A1111 default")
    return data


def git_read(root: str | Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def verify_source(root: str | Path, spec: dict[str, Any]) -> dict[str, str]:
    remote = git_read(root, "remote", "get-url", "origin").removesuffix(".git").rstrip("/")
    if remote != spec["repository"].removesuffix(".git").rstrip("/"):
        raise ValueError("Unexpected source repository")
    head = git_read(root, "rev-parse", "HEAD")
    branch = git_read(root, "branch", "--show-current")
    if head != spec["commit"] or git_read(root, "status", "--porcelain"):
        raise ValueError("Source pin mismatch or dirty source tree")
    # An extension or operator checkout may be detached at the exact approved commit.
    if branch and spec.get("branch") and branch != spec["branch"]:
        raise ValueError("Unexpected source branch")
    return {"repository": remote, "branch": branch or "detached", "commit": head}


def verify_assets(assets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    evidence = {}
    for name, spec in assets.items():
        path = Path(spec["path"])
        sha = hash_file(path)
        if sha != spec["sha256"]:
            raise ValueError(f"Asset changed: {name}")
        evidence[name] = {"path": str(path.resolve()), "sha256": sha, "bytes": path.stat().st_size}
    return evidence


def write_exclusive(path: str | Path, value: Any) -> None:
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def freeze_provenance(
    *, descriptor: dict[str, Any], matrix: dict[str, Any], stable_root: Path,
    forge_root: Path, adetailer_root: Path, runtime: dict[str, Any],
) -> dict[str, Any]:
    if git_read(stable_root, "rev-parse", "HEAD") != matrix["stable_sha"]:
        raise ValueError("StableNew source checkpoint changed")
    if git_read(stable_root, "status", "--porcelain"):
        raise ValueError("StableNew source must be clean for physical execution")
    value = {
        "schema_version": 1, "matrix_sha256": digest(matrix), "descriptor_sha256": digest(descriptor),
        "stable_sha": matrix["stable_sha"], "forge": verify_source(forge_root, descriptor["source"]),
        "adetailer": verify_source(adetailer_root, descriptor["adetailer"]),
        "assets": verify_assets(matrix["assets"]), "runtime": runtime,
    }
    return {**value, "provenance_sha256": digest(value)}
