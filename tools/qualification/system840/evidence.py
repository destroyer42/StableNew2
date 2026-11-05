"""Immutable attempt archives outside Git: unique run identity, atomic manifest publication, size+SHA-256 verification.

Every attempt gets a new directory ``<arm>_<UTC>_<digest12>_<random>``.  It is created as ``<name>.partial`` with the
frozen plan saved first (before any dispatch), grows by copy-only additions (nothing is ever overwritten, replaced or
deleted), and is sealed once: the manifest is published atomically, a ``COMPLETE`` marker is written and the directory is
renamed to its final name.  An unsealed, truncated or tampered archive is INCONCLUSIVE evidence and is never accepted; an
existing accepted archive is never touched, even after a failed or cancelled later attempt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_json
from tools.operator_journey.workspace import REPO_ROOT
from tools.qualification.system840 import SUITE_ID, SUITE_VERSION

MANIFEST = "manifest.json"
COMPLETE = "COMPLETE"
PLAN_FILE = "plan.json"
PARTIAL_SUFFIX = ".partial"
ENV_ROOT = "STABLENEW_QUAL840_ROOT"
OK, INCOMPLETE, TAMPERED, MISSING = "OK", "INCOMPLETE", "TAMPERED", "MISSING"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ArchiveRefused(RuntimeError):
    """The requested archive operation would overwrite evidence or write inside the repository."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_root() -> Path:
    return (
        Path(os.environ.get("USERPROFILE") or Path.home())
        / "Videos"
        / "StableNewAcceptance"
        / "QUAL-840"
    )


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def resolve_root(explicit: Path | str | None = None, env: dict[str, str] | None = None) -> Path:
    environ = os.environ if env is None else env
    chosen = Path(explicit or environ.get(ENV_ROOT) or default_root()).expanduser()
    if _inside(chosen, REPO_ROOT):
        raise ArchiveRefused(
            f"the evidence root {chosen} is inside the repository; permanent evidence lives outside Git"
        )
    return chosen


def attempt_name(arm_id: str, digest: str, now: datetime, token: str) -> str:
    return f"{_SAFE.sub('-', arm_id)}_{now:%Y%m%dT%H%M%SZ}_{digest[:12]}_{token}"


