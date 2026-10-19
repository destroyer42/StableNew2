"""Which driving-video frames a workflow's graph consumes, verified against its pinned runtime.

Split out of ``motion_source_readiness`` (PR-VID-MOTION-210) so the verified runtime contract can be
shared by the display-only advisories and by the explicit "Prepare Motion Source" action without the
job-affecting path importing the advisory module.  Pure: it reads only the spec it is given.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# ComfyUI revisions whose ``WanAnimate2ToVideo`` was read (read-only) for PR-VID-196: with the
# pose video connected it takes ``pose_video[video_frame_offset:]`` and then ``[:length]`` -- driving
# frame ``offset + i`` conditions generated frame ``i``, one for one, with no frame-rate
# conversion -- and holds the last driving frame when the clip is shorter than ``length``.  The
# revisions are the catalog's own provenance values (v0.37.0 and the managed v0.38.0 runtime).
VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS = frozenset(
    {
        "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",  # ComfyUI v0.37.0
        "6b747c0428c343e1417219641db93a4fb7cb69ae",  # ComfyUI v0.38.0
    }
)
_NODE_WITH_POSE_INPUT = "WanAnimate2ToVideo"
# Nodes that carry the clip to ``pose_video`` in the qualified graph.  None resamples frame rate or
# changes the frame count (decoded frames in order; per-frame resize with a centre crop).
_VERIFIED_POSE_CHAIN_NODES = frozenset({"LoadVideo", "GetVideoComponents", "ResizeImageMaskNode"})
_CONSUMPTION_RULE = (
    "Each generated frame is conditioned on one driving frame, in order from the start of the "
    "clip, with no frame-rate conversion; a shorter clip repeats its last frame."
)


@dataclass(frozen=True, slots=True)
class DrivingFrameConsumption:
    verified: bool
    reason: str
    rule: str = ""
    runtime_revision: str = ""


def _pose_chain_classes(template: Mapping[str, Any], node_id: str) -> list[str] | None:
    """Class types from the pose input back to its source, or None when the chain is not linear."""

    node = template.get(node_id)
    if not isinstance(node, Mapping):
        return None
    link = (node.get("inputs") or {}).get("pose_video")
    classes: list[str] = []
    seen: set[str] = set()
    while isinstance(link, (list, tuple)) and link:
        upstream = str(link[0])
        if upstream in seen:
            return None
        seen.add(upstream)
        upstream_node = template.get(upstream)
        if not isinstance(upstream_node, Mapping):
            return None
        class_type = str(upstream_node.get("class_type") or "")
        classes.append(class_type)
        inputs = upstream_node.get("inputs") or {}
        link = next(
            (
                inputs[name]
                for name in ("input", "video", "images", "image")
                if isinstance(inputs.get(name), (list, tuple))
            ),
            None,
        )
    return classes or None


def driving_frame_consumption(spec: Any) -> DrivingFrameConsumption:
    """Whether this spec's driving-frame timing was verified against the pinned node source.

    Decided from the spec itself (declared graph and runtime revision), never from a name: the
    template's pose chain must be exactly the verified nodes, the pose offset must be the literal
    zero, and the runtime revision must be one that was read."""

    declared = tuple(getattr(spec, "declared_input_names", ()) or ())
    if "pose_video" not in declared:
        return DrivingFrameConsumption(False, "The workflow takes no driving video.")
    defaults = getattr(spec, "backend_defaults", None) or {}
    template = defaults.get("prompt_template")
    if not isinstance(template, Mapping):
        return DrivingFrameConsumption(False, "The workflow graph is not available to verify.")
    animate_ids = [
        node_id
        for node_id, node in template.items()
        if isinstance(node, Mapping) and node.get("class_type") == _NODE_WITH_POSE_INPUT
    ]
    if len(animate_ids) != 1:
        return DrivingFrameConsumption(
            False, "The graph's driving-frame consumer is not recognised."
        )
    animate_inputs = template[animate_ids[0]].get("inputs") or {}
    if animate_inputs.get("video_frame_offset") != 0:
        return DrivingFrameConsumption(False, "The graph seeks into the driving video.")
    chain = _pose_chain_classes(template, animate_ids[0])
    if chain is None or not set(chain) <= _VERIFIED_POSE_CHAIN_NODES or "LoadVideo" not in chain:
        return DrivingFrameConsumption(
            False, "The driving video passes through nodes whose timing was not verified."
        )
    provenance = defaults.get("provenance")
    revision = (
        str(provenance.get("comfyui_revision") or "") if isinstance(provenance, Mapping) else ""
    )
    if revision not in VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS:
        return DrivingFrameConsumption(
            False,
            "The workflow's ComfyUI revision was not verified for driving-frame consumption.",
            runtime_revision=revision,
        )
    return DrivingFrameConsumption(
        True,
        "Verified against the pinned ComfyUI node source.",
        rule=_CONSUMPTION_RULE,
        runtime_revision=revision,
    )


__all__ = [
    "VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS",
    "DrivingFrameConsumption",
    "driving_frame_consumption",
]
