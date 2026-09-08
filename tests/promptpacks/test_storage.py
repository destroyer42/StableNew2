from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.gui.models.prompt_pack_model import PromptPackModel
from src.promptpacks.storage import (
    CURRENT_PROMPTPACK_SCHEMA_VERSION,
    MigrationAction,
    PromptPackFormatError,
    discover_native_prompt_packs,
    export_prompt_pack,
    import_prompt_pack,
    load_prompt_pack_document,
    migrate_legacy_pairs,
    prompt_pack_rows,
    save_prompt_pack_document,
)


def _document(*, slots: list[dict] | None = None, versioned: bool = False) -> dict:
    document = {
        "pack_data": {
            "name": "example",
            "slots": slots or [],
            "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
            "show_preview": True,
            "author_note": "preserve me",
        },
        "preset_data": {"txt2img": {"steps": 24}},
        "extension_data": {"owner": "Rob"},
    }
    if versioned:
        document["schema_version"] = CURRENT_PROMPTPACK_SCHEMA_VERSION
    return document


def _structured_slot(text: str = "a cinematic hero") -> dict:
    return {
        "index": 0,
        "text": text,
        "negative": "blurry\ndistorted",
        "template_id": "",
        "template_variables": {},
        "positive_embeddings": [["detail", 0.8]],
        "negative_embeddings": [["bad_quality", 1.0]],
        "loras": [["cinematic", 0.65]],
    }


def test_migration_treats_canonical_flattened_txt_as_equivalent(tmp_path: Path) -> None:
    json_path = tmp_path / "example.json"
    txt_path = tmp_path / "example.txt"
    json_path.write_text(json.dumps(_document(slots=[_structured_slot()])), encoding="utf-8")
    txt_path.write_text(
        "(<embedding:detail>:0.8)\n"
        "a cinematic hero\n"
        "<lora:cinematic:0.65>\n"
        "neg: <embedding:bad_quality>\n"
        "neg: blurry\n"
        "neg: distorted   \r\n\r\n\r\n",
        encoding="utf-8",
    )
    before = (json_path.read_bytes(), txt_path.read_bytes())

    [result] = migrate_legacy_pairs(tmp_path)

    assert result.action is MigrationAction.VERSION_UPGRADE
    assert not result.applied
    assert (json_path.read_bytes(), txt_path.read_bytes()) == before