class Attempt:
    """One physical or simulated attempt being recorded.  Use ``Attempt.open`` and finish with ``seal``."""

    def __init__(self, root: Path, name: str, plan: dict[str, Any]) -> None:
        self.root, self.name, self.plan = root, name, plan
        self.partial = root / f"{name}{PARTIAL_SUFFIX}"
        self.final = root / name
        self.files: list[dict[str, Any]] = []
        self.sealed = False

    @classmethod
    def open(
        cls,
        root: Path | str,
        plan: dict[str, Any],
        *,
        now: datetime | None = None,
        token: str | None = None,
    ) -> Attempt:
        root = resolve_root(root)
        root.mkdir(parents=True, exist_ok=True)
        now = now or datetime.now(UTC)
        name = attempt_name(
            str(plan["arm_id"]), str(plan["digest"]), now, token or secrets.token_hex(3)
        )
        attempt = cls(root, name, plan)
        if attempt.final.exists():
            raise ArchiveRefused(
                f"{attempt.final} already exists; an attempt directory is never reused"
            )
        attempt.partial.mkdir()  # exclusive: raises if it exists
        attempt.write_json(PLAN_FILE, plan, role="frozen_plan")
        return attempt

    def _target(self, rel: str) -> Path:
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ArchiveRefused(
                f"evidence path {rel!r} must be relative and stay inside the attempt"
            )
        if self.sealed:
            raise ArchiveRefused("the attempt is sealed")
        target = self.partial / rel_path
        if target.exists() or any(f["path"] == rel_path.as_posix() for f in self.files):
            raise ArchiveRefused(
                f"{rel} already exists in this attempt; evidence is never overwritten"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _record(self, target: Path, rel: str, role: str, **extra: Any) -> dict[str, Any]:
        entry = {
            "path": Path(rel).as_posix(),
            "role": role,
            "size": target.stat().st_size,
            "sha256": sha256_file(target),
            **extra,
        }
        self.files.append(entry)
        return entry

    def add_file(self, source: Path | str, rel: str, *, role: str, **extra: Any) -> dict[str, Any]:
        """Copy ``source`` in (the original stays where it is) and record its size and SHA-256."""

        source = Path(source)
        target = self._target(rel)
        with source.open("rb") as src, target.open("xb") as dst:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                dst.write(chunk)
        entry = self._record(target, rel, role, **extra)
        if entry["sha256"] != sha256_file(source):
            raise ArchiveRefused(f"{source} changed while it was being copied")
        return entry

    def write_json(self, rel: str, payload: Any, *, role: str) -> dict[str, Any]:
        target = self._target(rel)
        atomic_write_json(target, payload, indent=2, sort_keys=True)
        return self._record(target, rel, role)

    def seal(self, result: dict[str, Any], *, now: datetime | None = None) -> Path:
        """Publish the manifest atomically, mark the attempt complete and rename it to its final name."""

        if self.sealed:
            raise ArchiveRefused("the attempt is already sealed")
        manifest = {
            "suite": SUITE_ID,
            "suite_version": SUITE_VERSION,
            "attempt": self.name,
            "arm_id": self.plan.get("arm_id"),
            "stage": self.plan.get("stage"),
            "plan_digest": self.plan.get("digest"),
            "benchmark_version": self.plan.get("benchmark_version"),
            "sealed_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
            "repo": (self.plan.get("environment") or {}).get("repo"),
            "files": sorted(self.files, key=lambda f: f["path"]),
            "result": result,
        }
        atomic_write_json(self.partial / MANIFEST, manifest, indent=2, sort_keys=True)
        marker = self.partial / COMPLETE
        marker.write_text(sha256_file(self.partial / MANIFEST) + "\n", encoding="utf-8")
        if self.final.exists():
            raise ArchiveRefused(
                f"{self.final} appeared during the attempt; refusing to replace it"
            )
        self.partial.rename(self.final)
        self.sealed = True
        return self.final


def verify_attempt(path: Path | str) -> dict[str, Any]:
    """OK only for a sealed attempt whose manifest and every file match their recorded size and SHA-256."""

    path = Path(path)
    report: dict[str, Any] = {"path": str(path), "status": OK, "problems": []}
    problems: list[str] = report["problems"]
    if not path.is_dir():
        return {**report, "status": MISSING, "problems": [f"{path} is not a directory"]}
    if path.name.endswith(PARTIAL_SUFFIX):
        return {
            **report,
            "status": INCOMPLETE,
            "problems": ["the attempt was never sealed (interrupted)"],
        }
    manifest_path, marker = path / MANIFEST, path / COMPLETE
    if not manifest_path.is_file() or not marker.is_file():
        return {
            **report,
            "status": INCOMPLETE,
            "problems": ["manifest or COMPLETE marker is missing"],
        }
    if marker.read_text(encoding="utf-8").strip() != sha256_file(manifest_path):
        return {
            **report,
            "status": TAMPERED,
            "problems": ["the manifest does not match its COMPLETE marker"],
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return {**report, "status": TAMPERED, "problems": [f"manifest is unreadable: {exc}"]}
    listed = {f["path"] for f in manifest.get("files", [])}
    for entry in manifest.get("files", []):
        target = path / entry["path"]
        if not target.is_file():
            problems.append(f"{entry['path']} is missing")
        elif target.stat().st_size != entry["size"] or sha256_file(target) != entry["sha256"]:
            problems.append(f"{entry['path']} differs from its recorded size/SHA-256")
    present = {
        p.relative_to(path).as_posix()
        for p in path.rglob("*")
        if p.is_file() and p.name not in (MANIFEST, COMPLETE)
    }
    problems.extend(f"{extra} is not in the manifest" for extra in sorted(present - listed))
    if problems:
        report["status"] = TAMPERED
    return report


def list_attempts(root: Path | str, arm_id: str | None = None) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    prefix = f"{_SAFE.sub('-', arm_id)}_" if arm_id else ""
    return sorted(
        p
        for p in root.iterdir()
        if p.is_dir() and not p.name.endswith(PARTIAL_SUFFIX) and p.name.startswith(prefix)
    )


def interrupted_attempts(root: Path | str) -> list[Path]:
    root = Path(root)
    return (
        sorted(p for p in root.iterdir() if p.is_dir() and p.name.endswith(PARTIAL_SUFFIX))
        if root.is_dir()
        else []
    )


def load_manifest(path: Path | str) -> dict[str, Any]:
    return json.loads((Path(path) / MANIFEST).read_text(encoding="utf-8"))


def validate_media_files(
    attempt_path: Path | str, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    """Decode every retained PNG/MP4 (full decode, not a header read) and report integrity; never raises."""

    from tools.operator_journey.golden.media import inspect_media

    reports: list[dict[str, Any]] = []
    for entry in manifest.get("files", []):
        if Path(entry["path"]).suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".mp4",
            ".webm",
        }:
            info = inspect_media(Path(attempt_path) / entry["path"])
            reports.append(
                {"path": entry["path"], "valid": bool(info.get("valid")), "detail": info}
            )
    return reports


def write_verdict(attempt_path: Path | str, verdicts: dict[str, Any]) -> Path:
    """Write the computed verdict *beside* the sealed attempt (never inside it) and never over an existing one."""

    attempt_path = Path(attempt_path)
    target = attempt_path.with_name(f"{attempt_path.name}.verdict.json")
    if target.exists():
        raise ArchiveRefused(f"{target} already exists; a recomputed verdict goes to a new file")
    return atomic_write_json(target, verdicts, indent=2, sort_keys=True)
