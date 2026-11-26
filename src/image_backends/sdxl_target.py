"""N1b: may this checkpoint run an SDXL-only operation here, and with which warning? (``AGENTS.md`` section 2, N1).

Learning studies, ControlNet, the Review mask editor and outpaint, and guided ADetailer / img2img are written for SDXL
base checkpoints. Before N1b each refused any checkpoint the asset registry had not classified as SDXL from its
safetensors header ("registry-verified SDXL"), so a model that works in practice was unusable only because its header
was never read, could not be classified, or two same-named files disagreed.

The owner's rule (2026-11-25): "Experimental evidence should trump anecdotal or registry evidence. If it works, it
works." One pure answer per (checkpoint policy, operation, backend), in this order:

1. **Observed**: this exact checkpoint completed the same operation on the same backend through the queue here
   (``src/history/observed_execution.py``). It fully outranks unclassified registry evidence: verified, no warning,
   shown as "ran N times here". Against a header that names another family it turns the block into a warning (owner
   decision Q1, 2026-11-26, "Warn, then run"; ``OBSERVED_VS_REGISTRY_FAMILY``). It never outranks an exact qualified
   profile, whose limits the backend enforces itself. The operation is the capability
   level, with ControlNet per modality (owner decision Q2).
2. **Registry SDXL base**: verified, exactly as before.
3. **Unclassified** (no registry record, unknown family, conflicting records, unreadable header, an SDXL refiner or
   inpaint variant): a ``PolicyWarning`` with why and how to fix it. It runs as SDXL, and the accepted warning is
   frozen in the job's provenance on Queue.
4. **Positively another family** (SD1.5, SD2, SD3, FLUX, an exact profile): a real block with a helpful fix.

Backend facts (an operation only Forge performs) are not decided here; each feature keeps its own backend check.

Pure: it reads no file, repository or registry and imports no toolkit. The observed count is supplied by the caller.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from src.image_backends.model_policy import (
    EVIDENCE_ACCEPTED_UNVERIFIED,
    EVIDENCE_CONFLICTING,
    EVIDENCE_NONE,
    EVIDENCE_OBSERVED,
    EVIDENCE_REGISTRY,
    EVIDENCE_UNKNOWN,
    FAMILY_SDXL,
    FAMILY_UNKNOWN,
    SDXL_RUN_EVIDENCE,
    ModelPolicy,
    sdxl_policy_with_evidence,
)
from src.pipeline.policy_warnings import CODE_IMAGE_MODEL_FAMILY_UNVERIFIED, PolicyWarning

# -- operations (capability level, not study kind) ----------------------------------------------------------------
OP_TXT2IMG = "txt2img"
OP_TXT2IMG_EMBEDDING = "txt2img_embedding"
OP_TXT2IMG_LORA = "txt2img_lora"
OP_TXT2IMG_CONTROLNET = "txt2img_controlnet"
OP_IMG2IMG = "img2img"
OP_MASKED_INPAINT = "masked_inpaint"
OP_OUTPAINT = "outpaint"
OP_ADETAILER = "adetailer"
OPERATIONS = (
    OP_TXT2IMG,
    OP_TXT2IMG_EMBEDDING,
    OP_TXT2IMG_LORA,
    OP_TXT2IMG_CONTROLNET,
    OP_IMG2IMG,
    OP_MASKED_INPAINT,
    OP_OUTPAINT,
    OP_ADETAILER,
)
OPERATION_LABELS = {
    OP_TXT2IMG: "txt2img",
    OP_TXT2IMG_EMBEDDING: "txt2img with embeddings",
    OP_TXT2IMG_LORA: "txt2img with LoRAs",
    OP_TXT2IMG_CONTROLNET: "ControlNet txt2img",
    OP_IMG2IMG: "img2img",
    OP_MASKED_INPAINT: "masked inpaint",
    OP_OUTPAINT: "outpaint",
    OP_ADETAILER: "ADetailer",
}

#: What a completed run does against a registry header that names another family. Owner decision Q1 (2026-11-26,
#: "Warn, then run", superseding the first answer): ``"warn"``, the block becomes a warning (why and fix) that Queue
#: records, because a completed job does not prove the family. A code constant, not an operator setting; ``"verify"``
#: and ``"block"`` exist only for tests. An exact qualified profile is never outranked.
OBSERVED_VS_REGISTRY_FAMILY = "warn"

#: ControlNet is judged per modality (owner decision Q2): ``txt2img_controlnet:<modality>``.
CONTROLNET_OPERATION_PREFIX = OP_TXT2IMG_CONTROLNET + ":"


def controlnet_operation(modality: str) -> str:
    """The capability-level operation of ControlNet txt2img with one ``modality`` (``openpose``, ``canny``, ``depth``)."""

    name = str(modality or "").strip().lower()
    if not name:
        raise ValueError("A ControlNet operation needs a modality")
    return CONTROLNET_OPERATION_PREFIX + name


def is_operation(operation: str) -> bool:
    return operation in OPERATIONS or (
        operation.startswith(CONTROLNET_OPERATION_PREFIX)
        and len(operation) > len(CONTROLNET_OPERATION_PREFIX)
    )


def operation_label(operation: str) -> str:
    if operation.startswith(CONTROLNET_OPERATION_PREFIX):
        return f"ControlNet {operation[len(CONTROLNET_OPERATION_PREFIX) :]} txt2img"
    return OPERATION_LABELS.get(operation, operation)


def combine(targets: list[SdxlTarget]) -> SdxlTarget:
    """One verdict for several operations at once (for example two ControlNet units): the first block, else the first
    warning, else the first verified target."""

    if not targets:
        raise ValueError("Nothing to combine")
    for status in (TargetStatus.BLOCKED, TargetStatus.WARNING):
        found = next((item for item in targets if item.status is status), None)
        if found is not None:
            return found
    return targets[0]


#: (checkpoint name, operation, backend id) -> completed runs of that exact checkpoint here.
ObservedRuns = Callable[[str, str, str], int]

SOURCE_GATE = "sdxl_target"
_SCAN_HINT = (
    "To have StableNew read its header now, open Learning > Model Evidence Catalog and run Quick scan, then build "
    "Preview again."
)


class TargetStatus(str, Enum):
    OBSERVED = "observed"
    REGISTRY = "registry"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SdxlTarget:
    """The verdict for one checkpoint, operation and backend."""

    status: TargetStatus
    #: The policy the feature runs with: the SDXL policy (evidence ``registry``, ``observed_execution`` or
    #: ``accepted_unverified``) when allowed, else the resolved policy unchanged.
    policy: ModelPolicy
    operation: str
    model: str
    warning: PolicyWarning | None = None
    #: Operator text for a block (why and the fix); empty when allowed.
    block: str = ""
    observed_runs: int = 0

    @property
    def allowed(self) -> bool:
        return self.status is not TargetStatus.BLOCKED

    @property
    def warnings(self) -> tuple[PolicyWarning, ...]:
        return () if self.warning is None else (self.warning,)

    def evidence_text(self) -> str:
        """One plain line saying why the target is allowed (or the block)."""

        if self.status is TargetStatus.OBSERVED:
            times = "time" if self.observed_runs == 1 else "times"
            return f"{self.model}: ran {self.observed_runs} {times} here ({operation_label(self.operation)})."
        if self.status is TargetStatus.REGISTRY:
            ran = ""
            if self.observed_runs:
                times = "time" if self.observed_runs == 1 else "times"
                ran = f"; ran {self.observed_runs} {times} here ({operation_label(self.operation)})"
            return f"{self.model}: SDXL base checkpoint (read from its header{ran})."
        if self.warning is not None:
            return self.warning.title
        return self.block

    def require(self) -> SdxlTarget:
        """Raise ``ValueError`` with the block text when blocked; else return ``self``."""

        if not self.allowed:
            raise ValueError(self.block)
        return self

    def as_dict(self) -> dict[str, object]:
        """Surface-neutral data (the phone gateway and frozen records use this)."""

        return {
            "status": self.status.value,
            "operation": self.operation,
            "model": self.model,
            "evidence": self.policy.evidence if self.allowed else "",
            "observed_runs": self.observed_runs,
            "warning": None if self.warning is None else self.warning.as_dict(),
            "block": self.block,
            "text": self.evidence_text(),
        }


def _why(policy: ModelPolicy, model: str, feature: str) -> str:
    if policy.evidence == EVIDENCE_CONFLICTING:
        found = (
            f"StableNew found more than one checkpoint file named {model} and their headers disagree about "
            "the model family"
        )
    elif policy.evidence == EVIDENCE_UNKNOWN:
        found = (
            f"StableNew read the header of {model} but could not tell which model family it is (or it is an SDXL "
            "refiner or inpaint variant rather than a standard base checkpoint)"
        )
    else:
        found = f"StableNew has no record of the header of {model} yet"
    return (
        f"{found}, so it cannot confirm it is the SDXL base checkpoint {feature} is written for. Nothing has "
        "shown it to be the wrong kind, and it has not completed this operation here yet."
    )


def _fix(policy: ModelPolicy) -> str:
    steps = [
        "Queue runs it anyway, as an SDXL checkpoint. If it is SDXL, nothing else is needed: once a job with it "
        "completes here, StableNew counts that as proof and stops showing this.",
        "If it is not SDXL (for example SD1.5), the SDXL embeddings, LoRAs or ControlNet models will not match it; "
        "select an SDXL checkpoint instead.",
    ]
    if policy.evidence == EVIDENCE_CONFLICTING:
        steps.append("Remove or rename the duplicate checkpoint file so only one remains.")
    else:
        steps.append(_SCAN_HINT)
    return " ".join(steps)


def _block_text(policy: ModelPolicy, model: str, feature: str) -> str:
    if policy.profile_ref is not None or policy.refusal:
        return (
            f"Only SDXL checkpoints can be used for {feature}, and {model} is {policy.display_name}, which has its "
            "own model profile. Select an SDXL checkpoint."
        )
    return (
        f"Only SDXL checkpoints can be used for {feature}, and the header of {model} says it is "
        f"{policy.display_name}. "
        "Select an SDXL checkpoint. If this is wrong and the file really is SDXL, run Quick scan in Learning > "
        "Model Evidence Catalog to re-read the header."
    )


def _unclassified(policy: ModelPolicy) -> bool:
    return (
        policy.profile_ref is None
        and not policy.refusal
        and (
            policy.family == FAMILY_UNKNOWN
            or policy.evidence in (EVIDENCE_NONE, EVIDENCE_UNKNOWN, EVIDENCE_CONFLICTING)
        )
    )


def assess_sdxl_target(
    policy: ModelPolicy,
    *,
    model: str,
    operation: str,
    backend_id: str,
    feature: str,
    observed: ObservedRuns | None = None,
) -> SdxlTarget:
    """The verdict for running ``operation`` (one of ``OPERATIONS``) with ``model`` on ``backend_id``.

    ``policy`` is the checkpoint's canonical ``resolve_model_policy`` result; ``feature`` is the operator name of the
    feature asking ("Embedding experiments", "ControlNet"); ``observed`` counts completed runs (absent: none known).
    """

    if not is_operation(operation):
        raise ValueError(f"Unknown SDXL operation '{operation}'")
    name = str(model or "").strip()
    shown = name or "the selected checkpoint"
    exact_profile = policy.profile_ref is not None or bool(policy.refusal)
    runs = 0 if exact_profile else _count(observed, name, operation, backend_id)
    if policy.family == FAMILY_SDXL and policy.evidence == EVIDENCE_REGISTRY and not exact_profile:
        return SdxlTarget(TargetStatus.REGISTRY, policy, operation, shown, observed_runs=runs)
    # A frozen study re-checked carries its substituted SDXL policy; it is judged like the original evidence.
    if policy.family == FAMILY_SDXL and policy.evidence in SDXL_RUN_EVIDENCE and not exact_profile:
        policy_for_verdict = _UNCLASSIFIED_SDXL
    else:
        policy_for_verdict = policy
    policy = policy_for_verdict
    wrong_family = not exact_profile and not _unclassified(policy)
    if runs and wrong_family and OBSERVED_VS_REGISTRY_FAMILY == "warn":
        return SdxlTarget(
            TargetStatus.WARNING,
            sdxl_policy_with_evidence(EVIDENCE_ACCEPTED_UNVERIFIED),
            operation,
            shown,
            warning=_family_warning(policy, shown, feature, operation, runs),
            observed_runs=runs,
        )
    if runs and (not wrong_family or OBSERVED_VS_REGISTRY_FAMILY == "verify"):
        return SdxlTarget(
            TargetStatus.OBSERVED,
            sdxl_policy_with_evidence(EVIDENCE_OBSERVED),
            operation,
            shown,
            observed_runs=runs,
        )
    if _unclassified(policy):
        return SdxlTarget(
            TargetStatus.WARNING,
            sdxl_policy_with_evidence(EVIDENCE_ACCEPTED_UNVERIFIED),
            operation,
            shown,
            warning=_warning(policy, shown, feature),
        )
    return SdxlTarget(
        TargetStatus.BLOCKED, policy, operation, shown, block=_block_text(policy, shown, feature)
    )


#: Stand-in for a frozen ``accepted_unverified`` / ``observed_execution`` SDXL policy re-checked (callers pass the
#: canonical policy where they can; this keeps a frozen policy from ever reading as a positive family label).
_UNCLASSIFIED_SDXL = ModelPolicy(
    policy_id="unverified_generic", family=FAMILY_UNKNOWN, display_name="Unclassified model",
    evidence=EVIDENCE_UNKNOWN, controls={}, features={},
)  # fmt: skip


def _warning(policy: ModelPolicy, model: str, feature: str) -> PolicyWarning:
    return PolicyWarning(
        code=CODE_IMAGE_MODEL_FAMILY_UNVERIFIED,
        subject=model,
        title=f"{model} is not confirmed as SDXL.",
        why=_why(policy, model, feature),
        fix=_fix(policy),
        source_gate=SOURCE_GATE,
    )


def _family_warning(
    policy: ModelPolicy, model: str, feature: str, operation: str, runs: int
) -> PolicyWarning:
    times = "time" if runs == 1 else "times"
    return PolicyWarning(
        code=CODE_IMAGE_MODEL_FAMILY_UNVERIFIED,
        subject=model,
        title=f"The header of {model} says {policy.display_name}, but it ran {runs} {times} here.",
        why=(
            f"{feature} is written for SDXL checkpoints, and StableNew read {policy.display_name} from the header of "
            f"{model}. It has also completed {operation_label(operation)} on this backend {runs} {times} here. A "
            "completed job does not prove the family: Forge finishes a job and skips a LoRA or embedding that does "
            "not match the checkpoint."
        ),
        fix=(
            "Queue runs it anyway, as an SDXL checkpoint. Check the results: if the LoRAs, embeddings or ControlNet "
            "had no effect, select an SDXL checkpoint. If the header is wrong, run Quick scan in Learning > Model "
            "Evidence Catalog to re-read it."
        ),
        source_gate=SOURCE_GATE,
    )


def _count(observed: ObservedRuns | None, model: str, operation: str, backend_id: str) -> int:
    if observed is None or not model:
        return 0
    try:
        return max(0, int(observed(model, operation, str(backend_id or ""))))
    except Exception:  # noqa: BLE001 - unreadable history is absent evidence, never a pass or a block
        return 0


__all__ = [
    "CONTROLNET_OPERATION_PREFIX",
    "combine",
    "controlnet_operation",
    "is_operation",
    "operation_label",
    "OBSERVED_VS_REGISTRY_FAMILY",
    "OPERATIONS",
    "OPERATION_LABELS",
    "OP_ADETAILER",
    "OP_IMG2IMG",
    "OP_MASKED_INPAINT",
    "OP_OUTPAINT",
    "OP_TXT2IMG",
    "OP_TXT2IMG_CONTROLNET",
    "OP_TXT2IMG_EMBEDDING",
    "OP_TXT2IMG_LORA",
    "ObservedRuns",
    "SdxlTarget",
    "TargetStatus",
    "assess_sdxl_target",
]
