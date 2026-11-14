"""Verify and import visual candidates into an operator-owned evaluation root."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.ai_assist.paths import resolve_ai_root
from tools.qualification.vl220.candidates import (
    REASON_CANCELLED,
    REASON_RUNTIME_UNSUPPORTED,
    REASON_UNSAFE_PATH,
    CancelCheck,
    StagedFile,
    VisualCandidate,
    has_link,
    license_reasons,
    verify_pair,
)

REFUSED_UNDER_MANAGED_AI = "evaluation_root_is_the_ai_assist_root"
REFUSED_IN_REPOSITORY = "evaluation_root_inside_a_git_working_tree"
REFUSED_NOT_ADMITTED = "not_admitted"
REFUSED_EXISTS = "destination_exists"


class StagingRefused(Exception):
    """The operation was refused. The code and reasons are safe to report."""

    def __init__(self, code: str, reasons: tuple[str, ...] = ()) -> None:
        super().__init__(code if not reasons else f"{code}: {', '.join(reasons)}")
        self.code = code
        self.reasons = reasons


def download_commands(candidate: VisualCandidate, destination: str) -> list[str]:
    """Print the exact pinned, HTTPS-only downloads for the operator."""
    return [
        f'curl --proto "=https" --proto-redir "=https" -sS -L --fail --max-filesize {item.bytes}'
        f' -o "{destination}/{item.filename}" "{item.source_url}"'
        for item in (candidate.model, candidate.projector)
    ]


def stage_report(
    candidate: VisualCandidate,
    staging_dir: Path,
    *,
    build_id: str,
    acknowledgement: Mapping[str, Any] | None = None,
    cancel: CancelCheck | None = None,
) -> dict[str, Any]:
    """Report pair integrity and import readiness using the same checks as import."""

    pair = verify_pair(candidate, staging_dir, cancel=cancel)
    reasons = [*pair.reasons, *license_reasons(candidate, acknowledgement)]
    if build_id != candidate.runtime.required_build_id:
        reasons.append(REASON_RUNTIME_UNSUPPORTED)
    return {
        "candidate_id": candidate.candidate_id,
        "build_id": build_id,
        "pair_verified": pair.ok,
        "import_ready": not reasons,
        "admitted": not reasons,
        "reasons": reasons,
        "files": [
            {
                "filename": item.filename,
                "bytes": item.bytes,
                "sha256": item.sha256,
                "present": (Path(staging_dir) / item.filename).is_file(),
            }
            for item in (candidate.model, candidate.projector)
        ],
        "license_text_sha256": candidate.license.text_sha256,
        "download_bytes": candidate.download_bytes,
    }


def evaluation_root(path: Path) -> Path:
    path = path.absolute()
    if has_link(path):
        raise StagingRefused(REFUSED_NOT_ADMITTED, (REASON_UNSAFE_PATH,))
    root = path.resolve()
    managed = resolve_ai_root().resolve()
    local = os.environ.get("LOCALAPPDATA")
    default = (Path(local) / "StableNew" / "ManagedAi").resolve() if local else managed
    if (
        root.is_relative_to(managed)
        or root.is_relative_to(default)
        or any(part.lower() == "managedai" for part in root.parts)
    ):
        raise StagingRefused(REFUSED_UNDER_MANAGED_AI)
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise StagingRefused(REFUSED_IN_REPOSITORY)
    return root


def installed_pair(root: Path, candidate: VisualCandidate) -> Path:
    return root / candidate.candidate_id / candidate.model.sha256[:16]


def import_record(candidate: VisualCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "build_id": candidate.runtime.required_build_id,
        "model_sha256": candidate.model.sha256,
        "projector_sha256": candidate.projector.sha256,
        "license_text_sha256": candidate.license.text_sha256,
    }


def _copy_verified(
    source: Path, target: Path, pinned: StagedFile, cancel: CancelCheck | None
) -> None:
    digest = hashlib.sha256()
    size = 0
    if has_link(source) or not source.is_file():
        raise StagingRefused(REFUSED_NOT_ADMITTED, (REASON_UNSAFE_PATH,))
    with source.open("rb") as reader, target.open("xb") as writer:
        while chunk := reader.read(4 * 1024 * 1024):
            if cancel is not None and cancel():
                raise StagingRefused(REFUSED_NOT_ADMITTED, (REASON_CANCELLED,))
            size += len(chunk)
            if size > pinned.bytes:
                break
            digest.update(chunk)
            writer.write(chunk)
    if size != pinned.bytes or digest.hexdigest() != pinned.sha256:
        raise StagingRefused(REFUSED_NOT_ADMITTED, ("copied_bytes_do_not_match_the_pin",))


def import_candidate(
    candidate: VisualCandidate,
    staging_dir: Path,
    root: Path,
    *,
    build_id: str,
    acknowledgement: Mapping[str, Any] | None,
    cancel: CancelCheck | None = None,
) -> Path:
    """Verify while staging, then publish the pair and its receipt together."""

    root = evaluation_root(root)
    target = installed_pair(root, candidate)
    if has_link(target):
        raise StagingRefused(REFUSED_NOT_ADMITTED, (REASON_UNSAFE_PATH,))
    if target.exists():
        raise StagingRefused(REFUSED_EXISTS)
    report = stage_report(
        candidate,
        staging_dir,
        build_id=build_id,
        acknowledgement=acknowledgement,
        cancel=cancel,
    )
    if not report["import_ready"]:
        raise StagingRefused(REFUSED_NOT_ADMITTED, tuple(report["reasons"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".import-", dir=target.parent) as scratch:
        pending = Path(scratch) / "pair"
        pending.mkdir()
        for item in (candidate.model, candidate.projector):
            _copy_verified(staging_dir / item.filename, pending / item.filename, item, cancel)
        (pending / "import_record.json").write_text(
            json.dumps(import_record(candidate), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if cancel is not None and cancel():
            raise StagingRefused(REFUSED_NOT_ADMITTED, (REASON_CANCELLED,))
        if target.exists() or target.is_symlink():
            raise StagingRefused(REFUSED_EXISTS)
        try:
            pending.rename(target)
        except OSError as exc:
            if target.exists() or target.is_symlink():
                raise StagingRefused(REFUSED_EXISTS) from exc
            raise
    return target
