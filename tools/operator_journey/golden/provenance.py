"""Run provenance, source hashes and media retention: what makes one evidence folder comparable to another.

Everything here observes; nothing starts a runtime.  Values that cannot be read are recorded as ``None`` with the
reason, never guessed.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.operator_journey.workspace import REPO_ROOT, repo_sha

#: The files whose bytes define how a journey drives the product; their digest makes two runs' harnesses comparable.
HARNESS_SOURCES = ("tools/operator_journey/golden", "tools/operator_journey/desktop.py")
MEDIA_OBSERVATIONS = ("image_media", "video_media")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def dirty_files() -> list[dict[str, Any]]:
    """Tracked files that differ from HEAD (path, status, sha256 of the working copy)."""

    out = _git("status", "--porcelain", "--untracked-files=no")
    if out is None:
        return []
    rows = []
    for line in out.splitlines():
        status, name = line[:2].strip(), line[3:].strip().strip('"')
        path = REPO_ROOT / name
        rows.append(
            {
                "path": name.replace("\\", "/"),
                "status": status,
                "sha256": _sha256(path) if path.is_file() else None,
            }
        )
    return rows


def harness_sources() -> dict[str, Any]:
    """sha256 per harness source file plus one digest over all of them (line endings normalised)."""

    files: dict[str, str] = {}
    for entry in HARNESS_SOURCES:
        root = REPO_ROOT / entry
        paths = sorted(root.rglob("*.py")) if root.is_dir() else [root]
        for path in paths:
            if path.is_file() and "__pycache__" not in path.parts:
                data = path.read_bytes().replace(b"\r\n", b"\n")
                files[path.relative_to(REPO_ROOT).as_posix()] = hashlib.sha256(data).hexdigest()
    combined = hashlib.sha256(
        "\n".join(f"{name}:{sha}" for name, sha in sorted(files.items())).encode()
    ).hexdigest()
    return {"files": files, "combined_sha256": combined}


def provenance(
    *, display: dict[str, Any] | None = None, layout: str | None = None
) -> dict[str, Any]:
    """Who/what/where produced a run: commit, tree state, interpreter, OS, display, layout and harness hashes."""

    dirty = dirty_files()
    return {
        "repository_sha": repo_sha(),
        "dirty_tracked_files": dirty,
        "tree_state": "dirty" if dirty else "clean",
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "display": display or {},
        "layout": layout,
        "harness_sources": harness_sources(),
    }


def retain_media(observations: list[dict[str, Any]], run_dir: Path) -> list[dict[str, Any]]:
    """Copy each valid produced image/video into ``run_dir/artifacts/media`` and verify the copy's SHA-256.

    Called before the workspace is released.  A source that vanished, or a copy whose hash differs, is recorded with
    ``retained: false`` and a reason; evidence is never reconstructed.
    """

    target = run_dir / "artifacts" / "media"
    records: list[dict[str, Any]] = []
    for obs in observations:
        if obs.get("name") not in MEDIA_OBSERVATIONS or not isinstance(obs.get("value"), dict):
            continue
        value = obs["value"]
        record: dict[str, Any] = {
            "observation": obs["name"],
            "source": obs.get("source"),
            "original_path": value.get("path"),
            "expected_sha256": value.get("sha256"),
            "retained": False,
        }
        source = Path(str(value.get("path") or ""))
        if not value.get("valid"):
            record["reason"] = "the media did not validate"
        elif not source.is_file():
            record["reason"] = "the produced file no longer exists"
        else:
            target.mkdir(parents=True, exist_ok=True)
            name = (
                f"{obs['name']}_{str(value.get('sha256') or 'unknown')[:12]}{source.suffix.lower()}"
            )
            copy = target / name
            if copy.exists():
                record["reason"] = "a retained file with this name already exists"
            else:
                shutil.copy2(source, copy)
                actual = _sha256(copy)
                if actual == value.get("sha256"):
                    record.update(retained=True, file=f"artifacts/media/{name}", sha256=actual)
                else:
                    copy.unlink()
                    record["reason"] = f"the copy's SHA-256 {actual} differs from the recorded hash"
        records.append(record)
    return records


def settings_report(requested: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    """Requested vs observed values per key; ``match`` is ``None`` when the observation is absent."""

    rows = {}
    for key, wanted in requested.items():
        seen = observed.get(key)
        rows[key] = {
            "requested": wanted,
            "observed": seen,
            "match": None if key not in observed else _same(wanted, seen),
        }
    return {
        "keys": rows,
        "all_matched": all(r["match"] is True for r in rows.values()) if rows else None,
        "unobserved": sorted(k for k, r in rows.items() if r["match"] is None),
    }


def _same(wanted: Any, seen: Any) -> bool:
    if isinstance(wanted, (int, float)) and isinstance(seen, (int, float, str)):
        try:
            return float(seen) == float(wanted)
        except ValueError:
            return False
    return str(wanted) == str(seen)


def text_identity(text: str) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(text.encode()).hexdigest()[:16], "length": len(text)}


__all__ = [
    "dirty_files",
    "harness_sources",
    "provenance",
    "retain_media",
    "settings_report",
    "text_identity",
]