def test_migration_merges_split_txt_prompts_and_preserves_json_metadata(tmp_path: Path) -> None:
    json_path = tmp_path / "example.json"
    txt_path = tmp_path / "example.txt"
    json_path.write_text(json.dumps(_document()), encoding="utf-8")
    txt_path.write_text(
        "masterpiece, best quality\nlegacy hero\nneg: blurry, distorted\nneg: low quality\n",
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backups"

    [dry_run] = migrate_legacy_pairs(tmp_path)
    [applied] = migrate_legacy_pairs(tmp_path, apply=True, backup_dir=backup_dir)
    migrated = load_prompt_pack_document(json_path)

    assert dry_run.action is MigrationAction.MERGE_TEXT_PROMPTS
    assert applied.action is MigrationAction.MERGE_TEXT_PROMPTS
    assert applied.applied
    assert migrated["preset_data"] == {"txt2img": {"steps": 24}}
    assert migrated["pack_data"]["author_note"] == "preserve me"
    assert migrated["extension_data"] == {"owner": "Rob"}
    assert prompt_pack_rows(migrated)[0].quality_line == "masterpiece, best quality\nlegacy hero"
    assert prompt_pack_rows(migrated)[0].negative_phrases == (
        "blurry",
        "distorted",
        "low quality",
    )
    assert (backup_dir / "example.json").exists()
    assert (backup_dir / "example.txt").read_bytes() == txt_path.read_bytes()
    [second] = migrate_legacy_pairs(tmp_path, apply=True, backup_dir=backup_dir)
    assert second.action is MigrationAction.NOOP
    assert not second.applied


def test_migration_still_conflicts_when_normalized_negative_content_changes(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "example.json"
    txt_path = tmp_path / "example.txt"
    slot = _structured_slot()
    slot["negative"] = "blurry, distorted"
    json_path.write_text(json.dumps(_document(slots=[slot], versioned=True)), encoding="utf-8")
    txt_path.write_text(
        "(<embedding:detail>:0.8)\n"
        "a cinematic hero\n"
        "<lora:cinematic:0.65>\n"
        "neg: <embedding:bad_quality>\n"
        "neg: blurry\n"
        "neg: altered phrase\n",
        encoding="utf-8",
    )

    [result] = migrate_legacy_pairs(tmp_path)

    assert result.action is MigrationAction.CONFLICT


def test_migration_reports_genuine_semantic_conflict_without_overwrite(tmp_path: Path) -> None:
    json_path = tmp_path / "example.json"
    txt_path = tmp_path / "example.txt"
    json_path.write_text(json.dumps(_document(slots=[_structured_slot()])), encoding="utf-8")
    txt_path.write_text("an independently authored landscape\n", encoding="utf-8")
    before = (json_path.read_bytes(), txt_path.read_bytes())

    [result] = migrate_legacy_pairs(tmp_path, apply=True, backup_dir=tmp_path / "backups")

    assert result.action is MigrationAction.CONFLICT
    assert not result.applied
    assert (json_path.read_bytes(), txt_path.read_bytes()) == before
    assert not (tmp_path / "backups").exists()


def test_native_discovery_is_json_only_and_requires_current_schema(tmp_path: Path) -> None:
    save_prompt_pack_document(tmp_path / "native.json", _document(versioned=True))
    (tmp_path / "native.txt").write_text("different runtime prompt", encoding="utf-8")
    (tmp_path / "legacy.json").write_text(json.dumps(_document()), encoding="utf-8")
    (tmp_path / "only-text.txt").write_text("text", encoding="utf-8")

    assert discover_native_prompt_packs(tmp_path) == [tmp_path / "native.json"]


def test_model_save_is_deterministic_and_preserves_unknown_current_schema_data(
    tmp_path: Path,
) -> None:
    source = save_prompt_pack_document(
        tmp_path / "native.json", _document(slots=[_structured_slot()], versioned=True)
    )
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["pack_data"]["slots"][0]["future_slot_field"] = {"value": 7}
    source.write_text(json.dumps(raw), encoding="utf-8")
    pack = PromptPackModel.load_from_file(source, min_slots=1)
    pack.slots[0].text = "updated hero"

    pack.save_to_file()
    first = source.read_bytes()
    pack.save_to_file()

    persisted = load_prompt_pack_document(source)
    assert source.read_bytes() == first
    assert persisted["extension_data"] == {"owner": "Rob"}
    assert persisted["pack_data"]["author_note"] == "preserve me"
    assert persisted["pack_data"]["slots"][0]["future_slot_field"] == {"value": 7}
    assert persisted["pack_data"]["slots"][0]["text"] == "updated hero"


@pytest.mark.parametrize(
    ("suffix", "content", "expected"),
    [
        (".txt", "hero\nneg: blurry\n", "hero"),
        (".tsv", "hero\tblurry\n", "hero"),
    ],
)
def test_explicit_import_creates_runnable_native_json(
    tmp_path: Path, suffix: str, content: str, expected: str
) -> None:
    source = tmp_path / f"source{suffix}"
    source.write_text(content, encoding="utf-8")
    target = tmp_path / "imported.json"

    import_prompt_pack(source, target)

    document = load_prompt_pack_document(target)
    assert document["schema_version"] == CURRENT_PROMPTPACK_SCHEMA_VERSION
    assert prompt_pack_rows(document)[0].quality_line == expected


@pytest.mark.parametrize("suffix", [".txt", ".tsv"])
def test_explicit_export_is_flattened_and_does_not_modify_native(
    tmp_path: Path, suffix: str
) -> None:
    source = save_prompt_pack_document(
        tmp_path / "native.json", _document(slots=[_structured_slot()], versioned=True)
    )
    before = source.read_bytes()
    target = tmp_path / f"export{suffix}"

    export_prompt_pack(source, target)

    assert "a cinematic hero" in target.read_text(encoding="utf-8")
    assert source.read_bytes() == before


def test_malformed_pair_fails_safely(tmp_path: Path) -> None:
    json_path = tmp_path / "broken.json"
    json_path.write_text("{", encoding="utf-8")
    (tmp_path / "broken.txt").write_text("hero", encoding="utf-8")

    [result] = migrate_legacy_pairs(tmp_path)

    assert result.action is MigrationAction.MALFORMED
    with pytest.raises(PromptPackFormatError):
        load_prompt_pack_document(json_path)
