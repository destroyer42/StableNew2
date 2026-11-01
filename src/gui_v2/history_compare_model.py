"""Pure parent/child comparison (PR-HISTORY-610B): recorded lineage identity and typed recipe differences.

Everything here reads *recorded* evidence only - the frozen NJR stored with each job and values the backend separately
reported in the job result. A field that was never recorded stays "not recorded"; it is never filled from today's GUI,
defaults, Learning recommendations or a model profile. Nothing in this module touches Tk, files or the repository.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.gui_v2.history_iterate_model import _recorded_seed
from src.pipeline.history_variation_marker import is_history_variation
from src.pipeline.njr_core_v26 import NormalizedJobRecord

MAX_DIFFERENCE_ROWS = 600
MAX_VALUE_CHARS = 2000
_MAX_FLATTEN_DEPTH = 5


class ComparisonRefused(ValueError):
    """Content-safe refusal: the message never contains prompt text, paths or other record contents."""


class DifferenceState(str, Enum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    PARENT_ONLY = "only in parent"
    CHILD_ONLY = "only in child"
    NOT_RECORDED = "not recorded"
    NOT_COMPARABLE = "not comparable"


EVIDENCE_FROZEN = "frozen"  # saved in the immutable NJR (what was asked for)
EVIDENCE_OBSERVED = "observed"  # separately reported by the backend/result (what happened)

GROUP_ORDER = (
    "Job identity",
    "Prompts",
    "Model",
    "Sampling",
    "Dimensions",
    "Seed",
    "LoRA",
    "Embeddings",
    "Stages",
    "Editing",
    "Prompt transformations",
    "Provenance",
    "Other frozen settings",
    "Observed results",
)

_ABSENT: Any = object()


@dataclass(frozen=True)
class FieldDifference:
    group: str
    field: str
    state: DifferenceState
    parent: Any
    child: Any
    evidence: str = EVIDENCE_FROZEN

    @property
    def parent_recorded(self) -> bool:
        return self.parent is not _ABSENT

    @property
    def child_recorded(self) -> bool:
        return self.child is not _ABSENT


@dataclass(frozen=True)
class RecordedJob:
    """One persisted job after identity checks: the stored NJR mapping plus its hydrated form."""

    job_id: str
    record: Mapping[str, Any]
    njr: NormalizedJobRecord


def format_value(value: Any) -> str:
    if value is _ABSENT or value is None:
        return "not recorded"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        text = ", ".join(format_value(item) for item in value) if value else "(none)"
    elif isinstance(value, Mapping):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    else:
        text = str(value)
    if len(text) > MAX_VALUE_CHARS:
        return text[:MAX_VALUE_CHARS] + "… [display truncated]"
    return text


# --- identity / lineage -----------------------------------------------------------------------


def _status_value(entry: Any) -> str:
    status = getattr(entry, "status", None)
    return str(getattr(status, "value", status) or "")


def recorded_job(entry: Any, *, role: str) -> RecordedJob:
    """Validate one persisted entry as a completed, hydratable still-image job whose snapshot is its own."""

    if entry is None:
        raise ComparisonRefused(f"The {role} job is no longer in history.")
    job_id = str(getattr(entry, "job_id", "") or "")
    if _status_value(entry) != "completed":
        raise ComparisonRefused(f"The {role} job did not complete, so it cannot be compared.")
    snapshot = getattr(entry, "snapshot", None)
    record = snapshot.get("normalized_job") if isinstance(snapshot, Mapping) else None
    if not isinstance(record, Mapping) or not record:
        raise ComparisonRefused(
            f"The {role} job has no stored job snapshot (legacy or incomplete)."
        )
    try:
        njr = HistoryHandoffService().hydrate_njr_from_snapshot(snapshot)
    except Exception as exc:  # noqa: BLE001 - a corrupt snapshot is a visible refusal
        raise ComparisonRefused(f"The {role} job's stored snapshot cannot be read.") from exc
    if njr is None:
        raise ComparisonRefused(f"The {role} job's stored snapshot cannot be read.")
    if njr.job_id != job_id or record.get("job_id") != job_id:
        raise ComparisonRefused(
            f"The {role} job's stored snapshot belongs to a different job; refusing to mix identities."
        )
    if record.get("workload_kind") != "image":
        raise ComparisonRefused(f"The {role} job is not a still-image job.")
    return RecordedJob(job_id, record, njr)


def _source(record: Mapping[str, Any]) -> Mapping[str, Any]:
    source = record.get("source")
    return source if isinstance(source, Mapping) else {}


def recorded_parent_id(record: Mapping[str, Any]) -> str:
    """The child's frozen ``source.parent_job_id`` - the only relationship authority."""

    value = _source(record).get("parent_job_id")
    return str(value) if value else ""


