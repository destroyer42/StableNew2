"""Permanent, immutable acceptance evidence: archive a run folder outside the repository, verify it, never overwrite.

An archive is built in a ``.partial-*`` staging directory, hashed into ``MANIFEST.json``, sealed with a ``COMPLETE``
marker (which records the manifest's own SHA-256) and only then renamed to its unique final name.  A crash at any point
leaves a ``.partial-*`` directory that ``find_interrupted`` reports and ``verify_archive`` calls INCOMPLETE; a finished
archive is never written to again.  ``mark_accepted`` adds the one allowed later file, ``ACCEPTED.json``, exactly once.

Redaction is honest about its reach: text files lose the user's home path; PNG screenshots lose their metadata chunks
(the pixels are the application window as shown and are NOT redacted); other binaries are copied byte for byte and
listed under ``unredacted_binaries``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.operator_journey.golden import SUITE_ID
from tools.operator_journey.workspace import REPO_ROOT

ARCHIVE_SCHEMA = "stablenew.acceptance_archive"
ARCHIVE_VERSION = "1.0.0"
ENV_ROOT = "STABLENEW_ACCEPTANCE_ROOT"
MANIFEST = "MANIFEST.json"
COMPLETE = "COMPLETE"
ACCEPTED = "ACCEPTED.json"
PARTIAL_PREFIX = ".partial-"
_ALLOWED_EXTRA = {ACCEPTED}
_TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".log"}
_STATUS_OK, _STATUS_INCOMPLETE, _STATUS_TAMPERED = "OK", "INCOMPLETE", "TAMPERED"


class ArchiveRefused(Exception):
    """The archive request is unsafe or would overwrite evidence; nothing was written."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_root() -> Path:
    return Path.home() / "StableNewAcceptance"


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def resolve_root(explicit: Path | str | None = None, env: dict[str, str] | None = None) -> Path:
    """The baseline root: explicit option, else ``STABLENEW_ACCEPTANCE_ROOT``, else ``~/StableNewAcceptance``."""

    environ = os.environ if env is None else env
    chosen = Path(explicit or environ.get(ENV_ROOT) or default_root()).expanduser()
    if _inside(chosen, REPO_ROOT):
        raise ArchiveRefused(
            f"the acceptance root {chosen} is inside the repository; permanent evidence must live outside Git"
        )
    return chosen


def home_path_patterns() -> list[tuple[re.Pattern[str], str]]:
    home = str(Path.home())
    forms = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
    return [(re.compile(re.escape(f), re.IGNORECASE), "~") for f in sorted(forms, key=len)]


def redact_paths(text: str) -> str:
    for pattern, replacement in home_path_patterns():
        text = pattern.sub(replacement, text)
    return text


def strip_png_metadata(source: Path, target: Path) -> bool:
    """Re-encode a PNG without ancillary metadata chunks; pixels are unchanged.  False if it is not a readable PNG."""

    try:
        from PIL import Image

        with Image.open(source) as image:
            image.load()
            image.save(
                target, format="PNG"
            )  # no pnginfo is passed, so no text/metadata chunks are written
        return True
    except Exception:  # noqa: BLE001 - an unreadable image is copied as an opaque binary instead
        return False


def _copy_one(src: Path, dst: Path) -> tuple[str, bool]:
    """Copy with redaction; returns (transform, is_unredacted_binary)."""

    dst.parent.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copy2(src, dst)
            return "none", True
        dst.write_text(redact_paths(text), encoding="utf-8", newline="\n")
        return "home_path_redacted", False
    if suffix == ".png" and strip_png_metadata(src, dst):
        return "png_metadata_stripped_pixels_unredacted", False
    shutil.copy2(src, dst)
    return "none", True


