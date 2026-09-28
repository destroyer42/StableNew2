"""Deterministic fixtures for PR-PACK-120's missing-asset-reference triage.

All fixtures use temporary PromptPack/preset/WebUI roots; none reads the
operator's real files, and none performs network or runtime calls. No test
here ever applies a decision against anything but a disposable temp fixture.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import tools.missing_asset_reference_triage as triage
from src.assets import AssetRegistry


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _safetensors(path: Path, metadata: dict | None = None, payload: bytes = b"x") -> None:
    header = json.dumps({"__metadata__": metadata or {}}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)


def _finding(source_id: str, asset_kind: str, reference_name: str, source_type: str = "promptpack") -> dict:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "finding_code": "missing_file_backed_asset",
        "asset_kind": asset_kind,
        "reference_name": reference_name,
    }


def _pack(slots: list[dict], preset_data: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "pack_data": {"name": "pack", "slots": slots},
        "preset_data": preset_data or {},
    }


def _scan(findings, packs_dir, presets_dir=None, registry=None, source_sha="sha") -> triage.TriageReport:
    return triage.build_triage_report(
        findings, packs_dir=packs_dir, presets_dir=presets_dir, registry=registry, source_sha=source_sha
    )


def _registry(tmp_path: Path) -> AssetRegistry:
    return AssetRegistry(tmp_path / "webui", cache_path=tmp_path / "cache.json")


# --- 1/2/3. report filtering ------------------------------------------------------------------


def test_report_filtering_selects_only_missing_file_backed_asset(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "p.json", _pack([{"index": 0, "text": "a"}]))
    findings = [
        _finding("p", "lora", "missing_one"),
        {"source_type": "promptpack", "source_id": "p", "finding_code": "resolved_duplicate_bytes", "asset_kind": "lora", "reference_name": "dup"},
        {"source_type": "promptpack", "source_id": "p", "finding_code": "ambiguous_same_name", "asset_kind": "lora", "reference_name": "amb"},
    ]
    report = _scan(findings, packs)
    assert report.census_finding_count == 1
    assert len(report.triage_items) == 1
    assert report.triage_items[0].missing_reference_name == "missing_one"


# --- 4/5. checkpoint occurrence: nested and accepted top-level alias --------------------------


def test_checkpoint_occurrence_under_nested_txt2img(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack([{"index": 0, "text": "a"}], preset_data={"txt2img": {"model": "missing_ckpt.safetensors"}}),
    )
    report = _scan([_finding("p", "checkpoint", "missing_ckpt.safetensors")], packs)
    item = report.triage_items[0]
    assert len(item.occurrences) == 1
    assert item.occurrences[0].pointer == "preset_data.txt2img.model"


def test_checkpoint_occurrence_under_accepted_top_level_alias(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack([{"index": 0, "text": "a"}], preset_data={"sd_model": "missing_ckpt.safetensors"}),
    )
    report = _scan([_finding("p", "checkpoint", "missing_ckpt.safetensors")], packs)
    item = report.triage_items[0]
    assert len(item.occurrences) == 1
    assert item.occurrences[0].pointer == "preset_data.sd_model"


# --- 6/7. VAE and refiner occurrence -----------------------------------------------------------


def test_vae_occurrence(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack([{"index": 0, "text": "a"}], preset_data={"txt2img": {"vae_name": "missing_vae.safetensors"}}),
    )
    report = _scan([_finding("p", "vae", "missing_vae.safetensors")], packs)
    item = report.triage_items[0]
    assert item.occurrences[0].pointer == "preset_data.txt2img.vae_name"


def test_refiner_occurrence(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack([{"index": 0, "text": "a"}], preset_data={"txt2img": {"refiner_checkpoint": "None"}}),
    )
    report = _scan([_finding("p", "refiner_checkpoint", "None")], packs)
    item = report.triage_items[0]
    assert item.occurrences[0].pointer == "preset_data.txt2img.refiner_checkpoint"
    assert item.is_placeholder is True


# --- 8/9/10. LoRA and embedding occurrences, weight/position preserved -------------------------


def test_lora_occurrence_with_weight_preserved(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack([{"index": 0, "text": "a", "loras": [["keep", 1.0], ["missing_lora", 0.65]]}]),
    )
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    assert occ.pointer == "pack_data.slots[0].loras[1][0]"


def test_positive_embedding_occurrence(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack([{"index": 0, "text": "a", "positive_embeddings": ["keep", "missing_emb"]}]),
    )
    report = _scan([_finding("p", "embedding", "missing_emb")], packs)
    item = report.triage_items[0]
    assert item.occurrences[0].pointer == "pack_data.slots[0].positive_embeddings[1]"


def test_negative_embedding_occurrence(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack([{"index": 0, "text": "a", "negative_embeddings": ["missing_neg_emb"]}]),
    )
    report = _scan([_finding("p", "embedding", "missing_neg_emb")], packs)
    item = report.triage_items[0]
    assert item.occurrences[0].pointer == "pack_data.slots[0].negative_embeddings[0]"


# --- 11. same name in multiple slots yields multiple occurrences --------------------------------


def test_same_missing_name_in_multiple_slots_yields_multiple_occurrences(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack(
            [
                {"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]},
                {"index": 1, "text": "b", "loras": [["missing_lora", 0.9]]},
            ]
        ),
    )
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    assert len(item.occurrences) == 2
    assert {o.slot_index for o in item.occurrences} == {0, 1}


# --- 12. unmapped/stale evidence, never guessed --------------------------------------------------


def test_unfindable_reference_is_recorded_as_unmapped_not_guessed(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "p.json", _pack([{"index": 0, "text": "a", "loras": [["something_else", 0.5]]}]))
    report = _scan([_finding("p", "lora", "no_longer_there")], packs)
    item = report.triage_items[0]
    assert item.unmapped is True
    assert item.occurrences == ()


def test_missing_source_file_is_recorded_as_unmapped(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    report = _scan([_finding("does_not_exist", "lora", "x")], packs)
    item = report.triage_items[0]
    assert item.unmapped is True


# --- 13/14. placeholder classification ------------------------------------------------------------


@pytest.mark.parametrize("placeholder_value", ["None", "none", "(None)", "NULL"])
def test_known_placeholder_forms_are_classified(placeholder_value: str) -> None:
    assert triage.is_placeholder_value(placeholder_value) is True


@pytest.mark.parametrize("ordinary_value", ["nonexistent_lora_v2", "None_of_the_above_style", "xNoneStyle"])
def test_ordinary_unusual_filenames_are_not_classified_as_placeholder(ordinary_value: str) -> None:
    assert triage.is_placeholder_value(ordinary_value) is False


# --- 15/16/17/18. candidate evidence ---------------------------------------------------------------


def test_candidate_search_stays_within_asset_kind(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Stable-diffusion" / "missing_lora.safetensors")  # same name, wrong kind
    _safetensors(webui / "models" / "Lora" / "missing_lor.safetensors")  # same kind, close name
    registry = _registry(tmp_path)
    registry.refresh()
    candidates = triage.find_candidates("missing_lora", "lora", registry)
    names = [c.candidate_name for c in candidates]
    assert "missing_lora" not in names  # the checkpoint must never be proposed as a LoRA
    assert "missing_lor" in names


def test_candidate_ordering_is_deterministic(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    for name, payload in (("aaa", b"1"), ("bbb", b"2"), ("ccc", b"3")):
        _safetensors(webui / "models" / "Lora" / f"{name}.safetensors", payload=payload)
    registry = _registry(tmp_path)
    registry.refresh()
    first = triage.find_candidates("aaa", "lora", registry)
    second = triage.find_candidates("aaa", "lora", registry)
    assert [c.candidate_name for c in first] == [c.candidate_name for c in second]


def test_family_status_attached_to_candidates_observationally(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Lora" / "candidate_lora.safetensors", {"ss_base_model_version": "sdxl"})
    registry = _registry(tmp_path)
    registry.refresh()
    candidates = triage.find_candidates("candidate_lora", "lora", registry)
    assert candidates[0].resolved_family == "sdxl"
    assert candidates[0].resolved_status == "resolved"


def test_no_candidate_automatically_becomes_a_decision(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Lora" / "close_match.safetensors")
    _write_json(packs / "p.json", _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}]))
    registry = _registry(tmp_path)
    registry.refresh()
    report = _scan([_finding("p", "lora", "missing_lora")], packs, registry=registry)
    item = report.triage_items[0]
    assert len(item.candidates) >= 1
    template = triage.build_decisions_template(report, source_sha="sha", triage_report_sha256="abc")
    decision = template["decisions"][0]
    assert decision["action"] == "leave_unresolved"
    assert decision["replacement"] is None


# --- 19. decision template defaults to leave_unresolved --------------------------------------------


def test_decision_template_defaults_to_leave_unresolved(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "p.json", _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}]))
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    template = triage.build_decisions_template(report, source_sha="sha", triage_report_sha256="abc")
    assert all(d["action"] == "leave_unresolved" for d in template["decisions"])


# --- 20/21/22. replacement guards ------------------------------------------------------------------


def _one_item_report_with_lora(tmp_path: Path, registry) -> tuple[triage.TriageReport, Path]:
    packs = tmp_path / "packs"
    _write_json(packs / "p.json", _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}]))
    report = _scan([_finding("p", "lora", "missing_lora")], packs, registry=registry)
    return report, packs


def test_replacement_rejects_nonexistent_candidate(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.refresh()
    report, packs = _one_item_report_with_lora(tmp_path, registry)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "replace_reference",
        "replacement": "does_not_exist.safetensors",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=registry)
    assert result.ok is False


def test_replacement_rejects_ambiguous_candidate(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Lora" / "shared.safetensors", payload=b"AAA")
    _safetensors(webui / "models" / "LyCORIS" / "shared.safetensors", payload=b"BBB")
    registry = _registry(tmp_path)
    registry.refresh()
    report, packs = _one_item_report_with_lora(tmp_path, registry)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "replace_reference",
        "replacement": "shared.safetensors",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=registry)
    assert result.ok is False
    assert "ambigu" in result.reason


def test_replacement_rejects_wrong_kind_asset(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Stable-diffusion" / "onlyckpt.safetensors")
    registry = _registry(tmp_path)
    registry.refresh()
    report, packs = _one_item_report_with_lora(tmp_path, registry)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "replace_reference",
        "replacement": "onlyckpt.safetensors",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=registry)
    assert result.ok is False


# --- 23/24. staleness guards ------------------------------------------------------------------------


def test_source_sha_mismatch_rejects_the_decision(tmp_path: Path) -> None:
    report, packs = _one_item_report_with_lora(tmp_path, None)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": "0" * 64,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is False
    assert "stale" in result.reason.lower() or "sha" in result.reason.lower()


def test_expected_old_value_mismatch_rejects_the_decision(tmp_path: Path) -> None:
    report, packs = _one_item_report_with_lora(tmp_path, None)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": "some_other_value_entirely",
        "expected_source_sha256": occ.source_file_sha256,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is False


# --- 25/26. clear guards -----------------------------------------------------------------------------


def test_base_checkpoint_clear_is_rejected(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "p.json",
        _pack([{"index": 0, "text": "a"}], preset_data={"txt2img": {"model": "missing_ckpt.safetensors"}}),
    )
    report = _scan([_finding("p", "checkpoint", "missing_ckpt.safetensors")], packs)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "clear_optional_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is False


def test_optional_scalar_clear_dry_run_works(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a"}], preset_data={"txt2img": {"vae": "missing_vae.safetensors"}})
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "vae", "missing_vae.safetensors")], packs)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "clear_optional_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    result = triage.apply_batch(
        [decision], report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=True
    )
    assert result.dry_run is True
    assert not result.skipped
    # Dry run must not touch the source file.
    assert json.loads((packs / "p.json").read_text()) == document


# --- 27/28/29. dry-run mutation scope -----------------------------------------------------------------


def test_lora_removal_dry_run_changes_only_the_selected_occurrence(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a", "loras": [["keep", 1.0], ["missing_lora", 0.5]]}])
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    new_doc = triage._apply_one_decision(document, item, decision)
    assert new_doc["pack_data"]["slots"][0]["loras"] == [["keep", 1.0]]


def test_embedding_removal_dry_run_changes_only_the_selected_occurrence(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a", "positive_embeddings": ["keep", "missing_emb"]}])
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "embedding", "missing_emb")], packs)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    new_doc = triage._apply_one_decision(document, item, decision)
    assert new_doc["pack_data"]["slots"][0]["positive_embeddings"] == ["keep"]


def test_replacement_dry_run_changes_only_the_selected_json_pointer(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack(
        [{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}],
        preset_data={"txt2img": {"model": "keep_this.safetensors"}},
    )
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "replace_reference",
        "replacement": "replaced.safetensors",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    new_doc = triage._apply_one_decision(document, item, decision)
    assert new_doc["pack_data"]["slots"][0]["loras"] == [["replaced.safetensors", 0.5]]
    assert new_doc["preset_data"]["txt2img"]["model"] == "keep_this.safetensors"


# --- 30/31/32/33. batch safety: all-or-nothing, backup, rollback, semantic-diff guard ------------------


def test_all_decisions_validated_before_any_write(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    doc_a = _pack([{"index": 0, "text": "a", "loras": [["missing_a", 0.5]]}])
    doc_b = _pack([{"index": 0, "text": "b", "loras": [["missing_b", 0.5]]}])
    _write_json(packs / "a.json", doc_a)
    _write_json(packs / "b.json", doc_b)
    report = _scan([_finding("a", "lora", "missing_a"), _finding("b", "lora", "missing_b")], packs)
    item_a = next(i for i in report.triage_items if i.source_id == "a")
    item_b = next(i for i in report.triage_items if i.source_id == "b")

    good_decision = {
        "triage_item_id": item_a.triage_item_id,
        "occurrence_ids": [item_a.occurrences[0].occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item_a.missing_reference_name,
        "expected_source_sha256": item_a.occurrences[0].source_file_sha256,
    }
    bad_decision = {
        "triage_item_id": item_b.triage_item_id,
        "occurrence_ids": [item_b.occurrences[0].occurrence_id],
        "action": "remove_reference",
        "expected_old_value": "wrong value",
        "expected_source_sha256": item_b.occurrences[0].source_file_sha256,
    }
    result = triage.apply_batch(
        [good_decision, bad_decision],
        report,
        packs_dir=packs,
        presets_dir=None,
        registry=None,
        backup_dir=tmp_path / "backup",
        dry_run=False,
    )
    assert result.skipped  # batch refused
    assert json.loads((packs / "a.json").read_text()) == doc_a  # untouched despite being valid


def test_backup_failure_means_zero_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}])
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }

    def _corrupt_write_bytes(self, data):  # pragma: no cover - test double
        return len(data) + 1  # pretend to succeed without actually writing correctly

    # Simulate a backup that silently fails verification by monkeypatching
    # the post-backup hash check path: write garbage instead of the real
    # bytes so the SHA-256 comparison inside apply_batch fails.
    original_write_bytes = Path.write_bytes

    def _flaky_write_bytes(self: Path, data: bytes):
        if "backup" in self.parts:
            return original_write_bytes(self, b"corrupted")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", _flaky_write_bytes)
    result = triage.apply_batch(
        [decision], report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert result.skipped
    assert json.loads((packs / "p.json").read_text()) == document


def test_simulated_mid_write_failure_restores_byte_exact_originals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packs = tmp_path / "packs"
    document = _pack(
        [
            {"index": 0, "text": "a", "loras": [["missing_a", 0.5]]},
            {"index": 1, "text": "b", "loras": [["missing_b", 0.5]]},
        ]
    )
    _write_json(packs / "one.json", document)
    doc_two = _pack([{"index": 0, "text": "c", "loras": [["missing_c", 0.5]]}])
    _write_json(packs / "two.json", doc_two)
    original_one = (packs / "one.json").read_bytes()
    original_two = (packs / "two.json").read_bytes()

    report = _scan(
        [_finding("one", "lora", "missing_a"), _finding("two", "lora", "missing_c")], packs
    )
    item_one = next(i for i in report.triage_items if i.source_id == "one")
    item_two = next(i for i in report.triage_items if i.source_id == "two")
    decisions = [
        {
            "triage_item_id": item_one.triage_item_id,
            "occurrence_ids": [item_one.occurrences[0].occurrence_id],
            "action": "remove_reference",
            "expected_old_value": item_one.missing_reference_name,
            "expected_source_sha256": item_one.occurrences[0].source_file_sha256,
        },
        {
            "triage_item_id": item_two.triage_item_id,
            "occurrence_ids": [item_two.occurrences[0].occurrence_id],
            "action": "remove_reference",
            "expected_old_value": item_two.missing_reference_name,
            "expected_source_sha256": item_two.occurrences[0].source_file_sha256,
        },
    ]

    original_json_dump = json.dump
    call_count = {"n": 0}

    def _flaky_dump(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated mid-write failure")
        return original_json_dump(*args, **kwargs)

    monkeypatch.setattr(json, "dump", _flaky_dump)
    result = triage.apply_batch(
        decisions, report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert result.skipped
    assert (packs / "one.json").read_bytes() == original_one
    assert (packs / "two.json").read_bytes() == original_two


def test_semantic_diff_guard_rejects_unrelated_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}])
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }

    def _sneaky_apply(document, item, decision):
        new_doc = json.loads(json.dumps(document))
        new_doc["pack_data"]["slots"][0]["loras"] = []
        new_doc["pack_data"]["name"] = "renamed-without-authorization"
        return new_doc

    monkeypatch.setattr(triage, "_apply_one_decision", _sneaky_apply)
    result = triage.apply_batch(
        [decision], report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert result.skipped
    assert json.loads((packs / "p.json").read_text()) == document


# --- 34/35. scan is fully read-only ---------------------------------------------------------------------


def test_scan_performs_no_source_mutation(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}])
    _write_json(packs / "p.json", document)
    before = (packs / "p.json").read_bytes()
    _scan([_finding("p", "lora", "missing_lora")], packs)
    after = (packs / "p.json").read_bytes()
    assert before == after


def test_scan_and_validation_perform_no_network_or_runtime_call() -> None:
    import ast

    source = Path(triage.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"socket", "requests", "subprocess", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & forbidden)


# --- 36. deterministic output for unchanged inputs ------------------------------------------------------


def test_output_is_deterministic_for_unchanged_inputs(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "b.json", _pack([{"index": 0, "text": "b", "loras": [["missing_b", 0.5]]}]))
    _write_json(packs / "a.json", _pack([{"index": 0, "text": "a", "loras": [["missing_a", 0.5]]}]))
    findings = [_finding("b", "lora", "missing_b"), _finding("a", "lora", "missing_a")]
    first = _scan(findings, packs).to_json_dict()
    second = _scan(findings, packs).to_json_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# PR-PACK-120 batched apply-safety repair
# ---------------------------------------------------------------------------

# --- Finding 1: removal from non-final list positions ------------------------------------------


def _remove_decision(item, occurrence_ids: list[str]) -> dict:
    return {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": occurrence_ids,
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": item.occurrences[0].source_file_sha256,
    }


def test_remove_first_lora_from_two_entry_list(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5], ["keep", 1.0]]}])
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    decision = _remove_decision(item, [item.occurrences[0].occurrence_id])
    result = triage.apply_batch(
        [decision], report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert not result.skipped
    saved = json.loads((packs / "p.json").read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [["keep", 1.0]]


def test_remove_middle_lora_from_three_entry_list(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack(
        [{"index": 0, "text": "a", "loras": [["keep_a", 1.0], ["missing_lora", 0.5], ["keep_b", 2.0]]}]
    )
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    decision = _remove_decision(item, [item.occurrences[0].occurrence_id])
    result = triage.apply_batch(
        [decision], report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert not result.skipped
    saved = json.loads((packs / "p.json").read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [["keep_a", 1.0], ["keep_b", 2.0]]


def test_remove_first_embedding_preserves_later_entries(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a", "positive_embeddings": ["missing_emb", "keep1", "keep2"]}])
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "embedding", "missing_emb")], packs)
    item = report.triage_items[0]
    decision = _remove_decision(item, [item.occurrences[0].occurrence_id])
    result = triage.apply_batch(
        [decision], report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert not result.skipped
    saved = json.loads((packs / "p.json").read_text())
    assert saved["pack_data"]["slots"][0]["positive_embeddings"] == ["keep1", "keep2"]


def test_multiple_selected_removals_from_one_list_in_a_single_decision(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack(
        [{"index": 0, "text": "a", "loras": [["dup_missing", 0.5], ["keep", 1.0], ["dup_missing", 0.9]]}]
    )
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "dup_missing")], packs)
    item = report.triage_items[0]
    assert len(item.occurrences) == 2
    decision = _remove_decision(item, [o.occurrence_id for o in item.occurrences])
    result = triage.apply_batch(
        [decision], report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert not result.skipped
    saved = json.loads((packs / "p.json").read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [["keep", 1.0]]


def test_multiple_removals_from_one_list_across_separate_decisions(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack(
        [{"index": 0, "text": "a", "loras": [["missing_a", 0.5], ["keep", 1.0], ["missing_b", 0.7]]}]
    )
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "missing_a"), _finding("p", "lora", "missing_b")], packs)
    item_a = next(i for i in report.triage_items if i.missing_reference_name == "missing_a")
    item_b = next(i for i in report.triage_items if i.missing_reference_name == "missing_b")
    decisions = [
        _remove_decision(item_a, [item_a.occurrences[0].occurrence_id]),
        _remove_decision(item_b, [item_b.occurrences[0].occurrence_id]),
    ]
    result = triage.apply_batch(
        decisions, report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert not result.skipped
    saved = json.loads((packs / "p.json").read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [["keep", 1.0]]


def test_unauthorized_change_to_a_surviving_entry_is_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5], ["keep", 1.0]]}])
    _write_json(packs / "p.json", document)
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    decision = _remove_decision(item, [item.occurrences[0].occurrence_id])

    def _sneaky_apply(document, item, decision):
        new_doc = json.loads(json.dumps(document))
        # Correctly removes the missing entry, but also tampers with the
        # surviving entry's weight -- the dedicated list-level check must
        # catch this even though the entry count and the generic flattened
        # key set otherwise look plausible.
        new_doc["pack_data"]["slots"][0]["loras"] = [["keep", 999.0]]
        return new_doc

    monkeypatch.setattr(triage, "_apply_one_decision", _sneaky_apply)
    result = triage.apply_batch(
        [decision], report, packs_dir=packs, presets_dir=None, registry=None, backup_dir=tmp_path / "backup", dry_run=False
    )
    assert result.skipped
    assert json.loads((packs / "p.json").read_text()) == document


# --- Finding 2: actionable decisions require a source fingerprint ------------------------------


def test_actionable_decision_missing_sha_key_is_rejected(tmp_path: Path) -> None:
    report, packs = _one_item_report_with_lora(tmp_path, None)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is False


def test_actionable_decision_null_sha_is_rejected(tmp_path: Path) -> None:
    report, packs = _one_item_report_with_lora(tmp_path, None)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": None,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is False


def test_actionable_decision_blank_sha_is_rejected(tmp_path: Path) -> None:
    report, packs = _one_item_report_with_lora(tmp_path, None)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": "   ",
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is False


def test_actionable_decision_wrong_sha_is_rejected(tmp_path: Path) -> None:
    report, packs = _one_item_report_with_lora(tmp_path, None)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": "0" * 64,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is False


def test_actionable_decision_correct_sha_passes(tmp_path: Path) -> None:
    report, packs = _one_item_report_with_lora(tmp_path, None)
    item = report.triage_items[0]
    occ = item.occurrences[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [occ.occurrence_id],
        "action": "remove_reference",
        "expected_old_value": item.missing_reference_name,
        "expected_source_sha256": occ.source_file_sha256,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is True


def test_leave_unresolved_decision_without_sha_remains_valid(tmp_path: Path) -> None:
    report, packs = _one_item_report_with_lora(tmp_path, None)
    item = report.triage_items[0]
    decision = {
        "triage_item_id": item.triage_item_id,
        "occurrence_ids": [o.occurrence_id for o in item.occurrences],
        "action": "leave_unresolved",
        "replacement": None,
    }
    result = triage.validate_decision(decision, report, packs_dir=packs, presets_dir=None, registry=None)
    assert result.ok is True


# --- Finding 3: --asset-cache optional CLI contract ---------------------------------------------


def test_scan_cli_derives_audit_owned_cache_when_asset_cache_omitted(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Lora" / "close_match.safetensors")
    _write_json(packs / "p.json", _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}]))
    census_path = tmp_path / "census.json"
    census_path.write_text(
        json.dumps({"source_sha": "sha", "findings": [_finding("p", "lora", "missing_lora")]}),
        encoding="utf-8",
    )
    out_path = tmp_path / "out" / "triage.json"

    rc = triage.main(
        [
            "scan",
            "--census-report", str(census_path),
            "--packs-dir", str(packs),
            "--webui-root", str(webui),
            "--out", str(out_path),
        ]
    )

    assert rc == 0
    assert out_path.exists()
    derived_cache = out_path.parent / "asset_registry_triage_cache.json"
    assert derived_cache.exists()
    saved = json.loads(out_path.read_text())
    assert saved["triage_items"][0]["candidates"]  # candidate lookup actually worked


# --- Finding 4: non-object JSON is stale/unmapped evidence, never a crash -----------------------


@pytest.mark.parametrize("bad_payload", [[], "a string", 0, None])
def test_non_object_json_source_becomes_unmapped_not_a_crash(tmp_path: Path, bad_payload) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "p.json").write_text(json.dumps(bad_payload), encoding="utf-8")
    report = _scan([_finding("p", "lora", "missing_lora")], packs)
    item = report.triage_items[0]
    assert item.unmapped is True
    assert item.occurrences == ()


def test_non_object_json_source_does_not_block_other_sources_in_same_scan(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "bad.json").write_text(json.dumps([]), encoding="utf-8")
    _write_json(packs / "good.json", _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}]))
    findings = [_finding("bad", "lora", "x"), _finding("good", "lora", "missing_lora")]
    report = _scan(findings, packs)
    bad_item = next(i for i in report.triage_items if i.source_id == "bad")
    good_item = next(i for i in report.triage_items if i.source_id == "good")
    assert bad_item.unmapped is True
    assert good_item.unmapped is False
    assert len(good_item.occurrences) == 1


# --- Finding 5: backups are collision-free by source identity -----------------------------------


def test_backups_for_same_basename_promptpack_and_preset_do_not_collide(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    presets = tmp_path / "presets"
    doc_pack = _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}])
    doc_preset = {"vae": "missing_vae.safetensors"}
    _write_json(packs / "foo.json", doc_pack)
    _write_json(presets / "foo.json", doc_preset)
    findings = [
        _finding("foo", "lora", "missing_lora", source_type="promptpack"),
        _finding("foo", "vae", "missing_vae.safetensors", source_type="standalone_preset"),
    ]
    report = triage.build_triage_report(
        findings, packs_dir=packs, presets_dir=presets, registry=None, source_sha="sha"
    )
    pack_item = next(i for i in report.triage_items if i.source_type == "promptpack")
    preset_item = next(i for i in report.triage_items if i.source_type == "standalone_preset")
    decisions = [
        _remove_decision(pack_item, [pack_item.occurrences[0].occurrence_id]),
        {
            "triage_item_id": preset_item.triage_item_id,
            "occurrence_ids": [preset_item.occurrences[0].occurrence_id],
            "action": "clear_optional_reference",
            "expected_old_value": preset_item.missing_reference_name,
            "expected_source_sha256": preset_item.occurrences[0].source_file_sha256,
        },
    ]
    backup_dir = tmp_path / "backup"
    result = triage.apply_batch(
        decisions, report, packs_dir=packs, presets_dir=presets, registry=None, backup_dir=backup_dir, dry_run=False
    )
    assert not result.skipped
    pack_backup = Path(result.backups[str(packs / "foo.json")])
    preset_backup = Path(result.backups[str(presets / "foo.json")])
    assert pack_backup != preset_backup
    assert json.loads(pack_backup.read_text()) == doc_pack
    assert json.loads(preset_backup.read_text()) == doc_preset


def test_dual_source_same_basename_rollback_restores_both_originals_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packs = tmp_path / "packs"
    presets = tmp_path / "presets"
    doc_pack = _pack([{"index": 0, "text": "a", "loras": [["missing_lora", 0.5]]}])
    doc_preset = {"vae": "missing_vae.safetensors"}
    _write_json(packs / "foo.json", doc_pack)
    _write_json(presets / "foo.json", doc_preset)
    original_pack_bytes = (packs / "foo.json").read_bytes()
    original_preset_bytes = (presets / "foo.json").read_bytes()

    findings = [
        _finding("foo", "lora", "missing_lora", source_type="promptpack"),
        _finding("foo", "vae", "missing_vae.safetensors", source_type="standalone_preset"),
    ]
    report = triage.build_triage_report(
        findings, packs_dir=packs, presets_dir=presets, registry=None, source_sha="sha"
    )
    pack_item = next(i for i in report.triage_items if i.source_type == "promptpack")
    preset_item = next(i for i in report.triage_items if i.source_type == "standalone_preset")
    decisions = [
        _remove_decision(pack_item, [pack_item.occurrences[0].occurrence_id]),
        {
            "triage_item_id": preset_item.triage_item_id,
            "occurrence_ids": [preset_item.occurrences[0].occurrence_id],
            "action": "clear_optional_reference",
            "expected_old_value": preset_item.missing_reference_name,
            "expected_source_sha256": preset_item.occurrences[0].source_file_sha256,
        },
    ]

    original_json_dump = json.dump
    call_count = {"n": 0}

    def _flaky_dump(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated mid-write failure")
        return original_json_dump(*args, **kwargs)

    monkeypatch.setattr(json, "dump", _flaky_dump)
    result = triage.apply_batch(
        decisions, report, packs_dir=packs, presets_dir=presets, registry=None,
        backup_dir=tmp_path / "backup", dry_run=False,
    )
    assert result.skipped
    assert (packs / "foo.json").read_bytes() == original_pack_bytes
    assert (presets / "foo.json").read_bytes() == original_preset_bytes
