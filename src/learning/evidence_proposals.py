"""Deterministic qualification drafts. This module cannot enqueue, run or publish."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from src.generation_profiles.contract import SETTING_KEYS, ModelIdentity
from src.generation_profiles.evidence_catalog import EvidenceCatalog
from src.generation_profiles.identity import ResolvedModel
from src.image_backends.model_policy import EVIDENCE_REGISTRY
from src.learning import baseline_authoring as authoring
from src.learning.experiment_store import LearningExperimentStore
from src.learning.model_capabilities import project_learning_capabilities, variable_name
from src.learning.variable_metadata import get_variable_by_internal_name

CONTRACT = "qualification_proposal/1"
RUBRIC = ("overall quality", "prompt adherence", "artifacts", "detail", "variable-specific outcome")
DECISION = "For a six-pair pilot: at least 5/6 candidate wins and mean overall improvement >= 0.5 on the existing rating scale supports follow-up only. Mixed/small differences are inconclusive. This is a screening rule, not statistical proof or a universal optimum."
REQUIRED_EVIDENCE = (
    "verified checkpoint identity",
    "same backend-observed seed cohort",
    "compiled tested values unchanged",
    "backend-reported tested values",
    "saved raw ratings with variability and exclusions",
)


@dataclass(frozen=True)
class EvidenceGap:
    priority: str
    variable: str
    status: str
    reason: str
    # Lexicographic ranking is documented, not a confidence probability.
    consequence: int = 1
    weakness: int = 1
    usefulness: int = 1
    cost: int = 0


def evidence_gaps(
    catalog: EvidenceCatalog, target: ResolvedModel, *, variant: str = ""
) -> tuple[EvidenceGap, ...]:
    if target.policy.qualified and target.policy.exact_identity_authority:
        return (
            EvidenceGap(
                "P4",
                "recipe",
                "metadata_only",
                "Immutable executable profile owns fixed settings and specific qualification restrictions; research cannot vary them.",
            ),
        )
    if (
        not target.identity.sha256
        or not target.verified_family
        or target.identity.family == "unknown"
    ):
        return (
            EvidenceGap(
                "P0",
                "identity",
                "blocked",
                "Resolve byte identity and contradictory/missing compatibility evidence before generation.",
            ),
        )
    if target.policy.family != "sdxl" or target.policy.evidence != EVIDENCE_REGISTRY:
        return (
            EvidenceGap(
                "P4",
                "recipe",
                "metadata_only",
                "Canonical policy/exact profile owns execution; no independently variable qualified recipe.",
            ),
        )
    if variant:
        return (
            EvidenceGap(
                "P0",
                "variant",
                "blocked",
                "Exact accelerator/subtype and executable recipe must be qualified before generation.",
                3,
            ),
        )
    coverage = {row.field: row for row in catalog.coverage(target.identity)}
    rows = [
        EvidenceGap(
            "P1",
            variable,
            "candidate",
            f"{coverage[field].status}: {coverage[field].reason}",
            2,
            2 if coverage[field].status == "conflicting" else 1,
            2,
        )
        for variable, field in (
            ("cfg_scale", "cfg_scale"),
            ("steps", "steps"),
            ("sampler", "sampler_name"),
            ("scheduler", "scheduler"),
        )
        if coverage[field].status != "recommended"
        or not any(c.classification.startswith("exact_") for c in coverage[field].claims)
    ]
    rows.extend(
        (
            EvidenceGap(
                "P2",
                "geometry",
                "blocked",
                "Geometry remains descriptive until a compatible controlled mode and independent publication rule are qualified.",
            ),
            EvidenceGap(
                "P1",
                "vae",
                "blocked",
                "An external VAE comparison requires an exact, verified compatible pairing; preserve the model-owned VAE.",
            ),
            EvidenceGap(
                "P3",
                "adapters",
                "blocked",
                "Choose the existing LoRA/Embedding controlled mode after exact compatibility verification.",
            ),
            EvidenceGap(
                "P4",
                "metadata",
                "metadata_only",
                "Text-encoder context, CLIP skip and dependency unknowns require metadata research; do not infer execution values.",
            ),
        )
    )
    return tuple(
        sorted(
            rows,
            key=lambda g: (
                g.priority,
                -g.consequence,
                -g.weakness,
                -g.usefulness,
                g.status != "candidate",
                g.cost,
                g.variable,
            ),
        )
    )


@dataclass(frozen=True)
class ExperimentProposal:
    document: Mapping[str, Any]

    @property
    def proposal_id(self) -> str:
        return str(self.document["proposal_id"])

    @property
    def runnable(self) -> bool:
        return bool(self.document["status"] == "draft")


def propose(
    catalog: EvidenceCatalog,
    target: ResolvedModel,
    baseline: Mapping[str, Any],
    *,
    variable: str,
    values: tuple[Any, ...],
    prompt: str,
    negative_prompt: str = "",
    samples: int | None = None,
    seed: int = 42,
    resources: Mapping[str, Any] | None = None,
    variant: str = "",
) -> ExperimentProposal:
    """One factor, one prompt, shared requested seeds; requested seeds still need readback."""
    if (len(values), samples or (6 if len(values) == 2 else 5)) not in (
        (2, 6),
        (3, 5),
        (4, 5),
        (2, 10),
    ):
        raise ValueError("Pilot design must be 2x6, 3x5, 4x5 or explicit 2x10")
    if len({json.dumps(v, sort_keys=True) for v in values}) != len(values):
        raise ValueError("Candidates must be distinct")
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or len(prompt) > 16000
        or len(negative_prompt) > 16000
    ):
        raise ValueError("Freeze one bounded, nonempty prompt")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("Invalid shared seed")
    count = samples or (6 if len(values) == 2 else 5)
    config = copy.deepcopy(dict(baseline))
    section = config.get("txt2img", {})
    meta = get_variable_by_internal_name(variable)
    gap = next(
        (g for g in evidence_gaps(catalog, target, variant=variant) if g.variable == variable), None
    )
    reasons = []
    if gap is None or gap.status != "candidate":
        reasons.append(
            gap.reason if gap else "No eligible controlled evidence gap for this variable."
        )
    if meta is None:
        reasons.append("Variable has no existing controlled Learning mode.")
    else:
        try:
            project_learning_capabilities(
                target.policy, str(section.get("model", "")), "txt2img"
            ).require(meta.display_name)
        except ValueError as exc:
            reasons.append(str(exc))
        field = meta.config_path.split(".")[-1]
        if meta.value_type == "numeric":
            from src.learning.design_estimate import range_values

            planned = range_values(
                float(values[0]), float(values[-1]), float(values[1]) - float(values[0])
            )
            if planned != list(values):
                reasons.append(
                    "Alternatives cannot be represented by the existing ascending regular Learning range; no values will be substituted."
                )
        if field in SETTING_KEYS:
            from src.generation_profiles.contract import validate_settings

            for value in values:
                validate_settings({field: value})
        if section.get(field) != values[0]:
            reasons.append("First alternative must exactly match the selected baseline/control.")
        if meta.resource_key and (
            not resources or any(v not in resources.get(meta.resource_key, ()) for v in values)
        ):
            reasons.append(
                "Intended resource alternatives unavailable; no substitution is allowed."
            )
    if resources is None:
        reasons.append(
            "Current resource inventory is required before a runnable proposal can be saved."
        )
    reasons.extend(authoring.baseline_problems(config, "txt2img", resources=resources))
    if (
        any(section.get(k) for k in ("lora_strengths", "loras"))
        or "<lora:" in prompt.lower()
        or "<lyco:" in prompt.lower()
    ):
        reasons.append(
            "Adapter recipe needs exact compatibility validation in its existing controlled mode."
        )
    if section.get("model") != target.identity.display_name:
        reasons.append("Selected baseline checkpoint differs from the verified census identity.")
    config.setdefault("txt2img", {})["seed"] = seed
    display = meta.display_name if meta else variable
    identity = target.identity.to_dict()
    name = f"{target.identity.family.upper()} [{target.identity.display_name.rsplit('/', 1)[-1]}@{(target.identity.sha256 or 'pending')[:8]}] — {' vs '.join(map(str, values))} {display} — {count * len(values)}-image paired quality test"
    objective = f"Does changing {display} from {values[0]} to the candidate improve quality under this exact frozen context?"
    doc = {
        "contract": CONTRACT,
        "name": name,
        "objective": objective,
        "hypothesis": objective,
        "identity": identity,
        "catalog_revision": catalog.revision,
        "coverage": [
            {"field": r.field, "status": r.status, "claims": [asdict(c) for c in r.claims]}
            for r in catalog.coverage(target.identity, variant=variant)
        ],
        "priority": gap.priority if gap else "P0",
        "priority_reason": gap.reason if gap else "; ".join(reasons),
        "variable": variable,
        "values": list(values),
        "baseline": config,
        "held_constant": "Prompt, negative prompt, checkpoint, VAE, LoRAs, requested seed cohort and all non-tested settings.",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed_policy": {
            "policy": "requested_seed_with_backend_observed_vector",
            "requested_base_seed": seed,
            "requested_sample_count": count,
            "subseed_strength": 0.0,
            "requested_subseed": None,
        },
        "images_per_value": count,
        "expected_images": len(values) * count,
        "estimated_work": {
            "images": len(values) * count,
            "denoising_steps": sum(values) * count
            if variable == "steps"
            else section.get("steps", 0) * count * len(values),
            "seconds": None,
        },
        "status": "blocked" if reasons else "draft",
        "blocked_reasons": list(dict.fromkeys(reasons)),
        "requirements": "Explicit operator selection, current resources and whole-batch compile/admission; no automatic generation.",
        "rubric": list(RUBRIC),
        "decision_criteria": DECISION,
        "required_evidence": list(REQUIRED_EVIDENCE),
        "publication": "Existing controlled per-setting eligibility and explicit separate publication only.",
    }
    digest = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    doc["proposal_id"] = "evidence760-" + digest[:32]
    return ExperimentProposal(doc)


def save_proposal(proposal: ExperimentProposal, store: LearningExperimentStore) -> str:
    """Save once; edited drafts and completed results are never overwritten."""
    if not proposal.runnable:
        raise ValueError("Blocked proposal: " + "; ".join(proposal.document["blocked_reasons"]))
    if store.load_session(proposal.proposal_id) is not None:
        return proposal.proposal_id
    from src.gui.learning_state import LearningExperiment, LearningState

    d = copy.deepcopy(dict(proposal.document))
    meta = get_variable_by_internal_name(d["variable"])
    if meta is None:
        raise ValueError("Proposal variable is unavailable")
    values = d["values"]
    metadata = {
        "study_type": "controlled_variable",
        "prompt_source": "custom",
        "selected_prompt_negative_text": d["negative_prompt"],
        "selected_items": values,
        "start_value": values[0] if isinstance(values[0], (float, int)) else 1,
        "end_value": values[-1] if isinstance(values[-1], (float, int)) else 2,
        "step_value": (values[1] - values[0]) if isinstance(values[0], (float, int)) else 1,
        "frozen_seed_policy": d["seed_policy"],
        "evidence_proposal": d,
    }
    state = LearningState()
    authored = authoring.new_authoring(authoring.ORIGIN_LEARNING, source="model_evidence_catalog")
    state.baseline_draft = {"config": d["baseline"], "authoring": authored}
    state.current_experiment = LearningExperiment(
        name=d["name"],
        experiment_id=proposal.proposal_id,
        description=d["objective"] + " " + DECISION,
        baseline_config=d["baseline"],
        baseline_authoring=authored,
        prompt_text=d["prompt"],
        variable_under_test=meta.display_name,
        values=values,
        images_per_value=d["images_per_value"],
        metadata=metadata,
    )
    payload = state.to_dict()
    payload.update(workflow_state="designing", learning_enabled=True, resume_schema_version=1)
    try:
        store.save_session(
            display_name=d["name"],
            payload=payload,
            experiment_id=proposal.proposal_id,
            create_only=True,
        )
    except FileExistsError:
        pass  # Another window won; its draft/results remain untouched.
    return proposal.proposal_id


def proposal_form_fields(experiment: Any) -> dict[str, Any]:
    metadata = getattr(experiment, "metadata", {}) or {}
    if not metadata.get("evidence_proposal"):
        return {}
    return {
        key: copy.deepcopy(metadata.get(key)) for key in ("evidence_proposal", "frozen_seed_policy")
    }


def _selected_context(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(
        {
            k: snapshot.get(k)
            for k in (
                "stage",
                "variable_under_test",
                "variant_values",
                "baseline_config",
                "prompt_text",
                "negative_prompt_text",
                "seed_policy",
                "images_per_value",
                "model_identity",
            )
        }
    )


def freeze_proposal_context(
    proposal: Mapping[str, Any], snapshot: Mapping[str, Any], hypothesis: str
) -> dict[str, Any]:
    frozen = copy.deepcopy(dict(proposal))
    frozen["selected_context"] = _selected_context(snapshot)
    frozen["selected_hypothesis"] = hypothesis
    frozen["selected_context_revision"] = hashlib.sha256(
        json.dumps(frozen["selected_context"], sort_keys=True).encode()
    ).hexdigest()
    return frozen


def validate_proposal_snapshot(
    snapshot: Mapping[str, Any], *, current: ModelIdentity | None = None
) -> None:
    proposal = snapshot.get("evidence_proposal")
    if not proposal:
        return
    if proposal.get("contract") != CONTRACT or proposal.get("status") != "draft":
        raise ValueError("Invalid or blocked qualification proposal")
    if variable_name(snapshot.get("variable_under_test", "")) != proposal["variable"]:
        raise ValueError("Proposal tested variable changed; clone as a new ordinary experiment")
    selected = _selected_context(snapshot)
    revision = hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()
    if (
        proposal.get("selected_context") != selected
        or proposal.get("selected_context_revision") != revision
    ):
        raise ValueError(
            "Proposal selected context or seed policy differs from its frozen revision"
        )
    saved = ModelIdentity.from_dict(proposal["identity"])
    frozen = ModelIdentity.from_dict(snapshot["model_identity"])
    if not saved.sha256 or frozen.sha256 != saved.sha256 or frozen.family != saved.family:
        raise ValueError("Qualification checkpoint identity changed or is unverified")
    if current is not None and (current.sha256 != saved.sha256 or current.family != saved.family):
        raise ValueError("Qualification checkpoint bytes changed since Preview")
    if snapshot.get("variant_values") != proposal["values"]:
        raise ValueError(
            "Proposal alternatives changed; generate a new proposal or clone as an ordinary experiment"
        )
    if snapshot.get("images_per_value") != proposal["images_per_value"]:
        raise ValueError("Proposal image count changed")
