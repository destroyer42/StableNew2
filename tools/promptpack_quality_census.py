"""Offline, read-only quality census of PromptPacks and saved generation settings.

WP-PACK-AUDIT-100. This tool NEVER writes to a PromptPack, preset,
`.default_preset` pointer, `settings.json`, or the Asset Registry's normal
cache. It inspects raw persisted JSON before typed loading/default-merge can
normalize away a quality problem, reuses `AssetRegistry`/Asset-120
compatibility profiles rather than re-inventing model-family inference, and
reuses the confirmed production alias contract in
`src.pipeline.config_normalizer` rather than inventing a second one.

No network. No A1111/Comfy connection. No process launch. No GPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from dataclasses import replace as dataclasses_replace
from pathlib import Path
from typing import Any

from src.assets import AssetKind, AssetRecord, AssetRegistry, CompatibilityStatus
from src.learning.lora_variant import extract_lora_tokens
from src.pipeline.config_normalizer import normalize_pipeline_config
from src.pipeline.model_synchronizer import normalize_model_name
from src.promptpacks.paths import resolve_prompt_pack_dir
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.utils.embedding_prompt_utils import (
    extract_embedding_token_strings,
    normalize_embedding_entries,
)

REPORT_SCHEMA_VERSION = 1
DEFAULT_PRESET_MARKER = ".default_preset"
SETTINGS_JSON_NAME = "settings.json"

# Confirmed production alias groups: src/pipeline/config_normalizer.py
# (normalize_stage_payload_config / normalize_pipeline_config) is the single
# authority reused here -- these are not invented from name similarity.
_STAGE_VALUE_ALIAS_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "txt2img": (
        ("model", "model_name", "sd_model"),
        ("vae", "vae_name", "sd_vae"),
        ("sampler_name", "sampler"),
        ("scheduler", "scheduler_name"),
        ("refiner_model_name", "refiner_checkpoint"),
    ),
    "img2img": (
        ("model", "model_name", "sd_model"),
        ("vae", "vae_name", "sd_vae"),
        ("sampler_name", "sampler"),
        ("scheduler", "scheduler_name"),
    ),
    "adetailer": (("adetailer_model", "ad_model"),),
    "upscale": (("upscaler", "upscaler_name", "upscaler_1"),),
}

_STAGE_BOOL_ALIAS_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "txt2img": (
        ("enable_hr", "hires_enabled"),
        ("refiner_enabled", "use_refiner"),
    ),
    "adetailer": (("enabled", "adetailer_enabled"),),
}

# (pipeline-section key, stage section name, stage section's own "enabled" key)
_CROSS_SECTION_STAGE_ENABLED_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("txt2img_enabled", "txt2img", "enabled"),
    ("img2img_enabled", "img2img", "enabled"),
    ("adetailer_enabled", "adetailer", "enabled"),
    ("upscale_enabled", "upscale", "enabled"),
    ("animatediff_enabled", "animatediff", "enabled"),
    ("video_workflow_enabled", "video_workflow", "enabled"),
)

# Objectively-impossible persisted values (not style/preference opinions).
_IMPOSSIBLE_VALUE_FIELDS: dict[str, tuple[str, ...]] = {
    "txt2img": ("width", "height", "steps", "cfg_scale"),
    "img2img": ("width", "height", "steps", "cfg_scale"),
    "upscale": ("steps",),
}


@dataclass(frozen=True)
class Finding:
    finding_code: str
    finding_class: str
    severity: str  # "error" | "warning" | "info"
    confidence: str  # "high" | "medium" | "low"
    source_type: str  # "promptpack" | "standalone_preset" | "default_preset" | "presets_dir"
    source_id: str
    slot_index: int | None = None
    stage: str | None = None
    field: str | None = None
    reference_name: str | None = None
    asset_kind: str | None = None
    expected_family: str | None = None
    observed_family: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _stage_dict(document: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _fingerprint_file(path: Path) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def fingerprint_paths(paths: Iterable[Path]) -> dict[str, dict[str, Any] | None]:
    """Read-only size/mtime fingerprint used to prove the census mutated nothing."""

    return {str(path): _fingerprint_file(path) for path in paths}


# ---------------------------------------------------------------------------
# Structural PromptPack census
# ---------------------------------------------------------------------------


def discover_pack_files(packs_dir: Path) -> list[Path]:
    """Every *.json in the canonical directory, including invalid ones.

    Deliberately does not reuse ``discover_native_prompt_packs`` (storage.py),
    which silently skips invalid documents -- the whole point of this census
    is to surface those. Dot-prefixed files are treated as audit/migration
    metadata, not PromptPacks.
    """

    if not packs_dir.is_dir():
        return []
    return sorted(
        (path for path in packs_dir.glob("*.json") if not path.name.startswith(".")),
        key=lambda item: item.name.lower(),
    )


def _census_slot_lora_entries(
    pack_id: str, slot_index: int, raw_slot: Mapping[str, Any], findings: list[Finding]
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    raw_loras = raw_slot.get("loras", [])
    if raw_loras is None:
        raw_loras = []
    if not isinstance(raw_loras, list):
        findings.append(
            Finding(
                "malformed_lora_container",
                "slot_normalization_risk",
                "warning",
                "high",
                "promptpack",
                pack_id,
                slot_index=slot_index,
                stage="loras",
                detail=f"loras is {type(raw_loras).__name__}, expected a list",
            )
        )
        return names
    for entry in raw_loras:
        if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
            findings.append(
                Finding(
                    "malformed_lora_entry",
                    "slot_normalization_risk",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=slot_index,
                    stage="loras",
                    detail="LoRA entry is not a [name, weight] pair",
                )
            )
            continue
        name = str(entry[0] or "").strip()
        if not name:
            findings.append(
                Finding(
                    "blank_lora_name",
                    "slot_normalization_risk",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=slot_index,
                    stage="loras",
                    detail="LoRA entry has a blank name",
                )
            )
            continue
        try:
            weight = float(entry[1])
        except (TypeError, ValueError):
            findings.append(
                Finding(
                    "nonnumeric_lora_weight",
                    "slot_normalization_risk",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=slot_index,
                    stage="loras",
                    reference_name=name,
                    detail=f"weight={entry[1]!r} is not numeric",
                )
            )
            continue
        if math.isnan(weight) or math.isinf(weight):
            findings.append(
                Finding(
                    "non_finite_lora_weight",
                    "slot_normalization_risk",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=slot_index,
                    stage="loras",
                    reference_name=name,
                    detail=f"weight={weight}",
                )
            )
            continue
        key = name.lower()
        if key in seen:
            findings.append(
                Finding(
                    "duplicate_structured_reference",
                    "slot_normalization_risk",
                    "info",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=slot_index,
                    stage="loras",
                    reference_name=name,
                    detail="LoRA referenced more than once in one slot",
                )
            )
        seen.add(key)
        names.append(name)
    return names


def _census_slot_embedding_entries(
    pack_id: str,
    slot_index: int,
    raw_slot: Mapping[str, Any],
    field_name: str,
    findings: list[Finding],
) -> list[str]:
    raw_values = raw_slot.get(field_name, [])
    if raw_values is None:
        raw_values = []
    if not isinstance(raw_values, list):
        findings.append(
            Finding(
                "malformed_embedding_container",
                "slot_normalization_risk",
                "warning",
                "high",
                "promptpack",
                pack_id,
                slot_index=slot_index,
                stage=field_name,
                detail=f"{field_name} is {type(raw_values).__name__}, expected a list",
            )
        )
        return []
    normalized = normalize_embedding_entries(raw_values)
    if len(normalized) < len([v for v in raw_values if v not in (None, "", [], {})]):
        findings.append(
            Finding(
                "malformed_embedding_entry",
                "slot_normalization_risk",
                "warning",
                "medium",
                "promptpack",
                pack_id,
                slot_index=slot_index,
                stage=field_name,
                detail="one or more entries were dropped by normalization",
            )
        )
    seen: set[str] = set()
    names: list[str] = []
    for name, _weight in normalized:
        key = name.lower()
        if key in seen:
            findings.append(
                Finding(
                    "duplicate_structured_reference",
                    "slot_normalization_risk",
                    "info",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=slot_index,
                    stage=field_name,
                    reference_name=name,
                    detail="embedding referenced more than once in one slot",
                )
            )
        seen.add(key)
        names.append(name)
    return names


def _census_raw_tokens_in_text(
    pack_id: str, slot_index: int, raw_slot: Mapping[str, Any], findings: list[Finding]
) -> None:
    for field_name in ("text", "negative"):
        text = str(raw_slot.get(field_name, "") or "")
        lora_tokens = extract_lora_tokens(text)
        embedding_tokens = extract_embedding_token_strings(text)
        if lora_tokens:
            findings.append(
                Finding(
                    "raw_asset_token_in_text",
                    "normalization_debt",
                    "info",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=slot_index,
                    stage=field_name,
                    detail=f"{len(lora_tokens)} raw <lora:...> token(s) in nominally pure text",
                )
            )
        if embedding_tokens:
            findings.append(
                Finding(
                    "raw_asset_token_in_text",
                    "normalization_debt",
                    "info",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=slot_index,
                    stage=field_name,
                    detail=f"{len(embedding_tokens)} raw embedding token(s) in nominally pure text",
                )
            )


@dataclass
class PackSlotEvidence:
    slot_index: int
    lora_names: list[str] = field(default_factory=list)
    embedding_names: list[str] = field(default_factory=list)
    empty: bool = False


def census_slots(pack_id: str, document: Mapping[str, Any], findings: list[Finding]) -> list[PackSlotEvidence]:
    pack_data = document.get("pack_data")
    if not isinstance(pack_data, dict):
        return []
    raw_slots = pack_data.get("slots")
    if not isinstance(raw_slots, list):
        return []

    seen_indexes: Counter[int] = Counter()
    evidence: list[PackSlotEvidence] = []
    renderable = 0

    for enum_index, raw_slot in enumerate(raw_slots):
        if not isinstance(raw_slot, dict):
            findings.append(
                Finding(
                    "invalid_slot_container",
                    "slot_normalization_risk",
                    "error",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=enum_index,
                    detail="slot is not a JSON object",
                )
            )
            continue

        raw_index = raw_slot.get("index", enum_index)
        if not isinstance(raw_index, int) or isinstance(raw_index, bool):
            findings.append(
                Finding(
                    "missing_or_nonint_slot_index",
                    "slot_normalization_risk",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=enum_index,
                    detail=f"raw index={raw_index!r}",
                )
            )
            raw_index = enum_index
        elif raw_index < 0:
            findings.append(
                Finding(
                    "negative_slot_index",
                    "slot_normalization_risk",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=enum_index,
                    detail=f"index={raw_index}",
                )
            )
        seen_indexes[raw_index] += 1

        lora_names = _census_slot_lora_entries(pack_id, enum_index, raw_slot, findings)
        embedding_names = _census_slot_embedding_entries(
            pack_id, enum_index, raw_slot, "positive_embeddings", findings
        )
        embedding_names += _census_slot_embedding_entries(
            pack_id, enum_index, raw_slot, "negative_embeddings", findings
        )
        _census_raw_tokens_in_text(pack_id, enum_index, raw_slot, findings)

        is_empty = not (
            str(raw_slot.get("text", "") or "").strip()
            or str(raw_slot.get("negative", "") or "").strip()
            or lora_names
            or embedding_names
            or str(raw_slot.get("template_id", "") or "").strip()
        )
        if is_empty:
            findings.append(
                Finding(
                    "empty_persisted_slot",
                    "slot_normalization_risk",
                    "info",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=enum_index,
                    detail="slot has no renderable content",
                )
            )
        else:
            renderable += 1

        evidence.append(PackSlotEvidence(raw_index, lora_names, embedding_names, is_empty))

    for index, count in sorted(seen_indexes.items()):
        if count > 1:
            findings.append(
                Finding(
                    "duplicate_slot_index",
                    "slot_normalization_risk",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    slot_index=index,
                    detail=f"index {index} used by {count} slots",
                )
            )

    if raw_slots and renderable == 0:
        findings.append(
            Finding(
                "zero_renderable_slots",
                "slot_normalization_risk",
                "warning",
                "high",
                "promptpack",
                pack_id,
                detail="pack has no renderable slot content",
            )
        )

    ordered_indexes = sorted(seen_indexes)
    if ordered_indexes and ordered_indexes != list(range(len(ordered_indexes))):
        findings.append(
            Finding(
                "sparse_or_noncanonical_slot_indexes",
                "slot_normalization_risk",
                "info",
                "medium",
                "promptpack",
                pack_id,
                detail=f"persisted indexes {ordered_indexes} are not a canonical 0..N-1 run",
            )
        )

    return evidence


def census_matrix(pack_id: str, document: Mapping[str, Any], findings: list[Finding]) -> None:
    pack_data = document.get("pack_data")
    if not isinstance(pack_data, dict) or "matrix" not in pack_data:
        return
    matrix = pack_data.get("matrix")
    if not isinstance(matrix, dict):
        findings.append(
            Finding(
                "invalid_matrix_shape",
                "matrix_structure",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail="pack_data.matrix is not an object",
            )
        )
        return

    # No mode-value check here: src/pipeline/prompt_pack_job_builder.py only
    # special-cases mode == "random" (explicit sampling); every other value,
    # including "fanout"/"sequential" and any typo, falls into the same
    # general expansion branch rather than raising. There is no unsupported-
    # mode condition in the current production contract to detect.

    limit = matrix.get("limit", 8)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        findings.append(
            Finding(
                "invalid_matrix_limit",
                "matrix_structure",
                "warning",
                "high",
                "promptpack",
                pack_id,
                detail=f"limit={limit!r}; contract requires a positive integer",
            )
        )

    slots = matrix.get("slots", [])
    if not isinstance(slots, list):
        findings.append(
            Finding(
                "invalid_matrix_shape",
                "matrix_structure",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail="matrix.slots is not a list",
            )
        )
        return

    seen_names: set[str] = set()
    for matrix_slot in slots:
        if not isinstance(matrix_slot, dict):
            findings.append(
                Finding(
                    "invalid_matrix_shape",
                    "matrix_structure",
                    "error",
                    "high",
                    "promptpack",
                    pack_id,
                    detail="matrix slot is not an object",
                )
            )
            continue
        name = str(matrix_slot.get("name", "") or "").strip()
        if not name:
            findings.append(
                Finding(
                    "blank_matrix_slot_name",
                    "matrix_structure",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    detail="matrix slot has a blank name",
                )
            )
        elif name.lower() in seen_names:
            findings.append(
                Finding(
                    "duplicate_matrix_slot_name",
                    "matrix_structure",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    reference_name=name,
                    detail="duplicate matrix slot name",
                )
            )
        seen_names.add(name.lower())

        values = matrix_slot.get("values", [])
        if not isinstance(values, list):
            findings.append(
                Finding(
                    "invalid_matrix_shape",
                    "matrix_structure",
                    "error",
                    "high",
                    "promptpack",
                    pack_id,
                    reference_name=name or None,
                    detail="matrix slot values is not a list",
                )
            )
            continue
        usable = [v for v in values if str(v or "").strip()]
        if bool(matrix.get("enabled")) and not usable:
            findings.append(
                Finding(
                    "enabled_matrix_slot_no_values",
                    "matrix_structure",
                    "warning",
                    "high",
                    "promptpack",
                    pack_id,
                    reference_name=name or None,
                    detail="matrix is enabled but this slot has zero usable values",
                )
            )


# ---------------------------------------------------------------------------
# One PromptPack document
# ---------------------------------------------------------------------------


@dataclass
class PackCensusResult:
    pack_id: str
    path: Path
    valid: bool
    document: dict[str, Any] | None
    slot_evidence: list[PackSlotEvidence] = field(default_factory=list)


def census_pack_file(path: Path, findings: list[Finding]) -> PackCensusResult:
    pack_id = path.stem
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        findings.append(
            Finding(
                "unreadable_file",
                "format_schema",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail=str(exc),
            )
        )
        return PackCensusResult(pack_id, path, False, None)

    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        findings.append(
            Finding(
                "malformed_json",
                "format_schema",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail=str(exc),
            )
        )
        return PackCensusResult(pack_id, path, False, None)

    if not isinstance(document, dict):
        findings.append(
            Finding(
                "non_object_top_level",
                "format_schema",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail=f"top-level JSON is {type(document).__name__}",
            )
        )
        return PackCensusResult(pack_id, path, False, None)

    version = document.get("schema_version")
    if version is None:
        findings.append(
            Finding(
                "unversioned_schema",
                "format_schema",
                "info",
                "high",
                "promptpack",
                pack_id,
                detail="no schema_version; treated as legacy/unversioned",
            )
        )
    elif version != CURRENT_PROMPTPACK_SCHEMA_VERSION:
        findings.append(
            Finding(
                "unsupported_schema_version",
                "format_schema",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail=f"schema_version={version!r}; expected {CURRENT_PROMPTPACK_SCHEMA_VERSION}",
            )
        )

    pack_data = document.get("pack_data")
    if not isinstance(pack_data, dict):
        findings.append(
            Finding(
                "invalid_pack_data",
                "format_schema",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail="pack_data must be an object",
            )
        )
        return PackCensusResult(pack_id, path, False, document)

    slots = pack_data.get("slots", [])
    if not isinstance(slots, list):
        findings.append(
            Finding(
                "invalid_slots_container",
                "format_schema",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail="pack_data.slots must be a list",
            )
        )
        return PackCensusResult(pack_id, path, False, document)

    preset_data = document.get("preset_data", {})
    if not isinstance(preset_data, dict):
        findings.append(
            Finding(
                "invalid_preset_data",
                "format_schema",
                "error",
                "high",
                "promptpack",
                pack_id,
                detail="preset_data must be an object",
            )
        )
        return PackCensusResult(pack_id, path, False, document)

    stated_name = pack_data.get("name")
    if isinstance(stated_name, str) and stated_name.strip() and stated_name.strip() != pack_id:
        findings.append(
            Finding(
                "pack_name_filestem_mismatch",
                "identity_duplication",
                "info",
                "high",
                "promptpack",
                pack_id,
                detail=f"pack_data.name={stated_name!r} differs from file stem",
            )
        )

    slot_evidence = census_slots(pack_id, document, findings)
    census_matrix(pack_id, document, findings)
    return PackCensusResult(pack_id, path, True, document, slot_evidence)


def census_cross_pack_identity(results: list[PackCensusResult], findings: list[Finding]) -> None:
    names_seen: dict[str, list[str]] = {}
    content_hashes: dict[str, list[str]] = {}
    for result in results:
        if not result.document:
            continue
        pack_data = result.document.get("pack_data")
        name = None
        if isinstance(pack_data, dict):
            raw_name = pack_data.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                name = raw_name.strip().lower()
        if name:
            names_seen.setdefault(name, []).append(result.pack_id)

        canonical = json.dumps(
            {"pack_data": pack_data if isinstance(pack_data, dict) else {}},
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        content_hashes.setdefault(digest, []).append(result.pack_id)

    for name, pack_ids in names_seen.items():
        if len(pack_ids) > 1:
            for pack_id in pack_ids:
                findings.append(
                    Finding(
                        "duplicate_native_pack_name",
                        "identity_duplication",
                        "info",
                        "high",
                        "promptpack",
                        pack_id,
                        detail=f"pack_data.name={name!r} shared by {sorted(pack_ids)}",
                    )
                )

    for pack_ids in content_hashes.values():
        if len(pack_ids) > 1:
            for pack_id in pack_ids:
                findings.append(
                    Finding(
                        "duplicate_pack_contents",
                        "identity_duplication",
                        "info",
                        "high",
                        "promptpack",
                        pack_id,
                        detail=f"identical pack_data to {sorted(set(pack_ids) - {pack_id})}",
                    )
                )


# ---------------------------------------------------------------------------
# Saved generation settings (preset_data / standalone presets)
# ---------------------------------------------------------------------------


def _alias_conflict_values(raw: Mapping[str, Any], keys: tuple[str, ...], *, as_bool: bool) -> list[tuple[str, Any]] | None:
    present = [(key, raw[key]) for key in keys if key in raw and not _is_blank(raw[key])]
    if len(present) < 2:
        return None
    distinct_count = (
        len({bool(value) for _, value in present})
        if as_bool
        else len({str(value).strip() for _, value in present})
    )
    return present if distinct_count > 1 else None


def census_saved_settings(
    source_type: str, source_id: str, preset_data: Mapping[str, Any], findings: list[Finding]
) -> None:
    if not isinstance(preset_data, Mapping):
        findings.append(
            Finding(
                "invalid_preset_container",
                "saved_setting_contradiction",
                "error",
                "high",
                source_type,
                source_id,
                detail="saved settings container is not an object",
            )
        )
        return

    for stage, groups in _STAGE_VALUE_ALIAS_GROUPS.items():
        stage_dict = _stage_dict(preset_data, stage)
        # Also consider top-level keys merged into this stage, mirroring
        # normalize_stage_payload_config's _COMMON_TOP_LEVEL_KEYS merge.
        merged = {**{k: v for k, v in preset_data.items() if k in {key for group in groups for key in group}}, **stage_dict}
        for group in groups:
            conflict = _alias_conflict_values(merged, group, as_bool=False)
            if conflict:
                findings.append(
                    Finding(
                        "saved_setting_alias_conflict",
                        "saved_setting_contradiction",
                        "warning",
                        "high",
                        source_type,
                        source_id,
                        stage=stage,
                        field="/".join(group),
                        detail="; ".join(f"{k}={v!r}" for k, v in conflict),
                    )
                )

    for stage, groups in _STAGE_BOOL_ALIAS_GROUPS.items():
        stage_dict = _stage_dict(preset_data, stage)
        # Production accepts these booleans at the top level too (e.g.
        # hires_enabled/enable_hr, refiner_enabled/use_refiner) before
        # merging into the stage section; a contradiction split across that
        # boundary must still be visible.
        merged = {**{k: v for k, v in preset_data.items() if k in {key for group in groups for key in group}}, **stage_dict}
        for group in groups:
            conflict = _alias_conflict_values(merged, group, as_bool=True)
            if conflict:
                findings.append(
                    Finding(
                        "saved_setting_stage_contradiction",
                        "saved_setting_contradiction",
                        "warning",
                        "high",
                        source_type,
                        source_id,
                        stage=stage,
                        field="/".join(group),
                        detail="; ".join(f"{k}={v!r}" for k, v in conflict),
                    )
                )

    pipeline = _stage_dict(preset_data, "pipeline")
    for pipeline_key, section, section_key in _CROSS_SECTION_STAGE_ENABLED_PAIRS:
        if pipeline_key not in pipeline:
            continue
        section_dict = _stage_dict(preset_data, section)
        if section_key not in section_dict:
            continue
        if bool(pipeline[pipeline_key]) != bool(section_dict[section_key]):
            findings.append(
                Finding(
                    "saved_setting_stage_contradiction",
                    "saved_setting_contradiction",
                    "warning",
                    "high",
                    source_type,
                    source_id,
                    stage=section,
                    field=f"pipeline.{pipeline_key}/{section}.{section_key}",
                    detail=f"pipeline.{pipeline_key}={pipeline[pipeline_key]!r} vs {section}.{section_key}={section_dict[section_key]!r}",
                )
            )

    hires_fix = _stage_dict(preset_data, "hires_fix")
    txt2img = _stage_dict(preset_data, "txt2img")
    txt2img_hires = None
    for key in ("hires_enabled", "enable_hr"):
        if key in txt2img:
            txt2img_hires = bool(txt2img[key])
            break
    if "enabled" in hires_fix and txt2img_hires is not None and bool(hires_fix["enabled"]) != txt2img_hires:
        findings.append(
            Finding(
                "saved_setting_stage_contradiction",
                "saved_setting_contradiction",
                "warning",
                "high",
                source_type,
                source_id,
                stage="hires_fix",
                field="hires_fix.enabled/txt2img.hires_enabled",
                detail=f"hires_fix.enabled={hires_fix['enabled']!r} vs txt2img hires flag={txt2img_hires!r}",
            )
        )

    for stage, numeric_fields in _IMPOSSIBLE_VALUE_FIELDS.items():
        stage_dict = _stage_dict(preset_data, stage)
        for key in numeric_fields:
            if key not in stage_dict or _is_blank(stage_dict[key]):
                continue
            raw_value = stage_dict[key]
            try:
                numeric = float(raw_value)
            except (TypeError, ValueError):
                findings.append(
                    Finding(
                        "invalid_numeric_value",
                        "saved_setting_contradiction",
                        "error",
                        "high",
                        source_type,
                        source_id,
                        stage=stage,
                        field=key,
                        detail=f"{key}={raw_value!r} is not numeric",
                    )
                )
                continue
            if math.isnan(numeric) or math.isinf(numeric):
                findings.append(
                    Finding(
                        "invalid_numeric_value",
                        "saved_setting_contradiction",
                        "error",
                        "high",
                        source_type,
                        source_id,
                        stage=stage,
                        field=key,
                        detail=f"{key}={numeric}",
                    )
                )
                continue
            if key in ("width", "height", "steps") and numeric <= 0:
                findings.append(
                    Finding(
                        "impossible_value",
                        "saved_setting_contradiction",
                        "error",
                        "high",
                        source_type,
                        source_id,
                        stage=stage,
                        field=key,
                        detail=f"{key}={numeric} is not a usable value",
                    )
                )
            elif key == "cfg_scale" and numeric < 0:
                findings.append(
                    Finding(
                        "impossible_value",
                        "saved_setting_contradiction",
                        "error",
                        "high",
                        source_type,
                        source_id,
                        stage=stage,
                        field=key,
                        detail=f"{key}={numeric} is negative",
                    )
                )

    style_lora = preset_data.get("style_lora")
    if style_lora is not None and not isinstance(style_lora, Mapping):
        findings.append(
            Finding(
                "invalid_style_lora_container",
                "saved_setting_contradiction",
                "warning",
                "high",
                source_type,
                source_id,
                field="style_lora",
                detail="style_lora is present but not an object",
            )
        )


def census_standalone_presets(
    presets_dir: Path, findings: list[Finding]
) -> tuple[list[tuple[str, dict[str, Any]]], list[Path]]:
    """Return (name, raw preset dict) pairs plus every file examined (for fingerprinting)."""

    if not presets_dir.is_dir():
        return [], []
    examined: list[Path] = []
    results: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(presets_dir.glob("*.json"), key=lambda item: item.name.lower()):
        examined.append(path)
        if path.name == SETTINGS_JSON_NAME:
            findings.append(
                Finding(
                    "settings_json_surfaced_as_preset",
                    "saved_setting_contradiction",
                    "warning",
                    "high",
                    "presets_dir",
                    path.stem,
                    detail=(
                        "settings.json matches the same *.json discovery glob as generation "
                        "presets; it is not audited as a generation recipe"
                    ),
                )
            )
            continue
        try:
            raw_text = path.read_text(encoding="utf-8")
            document = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(
                Finding(
                    "malformed_json",
                    "format_schema",
                    "error",
                    "high",
                    "standalone_preset",
                    path.stem,
                    detail=str(exc),
                )
            )
            continue
        if not isinstance(document, dict):
            findings.append(
                Finding(
                    "non_object_top_level",
                    "format_schema",
                    "error",
                    "high",
                    "standalone_preset",
                    path.stem,
                    detail=f"top-level JSON is {type(document).__name__}",
                )
            )
            continue
        census_saved_settings("standalone_preset", path.stem, document, findings)
        results.append((path.stem, document))
    return results, examined


def census_default_preset(presets_dir: Path, findings: list[Finding]) -> Path | None:
    marker = presets_dir / DEFAULT_PRESET_MARKER
    if not marker.is_file():
        return None
    try:
        name = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        findings.append(
            Finding(
                "unreadable_default_preset_marker",
                "saved_setting_contradiction",
                "warning",
                "high",
                "default_preset",
                "(marker)",
                detail=str(exc),
            )
        )
        return marker
    if name and not (presets_dir / f"{name}.json").exists():
        findings.append(
            Finding(
                "dangling_default_preset",
                "saved_setting_contradiction",
                "warning",
                "high",
                "default_preset",
                name or "(blank)",
                detail=f".default_preset points at {name!r}, which does not exist",
            )
        )
    return marker


# ---------------------------------------------------------------------------
# Asset reference resolution + family compatibility (Asset-120 consumption)
# ---------------------------------------------------------------------------


@dataclass
class AssetIndex:
    by_kind: dict[AssetKind, dict[str, list[AssetRecord]]] = field(default_factory=dict)

    def resolve(self, raw_name: str, kind: AssetKind) -> tuple[str, AssetRecord | None]:
        normalized = normalize_model_name(raw_name)
        if not normalized:
            return "not_applicable", None
        bucket = self.by_kind.get(kind, {})
        records = bucket.get(normalized, [])
        if not records:
            return "missing_file_backed_asset", None
        if len(records) > 1:
            return "ambiguous_same_name", None
        record = records[0]
        # Scope the duplicate check to this reference's own kind: a shared
        # digest with an unrelated-kind asset (e.g. a checkpoint and a LoRA
        # that happen to share bytes) is not a duplicate alias of this
        # reference.
        same_kind_locations = [location for location in record.locations if location.kind is kind]
        classification = (
            "resolved_duplicate_bytes" if len(same_kind_locations) > 1 else "resolved_unique"
        )
        return classification, record


def build_asset_index(registry: AssetRegistry) -> AssetIndex:
    index = AssetIndex()
    for kind in (AssetKind.CHECKPOINT, AssetKind.VAE, AssetKind.LORA, AssetKind.EMBEDDING):
        bucket: dict[str, list[AssetRecord]] = {}
        for record in registry.snapshot.records_for(kind):
            names: set[str] = set()
            for location in record.locations:
                if location.kind is kind:
                    normalized = normalize_model_name(location.display_name)
                    if normalized:
                        names.add(normalized)
            for name in names:
                bucket.setdefault(name, []).append(record)
        index.by_kind[kind] = bucket
    return index


def _family_finding(
    source_type: str,
    source_id: str,
    stage: str | None,
    reference_name: str,
    asset_kind: str,
    base_status: CompatibilityStatus,
    base_family: str | None,
    ref_status: CompatibilityStatus,
    ref_family: str | None,
) -> Finding:
    if base_status is CompatibilityStatus.CONFLICTING or ref_status is CompatibilityStatus.CONFLICTING:
        code, klass, severity = "family_evidence_conflicting", "family_compatibility", "warning"
    elif base_status is CompatibilityStatus.UNKNOWN or ref_status is CompatibilityStatus.UNKNOWN:
        code, klass, severity = "family_unknown", "family_compatibility", "info"
    elif base_family == ref_family:
        code, klass, severity = "family_compatible", "family_compatibility", "info"
    else:
        code, klass, severity = "family_mismatch", "family_compatibility", "warning"
    return Finding(
        code,
        klass,
        severity,
        "high",
        source_type,
        source_id,
        stage=stage,
        reference_name=reference_name,
        asset_kind=asset_kind,
        expected_family=base_family,
        observed_family=ref_family,
    )


def census_asset_and_family_references(
    source_type: str,
    source_id: str,
    *,
    checkpoint_name: str | None,
    vae_name: str | None,
    refiner_name: str | None,
    refiner_enabled: bool,
    lora_names: Iterable[str],
    embedding_names: Iterable[str],
    asset_index: AssetIndex | None,
    findings: list[Finding],
) -> None:
    other_refs: list[tuple[str, AssetKind, str, bool]] = [
        *(((vae_name, AssetKind.VAE, "vae", False),) if vae_name else ()),
        *(((refiner_name, AssetKind.CHECKPOINT, "refiner_checkpoint", not refiner_enabled),) if refiner_name else ()),
        *((name, AssetKind.LORA, "lora", False) for name in lora_names),
        *((name, AssetKind.EMBEDDING, "embedding", False) for name in embedding_names),
    ]

    if asset_index is None:
        all_refs = other_refs + (
            [(checkpoint_name, AssetKind.CHECKPOINT, "checkpoint", False)] if checkpoint_name else []
        )
        for name, _kind, label, _dormant in all_refs:
            findings.append(
                Finding(
                    "offline_unverified",
                    "asset_resolution",
                    "info",
                    "low",
                    source_type,
                    source_id,
                    reference_name=name,
                    asset_kind=label,
                    detail="Asset Registry/WebUI root unavailable; coverage unknown",
                )
            )
        return

    def _resolve_and_report(name: str, kind: AssetKind, asset_kind_label: str, stage: str | None) -> AssetRecord | None:
        classification, record = asset_index.resolve(name, kind)
        severity = "warning" if classification == "missing_file_backed_asset" or classification == "ambiguous_same_name" else "info"
        findings.append(
            Finding(
                classification,
                "asset_resolution",
                severity,
                "high" if classification != "not_applicable" else "low",
                source_type,
                source_id,
                stage=stage,
                reference_name=name,
                asset_kind=asset_kind_label,
            )
        )
        return record

    if not checkpoint_name:
        # No explicit base checkpoint reference at all: still resolve every
        # other reference individually, but compatibility cannot be
        # adjudicated without a base -- one pack-level classification, not
        # one per reference.
        for name, kind, label, _dormant in other_refs:
            _resolve_and_report(name, kind, label, None)
        if other_refs:
            findings.append(
                Finding(
                    "no_explicit_base_context",
                    "family_compatibility",
                    "info",
                    "high",
                    source_type,
                    source_id,
                    detail="no explicit base checkpoint reference; family compatibility not adjudicated",
                )
            )
        return

    checkpoint_record = _resolve_and_report(checkpoint_name, AssetKind.CHECKPOINT, "checkpoint", "txt2img")
    if checkpoint_record is None or checkpoint_record.compatibility is None:
        # Checkpoint reference present but did not resolve to one asset with
        # a profile (missing/ambiguous/no-coverage): its own asset_resolution
        # finding already recorded that; there is no base to compare against.
        for name, kind, label, _dormant in other_refs:
            _resolve_and_report(name, kind, label, "txt2img" if kind is AssetKind.VAE else None)
        return

    base_profile = checkpoint_record.compatibility
    base_status = base_profile.status
    base_family = base_profile.family.value if base_profile.family else None

    for name, kind, label, dormant in other_refs:
        record = _resolve_and_report(name, kind, label, "txt2img" if kind is AssetKind.VAE else None)
        if record is None or record.compatibility is None:
            continue
        finding = _family_finding(
            source_type,
            source_id,
            "refiner" if dormant else None,
            name,
            label,
            base_status,
            base_family,
            record.compatibility.status,
            record.compatibility.family.value if record.compatibility.family else None,
        )
        if dormant and finding.finding_code == "family_mismatch":
            finding = dataclasses_replace(finding, severity="info", detail="dormant: refiner is disabled")
        findings.append(finding)


def _first_alias_value(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if not _is_blank(value):
            return str(value).strip()
    return None


def _first_bool_alias_value(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        if key in mapping and not _is_blank(mapping[key]):
            return bool(mapping[key])
    return None


def census_pack_references(
    pack_id: str,
    document: Mapping[str, Any],
    slot_evidence: list[PackSlotEvidence],
    asset_index: AssetIndex | None,
    findings: list[Finding],
) -> None:
    preset_data = document.get("preset_data")
    preset_data = preset_data if isinstance(preset_data, dict) else {}
    # Reuse production's own precedence (including accepted top-level
    # aliases merged in before the nested txt2img section, per
    # src/pipeline/config_normalizer.py's _COMMON_TOP_LEVEL_KEYS) rather than
    # maintaining a second, narrower alias implementation that only looked
    # at the nested section.
    normalized_pipeline = normalize_pipeline_config(preset_data)
    normalized_txt2img = (
        normalized_pipeline.get("txt2img", {}) if isinstance(normalized_pipeline, dict) else {}
    )
    checkpoint_name = _first_alias_value(normalized_txt2img, ("model",))
    vae_name = _first_alias_value(normalized_txt2img, ("vae",))
    refiner_name = _first_alias_value(normalized_txt2img, ("refiner_model_name",))
    refiner_enabled = bool(_first_bool_alias_value(normalized_txt2img, ("refiner_enabled",)))

    lora_names: list[str] = []
    embedding_names: list[str] = []
    seen_loras: set[str] = set()
    seen_embeddings: set[str] = set()
    for slot in slot_evidence:
        for name in slot.lora_names:
            if name.lower() not in seen_loras:
                seen_loras.add(name.lower())
                lora_names.append(name)
        for name in slot.embedding_names:
            if name.lower() not in seen_embeddings:
                seen_embeddings.add(name.lower())
                embedding_names.append(name)

    census_asset_and_family_references(
        "promptpack",
        pack_id,
        checkpoint_name=checkpoint_name,
        vae_name=vae_name,
        refiner_name=refiner_name,
        refiner_enabled=refiner_enabled,
        lora_names=lora_names,
        embedding_names=embedding_names,
        asset_index=asset_index,
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Report aggregation
# ---------------------------------------------------------------------------


@dataclass
class CensusReport:
    schema_version: int
    source_sha: str
    packs_dir: str
    presets_dir: str | None
    webui_root: str | None
    asset_coverage_available: bool
    pack_files_examined: int
    standalone_presets_examined: int
    findings: list[Finding]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_sha": self.source_sha,
            "packs_dir": self.packs_dir,
            "presets_dir": self.presets_dir,
            "webui_root": self.webui_root,
            "asset_coverage_available": self.asset_coverage_available,
            "pack_files_examined": self.pack_files_examined,
            "standalone_presets_examined": self.standalone_presets_examined,
            "findings": [f.as_dict() for f in sorted(
                self.findings,
                key=lambda item: (item.source_type, item.source_id, item.finding_code, item.slot_index or -1),
            )],
        }

    def summary_counts(self) -> dict[str, int]:
        return dict(Counter(f.finding_code for f in self.findings))

    def counts_by_class(self) -> dict[str, int]:
        return dict(Counter(f.finding_class for f in self.findings))


def _has_usable_supported_root(registry: AssetRegistry) -> bool:
    """Coverage requires an actually-usable supported source root.

    A nonempty configured webui_root is not sufficient: a nonexistent path,
    or one with none of the supported model/LoRA/embedding/etc. directories
    present, yields an empty registry that would otherwise make every real
    reference look like a definite miss instead of unverifiable coverage.
    Never creates a directory merely to test this.
    """

    if registry.webui_root is None:
        return False
    return any(root.is_dir() for _kind, root in registry.supported_roots())


def run_census(
    *,
    packs_dir: Path,
    presets_dir: Path | None,
    webui_root: str | None,
    asset_cache_path: Path,
    source_sha: str = "",
) -> CensusReport:
    findings: list[Finding] = []

    pack_files = discover_pack_files(packs_dir)
    results = [census_pack_file(path, findings) for path in pack_files]
    census_cross_pack_identity(results, findings)

    asset_index: AssetIndex | None = None
    asset_coverage_available = False
    if webui_root:
        registry = AssetRegistry(webui_root, cache_path=asset_cache_path)
        if _has_usable_supported_root(registry):
            registry.refresh()
            asset_index = build_asset_index(registry)
            asset_coverage_available = True

    for result in results:
        if result.document is not None:
            census_pack_references(result.pack_id, result.document, result.slot_evidence, asset_index, findings)
            preset_data = result.document.get("preset_data")
            if isinstance(preset_data, dict) and preset_data:
                census_saved_settings("promptpack", result.pack_id, preset_data, findings)

    standalone_presets_examined_count = 0
    if presets_dir is not None:
        _standalone_presets, examined_preset_files = census_standalone_presets(presets_dir, findings)
        census_default_preset(presets_dir, findings)
        # Coverage means every applicable file actually looked at, including
        # malformed/non-object ones -- not just the ones that parsed cleanly.
        # settings.json is excluded: it is flagged separately and was never a
        # generation preset to begin with.
        standalone_presets_examined_count = len(
            [path for path in examined_preset_files if path.name != SETTINGS_JSON_NAME]
        )

    return CensusReport(
        schema_version=REPORT_SCHEMA_VERSION,
        source_sha=source_sha,
        packs_dir=str(packs_dir),
        presets_dir=str(presets_dir) if presets_dir else None,
        webui_root=webui_root,
        asset_coverage_available=asset_coverage_available,
        pack_files_examined=len(pack_files),
        standalone_presets_examined=standalone_presets_examined_count,
        findings=findings,
    )


def render_summary_markdown(report: CensusReport) -> str:
    counts = report.summary_counts()
    class_counts = report.counts_by_class()
    lines = [
        "# PromptPack & Saved-Settings Quality Census Summary",
        "",
        f"- Schema version: {report.schema_version}",
        f"- Source SHA: {report.source_sha or '(unknown)'}",
        f"- PromptPack files examined: {report.pack_files_examined}",
        f"- Standalone presets examined: {report.standalone_presets_examined}",
        f"- Asset Registry coverage available: {report.asset_coverage_available}",
        "",
        "## Findings by class",
        "",
    ]
    for klass, count in sorted(class_counts.items()):
        lines.append(f"- {klass}: {count}")
    lines.extend(["", "## Findings by code", ""])
    for code, count in sorted(counts.items()):
        lines.append(f"- {code}: {count}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packs-dir", type=Path, default=None)
    parser.add_argument("--presets-dir", type=Path, default=None)
    parser.add_argument("--webui-root", type=str, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, default=None)
    parser.add_argument("--asset-cache", type=Path, default=None)
    parser.add_argument("--source-sha", type=str, default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    packs_dir = args.packs_dir or resolve_prompt_pack_dir()
    asset_cache_path = args.asset_cache or (args.out.parent / "asset_registry_census_cache.json")

    report = run_census(
        packs_dir=packs_dir,
        presets_dir=args.presets_dir,
        webui_root=args.webui_root,
        asset_cache_path=asset_cache_path,
        source_sha=args.source_sha,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report.to_json_dict(), indent=2, sort_keys=True), encoding="utf-8")

    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(render_summary_markdown(report), encoding="utf-8")

    print(f"Examined {report.pack_files_examined} PromptPack file(s), {len(report.findings)} finding(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
