"""Offline, read-only triage workflow for WP-PACK-AUDIT-100's missing
file-backed asset findings (PR-PACK-120).

`scan` re-opens each source that produced a `missing_file_backed_asset`
finding, read-only, and maps the aggregated census finding back to every
exact raw persisted JSON occurrence that actually carries the missing value.
It attaches deterministic, same-kind candidate evidence from the Asset
Registry and Asset-120 compatibility context, and produces a decision
template the operator can fill in -- this module never decides anything.

`apply` executes an operator-approved decisions file, but only when given
`--apply`; the default is a dry run. Every decision is validated (source
still exists, SHA-256 unchanged, expected old value still present, and for
`replace_reference` that the candidate resolves uniquely to the same asset
kind) before any file is touched, all backups are taken before the first
write, and any failure restores every file already changed in that batch.

No network. No A1111/Comfy/GPU/model execution. No PromptPack/preset/asset
mutation from `scan`, ever.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.assets import AssetKind, AssetRecord, AssetRegistry
from src.pipeline.model_synchronizer import normalize_model_name

REPORT_SCHEMA_VERSION = 1
DECISION_SCHEMA_VERSION = 1

_PLACEHOLDER_VALUES = frozenset({"none", "(none)", "null"})

_CHECKPOINT_ALIASES = ("model", "model_name", "sd_model")
_VAE_ALIASES = ("vae", "vae_name", "sd_vae")
_REFINER_ALIASES = ("refiner_model_name", "refiner_checkpoint")

_SCALAR_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "checkpoint": _CHECKPOINT_ALIASES,
    "vae": _VAE_ALIASES,
    "refiner_checkpoint": _REFINER_ALIASES,
}

_ASSET_KIND_BY_LABEL: dict[str, AssetKind] = {
    "checkpoint": AssetKind.CHECKPOINT,
    "vae": AssetKind.VAE,
    "refiner_checkpoint": AssetKind.CHECKPOINT,
    "lora": AssetKind.LORA,
    "embedding": AssetKind.EMBEDDING,
}

_OPTIONAL_CLEARABLE_FIELDS: frozenset[str] = frozenset(
    {"vae", "vae_name", "sd_vae", "refiner_model_name", "refiner_checkpoint"}
)


def _stable_id(*parts: str) -> str:
    """Deterministic ID for unchanged inputs; never derived from an
    absolute machine path."""

    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def is_placeholder_value(raw_value: Any) -> bool:
    """Recognize obvious literal non-asset placeholders only.

    Deliberately exact/case-insensitive match against a narrow known set --
    never a heuristic on "looks unusual", since an ordinary unusual filename
    must never be misclassified as a placeholder.
    """

    text = str(raw_value or "").strip().lower()
    return text in _PLACEHOLDER_VALUES


# ---------------------------------------------------------------------------
# Occurrence mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceOccurrence:
    occurrence_id: str
    source_type: str
    source_id: str
    source_file: str
    source_file_sha256: str
    pointer: str
    asset_kind: str
    raw_value: Any
    normalized_value: str | None
    stage: str | None = None
    slot_index: int | None = None
    active_context: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _scalar_alias_occurrences(
    prefix: str, container: Mapping[str, Any], missing_value: str, aliases: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Every raw location, top-level and nested `txt2img`, holding exactly
    the missing value under one of the accepted aliases for this kind."""

    target = missing_value.strip()
    found: list[dict[str, Any]] = []

    def _check(section: Mapping[str, Any], section_prefix: str) -> None:
        for key in aliases:
            if key not in section:
                continue
            value = section[key]
            if isinstance(value, str) and value.strip() == target:
                pointer = f"{section_prefix}.{key}" if section_prefix else key
                found.append({"pointer": pointer, "raw_value": value})

    _check(container, prefix)
    txt2img = container.get("txt2img")
    if isinstance(txt2img, Mapping):
        nested_prefix = f"{prefix}.txt2img" if prefix else "txt2img"
        _check(txt2img, nested_prefix)
    return found


