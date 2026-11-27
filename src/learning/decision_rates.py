"""LEARN-JOIN: what the owner keeps. Keep and favourite rates from review decisions, joined to each job's NJR.

Read-only and observational. A unit is one image (the SHA-256 of its bytes); its current decision is the last desktop
or phone disposition row for those bytes. Each decision is joined by job id to the job's immutable NJR snapshot, and
counted under the model that generated it and, within that model, under the slot values, LoRAs, embeddings, sampler,
steps, CFG, PromptPack and batch it was made with.

Nothing here writes anything, and nothing here feeds ``RecommendationEngine``, proposals, publication, Apply or any
setting (Learning invariant 5: observational evidence is manual-only). The data is not controlled: packs, models and
days are mixed, so a difference describes what was kept, not why.

This module is Tk-free and does no I/O of its own beyond :func:`read_current_decisions`.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist
from typing import Any

from src.utils.checkpoint_identity import checkpoint_key, checkpoint_stem

DISPOSITION_RECORD_KIND = "review_disposition"
#: The decisions that count; ``rework`` and ``cleared`` say nothing about keeping.
COUNTED = ("retain", "discard")
#: Both sides of a comparison need at least this many images before the interval is looked at.
MIN_IMAGES_PER_SIDE = 30
CONFIDENCE = 0.95
NOT_ENOUGH = "not enough yet"
UNKNOWN_MODEL = "(unknown model)"
_VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".gif")
_GENERATION_STAGES = ("txt2img", "img2img")

FACTOR_MODEL = "Model"
FACTOR_BATCH = "Batch"
FACTOR_LORA = "LoRA"
FACTOR_EMBEDDING = "Embedding"
FACTOR_SAMPLER = "Sampler"
FACTOR_STEPS = "Steps"
FACTOR_CFG = "CFG"
FACTOR_PACK = "PromptPack"
SLOT_PREFIX = "Slot: "


@dataclass(frozen=True)
class Decision:
    """The current Keep or Delete of one image."""

    digest: str
    disposition: str
    favorite: bool = False
    tags: tuple[str, ...] = ()
    job_id: str = ""
    model: str = ""
    video: bool = False
    batch: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class JobFacts:
    """The parts of one job's NJR a decision is counted under (no prompt text is kept)."""

    model: str = ""
    model_name: str = ""
    #: factor -> the options this job used (one for most factors; several LoRAs or embeddings).
    factors: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    batch_id: str = ""
    batch_name: str = ""


@dataclass(frozen=True)
class Counts:
    kept: int = 0
    deleted: int = 0
    favorites: int = 0
    tags: tuple[tuple[str, int], ...] = ()

    @property
    def decided(self) -> int:
        return self.kept + self.deleted


@dataclass(frozen=True)
class OptionRow:
    option: str
    counts: Counts
    #: What the comparison with the rest of the group shows, or ``NOT_ENOUGH``.
    difference: str = NOT_ENOUGH


@dataclass(frozen=True)
class Report:
    overall: Counts
    #: Current image decisions that found no job (no job id, or the job is not in the repository).
    unjoined: int
    #: Current Keep / Delete decisions on videos, which this report does not cover.
    videos: int
    #: Published images still without a decision; ``None`` when the publish ledger could not be read.
    undecided: int | None
    models: tuple[OptionRow, ...]
    #: model name -> factor -> rows.
    by_model: Mapping[str, Mapping[str, tuple[OptionRow, ...]]]
    batches: tuple[OptionRow, ...]

    @property
    def joined(self) -> int:
        return self.overall.decided - self.unjoined


# -- decisions ----------------------------------------------------------------------------------------------------


