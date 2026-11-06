"""PR-QUAL-SYSTEM-840 ledger: completeness, evidence rules, current-vs-historical precedence (CPU only, no host)."""

from __future__ import annotations

import copy

import pytest

from tools.qualification.system840 import host_inventory
from tools.qualification.system840.arms import ARM_BY_ID, ARMS
from tools.qualification.system840.ledger import (
    Entry,
    Ledger,
    applicable_physical,
    derive_status,
    evidence_applies,
    is_failed_attempt,
    load_ledger,
    reconcile_with_live,
    summarize,
    validate_ledger,
)
from tools.qualification.system840.statuses import STATUS_DEFINITIONS, Status


@pytest.fixture(scope="module")
def ledger() -> Ledger:
    return load_ledger()


def _mutated(ledger: Ledger, capability: str, change) -> Ledger:
    document = copy.deepcopy(ledger.document)
    for cap in document["capabilities"]:
        if cap["id"] == capability:
            change(cap)
    return Ledger(document)


def test_shipped_ledger_is_valid_and_complete(ledger: Ledger) -> None:
    assert validate_ledger(ledger) == []
    assert {arm.arm_id for arm in ARMS} == {e.arm for e in ledger}  # every arm has a capability
    assert set(STATUS_DEFINITIONS) == set(Status)  # every status is defined
    assert len(ARM_BY_ID) == 15


def test_no_capability_is_qualified_and_nothing_is_inferred(ledger: Ledger) -> None:
    summary = summarize(ledger)
    assert "QUALIFIED" not in summary["by_status"]
    for entry in ledger:
        if entry.status in (Status.NOT_TESTED,):
            assert not applicable_physical(entry)
        assert derive_status(entry) == entry.status or entry.status in (
            Status.HOLD,
            Status.NO_GO,
            Status.UNSUPPORTED,
            Status.INCONCLUSIVE,
        )


def test_known_holds_and_verdicts_are_preserved(ledger: Ledger) -> None:
    expectations = {
        "IMG-Q1.zimage-turbo-fp8": Status.HOLD,
        "IMG-Q1.klein-base-9b": Status.NO_GO,
        "IMG-Q4.forge-vs-comfy-still": Status.HOLD,
        "VID-Q4.wan-a14b-480p": Status.INCONCLUSIVE,
        "VID-Q2.fun-control-5b-canny": Status.FEASIBLE,
        "VID-Q1.svd-xt-native": Status.NOT_TESTED,  # approved by statement; never inferred qualified
        "AI-Q1.lfm3-1.7b-q4_k_m-liquidai": Status.HOLD,
        "AI-Q2.prompt-suggest-integration": Status.HOLD,
    }
    for capability, status in expectations.items():
        entry = ledger.get(capability)
        assert entry is not None and entry.status == status, capability


def test_qwen_and_lfm3_authorizations_are_separate(ledger: Ledger) -> None:
    ids = {e.identity["model_id"] for e in ledger.for_arm("AI-Q1")}
    assert {"qwen3.5-4b-q4_k_m-unsloth", "lfm3-1.7b-q4_k_m-liquidai"} <= ids
    assert len(ids) == len(ledger.for_arm("AI-Q1"))  # one candidate per entry, never a shared grant


def test_live_catalog_and_registry_agree_with_the_ledger(ledger: Ledger) -> None:
    assert reconcile_with_live(ledger) == []


def test_live_state_outranks_a_stale_recorded_claim(ledger: Ledger) -> None:
    stale = _mutated(
        ledger,
        "VID-Q0.wan22-ti2v-5b-1.3.0",
        lambda c: c["governance"].update(state="experimental (stale record)"),
    )
    drift = reconcile_with_live(stale)
    assert any(
        d["capability"] == "VID-Q0.wan22-ti2v-5b-1.3.0" and d["live"] == "approved" for d in drift
    )
    wrong_hash = _mutated(
        ledger,
        "AI-Q1.qwen3.5-4b-q4_k_m-unsloth",
        lambda c: c["identity"].update(model_sha256="0" * 64),
    )
    assert any(d["field"] == "model_sha256" for d in reconcile_with_live(wrong_hash))


def test_registry_qualification_flag_contradicting_the_ledger_is_drift(
    ledger: Ledger, monkeypatch
) -> None:
    from tools.qualification.system840 import ledger as ledger_module

    real = ledger_module._ai_registry

    def lying(repo_root):
        registry = real(repo_root)
        registry["qwen3.5-4b-q4_k_m-unsloth"] = {
            **registry["qwen3.5-4b-q4_k_m-unsloth"],
            "qualified": True,
        }
        return registry

    monkeypatch.setattr(ledger_module, "_ai_registry", lying)
    assert any(d["field"] == "qualified" for d in reconcile_with_live(ledger))


def test_physical_evidence_needs_an_exact_source(ledger: Ledger) -> None:
    def strip(cap):
        cap["evidence"][0].pop("exact_source")

    problems = validate_ledger(_mutated(ledger, "IMG-Q0.sdxl-forge-baseline", strip))
    assert any("exact source" in p for p in problems)


def test_evidence_for_another_identity_does_not_count(ledger: Ledger) -> None:
    entry = ledger.get("IMG-Q1.klein-4b-fp8")
    assert entry is not None
    other = {"model_sha256": "f" * 64}
    assert not evidence_applies({"applies_to": other}, entry.identity)
    changed = _mutated(
        ledger,
        "VID-Q0.wan22-ti2v-5b-1.2.0",
        lambda c: c["identity"].update(workflow="wan22_ti2v_5b_i2v_v1@9.9.9"),
    )
    problems = validate_ledger(changed)
    assert any(
        "without applicable physical evidence" in p for p in problems
    )  # a new revision starts untested