def _lora_occurrences(pack_data: Mapping[str, Any], missing_value: str) -> list[dict[str, Any]]:
    target = missing_value.strip().lower()
    found: list[dict[str, Any]] = []
    slots = pack_data.get("slots")
    if not isinstance(slots, list):
        return found
    for slot_index, slot in enumerate(slots):
        if not isinstance(slot, Mapping):
            continue
        loras = slot.get("loras")
        if not isinstance(loras, list):
            continue
        for entry_index, entry in enumerate(loras):
            if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
                continue
            name = str(entry[0] or "").strip()
            if name.lower() == target:
                found.append(
                    {
                        "pointer": f"pack_data.slots[{slot_index}].loras[{entry_index}][0]",
                        "raw_value": entry[0],
                        "slot_index": slot_index,
                        "weight": entry[1],
                    }
                )
    return found


def _embedding_entry_name(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, Mapping):
        return str(entry.get("name", "") or "").strip()
    if isinstance(entry, (list, tuple)) and entry:
        return str(entry[0] or "").strip()
    return None


def _embedding_occurrences(pack_data: Mapping[str, Any], missing_value: str) -> list[dict[str, Any]]:
    target = missing_value.strip().lower()
    found: list[dict[str, Any]] = []
    slots = pack_data.get("slots")
    if not isinstance(slots, list):
        return found
    for slot_index, slot in enumerate(slots):
        if not isinstance(slot, Mapping):
            continue
        for field_name in ("positive_embeddings", "negative_embeddings"):
            values = slot.get(field_name)
            if not isinstance(values, list):
                continue
            for entry_index, entry in enumerate(values):
                name = _embedding_entry_name(entry)
                if name and name.lower() == target:
                    found.append(
                        {
                            "pointer": f"pack_data.slots[{slot_index}].{field_name}[{entry_index}]",
                            "raw_value": entry,
                            "slot_index": slot_index,
                            "field": field_name,
                        }
                    )
    return found


def map_finding_to_occurrences(
    *,
    asset_kind: str,
    missing_value: str,
    document: Mapping[str, Any],
    is_promptpack: bool,
) -> list[dict[str, Any]]:
    """Re-open the raw document and find every exact occurrence.

    Never guesses: a finding whose value cannot be found verbatim in the raw
    document produces zero occurrences (the caller records that as
    unmapped/stale), rather than approximating a location.
    """

    if is_promptpack:
        preset_data = document.get("preset_data")
        container: Mapping[str, Any] = preset_data if isinstance(preset_data, Mapping) else {}
        prefix = "preset_data"
        pack_data = document.get("pack_data")
        pack_data = pack_data if isinstance(pack_data, Mapping) else {}
    else:
        container = document
        prefix = ""
        pack_data = {}

    if asset_kind in _SCALAR_ALIAS_GROUPS:
        return _scalar_alias_occurrences(prefix, container, missing_value, _SCALAR_ALIAS_GROUPS[asset_kind])
    if asset_kind == "lora":
        return _lora_occurrences(pack_data, missing_value)
    if asset_kind == "embedding":
        return _embedding_occurrences(pack_data, missing_value)
    return []


# ---------------------------------------------------------------------------
# Candidate evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateEvidence:
    candidate_name: str
    similarity_score: float
    similarity_method: str
    asset_kind: str
    resolved_family: str | None = None
    resolved_status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _installed_names_for_kind(registry: AssetRegistry, kind: AssetKind) -> dict[str, AssetRecord]:
    """One representative record per normalized display name, for candidate
    generation only -- never used to decide resolution/missing status."""

    names: dict[str, AssetRecord] = {}
    for record in registry.snapshot.records_for(kind):
        for location in record.locations:
            if location.kind is not kind:
                continue
            normalized = normalize_model_name(location.display_name)
            if normalized and normalized not in names:
                names[normalized] = record
    return names