def current_decisions(rows: Iterable[Mapping[str, Any]]) -> list[Decision]:
    """The current Keep / Delete per image from evidence rows in append order.

    The last row for the bytes wins (Undo and Re-work remove the image from the count). A job id or batch stamp
    recorded by an earlier row for the same bytes is kept when the latest row lacks it.
    """

    latest: dict[str, Mapping[str, Any]] = {}
    job_ids: dict[str, str] = {}
    batches: dict[str, Mapping[str, Any]] = {}
    models: dict[str, str] = {}
    for row in rows:
        metadata = row.get("metadata") if isinstance(row, Mapping) else None
        if not isinstance(metadata, Mapping):
            continue
        if metadata.get("record_kind") != DISPOSITION_RECORD_KIND:
            continue
        digest = str(metadata.get("artifact_sha256") or "").strip().lower()
        if not digest:
            continue
        latest[digest] = row
        if job_id := str(metadata.get("source_job_id") or "").strip():
            job_ids[digest] = job_id
        if isinstance(batch := metadata.get("review_batch"), Mapping):
            batches[digest] = batch
        if model := str(row.get("primary_model") or "").strip():
            models[digest] = model
    found: list[Decision] = []
    for digest, row in latest.items():
        metadata = row["metadata"]
        disposition = str(metadata.get("review_disposition") or "")
        if disposition not in COUNTED:
            continue
        tags = metadata.get("review_tags")
        image_path = str(metadata.get("image_path") or "").lower()
        found.append(
            Decision(
                digest=digest,
                disposition=disposition,
                favorite=disposition == "retain" and metadata.get("review_favorite") is True,
                tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
                job_id=job_ids.get(digest, ""),
                model=models.get(digest, ""),
                video=image_path.endswith(_VIDEO_SUFFIXES),
                batch=batches.get(digest),
            )
        )
    return found


