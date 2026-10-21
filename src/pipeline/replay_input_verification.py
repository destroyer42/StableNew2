"""Verify that the files a persisted NJR froze are still present and unchanged before it is replayed.

A replay creates a new job from an old immutable record, so the inputs that record points at may have moved or
changed since it first ran. This module only reads files (hashing in bounded blocks); it never writes, copies or
repairs anything, and it calls no runner or queue. Inputs that carry a recorded SHA-256 are re-hashed, so a
same-size/same-mtime replacement is still caught; inputs without a recorded hash are checked for presence only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.pipeline.job_models_v2 import NormalizedJobRecord

_BLOCK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class InputCheck:
    label: str
    path: str
    #: Lower-case hex digest recorded when the input was frozen; ``None`` when only presence can be checked.
    expected_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class InputIssue:
    label: str
    path: str
    reason: str

    def describe(self) -> str:
        return f"{self.label} {self.reason}: {self.path}"


def sha256_of(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _recorded_sha(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    return text if len(text) == 64 and all(char in "0123456789abcdef" for char in text) else None


def assembly_input_checks(spec: Mapping[str, Any]) -> list[InputCheck]:
    """The clips and audio track a frozen Movie Clips assembly spec recorded, each with its digest (PR-VID-ASM-332)."""

    checks = [
        InputCheck("assembly clip", str(clip["path"]), _recorded_sha(clip.get("sha256")))
        for clip in spec.get("clips") or ()
        if isinstance(clip, Mapping) and clip.get("path")
    ]
    audio = _mapping(spec.get("audio"))
    if audio.get("path"):
        checks.append(
            InputCheck("assembly audio track", str(audio["path"]), _recorded_sha(audio.get("sha256")))
        )
    return checks


def frozen_input_checks(record: NormalizedJobRecord) -> list[InputCheck]:
    """Every file the record froze, with the digest it recorded where it recorded one."""

    assembly = _mapping(_mapping(record.config).get("movie_assembly"))
    if assembly:
        # Every assembly input is frozen with its digest; the generic source-image checks would only repeat them.
        return assembly_input_checks(assembly)
    metadata = record.extra_metadata
    workflow = _mapping(metadata.get("video_workflow"))
    identity = _mapping(workflow.get("source_identity"))
    prepared_path = str(identity.get("prepared_path") or "")
    prepared_sha = _recorded_sha(identity.get("prepared_sha256"))
    inputs = [str(path) for path in record.input_image_paths]
    # A replay's own ``source.parent_artifact_id`` is the replay's lineage and may be empty; the digest of the
    # original source artifact survives in the (inherited) metadata, so a retry of a retry is still verified.
    parent_sha = _recorded_sha(record.source.parent_artifact_id) or _recorded_sha(
        metadata.get("parent_artifact_id")
    )
    checks: list[InputCheck] = []
    for path in inputs:
        expected = None
        if prepared_sha and path == prepared_path:
            expected = prepared_sha
        elif parent_sha and len(inputs) == 1:
            expected = parent_sha
        checks.append(InputCheck("source image", path, expected))
    pose = _mapping(workflow.get("pose_video"))
    if pose.get("path"):
        checks.append(InputCheck("driving video", str(pose["path"]), _recorded_sha(pose.get("sha256"))))
    config = _mapping(_mapping(record.config).get("video_workflow"))
    for mid in config.get("mid_anchor_paths") or ():
        if isinstance(mid, str) and mid:
            checks.append(InputCheck("mid anchor", mid))
    if config.get("end_anchor_path"):
        checks.append(InputCheck("end anchor", str(config["end_anchor_path"])))
    depth = _mapping(config.get("depth_input"))
    if str(depth.get("mode") or "") == "upload" and depth.get("path"):
        checks.append(InputCheck("depth map", str(depth["path"])))
    # PR-IMG-CNET-210: the job-owned OpenPose snapshot is content-addressed, so its recorded digest is always checkable.
    conditioning = _mapping(_mapping(record.config).get("controlnet_openpose"))
    snapshot = _mapping(conditioning.get("snapshot"))
    if snapshot.get("path"):
        checks.append(
            InputCheck(
                "OpenPose conditioning image",
                str(snapshot["path"]),
                _recorded_sha(conditioning.get("asset_sha256")),
            )
        )
    edit = _mapping(_mapping(_mapping(record.config).get("img2img")).get("image_edit_inputs"))
    from src.conditioning.controlnet import SLOT_FIELD, FrozenControlNet

    raw_units = _mapping(record.config).get(SLOT_FIELD)
    if raw_units is not None:
        for index, unit in enumerate(FrozenControlNet.from_config(raw_units).units):
            checks.append(InputCheck(f"ControlNet unit {index + 1} ({unit.modality})", unit.image.snapshot_path, unit.image.asset_sha256))
    mask = _mapping(edit.get("mask"))
    if mask.get("path"):
        checks.append(InputCheck("inpainting mask", str(mask["path"]), _recorded_sha(mask.get("sha256"))))
    return checks


def verify_inputs(
    checks: list[InputCheck], *, hash_file: Callable[[str], str] = sha256_of
) -> list[InputIssue]:
    """Return one issue per missing, unreadable or changed input (empty means every input is intact)."""

    issues: list[InputIssue] = []
    for check in checks:
        path = Path(check.path)
        if not path.is_file():
            issues.append(InputIssue(check.label, check.path, "is missing or was moved"))
            continue
        if check.expected_sha256 is None:
            continue
        try:
            actual = hash_file(check.path)
        except OSError:
            issues.append(InputIssue(check.label, check.path, "is no longer readable"))
            continue
        if actual != check.expected_sha256:
            issues.append(InputIssue(check.label, check.path, "changed since the job was created"))
    return issues


__all__ = [
    "InputCheck",
    "InputIssue",
    "assembly_input_checks",
    "frozen_input_checks",
    "sha256_of",
    "verify_inputs",
]
