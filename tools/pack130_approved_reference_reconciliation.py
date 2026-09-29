"""Purpose-built, one-time reconciliation of the owner-approved subset of
PR-PACK-120's missing-reference triage decisions (PR-PACK-130).

This is intentionally NOT a generic apply/mutation engine. It recognizes
exactly three fixed policies, keyed by (asset_kind, missing_reference_name):

    ("lora", "BetterThanWords-merged-SDXL-LoRA-v3") -> remove the structured
        LoRA entry (owner determination: this is a checkpoint/model, not a
        LoRA that should be separately applied).
    ("lora", "babesByStableYogiPony_xlV4")           -> remove the structured
        LoRA entry (same determination).
    ("refiner_checkpoint", "None")                    -> clear the literal
        placeholder `"None"` to `""` (owner determination: a placeholder,
        not an asset identity), but only when the refiner is not otherwise
        explicitly enabled at that source.
    ("lora", "DreamyStyle_xl")                         -> leave unresolved;
        identity/original role is unknown, and no automatic action is
        authorized for it.

Any triage item whose (asset_kind, missing_reference_name) is not one of
these four keys, or whose source_type is not "promptpack", or that is
unmapped, makes the whole batch refuse -- there is no fallback behavior, no
replacement candidate logic, no fuzzy matching, and no network access. This
package never touches a checkpoint/model/VAE selection, a standalone
preset, or an embedding.

Read-only preflight (`build_plan`) can be run at any time. Real mutation
(`reconcile`) is guarded by: exact owner-approved-decision-set validation,
per-source SHA-256 staleness checks (both at plan time and again
immediately before each write), byte-exact backups verified before the
first write, a semantic-diff guard that permits only the two authorized
kinds of change, atomic per-file writes, and full rollback to byte-exact
originals on any failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Fixed, owner-approved policy -- see module docstring. This is the entire
# decision surface; nothing else is recognized.
# ---------------------------------------------------------------------------

_REMOVE_LORA = "remove_lora"
_CLEAR_OPTIONAL_REFINER = "clear_optional_refiner"
_LEAVE_UNRESOLVED = "leave_unresolved"

_POLICY: dict[tuple[str, str], str] = {
    ("lora", "BetterThanWords-merged-SDXL-LoRA-v3"): _REMOVE_LORA,
    ("lora", "babesByStableYogiPony_xlV4"): _REMOVE_LORA,
    ("refiner_checkpoint", "None"): _CLEAR_OPTIONAL_REFINER,
    ("lora", "DreamyStyle_xl"): _LEAVE_UNRESOLVED,
}

# Exact owner-reviewed evidence this package was authorized against. A fresh
# triage that does not reproduce this exact shape refuses before any write.
_EXPECTED_TOTAL_TRIAGE_ITEMS = 24
_EXPECTED_ITEM_OCCURRENCE_COUNTS: dict[str, tuple[int, int]] = {
    "BetterThanWords-merged-SDXL-LoRA-v3": (3, 13),
    "babesByStableYogiPony_xlV4": (8, 54),
    "None": (4, 4),
    "DreamyStyle_xl": (9, 63),
}
_EXPECTED_ACTIONABLE_SOURCE_COUNT = 15
_EXPECTED_LORA_REMOVAL_OCCURRENCES = 67
_EXPECTED_REFINER_CLEAR_OCCURRENCES = 4
_EXPECTED_TOTAL_ACTIONABLE_OCCURRENCES = 71

_LORA_POINTER_RE = re.compile(r"^pack_data\.slots\[(\d+)\]\.loras\[(\d+)\]\[0\]$")


class PolicyRefusal(RuntimeError):
    """Raised whenever the batch must refuse rather than act. Every raise
    site is a deliberate hard stop, never a warning to work around."""


# ---------------------------------------------------------------------------
# Plan construction (read-only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RemovalTarget:
    triage_item_id: str
    source_id: str
    pointer: str
    expected_name: str


@dataclass(frozen=True)
class ClearTarget:
    triage_item_id: str
    source_id: str
    pointer: str
    expected_old_value: str


@dataclass(frozen=True)
class SourcePlan:
    source_id: str
    expected_sha256: str
    removals: tuple[RemovalTarget, ...] = ()
    clear: ClearTarget | None = None


@dataclass(frozen=True)
class ReconciliationPlan:
    sources: tuple[SourcePlan, ...]
    leave_unresolved_counts: dict[str, tuple[int, int]]

    @property
    def total_removal_occurrences(self) -> int:
        return sum(len(s.removals) for s in self.sources)

    @property
    def total_clear_occurrences(self) -> int:
        return sum(1 for s in self.sources if s.clear is not None)

    @property
    def total_occurrence_actions(self) -> int:
        return self.total_removal_occurrences + self.total_clear_occurrences

    def summary(self) -> dict[str, Any]:
        return {
            "actionable_source_count": len(self.sources),
            "lora_removal_occurrences": self.total_removal_occurrences,
            "refiner_clear_occurrences": self.total_clear_occurrences,
            "total_occurrence_actions": self.total_occurrence_actions,
            "leave_unresolved_counts": self.leave_unresolved_counts,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PolicyRefusal(message)


def build_plan(triage_report: dict[str, Any]) -> ReconciliationPlan:
    """Turn a fresh PR-PACK-120 triage report into a reconciliation plan,
    or refuse. Every triage item must map to one of the four fixed
    policies above; anything else refuses the entire batch."""

    items = triage_report.get("triage_items", [])

    per_name_items: dict[str, int] = defaultdict(int)
    per_name_occurrences: dict[str, int] = defaultdict(int)
    removals_by_source: dict[str, list[RemovalTarget]] = defaultdict(list)
    clears_by_source: dict[str, ClearTarget] = {}
    sha_by_source: dict[str, str] = {}
    leave_unresolved_counts: dict[str, tuple[int, int]] = {}

    for item in items:
        asset_kind = item.get("asset_kind", "")
        name = item.get("missing_reference_name", "")
        source_id = item.get("source_id", "")
        source_type = item.get("source_type", "")
        triage_item_id = item.get("triage_item_id", "")
        occurrences = item.get("occurrences", [])

        policy = _POLICY.get((asset_kind, name))
        _require(
            policy is not None,
            f"unrecognized missing-reference policy for kind={asset_kind!r} name={name!r} "
            f"(triage_item_id={triage_item_id}); no fallback is authorized, refusing entire batch",
        )
        _require(
            source_type == "promptpack",
            f"non-promptpack source_type {source_type!r} for {triage_item_id}; refusing entire batch",
        )
        _require(
            not item.get("unmapped", False),
            f"unmapped triage item {triage_item_id} cannot be actioned; refusing entire batch",
        )
        _require(
            len(occurrences) > 0,
            f"triage item {triage_item_id} has no occurrences; refusing entire batch",
        )

        per_name_items[name] += 1
        per_name_occurrences[name] += len(occurrences)

        for occ in occurrences:
            occ_sha = occ.get("source_file_sha256", "")
            prior_sha = sha_by_source.get(source_id)
            _require(
                prior_sha is None or prior_sha == occ_sha,
                f"source {source_id} has inconsistent SHA-256 across its own triage occurrences; refusing",
            )
            sha_by_source[source_id] = occ_sha

        if policy == _LEAVE_UNRESOLVED:
            leave_unresolved_counts[name] = (per_name_items[name], per_name_occurrences[name])
            continue

        if policy == _REMOVE_LORA:
            _require(asset_kind == "lora", f"remove_lora policy applied to non-lora item {triage_item_id}")
            for occ in occurrences:
                pointer = occ.get("pointer", "")
                _require(
                    bool(_LORA_POINTER_RE.match(pointer)),
                    f"unexpected LoRA occurrence shape {pointer!r} for {triage_item_id}; refusing",
                )
                removals_by_source[source_id].append(
                    RemovalTarget(triage_item_id, source_id, pointer, name)
                )
        elif policy == _CLEAR_OPTIONAL_REFINER:
            _require(
                asset_kind == "refiner_checkpoint",
                f"clear_optional_refiner policy applied to non-refiner item {triage_item_id}",
            )
            _require(
                len(occurrences) == 1,
                f"expected exactly one refiner occurrence for {triage_item_id}, found {len(occurrences)}",
            )
            occ = occurrences[0]
            pointer = occ.get("pointer", "")
            raw_value = occ.get("raw_value")
            _require(
                isinstance(raw_value, str) and raw_value.strip() == "None",
                f"refiner occurrence at {pointer} in {source_id} is not the literal placeholder"
                f" \"None\" (found {raw_value!r}); refusing",
            )
            _require(
                "[" not in pointer,
                f"unexpected refiner occurrence shape {pointer!r} for {triage_item_id}; refusing",
            )
            _require(
                source_id not in clears_by_source,
                f"source {source_id} has more than one refiner-clear target; refusing",
            )
            clears_by_source[source_id] = ClearTarget(triage_item_id, source_id, pointer, "None")

    _require(
        len(items) == _EXPECTED_TOTAL_TRIAGE_ITEMS,
        f"expected exactly {_EXPECTED_TOTAL_TRIAGE_ITEMS} triage items, found {len(items)}; refusing",
    )
    for name, (expected_items, expected_occ) in _EXPECTED_ITEM_OCCURRENCE_COUNTS.items():
        actual_items = per_name_items.get(name, 0)
        actual_occ = per_name_occurrences.get(name, 0)
        _require(
            (actual_items, actual_occ) == (expected_items, expected_occ),
            f"expected {expected_items} items / {expected_occ} occurrences for {name!r}, "
            f"found {actual_items} items / {actual_occ} occurrences; owner-reviewed evidence has "
            f"changed, refusing entire batch",
        )

    actionable_source_ids = set(removals_by_source) | set(clears_by_source)
    _require(
        len(actionable_source_ids) == _EXPECTED_ACTIONABLE_SOURCE_COUNT,
        f"expected exactly {_EXPECTED_ACTIONABLE_SOURCE_COUNT} actionable sources, "
        f"found {len(actionable_source_ids)}; refusing",
    )

    sources = tuple(
        SourcePlan(
            source_id=source_id,
            expected_sha256=sha_by_source[source_id],
            removals=tuple(removals_by_source.get(source_id, ())),
            clear=clears_by_source.get(source_id),
        )
        for source_id in sorted(actionable_source_ids)
    )

    plan = ReconciliationPlan(sources=sources, leave_unresolved_counts=leave_unresolved_counts)
    _require(
        plan.total_removal_occurrences == _EXPECTED_LORA_REMOVAL_OCCURRENCES,
        f"expected {_EXPECTED_LORA_REMOVAL_OCCURRENCES} LoRA removal occurrences, "
        f"found {plan.total_removal_occurrences}; refusing",
    )
    _require(
        plan.total_clear_occurrences == _EXPECTED_REFINER_CLEAR_OCCURRENCES,
        f"expected {_EXPECTED_REFINER_CLEAR_OCCURRENCES} refiner-clear occurrences, "
        f"found {plan.total_clear_occurrences}; refusing",
    )
    _require(
        plan.total_occurrence_actions == _EXPECTED_TOTAL_ACTIONABLE_OCCURRENCES,
        f"expected {_EXPECTED_TOTAL_ACTIONABLE_OCCURRENCES} total occurrence actions, "
        f"found {plan.total_occurrence_actions}; refusing",
    )
    return plan


# ---------------------------------------------------------------------------
# Refiner-enablement safety check (reuses the confirmed production alias
# contract: refiner_enabled/use_refiner, defaulting to disabled when absent)
# ---------------------------------------------------------------------------


def _refiner_enabled_at(document: dict[str, Any]) -> bool:
    preset_data = document.get("preset_data")
    preset_data = preset_data if isinstance(preset_data, dict) else {}
    txt2img = preset_data.get("txt2img")
    txt2img = txt2img if isinstance(txt2img, dict) else {}
    for key in ("refiner_enabled", "use_refiner"):
        for container in (txt2img, preset_data):
            if key in container and container[key] not in (None, ""):
                return bool(container[key])
    return False


# ---------------------------------------------------------------------------
# Preflight validation (read-only; safe to call at any time)
# ---------------------------------------------------------------------------


def _load_document(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise PolicyRefusal(f"{path} is valid JSON but not an object; refusing")
    return parsed


def _get_lora_entry(document: dict[str, Any], pointer: str) -> Any:
    match = _LORA_POINTER_RE.match(pointer)
    if not match:
        raise PolicyRefusal(f"unexpected LoRA pointer shape: {pointer!r}")
    slot_index, entry_index = int(match.group(1)), int(match.group(2))
    try:
        return document["pack_data"]["slots"][slot_index]["loras"][entry_index]
    except (KeyError, IndexError, TypeError) as exc:
        raise PolicyRefusal(f"occurrence no longer present at {pointer}") from exc


def _get_scalar(document: dict[str, Any], pointer: str) -> Any:
    node: Any = document
    parts = pointer.split(".")
    try:
        for part in parts[:-1]:
            node = node[part]
        return node[parts[-1]]
    except (KeyError, TypeError) as exc:
        raise PolicyRefusal(f"occurrence no longer present at {pointer}") from exc


def preflight_check(plan: ReconciliationPlan, *, packs_dir: Path) -> None:
    """Re-validate every planned action against the sources' current state.
    Read-only; raises PolicyRefusal on the first violation. Safe to call
    repeatedly (e.g. once at plan time and again immediately before write)."""

    for source in plan.sources:
        path = packs_dir / f"{source.source_id}.json"
        _require(path.is_file(), f"source missing: {source.source_id}")
        current_bytes = path.read_bytes()
        current_sha = hashlib.sha256(current_bytes).hexdigest()
        _require(
            current_sha == source.expected_sha256,
            f"source SHA-256 has changed since triage for {source.source_id}; stale, refusing",
        )
        document = _load_document(path)

        for removal in source.removals:
            entry = _get_lora_entry(document, removal.pointer)
            _require(
                isinstance(entry, list) and len(entry) == 2 and str(entry[0]).strip() == removal.expected_name,
                f"expected LoRA entry named {removal.expected_name!r} at {removal.pointer} in "
                f"{source.source_id}, found {entry!r}; refusing",
            )

        if source.clear is not None:
            value = _get_scalar(document, source.clear.pointer)
            _require(
                isinstance(value, str) and value.strip() == source.clear.expected_old_value,
                f"expected literal {source.clear.expected_old_value!r} at {source.clear.pointer} in "
                f"{source.source_id}, found {value!r}; refusing",
            )
            _require(
                not _refiner_enabled_at(document),
                f"refiner is explicitly enabled at {source.source_id}; clearing its checkpoint would "
                f"alter intended enabled-refiner behavior, refusing entire batch",
            )


# ---------------------------------------------------------------------------
# Semantic transformation + diff guard (real mutation, in memory)
# ---------------------------------------------------------------------------


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(obj, list):
        out = {}
        for index, value in enumerate(obj):
            out.update(_flatten(value, f"{prefix}[{index}]"))
        return out
    return {prefix: obj}


def _apply_transform(document: dict[str, Any], source: SourcePlan) -> tuple[set[str], set[str]]:
    """Pure mutation step: apply exactly this source's authorized removals
    and clear to `document` in place. Returns the set of list-prefixes that
    had removals and the set of scalar pointers that were cleared, for the
    surrounding semantic-diff guard in `_transform_source` to check against.
    Raises PolicyRefusal on any internal shape mismatch."""

    by_slot: dict[int, list[tuple[int, RemovalTarget]]] = defaultdict(list)
    for removal in source.removals:
        match = _LORA_POINTER_RE.match(removal.pointer)
        assert match is not None
        slot_index, entry_index = int(match.group(1)), int(match.group(2))
        by_slot[slot_index].append((entry_index, removal))

    list_prefixes: set[str] = set()
    for slot_index, entries in by_slot.items():
        loras = document["pack_data"]["slots"][slot_index]["loras"]
        pre_list = list(loras)
        removed_indices: set[int] = set()
        for entry_index, removal in sorted(entries, key=lambda pair: pair[0], reverse=True):
            entry = loras[entry_index]
            _require(
                isinstance(entry, list) and len(entry) == 2 and str(entry[0]).strip() == removal.expected_name,
                f"expected LoRA entry named {removal.expected_name!r} at {removal.pointer}, found {entry!r}",
            )
            del loras[entry_index]
            removed_indices.add(entry_index)
        expected_list = [value for index, value in enumerate(pre_list) if index not in removed_indices]
        _require(
            loras == expected_list,
            f"list-removal mismatch in slot {slot_index} of {source.source_id}: "
            f"removing the approved entries did not leave exactly the expected survivors",
        )
        list_prefixes.add(f"pack_data.slots[{slot_index}].loras")

    scalar_keys: set[str] = set()
    if source.clear is not None:
        value = _get_scalar(document, source.clear.pointer)
        _require(
            isinstance(value, str) and value.strip() == source.clear.expected_old_value,
            f"expected literal {source.clear.expected_old_value!r} at {source.clear.pointer}, found {value!r}",
        )
        node: Any = document
        parts = source.clear.pointer.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = ""
        scalar_keys.add(source.clear.pointer)

    return list_prefixes, scalar_keys


def _transform_source(document: dict[str, Any], source: SourcePlan) -> dict[str, Any]:
    """Apply exactly this source's authorized removals/clear to `document`
    (mutated in place) and prove, via a full before/after semantic diff,
    that nothing else changed."""

    before_flat = _flatten(document)
    list_prefixes, scalar_keys = _apply_transform(document, source)
    after_flat = _flatten(document)

    all_keys = set(before_flat) | set(after_flat)
    changed = {key for key in all_keys if before_flat.get(key) != after_flat.get(key)}
    changed = {key for key in changed if not any(key == p or key.startswith(p + "[") for p in list_prefixes)}
    unauthorized = changed - scalar_keys
    _require(
        not unauthorized,
        f"semantic-diff guard: unauthorized change(s) {sorted(unauthorized)} in {source.source_id}; refusing",
    )
    return document


# ---------------------------------------------------------------------------
# Backup / atomic write / rollback
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupRecord:
    source_id: str
    filename: str
    original_sha256: str
    original_size: int
    backup_path: str


def _backup_source(path: Path, backup_dir: Path, source_id: str) -> BackupRecord:
    original = path.read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    backup_path = backup_dir / "promptpack" / path.name
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_bytes(original)
    backup_sha = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    _require(backup_sha == original_sha, f"backup verification failed for {source_id}")
    return BackupRecord(source_id, path.name, original_sha, len(original), str(backup_path))


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


@dataclass(frozen=True)
class ReconciliationResult:
    dry_run: bool
    sources_changed: tuple[str, ...]
    backups: tuple[BackupRecord, ...]


def reconcile(
    plan: ReconciliationPlan,
    *,
    packs_dir: Path,
    backup_dir: Path,
    dry_run: bool = True,
) -> ReconciliationResult:
    """Validate, then (unless dry_run) back up every actionable source,
    re-check freshness immediately before writing, transform + guard +
    atomically write each source, and roll every already-written source
    back to its byte-exact backup on any failure. All-or-nothing."""

    preflight_check(plan, packs_dir=packs_dir)

    if dry_run:
        return ReconciliationResult(True, (), ())

    backups: list[BackupRecord] = []
    originals: dict[Path, bytes] = {}
    for source in plan.sources:
        path = packs_dir / f"{source.source_id}.json"
        originals[path] = path.read_bytes()
        backups.append(_backup_source(path, backup_dir, source.source_id))

    # TOCTOU protection: re-check every source's fingerprint again,
    # immediately before the first write, in case something changed the
    # file between preflight/backup and now.
    preflight_check(plan, packs_dir=packs_dir)

    changed: list[str] = []
    try:
        for source in plan.sources:
            path = packs_dir / f"{source.source_id}.json"
            document = _load_document(path)
            document = _transform_source(document, source)
            _atomic_write(path, document)
            changed.append(source.source_id)
    except Exception:
        for path, original_bytes in originals.items():
            path.write_bytes(original_bytes)
            restored_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            expected_sha = hashlib.sha256(original_bytes).hexdigest()
            if restored_sha != expected_sha:
                raise RuntimeError(f"rollback verification failed for {path}") from None
        raise

    return ReconciliationResult(False, tuple(changed), tuple(backups))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    triage_report = json.loads(Path(args.triage).read_text(encoding="utf-8"))
    plan = build_plan(triage_report)
    print(json.dumps(plan.summary(), indent=2, sort_keys=True))

    result = reconcile(
        plan,
        packs_dir=Path(args.packs_dir),
        backup_dir=Path(args.backup_dir),
        dry_run=not args.apply,
    )
    if result.dry_run:
        print("dry_run=True: plan validated against current source state; zero writes performed.")
    else:
        print(f"dry_run=False: {len(result.sources_changed)} source(s) reconciled: {result.sources_changed}")
        for backup in result.backups:
            print(f"  backup {backup.source_id} -> {backup.backup_path} (sha256={backup.original_sha256[:12]})")
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triage", required=True, help="Fresh PR-PACK-120 triage JSON to plan against.")
    parser.add_argument("--packs-dir", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default: dry run).")
    parser.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except PolicyRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