def read_current_decisions(records_path: str | os.PathLike[str]) -> list[Decision]:
    """Read the evidence file (read-only; unparseable lines are skipped; a missing file means no decisions)."""

    def rows() -> Iterable[Mapping[str, Any]]:
        path = Path(records_path)
        if not path.is_file():
            return
        with open(path, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if DISPOSITION_RECORD_KIND not in line:
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if isinstance(row, Mapping):
                    yield row

    return current_decisions(rows())


# -- job facts ----------------------------------------------------------------------------------------------------


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> str:
    if isinstance(value, bool) or value in (None, ""):
        return ""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return ""


def _embedding_weight(name: str, prompt: str) -> str:
    """The authored attention weight of ``name`` in a prompt: ``(name:1.2)`` or the tag form; else 1."""

    pattern = rf"\(\s*(?:<embedding:)?{re.escape(name)}>?\s*:\s*([+-]?\d+(?:\.\d+)?)\s*\)"
    match = re.search(pattern, prompt, re.IGNORECASE)
    return _number(match.group(1)) if match else "1"


def _generation_stage(stages: Any) -> Mapping[str, Any]:
    listed = [_mapping(stage) for stage in stages] if isinstance(stages, list) else []
    generating = [stage for stage in listed if stage.get("stage_type") in _GENERATION_STAGES]
    for stage in generating:
        if stage.get("enabled", True):
            return stage
    return generating[0] if generating else {}


def job_facts(snapshot: Mapping[str, Any]) -> JobFacts:
    """The recipe of a stored NJR snapshot (the ``normalized_job`` envelope or the bare record)."""

    job = _mapping(snapshot.get("normalized_job")) or snapshot
    stage = _generation_stage(job.get("stages"))
    workload = _mapping(job.get("workload"))
    config = _mapping(workload.get("config"))
    provenance = _mapping(job.get("provenance"))
    source = _mapping(job.get("source"))

    model_name = checkpoint_stem(stage.get("model") or config.get("model"))
    factors: dict[str, tuple[str, ...]] = {}

    def add(factor: str, *options: str) -> None:
        if chosen := tuple(dict.fromkeys(option for option in options if option)):
            factors[factor] = chosen

    slots = _mapping(provenance.get("matrix_slot_values"))
    for slot, value in slots.items():
        add(f"{SLOT_PREFIX}{slot}", " ".join(str(value).split()))

    loras = provenance.get("lora_tags")
    add(
        FACTOR_LORA,
        *(
            f"{tag.get('name')} @ {_number(tag.get('weight')) or '1'}"
            for tag in (map(_mapping, loras) if isinstance(loras, list) else ())
            if tag.get("name")
        ),
    )

    prompt_info = _mapping(provenance.get("txt2img_prompt_info"))
    embeddings: list[str] = []
    for key, prompt_key, label in (
        ("positive_embeddings", "final_prompt", ""),
        ("negative_embeddings", "final_negative_prompt", " (negative)"),
    ):
        names = provenance.get(key)
        prompt = str(prompt_info.get(prompt_key) or "")
        for name in names if isinstance(names, list) else ():
            if text := str(name).strip():
                embeddings.append(f"{text} @ {_embedding_weight(text, prompt)}{label}")
    add(FACTOR_EMBEDDING, *embeddings)

    sampler = str(stage.get("sampler_name") or config.get("sampler_name") or "")
    scheduler = str(stage.get("scheduler") or "")
    add(FACTOR_SAMPLER, f"{sampler} / {scheduler}" if sampler and scheduler else sampler)
    add(FACTOR_STEPS, _number(stage.get("steps")))
    add(FACTOR_CFG, _number(stage.get("cfg_scale")))
    if source.get("kind") == "prompt_pack":
        add(FACTOR_PACK, str(source.get("display_name") or source.get("id") or ""))

    batch = _mapping(_mapping(provenance.get("metadata")).get("batch"))
    return JobFacts(
        model=checkpoint_key(model_name),
        model_name=model_name,
        factors=factors,
        batch_id=str(batch.get("batch_id") or "") if batch.get("name") else "",
        batch_name=str(batch.get("name") or ""),
    )


# -- intervals ----------------------------------------------------------------------------------------------------


def _wilson(successes: int, total: int, z: float) -> tuple[float, float]:
    share = successes / total
    spread = z * z / total
    centre = (share + spread / 2) / (1 + spread)
    half = z * math.sqrt(share * (1 - share) / total + spread / (4 * total)) / (1 + spread)
    return centre - half, centre + half


def difference_interval(
    first: tuple[int, int], second: tuple[int, int], *, z: float
) -> tuple[float, float]:
    """Newcombe's score interval for ``p1 - p2``; each argument is ``(successes, total)`` with ``total > 0``."""

    p1, p2 = first[0] / first[1], second[0] / second[1]
    low1, high1 = _wilson(*first, z)
    low2, high2 = _wilson(*second, z)
    delta = p1 - p2
    return (
        delta - math.sqrt((p1 - low1) ** 2 + (high2 - p2) ** 2),
        delta + math.sqrt((high1 - p1) ** 2 + (p2 - low2) ** 2),
    )


def _z_for(comparisons: int) -> float:
    return NormalDist().inv_cdf(1 - (1 - CONFIDENCE) / (2 * max(1, comparisons)))


def _describe(option: Counts, rest: Counts, z: float) -> str:
    if option.decided < MIN_IMAGES_PER_SIDE or rest.decided < MIN_IMAGES_PER_SIDE:
        return NOT_ENOUGH
    parts = []
    for label, mine, theirs in (
        ("kept", option.kept, rest.kept),
        ("favourites", option.favorites, rest.favorites),
    ):
        low, high = difference_interval((mine, option.decided), (theirs, rest.decided), z=z)
        if low > 0 or high < 0:
            delta = 100 * (mine / option.decided - theirs / rest.decided)
            parts.append(f"{label} {delta:+.0f} pts ({100 * low:+.0f} to {100 * high:+.0f})")
    return "; ".join(parts) or NOT_ENOUGH


# -- aggregation --------------------------------------------------------------------------------------------------


class _Tally:
    def __init__(self) -> None:
        self.kept = self.deleted = self.favorites = 0
        self.tags: Counter[str] = Counter()

    def add(self, decision: Decision) -> None:
        if decision.disposition == "retain":
            self.kept += 1
            self.favorites += int(decision.favorite)
        else:
            self.deleted += 1
        self.tags.update(set(decision.tags))

    def counts(self) -> Counts:
        return Counts(self.kept, self.deleted, self.favorites, tuple(self.tags.most_common()))


def _rest(population: Counts, option: Counts) -> Counts:
    return Counts(
        population.kept - option.kept,
        population.deleted - option.deleted,
        population.favorites - option.favorites,
    )


def _rows(population: _Tally, options: Mapping[str, _Tally]) -> tuple[OptionRow, ...]:
    """Each option compared with the rest of its group, corrected for the number of comparisons made."""

    total = population.counts()
    counted = {name: tally.counts() for name, tally in options.items()}
    comparable = sum(
        1
        for counts in counted.values()
        if counts.decided >= MIN_IMAGES_PER_SIDE
        and total.decided - counts.decided >= MIN_IMAGES_PER_SIDE
    )
    z = _z_for(2 * comparable)  # keep and favourite rate are both tested
    return tuple(
        OptionRow(name, counts, _describe(counts, _rest(total, counts), z))
        for name, counts in sorted(
            counted.items(), key=lambda item: (-item[1].decided, item[0].lower())
        )
    )


def build_report(
    decisions: Sequence[Decision],
    facts: Mapping[str, JobFacts],
    *,
    published: Collection[str] | None = None,
) -> Report:
    """Aggregate current decisions. ``facts`` is keyed by job id; ``published`` holds published image digests."""

    images = [decision for decision in decisions if not decision.video]
    overall = _Tally()
    unjoined = 0
    model_population = _Tally()
    models: dict[str, _Tally] = {}
    names: dict[str, str] = {}
    model_totals: dict[str, _Tally] = {}
    factor_population: dict[tuple[str, str], _Tally] = {}
    factor_options: dict[tuple[str, str], dict[str, _Tally]] = {}
    batch_population = _Tally()
    batches: dict[str, _Tally] = {}
    batch_names: dict[str, str] = {}

    for decision in images:
        overall.add(decision)
        found = facts.get(decision.job_id)
        stamped = _mapping(decision.batch)
        batch_id = (found.batch_id if found else "") or str(stamped.get("batch_id") or "")
        if batch_id:
            batch_names.setdefault(
                batch_id, (found.batch_name if found else "") or str(stamped.get("name") or "")
            )
            batch_population.add(decision)
            batches.setdefault(batch_id, _Tally()).add(decision)
        if found is None:
            unjoined += 1
            continue
        key = found.model or checkpoint_key(decision.model)
        names.setdefault(key, found.model_name or checkpoint_stem(decision.model) or UNKNOWN_MODEL)
        model_population.add(decision)
        models.setdefault(key, _Tally()).add(decision)
        model_totals.setdefault(key, _Tally()).add(decision)
        for factor, options in found.factors.items():
            group = (key, factor)
            factor_population.setdefault(group, _Tally()).add(decision)
            listed = factor_options.setdefault(group, {})
            for option in options:
                listed.setdefault(option, _Tally()).add(decision)

    by_model: dict[str, dict[str, tuple[OptionRow, ...]]] = {}
    for (key, factor), options in sorted(factor_options.items()):
        # A LoRA or embedding is compared with the model's images without it, so the population is every image of
        # the model; other factors compare among the images that have the factor at all.
        population = (
            model_totals[key]
            if factor in (FACTOR_LORA, FACTOR_EMBEDDING)
            else factor_population[(key, factor)]
        )
        by_model.setdefault(names[key], {})[factor] = _rows(population, options)

    batch_labels: dict[str, str] = {}
    for batch_id in batches:
        name = batch_names.get(batch_id) or batch_id
        label = name if name not in batch_labels else f"{name} ({batch_id[:8]})"
        batch_labels[label] = batch_id

    undecided = None
    if published is not None:
        undecided = len(set(published) - {decision.digest for decision in decisions})
    return Report(
        overall=overall.counts(),
        unjoined=unjoined,
        videos=len(decisions) - len(images),
        undecided=undecided,
        models=_rows(model_population, {names[key]: tally for key, tally in models.items()}),
        by_model=by_model,
        batches=_rows(
            batch_population, {label: batches[bid] for label, bid in batch_labels.items()}
        ),
    )


def load_report(
    records_path: str | os.PathLike[str],
    read_snapshots: Callable[[Sequence[str]], Mapping[str, Mapping[str, Any]]],
    *,
    published: Collection[str] | None = None,
) -> Report:
    """Decisions, joined by job id through ``read_snapshots``, aggregated. Blocking; call from a worker."""

    decisions = read_current_decisions(records_path)
    job_ids = sorted({d.job_id for d in decisions if d.job_id and not d.video})
    facts = {job_id: job_facts(snapshot) for job_id, snapshot in read_snapshots(job_ids).items()}
    return build_report(decisions, facts, published=published)


# -- text ---------------------------------------------------------------------------------------------------------


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def tag_text(counts: Counts) -> str:
    return ", ".join(f"{tag} {count}" for tag, count in counts.tags)


def summary_lines(report: Report) -> list[str]:
    overall = report.overall
    lines = [
        f"{overall.decided} images decided: kept {overall.kept} ({percent(overall.kept, overall.decided)}), "
        f"deleted {overall.deleted}, favourites {overall.favorites} "
        f"({percent(overall.favorites, overall.decided)}).",
        f"Joined to a job: {report.joined} of {overall.decided}.",
    ]
    if report.undecided is not None:
        lines[-1] += f" Published and still undecided: {report.undecided}."
    if report.videos:
        lines[-1] += f" Video decisions (not included): {report.videos}."
    if overall.tags:
        lines.append(f"Reason tags: {tag_text(overall)}.")
    return lines
