"""What the Learning baseline's model can be tested with, before the operator picks a study form (LEARN-NAV-871).

A pure projection over ``study_catalog``. It adds no eligibility rule: every verdict and every refusal text is the one the
study's own target check already raises (the descriptor's ``target_check_ref``), and the model's testable variables are
``project_learning_capabilities``' own output. Nothing here imports a toolkit, reads the filesystem or the backend, or
changes a baseline.

Per-study call shapes (each is the study's own check; the catalog only names it):

* Prompt Slot, LoRA Composition, Embedding: ``require_target(policy, baseline[, channel])``. The Embedding objective is
  judged on the positive channel; the negative channel's extra refusal is part of that design, not of the target.
* Model Comparison: ``candidate_ineligibility(policy)`` returns the reason (or ``None``). It is the check every compared
  model must pass, so here it judges the baseline's model as one candidate.
* Prompt x Model Matrix: the same candidate check, then ``require_matrix_baseline(baseline)``, the refusal Preview applies.
* Two-Axis Grid: its policy eligibility, then ``require_plain_txt2img(baseline)``, the refusal Preview applies.
* Compatibility Probe: ``require_probe_target(policy, baseline, spec)`` over the lineage recipes the probe offers for this
  family. A probe runs on its own generation-only baseline (optimizer off), so the authored baseline is not passed.
* Controlled Variable: the capability projection itself (stage supported and at least one testable variable).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.learning import study_catalog

#: Plain wording for the reason codes ``project_learning_capabilities`` reports per unavailable variable.
_VARIABLE_REASONS = {
    "stage_unsupported": "this stage is not supported for the model",
    "fixed": "the model's profile fixes it",
    "unsupported": "the model does not support it",
    "restricted_control": "the model allows only specific values",
    "lora_admission_required": "no admitted LoRA is selected",
    "lora_unverified": "LoRA support is not verified for this model",
    "lora_unsupported": "the model does not support LoRAs",
    "model_policy_comparison_unavailable": "this model's policy has no model-comparison evidence",
}
_NOT_A_BASELINE_MODEL = "Judged for the Learning baseline's model; each model you compare is checked when you choose it."


@dataclass(frozen=True)
class StudyEligibility:
    slug: str
    label: str
    objective_group: str
    nav_tier: str
    available: bool
    #: The study's own refusal text; ``""`` when available.
    reason: str = ""
    #: Context that is not a verdict (for example what the verdict was judged against).
    note: str = ""


@dataclass(frozen=True)
class EligibleStudies:
    studies: tuple[StudyEligibility, ...]
    #: Display names of the variables a Controlled Variable experiment can test on this model and stage.
    variables: tuple[str, ...]
    #: ``(variable, plain reason)`` for each variable the model cannot test.
    unavailable_variables: tuple[tuple[str, str], ...]
    stage: str
    target: str

    def get(self, slug: str) -> StudyEligibility | None:
        return next((study for study in self.studies if study.slug == slug), None)

    def in_group(self, group: str) -> tuple[StudyEligibility, ...]:
        return tuple(study for study in self.studies if study.objective_group == group)


def _display_name(internal: str) -> str:
    from src.learning.variable_metadata import get_variable_by_internal_name

    meta = get_variable_by_internal_name(internal)
    return meta.display_name if meta else internal


def variable_reason(code: str) -> str:
    return _VARIABLE_REASONS.get(code) or str(code).replace("_", " ")


def _refusal(call: Any) -> str:
    """The text a study's own check raises, or ``""`` when it passes."""
    try:
        outcome = call()
    except ValueError as exc:
        return str(exc)
    return str(outcome or "")  # ``candidate_ineligibility`` returns its reason instead of raising


