"""Read-only qualification pairing and findings from frozen execution and saved ratings.

No filename, list-position or requested-seed inference is permitted. Pairing requires
the forward artifact association captured at the backend response save boundary.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.evidence_proposals import validate_proposal_snapshot
from src.learning.experiment_execution import snapshot_digest, thaw_snapshot
from src.learning.setting_evidence import require_rating_proof, screening_supported
from src.learning.variable_metadata import get_variable_metadata
from src.pipeline.learning_sample_evidence import valid_runtime_observation


@dataclass(frozen=True)
class QualificationSample:
    variant_id: str
    value: Any
    image_ref: str
    seed: int | None
    rating: int | None
    reason: str = ""


@dataclass(frozen=True)
class QualificationPair:
    control: QualificationSample
    candidate: QualificationSample

    @property
    def difference(self) -> int | None:
        if self.control.rating is None or self.candidate.rating is None:
            return None
        return self.candidate.rating - self.control.rating

    @property
    def identity(self) -> tuple[str, str, str, int | None]:
        return (
            self.control.image_ref,
            self.candidate.variant_id,
            self.candidate.image_ref,
            self.control.seed,
        )


@dataclass(frozen=True)
class ComparisonFinding:
    value: Any
    pairs: int
    rated: int
    wins: int
    ties: int
    losses: int
    mean_difference: float | None
    differences: tuple[int, ...]
    subscore_differences: tuple[tuple[str, float, int], ...]


@dataclass(frozen=True)
class QualificationFindings:
    outcome: str
    reason: str
    next_action: str
    setting: str
    values: tuple[Any, ...]
    samples: tuple[QualificationSample, ...]
    pairs: tuple[QualificationPair, ...]
    comparisons: tuple[ComparisonFinding, ...]
    exclusions: tuple[str, ...]
    per_value: tuple[tuple[Any, int, int, float | None], ...]
    expected_pairs: int

    @property
    def rated_pairs(self) -> int:
        return sum(row.rated for row in self.comparisons)


def valid_rating(value: Any) -> int | None:
    return value if type(value) is int and 1 <= value <= 5 else None


def _sample_proof(
    experiment: Any, variant: Any, snapshot: dict[str, Any]
) -> tuple[dict[str, int], str]:
    metadata = variant.execution_metadata or {}
    if variant.status != "completed" or metadata.get("controlled_evidence_valid") is not True:
        return {}, "Variant is failed, cancelled, incomplete or uncontrolled."
    if (
        not experiment.experiment_id
        or variant.experiment_id != experiment.experiment_id
        or not variant.variant_id
        or not variant.job_id
    ):
        return {}, "Experiment/variant/job identity is missing or conflicting."
    try:
        require_rating_proof({**metadata, "variant_value": variant.param_value}, snapshot)
        meta = get_variable_metadata(snapshot.get("variable_under_test", ""))
        if meta is None:
            raise ValueError("Frozen tested setting is unavailable")
        stage, _, field = meta.config_path.partition(".")
        config = variant.executed_config or {}
        if config.get(stage, {}).get(field) != variant.param_value:
            raise ValueError("Compiled configuration conflicts with frozen tested value")
        if config.get("txt2img", {}).get("model") != snapshot.get("model_identity", {}).get(
            "display_name"
        ):
            raise ValueError("Compiled model conflicts with frozen identity")
        from src.learning import baseline_authoring as authoring

        expected_rows = snapshot.get("variant_effective_settings")
        if expected_rows is not None:
            expected_settings = [
                row["settings"] for row in expected_rows if row.get("value") == variant.param_value
            ]
            if len(expected_settings) != 1:
                raise ValueError("Frozen per-variant configuration is missing or ambiguous")
            promised = expected_settings[0]
        else:
            # Historical snapshot contracts still have an explicit frozen baseline.
            promised = authoring.variant_projection(
                snapshot["baseline_config"],
                stage,
                snapshot["evidence_proposal"]["variable"],
                variant.param_value,
            )
        actual = authoring.variant_projection(config, stage, "", None)
        missing = set(promised) - set(actual)
        if missing or authoring.parity_mismatches(promised, actual):
            raise ValueError("Compiled configuration conflicts with frozen expected settings")
        tested = next(
            row for row in metadata["qualification_setting_evidence"] if row.get("tested")
        )
        if tested.get("dispatched_request") != variant.param_value:
            raise ValueError("Dispatched tested setting is missing or mismatched")
    except (ValueError, KeyError, StopIteration, TypeError, AttributeError) as exc:
        return {}, f"Tested-setting readback unavailable: {exc}"
    proof = metadata.get("qualification_samples") or {}
    if not isinstance(proof, dict) or proof.get("contract") != "learning_samples/1":
        return (
            {},
            "Cannot verify matched pairs: historical per-image seed association is unavailable.",
        )
    before, after = proof.get("runtime_before"), proof.get("runtime_after")
    if not isinstance(before, dict) or not valid_runtime_observation(before) or before != after:
        return {}, "Backend launch identity unavailable or changed during generation."
    backend = (
        snapshot.get("baseline_config", {}).get("backend_options", {}).get("image") or {}
    ).get("backend_id")
    if backend and before.get("backend") != backend:
        return {}, "Observed backend identity conflicts with the frozen experiment."
    for key, expected in (
        ("experiment_id", experiment.experiment_id),
        ("variant_id", variant.variant_id),
        ("job_id", variant.job_id),
        ("snapshot_sha256", snapshot_digest(experiment.execution_snapshot_json)),
    ):
        if proof.get(key) != expected:
            return {}, f"Conflicting {key} in artifact/seed association."
    rows, seeds = proof.get("samples"), metadata.get("actual_all_seeds")
    if (
        not isinstance(rows, list)
        or not isinstance(seeds, list)
        or not seeds
        or any(type(seed) is not int or seed < 0 for seed in seeds)
    ):
        return {}, "Missing backend-observed seed vector or artifact association."
    if len(set(seeds)) != len(seeds):
        return {}, "Duplicate observed seeds cannot identify independent matched pairs."
    mapping, indices = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            return {}, "Malformed artifact/seed association."
        path, seed, index = row.get("path"), row.get("seed"), row.get("sample_index")
        if (
            not isinstance(path, str)
            or not path
            or path in mapping
            or type(index) is not int
            or index in indices
            or not 0 <= index < len(seeds)
            or type(seed) is not int
            or seeds[index] != seed
            or row.get("job_id") != variant.job_id
        ):
            return {}, "Duplicate, ambiguous or contradictory artifact/seed identity."
        mapping[path] = seed
        indices.add(index)
    if (
        len(variant.image_refs) != len(set(variant.image_refs))
        or set(mapping) != set(variant.image_refs)
        or len(mapping) != len(seeds)
    ):
        return {}, "Artifact list and observed sample associations disagree."
    policy = snapshot.get("seed_policy") or {}
    if len(mapping) != snapshot.get("images_per_value") or len(mapping) != policy.get(
        "requested_sample_count"
    ):
        return {}, "Incomplete controlled sample cohort."
    return mapping, ""


def _fixed_config(snapshot: dict[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    import copy

    result = copy.deepcopy(dict(config))
    # Existing compiler audit label, not an executable non-tested setting.
    result.pop("learning_variant_value", None)
    meta = get_variable_metadata(snapshot.get("variable_under_test", ""))
    if meta:
        stage, _, field = meta.config_path.partition(".")
        result.get(stage, {}).pop(field, None)
    return result


def project_qualification(
    experiment: Any,
    plan: list[Any],
    ratings: Mapping[str, Any],
    *,
    exists: Callable[[str], bool] = lambda path: Path(path).is_file(),
) -> QualificationFindings:
    """Compute afresh; ``ratings`` is the existing writer's experiment-scoped latest saved map.

    ``exists`` is an injected artifact availability observation; no persistence or
    current Pipeline/model catalog is consulted by this projection.
    """
    errors: list[str] = []
    try:
        snapshot = thaw_snapshot(experiment.execution_snapshot_json)
        if not snapshot.get("evidence_proposal"):
            raise ValueError("No frozen qualification proposal")
        validate_proposal_snapshot(snapshot)
        values = tuple(snapshot["variant_values"])
        if len(plan) != len(values) or len(values) < 2:
            raise ValueError("Frozen alternatives and saved variant plan disagree")
        if len({v.variant_id for v in plan}) != len(plan) or len({v.job_id for v in plan}) != len(
            plan
        ):
            raise ValueError("Duplicate variant or job identity")
        if snapshot.get("experiment_id", experiment.experiment_id) != experiment.experiment_id:
            raise ValueError("Frozen experiment identity conflicts with saved session")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        snapshot, values = {}, tuple(getattr(experiment, "values", []))
        errors.append(
            f"Cannot verify matched pairs: frozen qualification context unavailable ({exc})."
        )
    setting = str(
        snapshot.get("variable_under_test") or getattr(experiment, "variable_under_test", "")
    )
    all_refs = Counter(str(path) for v in plan for path in v.image_refs)
    samples: list[QualificationSample] = []
    groups: dict[str, list[QualificationSample]] = {}
    ordered = []
    for value in values:
        matches = [v for v in plan if v.param_value == value]
        if len(matches) != 1:
            errors.append(f"Value {value}: ambiguous or missing variant.")
        else:
            ordered.append(matches[0])
    profiles = {(v.execution_metadata or {}).get("runtime_launch_profile") for v in ordered}
    boundary_error = (
        ""
        if len(profiles) == 1 and None not in profiles and "" not in profiles
        else "Backend launch-profile/restart boundary is missing or conflicting."
    )
    launches = [
        (v.execution_metadata.get("qualification_samples") or {}).get("runtime_before")
        for v in ordered
    ]
    if launches and any(launch != launches[0] for launch in launches):
        boundary_error = "Backend restart boundary between compared variants."
    configs = [_fixed_config(snapshot, v.executed_config or {}) for v in ordered]
    if configs and any(config != configs[0] for config in configs):
        boundary_error = "Conflicting frozen non-tested configuration."
    for variant in plan:
        mapping, reason = (
            _sample_proof(experiment, variant, snapshot) if snapshot else ({}, errors[0])
        )
        reason = reason or boundary_error
        if reason:
            errors.append(f"{variant.param_value}: {reason}")
        group = []
        for path in variant.image_refs:
            issue = reason
            if all_refs[path] != 1:
                issue = "Duplicate artifact identity across variants."
            try:
                if not exists(path):
                    issue = "Missing artifact file."
            except (OSError, ValueError):
                issue = "Artifact file unavailable."
            if issue:
                errors.append(f"{variant.param_value}: {issue}")
            detail = ratings.get(path) or {}
            rating = (
                valid_rating(detail.get("overall_rating")) if isinstance(detail, Mapping) else None
            )
            sample = QualificationSample(
                variant.variant_id, variant.param_value, path, mapping.get(path), rating, issue
            )
            group.append(sample)
            samples.append(sample)
        groups[variant.variant_id] = group
    pairs, comparisons, per_value = [], [], []
    for variant in ordered:
        valid = [s for s in groups[variant.variant_id] if not s.reason]
        rated = [s.rating for s in valid if s.rating is not None]
        per_value.append(
            (
                variant.param_value,
                len(valid),
                len(rated),
                sum(rated) / len(rated) if rated else None,
            )
        )
    if ordered:
        control = {
            s.seed: s for s in groups[ordered[0].variant_id] if not s.reason and s.seed is not None
        }
        for variant in ordered[1:]:
            candidate = {
                s.seed: s for s in groups[variant.variant_id] if not s.reason and s.seed is not None
            }
            if set(control) != set(candidate):
                errors.append(f"{variant.param_value}: Missing or mismatched observed seed cohort.")
            matched = [
                QualificationPair(control[seed], candidate[seed])
                for seed in sorted(set(control) & set(candidate))
            ]
            pairs.extend(matched)
            paired_rated = [
                p
                for p in matched
                if p.control.rating is not None and p.candidate.rating is not None
            ]
            deltas = tuple(delta for p in paired_rated if (delta := p.difference) is not None)
            subscores: dict[str, list[int]] = {}
            for pair in paired_rated:
                a = ratings[pair.control.image_ref].get("subscores") or {}
                b = ratings[pair.candidate.image_ref].get("subscores") or {}
                for key in sorted(set(a) & set(b)):
                    av, bv = valid_rating(a[key]), valid_rating(b[key])
                    if av is not None and bv is not None:
                        subscores.setdefault(key, []).append(bv - av)
            comparisons.append(
                ComparisonFinding(
                    variant.param_value,
                    len(matched),
                    len(paired_rated),
                    sum(d > 0 for d in deltas),
                    deltas.count(0),
                    sum(d < 0 for d in deltas),
                    sum(deltas) / len(deltas) if deltas else None,
                    deltas,
                    tuple((k, sum(v) / len(v), len(v)) for k, v in sorted(subscores.items())),
                )
            )
    count = snapshot.get("images_per_value", 0)
    expected = count * max(0, len(values) - 1)
    rated_count = sum(c.rated for c in comparisons)
    if errors:
        outcome, action = "Execution evidence invalid", "Inspect Execution Evidence"
        reason = errors[0]
    elif rated_count < expected:
        outcome, action = "Needs ratings", "Finish Rating"
        reason = f"{rated_count}/{expected} matched pairs have two valid saved ratings. Unsaved drafts do not count."
    elif len(values) != 2 or count != 6:
        outcome, action = "Unsupported screening design", "Explore Proposed Experiments"
        reason = "Descriptive observations only; the six-pair screening rule does not apply to this design."
    elif comparisons and screening_supported(list(comparisons[0].differences)):
        outcome, action = "Follow-up supported", "Investigate Further"
        reason = "At least 5/6 candidate wins and mean improvement ≥ 0.5. Follow-up investigation supported; not statistical significance or permission to adopt settings."
    else:
        outcome, action = "Inconclusive", "Explore Proposed Experiments"
        reason = "Screen requires ≥5/6 candidate wins AND mean improvement ≥0.5. Ties are not wins; observed preferences do not establish an optimum."
    return QualificationFindings(
        outcome,
        reason,
        action,
        setting,
        values,
        tuple(samples),
        tuple(pairs),
        tuple(comparisons),
        tuple(dict.fromkeys(errors)),
        tuple(per_value),
        expected,
    )
