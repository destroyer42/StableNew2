"""Findings and experiment conclusions: every statement carries source, applicability, freshness and a limitation.

Facts established by policy, research claims, controlled observations and subjective preferences stay in
separate source classes. Unknown, conflicting and missing evidence is reported as such and never filled in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.generation_profiles.contract import SETTING_KEYS
from src.generation_profiles.evidence_catalog import EvidenceCatalog
from src.generation_profiles.identity import ResolvedModel
from src.learning.intelligence_contracts import (
    SOURCE_CONTROLLED,
    SOURCE_POLICY,
    SOURCE_PREFERENCE,
    SOURCE_RESEARCH,
    STATUS_CLAIMED,
    STATUS_CONFLICTING,
    STATUS_ESTABLISHED,
    STATUS_EXCLUDED,
    STATUS_INSUFFICIENT,
    STATUS_OBSERVED,
    STATUS_UNKNOWN,
    VERDICT_INSUFFICIENT,
    EvidenceFinding,
    ExperimentConclusion,
    PreferenceSummary,
    digest,
)
from src.learning.intelligence_sources import STATE_COMPLETED, STATE_FAILED, ExperimentView
from src.learning.profile_publication import LIMITATION, PublicationProposal
from src.learning.setting_evidence import SCREENING_PAIRS, screening_supported

SCREENING_LIMITATION = (
    "Six-pair screening rule: supports follow-up investigation only. It is not statistical proof, "
    "a universal optimum or a probability of improvement."
)
_COVERAGE_STATUS = {
    "unavailable": STATUS_UNKNOWN,
    "conflicting": STATUS_CONFLICTING,
    "recommended": STATUS_CLAIMED,
    "hypothesis": STATUS_CLAIMED,
}


def model_ref(target: ResolvedModel) -> str:
    identity = target.identity
    return "mdl-" + digest([identity.sha256 or identity.display_name, identity.family])[:12]


def make_finding(
    topic: str,
    source_class: str,
    status: str,
    statement: str,
    *,
    source_ref: str,
    applicability: str,
    freshness: str,
    limitation: str,
) -> EvidenceFinding:
    ident = "fnd-" + digest([topic, source_class, status, source_ref, statement])[:12]
    return EvidenceFinding(
        ident,
        topic,
        source_class,
        status,
        statement,
        source_ref,
        applicability,
        freshness,
        limitation,
    )


def is_applicable(view: ExperimentView, target: ResolvedModel) -> bool:
    """An experiment speaks about this checkpoint only when its frozen or proposed bytes are the same."""
    sha = target.identity.sha256
    return bool(sha) and view.model_sha == sha and view.model_family == target.identity.family


def invalid_evidence(view: ExperimentView) -> list[str]:
    """Why a completed or failed experiment cannot be technical evidence (empty when it can)."""
    reasons = []
    for variant in view.variants:
        if variant.status == "failed":
            reasons.append(f"variant {variant.variant_id or '?'} failed")
        elif variant.status == "completed" and (
            variant.controlled is not True or variant.reason != "valid"
        ):
            why = variant.reason or "no controlled readback was recorded"
            reasons.append(f"variant {variant.variant_id or '?'}: {why}")
    return reasons


def conclude(view: ExperimentView, overall: Mapping[str, float]) -> ExperimentConclusion | None:
    """The supported conclusion of a completed, controlled experiment, from saved ratings only."""
    if view.state != STATE_COMPLETED or invalid_evidence(view):
        return None
    base = {"experiment_id": view.experiment_id, "prompt_context": view.prompt_context}
    variants = view.variants
    paired_design = (
        len(variants) == 2
        and all(len(v.image_refs) == SCREENING_PAIRS for v in variants)
        and variants[0].seeds == variants[1].seeds
        and len(variants[0].seeds) == SCREENING_PAIRS
    )
    if not paired_design:
        return ExperimentConclusion(
            **base,
            status="descriptive",
            text="Controlled and rated, but no screening decision rule applies to this design; "
            "the ratings are descriptive only.",
            limitation=SCREENING_LIMITATION,
        )
    paired = [
        overall[b] - overall[a]
        for a, b in zip(variants[0].image_refs, variants[1].image_refs, strict=True)
        if a in overall and b in overall
    ]
    if len(paired) < SCREENING_PAIRS:
        return ExperimentConclusion(
            **base,
            status="insufficient",
            text=f"{len(paired)} of {SCREENING_PAIRS} seed-paired images are rated; no conclusion yet.",
            limitation=SCREENING_LIMITATION,
        )
    supported = screening_supported(paired)
    return ExperimentConclusion(
        **base,
        status="supported" if supported else "inconclusive",
        text=(
            "Follow-up investigation supported: the candidate won at least 5 of 6 seed-paired images "
            "with a mean improvement of at least 0.5."
            if supported
            else "Inconclusive: the six seed-paired ratings do not meet the screening rule."
        ),
        limitation=SCREENING_LIMITATION,
    )


def build_findings(
    target: ResolvedModel,
    catalog: EvidenceCatalog,
    applicable: Iterable[ExperimentView],
    conclusions: Iterable[ExperimentConclusion],
    preference: PreferenceSummary,
    publication: PublicationProposal | None,
    *,
    rating_revision: str,
) -> tuple[EvidenceFinding, ...]:
    identity, policy = target.identity, target.policy
    ref = model_ref(target)
    revision = "catalog:" + catalog.revision[:12]
    out: list[EvidenceFinding] = []
    verified = bool(identity.sha256 and target.verified_family and identity.family != "unknown")
    out.append(
        make_finding(
            "identity",
            SOURCE_POLICY,
            STATUS_ESTABLISHED if verified else STATUS_UNKNOWN,
            f"Checkpoint bytes verified; family {identity.family}."
            if verified
            else "Checkpoint identity or compatibility is unverified"
            + (f": {target.unverified_reason}" if target.unverified_reason else "."),
            source_ref=f"identity:{(identity.sha256 or 'unverified')[:12]}",
            applicability=f"{ref}, this exact checkpoint",
            freshness=f"policy:{policy.policy_id}",
            limitation="Identity is byte-level; a renamed or modified file is a different checkpoint.",
        )
    )
    out.append(
        make_finding(
            "policy",
            SOURCE_POLICY,
            STATUS_ESTABLISHED if verified else STATUS_UNKNOWN,
            f"Policy {policy.policy_id}: family {policy.family}, "
            f"{'qualified exact profile' if policy.qualified else 'registry capability policy'}.",
            source_ref=f"policy:{policy.policy_id}",
            applicability=f"{ref}, backends {', '.join(sorted(policy.allowed_backends)) or 'none'}",
            freshness=f"policy:{policy.policy_id}",
            limitation="Policy states what may be varied or applied; it is not a quality claim.",
        )
    )
    for row in catalog.coverage(identity):
        if row.field not in SETTING_KEYS:
            continue
        scopes = sorted({c.classification for c in row.claims})
        values = sorted({str(c.value) for c in row.claims})[:4]
        status = _COVERAGE_STATUS[row.status]
        detail = f" Claimed values: {', '.join(values)}." if values else ""
        out.append(
            make_finding(
                f"claim:{row.field}",
                SOURCE_RESEARCH,
                status,
                f"{row.field}: {row.reason}{detail}",
                source_ref=f"catalog:{row.field}",
                applicability=(
                    f"claims scoped {', '.join(scopes)}" if scopes else "no matching claim"
                )
                + f" for {ref}",
                freshness=revision,
                limitation="Reviewed research claims are not controlled observations of this installation.",
            )
        )
    for view in sorted(applicable, key=lambda v: v.experiment_id):
        problems = invalid_evidence(view)
        if problems and view.state in (STATE_COMPLETED, STATE_FAILED):
            out.append(
                make_finding(
                    f"experiment:{view.experiment_id}",
                    SOURCE_CONTROLLED,
                    STATUS_EXCLUDED,
                    "Execution evidence is invalid and cannot support a conclusion: "
                    + "; ".join(problems[:3]),
                    source_ref=f"experiment:{view.experiment_id}",
                    applicability=f"{ref}, tested setting {view.variable or 'unknown'}",
                    freshness="records:" + rating_revision[:12],
                    limitation="Uncontrolled or unverified runs are neither technical nor preference evidence.",
                )
            )
    for conclusion in sorted(conclusions, key=lambda c: c.experiment_id):
        out.append(
            make_finding(
                f"experiment:{conclusion.experiment_id}",
                SOURCE_CONTROLLED,
                STATUS_INSUFFICIENT if conclusion.status == "insufficient" else STATUS_OBSERVED,
                conclusion.text,
                source_ref=f"experiment:{conclusion.experiment_id}",
                applicability=f"{ref}, prompt context {conclusion.prompt_context or 'unrecorded'}",
                freshness="records:" + rating_revision[:12],
                limitation=conclusion.limitation,
            )
        )
    for group in preference.groups:
        out.append(
            make_finding(
                f"preference:{group.setting}",
                SOURCE_PREFERENCE,
                STATUS_INSUFFICIENT if group.verdict == VERDICT_INSUFFICIENT else STATUS_OBSERVED,
                group.statement,
                source_ref=group.group_id,
                applicability=f"{ref}, {group.prompt_context}, category {group.category}",
                freshness="records:" + rating_revision[:12],
                limitation=group.limitation,
            )
        )
    if preference.excluded:
        counts = ", ".join(f"{name} {count}" for name, count in preference.excluded)
        out.append(
            make_finding(
                "preference:excluded",
                SOURCE_PREFERENCE,
                STATUS_EXCLUDED,
                f"Ratings not pooled into any preference: {counts}.",
                source_ref="ratings:excluded",
                applicability=f"{ref}",
                freshness="records:" + rating_revision[:12],
                limitation="Other models, uncontrolled runs, unpaired generations and unmatched "
                "prompt contexts are never combined.",
            )
        )
    if publication is not None and publication.ready:
        out.append(
            make_finding(
                "publication",
                SOURCE_CONTROLLED,
                STATUS_OBSERVED,
                f"{publication.sample_count} controlled rating(s) in {publication.experiment_count} "
                f"experiment(s) qualify {len(publication.findings)} setting(s) for review.",
                source_ref="publication:" + publication.evidence_digest[:12],
                applicability=f"{ref}, tested prompts and frozen contexts",
                freshness="records:" + rating_revision[:12],
                limitation=LIMITATION,
            )
        )
    return tuple(sorted(out, key=lambda f: (f.source_class, f.topic, f.finding_id)))
