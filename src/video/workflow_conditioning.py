"""What a driving-video workflow actually does with the driving clip (PR-VID-MOTION-430).

A pure, display-and-evaluation projection of registered ``WorkflowSpec`` entries.  It is neither a catalog field nor a second
engine registry: the contract is *derived* from each spec's own graph (the nodes that the ``pose_video`` input flows through
before it reaches the consuming node) and from the spec's declared frame policy, source preparation, controls, governance and
resource readiness.  Nothing here reads a file, calls Comfy, or can change what a backend executes.

Four things are kept apart on purpose, because the same MP4 means different things at each step:

1. **Underlying movement** - the animation or footage whose motion is wanted (Motion Library identity, not modelled here).
2. **Driving representation** - what the pixels of the supplied clip depict (``REPRESENTATIONS``).  Every representation travels
   as an ordinary RGB video; a silhouette render is a silhouette-*derived RGB video*, not a different tensor.
3. **Workflow conditioning mechanism** - what the registered graph does to those RGB frames before the model sees them
   (``MECHANISMS``): Wan-Animate-2 resizes them and VAE-encodes them directly; Fun Control runs Canny at the prepared clip's own
   size, *then* centre-crops and bilinearly resizes the edge image, then VAE-encodes it.
4. **Tensor the model consumes** - ``ConditioningContract.consumes``.

No single catalog field, and no generic ``pose_video`` transport name, says that representations are interchangeable.  A
precomputed edge map is refused for both registered mechanisms (Fun Control would run Canny a second time on it), and no
registered graph consumes an explicit pose map; a skeleton *render* is not an OpenPose map.

Statements about the pinned runtime were read from ComfyUI v0.38.0 (``config/managed_comfy_runtime.json``) source:
``comfy_extras/nodes_wan.py`` (``Wan22FunControlToVideo``, ``WanAnimate2ToVideo``) and ``comfy_extras/nodes_canny.py``.  They are
``BASIS_RUNTIME_SOURCE`` facts, not measurements.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from src.video.motion_alignment_support import alignment_support
from src.video.workflow_controls import operator_controls
from src.video.workflow_frame_count import frame_count_policy, legal_frame_counts

REP_RGB_FOOTAGE = "rgb_footage"
REP_RENDERED_CHARACTER = "rendered_character"
REP_RENDERED_SILHOUETTE = "rendered_silhouette"
REP_RENDERED_SKELETON = "rendered_skeleton"
REP_PRECOMPUTED_EDGES = "precomputed_edge_map"
REP_POSE_MAP = "pose_map"
REPRESENTATIONS = (
    REP_RGB_FOOTAGE,
    REP_RENDERED_CHARACTER,
    REP_RENDERED_SILHOUETTE,
    REP_RENDERED_SKELETON,
    REP_PRECOMPUTED_EDGES,
    REP_POSE_MAP,
)
REPRESENTATION_LABELS = {
    REP_RGB_FOOTAGE: "Recorded or generated RGB footage",
    REP_RENDERED_CHARACTER: "Rendered character",
    REP_RENDERED_SILHOUETTE: "Rendered high-contrast silhouette",
    REP_RENDERED_SKELETON: "Rendered skeleton (not an OpenPose map)",
    REP_PRECOMPUTED_EDGES: "Precomputed edge map",
    REP_POSE_MAP: "Explicit pose map (keypoints or OpenPose image)",
}
#: Representations that are an ordinary RGB video of something (what a registered ``pose_video`` input accepts).
RGB_VIDEO_REPRESENTATIONS = (
    REP_RGB_FOOTAGE,
    REP_RENDERED_CHARACTER,
    REP_RENDERED_SILHOUETTE,
    REP_RENDERED_SKELETON,
)
#: ``DerivationRecord.profile`` (the Blender conversion profiles) -> driving representation.
PROFILE_REPRESENTATION = {
    "character_reference": REP_RENDERED_CHARACTER,
    "high_contrast_silhouette": REP_RENDERED_SILHOUETTE,
    "skeleton_reference": REP_RENDERED_SKELETON,
}

MECH_RGB_VAE = "rgb_frames_vae_encoded"
MECH_CANNY_THEN_RESIZE = "rgb_canny_edges_then_resize"
MECHANISM_LABELS = {
    MECH_RGB_VAE: "RGB frames, resized and VAE-encoded directly",
    MECH_CANNY_THEN_RESIZE: "Canny edge map of the RGB frames, then cropped, resized and VAE-encoded",
}
MECH_UNKNOWN = "unrecognized"

BASIS_CATALOG = "catalog"
BASIS_RUNTIME_SOURCE = "runtime_source"
BASIS_HISTORICAL = "historical"
BASIS_HEURISTIC = "heuristic"
BASIS_MEASURED = "measured"
BASIS_LABELS = {
    BASIS_CATALOG: "declared by the catalog entry",
    BASIS_RUNTIME_SOURCE: "read from the pinned ComfyUI source",
    BASIS_HISTORICAL: "historical observation (one host, limited samples)",
    BASIS_HEURISTIC: "heuristic",
    BASIS_MEASURED: "measured from the files in front of you",
}

PINNED_RUNTIME = "ComfyUI v0.38.0 (config/managed_comfy_runtime.json)"
_DRIVER_PLACEHOLDER = re.compile(r"\{\{\s*input\.pose_video\s*\}\}")

_EV_212 = "docs/Subsystems/Video/PR-VID-MOTION-212_Conditioning_Semantics_and_Fidelity.md"
_EV_352 = "docs/Subsystems/Video/PR-VID-FUN-352_Fun_Control_5B.md"
_EV_354 = "docs/Subsystems/Video/PR-VID-MOTION-354_Motion_Conversion_and_Fun_Qualification.md"
_EV_410 = "docs/Subsystems/Video/PR-VID-MOTION-410_Motion_Fidelity_and_Transfer_Evaluation.md"
_EV_420 = "docs/Subsystems/Video/PR-VID-MOTION-420_Subject_Alignment_and_Compatibility.md"

#: Graph node classes whose role in the driver's path is known; the stage detail is what the pinned runtime source shows.
_STAGE_KNOWLEDGE: dict[str, tuple[str, str]] = {
    "LoadVideo": ("decode", "decodes the prepared driving MP4"),
    "GetVideoComponents": ("decode", "splits the video into ordered frames (and rate)"),
    "ImageFromBatch": ("frame_select", "takes frames from the ordered batch"),
    "ResizeImageMaskNode": (
        "resize",
        "scales the frames to the generation geometry, centre-cropping to the aspect (area resampling)",
    ),
    "Canny": (
        "edge_detect",
        "Canny edge detection (kornia) on each frame at the size it arrives, thresholds fixed in the graph; "
        "the result is a one-channel edge image repeated to three channels",
    ),
    "CLIPVisionEncode": (
        "vision_context",
        "CLIP-vision encoding of the driving clip's first frame (extra visual context, not motion)",
    ),
}
#: Consumer nodes: what the pinned runtime does inside the node (BASIS_RUNTIME_SOURCE).
_CONSUMER_KNOWLEDGE: dict[str, tuple[str, str, str]] = {
    "Wan22FunControlToVideo": (
        MECH_CANNY_THEN_RESIZE,
        "VAE-encoded edge image (control_video, first `length` frames, centre-cropped to the aspect and bilinearly "
        "resized to width x height inside the node)",
        "control_video",
    ),
    "WanAnimate2ToVideo": (
        MECH_RGB_VAE,
        "VAE-encoded RGB frames (pose_video, first `length` frames, resized to width x height with area "
        "resampling inside the node; a clip shorter than `length` is padded by holding its last frame)",
        "pose_video",
    ),
}


@dataclass(frozen=True, slots=True)
class ConditioningStage:
    order: int
    kind: str
    node: str
    detail: str
    basis: str = BASIS_RUNTIME_SOURCE

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


@dataclass(frozen=True, slots=True)
class RepresentationAcceptance:
    """Whether a driving representation can be supplied to one workflow, and what actually happens to it."""

    representation: str
    accepted: bool
    #: What the workflow does with it (accepted) or why it is refused.
    note: str
    basis: str = BASIS_CATALOG

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


@dataclass(frozen=True, slots=True)
class ConditioningContract:
    workflow_id: str
    workflow_version: str
    display_name: str
    mechanism: str
    consumes: str
    stages: tuple[ConditioningStage, ...]
    #: ``True``/``False`` when the graph has a preprocessing stage (edge detection); ``None`` when it has none.
    preprocessing_before_resize: bool | None
    geometry: Mapping[str, Any]
    frame_policy: Mapping[str, int] | None
    legal_frames: tuple[int, ...]
    fps: int | None
    exact_prepared_frames: bool
    required_preparation: tuple[str, ...]
    supported_controls: tuple[str, ...]
    governance: str
    trial: bool
    qualification_status: str
    resource_readiness: Mapping[str, Any]
    refusal_reason: str
    limitations: tuple[tuple[str, str], ...]
    evidence: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return (self.workflow_id, self.workflow_version)

    @property
    def mechanism_label(self) -> str:
        return MECHANISM_LABELS.get(self.mechanism, "Unrecognized conditioning path")

    @property
    def status_label(self) -> str:
        if self.refusal_reason:
            return "Refused"
        if self.trial:
            return "Experimental trial (not qualified)"
        if self.governance == "experimental":
            return "Experimental"
        return self.governance.capitalize() if self.governance else "Unknown"

    @property
    def edge_preprocessing(self) -> bool:
        return any(stage.kind == "edge_detect" for stage in self.stages)

    def acceptance(self, representation: str) -> RepresentationAcceptance:
        return representation_acceptance(self, representation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "display_name": self.display_name,
            "mechanism": self.mechanism,
            "mechanism_label": self.mechanism_label,
            "consumes": self.consumes,
            "stages": [stage.to_dict() for stage in self.stages],
            "preprocessing_before_resize": self.preprocessing_before_resize,
            "geometry": dict(self.geometry),
            "frame_policy": dict(self.frame_policy) if self.frame_policy else None,
            "legal_frames": list(self.legal_frames),
            "fps": self.fps,
            "exact_prepared_frames": self.exact_prepared_frames,
            "required_preparation": list(self.required_preparation),
            "supported_controls": list(self.supported_controls),
            "governance": self.governance,
            "trial": self.trial,
            "qualification_status": self.qualification_status,
            "resource_readiness": dict(self.resource_readiness),
            "refusal_reason": self.refusal_reason,
            "limitations": [{"text": text, "basis": basis} for text, basis in self.limitations],
            "evidence": list(self.evidence),
        }


# ------------------------------------------------------------------------------------------------ graph tracing


def _references(value: Any) -> Iterable[str]:
    """Node ids an input value points at (``["12", 0]`` links)."""

    if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str):
        if isinstance(value[1], int) and not isinstance(value[1], bool):
            yield value[0]


def _inputs_of(node: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = node.get("inputs")
    return raw if isinstance(raw, Mapping) else {}


def trace_driver_path(
    graph: Mapping[str, Any],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """``(path, consumers)`` of the driving input through a rendered-template graph.

    ``path`` lists ``(node_id, class_type)`` from the node that loads ``{{input.pose_video}}`` outward in graph (id) order,
    including every node reachable from it that is not itself a consumer; ``consumers`` are the reachable nodes this module
    knows how to describe.  An empty path means the graph does not use the driving input."""

    roots = [
        node_id
        for node_id, node in graph.items()
        if isinstance(node, Mapping)
        and any(
            isinstance(v, str) and _DRIVER_PLACEHOLDER.search(v) for v in _inputs_of(node).values()
        )
    ]
    if not roots:
        return [], []
    reached: dict[str, str] = {}
    frontier = list(roots)
    while frontier:
        current = frontier.pop()
        if current in reached:
            continue
        reached[current] = str(graph[current].get("class_type", ""))
        if reached[current] in _CONSUMER_KNOWLEDGE:
            continue  # what the consumer feeds (sampler, decode, save) is not conditioning
        for node_id, node in graph.items():
            if node_id in reached or not isinstance(node, Mapping):
                continue
            if current in {ref for v in _inputs_of(node).values() for ref in _references(v)}:
                frontier.append(node_id)
    ordered = sorted(reached.items(), key=lambda item: (len(item[0]), item[0]))
    consumers = [(i, c) for i, c in ordered if c in _CONSUMER_KNOWLEDGE]
    path = [(i, c) for i, c in ordered if c not in _CONSUMER_KNOWLEDGE]
    return path, consumers


def _stages(
    path: Sequence[tuple[str, str]], consumer: tuple[str, str] | None
) -> tuple[ConditioningStage, ...]:
    stages: list[ConditioningStage] = []
    for order, (_node_id, class_type) in enumerate(path, start=1):
        kind, detail = _STAGE_KNOWLEDGE.get(
            class_type, ("unrecognized", f"{class_type}: not described by this module")
        )
        stages.append(ConditioningStage(order, kind, class_type, detail))
    if consumer is not None:
        _mechanism, consumes, _port = _CONSUMER_KNOWLEDGE[consumer[1]]
        stages.append(ConditioningStage(len(stages) + 1, "vae_encode", consumer[1], consumes))
    return tuple(stages)


# ------------------------------------------------------------------------------------------------ contract


def _required_preparation(spec: Any) -> tuple[str, ...]:
    policy = (getattr(spec, "backend_defaults", None) or {}).get("motion_source_policy")
    steps = [
        "Prepare Motion Source: the exact driving frames this workflow version and length consume (24 FPS)"
    ]
    if not (isinstance(policy, Mapping) and policy.get("exact_prepared_frames")):
        steps[0] = "Prepare Motion Source (optional for this workflow)"
    support = alignment_support(spec)
    steps.append(
        "Align Motion is available for this workflow"
        if support.supported
        else f"Align Motion is not available: {support.reason}"
    )
    return tuple(steps)


def _limitations(mechanism: str, *, trial: bool, edge_size: bool) -> tuple[tuple[str, str], ...]:
    notes: list[tuple[str, str]] = []
    if mechanism == MECH_RGB_VAE:
        notes += [
            (
                "The driver's pixels reach the model resized only: its appearance and background are visible to the "
                "model, so a driver unlike the reference subject can leak into the result.",
                BASIS_RUNTIME_SOURCE,
            ),
            (
                "The driving clip's first frame is also encoded as extra visual context; a first-frame pose that "
                "differs from the source image has produced an unnatural opening.",
                BASIS_HISTORICAL,
            ),
            (
                "Subject attachment, initial-pose mismatch and locomotion failed in earlier experiments; a later "
                "head-turn and wave pilot succeeded with little visible difference between control settings.",
                BASIS_HISTORICAL,
            ),
        ]
    elif mechanism == MECH_CANNY_THEN_RESIZE:
        notes += [
            (
                "Only edges survive Canny, so colour, shading and flat interior regions are discarded; busy "
                "backgrounds and textured clothing add edges that compete with the body outline.",
                BASIS_RUNTIME_SOURCE,
            ),
            (
                "Canny runs on the prepared clip at its own size before the crop and resize, so a large driver costs "
                "memory in proportion to its pixels (the kornia non-maximum-suppression stage holds eight channels "
                "per frame); two 4K drivers failed with memory or time-outs before the clips were pre-scaled, and "
                "Prepare Motion Source now scales an input longer than 832 px to an 832-pixel long edge for this workflow.",
                BASIS_HISTORICAL,
            ),
            (
                "The 14-case campaign on one 12 GB host was technically feasible with appropriately sized inputs; "
                "it is not a visual-quality, repeatability or hardware qualification.",
                BASIS_HISTORICAL,
            ),
        ]
    if trial:
        notes.append(
            (
                "Trial version: the resource floors are provisional (taken from the TI2V-5B figures), not "
                "independently established Fun Control thresholds.",
                BASIS_CATALOG,
            )
        )
    if edge_size:
        notes.append(("No exact start or end anchor and no identity guarantee.", BASIS_CATALOG))
    return tuple(notes)


def conditioning_contract(spec: Any) -> ConditioningContract | None:
    """The contract of one registered driving-video spec, or ``None`` when it does not consume a driving video."""

    declared = tuple(getattr(spec, "declared_input_names", ()) or ())
    if "pose_video" not in declared:
        return None
    defaults = getattr(spec, "backend_defaults", None) or {}
    template = defaults.get("prompt_template")
    path, consumers = trace_driver_path(template if isinstance(template, Mapping) else {})
    consumer = consumers[0] if consumers else None
    mechanism = _CONSUMER_KNOWLEDGE[consumer[1]][0] if consumer is not None else MECH_UNKNOWN
    stages = _stages(path, consumer)
    edge_index = next((s.order for s in stages if s.kind == "edge_detect"), None)
    resize_index = next((s.order for s in stages if s.kind == "resize"), None)
    if edge_index is None:
        before_resize: bool | None = None
    elif resize_index is not None:
        before_resize = edge_index < resize_index
    else:
        before_resize = (
            True  # the only resize is inside the consuming node, after every graph stage
        )
    policy = frame_count_policy(spec)
    readiness = defaults.get("resource_readiness")
    readiness = dict(readiness) if isinstance(readiness, Mapping) else {}
    projection = defaults.get("operator_projection")
    projection = projection if isinstance(projection, Mapping) else {}
    refusal = str(projection.get("admission_block_reason") or "")
    trial = bool(projection.get("trial_unqualified"))
    preparation = defaults.get("source_preparation")
    geometry: dict[str, Any] = dict(preparation) if isinstance(preparation, Mapping) else {}
    consumes = _CONSUMER_KNOWLEDGE[consumer[1]][1] if consumer is not None else "unrecognized"
    evidence = (
        (_EV_212, _EV_352, _EV_354)
        if mechanism == MECH_CANNY_THEN_RESIZE
        else (_EV_212, _EV_410, _EV_420)
    )
    policy_block = defaults.get("motion_source_policy")
    return ConditioningContract(
        workflow_id=str(spec.workflow_id),
        workflow_version=str(spec.workflow_version),
        display_name=str(getattr(spec, "display_name", spec.workflow_id)),
        mechanism=mechanism,
        consumes=consumes,
        stages=stages,
        preprocessing_before_resize=before_resize,
        geometry=geometry,
        frame_policy=policy,
        legal_frames=tuple(legal_frame_counts(spec)),
        fps=policy["fps"] if policy else None,
        exact_prepared_frames=bool(
            isinstance(policy_block, Mapping) and policy_block.get("exact_prepared_frames")
        ),
        required_preparation=_required_preparation(spec),
        supported_controls=tuple(c["name"] for c in operator_controls(spec)),
        governance=str(getattr(spec, "governance_state", "")),
        trial=trial,
        qualification_status=str(readiness.get("qualification_status") or "unspecified"),
        resource_readiness=readiness,
        refusal_reason=refusal,
        limitations=_limitations(
            mechanism, trial=trial, edge_size=mechanism == MECH_CANNY_THEN_RESIZE
        ),
        evidence=evidence,
    )


@lru_cache(maxsize=1)
def registered_contracts() -> dict[tuple[str, str], ConditioningContract]:
    """Contracts of every built-in driving-video workflow, keyed by ``(workflow_id, version)`` (built once)."""

    from src.video.workflow_catalog import build_builtin_workflow_specs

    return {c.key: c for c in conditioning_contracts(build_builtin_workflow_specs())}


def takes_motion_prompt(workflow_id: str, workflow_version: str) -> bool:
    """Whether the registered workflow declares a separate motion prompt (``pose_prompt``) as an operator control.

    Wan-Animate-2 1.1.0+ does; Fun Control does not (its movement comes from the driving clip and the main prompt), so a
    case's motion prompt is *not sent* to it and is disclosed rather than forced into an unsupported control."""

    contract = registered_contracts().get((workflow_id, workflow_version))
    return contract is not None and "pose_prompt" in contract.supported_controls