def parent_artifact_claim(record: Mapping[str, Any]) -> str:
    value = _source(record).get("parent_artifact_id")
    return str(value) if value else ""


def verify_direct_lineage(
    parent: RecordedJob, child: RecordedJob, persisted: tuple[str | None, str | None] | None
) -> None:
    """Refuse unless the child's frozen source, its metadata claims and the persisted projection all agree."""

    source = _source(child.record)
    if parent.job_id == child.job_id or recorded_parent_id(child.record) != parent.job_id:
        raise ComparisonRefused("These records do not verify a direct parent/child relationship.")
    for metadata in (
        source.get("metadata"),
        (child.record.get("workload") or {}).get("metadata"),
        (child.record.get("provenance") or {}).get("metadata"),
    ):
        if not isinstance(metadata, Mapping):
            continue
        claimed = metadata.get("parent_job_id")
        if claimed and claimed != parent.job_id:
            raise ComparisonRefused("Recorded parent identity claims contradict one another.")
        artifact = metadata.get("parent_artifact_id")
        if artifact and artifact != source.get("parent_artifact_id"):
            raise ComparisonRefused("Recorded parent-artifact claims contradict one another.")
    if persisted is None or persisted != (
        parent.job_id,
        source.get("parent_artifact_id") or None,
    ):
        raise ComparisonRefused("Persisted lineage contradicts the stored snapshot.")


def lineage_kind(record: Mapping[str, Any]) -> str:
    """A content-safe label for how the child came from its parent."""

    source = _source(record)
    kind = str(source.get("kind") or "")
    metadata = source.get("metadata")
    provenance = record.get("provenance")
    provenance_meta = provenance.get("metadata") if isinstance(provenance, Mapping) else None
    if kind == "history_replay":
        if is_history_variation(metadata):
            return "Edited History variation"
        if isinstance(provenance_meta, Mapping) and provenance_meta.get("replay") is True:
            return "Exact History replay"
    if kind in {"reprocess", "image_edit"}:
        return "Review-derived image"
    return f"Derived image job ({kind or 'unknown source'})"


# --- typed recipe differences -----------------------------------------------------------------


def _get(mapping: Any, *path: str) -> Any:
    current = mapping
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return _ABSENT
        current = current[key]
    return _ABSENT if current is None else current


def _usable(value: Any, *, skip_empty_list: bool = False) -> bool:
    if value is _ABSENT or value is None or value == "":
        return False
    return not (skip_empty_list and value == [])


_CONFIG_SECTIONS = ("txt2img", "img2img", "svd_native", "train_lora")


