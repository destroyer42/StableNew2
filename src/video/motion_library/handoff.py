"""Hand a library clip to the Video Workflow as its driving video (PR-VID-MOTION-LIB-353).

This module only *decides and describes*.  ``plan_driving_handoff`` verifies the clip against its recorded
SHA-256 and checks the selected workflow's declared contract, then returns the one form field the tab may
fill (``pose_video_path``) and the library identity to remember beside it.  It builds no job, calls no
builder and queues nothing: the operator still previews and submits through the canonical admission path,
and ``Prepare Motion Source`` stays the only thing that may trim, align or resample the clip.

The library is neutral about which model consumes a clip.  Compatibility is therefore a property of the
*selected workflow*, never of the clip: a refusal names that workflow, and every advisory is phrased as
something the workflow's own checks will confirm.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.video.motion_library.models import (
    REVIEW_REJECTED,
    REVIEW_UNREVIEWED,
    MotionAsset,
)
from src.video.motion_library.store import LibraryError, MotionLibraryStore
from src.video.motion_library.verification import (
    FILE_CHANGED,
    FILE_MISSING,
    FILE_OK,
    verify_content,
)

FIELD_DRIVING_VIDEO = "pose_video_path"
#: Form key carrying the library identity to the job builder (which re-verifies it against the frozen clip).
FIELD_LIBRARY_BINDING = "motion_library_asset"
_FPS_TOLERANCE = 0.5


@dataclass(frozen=True, slots=True)
class HandoffPlan:
    ok: bool
    asset_id: str
    path: str = ""
    sha256: str = ""
    workflow_id: str = ""
    workflow_version: str = ""
    refusal: str = ""
    #: What the operator can do about a refusal.
    corrective_action: str = ""
    advisories: tuple[str, ...] = ()
    preparation_offered: bool = False

    @property
    def form_fields(self) -> dict[str, Any]:
        """The only form field a successful handoff may populate."""

        return {FIELD_DRIVING_VIDEO: self.path} if self.ok else {}

    @property
    def binding(self) -> dict[str, str]:
        return {"asset_id": self.asset_id, "sha256": self.sha256} if self.ok else {}


def _refuse(asset: MotionAsset, reason: str, action: str, meta: Mapping[str, Any]) -> HandoffPlan:
    return HandoffPlan(
        ok=False,
        asset_id=asset.asset_id,
        workflow_id=str(meta.get("workflow_id") or ""),
        workflow_version=str(meta.get("workflow_version") or ""),
        refusal=reason,
        corrective_action=action,
    )


def _workflow_name(meta: Mapping[str, Any]) -> str:
    return str(meta.get("display_name") or meta.get("workflow_id") or "the selected workflow")


def _advisories(asset: MotionAsset, meta: Mapping[str, Any], preparation: bool) -> tuple[str, ...]:
    notes: list[str] = []
    name = _workflow_name(meta)
    frames_meta = meta.get("frame_count")
    frames_meta = frames_meta if isinstance(frames_meta, Mapping) else {}
    output_fps = frames_meta.get("fps")
    if asset.fps is not None and isinstance(output_fps, (int, float)) and output_fps > 0:
        if abs(asset.fps - float(output_fps)) > _FPS_TOLERANCE:
            how = (
                "Prepare Motion Source can convert it explicitly."
                if preparation
                else "this workflow offers no verified preparation, so it is used as it is."
            )
            notes.append(
                f"The clip is {asset.fps:g} fps; {name} generates at {float(output_fps):g} fps; {how}"
            )
    choices: list[int] = []
    for choice in frames_meta.get("choices") or []:
        if isinstance(choice, Mapping):
            frames = choice.get("frames")
            if isinstance(frames, int):
                choices.append(frames)
    if asset.frame_count is not None and choices:
        if asset.frame_count < min(choices):
            notes.append(
                f"The clip has {asset.frame_count} frames; the shortest length {name} offers is "
                f"{min(choices)}."
            )
        elif asset.frame_count > max(choices) and preparation:
            notes.append(
                f"The clip has {asset.frame_count} frames; {name} uses at most {max(choices)}. "
                "Prepare Motion Source can trim it to an exact window."
            )
    if not preparation:
        notes.append(
            f"{name} has no verified Prepare Motion Source contract, so geometry and frame rules are "
            "checked when you preview the job."
        )
    if meta.get("experimental"):
        notes.append(
            f"{name} is experimental: the job needs its own opt-in before it can be queued."
        )
    if asset.review_status == REVIEW_REJECTED:
        notes.append("You marked this clip rejected.")
    elif asset.review_status == REVIEW_UNREVIEWED:
        notes.append("This clip has not been reviewed.")
    if asset.origin is not None and asset.origin.motion_achieved is False:
        notes.append("You recorded that this generated clip did not achieve the requested motion.")
    notes.append(
        "Library clips are model-neutral: being usable here does not mean every motion workflow "
        "accepts it. The selected workflow's own checks decide."
    )
    return tuple(notes)


def plan_driving_handoff(
    store: MotionLibraryStore,
    asset_id: str,
    workflow_meta: Mapping[str, Any] | None,
    *,
    cancel: threading.Event | None = None,
) -> HandoffPlan:
    """Verify ``asset_id`` and check ``workflow_meta`` (one entry of ``list_workflow_specs``).

    Hashes the whole clip, so run it off the UI thread.  Never raises for an expected refusal."""

    meta: Mapping[str, Any] = workflow_meta if isinstance(workflow_meta, Mapping) else {}
    asset = store.get(asset_id)
    if asset is None:
        return HandoffPlan(
            ok=False,
            asset_id=str(asset_id or ""),
            refusal="That library asset no longer exists.",
            corrective_action="Refresh the library list.",
        )
    if not meta.get("workflow_id"):
        return _refuse(
            asset,
            "No Video Workflow is selected.",
            "Choose a workflow that takes a driving video, then use the clip again.",
            meta,
        )
    readiness = meta.get("motion_readiness")
    readiness = readiness if isinstance(readiness, Mapping) else {}
    name = _workflow_name(meta)
    if readiness.get("accepts_driving_video") is not True:
        return _refuse(
            asset,
            f"{name} does not take a driving video, so the clip was not used.",
            "Select a workflow that declares a driving video input. No workflow was changed for you.",
            meta,
        )
    try:
        path = store.asset_path(asset)
    except LibraryError as exc:
        return _refuse(asset, str(exc), "Relink the clip to a file with the same SHA-256.", meta)
    check = verify_content(asset, path, cancel)
    if check.state != FILE_OK:
        action = {
            FILE_MISSING: "Relink the file (it must hash to the same SHA-256) or import the new file.",
            FILE_CHANGED: "Import the changed file as a new asset, or restore the original and relink it.",
        }.get(check.state, "Check the file and try again.")
        return _refuse(asset, check.message, action, meta)
    consumption = readiness.get("driving_frame_consumption")
    consumption = consumption if isinstance(consumption, Mapping) else {}
    preparation = bool(consumption.get("verified")) and bool(meta.get("frame_count"))
    return HandoffPlan(
        ok=True,
        asset_id=asset.asset_id,
        path=str(Path(path)),
        sha256=asset.sha256,
        workflow_id=str(meta.get("workflow_id") or ""),
        workflow_version=str(meta.get("workflow_version") or ""),
        advisories=_advisories(asset, meta, preparation),
        preparation_offered=preparation,
    )


def binding_for_submission(
    binding: Mapping[str, Any] | None, *, current_path: str, bound_path: str
) -> dict[str, str] | None:
    """The library identity to freeze with a job -- only while the form still names the handed-off file."""

    if not binding or not bound_path or not current_path:
        return None
    if Path(current_path).expanduser() != Path(bound_path):
        return None
    asset_id = str(binding.get("asset_id") or "")
    sha = str(binding.get("sha256") or "")
    return {"asset_id": asset_id, "sha256": sha} if asset_id and sha else None


__all__ = [
    "FIELD_DRIVING_VIDEO",
    "FIELD_LIBRARY_BINDING",
    "HandoffPlan",
    "binding_for_submission",
    "plan_driving_handoff",
]
