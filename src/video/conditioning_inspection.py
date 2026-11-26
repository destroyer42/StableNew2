"""What the operator should inspect, and which engines a selected motion asset can honestly go to (PR-VID-MOTION-430).

Pure planning over registered specs, a Motion Library asset record and the frozen preparation record the Video Workflow tab
already holds.  It reads no file, starts no worker, queues nothing and calls no runtime; the view runs the existing bounded
preview worker with the context built here.

Three things the operator can see side by side:

1. the **original** driving reference (the library clip as imported);
2. the **effective** driving input the job would consume: the exact prepared or aligned derivative when a verified preparation
   exists for the *selected engine and length*, else the original;
3. the approximate Canny conditioning preview of that effective input, with its fidelity stated.

A preparation made for another workflow, version or length is never offered as the effective input: it is reported as stale
with the reason (``engine_change_problem``) and the original is inspected instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.video.conditioning_advisories import ConditioningAdvisory
from src.video.motion_alignment_preparation import ALIGNED_SCHEMA
from src.video.workflow_conditioning import (
    BASIS_LABELS,
    PROFILE_REPRESENTATION,
    REP_RGB_FOOTAGE,
    REPRESENTATION_LABELS,
    ConditioningContract,
    RepresentationAcceptance,
    conditioning_contract,
    engine_change_problem,
    shared_envelope,
)

KIND_ORIGINAL = "original"
KIND_PREPARED = "prepared"
KIND_ALIGNED = "aligned"
KIND_LABELS = {
    KIND_ORIGINAL: "Original library clip (no preparation applies)",
    KIND_PREPARED: "Prepared driving clip (exact frames this engine and length consume)",
    KIND_ALIGNED: "Aligned driving clip (prepared and spatially aligned to the source image)",
}
DEFAULT_PORTRAIT = (480, 832)
DEFAULT_LANDSCAPE = (832, 480)


@dataclass(frozen=True, slots=True)
class EffectiveDriver:
    path: str
    sha256: str
    kind: str
    #: Frames the preparation selected (``None`` for the original clip).
    frames: int | None = None
    #: SHA-256 of the clip it was derived from ("" for the original).
    derived_from_sha256: str = ""
    #: Why a preparation that exists is *not* the effective input (empty when it is, or when none exists).
    stale_reason: str = ""

    @property
    def label(self) -> str:
        return KIND_LABELS[self.kind]


@dataclass(frozen=True, slots=True)
class InspectionContext:
    contract: ConditioningContract
    representation: str
    driver: EffectiveDriver
    original_path: str
    original_sha256: str
    target_size: tuple[int, int]
    generation_frames: int | None
    driver_viewpoint: str = ""
    source_viewpoint: str = ""
    motion_category: str = ""
    file_bytes: int | None = None

    @property
    def heading(self) -> str:
        return (
            f"{REPRESENTATION_LABELS.get(self.representation, self.representation)} -> "
            f"{self.contract.display_name} {self.contract.workflow_version} "
            f"({self.target_size[0]}x{self.target_size[1]}); {self.driver.label}"
        )

    def acceptance(self) -> RepresentationAcceptance:
        return self.contract.acceptance(self.representation)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def asset_representation(asset: Any) -> str:
    """The driving representation a library asset depicts: its conversion profile when converted, else RGB footage."""

    derivation = getattr(asset, "derivation", None)
    profile = getattr(derivation, "profile", "") if derivation is not None else ""
    return PROFILE_REPRESENTATION.get(profile, REP_RGB_FOOTAGE)


def effective_driver(
    prepared: Mapping[str, Any] | None,
    contract: ConditioningContract,
    frame_count: int | None,
    *,
    original_path: str,
    original_sha256: str,
) -> EffectiveDriver:
    """The clip a job would consume, never a preparation made for another engine, version or length."""

    if not prepared:
        return EffectiveDriver(original_path, original_sha256, KIND_ORIGINAL)
    problem = engine_change_problem(prepared.get("contract"), contract, frame_count)
    derived = _mapping(prepared.get("derived"))
    original = _mapping(prepared.get("original"))
    path, sha = str(derived.get("path") or ""), str(derived.get("sha256") or "")
    if problem or not path or not sha:
        reason = problem or "the preparation record names no derived clip"
        return EffectiveDriver(original_path, original_sha256, KIND_ORIGINAL, stale_reason=reason)
    if str(original.get("sha256") or "") not in ("", original_sha256):
        return EffectiveDriver(
            original_path,
            original_sha256,
            KIND_ORIGINAL,
            stale_reason="the preparation was made from a different driving clip than the selected one",
        )
    kind = KIND_ALIGNED if prepared.get("schema") == ALIGNED_SCHEMA else KIND_PREPARED
    frames = derived.get("frames")
    return EffectiveDriver(
        path,
        sha,
        kind,
        frames=int(frames) if isinstance(frames, int) and not isinstance(frames, bool) else None,
        derived_from_sha256=original_sha256,
    )


def target_size_for(
    contract: ConditioningContract, width: int | None, height: int | None
) -> tuple[int, int]:
    """The generation geometry the workflow declares for a portrait or landscape clip."""

    portrait = not width or not height or height >= width
    geometry = contract.geometry
    key = "portrait_target" if portrait else "landscape_target"
    target = geometry.get(key) if isinstance(geometry, Mapping) else None
    if isinstance(target, Mapping) and target.get("width") and target.get("height"):
        return int(target["width"]), int(target["height"])
    return DEFAULT_PORTRAIT if portrait else DEFAULT_LANDSCAPE


def build_inspection_context(
    spec: Any,
    asset: Any,
    media_path: str,
    prepared: Mapping[str, Any] | None,
    *,
    frame_count: int | None,
    source_viewpoint: str = "",
    motion_category: str = "",
    file_size: int | None = None,
) -> InspectionContext | None:
    """The context for inspecting ``asset`` against ``spec`` (``None`` when ``spec`` takes no driving video)."""

    contract = conditioning_contract(spec)
    if contract is None:
        return None
    driver = effective_driver(
        prepared,
        contract,
        frame_count,
        original_path=media_path,
        original_sha256=str(getattr(asset, "sha256", "")),
    )
    viewpoint = str(getattr(asset, "viewpoint", "") or "")
    return InspectionContext(
        contract=contract,
        representation=asset_representation(asset),
        driver=driver,
        original_path=media_path,
        original_sha256=str(getattr(asset, "sha256", "")),
        target_size=target_size_for(
            contract, getattr(asset, "width", None), getattr(asset, "height", None)
        ),
        generation_frames=frame_count,
        driver_viewpoint="" if viewpoint in ("", "unknown") else viewpoint,
        source_viewpoint="" if source_viewpoint in ("", "unknown") else source_viewpoint,
        motion_category=motion_category,
        file_bytes=file_size,
    )


# ------------------------------------------------------------------------------------------------ preview display lines


def context_notes(context: InspectionContext) -> tuple[ConditioningAdvisory, ...]:
    """What the selected engine means for this clip, as advisories the preview carries with it."""

    notes: list[ConditioningAdvisory] = []
    accept = context.acceptance()
    notes.append(
        ConditioningAdvisory(
            "engine_representation" if accept.accepted else "engine_refusal",
            ("Accepted: " if accept.accepted else "Refused: ") + accept.note,
            accept.basis,
        )
    )
    if context.driver.stale_reason:
        notes.append(
            ConditioningAdvisory(
                "stale_preparation",
                f"A preparation exists but is not used as the effective input: {context.driver.stale_reason}.",
                "measured",
            )
        )
    if context.contract.refusal_reason:
        notes.append(
            ConditioningAdvisory("workflow_refused", context.contract.refusal_reason, "catalog")
        )
    return tuple(notes)


def preview_notes(preview: Any) -> tuple[str, ...]:
    """Lines for the preview window: what is exact, what is approximate, then every advisory with its basis."""

    lines: list[str] = []
    fidelity = getattr(preview, "fidelity", None) or {}
    if fidelity:
        lines.append("Exact: " + str(fidelity.get("source_frame", "")))
        lines.append("Exact when prepared: " + str(fidelity.get("prepared_driving_frame", "")))
        lines.append(str(fidelity.get("conditioning", "")))
    advisories: Sequence[ConditioningAdvisory] = getattr(preview, "advisories", ()) or ()
    if advisories:
        lines.extend(f"[{BASIS_LABELS.get(a.basis, a.basis)}] {a.text}" for a in advisories)
    else:
        lines.extend(getattr(preview, "warnings", ()) or ())
    return tuple(line for line in lines if line)


# ------------------------------------------------------------------------------------------------ engine rows


@dataclass(frozen=True, slots=True)
class EngineRow:
    """One registered driving-video workflow as the picker's readiness details show it for the selected motion asset."""

    workflow_id: str
    workflow_version: str
    display_name: str
    selected: bool
    mechanism: str
    consumes: str
    representation_note: str
    representation_accepted: bool
    required_preparation: tuple[str, ...]
    legal_lengths: str
    status: str
    refusal: str
    resource: str
    limitations: tuple[str, ...]
    preparation_state: str

    @property
    def usable(self) -> bool:
        return not self.refusal and self.representation_accepted