def conditioning_contracts(specs: Iterable[Any]) -> tuple[ConditioningContract, ...]:
    """Contracts of every driving-video spec in ``specs`` (prompt-only workflows are skipped, never reinterpreted)."""

    found = (conditioning_contract(spec) for spec in specs)
    return tuple(c for c in found if c is not None)


# ------------------------------------------------------------------------------------------------ acceptance


def representation_acceptance(
    contract: ConditioningContract, representation: str
) -> RepresentationAcceptance:
    """What happens when ``representation`` is supplied as the driving clip of ``contract``'s workflow."""

    if representation not in REPRESENTATIONS:
        return RepresentationAcceptance(
            representation, False, f"'{representation}' is not a known representation."
        )
    label = REPRESENTATION_LABELS[representation]
    if contract.mechanism == MECH_UNKNOWN:
        return RepresentationAcceptance(
            representation,
            False,
            "This workflow's driving-video path is not recognized, so nothing can be claimed.",
        )
    if representation == REP_PRECOMPUTED_EDGES:
        reason = (
            "Refused: this graph runs Canny on whatever clip it is given, so a precomputed edge video would be edge-"
            "detected a second time. There is no direct edge-input mode; one would need its own versioned workflow."
            if contract.edge_preprocessing
            else "Refused: no registered graph feeds an edge map to this workflow; the clip is consumed as RGB frames."
        )
        return RepresentationAcceptance(representation, False, reason)
    if representation == REP_POSE_MAP:
        return RepresentationAcceptance(
            representation,
            False,
            "Refused: no registered graph consumes an explicit pose map. Rendered skeletons are ordinary RGB renders, "
            "not OpenPose maps, and are never relabelled as one.",
        )
    if contract.mechanism == MECH_CANNY_THEN_RESIZE:
        detail = {
            REP_RGB_FOOTAGE: "Accepted as an RGB clip; Canny keeps its edges, including background and clothing "
            "texture.",
            REP_RENDERED_CHARACTER: "Accepted as an RGB clip; Canny keeps the character's outline and the texture "
            "edges of its render.",
            REP_RENDERED_SILHOUETTE: "Accepted as a silhouette-derived RGB clip; Canny then keeps essentially the "
            "outline. It is not an externally computed edge tensor.",
            REP_RENDERED_SKELETON: "Accepted as a skeleton-render RGB clip; Canny then detects the edges of the "
            "drawn lines. Head orientation and body shape are only as present as the render makes them.",
        }[representation]
    else:
        detail = {
            REP_RGB_FOOTAGE: "Accepted; the frames are encoded as they are, so the driver's appearance and background "
            "are visible to the model.",
            REP_RENDERED_CHARACTER: "Accepted; the render's appearance is visible to the model.",
            REP_RENDERED_SILHOUETTE: "Accepted as RGB frames; there is no edge step, so the silhouette's flat colours "
            "are encoded directly (not tested as an Animate-2 driver in this repository).",
            REP_RENDERED_SKELETON: "Accepted as RGB frames; this is not the skeletal pose input some other tools "
            "expect, and its effect on this workflow is untested.",
        }[representation]
    basis = BASIS_CATALOG
    return RepresentationAcceptance(representation, True, f"{label}: {detail}", basis)


