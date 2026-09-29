"""Deterministic fixtures for PR-PACK-130's approved missing-reference
reconciliation.

All fixtures use temporary PromptPack roots; no real user PromptPack is
used as a test fixture, and no network/A1111/Comfy/GPU call is made
anywhere in this module or the tool it tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import tools.pack130_approved_reference_reconciliation as pack130

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _write_pack(path: Path, slots: list[dict], preset_data: dict | None = None) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "pack_data": {"name": path.stem, "slots": slots}, "preset_data": preset_data or {}}
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def _sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _removal(source_id: str, pointer: str, expected_name: str, triage_item_id: str = "item") -> pack130.RemovalTarget:
    return pack130.RemovalTarget(triage_item_id, source_id, pointer, expected_name)


def _clear(source_id: str, pointer: str, expected_old_value: str = "None", triage_item_id: str = "item") -> pack130.ClearTarget:
    return pack130.ClearTarget(triage_item_id, source_id, pointer, expected_old_value)


def _source_plan(
    source_id: str,
    path: Path,
    removals: tuple[pack130.RemovalTarget, ...] = (),
    clear: pack130.ClearTarget | None = None,
) -> pack130.SourcePlan:
    return pack130.SourcePlan(source_id=source_id, expected_sha256=_sha_of(path), removals=removals, clear=clear)


def _plan(sources: tuple[pack130.SourcePlan, ...]) -> pack130.ReconciliationPlan:
    return pack130.ReconciliationPlan(sources=sources, leave_unresolved_counts={})


# --- 1/2. exact approved entries removed ---------------------------------------------------------


def test_betterthanwords_entry_removed(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    result = pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    assert result.sources_changed == ("src",)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == []


def test_babesbystableyogipony_entry_removed(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a", "loras": [["babesByStableYogiPony_xlV4", 1.0]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "babesByStableYogiPony_xlV4"),))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == []


# --- 3/4. unrelated LoRA and its weight survive unchanged -----------------------------------------


def test_unrelated_lora_and_weight_survive_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a", "loras": [["keep", 0.6864406779661016], ["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[1][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [["keep", 0.6864406779661016]]


# --- 5. DreamyStyle_xl beside a removed entry survives unchanged (real-world overlap) --------------


def test_dreamystyle_xl_beside_removed_entry_survives_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(
        path,
        [
            {
                "index": 0,
                "text": "a",
                "loras": [
                    ["add-detail-xl", 0.6864406779661016],
                    ["CinematicStyle_v1", 0.8310810810810811],
                    ["DetailedEyes_V3", 0.39375000000000004],
                    ["babesByStableYogiPony_xlV4", 1.0],
                    ["DreamyStyle_xl", 0.75],
                ],
            }
        ],
    )
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[3][0]", "babesByStableYogiPony_xlV4"),))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [
        ["add-detail-xl", 0.6864406779661016],
        ["CinematicStyle_v1", 0.8310810810810811],
        ["DetailedEyes_V3", 0.39375000000000004],
        ["DreamyStyle_xl", 0.75],
    ]


# --- 6/7. first- and middle-position removal -------------------------------------------------------


def test_first_position_removal(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5], ["keep", 1.0]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [["keep", 1.0]]


def test_middle_position_removal(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(
        path,
        [{"index": 0, "text": "a", "loras": [["keep_a", 1.0], ["babesByStableYogiPony_xlV4", 0.5], ["keep_b", 2.0]]}],
    )
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[1][0]", "babesByStableYogiPony_xlV4"),))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [["keep_a", 1.0], ["keep_b", 2.0]]


# --- 8/9. multiple removals in different slots, and highest-index-first in one list ----------------


def test_multiple_removals_in_different_slots(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(
        path,
        [
            {"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]},
            {"index": 1, "text": "b", "loras": [["keep", 1.0], ["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]},
        ],
    )
    source = _source_plan(
        "src",
        path,
        removals=(
            _removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),
            _removal("src", "pack_data.slots[1].loras[1][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),
        ),
    )
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == []
    assert saved["pack_data"]["slots"][1]["loras"] == [["keep", 1.0]]


def test_multiple_removals_in_same_list_apply_highest_index_first(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(
        path,
        [
            {
                "index": 0,
                "text": "a",
                "loras": [
                    ["keep_0", 1.0],
                    ["BetterThanWords-merged-SDXL-LoRA-v3", 0.5],
                    ["keep_2", 2.0],
                    ["babesByStableYogiPony_xlV4", 0.7],
                ],
            }
        ],
    )
    source = _source_plan(
        "src",
        path,
        removals=(
            _removal("src", "pack_data.slots[0].loras[1][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),
            _removal("src", "pack_data.slots[0].loras[3][0]", "babesByStableYogiPony_xlV4"),
        ),
    )
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["loras"] == [["keep_0", 1.0], ["keep_2", 2.0]]


# --- 10/11. only approved target names may be removed; unexpected name refuses ---------------------


@pytest.mark.parametrize(
    "kind,name",
    [("lora", "SomeOtherLora"), ("lora", "AnotherRandomLora"), ("checkpoint", "SomeModel.safetensors")],
)
def test_build_plan_refuses_unrecognized_missing_reference(kind: str, name: str) -> None:
    report = {
        "triage_items": [
            {
                "triage_item_id": "x",
                "asset_kind": kind,
                "missing_reference_name": name,
                "source_id": "src",
                "source_type": "promptpack",
                "unmapped": False,
                "occurrences": [{"pointer": "pack_data.slots[0].loras[0][0]", "raw_value": name, "source_file_sha256": "a" * 64}],
            }
        ]
    }
    with pytest.raises(pack130.PolicyRefusal):
        pack130.build_plan(report)


def test_build_plan_refuses_a_specific_unexpected_name_with_a_clear_message() -> None:
    report = {
        "triage_items": [
            {
                "triage_item_id": "x",
                "asset_kind": "lora",
                "missing_reference_name": "totally_unapproved_lora",
                "source_id": "src",
                "source_type": "promptpack",
                "unmapped": False,
                "occurrences": [{"pointer": "pack_data.slots[0].loras[0][0]", "raw_value": "totally_unapproved_lora", "source_file_sha256": "a" * 64}],
            }
        ]
    }
    with pytest.raises(pack130.PolicyRefusal, match="unrecognized missing-reference policy"):
        pack130.build_plan(report)


# --- 12. unexpected source type causes refusal ------------------------------------------------------


def test_build_plan_refuses_non_promptpack_source_type() -> None:
    report = {
        "triage_items": [
            {
                "triage_item_id": "x",
                "asset_kind": "lora",
                "missing_reference_name": "BetterThanWords-merged-SDXL-LoRA-v3",
                "source_id": "src",
                "source_type": "standalone_preset",
                "unmapped": False,
                "occurrences": [{"pointer": "loras[0][0]", "raw_value": "x", "source_file_sha256": "a" * 64}],
            }
        ]
    }
    with pytest.raises(pack130.PolicyRefusal, match="non-promptpack"):
        pack130.build_plan(report)


# --- 13. unmapped item causes refusal ----------------------------------------------------------------


def test_build_plan_refuses_unmapped_item() -> None:
    report = {
        "triage_items": [
            {
                "triage_item_id": "x",
                "asset_kind": "lora",
                "missing_reference_name": "DreamyStyle_xl",
                "source_id": "src",
                "source_type": "promptpack",
                "unmapped": True,
                "occurrences": [],
            }
        ]
    }
    with pytest.raises(pack130.PolicyRefusal, match="unmapped"):
        pack130.build_plan(report)


# --- 14. stale source SHA causes refusal --------------------------------------------------------------


def test_preflight_refuses_stale_source_sha(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    source = pack130.SourcePlan(
        source_id="src",
        expected_sha256="0" * 64,
        removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),),
    )
    with pytest.raises(pack130.PolicyRefusal, match="stale"):
        pack130.preflight_check(_plan((source,)), packs_dir=tmp_path)


# --- 15. old value missing at mapped pointer causes refusal --------------------------------------------


def test_preflight_refuses_when_expected_old_value_no_longer_present(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a", "loras": [["something_else", 0.5]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    with pytest.raises(pack130.PolicyRefusal, match="expected LoRA entry"):
        pack130.preflight_check(_plan((source,)), packs_dir=tmp_path)


# --- 16/17. literal "None" clears; non-placeholder refiner value refuses ---------------------------


def test_literal_none_refiner_clears_to_empty_string(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a"}], preset_data={"txt2img": {"refiner_checkpoint": "None"}})
    source = _source_plan("src", path, clear=_clear("src", "preset_data.txt2img.refiner_checkpoint"))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["preset_data"]["txt2img"]["refiner_checkpoint"] == ""


def test_build_plan_refuses_non_placeholder_refiner_value() -> None:
    report = {
        "triage_items": [
            {
                "triage_item_id": "x",
                "asset_kind": "refiner_checkpoint",
                "missing_reference_name": "None",
                "source_id": "src",
                "source_type": "promptpack",
                "unmapped": False,
                "occurrences": [
                    {
                        "pointer": "preset_data.txt2img.refiner_checkpoint",
                        "raw_value": "actual_refiner_model.safetensors",
                        "source_file_sha256": "a" * 64,
                    }
                ],
            }
        ]
    }
    with pytest.raises(pack130.PolicyRefusal, match="literal placeholder"):
        pack130.build_plan(report)


# --- 18. enabled-refiner safety check refuses the batch -------------------------------------------------


def test_preflight_refuses_when_refiner_is_explicitly_enabled(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(
        path,
        [{"index": 0, "text": "a"}],
        preset_data={"txt2img": {"refiner_checkpoint": "None", "refiner_enabled": True}},
    )
    source = _source_plan("src", path, clear=_clear("src", "preset_data.txt2img.refiner_checkpoint"))
    with pytest.raises(pack130.PolicyRefusal, match="refiner is explicitly enabled"):
        pack130.preflight_check(_plan((source,)), packs_dir=tmp_path)


def test_preflight_allows_clear_when_refiner_flags_are_absent(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a"}], preset_data={"txt2img": {"refiner_checkpoint": "None"}})
    source = _source_plan("src", path, clear=_clear("src", "preset_data.txt2img.refiner_checkpoint"))
    pack130.preflight_check(_plan((source,)), packs_dir=tmp_path)  # must not raise


# --- 19. DreamyStyle_xl policy is leave-only --------------------------------------------------------------


def test_dreamystyle_xl_is_recognized_as_leave_unresolved_only() -> None:
    assert pack130._POLICY[("lora", "DreamyStyle_xl")] == pack130._LEAVE_UNRESOLVED


def test_build_plan_never_creates_a_removal_or_clear_target_for_dreamystyle_xl(tmp_path: Path) -> None:
    packs_dir = tmp_path / "packs"
    report = _build_full_valid_fixture(packs_dir)
    plan = pack130.build_plan(report)

    for source in plan.sources:
        for removal in source.removals:
            assert removal.expected_name != "DreamyStyle_xl"
        if source.clear is not None:
            assert source.clear.expected_old_value != "DreamyStyle_xl"
    assert plan.leave_unresolved_counts == {"DreamyStyle_xl": (9, 63)}


# --- 20. no replacement action exists ------------------------------------------------------------------


def test_no_replacement_action_exists_in_the_policy_surface() -> None:
    assert set(pack130._POLICY.values()) == {
        pack130._REMOVE_LORA,
        pack130._CLEAR_OPTIONAL_REFINER,
        pack130._LEAVE_UNRESOLVED,
    }
    assert not hasattr(pack130, "replace_reference")
    assert not any("replace" in value for value in pack130._POLICY.values())


# --- 21. all backups complete before first write --------------------------------------------------------


def test_all_backups_complete_before_the_first_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    _write_pack(path_a, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    _write_pack(path_b, [{"index": 0, "text": "b", "loras": [["babesByStableYogiPony_xlV4", 0.5]]}])
    source_a = _source_plan("a", path_a, removals=(_removal("a", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    source_b = _source_plan("b", path_b, removals=(_removal("b", "pack_data.slots[0].loras[0][0]", "babesByStableYogiPony_xlV4"),))

    original_dump = json.dump

    def _fail_first_dump(*args, **kwargs):
        raise RuntimeError("simulated write failure on first source")

    monkeypatch.setattr(json, "dump", _fail_first_dump)
    backup_dir = tmp_path / "backup"
    with pytest.raises(RuntimeError):
        pack130.reconcile(_plan((source_a, source_b)), packs_dir=tmp_path, backup_dir=backup_dir, dry_run=False)

    # Both backups must exist even though the write loop failed on the
    # very first source.
    assert (backup_dir / "promptpack" / "a.json").is_file()
    assert (backup_dir / "promptpack" / "b.json").is_file()
    monkeypatch.setattr(json, "dump", original_dump)
    assert json.loads(path_a.read_text())["pack_data"]["slots"][0]["loras"] == [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]
    assert json.loads(path_b.read_text())["pack_data"]["slots"][0]["loras"] == [["babesByStableYogiPony_xlV4", 0.5]]


# --- 22. backup hash mismatch causes zero writes --------------------------------------------------------


def test_backup_hash_mismatch_causes_zero_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "src.json"
    document = _write_pack(path, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))

    original_write_bytes = Path.write_bytes

    def _flaky_write_bytes(self: Path, data: bytes):
        if "backup" in self.parts:
            return original_write_bytes(self, b"corrupted")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", _flaky_write_bytes)
    with pytest.raises(pack130.PolicyRefusal, match="backup verification failed"):
        pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    monkeypatch.setattr(Path, "write_bytes", original_write_bytes)
    assert json.loads(path.read_text()) == document


# --- 23. same source handled once even with multiple occurrences --------------------------------------


def test_build_plan_groups_multiple_occurrences_of_one_source_into_one_entry(tmp_path: Path) -> None:
    packs_dir = tmp_path / "packs"
    report = _build_full_valid_fixture(packs_dir)
    plan = pack130.build_plan(report)

    # "bw0" was built with 5 occurrences of BetterThanWords across 5 slots
    # of the same source; it must appear exactly once in plan.sources with
    # all 5 removals grouped together, never duplicated per occurrence.
    matching = [s for s in plan.sources if s.source_id == "bw0"]
    assert len(matching) == 1
    assert len(matching[0].removals) == 5


# --- 24. source changed between backup and write causes refusal (TOCTOU) ------------------------------


def test_source_changed_between_backup_and_write_causes_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    _write_pack(path_a, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    _write_pack(path_b, [{"index": 0, "text": "b", "loras": [["babesByStableYogiPony_xlV4", 0.5]]}])
    source_a = _source_plan("a", path_a, removals=(_removal("a", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    source_b = _source_plan("b", path_b, removals=(_removal("b", "pack_data.slots[0].loras[0][0]", "babesByStableYogiPony_xlV4"),))

    original_backup = pack130._backup_source
    tampered_b_bytes: dict[str, bytes] = {}

    def _backup_then_tamper(path, backup_dir, source_id):
        record = original_backup(path, backup_dir, source_id)
        if source_id == "b":
            # Simulate a concurrent external edit (e.g. someone editing the
            # PromptPack in the GUI) landing after this source's own backup
            # was taken but before the batch's post-backup freshness
            # re-check runs.
            path_b.write_text(path_b.read_text().replace("babesByStableYogiPony_xlV4", "somethingElse"), encoding="utf-8")
            tampered_b_bytes["value"] = path_b.read_bytes()
        return record

    monkeypatch.setattr(pack130, "_backup_source", _backup_then_tamper)
    with pytest.raises(pack130.PolicyRefusal, match="stale"):
        pack130.reconcile(_plan((source_a, source_b)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)

    # Nothing was written by our tool: source_a is fully untouched, and the
    # concurrently-edited source_b was never further overwritten (neither
    # restored nor "fixed") -- it is left exactly as the concurrent edit
    # left it, since that edit does not belong to us to undo.
    assert json.loads(path_a.read_text())["pack_data"]["slots"][0]["loras"] == [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]
    assert path_b.read_bytes() == tampered_b_bytes["value"]


# --- 25/26. atomic write failure rolls all prior sources back, byte-identical -------------------------


def test_atomic_write_failure_rolls_back_all_prior_sources_byte_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    _write_pack(path_a, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    _write_pack(path_b, [{"index": 0, "text": "b", "loras": [["babesByStableYogiPony_xlV4", 0.5]]}])
    original_a = path_a.read_bytes()
    original_b = path_b.read_bytes()
    source_a = _source_plan("a", path_a, removals=(_removal("a", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    source_b = _source_plan("b", path_b, removals=(_removal("b", "pack_data.slots[0].loras[0][0]", "babesByStableYogiPony_xlV4"),))

    original_dump = json.dump
    call_count = {"n": 0}

    def _flaky_dump(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated mid-write failure")
        return original_dump(*args, **kwargs)

    monkeypatch.setattr(json, "dump", _flaky_dump)
    with pytest.raises(RuntimeError, match="simulated mid-write failure"):
        pack130.reconcile(_plan((source_a, source_b)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    monkeypatch.setattr(json, "dump", original_dump)

    assert path_a.read_bytes() == original_a
    assert path_b.read_bytes() == original_b
    assert hashlib.sha256(path_a.read_bytes()).hexdigest() == hashlib.sha256(original_a).hexdigest()
    assert hashlib.sha256(path_b.read_bytes()).hexdigest() == hashlib.sha256(original_b).hexdigest()


# --- rollback-safety repair: rollback only restores sources this tool actually wrote --------------------


def test_rollback_preserves_unwritten_source_with_concurrent_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    path_c = tmp_path / "c.json"
    _write_pack(path_a, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    _write_pack(path_b, [{"index": 0, "text": "b", "loras": [["babesByStableYogiPony_xlV4", 0.5]]}])
    _write_pack(path_c, [{"index": 0, "text": "c", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    original_a = path_a.read_bytes()
    original_c = path_c.read_bytes()
    source_a = _source_plan("a", path_a, removals=(_removal("a", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    source_b = _source_plan("b", path_b, removals=(_removal("b", "pack_data.slots[0].loras[0][0]", "babesByStableYogiPony_xlV4"),))
    source_c = _source_plan("c", path_c, removals=(_removal("c", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))

    original_load_document = pack130._load_document
    b_load_count = {"n": 0}
    tampered_b_bytes: dict[str, bytes] = {}

    def _load_and_maybe_tamper(path: Path):
        if path.name == "b.json":
            b_load_count["n"] += 1
            # The 3rd load of "b" is the mutation loop's own load (the
            # first two are the pre-backup and post-backup/TOCTOU preflight
            # passes) -- tamper only there, simulating a concurrent editor
            # landing on "b" just before this tool would have processed it.
            if b_load_count["n"] == 3:
                path.write_text(
                    path.read_text().replace("babesByStableYogiPony_xlV4", "somethingElse"), encoding="utf-8"
                )
                tampered_b_bytes["value"] = path.read_bytes()
        return original_load_document(path)

    monkeypatch.setattr(pack130, "_load_document", _load_and_maybe_tamper)

    with pytest.raises(pack130.PolicyRefusal):
        pack130.reconcile(
            _plan((source_a, source_b, source_c)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False
        )

    # "a" was successfully replaced by this tool, then rolled back byte-exact.
    assert path_a.read_bytes() == original_a
    # "b" was never successfully replaced by this tool -- it must retain
    # the concurrent edit exactly, never restored from its pre-run backup
    # merely because it existed among the sources this run backed up.
    assert path_b.read_bytes() == tampered_b_bytes["value"]
    # "c" was never reached at all.
    assert path_c.read_bytes() == original_c


def test_failure_before_first_successful_write_restores_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    _write_pack(path_a, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    _write_pack(path_b, [{"index": 0, "text": "b", "loras": [["babesByStableYogiPony_xlV4", 0.5]]}])
    original_b = path_b.read_bytes()
    source_a = _source_plan("a", path_a, removals=(_removal("a", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    source_b = _source_plan("b", path_b, removals=(_removal("b", "pack_data.slots[0].loras[0][0]", "babesByStableYogiPony_xlV4"),))

    original_load_document = pack130._load_document
    a_load_count = {"n": 0}
    tampered_a_bytes: dict[str, bytes] = {}

    def _load_and_maybe_tamper(path: Path):
        if path.name == "a.json":
            a_load_count["n"] += 1
            if a_load_count["n"] == 3:  # the mutation loop's own load, i.e. before any write at all
                path.write_text(
                    path.read_text().replace("BetterThanWords-merged-SDXL-LoRA-v3", "somethingElse"),
                    encoding="utf-8",
                )
                tampered_a_bytes["value"] = path.read_bytes()
        return original_load_document(path)

    monkeypatch.setattr(pack130, "_load_document", _load_and_maybe_tamper)

    with pytest.raises(pack130.PolicyRefusal):
        pack130.reconcile(_plan((source_a, source_b)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)

    # Zero sources were ever successfully written, so rollback had nothing
    # to restore: "a" retains the concurrent edit, "b" is fully untouched.
    assert path_a.read_bytes() == tampered_a_bytes["value"]
    assert path_b.read_bytes() == original_b


def test_keyboard_interrupt_after_one_success_rolls_back_and_reraises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    _write_pack(path_a, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    _write_pack(path_b, [{"index": 0, "text": "b", "loras": [["babesByStableYogiPony_xlV4", 0.5]]}])
    original_a = path_a.read_bytes()
    original_b = path_b.read_bytes()
    source_a = _source_plan("a", path_a, removals=(_removal("a", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    source_b = _source_plan("b", path_b, removals=(_removal("b", "pack_data.slots[0].loras[0][0]", "babesByStableYogiPony_xlV4"),))

    original_atomic_write = pack130._atomic_write

    def _atomic_write_with_interrupt(path: Path, document):
        if path.name == "b.json":
            raise KeyboardInterrupt()
        return original_atomic_write(path, document)

    monkeypatch.setattr(pack130, "_atomic_write", _atomic_write_with_interrupt)

    with pytest.raises(KeyboardInterrupt):
        pack130.reconcile(_plan((source_a, source_b)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)

    # "a" was written then rolled back byte-exact; "b" was never touched
    # by this tool at all (the interrupt fired before its own write).
    assert path_a.read_bytes() == original_a
    assert path_b.read_bytes() == original_b


def test_rollback_conflict_when_a_replaced_source_is_modified_before_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    _write_pack(path_a, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    _write_pack(path_b, [{"index": 0, "text": "b", "loras": [["babesByStableYogiPony_xlV4", 0.5]]}])
    source_a = _source_plan("a", path_a, removals=(_removal("a", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    source_b = _source_plan("b", path_b, removals=(_removal("b", "pack_data.slots[0].loras[0][0]", "babesByStableYogiPony_xlV4"),))

    original_transform_source = pack130._transform_source
    tampered_a_bytes: dict[str, bytes] = {}

    def _transform_and_tamper(document, source):
        if source.source_id == "b":
            # A second, independent external edit lands on "a" -- a file
            # this tool already successfully wrote -- before rollback gets
            # a chance to run.
            path_a.write_text(
                path_a.read_text().replace('"text": "a"', '"text": "externally-edited-after-our-write"'),
                encoding="utf-8",
            )
            tampered_a_bytes["value"] = path_a.read_bytes()
            raise RuntimeError("simulated failure while processing b")
        return original_transform_source(document, source)

    monkeypatch.setattr(pack130, "_transform_source", _transform_and_tamper)

    with pytest.raises(pack130.RollbackConflict) as excinfo:
        pack130.reconcile(_plan((source_a, source_b)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)

    assert "a" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, RuntimeError)  # original failure never swallowed
    # Rollback must never overwrite the newer external edit to "a" -- it
    # is preserved exactly as the concurrent edit left it.
    assert path_a.read_bytes() == tampered_a_bytes["value"]


# --- 27/28. semantic-diff guard rejects prompt/unrelated setting mutation ------------------------------


def test_semantic_diff_guard_rejects_prompt_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "original prompt", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))

    original_apply_transform = pack130._apply_transform

    def _sneaky_transform(document, src):
        prefixes, keys = original_apply_transform(document, src)
        document["pack_data"]["slots"][0]["text"] = "tampered prompt"
        return prefixes, keys

    monkeypatch.setattr(pack130, "_apply_transform", _sneaky_transform)
    with pytest.raises(pack130.PolicyRefusal, match="unauthorized change"):
        pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    assert json.loads(path.read_text())["pack_data"]["slots"][0]["text"] == "original prompt"


def test_semantic_diff_guard_rejects_unrelated_setting_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "src.json"
    _write_pack(
        path,
        [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}],
        preset_data={"txt2img": {"cfg_scale": 7.0}},
    )
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))

    original_apply_transform = pack130._apply_transform

    def _sneaky_transform(document, src):
        result = original_apply_transform(document, src)
        document["preset_data"]["txt2img"]["cfg_scale"] = 99.0
        return result

    monkeypatch.setattr(pack130, "_apply_transform", _sneaky_transform)
    with pytest.raises(pack130.PolicyRefusal, match="unauthorized change"):
        pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    assert json.loads(path.read_text())["preset_data"]["txt2img"]["cfg_scale"] == 7.0


# --- 29. unknown extension fields survive ----------------------------------------------------------------


def test_unknown_extension_fields_survive(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    document = _write_pack(path, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]], "custom_extension": {"foo": "bar"}}])
    document["some_future_field"] = {"nested": [1, 2, 3]}
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    assert saved["pack_data"]["slots"][0]["custom_extension"] == {"foo": "bar"}
    assert saved["some_future_field"] == {"nested": [1, 2, 3]}


# --- 30. dry-run/preflight performs zero source writes ----------------------------------------------------


def test_dry_run_performs_zero_source_writes(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    document = _write_pack(path, [{"index": 0, "text": "a", "loras": [["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[0][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    result = pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=True)
    assert result.dry_run is True
    assert result.sources_changed == ()
    assert not (tmp_path / "backup").exists()
    assert json.loads(path.read_text()) == document


# --- 31. successful apply changes only approved fields -----------------------------------------------------


def test_successful_apply_changes_only_approved_fields(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    document = _write_pack(
        path,
        [{"index": 0, "text": "unchanged prompt", "loras": [["keep", 1.0], ["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}],
        preset_data={"txt2img": {"model": "some_checkpoint.safetensors", "cfg_scale": 7.0}},
    )
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[1][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    saved = json.loads(path.read_text())
    expected = json.loads(json.dumps(document))
    expected["pack_data"]["slots"][0]["loras"] = [["keep", 1.0]]
    assert saved == expected


# --- 32. rerunning against an already-reconciled fixture refuses/no-ops safely ------------------------------


def test_rerunning_against_an_already_reconciled_fixture_refuses_safely(tmp_path: Path) -> None:
    path = tmp_path / "src.json"
    _write_pack(path, [{"index": 0, "text": "a", "loras": [["keep", 1.0], ["BetterThanWords-merged-SDXL-LoRA-v3", 0.5]]}])
    source = _source_plan("src", path, removals=(_removal("src", "pack_data.slots[0].loras[1][0]", "BetterThanWords-merged-SDXL-LoRA-v3"),))
    pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup", dry_run=False)
    after_first = json.loads(path.read_text())
    assert after_first["pack_data"]["slots"][0]["loras"] == [["keep", 1.0]]

    # Re-running the exact same (now-stale) plan must refuse, not delete
    # "keep" or anything else.
    with pytest.raises(pack130.PolicyRefusal):
        pack130.reconcile(_plan((source,)), packs_dir=tmp_path, backup_dir=tmp_path / "backup2", dry_run=False)
    assert json.loads(path.read_text()) == after_first


# ---------------------------------------------------------------------------
# Full owner-approved-shape integration: build_plan + preflight + dry-run
# ---------------------------------------------------------------------------


def _lora_slot(name: str, weight: float = 0.5) -> dict:
    return {"index": 0, "text": "p", "loras": [[name, weight]]}


def _build_full_valid_fixture(packs_dir: Path) -> dict:
    """Build real, disposable PromptPack files reproducing the exact
    owner-approved evidence shape and return a matching triage_report
    dict: 3 items/13 occurrences of BetterThanWords, 8 items/54 occurrences
    of babes, 4 items/4 occurrences of the refiner None placeholder, and
    9 items/63 occurrences of DreamyStyle_xl (left unresolved)."""

    items: list[dict] = []

    def add_lora_group(name: str, counts: list[int], prefix: str) -> None:
        for index, count in enumerate(counts):
            source_id = f"{prefix}{index}"
            slots = [_lora_slot(name) for _ in range(count)]
            path = packs_dir / f"{source_id}.json"
            _write_pack(path, slots)
            sha = _sha_of(path)
            occurrences = [
                {"pointer": f"pack_data.slots[{slot}].loras[0][0]", "raw_value": name, "source_file_sha256": sha}
                for slot in range(count)
            ]
            items.append(
                {
                    "triage_item_id": f"{source_id}_item",
                    "asset_kind": "lora",
                    "missing_reference_name": name,
                    "source_id": source_id,
                    "source_type": "promptpack",
                    "unmapped": False,
                    "occurrences": occurrences,
                }
            )

    add_lora_group("BetterThanWords-merged-SDXL-LoRA-v3", [5, 1, 7], "bw")
    add_lora_group("babesByStableYogiPony_xlV4", [10, 8, 7, 7, 6, 6, 5, 5], "babes")
    add_lora_group("DreamyStyle_xl", [7, 7, 7, 7, 7, 7, 7, 7, 7], "dreamy")

    for index in range(4):
        source_id = f"ref{index}"
        path = packs_dir / f"{source_id}.json"
        _write_pack(path, [{"index": 0, "text": "p"}], preset_data={"txt2img": {"refiner_checkpoint": "None"}})
        sha = _sha_of(path)
        items.append(
            {
                "triage_item_id": f"{source_id}_item",
                "asset_kind": "refiner_checkpoint",
                "missing_reference_name": "None",
                "source_id": source_id,
                "source_type": "promptpack",
                "unmapped": False,
                "occurrences": [
                    {"pointer": "preset_data.txt2img.refiner_checkpoint", "raw_value": "None", "source_file_sha256": sha}
                ],
            }
        )

    return {"schema_version": 1, "source_sha": "sha", "census_finding_count": 24, "triage_item_count": 24, "triage_items": items}


def test_full_owner_approved_shape_builds_and_preflights_cleanly(tmp_path: Path) -> None:
    packs_dir = tmp_path / "packs"
    report = _build_full_valid_fixture(packs_dir)

    plan = pack130.build_plan(report)
    summary = plan.summary()
    assert summary["actionable_source_count"] == 15
    assert summary["lora_removal_occurrences"] == 67
    assert summary["refiner_clear_occurrences"] == 4
    assert summary["total_occurrence_actions"] == 71
    assert summary["leave_unresolved_counts"] == {"DreamyStyle_xl": (9, 63)}

    pack130.preflight_check(plan, packs_dir=packs_dir)  # must not raise

    result = pack130.reconcile(plan, packs_dir=packs_dir, backup_dir=tmp_path / "backup", dry_run=True)
    assert result.dry_run is True
    assert result.sources_changed == ()

    real_result = pack130.reconcile(plan, packs_dir=packs_dir, backup_dir=tmp_path / "backup_real", dry_run=False)
    assert len(real_result.sources_changed) == 15
    assert len(real_result.backups) == 15

    # Every DreamyStyle_xl source is untouched.
    for index in range(9):
        saved = json.loads((packs_dir / f"dreamy{index}.json").read_text())
        assert saved["pack_data"]["slots"][0]["loras"] == [["DreamyStyle_xl", 0.5]]

    for index, count in enumerate([5, 1, 7]):
        saved = json.loads((packs_dir / f"bw{index}.json").read_text())
        assert all(slot["loras"] == [] for slot in saved["pack_data"]["slots"])
        assert len(saved["pack_data"]["slots"]) == count

    for index in range(4):
        saved = json.loads((packs_dir / f"ref{index}.json").read_text())
        assert saved["preset_data"]["txt2img"]["refiner_checkpoint"] == ""


def test_full_owner_approved_shape_refuses_if_a_count_drifts(tmp_path: Path) -> None:
    packs_dir = tmp_path / "packs"
    report = _build_full_valid_fixture(packs_dir)
    # Drop one BetterThanWords occurrence to simulate source state drifting
    # away from the owner-reviewed evidence.
    for item in report["triage_items"]:
        if item["source_id"] == "bw0":
            item["occurrences"].pop()
            break
    with pytest.raises(pack130.PolicyRefusal, match="BetterThanWords"):
        pack130.build_plan(report)


# ---------------------------------------------------------------------------
# No network/runtime import
# ---------------------------------------------------------------------------


def test_tool_performs_no_network_or_runtime_call() -> None:
    import ast

    source = Path(pack130.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"socket", "requests", "subprocess", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & forbidden)
