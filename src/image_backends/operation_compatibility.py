"""PR-IMG-MODELS-158: one pure, read-only "can this requested operation run on that resolved target?" projection.

Review/reprocess, the PromptPack editor and Model Comparison each need the same answer *before* anything is queued: does
the exact qualified profile of the resolved model admit the requested backend, stage chain, source-image count and
geometry? The facts come only from the canonical ``ModelPolicy`` (which projects the immutable profile); this module owns
no model, family or profile table and no default value.

It is a projection, never an authority: the compiler and the backend (``validate_njr_intent`` / ``validate_profile_intent``)
still validate every immutable job independently and remain final. It never rewrites a request, substitutes a model,
switches a backend, omits a requested stage or reads any file, network, GUI, asset registry or GPU state. A target without
an exact qualified profile (ordinary SDXL, unverified or unknown families) is never narrowed here, so ordinary behavior is
preserved exactly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.image_backends.forge_klein_profile import (
    EDIT_STAGE_CHAIN,
    KLEIN_EDIT_METADATA_KEY,
    MODE_SINGLE_REFERENCE_EDIT,
    MODE_TXT2IMG,
    T2I_STAGE_CHAIN,
)
from src.image_backends.image_backend_types import resolve_image_backend_id
from src.image_backends.model_policy import (
    CONTROL_GEOMETRY,
    ModelPolicy,
    policy_for_model_profile_reference,
    resolve_model_policy,
)

BACKEND_MISMATCH = "backend_mismatch"
STAGE_UNSUPPORTED = "stage_unsupported"
STAGE_CHAIN_UNSUPPORTED = "stage_chain_unsupported"
MODE_NOT_REQUESTED = "mode_not_requested"
SOURCE_IMAGE_COUNT = "source_image_count"
GEOMETRY_UNSUPPORTED = "geometry_unsupported"


@dataclass(frozen=True, slots=True)
class OperationRequest:
    """What the operator asked for (every field is explicit input; nothing is inferred from a GUI or an image)."""

    #: Requested image stages, in order.
    stages: tuple[str, ...]
    #: Resolved image backend id, or ``None`` when it is not known to the caller (then it is not assessed).
    backend_id: str | None = None
    #: Requested output geometry, or ``None`` when it is not known (then it is not assessed).
    width: int | None = None
    height: int | None = None
    input_image_count: int = 0
    #: The explicit single-reference edit request (Review's checkbox); never derived from an image or a file name.
    single_reference_edit: bool = False


@dataclass(frozen=True, slots=True)
class OperationProblem:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class OperationAssessment:
    target: str
    #: ``True`` when an exact qualified profile governs the target (otherwise nothing is narrowed here).
    exact_profile: bool
    problems: tuple[OperationProblem, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.problems

    def codes(self) -> tuple[str, ...]:
        return tuple(problem.code for problem in self.problems)

    def explain(self) -> str:
        """One operator-facing sentence listing every conflict; empty when ready."""

        if not self.problems:
            return ""
        return f"{self.target} cannot run this request: " + "; ".join(p.message for p in self.problems)


class OperationNotSupportedError(ValueError):
    """The exact profile of the resolved model does not admit the requested operation; nothing was queued."""

    def __init__(self, assessment: OperationAssessment) -> None:
        super().__init__(assessment.explain() + ". Nothing was queued and no setting was changed.")
        self.assessment = assessment


def _modes_text(policy: ModelPolicy) -> str:
    labels = {MODE_TXT2IMG: "txt2img", MODE_SINGLE_REFERENCE_EDIT: "explicit single-reference edit (img2img)"}
    return ", ".join(labels.get(mode, mode) for mode in policy.modes) or "no qualified mode"


def assess_operation(policy: ModelPolicy, request: OperationRequest) -> OperationAssessment:
    """Assess one requested operation against one resolved policy. Pure; mutates nothing."""

    if not policy.qualified:
        return OperationAssessment(policy.display_name, False)

    problems: list[OperationProblem] = []
    required = policy.required_backend
    if required and request.backend_id is not None and request.backend_id != required:
        problems.append(OperationProblem(
            BACKEND_MISMATCH,
            f"it runs only on the '{required}' backend but the resolved backend is '{request.backend_id}' "
            "(StableNew never switches backends for you)",
        ))

    stages = tuple(str(stage) for stage in request.stages)
    expected_inputs: int | None = None
    if stages == T2I_STAGE_CHAIN and MODE_TXT2IMG in policy.modes:
        expected_inputs = 0
    elif stages == EDIT_STAGE_CHAIN and MODE_SINGLE_REFERENCE_EDIT in policy.modes:
        if request.single_reference_edit:
            expected_inputs = 1
        else:
            problems.append(OperationProblem(
                MODE_NOT_REQUESTED,
                "img2img is available only as the explicitly requested single-reference edit; "
                "it is never used as a free-form reprocess stage",
            ))
    else:
        unsupported = [stage for stage in stages if stage not in policy.stages]
        if unsupported:
            problems.append(OperationProblem(
                STAGE_UNSUPPORTED,
                f"stage(s) {', '.join(unsupported)} are outside its qualified envelope "
                f"(supported: {_modes_text(policy)}); no stage is omitted or rewritten for you",
            ))
        else:
            problems.append(OperationProblem(
                STAGE_CHAIN_UNSUPPORTED,
                f"stage chain {list(stages)} is not a qualified mode (supported: {_modes_text(policy)})",
            ))

    if expected_inputs is not None and request.input_image_count != expected_inputs:
        problems.append(OperationProblem(
            SOURCE_IMAGE_COUNT,
            f"{'the single-reference edit needs exactly one source image' if expected_inputs else 'txt2img takes no source image'}"
            f" (this request has {request.input_image_count}; multi-reference is not supported)",
        ))

    allowed = policy.control(CONTROL_GEOMETRY).allowed
    if allowed and request.width is not None and request.height is not None:
        if (int(request.width), int(request.height)) not in {tuple(int(v) for v in pair) for pair in allowed}:
            choices = ", ".join(f"{w}x{h}" for w, h in allowed)
            problems.append(OperationProblem(
                GEOMETRY_UNSUPPORTED,
                f"geometry {request.width}x{request.height} is not qualified (supported: {choices})",
            ))
    return OperationAssessment(policy.display_name, True, tuple(problems))


def explicit_single_reference_edit(metadata: Mapping[str, Any] | None) -> bool:
    """Whether Review froze an explicit single-reference edit for *every* source item of this job's metadata."""

    reprocess = (metadata or {}).get("reprocess")
    items = reprocess.get("source_items") if isinstance(reprocess, Mapping) else None
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes, Mapping)):
        return False
    found = [
        item.get("metadata", {}).get(KLEIN_EDIT_METADATA_KEY)
        for item in items
        if isinstance(item, Mapping) and isinstance(item.get("metadata"), Mapping)
    ]
    return bool(found) and all(
        isinstance(entry, Mapping) and entry.get("mode") == MODE_SINGLE_REFERENCE_EDIT for entry in found
    )