# ------------------------------------------------------------------------------------------------ display projection


def conditioning_projection(spec: Any) -> dict[str, Any] | None:
    """Plain data for the readiness details: the contract plus an explicit answer for every representation."""

    contract = conditioning_contract(spec)
    if contract is None:
        return None
    payload = contract.to_dict()
    payload["representations"] = [
        {
            "representation": rep,
            "label": REPRESENTATION_LABELS[rep],
            "accepted": (a := contract.acceptance(rep)).accepted,
            "note": a.note,
        }
        for rep in REPRESENTATIONS
    ]
    return payload


def conditioning_lines(projection: Mapping[str, Any]) -> list[str]:
    """Operator-readable lines for a ``conditioning_projection`` (display only; nothing here is read by a backend)."""

    lines = [
        f"How {projection.get('display_name')} {projection.get('workflow_version')} uses the driving clip"
    ]
    lines.append(f"  Status: {_status_text(projection)}")
    lines.append(f"  Conditioning: {projection.get('mechanism_label')}")
    lines.append(f"  The model consumes: {projection.get('consumes')}")
    order = projection.get("preprocessing_before_resize")
    if order is True:
        lines.append(
            "  Order: edge detection runs on the prepared clip at its own size, before the crop and resize"
        )
    for stage in projection.get("stages") or ():
        lines.append(f"    {stage.get('order')}. {stage.get('node')}: {stage.get('detail')}")
    frames = projection.get("legal_frames") or ()
    if frames:
        lines.append(f"  Lengths: {frames[0]}-{frames[-1]} frames at {projection.get('fps')} FPS")
    lines.extend(f"  Preparation: {step}" for step in projection.get("required_preparation") or ())
    readiness = projection.get("resource_readiness") or {}
    if readiness:
        lines.append(f"  Resources: {_resource_text(projection, readiness)}")
    lines.append("  What each kind of driving clip does here:")
    for item in projection.get("representations") or ():
        mark = "accepted" if item.get("accepted") else "refused"
        lines.append(f"    - {item.get('label')} ({mark}): {item.get('note')}")
    for entry in projection.get("limitations") or ():
        basis = BASIS_LABELS.get(str(entry.get("basis")), str(entry.get("basis")))
        lines.append(f"  - [{basis}] {entry.get('text')}")
    return lines