def _enabled_stages(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    stages = record.get("stages")
    return (
        [s for s in stages if isinstance(s, Mapping) and s.get("enabled")]
        if isinstance(stages, list)
        else []
    )


def _effective(record: Mapping[str, Any], stage_attr: str | None, *config_keys: str) -> Any:
    """The NJR's own accessor precedence (first enabled stage, then config), but absent stays absent."""

    if stage_attr:
        for stage in _enabled_stages(record):
            value = stage.get(stage_attr)
            if _usable(value):
                return value
    config = _get(record, "workload", "config")
    if not isinstance(config, Mapping):
        return _ABSENT
    sections = [config] + [
        config[s] for s in _CONFIG_SECTIONS if isinstance(config.get(s), Mapping)
    ]
    for section in sections:
        for key in config_keys:
            value = section.get(key)
            if _usable(value, skip_empty_list=True):
                return value
    return _ABSENT


def _classify(parent: Any, child: Any) -> DifferenceState:
    if parent is _ABSENT and child is _ABSENT:
        return DifferenceState.NOT_RECORDED
    if parent is _ABSENT:
        return DifferenceState.CHILD_ONLY
    if child is _ABSENT:
        return DifferenceState.PARENT_ONLY
    numeric = (int, float)
    if isinstance(parent, bool) != isinstance(child, bool) or (
        type(parent) is not type(child)
        and not (isinstance(parent, numeric) and isinstance(child, numeric))
    ):
        return DifferenceState.NOT_COMPARABLE
    return DifferenceState.UNCHANGED if parent == child else DifferenceState.CHANGED


def _leaves(value: Any, prefix: str, out: dict[str, Any], depth: int = 0) -> None:
    if isinstance(value, Mapping) and value and depth < _MAX_FLATTEN_DEPTH:
        for key in sorted(value, key=str):
            _leaves(value[key], f"{prefix}.{key}" if prefix else str(key), out, depth + 1)
    elif value is not None:
        out[prefix] = value


class _Rows:
    def __init__(self, parent: Mapping[str, Any], child: Mapping[str, Any]) -> None:
        self.parent, self.child = parent, child
        self.rows: list[FieldDifference] = []

    def add(
        self, group: str, field: str, parent: Any, child: Any, *, evidence: str = EVIDENCE_FROZEN
    ) -> None:
        self.rows.append(
            FieldDifference(group, field, _classify(parent, child), parent, child, evidence)
        )

    def both(self, group: str, field: str, *path: str) -> None:
        self.add(group, field, _get(self.parent, *path), _get(self.child, *path))

    def effective(self, group: str, field: str, stage_attr: str | None, *keys: str) -> None:
        self.add(
            group,
            field,
            _effective(self.parent, stage_attr, *keys),
            _effective(self.child, stage_attr, *keys),
        )

    def mapping(self, group: str, prefix: str, parent: Any, child: Any) -> None:
        left: dict[str, Any] = {}
        right: dict[str, Any] = {}
        _leaves(parent if isinstance(parent, Mapping) else {}, "", left)
        _leaves(child if isinstance(child, Mapping) else {}, "", right)
        for key in sorted(left.keys() | right.keys()):
            self.add(group, f"{prefix}{key}", left.get(key, _ABSENT), right.get(key, _ABSENT))


def _stage_keys(record: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    keys: dict[str, Mapping[str, Any]] = {}
    seen: dict[str, int] = {}
    for stage in _enabled_stages(record):
        kind = str(stage.get("stage_type") or "unknown")
        seen[kind] = seen.get(kind, 0) + 1
        keys[kind if seen[kind] == 1 else f"{kind} #{seen[kind]}"] = stage
    return keys


def _tag_list(record: Mapping[str, Any]) -> Any:
    tags = _get(record, "provenance", "lora_tags")
    if tags is _ABSENT or not isinstance(tags, list):
        return _ABSENT
    return sorted(
        (f"{t.get('name')}:{t.get('weight')}" if isinstance(t, Mapping) else str(t)) for t in tags
    )


def _embeddings(record: Mapping[str, Any], key: str) -> Any:
    value = _get(record, "provenance", key)
    return sorted(str(v) for v in value) if isinstance(value, list) else _ABSENT


_CONSUMED_CONFIG_KEYS = {
    "model", "model_name", "base_model", "vae", "vae_name", "sampler_name", "sampler",
    "scheduler", "steps", "cfg_scale", "width", "height", "denoising_strength", "seed",
    "prompt_optimizer",
}  # fmt: skip


def _prompt_info(record: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    info = _get(record, "provenance", key)
    return info if isinstance(info, Mapping) else {}


def recipe_differences(
    parent: Mapping[str, Any], child: Mapping[str, Any]
) -> tuple[FieldDifference, ...]:
    """Typed, deterministically ordered differences between two frozen NJR mappings."""

    r = _Rows(parent, child)
    g = "Job identity"
    r.both(g, "Job ID", "job_id")
    r.both(g, "Source kind", "source", "kind")
    r.add(
        g,
        "Parent job",
        _get(parent, "source", "parent_job_id"),
        _get(child, "source", "parent_job_id"),
    )

    g = "Prompts"
    r.both(g, "Positive prompt", "workload", "positive_prompt")
    r.both(g, "Negative prompt", "workload", "negative_prompt")

    g = "Model"
    r.effective(g, "Checkpoint", "model", "model", "model_name", "base_model")
    r.both(g, "Backend", "workload", "backend_options", "image", "backend_id")
    r.effective(g, "VAE", "vae", "vae", "vae_name")
    r.both(
        g, "Model profile (as recorded)", "workload", "backend_options", "image", "model_profile"
    )

    g = "Sampling"
    r.effective(g, "Sampler", "sampler_name", "sampler_name", "sampler")
    r.effective(g, "Scheduler", "scheduler", "scheduler")
    r.effective(g, "Steps", "steps", "steps")
    r.effective(g, "CFG scale", "cfg_scale", "cfg_scale")

    g = "Dimensions"
    r.effective(g, "Width", None, "width")
    r.effective(g, "Height", None, "height")

    r.both("Seed", "Requested seed (frozen)", "provenance", "seed")

    g = "LoRA"
    r.add(g, "LoRA tags", _tag_list(parent), _tag_list(child))
    g = "Embeddings"
    r.add(
        g,
        "Positive embeddings",
        _embeddings(parent, "positive_embeddings"),
        _embeddings(child, "positive_embeddings"),
    )
    r.add(
        g,
        "Negative embeddings",
        _embeddings(parent, "negative_embeddings"),
        _embeddings(child, "negative_embeddings"),
    )

    g = "Stages"
    left_stages, right_stages = _stage_keys(parent), _stage_keys(child)
    r.add(g, "Enabled stage chain", list(left_stages) or _ABSENT, list(right_stages) or _ABSENT)
    ordered = list(left_stages) + [k for k in right_stages if k not in left_stages]
    for key in ordered:
        a, b = left_stages.get(key), right_stages.get(key)
        for attr in (
            "steps",
            "cfg_scale",
            "denoising_strength",
            "sampler_name",
            "scheduler",
            "model",
            "vae",
        ):
            r.add(
                g,
                f"{key}: {attr}",
                _get(a, attr) if a else _ABSENT,
                _get(b, attr) if b else _ABSENT,
            )
        r.mapping(g, f"{key}: ", a.get("extra") if a else None, b.get("extra") if b else None)

    g = "Editing"
    r.both(g, "Denoising strength (config)", "workload", "config", "denoising_strength")
    r.add(
        g,
        "Source images",
        _get(parent, "workload", "input_image_paths")
        if _usable(_get(parent, "workload", "input_image_paths"), skip_empty_list=True)
        else _ABSENT,
        _get(child, "workload", "input_image_paths")
        if _usable(_get(child, "workload", "input_image_paths"), skip_empty_list=True)
        else _ABSENT,
    )
    r.mapping(
        g, "", _get(parent, "workload", "intent_config"), _get(child, "workload", "intent_config")
    )

    g = "Prompt transformations"
    r.mapping(
        g,
        "Prompt optimizer: ",
        _get(parent, "workload", "config", "prompt_optimizer"),
        _get(child, "workload", "config", "prompt_optimizer"),
    )
    for stage in ("txt2img", "img2img"):
        a, b = (
            _prompt_info(parent, f"{stage}_prompt_info"),
            _prompt_info(child, f"{stage}_prompt_info"),
        )
        for attr in ("global_negative_applied", "global_negative_terms"):
            r.add(
                g,
                f"{stage}: {attr}",
                a.get(attr, _ABSENT) if a.get(attr) is not None else _ABSENT,
                b.get(attr, _ABSENT) if b.get(attr) is not None else _ABSENT,
            )
        r.add(
            g,
            f"{stage}: prompt rewritten",
            (a.get("original_prompt") != a.get("final_prompt")) if a else _ABSENT,
            (b.get("original_prompt") != b.get("final_prompt")) if b else _ABSENT,
        )

    g = "Provenance"
    r.both(g, "Source ID", "source", "id")
    r.both(g, "Source revision", "source", "revision")
    r.add(
        g,
        "Parent artifact claim recorded",
        bool(parent_artifact_claim(parent)) if _get(parent, "source") is not _ABSENT else _ABSENT,
        bool(parent_artifact_claim(child)) if _get(child, "source") is not _ABSENT else _ABSENT,
    )
    r.both(g, "NJR schema", "schema_version")

    g = "Other frozen settings"
    left_cfg: dict[str, Any] = {}
    right_cfg: dict[str, Any] = {}
    for record, out in ((parent, left_cfg), (child, right_cfg)):
        config = _get(record, "workload", "config")
        if not isinstance(config, Mapping):
            continue
        for key, value in config.items():
            if key in _CONSUMED_CONFIG_KEYS:
                continue
            if key in _CONFIG_SECTIONS and isinstance(value, Mapping):
                value = {k: v for k, v in value.items() if k not in _CONSUMED_CONFIG_KEYS}
            _leaves(value, str(key), out)
    for key in sorted(left_cfg.keys() | right_cfg.keys()):
        r.add(g, key, left_cfg.get(key, _ABSENT), right_cfg.get(key, _ABSENT))

    return _ordered(r.rows)


def _ordered(rows: Sequence[FieldDifference]) -> tuple[FieldDifference, ...]:
    position = {group: index for index, group in enumerate(GROUP_ORDER)}
    # sorted() is stable: fields keep the deterministic order they were built in within a group.
    return tuple(sorted(rows, key=lambda row: position.get(row.group, len(position))))


def observed_differences(
    parent_result: Any,
    child_result: Any,
    parent_size: tuple[int, int] | None,
    child_size: tuple[int, int] | None,
) -> tuple[FieldDifference, ...]:
    """Values the backend or the verified output file reported, kept apart from the frozen recipe."""

    def seed(result: Any) -> Any:
        value = _recorded_seed(result)
        return _ABSENT if value is None else value

    def size(value: tuple[int, int] | None) -> Any:
        return _ABSENT if value is None else f"{value[0]} x {value[1]}"

    group = "Observed results"
    pairs = (
        ("Actual seed (reported by backend)", seed(parent_result), seed(child_result)),
        ("Output image size (verified file)", size(parent_size), size(child_size)),
    )
    return tuple(
        FieldDifference(group, name, _classify(a, b), a, b, EVIDENCE_OBSERVED)
        for name, a, b in pairs
    )


def merge_differences(*groups: Sequence[FieldDifference]) -> tuple[FieldDifference, ...]:
    """Order the rows and bound the table; observed rows are kept ahead of the long tail of frozen config."""

    rows = _ordered([row for group in groups for row in group])
    if len(rows) <= MAX_DIFFERENCE_ROWS:
        return rows
    observed = [row for row in rows if row.evidence == EVIDENCE_OBSERVED]
    frozen = [row for row in rows if row.evidence != EVIDENCE_OBSERVED]
    return tuple(frozen[: MAX_DIFFERENCE_ROWS - len(observed)]) + tuple(observed)


def recipe_limitations(
    parent: RecordedJob,
    child: RecordedJob,
    rows: Sequence[FieldDifference],
    *,
    truncated: bool = False,
) -> list[str]:
    notes = ["Frozen settings show what was requested, not necessarily what the backend executed."]
    if parent.record.get("schema_version") != child.record.get("schema_version"):
        notes.append("The two jobs were stored under different job-record schema versions.")
    unrecorded = sum(1 for row in rows if row.state is DifferenceState.NOT_RECORDED)
    if unrecorded:
        notes.append(f"{unrecorded} field(s) were not recorded on either job and are not guessed.")
    if truncated:
        notes.append("Display budget reached; additional stored settings are omitted.")
    return notes


__all__ = [
    "EVIDENCE_FROZEN",
    "EVIDENCE_OBSERVED",
    "GROUP_ORDER",
    "MAX_DIFFERENCE_ROWS",
    "ComparisonRefused",
    "DifferenceState",
    "FieldDifference",
    "RecordedJob",
    "format_value",
    "lineage_kind",
    "merge_differences",
    "observed_differences",
    "parent_artifact_claim",
    "recipe_differences",
    "recipe_limitations",
    "recorded_job",
    "recorded_parent_id",
    "verify_direct_lineage",
]