def _lengths(contract: ConditioningContract) -> str:
    frames = contract.legal_frames
    if not frames:
        return "no declared length policy"
    return f"{frames[0]}-{frames[-1]} frames in steps of 4 at {contract.fps} FPS"


def _resource(contract: ConditioningContract) -> str:
    readiness = contract.resource_readiness
    if not readiness:
        return "no declared resource policy"
    vram, ram = (
        readiness.get("min_available_to_comfy_vram_mib"),
        readiness.get("min_available_ram_gb"),
    )
    status = contract.qualification_status
    parts = [f"status {status}"]
    if vram:
        parts.append(f"{vram} MiB available VRAM floor")
    if ram:
        parts.append(f"{ram:g} GB host RAM advisory")
    return ", ".join(parts)


def _latest(contracts: Iterable[ConditioningContract]) -> list[ConditioningContract]:
    best: dict[str, ConditioningContract] = {}
    for c in contracts:
        version = tuple(int(p) if p.isdigit() else 0 for p in c.workflow_version.split("."))
        current = best.get(c.workflow_id)
        if current is None or version > tuple(
            int(p) if p.isdigit() else 0 for p in current.workflow_version.split(".")
        ):
            best[c.workflow_id] = c
    return sorted(best.values(), key=lambda c: c.display_name)