def _status_text(projection: Mapping[str, Any]) -> str:
    if projection.get("refusal_reason"):
        return f"refused - {projection['refusal_reason']}"
    if projection.get("trial"):
        return "experimental trial, not qualified (per-job consent; selecting it does not make it a default)"
    return str(projection.get("governance") or "unknown")


def _resource_text(projection: Mapping[str, Any], readiness: Mapping[str, Any]) -> str:
    parts = [f"qualification {projection.get('qualification_status')}"]
    if readiness.get("min_available_to_comfy_vram_mib"):
        parts.append(f"{readiness['min_available_to_comfy_vram_mib']} MiB available VRAM floor")
    if readiness.get("min_available_ram_gb"):
        parts.append(f"{readiness['min_available_ram_gb']:g} GB host RAM advisory")
    return ", ".join(parts)


# ------------------------------------------------------------------------------------------------ comparison envelope


@dataclass(frozen=True, slots=True)
class SharedEnvelope:
    """Generation lengths and rate every contract in a comparison can honestly run."""

    legal_frames: tuple[int, ...]
    fps: int | None
    workflows: tuple[str, ...]
    #: Why the envelope is empty, or what must be disclosed (differing rates).
    notes: tuple[str, ...] = ()

    @property
    def maximum(self) -> int | None:
        return max(self.legal_frames) if self.legal_frames else None

    @property
    def minimum(self) -> int | None:
        return min(self.legal_frames) if self.legal_frames else None

    def contains(self, frame_count: int) -> bool:
        return frame_count in self.legal_frames


