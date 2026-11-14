"""Operator staging, verification and import of a visual candidate (PR-AI-VL-220, decision D15).

The application never downloads anything, and neither does this module: the operator fetches the two pinned files with the
exact commands the runbook prints (:func:`download_commands`), then runs :func:`stage_report` to verify them and, only with
the owner's license acknowledgement, :func:`import_candidate` to copy them into an evaluation root the operator names.

The evaluation root is never the AI Assist root (``%LOCALAPPDATA%\\StableNew\\ManagedAi``) and never inside a Git working tree,
so an imported visual file can never be seen by the production activation, selector, Preview or ``import-model`` path.
Nothing is executed or loaded; a cancelled or failed copy leaves no partial file behind.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.ai_assist.manifests import RuntimeManifest
from tools.qualification.vl220.candidates import (
    REASON_CANCELLED,
    Admission,
    CancelCheck,
    StagedFile,
    VisualCandidate,
    check_admission,
)

REFUSED_UNDER_MANAGED_AI = "evaluation_root_is_the_ai_assist_root"
REFUSED_IN_REPOSITORY = "evaluation_root_inside_a_git_working_tree"
REFUSED_NOT_ADMITTED = "not_admitted"
REFUSED_EXISTS = "destination_exists"


class StagingRefused(Exception):
    """Nothing was copied. ``code`` is stable; ``reasons`` carries admission reason codes when that was the cause."""

    def __init__(self, code: str, reasons: tuple[str, ...] = ()) -> None:
        super().__init__(code if not reasons else f"{code}: {', '.join(reasons)}")
        self.code = code
        self.reasons = reasons


def download_commands(candidate: VisualCandidate, destination: str) -> list[str]:
    """The exact anonymous, revision-pinned ``curl`` lines for the operator. Printed, never run."""

    lines: list[str] = []
    for item in (candidate.model, candidate.projector):
        lines.append(f'curl -sS -L --fail -o "{destination}/{item.filename}" "{item.source_url}"')
    return lines


def stage_report(
    candidate: VisualCandidate,
    staging_dir: Path,
    *,
    build_id: str,
    runtime_manifest: RuntimeManifest | None = None,
    acknowledgement: Mapping[str, Any] | None = None,
    cancel: CancelCheck | None = None,
) -> dict[str, Any]:
    """A content-free verification report: pinned identities, what was found, and the fail-closed admission verdict."""

    admission = check_admission(
        candidate, staging_dir, build_id=build_id, runtime_manifest=runtime_manifest,
        acknowledgement=acknowledgement, cancel=cancel,
    )  # fmt: skip
    return {
        "candidate_id": candidate.candidate_id,
        "build_id": build_id,
        "admitted": admission.ok,
        "reasons": list(admission.reasons),
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


def _inside_git(path: Path) -> bool:
    return any((candidate / ".git").exists() for candidate in (path, *path.parents))


def _is_managed_ai(path: Path) -> bool:
    if any(part.lower() == "managedai" for part in path.parts):
        return True
    local = os.environ.get("LOCALAPPDATA")
    if local:
        managed = (Path(local) / "StableNew" / "ManagedAi").resolve()
        return path == managed or managed in path.parents
    return False


def _copy_verified(
    source: Path, target: Path, pinned: StagedFile, cancel: CancelCheck | None
) -> bool:
    """Copy while hashing; keep the file only when it matches the pin. ``False`` means cancelled."""

    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with open(source, "rb") as reader, open(partial, "wb") as writer:
            while chunk := reader.read(4 * 1024 * 1024):
                if cancel is not None and cancel():
                    raise _Cancelled
                digest.update(chunk)
                size += len(chunk)
                writer.write(chunk)
        if size != pinned.bytes or digest.hexdigest() != pinned.sha256:
            raise StagingRefused(REFUSED_NOT_ADMITTED, ("copied_bytes_do_not_match_the_pin",))
        os.replace(partial, target)
        return True
    except _Cancelled:
        return False
    finally:
        partial.unlink(missing_ok=True)


class _Cancelled(Exception):
    pass


def import_candidate(
    candidate: VisualCandidate,
    staging_dir: Path,
    evaluation_root: Path,
    *,
    build_id: str,
    acknowledgement: Mapping[str, Any] | None,
    runtime_manifest: RuntimeManifest | None = None,
    cancel: CancelCheck | None = None,
) -> Path:
    """Copy the verified pair into ``evaluation_root/<candidate_id>/<model sha prefix>/``; return that directory.

    Refuses (and writes nothing) unless admission passes, including the owner's license acknowledgement; refuses the AI Assist
    root and any Git working tree; never overwrites. A cancel removes everything written by this call."""

    root = Path(evaluation_root).resolve()
    if _is_managed_ai(root):
        raise StagingRefused(REFUSED_UNDER_MANAGED_AI)
    if _inside_git(root):
        raise StagingRefused(REFUSED_IN_REPOSITORY)
    admission: Admission = check_admission(
        candidate, staging_dir, build_id=build_id, runtime_manifest=runtime_manifest,
        acknowledgement=acknowledgement, cancel=cancel,
    )  # fmt: skip
    if not admission.ok:
        raise StagingRefused(REFUSED_NOT_ADMITTED, admission.reasons)
    target = root / candidate.candidate_id / candidate.model.sha256[:16]
    if target.exists():
        raise StagingRefused(REFUSED_EXISTS)
    target.mkdir(parents=True)
    try:
        for item in (candidate.model, candidate.projector):
            if not _copy_verified(
                Path(staging_dir) / item.filename, target / item.filename, item, cancel
            ):
                raise StagingRefused(REFUSED_NOT_ADMITTED, (REASON_CANCELLED,))
        record = {
            "candidate_id": candidate.candidate_id,
            "build_id": build_id,
            "model_sha256": candidate.model.sha256,
            "projector_sha256": candidate.projector.sha256,
            "license_text_sha256": candidate.license.text_sha256,
        }
        (target / "import_record.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


__all__ = [
    "StagingRefused",
    "download_commands",
    "import_candidate",
    "stage_report",
]
