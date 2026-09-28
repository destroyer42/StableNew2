"""Deterministic fixtures for WP-PACK-AUDIT-100's read-only quality census.

All fixtures use temporary PromptPack/preset/WebUI roots; none reads the
operator's real files, and none performs network or runtime calls.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import tools.promptpack_quality_census as census


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _pack(slots: list[dict], preset_data: dict | None = None, *, matrix: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "pack_data": {
            "name": "pack",
            "slots": slots,
            "matrix": matrix or {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
        },
        "preset_data": preset_data or {},
    }


def _safetensors(path: Path, metadata: dict | None = None, payload: bytes = b"x") -> None:
    header = json.dumps({"__metadata__": metadata or {}}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)


def _codes(report: census.CensusReport, source_id: str | None = None) -> set[str]:
    return {
        f.finding_code
        for f in report.findings
        if source_id is None or f.source_id == source_id
    }


def _run(packs_dir: Path, presets_dir: Path | None = None, webui_root: str | None = None, tmp_path: Path | None = None) -> census.CensusReport:
    cache = (tmp_path or packs_dir.parent) / "cache.json"
    return census.run_census(
        packs_dir=packs_dir, presets_dir=presets_dir, webui_root=webui_root, asset_cache_path=cache
    )


# --- 1. valid current native PromptPack -------------------------------------------------


def test_valid_current_pack_has_no_structural_findings(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "good.json", _pack([{"index": 0, "text": "a cat", "negative": ""}]))
    report = _run(packs, tmp_path=tmp_path)
    assert report.pack_files_examined == 1
    structural = {f.finding_code for f in report.findings if f.finding_class == "format_schema"}
    assert not structural


# --- 2/3. malformed JSON / unsupported schema -------------------------------------------


def test_malformed_json_and_unsupported_schema_are_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "broken.json").write_text("not json {{{", encoding="utf-8")
    _write_json(packs / "future.json", {**_pack([]), "schema_version": 99})
    _write_json(packs / "legacy.json", {"pack_data": {"slots": []}})  # no schema_version at all

    report = _run(packs, tmp_path=tmp_path)
    assert "malformed_json" in _codes(report, "broken")
    assert "unsupported_schema_version" in _codes(report, "future")
    assert "unversioned_schema" in _codes(report, "legacy")


def test_non_object_top_level_is_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "array.json").write_text("[1, 2, 3]", encoding="utf-8")
    report = _run(packs, tmp_path=tmp_path)
    assert "non_object_top_level" in _codes(report, "array")


# --- 4. duplicate/negative/sparse slot indexes -------------------------------------------


def test_duplicate_negative_and_sparse_slot_indexes_are_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "slots.json",
        _pack(
            [
                {"index": 0, "text": "a"},
                {"index": 0, "text": "b"},  # duplicate
                {"index": -1, "text": "c"},  # negative
                {"index": 7, "text": "d"},  # sparse
            ]
        ),
    )
    report = _run(packs, tmp_path=tmp_path)
    codes = _codes(report, "slots")
    assert "duplicate_slot_index" in codes
    assert "negative_slot_index" in codes
    assert "sparse_or_noncanonical_slot_indexes" in codes


def test_missing_or_nonint_slot_index_is_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "badidx.json", _pack([{"index": "zero", "text": "a"}]))
    report = _run(packs, tmp_path=tmp_path)
    assert "missing_or_nonint_slot_index" in _codes(report, "badidx")


# --- 5. empty/non-renderable slots --------------------------------------------------------


def test_empty_slot_and_zero_renderable_slots_are_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "empty.json", _pack([{"index": 0, "text": "", "negative": ""}]))
    report = _run(packs, tmp_path=tmp_path)
    codes = _codes(report, "empty")
    assert "empty_persisted_slot" in codes
    assert "zero_renderable_slots" in codes


# --- 6. malformed LoRA and embedding entries ---------------------------------------------


def test_malformed_lora_and_embedding_entries_are_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "malformed.json",
        _pack(
            [
                {
                    "index": 0,
                    "text": "a",
                    "loras": [["", 0.5], ["ok", "not-a-number"], ["dup", 1.0], ["dup", 1.0]],
                    "positive_embeddings": [123, "goodemb"],
                }
            ]
        ),
    )
    report = _run(packs, tmp_path=tmp_path)
    codes = _codes(report, "malformed")
    assert "blank_lora_name" in codes
    assert "nonnumeric_lora_weight" in codes
    assert "duplicate_structured_reference" in codes


# --- 7. raw LoRA/embedding tokens in nominally pure text ----------------------------------


def test_raw_asset_tokens_in_text_are_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "rawtokens.json",
        _pack([{"index": 0, "text": "a cat <lora:sneaky:0.5> <embedding:neg1>"}]),
    )
    report = _run(packs, tmp_path=tmp_path)
    assert "raw_asset_token_in_text" in _codes(report, "rawtokens")


# --- 8. malformed/enabled matrix configuration --------------------------------------------


def test_malformed_and_enabled_empty_matrix_configuration_is_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "matrix.json",
        _pack(
            [{"index": 0, "text": "a"}],
            matrix={
                "enabled": True,
                "mode": "random",
                "limit": -1,
                "slots": [
                    {"name": "", "values": ["x"]},
                    {"name": "style", "values": []},
                    {"name": "style", "values": ["dup"]},
                ],
            },
        ),
    )
    report = _run(packs, tmp_path=tmp_path)
    codes = _codes(report, "matrix")
    assert "invalid_matrix_limit" in codes
    assert "blank_matrix_slot_name" in codes
    assert "duplicate_matrix_slot_name" in codes
    assert "enabled_matrix_slot_no_values" in codes


# --- 9. pack-name/file-name mismatch -------------------------------------------------------


def test_pack_name_filestem_mismatch_is_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    document = _pack([{"index": 0, "text": "a"}])
    document["pack_data"]["name"] = "totally different name"
    _write_json(packs / "myfile.json", document)
    report = _run(packs, tmp_path=tmp_path)
    assert "pack_name_filestem_mismatch" in _codes(report, "myfile")


# --- 10. raw preset alias contradiction ----------------------------------------------------


def test_raw_preset_alias_contradiction_is_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "alias.json",
        _pack(
            [{"index": 0, "text": "a"}],
            preset_data={
                "txt2img": {"model": "one.safetensors", "model_name": "two.safetensors"},
            },
        ),
    )
    report = _run(packs, tmp_path=tmp_path)
    assert "saved_setting_alias_conflict" in _codes(report, "alias")


def test_agreeing_alias_values_do_not_conflict(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "agree.json",
        _pack(
            [{"index": 0, "text": "a"}],
            preset_data={"txt2img": {"model": "same.safetensors", "model_name": "same.safetensors"}},
        ),
    )
    report = _run(packs, tmp_path=tmp_path)
    assert "saved_setting_alias_conflict" not in _codes(report, "agree")


def test_omitted_alias_value_is_not_a_contradiction(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "omit.json",
        _pack([{"index": 0, "text": "a"}], preset_data={"txt2img": {"model": "only.safetensors"}}),
    )
    report = _run(packs, tmp_path=tmp_path)
    assert "saved_setting_alias_conflict" not in _codes(report, "omit")


def test_stage_enablement_contradiction_is_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "stage.json",
        _pack(
            [{"index": 0, "text": "a"}],
            preset_data={
                "pipeline": {"adetailer_enabled": True},
                "adetailer": {"enabled": False},
            },
        ),
    )
    report = _run(packs, tmp_path=tmp_path)
    assert "saved_setting_stage_contradiction" in _codes(report, "stage")


def test_hires_fix_cross_section_contradiction_is_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "hires.json",
        _pack(
            [{"index": 0, "text": "a"}],
            preset_data={
                "txt2img": {"enable_hr": True},
                "hires_fix": {"enabled": False},
            },
        ),
    )
    report = _run(packs, tmp_path=tmp_path)
    assert "saved_setting_stage_contradiction" in _codes(report, "hires")


# --- 11. dangling default preset ------------------------------------------------------------


def test_dangling_default_preset_is_reported(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / ".default_preset").write_text("ghost", encoding="utf-8")
    report = _run(packs, presets_dir=presets, tmp_path=tmp_path)
    assert "dangling_default_preset" in _codes(report)


def test_valid_default_preset_is_not_flagged(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    presets = tmp_path / "presets"
    presets.mkdir()
    _write_json(presets / "real.json", {"txt2img": {}})
    (presets / ".default_preset").write_text("real", encoding="utf-8")
    report = _run(packs, presets_dir=presets, tmp_path=tmp_path)
    assert "dangling_default_preset" not in _codes(report)


def test_settings_json_is_flagged_not_audited_as_a_preset(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    presets = tmp_path / "presets"
    presets.mkdir()
    _write_json(presets / "settings.json", {"model": "one", "model_name": "two"})
    report = _run(packs, presets_dir=presets, tmp_path=tmp_path)
    assert "settings_json_surfaced_as_preset" in _codes(report)
    assert "saved_setting_alias_conflict" not in _codes(report)


# --- 12/13/14/15. asset-reference resolution classes ----------------------------------------


def _webui_with_checkpoint_and_lora(tmp_path: Path) -> Path:
    webui = tmp_path / "webui"
    _safetensors(
        webui / "models" / "Stable-diffusion" / "ckpt.safetensors",
        {"ss_base_model_version": "sd_v1.5"},
        payload=b"checkpoint-bytes",
    )
    _safetensors(
        webui / "models" / "Lora" / "goodlora.safetensors",
        {"ss_base_model_version": "sd_v1.5"},
        payload=b"lora-bytes",
    )
    return webui


def test_unique_resolved_reference_produces_no_missing_finding(tmp_path: Path) -> None:
    webui = _webui_with_checkpoint_and_lora(tmp_path)
    packs = tmp_path / "packs"
    _write_json(
        packs / "resolved.json",
        _pack(
            [{"index": 0, "text": "a", "loras": [["goodlora", 0.8]]}],
            preset_data={"txt2img": {"model": "ckpt.safetensors"}},
        ),
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    codes = _codes(report, "resolved")
    assert "resolved_unique" in codes
    assert "missing_file_backed_asset" not in codes


def test_ambiguous_same_name_reference_is_reported(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Lora" / "same.safetensors", payload=b"AAA")
    _safetensors(webui / "models" / "LyCORIS" / "same.safetensors", payload=b"BBB")
    packs = tmp_path / "packs"
    _write_json(
        packs / "ambiguous.json",
        _pack([{"index": 0, "text": "a", "loras": [["same", 0.8]]}]),
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    assert "ambiguous_same_name" in _codes(report, "ambiguous")


def test_definitely_missing_file_backed_asset_is_reported(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    (webui / "models" / "Lora").mkdir(parents=True)
    packs = tmp_path / "packs"
    _write_json(
        packs / "missing.json",
        _pack([{"index": 0, "text": "a", "loras": [["ghost_lora", 0.8]]}]),
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    assert "missing_file_backed_asset" in _codes(report, "missing")


def test_offline_unverified_when_asset_registry_coverage_unavailable(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(
        packs / "nowebui.json",
        _pack([{"index": 0, "text": "a", "loras": [["anything", 0.8]]}]),
    )
    report = _run(packs, webui_root=None, tmp_path=tmp_path)
    assert not report.asset_coverage_available
    assert "offline_unverified" in _codes(report, "nowebui")
    assert "missing_file_backed_asset" not in _codes(report, "nowebui")


# --- 16/17/18/19. family compatibility classes ------------------------------------------------


def test_same_family_compatibility_is_reported(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(
        webui / "models" / "Stable-diffusion" / "ckpt.safetensors",
        {"ss_base_model_version": "sdxl"},
        payload=b"checkpoint-bytes",
    )
    _safetensors(
        webui / "models" / "Lora" / "matching.safetensors",
        {"ss_base_model_version": "sdxl"},
        payload=b"lora-bytes",
    )
    packs = tmp_path / "packs"
    _write_json(
        packs / "compatible.json",
        _pack(
            [{"index": 0, "text": "a", "loras": [["matching", 0.8]]}],
            preset_data={"txt2img": {"model": "ckpt.safetensors"}},
        ),
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    assert "family_compatible" in _codes(report, "compatible")


def test_resolved_family_mismatch_is_reported(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Stable-diffusion" / "ckpt.safetensors", {"ss_base_model_version": "sdxl"})
    _safetensors(webui / "models" / "Lora" / "mismatched.safetensors", {"ss_base_model_version": "sd_v1.5"})
    packs = tmp_path / "packs"
    _write_json(
        packs / "mismatch.json",
        _pack(
            [{"index": 0, "text": "a", "loras": [["mismatched", 0.8]]}],
            preset_data={"txt2img": {"model": "ckpt.safetensors"}},
        ),
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    assert "family_mismatch" in _codes(report, "mismatch")


def test_asset120_unknown_profile_is_reported(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Stable-diffusion" / "ckpt.safetensors", {"ss_base_model_version": "sdxl"})
    _safetensors(webui / "models" / "Lora" / "unknown_family.safetensors")  # no metadata at all
    packs = tmp_path / "packs"
    _write_json(
        packs / "unknownfam.json",
        _pack(
            [{"index": 0, "text": "a", "loras": [["unknown_family", 0.8]]}],
            preset_data={"txt2img": {"model": "ckpt.safetensors"}},
        ),
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    assert "family_unknown" in _codes(report, "unknownfam")


def test_asset120_conflicting_profile_is_reported(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Stable-diffusion" / "ckpt.safetensors", {"ss_base_model_version": "sdxl"})
    conflicting = webui / "models" / "Lora" / "conflicting.safetensors"
    _safetensors(conflicting, {"ss_base_model_version": "sd_v1.5"})
    (conflicting.with_suffix(conflicting.suffix + ".civitai.info")).write_text(
        json.dumps({"baseModel": "SDXL 1.0"}), encoding="utf-8"
    )
    packs = tmp_path / "packs"
    _write_json(
        packs / "conflicting.json",
        _pack(
            [{"index": 0, "text": "a", "loras": [["conflicting", 0.8]]}],
            preset_data={"txt2img": {"model": "ckpt.safetensors"}},
        ),
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    assert "family_evidence_conflicting" in _codes(report, "conflicting")


# --- 20. absent explicit base-model context ---------------------------------------------------


def test_no_explicit_base_context_is_reported(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Lora" / "anylora.safetensors")
    packs = tmp_path / "packs"
    _write_json(
        packs / "nobase.json",
        _pack([{"index": 0, "text": "a", "loras": [["anylora", 0.8]]}]),  # no preset_data checkpoint
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    assert "no_explicit_base_context" in _codes(report, "nobase")
    assert "family_mismatch" not in _codes(report, "nobase")


# --- 21. disabled-stage mismatch retained but downgraded ---------------------------------------


def test_disabled_stage_mismatch_is_retained_but_downgraded(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _safetensors(webui / "models" / "Stable-diffusion" / "ckpt.safetensors", {"ss_base_model_version": "sdxl"})
    _safetensors(webui / "models" / "Stable-diffusion" / "refiner.safetensors", {"ss_base_model_version": "sd_v1.5"})
    packs = tmp_path / "packs"
    _write_json(
        packs / "dormant.json",
        _pack(
            [{"index": 0, "text": "a"}],
            preset_data={
                "txt2img": {
                    "model": "ckpt.safetensors",
                    "refiner_model_name": "refiner.safetensors",
                    "refiner_enabled": False,
                }
            },
        ),
    )
    report = _run(packs, webui_root=str(webui), tmp_path=tmp_path)
    mismatch = [f for f in report.findings if f.source_id == "dormant" and f.finding_code == "family_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0].severity == "info"
    assert "dormant" in mismatch[0].detail


# --- 22. deterministic ordering/output ----------------------------------------------------------


def test_output_is_deterministic_for_unchanged_inputs(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "b.json", _pack([{"index": 0, "text": "b"}]))
    _write_json(packs / "a.json", _pack([{"index": 0, "text": "a"}]))

    first = _run(packs, tmp_path=tmp_path).to_json_dict()
    second = _run(packs, tmp_path=tmp_path).to_json_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# --- 23. no source mutation ------------------------------------------------------------------


def test_census_does_not_mutate_source_promptpack_or_preset_files(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    presets = tmp_path / "presets"
    pack_path = packs / "keep.json"
    _write_json(pack_path, _pack([{"index": 0, "text": "a"}]))
    presets.mkdir()
    preset_path = presets / "mypreset.json"
    _write_json(preset_path, {"txt2img": {}})
    (presets / ".default_preset").write_text("mypreset", encoding="utf-8")

    watched = [pack_path, preset_path, presets / ".default_preset"]
    before = census.fingerprint_paths(watched)
    _run(packs, presets_dir=presets, tmp_path=tmp_path)
    after = census.fingerprint_paths(watched)
    assert before == after


# --- 24. no network/runtime calls (structural guarantee, exercised by design) -----------------


def test_census_never_imports_networking_or_process_launch_modules() -> None:
    import ast

    source = Path(census.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"socket", "requests", "subprocess", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & forbidden)


def test_run_census_gracefully_degrades_when_packs_dir_is_absent(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    report = _run(missing, tmp_path=tmp_path)
    assert report.pack_files_examined == 0
    assert report.findings == []


@pytest.mark.parametrize("presets_dir_present", [True, False])
def test_presets_dir_omission_degrades_gracefully(tmp_path: Path, presets_dir_present: bool) -> None:
    packs = tmp_path / "packs"
    _write_json(packs / "p.json", _pack([{"index": 0, "text": "a"}]))
    presets = (tmp_path / "presets") if presets_dir_present else None
    if presets is not None:
        presets.mkdir()
    report = _run(packs, presets_dir=presets, tmp_path=tmp_path)
    assert report.standalone_presets_examined == 0