def engine_rows(
    specs: Iterable[Any],
    *,
    selected: tuple[str, str] | None,
    representation: str,
    prepared: Mapping[str, Any] | None = None,
    frame_count: int | None = None,
) -> tuple[EngineRow, ...]:
    """Compatible registered driving-video engines (latest version of each) for a motion asset's representation.

    Nothing is hidden to make an engine look queueable: a refused version, a representation an engine does not take and a
    preparation made for another engine are each stated.  The selected engine is only marked, never changed."""

    contracts = [c for c in (conditioning_contract(s) for s in specs) if c is not None]
    rows: list[EngineRow] = []
    for contract in _latest(contracts):
        accept = contract.acceptance(representation)
        if prepared:
            problem = engine_change_problem(prepared.get("contract"), contract, frame_count)
            state = f"stale: {problem}" if problem else "prepared for this engine and length"
        else:
            state = "not prepared"
        rows.append(
            EngineRow(
                workflow_id=contract.workflow_id,
                workflow_version=contract.workflow_version,
                display_name=contract.display_name,
                selected=selected == contract.key,
                mechanism=contract.mechanism_label,
                consumes=contract.consumes,
                representation_note=accept.note,
                representation_accepted=accept.accepted,
                required_preparation=contract.required_preparation,
                legal_lengths=_lengths(contract),
                status=contract.status_label,
                refusal=contract.refusal_reason,
                resource=_resource(contract),
                limitations=tuple(text for text, _basis in contract.limitations[:3]),
                preparation_state=state,
            )
        )
    return tuple(rows)


def shared_length_note(rows: Sequence[EngineRow], specs: Iterable[Any]) -> str:
    """The generation lengths every usable engine in ``rows`` shares (for a deliberate multi-engine comparison)."""

    keys = {(r.workflow_id, r.workflow_version) for r in rows if r.usable}
    contracts = [
        c for c in (conditioning_contract(s) for s in specs) if c is not None and c.key in keys
    ]
    if len(contracts) < 2:
        return ""
    envelope = shared_envelope(contracts)
    if not envelope.legal_frames:
        return "The usable engines share no legal generation length."
    return (
        f"Shared length for comparing these engines: {envelope.minimum}-{envelope.maximum} frames at "
        f"{envelope.fps} FPS (longer clips on one engine do not cover the same action)."
    )


__all__ = [
    "KIND_ALIGNED",
    "KIND_LABELS",
    "KIND_ORIGINAL",
    "KIND_PREPARED",
    "EffectiveDriver",
    "EngineRow",
    "InspectionContext",
    "asset_representation",
    "build_inspection_context",
    "context_notes",
    "effective_driver",
    "engine_rows",
    "preview_notes",
    "shared_length_note",
    "target_size_for",
]