def shared_envelope(contracts: Sequence[ConditioningContract]) -> SharedEnvelope:
    """The intersection of the contracts' legal lengths (at the research baseline: 17-49 frames at 24 FPS)."""

    if not contracts:
        return SharedEnvelope((), None, (), ("no workflows to compare",))
    names = tuple(f"{c.workflow_id}@{c.workflow_version}" for c in contracts)
    legal = set(contracts[0].legal_frames)
    for contract in contracts[1:]:
        legal &= set(contract.legal_frames)
    rates = {c.fps for c in contracts}
    notes: list[str] = []
    fps: int | None = None
    if len(rates) == 1:
        fps = next(iter(rates))
    else:
        notes.append(
            "the workflows run at different frame rates; their outputs are not frame-for-frame comparable"
        )
    if not legal:
        notes.append("the workflows share no legal generation length")
    return SharedEnvelope(tuple(sorted(legal)), fps, names, tuple(notes))


def envelope_problem(
    envelope: SharedEnvelope, frame_count: int | None, *, label: str = ""
) -> str | None:
    """Why ``frame_count`` is not a shared-envelope length (e.g. 81 frames against a 49-frame Fun Control)."""

    if frame_count is None or envelope.contains(frame_count):
        return None
    where = f" for {label}" if label else ""
    if envelope.legal_frames:
        return (
            f"{frame_count} frames is outside the shared envelope{where} "
            f"({envelope.minimum}-{envelope.maximum} frames); results of different lengths do not cover the same action"
        )
    return f"the compared workflows share no legal length, so {frame_count} frames cannot be compared{where}"


