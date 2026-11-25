"""Which registered workflows can honestly be offered spatial alignment (PR-VID-MOTION-420).

Alignment is offered only where the *effective conditioning geometry* is established from the workflow's own
declaration, never from the mere presence of a driving-video field.  That means the pinned graph must send the
driving frames through exactly one resize -- ``ResizeImageMaskNode`` ("scale dimensions", centre crop, ``area``)
to the prepared source image's frozen ``target_width`` x ``target_height`` -- so that an aligned clip prepared at
precisely that size passes through the node unchanged and the operator's transform is the only spatial step.

The check reads the spec (graph, declared inputs, source-preparation policy); it never reads a file or a runtime.
A workflow that converts the frames before the resize (the Fun Control Canny path turns them into edges, so a
border introduced by alignment would become edges of its own) or whose resize is not this node is refused with the
reason, and ``motion_alignment`` is never asked to resolve a geometry for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.video.driving_frame_consumption import driving_frame_consumption
from src.video.workflow_frame_count import frame_count_policy

_CONSUMER = "WanAnimate2ToVideo"
_RESIZE = "ResizeImageMaskNode"
_EXPECTED_RESIZE = {
    "resize_type": "scale dimensions",
    "resize_type.width": "{{input.target_width}}",
    "resize_type.height": "{{input.target_height}}",
    "resize_type.crop": "center",
    "scale_method": "area",
}


@dataclass(frozen=True, slots=True)
class AlignmentSupport:
    supported: bool
    reason: str
    #: Plain-language statement of why the workflow's own resize does nothing to an aligned clip.
    resize_statement: str = ""

    def to_projection(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "reason": self.reason,
            "resize_statement": self.resize_statement,
        }


def comfy_center_crop_offsets(
    old_width: int, old_height: int, new_width: int, new_height: int
) -> tuple[int, int]:
    """The crop ComfyUI's ``common_upscale(..., crop="center")`` takes before it resizes (offsets per side).

    A transcription of the pinned runtime's arithmetic (``x = round((old_w - old_w * new_aspect/old_aspect)/2)``
    when the old frame is wider, the same for ``y`` when it is taller), kept so a test can show that a frame
    already at the target size has no crop."""

    old_aspect = old_width / old_height
    new_aspect = new_width / new_height
    x = y = 0
    if old_aspect > new_aspect:
        x = round((old_width - old_width * (new_aspect / old_aspect)) / 2)
    elif old_aspect < new_aspect:
        y = round((old_height - old_height * (old_aspect / new_aspect)) / 2)
    return x, y


def resize_is_spatially_inert(
    old_width: int, old_height: int, new_width: int, new_height: int
) -> bool:
    """True when the pinned centre-crop + ``area`` resize leaves a frame of this size unchanged.

    With equal size there is no crop (equal aspect) and an area (adaptive average) resize with the output size
    equal to the input size averages a one-pixel window per output pixel, i.e. the identity."""

    return (old_width, old_height) == (new_width, new_height) and comfy_center_crop_offsets(
        old_width, old_height, new_width, new_height
    ) == (0, 0)


def alignment_support(spec: Any) -> AlignmentSupport:
    """Whether ``spec`` takes an aligned driving clip, and the exact reason when it does not."""

    name = getattr(spec, "display_name", None) or getattr(spec, "workflow_id", "workflow")
    if "pose_video" not in tuple(getattr(spec, "declared_input_names", ()) or ()):
        return AlignmentSupport(
            False, f"'{name}' takes no driving video, so there is nothing to align."
        )
    consumption = driving_frame_consumption(spec)
    if not consumption.verified:
        return AlignmentSupport(
            False,
            f"Alignment is not offered: {consumption.reason} The frames it consumes were not verified "
            "against its pinned runtime.",
        )
    if consumption.requires_prepared_source:
        return AlignmentSupport(
            False,
            "Alignment is not offered for this workflow: it converts the driving frames to edges before "
            "resizing, so a border introduced by alignment would become edges of its own and its effect on "
            "conditioning is not established.",
        )
    defaults = getattr(spec, "backend_defaults", None) or {}
    policy = defaults.get("source_preparation")
    template = defaults.get("prompt_template")
    if not isinstance(policy, Mapping) or not isinstance(template, Mapping):
        return AlignmentSupport(
            False, "Alignment is not offered: the workflow declares no source geometry to align to."
        )
    if str(policy.get("resize_policy") or "") != "cover_resize_center_crop":
        return AlignmentSupport(
            False, "Alignment is not offered: the workflow's target-frame policy is not recognised."
        )
    if frame_count_policy(spec) is None:
        return AlignmentSupport(
            False, "Alignment is not offered: the workflow declares no length policy."
        )
    consumers = [
        node
        for node in template.values()
        if isinstance(node, Mapping) and node.get("class_type") == _CONSUMER
    ]
    if len(consumers) != 1:
        return AlignmentSupport(
            False, "Alignment is not offered: the graph's driving-frame consumer is not recognised."
        )
    link = (consumers[0].get("inputs") or {}).get("pose_video")
    resize = template.get(str(link[0])) if isinstance(link, (list, tuple)) and link else None
    inputs = resize.get("inputs") if isinstance(resize, Mapping) else None
    if (
        not isinstance(resize, Mapping)
        or resize.get("class_type") != _RESIZE
        or not isinstance(inputs, Mapping)
        or any(inputs.get(key) != value for key, value in _EXPECTED_RESIZE.items())
    ):
        return AlignmentSupport(
            False,
            "Alignment is not offered: the graph's driving-frame resize is not the verified centre-crop "
            "resize to the frozen target size, so the effective geometry cannot be established.",
        )
    return AlignmentSupport(
        True,
        "",
        "The workflow resizes every driving frame to the frozen target size with a centre crop. A clip "
        "prepared at exactly that size has no crop and an equal-size area resize is the identity, so the "
        "alignment is the only spatial step.",
    )


__all__ = [
    "AlignmentSupport",
    "alignment_support",
    "comfy_center_crop_offsets",
    "resize_is_spatially_inert",
]
