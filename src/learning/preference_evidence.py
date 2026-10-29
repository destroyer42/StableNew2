"""Read-only preference summary from saved Learning ratings.

Only ratings that are controlled, attributed to the exact checkpoint and carry a frozen prompt context can
be compared. Ratings from other models, uncontrolled runs, unpaired generations and unattributed prompts are
counted as excluded and never pooled. Verdicts name what was observed; none claims a learned or general
preference. Ordinal differences here are rating points, not confidence.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.generation_profiles.contract import ModelIdentity
from src.generation_profiles.identity import ResolvedModel
from src.learning.intelligence_contracts import (
    VERDICT_COMPETING,
    VERDICT_INSUFFICIENT,
    VERDICT_NO_CLEAR,
    VERDICT_OBSERVED,
    PreferenceGroup,
    PreferenceSummary,
    ValueSummary,
    digest,
)
from src.learning.intelligence_sources import rating_identity, valid_rating
from src.learning.learning_record import LearningRecord
from src.learning.profile_publication import ControlledSample, controlled_sample, strong_match

MIN_RATINGS_PER_VALUE = 3  # the same floor the recommendation engine uses for controlled ratings
MIN_LEADING_MARGIN = (
    0.5  # rating points on the existing 1-5 scale; a screening margin, not significance
)
CATEGORY_FLAGS = ("people", "animals", "landscape", "architecture")

OUTCOME_CONTROLLED = "controlled"
OUTCOME_OTHER_MODEL = "other_model"
OUTCOME_UNCONTROLLED = "uncontrolled"
OUTCOME_INVALID = "invalid_rating"


@dataclass(frozen=True)
class RatingAttribution:
    experiment: str
    image: str
    outcome: str
    reason: str
    overall: float | None
    subscores: tuple[tuple[str, float], ...] = ()
    category: str = "general"
    prompt_context: str = ""
    sample: ControlledSample | None = None


def _category(flags: Mapping[str, Any]) -> str:
    chosen = [name for name in CATEGORY_FLAGS if flags.get(name) is True]
    return "+".join(chosen) if chosen else "general"


def _overall(meta: Mapping[str, Any]) -> float | None:
    """The operator's own overall rating; the blended score would double count the subscores."""
    raw = valid_rating(meta.get("user_rating_raw"))
    return raw if raw is not None else valid_rating(meta.get("user_rating"))