def engine_change_problem(
    prepared_contract: Mapping[str, Any] | None,
    contract: ConditioningContract,
    frame_count: int | None,
) -> str | None:
    """Why a preparation made for another workflow, version or length must not be reused for ``contract`` (or ``None``).

    ``prepared_contract`` is the ``contract`` block a Prepare Motion Source / Align Motion record froze
    (``workflow_id``, ``workflow_version``, ``frame_count``); a missing block is treated as incompatible."""

    if not prepared_contract:
        return "the prepared driving clip records no workflow contract, so it cannot be reused"
    recorded = (
        str(prepared_contract.get("workflow_id") or ""),
        str(prepared_contract.get("workflow_version") or ""),
    )
    if recorded != contract.key:
        return (
            f"the driving clip was prepared for {recorded[0]}@{recorded[1]}, not "
            f"{contract.workflow_id}@{contract.workflow_version}; prepare it again for this engine"
        )
    frames = prepared_contract.get("output_frames", prepared_contract.get("frame_count"))
    if frame_count is not None and frames is not None and int(frames) != int(frame_count):
        return f"the driving clip was prepared for {frames} frames, not {frame_count}; prepare it again"
    return None


__all__ = [
    "BASIS_CATALOG",
    "BASIS_HEURISTIC",
    "BASIS_HISTORICAL",
    "BASIS_LABELS",
    "BASIS_MEASURED",
    "BASIS_RUNTIME_SOURCE",
    "MECHANISM_LABELS",
    "MECH_CANNY_THEN_RESIZE",
    "MECH_RGB_VAE",
    "MECH_UNKNOWN",
    "PINNED_RUNTIME",
    "PROFILE_REPRESENTATION",
    "REPRESENTATIONS",
    "REPRESENTATION_LABELS",
    "REP_POSE_MAP",
    "REP_PRECOMPUTED_EDGES",
    "REP_RENDERED_CHARACTER",
    "REP_RENDERED_SILHOUETTE",
    "REP_RENDERED_SKELETON",
    "REP_RGB_FOOTAGE",
    "RGB_VIDEO_REPRESENTATIONS",
    "ConditioningContract",
    "ConditioningStage",
    "RepresentationAcceptance",
    "SharedEnvelope",
    "conditioning_contract",
    "conditioning_contracts",
    "conditioning_lines",
    "conditioning_projection",
    "engine_change_problem",
    "registered_contracts",
    "takes_motion_prompt",
    "envelope_problem",
    "representation_acceptance",
    "shared_envelope",
    "trace_driver_path",
]