def _tree(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _unique_name(mode: str, sha: str, layout: str | None, evidence_class: str) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    parts = [stamp, mode, (sha or "nosha")[:8], layout or "nolayout", evidence_class]
    return "_".join(parts) + "_" + secrets.token_hex(3)


def archive_run(
    run_dir: Path,
    root: Path | str | None = None,
    *,
    evidence_class: str = "acceptance",
    label: str | None = None,
    notes: list[str] | None = None,
    extra_files: dict[str, Path] | None = None,
    suite: str = SUITE_ID,
    copier: Callable[[Path, Path], tuple[str, bool]] = _copy_one,
) -> Path:
    """Archive ``run_dir`` into a new unique, sealed directory under the baseline root; returns the final path.

    ``evidence_class`` is ``acceptance`` for runs made on the committed tree or ``exploratory`` for earlier runs that
    are preserved with their provenance but never presented as acceptance evidence.
    """

    run_dir = Path(run_dir)
    if not run_dir.is_dir() or not (run_dir / "evidence.json").is_file():
        raise ArchiveRefused(f"{run_dir} is not a golden-path run folder (no evidence.json)")
    base = resolve_root(root)
    if _inside(run_dir, base):
        raise ArchiveRefused("the run folder is already inside the acceptance root")
    evidence = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    provenance = evidence.get("provenance") or {}
    mode = str(evidence.get("mode", "unknown"))
    sha = str(evidence.get("repository_sha") or provenance.get("repository_sha") or "")
    layout = evidence.get("layout") or provenance.get("layout")
    name = _unique_name(mode, sha, layout, evidence_class)
    parent = base / suite
    final, staging = parent / name, parent / f"{PARTIAL_PREFIX}{name}"
    parent.mkdir(parents=True, exist_ok=True)
    if final.exists() or staging.exists():
        raise ArchiveRefused(f"{final} already exists; an archive is never overwritten")
    staging.mkdir()

    files: list[dict[str, Any]] = []
    unredacted: list[str] = []
    sources: list[tuple[Path, str]] = [
        (p, p.relative_to(run_dir).as_posix()) for p in _tree(run_dir)
    ]
    for rel, src in sorted((extra_files or {}).items()):
        if Path(src).is_file():
            sources.append((Path(src), rel))
    for src, rel in sources:
        dst = staging / rel
        if dst.exists():
            raise ArchiveRefused(f"duplicate archive path {rel}")
        transform, binary = copier(src, dst)
        if binary:
            unredacted.append(rel)
        files.append(
            {
                "path": rel,
                "size": dst.stat().st_size,
                "sha256": _sha256(dst),
                "source_sha256": _sha256(src),
                "transform": transform,
            }
        )
    manifest = {
        "schema": ARCHIVE_SCHEMA,
        "version": ARCHIVE_VERSION,
        "suite": suite,
        "name": name,
        "label": label,
        "evidence_class": evidence_class,
        "mode": mode,
        "repository_sha": sha,
        "suite_version": evidence.get("suite_version"),
        "layout": layout,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "overall_verdict": evidence.get("overall_verdict"),
        "notes": list(notes or []),
        "unredacted_binaries": unredacted,
        "redaction": "text files: home path replaced; PNG: metadata chunks stripped, pixels NOT redacted",
        "files": files,
    }
    manifest_path = staging / MANIFEST
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (staging / COMPLETE).write_text(
        json.dumps({"manifest_sha256": _sha256(manifest_path), "files": len(files)}),
        encoding="utf-8",
    )
    for path in _tree(staging):
        path.chmod(stat.S_IREAD)
    os.rename(
        staging, final
    )  # atomic on one volume; refuses to replace an existing directory on Windows
    return final


def find_interrupted(root: Path | str | None = None, suite: str = SUITE_ID) -> list[Path]:
    parent = resolve_root(root) / suite
    return sorted(parent.glob(f"{PARTIAL_PREFIX}*")) if parent.is_dir() else []


def verify_archive(path: Path) -> dict[str, Any]:
    """Re-hash an archive against its manifest.  Status OK, INCOMPLETE (never sealed) or TAMPERED."""

    path = Path(path)
    problems: list[str] = []
    manifest_path, complete_path = path / MANIFEST, path / COMPLETE
    if path.name.startswith(PARTIAL_PREFIX) or not complete_path.is_file():
        return {
            "status": _STATUS_INCOMPLETE,
            "problems": ["the archive was never sealed (no COMPLETE marker)"],
        }
    if not manifest_path.is_file():
        return {"status": _STATUS_TAMPERED, "problems": ["MANIFEST.json is missing"]}
    try:
        seal = json.loads(complete_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": _STATUS_TAMPERED, "problems": [f"unreadable seal or manifest: {exc}"]}
    if seal.get("manifest_sha256") != _sha256(manifest_path):
        problems.append("MANIFEST.json does not match the sealed hash")
    listed = {row["path"] for row in manifest.get("files", [])}
    for row in manifest.get("files", []):
        file = path / row["path"]
        if not file.is_file():
            problems.append(f"missing: {row['path']}")
        elif _sha256(file) != row["sha256"]:
            problems.append(f"hash mismatch: {row['path']}")
    for file in _tree(path):
        rel = file.relative_to(path).as_posix()
        if rel not in listed and rel not in {MANIFEST, COMPLETE} | _ALLOWED_EXTRA:
            problems.append(f"unexpected file: {rel}")
    return {
        "status": _STATUS_TAMPERED if problems else _STATUS_OK,
        "problems": problems,
        "manifest": manifest,
    }


def mark_accepted(path: Path, *, accepted_by: str, reason: str) -> Path:
    """Record the owner's acceptance of a verified archive.  One-shot: an accepted baseline is never re-marked."""

    path = Path(path)
    report = verify_archive(path)
    if report["status"] != _STATUS_OK:
        raise ArchiveRefused(f"only a verified archive can be accepted ({report['status']})")
    target = path / ACCEPTED
    if target.exists():
        raise ArchiveRefused("this baseline is already accepted and is never overwritten")
    with target.open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "accepted_by": accepted_by,
                "reason": reason,
                "accepted_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "manifest_sha256": _sha256(path / MANIFEST),
            },
            handle,
            indent=2,
        )
    target.chmod(stat.S_IREAD)
    return target


