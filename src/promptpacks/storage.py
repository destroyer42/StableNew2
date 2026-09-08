"""One-file native PromptPack storage and explicit legacy interchange.

JSON is the only runtime PromptPack format. TXT and TSV are intentionally
lossy, flattened interchange formats and are used only by explicit import,
export, and offline migration operations.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.pipeline.prompt_pack_parser import PackRow, parse_prompt_pack_text
from src.utils.embedding_prompt_utils import (
    normalize_embedding_entries,
    render_embedding_reference,
    serialize_embedding_entries,
)
from src.utils.prompt_templates import compose_prompt_text

CURRENT_PROMPTPACK_SCHEMA_VERSION = 1


class PromptPackFormatError(ValueError):
    """Raised when a file is not a valid native PromptPack document."""


class MigrationAction(str, Enum):
    NOOP = "noop"
    VERSION_UPGRADE = "version_upgrade"
    MERGE_TEXT_PROMPTS = "merge_text_prompts"
    CONFLICT = "conflict"
    MALFORMED = "malformed"


@dataclass(frozen=True)
class MigrationResult:
    stem: str
    action: MigrationAction
    json_path: Path
    interchange_path: Path | None = None
    detail: str = ""
    applied: bool = False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromptPackFormatError(f"Failed to read PromptPack JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PromptPackFormatError(f"PromptPack JSON must be an object: {path}")
    return value


def validate_prompt_pack_document(
    document: dict[str, Any], *, allow_unversioned: bool = False
) -> None:
    version = document.get("schema_version")
    if version is None and not allow_unversioned:
        raise PromptPackFormatError("PromptPack schema_version is required")
    if version is not None and version != CURRENT_PROMPTPACK_SCHEMA_VERSION:
        raise PromptPackFormatError(
            f"Unsupported PromptPack schema_version {version!r}; "
            f"expected {CURRENT_PROMPTPACK_SCHEMA_VERSION}"
        )
    pack_data = document.get("pack_data")
    if not isinstance(pack_data, dict):
        raise PromptPackFormatError("PromptPack pack_data must be an object")
    slots = pack_data.get("slots", [])
    if not isinstance(slots, list) or any(not isinstance(slot, dict) for slot in slots):
        raise PromptPackFormatError("PromptPack pack_data.slots must be a list of objects")
    preset_data = document.get("preset_data", {})
    if not isinstance(preset_data, dict):
        raise PromptPackFormatError("PromptPack preset_data must be an object")


def load_prompt_pack_document(
    path: str | Path, *, allow_unversioned: bool = False
) -> dict[str, Any]:
    document = _read_json(Path(path))
    if "pack_data" not in document and allow_unversioned:
        document = {"pack_data": document, "preset_data": {}}
    validate_prompt_pack_document(document, allow_unversioned=allow_unversioned)
    return document


def save_prompt_pack_document(path: str | Path, document: dict[str, Any]) -> Path:
    target = Path(path)
    payload = copy.deepcopy(document)
    payload["schema_version"] = CURRENT_PROMPTPACK_SCHEMA_VERSION
    validate_prompt_pack_document(payload)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
    except Exception as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise OSError(f"Failed to save PromptPack {target}: {exc}") from exc
    return target


def discover_native_prompt_packs(directory: str | Path) -> list[Path]:
    packs_dir = Path(directory)
    packs_dir.mkdir(parents=True, exist_ok=True)
    discovered: list[Path] = []
    for path in sorted(packs_dir.glob("*.json"), key=lambda item: item.stem.lower()):
        try:
            load_prompt_pack_document(path)
        except PromptPackFormatError:
            continue
        discovered.append(path)
    return discovered


def _slot_prompt_text(slot: dict[str, Any]) -> str:
    return compose_prompt_text(
        str(slot.get("template_id", "") or ""),
        slot.get("template_variables", {})
        if isinstance(slot.get("template_variables"), dict)
        else {},
        str(slot.get("text", "") or ""),
    )


def prompt_pack_rows(document: dict[str, Any]) -> list[PackRow]:
    validate_prompt_pack_document(document, allow_unversioned=True)
    rows: list[PackRow] = []
    for raw_slot in document["pack_data"].get("slots", []):
        text = _slot_prompt_text(raw_slot).strip()
        positive_embeddings = tuple(
            normalize_embedding_entries(raw_slot.get("positive_embeddings", []))
        )
        negative_embeddings = tuple(
            normalize_embedding_entries(raw_slot.get("negative_embeddings", []))
        )
        loras: list[tuple[str, float]] = []
        for raw_lora in raw_slot.get("loras", []):
            if isinstance(raw_lora, (list, tuple)) and len(raw_lora) == 2:
                loras.append((str(raw_lora[0]), float(raw_lora[1])))
        negative = str(raw_slot.get("negative", "") or "")
        negative_phrases = tuple(
            phrase.strip()
            for line in negative.splitlines()
            for phrase in line.split(",")
            if phrase.strip()
        )
        if text or positive_embeddings or negative_embeddings or loras or negative_phrases:
            rows.append(
                PackRow(
                    embeddings=positive_embeddings,
                    quality_line=text,
                    subject_template="",
                    lora_tags=tuple(loras),
                    negative_embeddings=negative_embeddings,
                    negative_phrases=negative_phrases,
                )
            )
    return rows


def render_prompt_pack_prompts(document: dict[str, Any]) -> list[dict[str, str]]:
    """Render structured slots for UI preview without consulting interchange files."""
    validate_prompt_pack_document(document)
    prompts: list[dict[str, str]] = []
    for slot in document["pack_data"].get("slots", []):
        positive_parts = [
            render_embedding_reference(name, weight)
            for name, weight in normalize_embedding_entries(slot.get("positive_embeddings", []))
        ]
        positive_text = _slot_prompt_text(slot).strip()
        if positive_text:
            positive_parts.append(positive_text)
        positive_parts.extend(
            f"<lora:{item[0]}:{float(item[1])}>"
            for item in slot.get("loras", [])
            if isinstance(item, (list, tuple)) and len(item) == 2
        )
        negative_parts = [
            render_embedding_reference(name, weight)
            for name, weight in normalize_embedding_entries(slot.get("negative_embeddings", []))
        ]
        negative_parts.extend(
            line.strip()
            for line in str(slot.get("negative", "") or "").splitlines()
            if line.strip()
        )
        prompt = {
            "positive": " ".join(positive_parts).strip(),
            "negative": " ".join(negative_parts).strip(),
        }
        if prompt["positive"] or prompt["negative"]:
            prompts.append(prompt)
    return prompts


def _render_row(row: PackRow) -> tuple[str, str]:
    positive_parts = [render_embedding_reference(name, weight) for name, weight in row.embeddings]
    positive_parts.extend(part for part in (row.quality_line, row.subject_template) if part)
    positive_parts.extend(f"<lora:{name}:{weight}>" for name, weight in row.lora_tags)
    negative_parts = [
        render_embedding_reference(name, weight) for name, weight in row.negative_embeddings
    ]
    negative_parts.extend(row.negative_phrases)
    return " ".join(positive_parts).strip(), ", ".join(negative_parts).strip()


def _render_txt_document(document: dict[str, Any]) -> str:
    """Render the canonical flattened TXT representation of structured slots."""
    blocks: list[str] = []
    for slot in document["pack_data"].get("slots", []):
        lines: list[str] = []
        positive_embeddings = normalize_embedding_entries(slot.get("positive_embeddings", []))
        if positive_embeddings:
            lines.append(
                " ".join(
                    render_embedding_reference(name, weight) for name, weight in positive_embeddings
                )
            )
        positive_text = _slot_prompt_text(slot).strip()
        if positive_text:
            lines.append(positive_text)
        loras = slot.get("loras", [])
        lora_tokens = [
            f"<lora:{item[0]}:{float(item[1])}>"
            for item in loras
            if isinstance(item, (list, tuple)) and len(item) == 2
        ]
        if lora_tokens:
            lines.append(" ".join(lora_tokens))
        negative_embeddings = normalize_embedding_entries(slot.get("negative_embeddings", []))
        if negative_embeddings:
            lines.append(
                "neg: "
                + " ".join(
                    render_embedding_reference(name, weight) for name, weight in negative_embeddings
                )
            )
        lines.extend(
            f"neg: {line.strip()}"
            for line in str(slot.get("negative", "") or "").splitlines()
            if line.strip()
        )
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _render_tsv_document(document: dict[str, Any]) -> str:
    output_lines: list[str] = []
    for row in prompt_pack_rows(document):
        positive, negative = _render_row(row)
        output_lines.append(
            "\t".join(
                value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
                for value in (positive, negative)
            )
        )
    return "\n".join(output_lines) + ("\n" if output_lines else "")


def _normalized_semantic_rows(rows: list[PackRow]) -> tuple[tuple[Any, ...], ...]:
    """Return ordered, loss-aware slot semantics for migration comparison."""
    return tuple(
        (
            tuple((name, float(weight)) for name, weight in row.embeddings),
            " ".join(" ".join((row.quality_line, row.subject_template)).split()),
            tuple((name, float(weight)) for name, weight in row.lora_tags),
            tuple((name, float(weight)) for name, weight in row.negative_embeddings),
            tuple(" ".join(phrase.split()) for phrase in row.negative_phrases),
        )
        for row in rows
    )


def _rows_to_slots(rows: list[PackRow]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        slots.append(
            {
                "index": index,
                "text": "\n".join(
                    part for part in (row.quality_line, row.subject_template) if part
                ).strip(),
                "negative": ", ".join(row.negative_phrases),
                "template_id": "",
                "template_variables": {},
                "positive_embeddings": serialize_embedding_entries(row.embeddings),
                "negative_embeddings": serialize_embedding_entries(row.negative_embeddings),
                "loras": [[name, weight] for name, weight in row.lora_tags],
            }
        )
    return slots


def _read_interchange(path: Path) -> list[PackRow]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PromptPackFormatError(f"Failed to read interchange file {path}: {exc}") from exc
    if path.suffix.lower() == ".txt":
        return parse_prompt_pack_text(content)
    if path.suffix.lower() != ".tsv":
        raise PromptPackFormatError("PromptPack interchange must be .txt or .tsv")
    rows: list[PackRow] = []
    try:
        for values in csv.reader(content.splitlines(), delimiter="\t"):
            if (
                not values
                or not any(value.strip() for value in values)
                or values[0].lstrip().startswith("#")
            ):
                continue
            if len(values) > 2:
                raise PromptPackFormatError(
                    f"TSV row has {len(values)} columns; expected at most 2"
                )
            positive = values[0].strip()
            negative = values[1].strip() if len(values) == 2 else ""
            parsed = parse_prompt_pack_text(positive + (f"\nneg: {negative}" if negative else ""))
            rows.extend(parsed)
    except csv.Error as exc:
        raise PromptPackFormatError(f"Malformed TSV {path}: {exc}") from exc
    return rows


def import_prompt_pack(source: str | Path, target: str | Path, *, name: str | None = None) -> Path:
    source_path = Path(source)
    rows = _read_interchange(source_path)
    document: dict[str, Any] = {
        "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
        "pack_data": {
            "name": name or source_path.stem,
            "slots": _rows_to_slots(rows),
            "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
            "show_preview": True,
        },
        "preset_data": {},
    }
    return save_prompt_pack_document(target, document)


def export_prompt_pack(source: str | Path, target: str | Path) -> Path:
    document = load_prompt_pack_document(source)
    target_path = Path(target)
    suffix = target_path.suffix.lower()
    if suffix == ".txt":
        output = _render_txt_document(document)
    elif suffix == ".tsv":
        output = _render_tsv_document(document)
    else:
        raise PromptPackFormatError("PromptPack export target must be .txt or .tsv")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(output, encoding="utf-8")
    return target_path


def _migration_result(
    json_path: Path, interchange_path: Path
) -> tuple[MigrationAction, str, dict[str, Any] | None]:
    try:
        document = load_prompt_pack_document(json_path, allow_unversioned=True)
        interchange_rows = _read_interchange(interchange_path)
        json_rows = prompt_pack_rows(document)
    except PromptPackFormatError as exc:
        return MigrationAction.MALFORMED, str(exc), None
    if not json_rows and interchange_rows:
        migrated = copy.deepcopy(document)
        migrated["pack_data"]["slots"] = _rows_to_slots(interchange_rows)
        migrated["schema_version"] = CURRENT_PROMPTPACK_SCHEMA_VERSION
        return (
            MigrationAction.MERGE_TEXT_PROMPTS,
            "JSON has no prompts; import supplies prompt rows",
            migrated,
        )
    if _normalized_semantic_rows(json_rows) != _normalized_semantic_rows(interchange_rows):
        return MigrationAction.CONFLICT, "JSON and interchange prompt content disagree", None
    if document.get("schema_version") != CURRENT_PROMPTPACK_SCHEMA_VERSION:
        migrated = copy.deepcopy(document)
        migrated["schema_version"] = CURRENT_PROMPTPACK_SCHEMA_VERSION
        return (
            MigrationAction.VERSION_UPGRADE,
            "Equivalent prompts require schema version",
            migrated,
        )
    return MigrationAction.NOOP, "Native JSON is current and equivalent", document


def migrate_legacy_pairs(
    packs_dir: str | Path, *, apply: bool = False, backup_dir: str | Path | None = None
) -> list[MigrationResult]:
    directory = Path(packs_dir)
    if apply and backup_dir is None:
        raise ValueError("backup_dir is required when applying PromptPack migration")
    backup_root = Path(backup_dir) if backup_dir is not None else None
    results: list[MigrationResult] = []
    for json_path in sorted(directory.glob("*.json"), key=lambda item: item.stem.lower()):
        interchange = next(
            (
                candidate
                for candidate in (json_path.with_suffix(".txt"), json_path.with_suffix(".tsv"))
                if candidate.exists()
            ),
            None,
        )
        if interchange is None:
            try:
                document = load_prompt_pack_document(json_path, allow_unversioned=True)
            except PromptPackFormatError as exc:
                results.append(
                    MigrationResult(
                        json_path.stem, MigrationAction.MALFORMED, json_path, detail=str(exc)
                    )
                )
                continue
            action = (
                MigrationAction.NOOP
                if document.get("schema_version") == CURRENT_PROMPTPACK_SCHEMA_VERSION
                else MigrationAction.VERSION_UPGRADE
            )
            migrated = copy.deepcopy(document)
            migrated["schema_version"] = CURRENT_PROMPTPACK_SCHEMA_VERSION
            detail = (
                "Native JSON is current"
                if action is MigrationAction.NOOP
                else "JSON requires schema version"
            )
        else:
            action, detail, migrated = _migration_result(json_path, interchange)
        applied = False
        if apply and action in {
            MigrationAction.VERSION_UPGRADE,
            MigrationAction.MERGE_TEXT_PROMPTS,
        }:
            assert backup_root is not None and migrated is not None
            backup_root.mkdir(parents=True, exist_ok=True)
            for original in (json_path, interchange):
                if original is None:
                    continue
                backup = backup_root / original.name
                if not backup.exists():
                    shutil.copy2(original, backup)
            save_prompt_pack_document(json_path, migrated)
            applied = True
        results.append(
            MigrationResult(json_path.stem, action, json_path, interchange, detail, applied)
        )
    return results