def policy_for_njr(njr: Any) -> ModelPolicy:
    """The policy of the exact profile the NJR froze, else the one resolved from its recorded checkpoint name."""

    options = getattr(njr, "backend_options", None) or {}
    policy = policy_for_model_profile_reference(options)
    return policy if policy is not None else resolve_model_policy(getattr(njr, "base_model", None))


def request_from_njr(njr: Any, metadata: Mapping[str, Any] | None = None) -> OperationRequest:
    """The operation an already-built image NJR asks for (geometry is left unassessed: a reprocess has no source geometry)."""

    metadata = metadata if metadata is not None else getattr(getattr(njr, "provenance", None), "metadata", None)
    return OperationRequest(
        stages=tuple(str(stage) for stage in njr.stage_chain_labels),
        backend_id=resolve_image_backend_id(getattr(njr, "backend_options", None) or {}),
        input_image_count=len(getattr(njr, "input_image_paths", ()) or ()),
        single_reference_edit=explicit_single_reference_edit(metadata),
    )


def assess_njr(njr: Any, metadata: Mapping[str, Any] | None = None) -> OperationAssessment:
    return assess_operation(policy_for_njr(njr), request_from_njr(njr, metadata))


def require_njr_operation(njr: Any, metadata: Mapping[str, Any] | None = None) -> None:
    """Raise ``OperationNotSupportedError`` before queue admission when the exact profile cannot run this NJR."""

    assessment = assess_njr(njr, metadata)
    if not assessment.ready:
        raise OperationNotSupportedError(assessment)


__all__ = [
    "BACKEND_MISMATCH",
    "GEOMETRY_UNSUPPORTED",
    "MODE_NOT_REQUESTED",
    "SOURCE_IMAGE_COUNT",
    "STAGE_CHAIN_UNSUPPORTED",
    "STAGE_UNSUPPORTED",
    "OperationAssessment",
    "OperationNotSupportedError",
    "OperationProblem",
    "OperationRequest",
    "assess_njr",
    "assess_operation",
    "explicit_single_reference_edit",
    "policy_for_njr",
    "request_from_njr",
    "require_njr_operation",
]