def test_offline_or_ci_evidence_cannot_produce_a_physical_status(ledger: Ledger) -> None:
    def overclaim(cap):
        cap["status"] = "FEASIBLE"

    problems = validate_ledger(_mutated(ledger, "VID-Q1.svd-xt-native", overclaim))
    assert any("supports NOT TESTED" in p for p in problems)

    def dims(cap):
        cap["qualification"]["resource"] = "PARTIALLY QUALIFIED"

    assert any(
        "without applicable physical evidence" in p
        for p in validate_ledger(_mutated(ledger, "VID-Q1.svd-xt-native", dims))
    )


def test_qualified_needs_verified_gui_production_evidence(ledger: Ledger) -> None:
    def promote(cap):
        cap["qualification"] = {
            "resource": "QUALIFIED",
            "quality": "QUALIFIED",
            "integration": "QUALIFIED",
        }
        cap["status"] = "QUALIFIED"

    problems = validate_ledger(_mutated(ledger, "IMG-Q0.sdxl-forge-baseline", promote))
    assert any("operator GUI" in p for p in problems)

    def promote_unverified(cap):
        promote(cap)
        cap["evidence"][0]["surface"] = "gui"
        cap["evidence"][1]["exact_source"] = "unverified: no sha"

    problems = validate_ledger(_mutated(ledger, "IMG-Q0.sdxl-forge-baseline", promote_unverified))
    assert any("unverified source" in p for p in problems)


def test_a_failed_gui_attempt_is_history_not_qualifying_gui_evidence(ledger: Ledger) -> None:
    """IMG-Q0 e5 is the NO-GO GUI attempt of 2026-11-05: it is on record and must never satisfy the GUI requirement."""

    entry = ledger.get("IMG-Q0.sdxl-forge-baseline")
    assert entry is not None
    e5 = next(e for e in entry.evidence if e["id"] == "e5")
    assert e5["surface"] == "gui" and e5 in applicable_physical(entry)
    assert is_failed_attempt(e5) and not is_failed_attempt(
        {"result": "CANONICAL_FORGE_BASELINE_PASS"}
    )
    assert entry.status == Status.PARTIALLY_QUALIFIED and entry.data["next_test"]["blocked"] is True

    def promote(cap):
        cap["qualification"] = {
            "resource": "QUALIFIED",
            "quality": "QUALIFIED",
            "integration": "QUALIFIED",
        }
        cap["status"] = "QUALIFIED"

    problems = validate_ledger(_mutated(ledger, "IMG-Q0.sdxl-forge-baseline", promote))
    assert any("operator GUI" in p for p in problems)


def test_hold_must_name_a_standing_hold_and_non_executable_has_no_authorizable_test(
    ledger: Ledger,
) -> None:
    def no_holds(cap):
        cap["holds"] = []

    assert any(
        "must name its holds" in p
        for p in validate_ledger(_mutated(ledger, "IMG-Q1.zimage-turbo-fp8", no_holds))
    )

    def unknown_hold(cap):
        cap["holds"] = ["HOLD-NOT-A-THING"]

    assert any(
        "not a standing hold" in p
        for p in validate_ledger(_mutated(ledger, "IMG-Q1.zimage-turbo-fp8", unknown_hold))
    )

    def authorizable(cap):
        cap["next_test"]["admissible"] = True
        cap["next_test"]["needs_owner_authorization"] = True

    assert any(
        "authorizable next test" in p
        for p in validate_ledger(_mutated(ledger, "IMG-Q1.zimage-turbo-fp8", authorizable))
    )


def test_missing_citation_and_arm_coverage_are_reported(ledger: Ledger) -> None:
    def bad_path(cap):
        cap["sources"] = ["docs/does/not/exist.md"]

    assert any(
        "does not exist" in p
        for p in validate_ledger(_mutated(ledger, "IMG-Q0.sdxl-forge-baseline", bad_path))
    )
    document = copy.deepcopy(ledger.document)
    document["capabilities"] = [c for c in document["capabilities"] if c["arm_id"] != "VID-Q4"]
    assert any("VID-Q4 has no capability" in p for p in validate_ledger(Ledger(document)))


def test_entry_wrapper_exposes_dimensions(ledger: Ledger) -> None:
    entry = ledger.get("IMG-Q0.sdxl-forge-baseline")
    assert isinstance(entry, Entry)
    assert entry.dimension("quality") == Status.NOT_TESTED


def test_host_inventory_reports_missing_present_and_mismatched(tmp_path, ledger: Ledger) -> None:
    entry = ledger.get("AI-Q1.qwen3.5-4b-q4_k_m-unsloth")
    assert entry is not None
    root = tmp_path / "models"
    root.mkdir()
    report = host_inventory.installed_assets(ledger, [root])
    assert {r["state"] for r in report if r["capability"] == entry.id} == {"MISSING"}
    (root / "Qwen3.5-4B-Q4_K_M.gguf").write_bytes(b"too small")
    report = host_inventory.installed_assets(ledger, [root], hash_files=True)
    item = next(r for r in report if r["capability"] == entry.id)
    assert item["state"] == "IDENTITY_MISMATCH" and item["size_matches"] is False
    assert all("download" not in str(v).lower() or "never" in str(v).lower() for v in item.values())


def test_runtime_pins_are_read_only_facts() -> None:
    pins = host_inventory.runtime_pins()
    assert pins["config/managed_comfy_runtime.json"] is not None
