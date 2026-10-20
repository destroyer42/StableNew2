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
_VERIFIED_POSE_CHAIN = (
    ("ResizeImageMaskNode", "input"),
    ("GetVideoComponents", "video"),
    ("LoadVideo", "file"),
)
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


def _verified_pose_chain(template: Mapping[str, Any], node_id: str) -> bool:
    """Check ordered image/video ports through to the declared driving-file placeholder.

    Recognising class names alone cannot prove timing: GetVideoComponents output 1 is audio,
    and a LoadVideo of a literal or another binding is not the clip the frame plan describes.
    Node IDs are deliberately irrelevant; only the connected path is inspected.
    """

    node = template.get(node_id)
    if not isinstance(node, Mapping):
        return False
    inputs = node.get("inputs")
    if not isinstance(inputs, Mapping):
        return False
    link = inputs.get("pose_video")
    seen: set[str] = set()
    for expected_class, input_name in _VERIFIED_POSE_CHAIN:
        if (
            not isinstance(link, (list, tuple))
            or len(link) != 2
            or type(link[1]) is not int
            or link[1] != 0
        ):
            return False
        upstream = str(link[0])
        if upstream in seen:
            return False
        seen.add(upstream)
        upstream_node = template.get(upstream)
        if (
            not isinstance(upstream_node, Mapping)
            or upstream_node.get("class_type") != expected_class
        ):
            return False
        inputs = upstream_node.get("inputs")
        if not isinstance(inputs, Mapping):
            return False
        link = inputs.get(input_name)
    return isinstance(link, str) and link == "{{input.pose_video}}"


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
    animate_inputs = template[animate_ids[0]].get("inputs")
    if not isinstance(animate_inputs, Mapping):
        return DrivingFrameConsumption(
            False, "The graph's driving-frame inputs are not recognised."
        )
    offset = animate_inputs.get("video_frame_offset")
    if type(offset) is not int or offset != 0 or "continue_motion" in animate_inputs:
        return DrivingFrameConsumption(False, "The graph seeks into the driving video.")
    if not _verified_pose_chain(template, animate_ids[0]):
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