def find_candidates(
    missing_value: str,
    asset_kind: str,
    registry: AssetRegistry | None,
    *,
    max_candidates: int = 5,
) -> list[CandidateEvidence]:
    """Deterministic, same-kind-only candidate evidence.

    Uses stdlib difflib.SequenceMatcher.ratio() against normalized display
    names -- documented, reproducible, and never a network/fuzzy-download
    lookup. Ordering is deterministic: by descending score, then
    alphabetically by candidate name.
    """

    if registry is None:
        return []
    kind = _ASSET_KIND_BY_LABEL.get(asset_kind)
    if kind is None:
        return []
    normalized_missing = normalize_model_name(missing_value) or missing_value.strip().lower()
    installed = _installed_names_for_kind(registry, kind)

    scored: list[tuple[float, str, AssetRecord]] = []
    for name, record in installed.items():
        score = difflib.SequenceMatcher(None, normalized_missing, name).ratio()
        scored.append((score, name, record))
    scored.sort(key=lambda item: (-item[0], item[1]))

    results: list[CandidateEvidence] = []
    for score, name, record in scored[:max_candidates]:
        profile = record.compatibility
        results.append(
            CandidateEvidence(
                candidate_name=name,
                similarity_score=round(score, 4),
                similarity_method="difflib.SequenceMatcher.ratio",
                asset_kind=asset_kind,
                resolved_family=(profile.family.value if profile and profile.family else None),
                resolved_status=(profile.status.value if profile else None),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Triage item / report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TriageItem:
    triage_item_id: str
    census_finding_identity: dict[str, Any]
    source_type: str
    source_id: str
    asset_kind: str
    missing_reference_name: str
    occurrences: tuple[ReferenceOccurrence, ...]
    is_placeholder: bool
    candidates: tuple[CandidateEvidence, ...]
    base_family: str | None = None
    base_status: str | None = None
    unmapped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "triage_item_id": self.triage_item_id,
            "census_finding_identity": self.census_finding_identity,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "asset_kind": self.asset_kind,
            "missing_reference_name": self.missing_reference_name,
            "occurrence_count": len(self.occurrences),
            "occurrences": [o.as_dict() for o in self.occurrences],
            "is_placeholder": self.is_placeholder,
            "candidates": [c.as_dict() for c in self.candidates],
            "base_family": self.base_family,
            "base_status": self.base_status,
            "unmapped": self.unmapped,
        }


@dataclass(frozen=True)
class TriageReport:
    schema_version: int
    source_sha: str
    census_finding_count: int
    triage_items: tuple[TriageItem, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_sha": self.source_sha,
            "census_finding_count": self.census_finding_count,
            "triage_item_count": len(self.triage_items),
            "triage_items": [item.as_dict() for item in sorted(
                self.triage_items,
                key=lambda i: (i.source_type, i.source_id, i.asset_kind, i.missing_reference_name),
            )],
        }


def _load_source_document(
    source_type: str, source_id: str, packs_dir: Path, presets_dir: Path | None
) -> tuple[dict[str, Any] | None, Path | None]:
    if source_type == "promptpack":
        path = packs_dir / f"{source_id}.json"
    elif source_type == "standalone_preset" and presets_dir is not None:
        path = presets_dir / f"{source_id}.json"
    else:
        return None, None
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except (OSError, json.JSONDecodeError):
        return None, path


def _base_checkpoint_context(
    source_type: str, document: Mapping[str, Any], registry: AssetRegistry | None
) -> tuple[str | None, str | None]:
    """Best-effort, read-only base-checkpoint family lookup for context only."""

    if registry is None:
        return None, None
    container: Mapping[str, Any]
    if source_type == "promptpack":
        preset_data = document.get("preset_data")
        container = preset_data if isinstance(preset_data, Mapping) else {}
    else:
        container = document
    checkpoint_name = None
    for key in _CHECKPOINT_ALIASES:
        txt2img = container.get("txt2img")
        candidates = [container.get(key)]
        if isinstance(txt2img, Mapping):
            candidates.append(txt2img.get(key))
        for value in candidates:
            if isinstance(value, str) and value.strip():
                checkpoint_name = value.strip()
                break
        if checkpoint_name:
            break
    if not checkpoint_name:
        return None, None
    normalized = normalize_model_name(checkpoint_name)
    if not normalized:
        return None, None
    for record in registry.snapshot.records_for(AssetKind.CHECKPOINT):
        for location in record.locations:
            if location.kind is AssetKind.CHECKPOINT and normalize_model_name(location.display_name) == normalized:
                profile = record.compatibility
                family = profile.family.value if profile and profile.family else None
                status = profile.status.value if profile else None
                return family, status
    return None, None


def build_triage_report(
    census_findings: list[dict[str, Any]],
    *,
    packs_dir: Path,
    presets_dir: Path | None,
    registry: AssetRegistry | None,
    source_sha: str,
) -> TriageReport:
    targeted = [f for f in census_findings if f.get("finding_code") == "missing_file_backed_asset"]
    items: list[TriageItem] = []

    for finding in targeted:
        source_type = finding.get("source_type", "")
        source_id = finding.get("source_id", "")
        asset_kind = finding.get("asset_kind", "")
        missing_name = finding.get("reference_name") or ""

        item_id = _stable_id(source_type, source_id, asset_kind, missing_name)
        finding_identity = {
            "source_type": source_type,
            "source_id": source_id,
            "finding_code": "missing_file_backed_asset",
            "asset_kind": asset_kind,
            "reference_name": missing_name,
        }

        document, path = _load_source_document(source_type, source_id, packs_dir, presets_dir)
        if document is None or path is None:
            items.append(
                TriageItem(
                    item_id,
                    finding_identity,
                    source_type,
                    source_id,
                    asset_kind,
                    missing_name,
                    (),
                    is_placeholder_value(missing_name),
                    (),
                    unmapped=True,
                )
            )
            continue

        source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        is_promptpack = source_type == "promptpack"
        raw_occurrences = map_finding_to_occurrences(
            asset_kind=asset_kind, missing_value=missing_name, document=document, is_promptpack=is_promptpack
        )

        occurrences = tuple(
            ReferenceOccurrence(
                occurrence_id=_stable_id(source_type, source_id, asset_kind, missing_name, occ["pointer"]),
                source_type=source_type,
                source_id=source_id,
                source_file=path.name,
                source_file_sha256=source_sha256,
                pointer=occ["pointer"],
                asset_kind=asset_kind,
                raw_value=occ["raw_value"],
                normalized_value=normalize_model_name(missing_name) if isinstance(occ["raw_value"], str) else None,
                slot_index=occ.get("slot_index"),
            )
            for occ in raw_occurrences
        )

        base_family, base_status = _base_checkpoint_context(source_type, document, registry)
        candidates = tuple(find_candidates(missing_name, asset_kind, registry))

        items.append(
            TriageItem(
                item_id,
                finding_identity,
                source_type,
                source_id,
                asset_kind,
                missing_name,
                occurrences,
                is_placeholder_value(missing_name),
                candidates,
                base_family=base_family,
                base_status=base_status,
                unmapped=not occurrences,
            )
        )

    return TriageReport(REPORT_SCHEMA_VERSION, source_sha, len(targeted), tuple(items))


def render_triage_markdown(report: TriageReport) -> str:
    lines = [
        "# Missing Asset Reference Triage Summary",
        "",
        f"- Schema version: {report.schema_version}",
        f"- Source SHA: {report.source_sha or '(unknown)'}",
        f"- Census `missing_file_backed_asset` findings: {report.census_finding_count}",
        f"- Triage items: {len(report.triage_items)}",
        f"- Unmapped/stale items: {sum(1 for i in report.triage_items if i.unmapped)}",
        f"- Placeholder items: {sum(1 for i in report.triage_items if i.is_placeholder)}",
        "",
        "## Items",
        "",
    ]
    for item in sorted(report.triage_items, key=lambda i: (i.source_type, i.source_id, i.asset_kind)):
        lines.append(
            f"- `{item.triage_item_id}` {item.source_type}:{item.source_id} "
            f"[{item.asset_kind}] {item.missing_reference_name!r} "
            f"occurrences={len(item.occurrences)} placeholder={item.is_placeholder} "
            f"candidates={len(item.candidates)}"
        )
    return "\n".join(lines) + "\n"


def build_decisions_template(report: TriageReport, *, source_sha: str, triage_report_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "generated_from": {
            "source_sha": source_sha,
            "triage_report_sha256": triage_report_sha256,
        },
        "decisions": [
            {
                "triage_item_id": item.triage_item_id,
                "occurrence_ids": [o.occurrence_id for o in item.occurrences],
                "action": "leave_unresolved",
                "replacement": None,
                "expected_old_value": item.missing_reference_name,
                "expected_source_sha256": (item.occurrences[0].source_file_sha256 if item.occurrences else None),
            }
            for item in sorted(
                report.triage_items,
                key=lambda i: (i.source_type, i.source_id, i.asset_kind, i.missing_reference_name),
            )
        ],
    }


# ---------------------------------------------------------------------------
# Decision validation and apply (never invoked against real data in this PR)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    triage_item_id: str
    ok: bool
    reason: str = ""


def _find_item(report: TriageReport, triage_item_id: str) -> TriageItem | None:
    for item in report.triage_items:
        if item.triage_item_id == triage_item_id:
            return item
    return None


def _find_occurrence(item: TriageItem, occurrence_id: str) -> ReferenceOccurrence | None:
    for occ in item.occurrences:
        if occ.occurrence_id == occurrence_id:
            return occ
    return None


def validate_decision(
    decision: Mapping[str, Any],
    report: TriageReport,
    *,
    packs_dir: Path,
    presets_dir: Path | None,
    registry: AssetRegistry | None,
) -> ValidationResult:
    triage_item_id = decision.get("triage_item_id", "")
    item = _find_item(report, triage_item_id)
    if item is None:
        return ValidationResult(triage_item_id, False, "unknown triage_item_id")

    action = decision.get("action", "leave_unresolved")
    if action == "leave_unresolved":
        return ValidationResult(triage_item_id, True)

    if item.unmapped:
        return ValidationResult(triage_item_id, False, "item has no mapped occurrence; refusing to act")

    occurrence_ids = decision.get("occurrence_ids") or []
    occurrences = [_find_occurrence(item, oid) for oid in occurrence_ids]
    if not occurrence_ids or any(o is None for o in occurrences):
        return ValidationResult(triage_item_id, False, "unknown occurrence_id in decision")

    document, path = _load_source_document(item.source_type, item.source_id, packs_dir, presets_dir)
    if document is None or path is None:
        return ValidationResult(triage_item_id, False, "source no longer exists or is unreadable")

    expected_sha = decision.get("expected_source_sha256")
    current_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha and expected_sha != current_sha:
        return ValidationResult(triage_item_id, False, "source SHA-256 has changed since triage; stale decision")

    expected_old_value = decision.get("expected_old_value")
    for occ in occurrences:
        assert occ is not None
        fresh_occ = map_finding_to_occurrences(
            asset_kind=item.asset_kind,
            missing_value=item.missing_reference_name,
            document=document,
            is_promptpack=item.source_type == "promptpack",
        )
        if not any(o["pointer"] == occ.pointer for o in fresh_occ):
            return ValidationResult(triage_item_id, False, f"expected old value no longer present at {occ.pointer}")
        if expected_old_value is not None and str(expected_old_value).strip() != item.missing_reference_name.strip():
            return ValidationResult(triage_item_id, False, "expected_old_value does not match triage evidence")

    if action == "replace_reference":
        replacement = str(decision.get("replacement") or "").strip()
        if not replacement:
            return ValidationResult(triage_item_id, False, "replace_reference requires a replacement value")
        if registry is None:
            return ValidationResult(triage_item_id, False, "no Asset Registry available to validate replacement")
        kind = _ASSET_KIND_BY_LABEL.get(item.asset_kind)
        if kind is None:
            return ValidationResult(triage_item_id, False, f"unsupported asset kind for replacement: {item.asset_kind}")
        normalized = normalize_model_name(replacement)
        matches = [
            record
            for record in registry.snapshot.records_for(kind)
            if any(
                loc.kind is kind and normalize_model_name(loc.display_name) == normalized
                for loc in record.locations
            )
        ]
        if not matches:
            return ValidationResult(triage_item_id, False, "replacement does not resolve to any installed asset")
        if len(matches) > 1:
            return ValidationResult(triage_item_id, False, "replacement resolves ambiguously; refusing")
        return ValidationResult(triage_item_id, True)

    if action == "clear_optional_reference":
        for occ in occurrences:
            assert occ is not None
            field_name = occ.pointer.rsplit(".", 1)[-1]
            if field_name not in _OPTIONAL_CLEARABLE_FIELDS:
                return ValidationResult(
                    triage_item_id, False, f"{field_name} is not an optional/clearable field"
                )
        return ValidationResult(triage_item_id, True)

    if action == "remove_reference":
        if item.asset_kind not in ("lora", "embedding"):
            return ValidationResult(
                triage_item_id, False, "remove_reference is only authorized for structured lora/embedding entries"
            )
        return ValidationResult(triage_item_id, True)

    return ValidationResult(triage_item_id, False, f"unsupported action: {action}")


def validate_batch(
    decisions: Iterable[Mapping[str, Any]],
    report: TriageReport,
    *,
    packs_dir: Path,
    presets_dir: Path | None,
    registry: AssetRegistry | None,
) -> list[ValidationResult]:
    return [
        validate_decision(d, report, packs_dir=packs_dir, presets_dir=presets_dir, registry=registry)
        for d in decisions
    ]


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    if isinstance(obj, list):
        out = {}
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
        return out
    return {prefix: obj}


def _apply_one_decision(document: dict[str, Any], item: TriageItem, decision: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new document with only this decision's authorized change applied."""

    import copy

    new_doc = copy.deepcopy(document)
    action = decision["action"]
    occurrence_ids = set(decision.get("occurrence_ids") or [])
    target_occurrences = [o for o in item.occurrences if o.occurrence_id in occurrence_ids]

    for occ in target_occurrences:
        path_parts = _pointer_to_parts(occ.pointer)
        if action == "replace_reference":
            if item.asset_kind == "embedding":
                _set_at_pointer(new_doc, path_parts, _replace_embedding_name(occ.raw_value, decision["replacement"]))
            else:
                _set_at_pointer(new_doc, path_parts, decision["replacement"])
        elif action == "clear_optional_reference":
            _set_at_pointer(new_doc, path_parts, "")
        elif action == "remove_reference":
            _remove_entry_at_pointer(new_doc, path_parts, item.asset_kind)
    return new_doc


def _authorized_prefix(occ: ReferenceOccurrence, action: str) -> str:
    """The semantic-diff prefix this occurrence's decision authorizes.

    Removing a LoRA [name, weight] entry also removes its sibling weight
    key, which the bare name pointer (`...loras[j][0]`) does not cover;
    authorize the whole entry in that case. Every other action only ever
    touches exactly the pointer itself (or, for a dict-shaped embedding
    entry, its own sub-keys, which already share that same prefix).
    """

    if action == "remove_reference" and occ.asset_kind == "lora" and occ.pointer.endswith("]"):
        return occ.pointer.rsplit("[", 1)[0]
    return occ.pointer


def _replace_embedding_name(original_entry: Any, replacement: str) -> Any:
    """Swap only the name component of an embedding entry, preserving its
    original shape/weight rather than discarding them."""

    if isinstance(original_entry, Mapping):
        updated = dict(original_entry)
        updated["name"] = replacement
        return updated
    if isinstance(original_entry, (list, tuple)) and len(original_entry) >= 2:
        return [replacement, original_entry[1]]
    return replacement


def _pointer_to_parts(pointer: str) -> list[str | int]:
    parts: list[str | int] = []
    for chunk in pointer.replace("]", "").split("."):
        while "[" in chunk:
            name, _, rest = chunk.partition("[")
            if name:
                parts.append(name)
            idx, _, chunk = rest.partition("[")
            parts.append(int(idx))
            chunk = "[" + chunk if chunk else ""
        if chunk and not chunk.startswith("["):
            parts.append(chunk)
    return parts


def _navigate(doc: Any, parts: list[str | int]) -> tuple[Any, str | int]:
    node = doc
    for part in parts[:-1]:
        node = node[part]
    return node, parts[-1]


def _set_at_pointer(doc: dict[str, Any], parts: list[str | int], value: Any) -> None:
    parent, last = _navigate(doc, parts)
    parent[last] = value


def _remove_entry_at_pointer(doc: dict[str, Any], parts: list[str | int], asset_kind: str) -> None:
    """Remove the whole structured entry the pointer's name element belongs
    to, never a partial/malformed entry.

    A LoRA pointer targets the name sub-index within its [name, weight]
    entry (e.g. `...loras[1][0]`), so the entry itself is two levels up.
    An embedding pointer targets the entry directly (e.g.
    `...positive_embeddings[1]`), so the entry is one level up.
    """

    entry_offset = 2 if asset_kind == "lora" else 1
    list_parts = parts[:-entry_offset]
    entry_index = parts[-entry_offset]
    parent, list_key = _navigate(doc, list_parts)
    target_list = parent[list_key]
    if isinstance(target_list, list) and isinstance(entry_index, int) and 0 <= entry_index < len(target_list):
        del target_list[entry_index]


@dataclass(frozen=True)
class ApplyResult:
    dry_run: bool
    applied_triage_item_ids: list[str]
    skipped: list[ValidationResult]
    backups: dict[str, str]


def apply_batch(
    decisions: list[dict[str, Any]],
    report: TriageReport,
    *,
    packs_dir: Path,
    presets_dir: Path | None,
    registry: AssetRegistry | None,
    backup_dir: Path,
    dry_run: bool = True,
) -> ApplyResult:
    """All-or-nothing apply. Dry-run by default; real writes require dry_run=False."""

    validations = validate_batch(decisions, report, packs_dir=packs_dir, presets_dir=presets_dir, registry=registry)
    failures = [v for v in validations if not v.ok]
    if failures:
        return ApplyResult(dry_run, [], failures, {})

    actionable = [
        d for d in decisions if d.get("action", "leave_unresolved") != "leave_unresolved"
    ]
    if not actionable:
        return ApplyResult(dry_run, [], [], {})

    # Group decisions by source file so each file is touched exactly once.
    by_source: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for decision in actionable:
        item = _find_item(report, decision["triage_item_id"])
        assert item is not None
        by_source.setdefault((item.source_type, item.source_id), []).append(decision)

    backups: dict[str, str] = {}
    backup_dir.mkdir(parents=True, exist_ok=True)
    originals: dict[Path, bytes] = {}

    for source_type, source_id in by_source:
        _document, path = _load_source_document(source_type, source_id, packs_dir, presets_dir)
        if path is None:
            return ApplyResult(dry_run, [], [ValidationResult(source_id, False, "source missing at apply time")], {})
        original_bytes = path.read_bytes()
        originals[path] = original_bytes
        backup_path = backup_dir / path.name
        backup_path.write_bytes(original_bytes)
        if hashlib.sha256(backup_path.read_bytes()).hexdigest() != hashlib.sha256(original_bytes).hexdigest():
            return ApplyResult(dry_run, [], [ValidationResult(source_id, False, "backup verification failed")], {})
        backups[str(path)] = str(backup_path)

    if dry_run:
        return ApplyResult(True, [d["triage_item_id"] for d in actionable], [], backups)

    applied: list[str] = []
    try:
        for (source_type, source_id), source_decisions in by_source.items():
            document, path = _load_source_document(source_type, source_id, packs_dir, presets_dir)
            assert document is not None and path is not None
            before_flat = _flatten(document)
            new_doc = document
            authorized_pointer_prefixes: set[str] = set()
            for decision in source_decisions:
                item = _find_item(report, decision["triage_item_id"])
                assert item is not None
                action = decision.get("action", "leave_unresolved")
                for occ in item.occurrences:
                    if occ.occurrence_id in set(decision.get("occurrence_ids") or []):
                        authorized_pointer_prefixes.add(_authorized_prefix(occ, action))
                new_doc = _apply_one_decision(new_doc, item, decision)

            after_flat = _flatten(new_doc)
            all_keys = set(before_flat) | set(after_flat)
            changed = {k for k in all_keys if before_flat.get(k) != after_flat.get(k)}
            unauthorized = {
                k for k in changed if not any(k == p or k.startswith(p) for p in authorized_pointer_prefixes)
            }
            if unauthorized:
                raise RuntimeError(f"semantic-diff guard: unauthorized change(s) {unauthorized} in {source_id}")

            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
                json.dump(new_doc, handle, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)
            applied.extend(d["triage_item_id"] for d in source_decisions)
    except Exception:
        for path, original_bytes in originals.items():
            path.write_bytes(original_bytes)
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(original_bytes).hexdigest():
                raise RuntimeError(f"rollback verification failed for {path}") from None
        return ApplyResult(
            dry_run, [], [ValidationResult("batch", False, "apply failed; all files restored from backup")], backups
        )

    return ApplyResult(dry_run, applied, [], backups)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_scan(args: argparse.Namespace) -> int:
    census = json.loads(Path(args.census_report).read_text(encoding="utf-8"))
    packs_dir = Path(args.packs_dir)
    presets_dir = Path(args.presets_dir) if args.presets_dir else None

    registry: AssetRegistry | None = None
    if args.webui_root:
        registry = AssetRegistry(args.webui_root, cache_path=Path(args.asset_cache))
        if any(root.is_dir() for _kind, root in registry.supported_roots()):
            registry.refresh()
        else:
            registry = None

    report = build_triage_report(
        census.get("findings", []),
        packs_dir=packs_dir,
        presets_dir=presets_dir,
        registry=registry,
        source_sha=census.get("source_sha", ""),
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_json_dict(), indent=2, sort_keys=True), encoding="utf-8")

    if args.summary_out:
        Path(args.summary_out).write_text(render_triage_markdown(report), encoding="utf-8")

    if args.decisions_template:
        triage_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
        template = build_decisions_template(report, source_sha=report.source_sha, triage_report_sha256=triage_sha)
        Path(args.decisions_template).write_text(json.dumps(template, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Triaged {len(report.triage_items)} item(s) from {report.census_finding_count} finding(s).")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    report_data = json.loads(Path(args.triage).read_text(encoding="utf-8"))
    items = tuple(
        TriageItem(
            triage_item_id=d["triage_item_id"],
            census_finding_identity=d["census_finding_identity"],
            source_type=d["source_type"],
            source_id=d["source_id"],
            asset_kind=d["asset_kind"],
            missing_reference_name=d["missing_reference_name"],
            occurrences=tuple(
                ReferenceOccurrence(**{k: v for k, v in o.items() if k in ReferenceOccurrence.__dataclass_fields__})
                for o in d.get("occurrences", [])
            ),
            is_placeholder=d["is_placeholder"],
            candidates=(),
            unmapped=d.get("unmapped", False),
        )
        for d in report_data.get("triage_items", [])
    )
    report = TriageReport(
        report_data["schema_version"], report_data.get("source_sha", ""), report_data["census_finding_count"], items
    )
    decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8")).get("decisions", [])

    registry: AssetRegistry | None = None
    if args.webui_root:
        registry = AssetRegistry(args.webui_root, cache_path=Path(args.asset_cache)) if args.asset_cache else None
        if registry is not None:
            registry.refresh()

    result = apply_batch(
        decisions,
        report,
        packs_dir=Path(args.packs_dir),
        presets_dir=Path(args.presets_dir) if args.presets_dir else None,
        registry=registry,
        backup_dir=Path(args.backup_dir),
        dry_run=not args.apply,
    )
    print(f"dry_run={result.dry_run} applied={result.applied_triage_item_ids} skipped={len(result.skipped)}")
    for skip in result.skipped:
        print(f"  REFUSED {skip.triage_item_id}: {skip.reason}")
    return 0 if not result.skipped else 1


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--census-report", required=True)
    scan.add_argument("--packs-dir", required=True)
    scan.add_argument("--presets-dir", default=None)
    scan.add_argument("--webui-root", default=None)
    scan.add_argument("--asset-cache", default=None)
    scan.add_argument("--out", required=True)
    scan.add_argument("--summary-out", default=None)
    scan.add_argument("--decisions-template", default=None)
    scan.set_defaults(func=_cmd_scan)

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--triage", required=True)
    apply_cmd.add_argument("--decisions", required=True)
    apply_cmd.add_argument("--packs-dir", required=True)
    apply_cmd.add_argument("--presets-dir", default=None)
    apply_cmd.add_argument("--webui-root", default=None)
    apply_cmd.add_argument("--asset-cache", default=None)
    apply_cmd.add_argument("--backup-dir", required=True)
    apply_cmd.add_argument("--apply", action="store_true", help="Actually write changes (default: dry run).")
    apply_cmd.set_defaults(func=_cmd_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
