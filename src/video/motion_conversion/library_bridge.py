"""Accept a verified converted clip into the existing Motion Library (PR-VID-MOTION-354).

Uses the library's own ``import_video`` -- no second catalog.  Only an *accepted* conversion whose published video still
hashes to its record can be added; a preview never can.  Nothing here prepares, queues or hands off the clip.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.video.driving_video_inspection import inspect_driving_video
from src.video.motion_conversion.conversion_plan import (
    CAMERA_STATIC,
    PROFILE_SKELETON,
    ROOT_IN_PLACE,
)
from src.video.motion_conversion.conversion_service import (
    PROVENANCE_NAME,
    PURPOSE_ACCEPTED,
    published_video,
    read_provenance,
    verify_published,
)
from src.video.motion_library.importer import ImportOutcome, Inspector, import_video
from src.video.motion_library.models import (
    FRAMING_FULL_BODY,
    LOCATOR_LINKED,
    SOURCE_RENDERED_MOCAP,
    SUBJECT_HUMAN,
    UNKNOWN,
    DerivationRecord,
    clean_note,
    normalize_tags,
)
from src.video.motion_library.store import MotionLibraryStore

_PROFILE_TAG = {
    "character_reference": "character-render",
    "high_contrast_silhouette": "silhouette-render",
    "skeleton_reference": "skeleton-render",
}


def derivation_from_record(record: dict[str, Any], provenance_path: str) -> DerivationRecord:
    source = record["source"]
    conversion = record["conversion"]
    tools = record["tools"]
    return DerivationRecord(
        source_sha256=source["sha256"],
        source_type=source["type"],
        source_name=Path(source["path"]).name,
        source_path=source["path"],
        provenance_path=provenance_path,
        plan_digest=record["plan_digest"],
        profile=conversion["profile"],
        camera=conversion["camera"],
        camera_mode=conversion["camera_mode"],
        root_motion=conversion["root_motion"],
        blender_version=str(tools["blender"].get("version", "")),
        script_version=str(tools.get("script_version", "")),
        character_mode=str(record["character"].get("mode", "")),
    )


def suggested_tags(record: dict[str, Any], extra: Iterable[str] = ()) -> tuple[str, ...]:
    """Search-friendly tags that state facts about the render (never claims about quality)."""

    conversion = record["conversion"]
    tags = [
        "derived",
        f"source-{record['source']['type']}",
        _PROFILE_TAG.get(conversion["profile"], conversion["profile"]),
        f"view-{conversion['camera'].replace('_', '-')}",
        "static-camera" if conversion["camera_mode"] == CAMERA_STATIC else "tracking-camera",
        "in-place" if conversion["root_motion"] == ROOT_IN_PLACE else "root-motion",
        "full-body",
        "unreviewed",
    ]
    return normalize_tags([*tags, *extra])


def accept_conversion(
    store: MotionLibraryStore,
    directory: str | Path,
    *,
    name: str = "",
    extra_tags: Iterable[str] = (),
    usage_terms: str = "",
    inspect: Inspector | None = None,
    cancel: threading.Event | None = None,
) -> ImportOutcome:
    """Import the converted video (linked, so the published folder stays the single copy)."""

    folder = Path(directory)
    problem = verify_published(folder)
    if problem:
        return ImportOutcome(str(folder), "failed", reason=problem)
    record = read_provenance(folder / PROVENANCE_NAME)
    video = published_video(folder, record) if record is not None else None
    if (
        record is None or video is None
    ):  # verify_published proved both; kept as a guard, never an assert
        return ImportOutcome(str(folder), "failed", reason="The conversion record is malformed.")
    if record.get("purpose") != PURPOSE_ACCEPTED:
        return ImportOutcome(
            str(folder),
            "failed",
            reason="A preview cannot be added to the library; convert the full clip.",
        )
    conversion = record["conversion"]
    provenance_path = str(folder / PROVENANCE_NAME)
    source = record["source"]
    notes = clean_note(
        f"Rendered with Blender from {Path(source['path']).name} (SHA-256 {source['sha256']}); "
        f"{conversion['profile'].replace('_', ' ')}. Conversion record: {provenance_path}"
    )
    annotations = {
        "display_name": name.strip()
        or f"{Path(source['path']).stem} ({conversion['camera'].replace('_', '-')})",
        "tags": suggested_tags(record, extra_tags),
        "source_category": SOURCE_RENDERED_MOCAP,
        "source_reference": Path(source["path"]).name,
        "provenance_notes": notes,
        "usage_terms": usage_terms,
        "viewpoint": conversion["camera"],
        "camera_movement": "static" if conversion["camera_mode"] == CAMERA_STATIC else "tracking",
        "framing": FRAMING_FULL_BODY,
        "subject_kind": UNKNOWN if conversion["profile"] == PROFILE_SKELETON else SUBJECT_HUMAN,
    }
    return import_video(
        store,
        video,
        mode=LOCATOR_LINKED,
        annotations=annotations,
        derivation=derivation_from_record(record, provenance_path),
        inspect=inspect or (lambda p, c: inspect_driving_video(p, cancel=c)),
        cancel=cancel,
    )
