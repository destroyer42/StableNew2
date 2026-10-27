"""Field-specific controlled evidence -> advisory profile; no execution or rating authority.

Only saved ordinary txt2img ratings enter this projection. Historical records without a
frozen byte identity stay readable but cannot establish a checkpoint-specific finding.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.generation_profiles.application import plan_application, policy_blocks
from src.generation_profiles.contract import (
    IDENTITY_EXACT,
    IDENTITY_MODEL,
    KIND_LEARNING,
    SETTING_KEYS,
    SOURCE_LEARNING,
    EvidenceNote,
    GenerationProfile,
    ModelIdentity,
    ProfileError,
    ProfileRef,
    validate_settings,
)
from src.generation_profiles.identity import (
    MATCH_EXACT,
    MATCH_RENAMED,
    ModelIdentityResolver,
    ResolvedModel,
    match_identity,
)
from src.generation_profiles.store import GenerationProfileStore
from src.learning.experiment_execution import freeze_snapshot, snapshot_digest
from src.learning.learning_record import evidence_file_lock
from src.learning.model_capabilities import compatible_context, policy_context, variable_name
from src.learning.model_policy_service import selected_model
from src.learning.recommendation_engine import (
    MIN_CONTROLLED_RATINGS,
    MIN_CONTROLLED_VARIANTS,
    recommendation_confidence,
)
from src.learning.variable_metadata import LEARNING_VARIABLES

LIMITATION = (
    "These findings describe the tested prompts and frozen context. They do not establish "
    "universal optimal settings or a probability of improvement."
)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _rank_value(item: tuple[Any, list[float]]) -> tuple[float, float, str]:
    value, ratings = item
    deviation = statistics.stdev(ratings) if len(ratings) > 1 else 0.0
    return (
        -recommendation_confidence(len(ratings), deviation, 1.0),
        -statistics.mean(ratings),
        json.dumps(value),
    )


def strong_match(saved: ModelIdentity, current: ModelIdentity) -> bool:
    if saved.kind == IDENTITY_EXACT:
        reference = saved.exact_profile or {}
        return (
            current.kind == IDENTITY_EXACT
            and bool(reference)
            and (
                dict(reference) == dict(current.exact_profile or {})
                and reference.get("version") is not None
                and saved.family == current.family
            )
        )
    return bool(
        saved.kind == current.kind == IDENTITY_MODEL
        and saved.sha256
        and current.sha256
        and match_identity(saved, current).status in (MATCH_EXACT, MATCH_RENAMED)
    )


@dataclass(frozen=True)
class Finding:
    setting: str
    value: Any
    experiment_count: int
    sample_count: int
    tested_values: tuple[Any, ...]
    mean_rating: float
    rating_stddev: float
    evidence_digest: str

    @property
    def rationale(self) -> str:
        return (
            f"{self.setting}={self.value}: {self.sample_count} saved controlled ratings in "
            f"{self.experiment_count} experiments across {len(self.tested_values)} tested values. "
            f"Winning value mean {self.mean_rating:.2f}/5, standard deviation {self.rating_stddev:.2f}. "
            "Evidence tier experiment_strong. A learned starting point, not a guaranteed optimum."
        )


@dataclass(frozen=True)
class PublicationProposal:
    model: ModelIdentity
    experiment_id: str
    findings: tuple[Finding, ...] = ()
    excluded: tuple[tuple[str, str], ...] = ()
    blockers: tuple[str, ...] = ()
    evidence_digest: str = ""
    experiment_count: int = 0
    sample_count: int = 0
    lineages: tuple[GenerationProfile, ...] = ()
    # Serialized once: the UI cannot accidentally mutate the approved evidence/settings.
    target_context: str = ""
    prior_publications: tuple[GenerationProfile, ...] = ()

    @property
    def settings(self) -> dict[str, Any]:
        return {finding.setting: finding.value for finding in self.findings}

    @property
    def ready(self) -> bool:
        return bool(self.findings) and not self.blockers

    def already_published(self, lineage: ProfileRef | None = None) -> GenerationProfile | None:
        return next(
            (
                profile
                for profile in self.prior_publications
                if profile.provenance.get("evidence_digest") == self.evidence_digest
                and dict(profile.settings) == self.settings
                and (lineage is None or profile.profile_id == lineage.profile_id)
            ),
            None,
        )

    def differences(self, previous: GenerationProfile | None) -> tuple[str, ...]:
        before = previous.settings if previous else {}
        return tuple(
            f"{key}: {before.get(key, 'unavailable')} -> {self.settings.get(key, 'unavailable')}"
            for key in sorted(set(before) | set(self.settings))
            if before.get(key) != self.settings.get(key)
        )


@dataclass(frozen=True)
class _Sample:
    identity: tuple[str, str, str]
    experiment: str
    setting: str
    value: Any
    rating: float
    context: str
    proof: str
    seeds: tuple[int, ...]


def _sample(row: Mapping[str, Any], target: ResolvedModel) -> _Sample:
    meta = row["metadata"]
    frozen = meta["frozen_experiment"]
    snapshot = frozen["snapshot"]
    from src.learning.evidence_proposals import validate_proposal_snapshot
    from src.learning.setting_evidence import require_rating_proof

    validate_proposal_snapshot(snapshot, current=target.identity)
    require_rating_proof(meta, snapshot)
    config = frozen["executed_config"]
    experiment = meta["experiment_id"]
    variant = meta["learning_context"]["variant_id"]
    if not all(
        isinstance(item, str) and item.strip()
        for item in (experiment, variant, meta["job_id"], meta["image_path"])
    ):
        raise ProfileError("Durable experiment, variant, job and sample identities are required.")
    if (
        experiment != frozen["experiment_id"]
        or experiment != snapshot["experiment_id"]
        or experiment != meta["learning_context"]["experiment_id"]
        or variant != frozen["variant_id"]
    ):
        raise ProfileError("Contradictory experiment or variant identity.")
    if (
        frozen.get("controlled_evidence_valid") is not True
        or frozen.get("variable_validation_reason") != "valid"
    ):
        raise ProfileError("Ratings are saved but controlled execution evidence is unverified.")
    if snapshot_digest(freeze_snapshot(snapshot)) != frozen["snapshot_sha256"]:
        raise ProfileError("Frozen snapshot digest does not verify.")
    seeds = frozen["actual_all_seeds"]
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
        or len(seeds) != snapshot["seed_policy"]["requested_sample_count"]
    ):
        raise ProfileError("Actual controlled seed readback is missing or contradictory.")
    if snapshot.get("stage") != "txt2img" or snapshot.get(
        "study_type", "controlled_variable"
    ) not in ("controlled_variable", "ordinary"):
        raise ProfileError(
            "Stage-specific and comparative Learning profiles are not supported yet."
        )
    variable = variable_name(snapshot["variable_under_test"])
    if not variable or variable != variable_name(meta["variable_under_test"]):
        raise ProfileError("The tested variable identity is missing or contradictory.")
    key = LEARNING_VARIABLES[variable].config_path.split(".")[-1]
    if key not in SETTING_KEYS:
        raise ProfileError("The tested variable cannot be represented by Base Generation profiles.")
    value = validate_settings({key: meta["variant_value"]})[key]
    section = config["txt2img"]
    if value != section[key] or value not in snapshot["variant_values"]:
        raise ProfileError("Executed tested-variable value contradicts the frozen experiment.")
    for fixed_key, fixed_value in snapshot["baseline_config"]["txt2img"].items():
        if (
            fixed_key in SETTING_KEYS
            and fixed_key != key
            and fixed_key in section
            and section[fixed_key] != fixed_value
        ):
            raise ProfileError(
                "Executed fixed baseline settings contradict the frozen controlled context."
            )
    identity = ModelIdentity.from_dict(snapshot["model_identity"])
    if not strong_match(identity, target.identity):
        raise ProfileError(
            "Frozen checkpoint identity or executable profile version conflicts with the target."
        )
    if identity.kind == IDENTITY_EXACT:
        executed_profile = (
            (config.get("backend_options") or {}).get("image", {}).get("model_profile")
        )
        if executed_profile != identity.exact_profile:
            raise ProfileError(
                "Executed executable profile/version conflicts with the frozen target."
            )
    context = snapshot["model_policy_context"]
    if not compatible_context(
        context, policy_context(target.policy, context["selected_model"], "txt2img")
    ):
        raise ProfileError("Frozen model policy is incompatible with the current target.")
    # Names corroborate the frozen byte binding; current registry data never backfills an old snapshot.
    from src.image_backends.model_readiness_probe import checkpoint_key

    names = (
        selected_model(snapshot["baseline_config"], "txt2img"),
        selected_model(config, "txt2img"),
        row["primary_model"],
        context["selected_model"],
    )
    if not identity.model_key or any(checkpoint_key(name) != identity.model_key for name in names):
        raise ProfileError("Frozen and executed model identities conflict.")
    rating = meta["user_rating"]
    if (
        isinstance(rating, bool)
        or not isinstance(rating, (int, float))
        or not math.isfinite(rating)
        or not 1 <= rating <= 5
    ):
        raise ProfileError("A valid saved rating from 1 to 5 is required.")
    blocked = policy_blocks(target.policy, key, value)
    control = target.policy.control(variable, "txt2img")
    if blocked or (control.allowed and value not in control.allowed):
        raise ProfileError(blocked or "The value is outside the model policy's allowed settings.")
    # All variants of an experiment must share the very same frozen snapshot.
    sample_id = (experiment, meta["job_id"], meta["image_path"])
    return _Sample(
        sample_id,
        experiment,
        key,
        value,
        float(rating),
        frozen["snapshot_sha256"],
        digest({"sample": sample_id, "variant": variant, "frozen": frozen, "rating": rating}),
        tuple(seeds),
    )


class ProfilePublicationService:
    """Read-only proposals, then fresh validation and one explicitly confirmed store write."""

    def __init__(
        self, store: GenerationProfileStore, resolver: ModelIdentityResolver | None = None
    ) -> None:
        self.store = store
        self.resolver = resolver or ModelIdentityResolver()

    def evaluate(
        self,
        rows: Iterable[Mapping[str, Any]],
        model_name: str,
        *,
        experiment_id: str = "",
        catalogs: Mapping[str, Any] | None = None,
    ) -> PublicationProposal:
        target = self.resolver.resolve(model_name)
        blockers: list[str] = []
        if not target.verified_family or target.unverified_reason:
            blockers.append(
                target.unverified_reason or "The selected checkpoint family is unverified."
            )
        if target.identity.kind == IDENTITY_MODEL and not target.identity.sha256:
            blockers.append(
                "The selected checkpoint's SHA-256 is not verified; use existing registry readiness first."
            )
        latest: dict[tuple[Any, ...], Mapping[str, Any]] = {}
        for row in rows:
            meta = row.get("metadata") or {}
            if meta.get("record_kind") != "learning_experiment_rating":
                continue
            if experiment_id and meta.get("experiment_id") != experiment_id:
                continue
            identity = (meta.get("experiment_id"), meta.get("job_id"), meta.get("image_path"))
            if all(isinstance(item, str) and item for item in identity):
                latest[identity] = row  # append order is the durable rating-replacement rule
        excluded = dict.fromkeys(
            SETTING_KEYS, "No independently qualified controlled experiment for this setting."
        )
        groups: dict[tuple[str, str], list[_Sample]] = defaultdict(list)
        experiment_contexts: dict[str, set[str]] = defaultdict(set)
        rejected: list[str] = []
        for row in latest.values():
            try:
                sample = _sample(row, target)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                reason = (
                    str(exc)
                    if not isinstance(exc, KeyError)
                    else f"Missing execution evidence: {exc}."
                )
                rejected.append(reason)
                variable = variable_name((row.get("metadata") or {}).get("variable_under_test", ""))
                if variable:
                    setting = LEARNING_VARIABLES[variable].config_path.split(".")[-1]
                    if setting in excluded:
                        excluded[setting] = reason
                continue
            groups[(sample.experiment, sample.setting)].append(sample)
            experiment_contexts[sample.experiment].add(sample.context)
        qualified: dict[str, list[_Sample]] = defaultdict(list)
        for (_experiment, setting), cohort in groups.items():
            values = {json.dumps(s.value, sort_keys=True) for s in cohort}
            if len(experiment_contexts[_experiment]) != 1:
                excluded[setting] = "Contradictory frozen snapshots within one experiment."
            elif len({s.seeds for s in cohort}) != 1:
                excluded[setting] = "Contradictory controlled seed readback within one experiment."
            elif len(values) < MIN_CONTROLLED_VARIANTS:
                excluded[setting] = (
                    f"At least {MIN_CONTROLLED_VARIANTS} distinct tested values are required."
                )
            elif len(cohort) < MIN_CONTROLLED_RATINGS:
                excluded[setting] = (
                    f"{MIN_CONTROLLED_RATINGS - len(cohort)} more controlled rating(s) needed."
                )
            else:
                qualified[setting].extend(cohort)
        findings: list[Finding] = []
        used: list[_Sample] = []
        for key, cohort in sorted(qualified.items()):
            by_value: dict[Any, list[float]] = defaultdict(list)
            for sample in cohort:
                by_value[sample.value].append(sample.rating)

            # Existing volume/variance score, with identical exact-context weight for each
            # candidate. No broad prompt weighting or untested baseline parameters enter.
            winner = min(by_value.items(), key=_rank_value)[0]
            winning_ratings = by_value[winner]
            plan = plan_application(
                profile=GenerationProfile(
                    "proposal",
                    1,
                    KIND_LEARNING,
                    "Proposal",
                    target.identity,
                    {key: winner},
                    executable_profile=target.identity.exact_profile,
                    provenance={"publisher": "learning-profile-660"},
                ),
                match=match_identity(target.identity, target.identity),
                working={},
                policy=target.policy,
                catalogs=catalogs,
            )
            refused = [note.message for note in plan.conflicts]
            resource = {"sampler_name": "samplers", "scheduler": "schedulers", "vae": "vaes"}.get(
                key
            )
            if resource and (not catalogs or not catalogs.get(resource)):
                refused.append(
                    "Runtime resource availability is unverified; refresh resources before publication."
                )
            if refused:
                excluded[key] = "Evidence qualified; publication unavailable: " + "; ".join(refused)
                continue
            findings.append(
                Finding(
                    key,
                    winner,
                    len({s.experiment for s in cohort}),
                    len(cohort),
                    tuple(sorted(by_value, key=json.dumps)),
                    statistics.mean(winning_ratings),
                    statistics.stdev(winning_ratings) if len(winning_ratings) > 1 else 0.0,
                    digest(sorted(s.proof for s in cohort)),
                )
            )
            used.extend(cohort)
            excluded.pop(key)
        lineages = tuple(
            p
            for p in self.store.list_latest(KIND_LEARNING)
            if strong_match(p.model, target.identity)
        )
        if not findings:
            blockers.extend(sorted(set(rejected))[:4] or ["More controlled evidence is needed."])
        return PublicationProposal(
            target.identity,
            experiment_id,
            tuple(findings),
            tuple(sorted(excluded.items())),
            tuple(dict.fromkeys(blockers)),
            digest(sorted(s.proof for s in used)),
            len({s.experiment for s in used}),
            len(used),
            lineages,
            freeze_snapshot(policy_context(target.policy, model_name, "txt2img")),
            tuple(
                revision
                for profile in lineages
                for revision in self.store.revisions(KIND_LEARNING, profile.profile_id)
            ),
        )

    def publish(
        self,
        proposal: PublicationProposal,
        rows: Iterable[Mapping[str, Any]],
        model_name: str,
        *,
        name: str,
        confirmed: bool,
        lineage: ProfileRef | None = None,
        catalogs: Mapping[str, Any] | None = None,
    ) -> GenerationProfile:
        # Cooperating in-process publishers serialize the duplicate check and store call.
        # The store additionally refuses a competing immutable file atomically across processes.
        with evidence_file_lock(self.store.root / "profiles" / KIND_LEARNING):
            return self._publish(
                proposal,
                rows,
                model_name,
                name=name,
                confirmed=confirmed,
                lineage=lineage,
                catalogs=catalogs,
            )

    def _publish(
        self,
        proposal: PublicationProposal,
        rows: Iterable[Mapping[str, Any]],
        model_name: str,
        *,
        name: str,
        confirmed: bool,
        lineage: ProfileRef | None,
        catalogs: Mapping[str, Any] | None,
    ) -> GenerationProfile:
        if confirmed is not True:
            raise ProfileError("Explicit operator confirmation is required.")
        current = self.evaluate(
            rows, model_name, experiment_id=proposal.experiment_id, catalogs=catalogs
        )
        if (
            not proposal.ready
            or not current.ready
            or proposal.model != current.model
            or proposal.evidence_digest != current.evidence_digest
            or proposal.settings != current.settings
            or proposal.target_context != current.target_context
        ):
            raise ProfileError(
                "Proposal is stale or ineligible; review fresh model and evidence findings."
            )
        previous = None
        if lineage is not None:
            if lineage.kind != KIND_LEARNING:
                raise ProfileError("Only a Learning lineage can receive these findings.")
            previous = self.store.load(ProfileRef(KIND_LEARNING, lineage.profile_id))
            if (
                previous is None
                or previous.ref != lineage
                or not strong_match(previous.model, current.model)
            ):
                raise ProfileError(
                    "Selected Learning lineage is stale or belongs to a different model."
                )
        if current.already_published(previous.ref if previous else None):
            raise ProfileError("These findings are already published.")
        profile = GenerationProfile(
            previous.profile_id if previous else f"learning-{uuid.uuid4().hex[:16]}",
            previous.revision + 1 if previous else 1,
            KIND_LEARNING,
            name.strip(),
            previous.model if previous else current.model,
            validate_settings(current.settings),
            unavailable=dict(current.excluded),
            evidence=tuple(
                EvidenceNote(
                    (finding.setting,),
                    SOURCE_LEARNING,
                    finding.rationale,
                    reference=finding.evidence_digest,
                )
                for finding in current.findings
            ),
            operations=("txt2img",),
            executable_profile=current.model.exact_profile,
            provenance={
                "publisher": "stablenew.learning-profile.v1",
                "evidence_digest": current.evidence_digest,
                "model_identity_digest": digest(current.model.to_dict()),
                "experiment_count": current.experiment_count,
                "sample_count": current.sample_count,
                "tested_setting_count": len(current.findings),
                "method": "explicit_operator_confirmation",
                "evaluated_at": self.store.now(),
                "previous_revision": previous.revision if previous else 0,
            },
            created_at=self.store.now(),
        )
        return self.store.publish_learning_profile(profile)
