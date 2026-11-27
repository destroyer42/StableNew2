"""The N1 warnings for a Comfy video workflow: experimental, and a cropped source (``policy_warnings.py``).

Experimental means *not production-promoted*, not *refused*: the Queue summary shows this warning and selecting
Queue records the job's own opt-in (``AGENTS.md`` section 2, ``VIDEO_PIPELINE.md`` section 10 invariant 4).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

from src.pipeline.policy_warnings import (
    CODE_VIDEO_END_FRAME_CROPPED,
    CODE_VIDEO_EXPERIMENTAL,
    CODE_VIDEO_SOURCE_CROPPED,
    PolicyWarning,
)
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_CROP_WARNED_IDS,
    WAN_A14B_MAX_CROP_FRACTION,
)
from src.video.workflow_source_preparation import discarded_fraction, resolve_declared_target

DEFAULT_WHY = "It has not been promoted for production use, so its output can vary and it has no qualification record."


def workflow_subject(spec: Any) -> str:
    return f"{spec.workflow_id}@{spec.workflow_version}"


def experimental_workflow_warning(spec: Any, *, alternative: str = "") -> PolicyWarning | None:
    """The warning for ``spec`` when it is experimental, else ``None``.

    ``alternative`` names an approved workflow to suggest (display name), when the caller knows one.
    """

    if spec is None or not getattr(spec, "is_experimental", False):
        return None
    notes = str(getattr(spec, "governance_notes", "") or "").strip()
    why = f"{DEFAULT_WHY} {notes}".strip()
    fix = "Queue runs it anyway and records your opt-in on the job."
    if alternative:
        fix += f" For a production result choose {alternative}."
    return PolicyWarning(
        code=CODE_VIDEO_EXPERIMENTAL,
        subject=workflow_subject(spec),
        title=f"{spec.display_name} is experimental.",
        why=why,
        fix=fix,
        source_gate="workflow_registry.governance",
    )


def workflow_warning_records(spec: Any) -> list[dict[str, str]]:
    """The Queue summary's warnings for ``spec`` as plain data (rendered by Tk now, by the phone gateway later)."""

    warning = experimental_workflow_warning(spec)
    return [] if warning is None else [warning.as_dict()]


def _crop_warning(policy: Any, subject: str, width: int, height: int) -> PolicyWarning | None:
    """VID-FRAME: the warning when ``policy``'s size for a ``width`` x ``height`` source crops more than it allows."""

    workflow_id = subject.partition("@")[0]
    if not isinstance(policy, Mapping) or not policy or workflow_id not in WAN_A14B_CROP_WARNED_IDS:
        return None
    if width <= 0 or height <= 0:
        return None
    target = resolve_declared_target(policy, width, height)[1]
    cut = discarded_fraction((width, height), (target["width"], target["height"]))
    if cut <= WAN_A14B_MAX_CROP_FRACTION:
        return None
    sizes = policy.get("aspect_targets") or (policy["portrait_target"], policy["landscape_target"])
    offered = ", ".join(f"{size['width']}x{size['height']}" for size in sizes)
    return PolicyWarning(
        code=CODE_VIDEO_SOURCE_CROPPED,
        subject=subject,
        title=f"{cut:.0%} of the source picture is cut away.",
        why=(
            f"The source is {width}x{height} and the closest size this workflow offers, "
            f"{target['width']}x{target['height']}, has a different shape."
        ),
        fix=(
            "Queue runs it with the crop. To keep the whole picture, first crop or pad the source "
            f"to the shape of one of: {offered}."
        ),
        source_gate="workflow_source_preparation",
    )


def source_crop_warning(spec: Any, width: int, height: int) -> PolicyWarning | None:
    policy = (getattr(spec, "backend_defaults", None) or {}).get("source_preparation")
    return _crop_warning(policy, workflow_subject(spec), width, height)


def end_frame_crop_warning(
    subject: str, end_width: int, end_height: int, target: Mapping[str, Any] | None
) -> PolicyWarning | None:
    """V1 end frame: the warning when cutting the end image to the start image's ``target`` size loses too much."""

    workflow_id = subject.partition("@")[0]
    if not target or workflow_id not in WAN_A14B_CROP_WARNED_IDS or min(end_width, end_height) <= 0:
        return None
    width, height = int(target["width"]), int(target["height"])
    cut = discarded_fraction((end_width, end_height), (width, height))
    if cut <= WAN_A14B_MAX_CROP_FRACTION:
        return None
    return PolicyWarning(
        code=CODE_VIDEO_END_FRAME_CROPPED,
        subject=subject,
        title=f"{cut:.0%} of the end picture is cut away.",
        why=(
            f"The end image is {end_width}x{end_height}; it is cut to the clip's {width}x{height}, which the start "
            "image set and which has a different shape."
        ),
        fix="Queue runs it with the crop. To keep the whole end picture, give it the same shape as the start image.",
        source_gate="workflow_source_preparation",
    )


def image_size(path: str) -> tuple[int, int] | None:
    """A source image's displayed size from its header, or ``None`` when it cannot be read."""

    if not path or not Path(path).is_file():
        return None
    try:
        with Image.open(path) as image:
            width, height = image.size
            if int(image.getexif().get(0x0112, 1) or 1) >= 5:  # rotated a quarter turn on load
                width, height = height, width
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None
    return width, height


def end_frame_crop_warning_for_paths(
    policy: Any, subject: str, source_path: str, end_path: str
) -> PolicyWarning | None:
    """The same warning for two files, read from their headers only."""

    source, end = image_size(source_path), image_size(end_path)
    if not isinstance(policy, Mapping) or not policy or source is None or end is None:
        return None
    return end_frame_crop_warning(
        subject, end[0], end[1], resolve_declared_target(policy, *source)[1]
    )


def source_crop_warning_for_path(policy: Any, subject: str, path: str) -> PolicyWarning | None:
    """The same warning for a file, read from its header only; ``None`` when it cannot be read."""

    size = image_size(path)
    if not isinstance(policy, Mapping) or size is None:
        return None
    return _crop_warning(policy, subject, *size)


__all__ = [
    "DEFAULT_WHY",
    "end_frame_crop_warning",
    "end_frame_crop_warning_for_paths",
    "image_size",
    "experimental_workflow_warning",
    "source_crop_warning",
    "source_crop_warning_for_path",
    "workflow_subject",
    "workflow_warning_records",
]