def preserve_findings_evidence(
    findings: dict[str, Any], source_root: Path | None
) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    """Resolve each finding's evidence hints under ``source_root``; returns (archive path -> file, report).

    Files that cannot be found are reported as missing; nothing is reconstructed.
    """

    wanted: dict[str, Path] = {}
    report: list[dict[str, Any]] = []
    for finding in findings.get("findings", []):
        for ref in finding.get("evidence", []):
            hint = ref["source_hint"]
            matches = sorted(source_root.glob(hint)) if source_root and source_root.is_dir() else []
            row: dict[str, Any] = {
                "finding": finding["id"],
                "source_hint": hint,
                "found": bool(matches),
            }
            if matches:
                file = matches[0]
                rel = f"findings_evidence/{finding['id']}/{file.name}"
                wanted[rel] = file
                row.update(archive_path=rel, source_sha256=_sha256(file))
            report.append(row)
    return wanted, report


def archive_with_registries(
    run_dir: Path,
    root: Path | str | None = None,
    *,
    findings_source_root: Path | None = None,
    **kwargs: Any,
) -> Path:
    """``archive_run`` plus the findings and coverage registries and the evidence files the findings cite."""

    import tempfile

    from tools.operator_journey.golden import registry

    findings = registry.load_findings()
    with tempfile.TemporaryDirectory(prefix="gp_archive_") as scratch:
        wanted, report = preserve_findings_evidence(findings, findings_source_root)
        index = Path(scratch) / "findings_evidence.json"
        index.write_text(json.dumps(report, indent=2), encoding="utf-8")
        extra = {
            **wanted,
            "registries/findings.v1.json": registry.FINDINGS_PATH,
            "registries/coverage_matrix.v1.json": registry.COVERAGE_PATH,
            "registries/findings_evidence.json": index,
        }
        extra.update(kwargs.pop("extra_files", None) or {})
        return archive_run(run_dir, root, extra_files=extra, **kwargs)


__all__ = [
    "ARCHIVE_VERSION",
    "ArchiveRefused",
    "archive_run",
    "archive_with_registries",
    "default_root",
    "find_interrupted",
    "mark_accepted",
    "preserve_findings_evidence",
    "redact_paths",
    "resolve_root",
    "strip_png_metadata",
    "verify_archive",
]
