"""Pure catalog-derived qualification plans; no discovery, prompting, persistence or admission."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.generation_profiles.contract import SETTING_KEYS, validate_settings
from src.generation_profiles.evidence_catalog import CLASSES, EvidenceCatalog
from src.generation_profiles.identity import ResolvedModel
from src.learning import baseline_authoring as authoring
from src.learning.evidence_proposals import CONTRACT_V2, ExperimentProposal, evidence_gaps, propose
from src.learning.model_capabilities import project_learning_capabilities

GENERATOR = "evidence-autopilot/1"
PLAN_CONTRACT = "qualification_proposal_plan/1"
VARIABLES = (
    ("cfg_scale", "cfg_scale"),
    ("steps", "steps"),
    ("sampler", "sampler_name"),
    ("scheduler", "scheduler"),
)
RESOURCE_KEYS = ("models", "samplers", "schedulers", "vaes")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _resource_name(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 400 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid resource identifier")
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        raise ValueError("Absolute resource paths cannot enter a proposal plan")
    return value


def resource_snapshot(resources: Mapping[str, Any]) -> dict[str, list[str]]:
    return {
        key: sorted({_resource_name(v) for v in resources.get(key, ())}) for key in RESOURCE_KEYS
    }


def model_baseline(baseline: Mapping[str, Any], target: ResolvedModel) -> dict[str, Any]:
    """An isolated generation-only baseline; prompts, paths and other drafts never enter planning."""
    section = {}
    for spec in authoring.fields_for_stage("txt2img"):
        value = authoring.read_field(baseline, spec)
        if value is not None:
            section[spec.key] = copy.deepcopy(value)
    old_model = section.get("model")
    section["model"] = _resource_name(target.identity.display_name)
    if old_model != section["model"]:
        section["vae"] = ""  # A different checkpoint cannot inherit an unverified external pairing.
    for key in ("model", "vae", "sampler_name", "scheduler"):
        if key in section:
            section[key] = _resource_name(section[key])
    for key in SETTING_KEYS:
        if key in section:
            validate_settings({key: section[key]})
    seed = section.get("seed", 42)
    section["seed"] = (
        seed if isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed < 2**32 else 42
    )
    image = (baseline.get("backend_options") or {}).get("image") or {}
    backend = _resource_name(image.get("backend_id", ""))
    result = {
        "txt2img": section,
        "backend_options": {"image": {"backend_id": backend}},
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": False,
            "adetailer_enabled": False,
            "upscale_enabled": False,
        },
    }
    authoring.align_aliases(result, "txt2img")
    return result


def execution_baseline(context: ProposalPlanningContext) -> dict[str, Any]:
    """Private fixed intent, materialized only by explicit Save/Preview adapters."""
    from src.learning.ordinary_prompt_freeze import freeze_preview_global_policy

    result = copy.deepcopy(dict(context.baseline))
    safe = model_baseline(context.baseline, context.target)
    result.setdefault("txt2img", {}).update(safe["txt2img"])
    result.setdefault("backend_options", {}).setdefault("image", {}).update(
        safe["backend_options"]["image"]
    )
    return freeze_preview_global_policy(authoring.finalize_for_stage(result, "txt2img"))


def _fixed_digest(context: ProposalPlanningContext) -> str:
    baseline = execution_baseline(context)
    # Prompt selection is deliberately deferred. Global policy and optimizer settings
    # remain fixed execution intent and are included, privately, in this digest.
    for section in (baseline, baseline["txt2img"]):
        for key in ("prompt", "negative_prompt"):
            section.pop(key, None)
    for key in ("ratings", "display_name", "timestamp", "updated_at", "created_at"):
        baseline.pop(key, None)
    return _baseline_digest(baseline, context.target.identity.to_dict())


@dataclass(frozen=True)
class ProposalPlanningContext:
    target: ResolvedModel
    catalog: EvidenceCatalog
    baseline: Mapping[str, Any]
    resources: Mapping[str, Any]
    variant: str = ""
    baseline_origin: str = "learning"
    samples: int | None = None


@dataclass(frozen=True)
class ProposalPlan:
    canonical_json: str

    @property
    def document(self) -> dict[str, Any]:
        return dict(json.loads(self.canonical_json))

    @property
    def proposals(self) -> tuple[ExperimentProposal, ...]:
        return tuple(ExperimentProposal(p) for p in self.document["proposals"])

    @property
    def plan_id(self) -> str:
        return str(self.document["plan_id"])


def _identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {key: identity.get(key) for key in ("kind", "family", "sha256", "exact_profile")}


def _baseline_digest(baseline: Mapping[str, Any], identity: Mapping[str, Any]) -> str:
    safe = copy.deepcopy(dict(baseline))
    safe["txt2img"]["model"] = _identity(identity)
    safe["txt2img"].pop("model_name", None)
    return digest(safe)


def _refs(
    catalog: EvidenceCatalog, claims: tuple[Any, ...], context: ProposalPlanningContext
) -> list[dict[str, Any]]:
    refs = []
    identity = context.target.identity
    matches = [
        r
        for r in catalog.records
        if r.asset_kind == "checkpoint"
        and r.family == identity.family
        and (
            (r.scope == "exact" and identity.sha256 and r.sha256 == identity.sha256)
            or (r.scope == "family" and identity.family != "unknown")
            or (r.scope == "variant" and context.variant and r.variant == context.variant)
        )
    ]
    rank = {"family": 0, "variant": 1, "exact": 2}
    for record in matches:
        for claim in record.claims:
            best = max(
                (rank[r.scope] for r in matches if any(c.field == claim.field for c in r.claims)),
                default=-1,
            )
            if rank[record.scope] == best and claim in claims:
                if isinstance(claim.value, str):
                    _resource_name(claim.value)
                refs.append(
                    {
                        "record_id": record.record_id,
                        "scope": record.scope,
                        "field": claim.field,
                        "value": claim.value,
                        "classification": claim.classification,
                        "confidence": claim.confidence,
                        "source": claim.source,
                        "source_revision": claim.source_revision,
                        "claim_digest": digest(vars(claim)),
                        "coupled_recipe": {"sampler_name", "scheduler"}.issubset(
                            {c.field for c in record.claims}
                        ),
                    }
                )
    return sorted(
        refs, key=lambda r: (CLASSES.index(r["classification"]), r["record_id"], digest(r))
    )


def _seal(doc: dict[str, Any], context: dict[str, Any]) -> ExperimentProposal:
    doc["planning_context"] = copy.deepcopy(context)
    doc["generator_version"] = GENERATOR
    core = {
        key: doc.get(key)
        for key in (
            "variable",
            "values",
            "images_per_value",
            "seed_policy",
            "status",
            "evidence_refs",
        )
    }
    doc["proposal_id"] = "evidence800-" + digest({"context": context, "design": core})[:32]
    doc["default_selected"] = doc["priority"] == "P1" and doc["status"] == "draft"
    return ExperimentProposal(doc)


class EvidenceProposalPlanner:
    def plan(self, context: ProposalPlanningContext) -> ProposalPlan:
        target, catalog = context.target, context.catalog
        baseline = model_baseline(context.baseline, target)
        resources = resource_snapshot(context.resources)
        identity = target.identity.to_dict()
        identity["display_name"] = _resource_name(identity["display_name"])
        core = {
            "model_identity": _identity(identity),
            "catalog_revision": catalog.revision,
            "baseline_digest": _baseline_digest(baseline, identity),
            "fixed_execution_digest": _fixed_digest(context),
            "variant": context.variant,
            "resource_digest": digest(resources),
            "generator_version": GENERATOR,
            "samples": context.samples,
            "policy_context": json.loads(
                project_learning_capabilities(
                    target.policy, target.identity.display_name, "txt2img"
                ).context_json
            ),
        }
        coverage = {c.field: c for c in catalog.coverage(target.identity, variant=context.variant)}
        gaps = evidence_gaps(catalog, target, variant=context.variant)
        proposals = []
        for gap in sorted(
            gaps,
            key=lambda g: (
                g.priority,
                -g.consequence,
                -g.weakness,
                -g.usefulness,
                g.cost,
                [v[0] for v in VARIABLES].index(g.variable)
                if g.variable in dict(VARIABLES)
                else 99,
                g.variable,
            ),
        ):
            field = dict(VARIABLES).get(gap.variable)
            claims = coverage[field].claims if field else ()
            refs = _refs(catalog, claims, context)
            reasons = []
            doc: dict[str, Any] = {
                "contract": CONTRACT_V2,
                "identity": identity,
                "catalog_revision": catalog.revision,
                "priority": gap.priority,
                "priority_reason": gap.reason,
                "variable": gap.variable,
                "values": [],
                "images_per_value": 0,
                "expected_images": 0,
                "status": "metadata_only" if gap.status == "metadata_only" else "blocked",
                "blocked_reasons": [gap.reason],
                "evidence_refs": refs,
                "name": f"{target.identity.family.upper()} [{identity['display_name']}@{(identity.get('sha256') or 'pending')[:8]}] — {gap.variable}",
                "objective": gap.reason,
                "hypothesis": gap.reason,
            }
            if field and gap.status == "candidate":
                control = baseline["txt2img"].get(field)
                candidates = []
                for ref in refs:
                    value = ref["value"]
                    if value != control and value not in candidates:
                        candidates.append(value)
                if not candidates:
                    reasons.append(
                        "No source-backed alternate exists. Refresh/import reviewed evidence; no fallback recipe is invented."
                    )
                else:
                    values = (control, *candidates[: 1 if context.samples == 10 else 3])
                    try:
                        _validate_values(gap.variable, values)
                        proposal = propose(
                            catalog,
                            target,
                            baseline,
                            variable=gap.variable,
                            values=values,
                            prompt="",
                            resources=resources,
                            seed=baseline["txt2img"]["seed"],
                            samples=context.samples,
                            variant=context.variant,
                            contract=CONTRACT_V2,
                        )
                        doc.update(copy.deepcopy(dict(proposal.document)))
                        doc["coverage"] = [
                            {"field": c.field, "status": c.status} for c in coverage.values()
                        ]
                        doc["evidence_refs"] = refs
                        doc["baseline_origin"] = (
                            context.baseline_origin
                            if context.baseline_origin in ("learning", "pipeline", "profile")
                            else "learning"
                        )
                        doc["prompt_context"] = (
                            "Choose once at Preview; planning does not resolve prompts."
                        )
                        if len(candidates) > 3:
                            doc["candidate_limit"] = (
                                "First three ranked alternatives; further claims remain in Evidence Details."
                            )
                    except (ValueError, TypeError) as exc:
                        reasons.append(str(exc))
                backend = baseline["backend_options"]["image"]["backend_id"]
                from src.image_backends.model_readiness_probe import checkpoint_key

                for setting, resource in (
                    ("model", "models"),
                    ("sampler_name", "samplers"),
                    ("scheduler", "schedulers"),
                    ("vae", "vaes"),
                ):
                    value = baseline["txt2img"].get(setting)
                    if setting == "vae" and not value:
                        continue
                    available = resources[resource]
                    present = (
                        checkpoint_key(str(value or "")) in {checkpoint_key(v) for v in available}
                        if resource in ("models", "vaes")
                        else value in available
                    )
                    if not present:
                        reasons.append(
                            f"Baseline {setting} is unavailable in the current {resource} inventory; no substitution is allowed."
                        )
                if not backend or backend not in target.policy.allowed_backends:
                    reasons.append("Select a policy-compatible backend before qualification.")
                if field in ("sampler_name", "scheduler") and any(
                    r["coupled_recipe"] for r in refs
                ):
                    reasons.append(
                        "Source describes a sampler/scheduler recipe together; an independent one-factor mapping is unverified."
                    )
                if baseline["txt2img"].get("subseed_strength", 0):
                    reasons.append(
                        "Qualification needs a fixed common seed cohort without subseed variation."
                    )
                raw = context.baseline.get("txt2img") or {}
                if raw.get("loras") or raw.get("lora_strengths"):
                    reasons.append(
                        "Adapters require their existing exact-compatibility controlled mode."
                    )
                if reasons:
                    doc["status"] = "blocked"
                    doc["blocked_reasons"] = list(
                        dict.fromkeys([*doc.get("blocked_reasons", []), *reasons])
                    )
            proposals.append(_seal(doc, core))
        document = {
            "contract": PLAN_CONTRACT,
            **core,
            "proposals": [dict(p.document) for p in proposals],
        }
        document["plan_id"] = (
            "proposal-plan-"
            + digest({"context": core, "proposals": [p.proposal_id for p in proposals]})[:32]
        )
        return ProposalPlan(
            json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )


def validate_current(plan: ProposalPlan, context: ProposalPlanningContext) -> None:
    current = EvidenceProposalPlanner().plan(context)
    presentation = {
        "name",
        "objective",
        "hypothesis",
        "priority_reason",
        "blocked_reasons",
        "requirements",
        "held_constant",
        "rubric",
        "decision_criteria",
        "publication",
        "prompt_context",
        "candidate_limit",
        "baseline_origin",
    }

    def designs(value: ProposalPlan) -> list[dict[str, Any]]:
        return [
            {key: item for key, item in p.document.items() if key not in presentation}
            for p in value.proposals
        ]

    if current.plan_id != plan.plan_id or designs(current) != designs(plan):
        raise ValueError(
            "Findings are stale: model, catalog, baseline or resources changed. Replan before continuing."
        )


def selected_proposals(
    plan: ProposalPlan, proposal_ids: tuple[str, ...]
) -> tuple[ExperimentProposal, ...]:
    chosen = set(proposal_ids)
    if len(chosen) != len(proposal_ids):
        raise ValueError("Duplicate selection")
    proposals = tuple(p for p in plan.proposals if p.proposal_id in chosen)
    if len(proposals) != len(chosen) or any(not p.runnable for p in proposals):
        raise ValueError(
            "Select only current runnable experiments; blocked/metadata rows cannot be saved or previewed."
        )
    return proposals


def explicit_values(experiment: Any) -> list[Any] | None:
    proposal = (getattr(experiment, "metadata", {}) or {}).get("evidence_proposal") or {}
    if proposal.get("contract") != CONTRACT_V2:
        return None
    from src.learning.model_capabilities import variable_name

    variable = variable_name(experiment.variable_under_test)
    if variable != proposal["variable"]:
        raise ValueError("Proposal variable changed; replan or clone as an ordinary experiment")
    field = dict(VARIABLES).get(variable)
    values = proposal["values"]
    if not field or not 2 <= len(values) <= 4:
        raise ValueError("Unsupported explicit proposal alternatives")
    _validate_values(variable, values)
    return copy.deepcopy(list(values))


def _validate_values(variable: str, values: Any) -> None:
    from src.learning.variable_metadata import get_variable_by_internal_name

    meta = get_variable_by_internal_name(variable)
    field = dict(VARIABLES)[variable]
    for value in values:
        validate_settings({field: value})
        if (
            meta is not None
            and meta.value_type == "numeric"
            and not (meta.constraints["min"] <= value <= meta.constraints["max"])
        ):
            raise ValueError(f"{meta.display_name} is outside existing Learning bounds")


def describe(proposal: ExperimentProposal) -> str:
    d = proposal.document
    if d.get("contract") != CONTRACT_V2:
        return f"{d.get('name', 'Saved proposal')}\nLegacy /1 proposal: resource revision and evidence references unavailable in this revision."
    refs = d.get("evidence_refs", [])
    sources = "\n".join(
        f"  {r['scope']} / {r['classification']} / {r['confidence']}: {r['source']}" for r in refs
    )
    return (
        f"{d['name']}\n\nQuestion: {d['objective']}\nWhy: {d['priority_reason']}\n"
        f"Controlled variable: {d['variable']}\nAlternatives: {d['values']}\n"
        f"Images: {d['expected_images']}\nStatus: {d['status']}\n"
        + "\n".join(d.get("blocked_reasons", []))
        + f"\n\nEvidence:\n{sources or '  No qualifying alternate claim.'}\n"
        "\nHeld constant: model, prompt context, common seed cohort and all other settings."
        "\nPublication requires controlled executed readback, saved ratings and explicit confirmation."
        "\nPreview and Queue to Learning do not admit jobs."
    )