def _other_model(row: Mapping[str, Any], target: ResolvedModel) -> bool:
    try:
        saved = ModelIdentity.from_dict(
            row["metadata"]["frozen_experiment"]["snapshot"]["model_identity"]
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return bool(saved.sha256 and target.identity.sha256) and not strong_match(
        saved, target.identity
    )


def _prompt_context(row: Mapping[str, Any]) -> str:
    try:
        snapshot = row["metadata"]["frozen_experiment"]["snapshot"]
        prompt = snapshot["prompt_text"]
    except (KeyError, TypeError):
        return ""
    if not isinstance(prompt, str) or not prompt.strip():
        return ""
    return "ctx-" + digest([prompt, snapshot.get("negative_prompt_text") or ""])[:12]


def attribute_ratings(
    rows: Iterable[Mapping[str, Any]], target: ResolvedModel
) -> tuple[RatingAttribution, ...]:
    result = []
    for row in rows:
        identity = rating_identity(row)
        if identity is None:
            continue
        meta = row["metadata"]
        overall = _overall(meta)
        experiment, image = identity[0], identity[2]
        if valid_rating(meta.get("user_rating")) is None or overall is None:
            result.append(
                RatingAttribution(
                    experiment, image, OUTCOME_INVALID, "No valid 1-5 rating is saved.", None
                )
            )
            continue
        detail = LearningRecord.extract_rating_detail(meta)
        subscores = tuple(sorted(detail["subscores"].items()))
        category = _category(detail["context_flags"])
        context = _prompt_context(row)
        try:
            sample = controlled_sample(row, target)
        except (
            Exception
        ) as exc:  # any proof failure means "not controlled evidence", with its reason
            if _other_model(row, target):
                outcome, reason = OUTCOME_OTHER_MODEL, "Rated on a different checkpoint."
            else:
                outcome = OUTCOME_UNCONTROLLED
                reason = (
                    f"Missing execution evidence: {exc}." if isinstance(exc, KeyError) else str(exc)
                )
            result.append(
                RatingAttribution(
                    experiment, image, outcome, reason, overall, subscores, category, context
                )
            )
            continue
        result.append(
            RatingAttribution(
                experiment,
                image,
                OUTCOME_CONTROLLED,
                "",
                overall,
                subscores,
                category,
                context,
                sample,
            )
        )
    return tuple(sorted(result, key=lambda a: (a.experiment, a.image)))


def _label(value: Any) -> str:
    return json.dumps(value) if not isinstance(value, str) else value


def _summarize(
    key: tuple[str, str, str], members: list[RatingAttribution], target: ResolvedModel
) -> PreferenceGroup:
    setting, context, category = key
    by_value: dict[str, list[RatingAttribution]] = defaultdict(list)
    by_experiment: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for member in members:
        assert member.sample is not None and member.overall is not None
        label = json.dumps(member.sample.value, sort_keys=True)
        by_value[label].append(member)
        by_experiment[member.experiment][label].append(member.overall)
    summaries = []
    for label, items in by_value.items():
        ratings = [m.overall for m in items if m.overall is not None]
        subs: dict[str, list[float]] = defaultdict(list)
        for item in items:
            for name, score in item.subscores:
                subs[name].append(score)
        summaries.append(
            ValueSummary(
                json.loads(label),
                len(ratings),
                round(statistics.mean(ratings), 4),
                min(ratings),
                max(ratings),
                tuple(sorted((n, round(statistics.mean(v), 4)) for n, v in subs.items())),
            )
        )
    summaries.sort(key=lambda s: (-s.mean, json.dumps(s.value, sort_keys=True)))
    insufficiency = []
    if len(summaries) < 2:
        insufficiency.append("Fewer than two tested values have comparable ratings.")
    insufficiency.extend(
        f"{_label(s.value)}: {s.ratings} comparable rating(s); {MIN_RATINGS_PER_VALUE} needed."
        for s in sorted(summaries, key=lambda s: json.dumps(s.value, sort_keys=True))
        if s.ratings < MIN_RATINGS_PER_VALUE
    )
    leader: Any = None
    margin: float | None = None
    if insufficiency:
        verdict = VERDICT_INSUFFICIENT
    else:
        margin = round(summaries[0].mean - summaries[1].mean, 4)
        leaders = set()
        for experiment_means in by_experiment.values():
            means = sorted(
                ((statistics.mean(v), k) for k, v in experiment_means.items()),
                key=lambda m: (-m[0], m[1]),
            )
            if len(means) >= 2 and means[0][0] - means[1][0] >= MIN_LEADING_MARGIN:
                leaders.add(means[0][1])
        if len(leaders) > 1:
            verdict = VERDICT_COMPETING
        elif margin < MIN_LEADING_MARGIN:
            verdict = VERDICT_NO_CLEAR
        else:
            verdict = VERDICT_OBSERVED
            leader = summaries[0].value
    experiments = len(by_experiment)
    scope = f"{experiments} experiment(s), {len(members)} rating(s), prompt context {context}, category {category}"
    if verdict == VERDICT_INSUFFICIENT:
        statement = f"Insufficient evidence for {setting} ({scope}); no preference is inferred."
    elif verdict == VERDICT_COMPETING:
        statement = f"Experiments disagree about {setting} ({scope}); the observations compete."
    elif verdict == VERDICT_NO_CLEAR:
        statement = f"No clear rating difference for {setting} ({scope})."
    else:
        statement = (
            f"{setting}={_label(leader)} was rated higher (mean {summaries[0].mean:.2f} vs "
            f"{summaries[1].mean:.2f}) in this exact checkpoint and prompt context ({scope})."
        )
    return PreferenceGroup(
        group_id="pref-" + digest([target.identity.sha256, *key])[:12],
        setting=setting,
        prompt_context=context,
        category=category,
        experiments=experiments,
        ratings=len(members),
        values=tuple(summaries),
        verdict=verdict,
        leading_value=leader,
        margin=margin,
        statement=statement,
        limitation=(
            "Observed for these prompts and this exact checkpoint only; not a general preference, "
            "not a probability of improvement, and not evidence about other models or prompts."
        ),
        insufficiency=tuple(insufficiency),
    )


def summarize_preferences(
    attributions: Iterable[RatingAttribution], target: ResolvedModel
) -> PreferenceSummary:
    excluded: dict[str, int] = defaultdict(int)
    considered = 0
    candidates: list[RatingAttribution] = []
    for item in attributions:
        considered += 1
        if item.outcome != OUTCOME_CONTROLLED:
            excluded[item.outcome] += 1
        elif not item.prompt_context:
            excluded["unattributed_prompt"] += 1
        else:
            candidates.append(item)
    # An experiment contributes to a group only when its seeds agree and it compares at least two values there.
    grouped: dict[tuple[str, str, str], list[RatingAttribution]] = defaultdict(list)
    for item in candidates:
        assert item.sample is not None
        grouped[(item.sample.setting, item.prompt_context, item.category)].append(item)
    kept: dict[tuple[str, str, str], list[RatingAttribution]] = {}
    for key, members in grouped.items():
        per_experiment: dict[str, list[RatingAttribution]] = defaultdict(list)
        for member in members:
            per_experiment[member.experiment].append(member)
        usable: list[RatingAttribution] = []
        for experiment_members in per_experiment.values():
            values = {
                json.dumps(m.sample.value, sort_keys=True) for m in experiment_members if m.sample
            }
            seeds = {m.sample.seeds for m in experiment_members if m.sample}
            if len(values) < 2 or len(seeds) != 1:
                excluded["unpaired"] += len(experiment_members)
            else:
                usable.extend(experiment_members)
        if usable:
            kept[key] = usable
    groups = tuple(
        sorted(
            (_summarize(key, members, target) for key, members in kept.items()),
            key=lambda g: g.group_id,
        )
    )
    return PreferenceSummary(
        groups=groups,
        excluded=tuple(sorted(excluded.items())),
        considered=considered,
    )