def _target_checks(
    descriptor: study_catalog.StudyDescriptor, policy: Any, baseline: Mapping[str, Any]
) -> list[Any]:
    """The ordered calls that decide this study for the model; each raises ``ValueError`` or returns a reason."""
    check = study_catalog.resolve_ref(descriptor.target_check_ref)
    slug = descriptor.slug
    if slug in ("prompt_slot", "lora_composition"):
        return [lambda: check(policy, baseline)]
    if slug == "embedding_experiment":
        from src.learning.embedding_experiment import POSITIVE

        return [lambda: check(policy, baseline, POSITIVE)]
    if slug == "model_comparison":
        return [lambda: check(policy)]
    if slug == "prompt_model_matrix":
        from src.learning.prompt_model_matrix import require_matrix_baseline

        return [lambda: check(policy), lambda: require_matrix_baseline(baseline)]
    if slug == "two_axis_grid":
        from src.learning.two_axis_grid import require_plain_txt2img

        return [lambda: check(policy), lambda: require_plain_txt2img(baseline)]
    if slug == "compatibility_probe":
        from src.learning.compatibility_probe import suggest_recipes

        spec = {
            "recipes": [recipe.to_dict() for recipe in suggest_recipes(family=str(policy.family))]
        }
        return [lambda: check(policy, {}, spec)]
    raise ValueError(f"No target check is wired for study {slug!r}")


def _inventory_note(slug: str, resources: Mapping[str, Any] | None) -> str:
    key = {"lora_composition": "loras", "embedding_experiment": "embeddings"}.get(slug)
    if key and resources is not None and key in resources and not resources[key]:
        return f"No {'LoRAs' if key == 'loras' else 'embeddings'} are listed yet; refresh the lists before designing."
    return ""


def eligible_studies(
    policy: Any,
    baseline: Mapping[str, Any] | None,
    resources: Mapping[str, Any] | None = None,
    *,
    stage: str = "txt2img",
    model: str = "",
    capabilities: Any = None,
) -> EligibleStudies:
    """Each cataloged study as available or unavailable for ``policy``, plus the model's testable variables.

    ``capabilities`` lets a caller that already holds the live projection (which knows the selected LoRAs) pass it in;
    otherwise the pure projection for ``policy`` is used. ``resources`` only adds inventory notes, never a verdict.
    """
    from src.learning.model_capabilities import project_learning_capabilities
    from src.learning.model_policy_service import selected_model

    baseline = baseline or {}
    model = model or selected_model(dict(baseline), stage) or ""
    capability = capabilities or project_learning_capabilities(policy, model, stage)
    studies: list[StudyEligibility] = []
    for descriptor in study_catalog.STUDIES:
        if descriptor.slug == "controlled_variable":
            if not capability.stage_supported:
                reason = "The selected stage is unavailable for this model."
            elif not capability.variables:
                reason = "No variable can be tested on this model and stage."
            else:
                reason = ""
        else:
            reason = next(
                (
                    text
                    for text in (
                        _refusal(call) for call in _target_checks(descriptor, policy, baseline)
                    )
                    if text
                ),
                "",
            )
        note = (
            _NOT_A_BASELINE_MODEL
            if descriptor.slug in ("model_comparison", "prompt_model_matrix")
            else ""
        )
        studies.append(
            StudyEligibility(
                slug=descriptor.slug,
                label=descriptor.label,
                objective_group=descriptor.objective_group,
                nav_tier=descriptor.nav_tier,
                available=not reason,
                reason=reason,
                note=note or _inventory_note(descriptor.slug, resources),
            )
        )
    return EligibleStudies(
        studies=tuple(studies),
        variables=tuple(capability.variables),
        unavailable_variables=tuple(
            (_display_name(name), variable_reason(code)) for name, code in capability.unavailable
        ),
        stage=stage,
        target=capability.target,
    )


def describe(result: EligibleStudies) -> tuple[str, ...]:
    """Plain lines for a read-only details block ("What you can test on this model")."""
    lines: list[str] = []
    for objective in study_catalog.OBJECTIVES:
        members = result.in_group(objective.key)
        if not members:
            continue
        lines.append(f"{objective.label}:")
        for study in members:
            if study.available:
                lines.append(f"  {study.label}: available")
            else:
                lines.append(f"  {study.label}: not available - {study.reason}")
    if result.variables:
        lines.append("Settings you can vary (Controlled Variable): " + ", ".join(result.variables))
    for name, reason in result.unavailable_variables:
        lines.append(f"  {name}: not testable - {reason}")
    return tuple(lines)
