"""AI-QUAL-115: the frozen LFM3 qualification contract, on synthetic data only.

No artifact is downloaded, extracted or executed, no model is loaded and no telemetry is real. These tests prove that the
contract is deterministic, leaves the Qwen evidence and production configuration untouched, and fails closed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from src.ai_assist.argv import (
    ALLOWED_FLAGS,
    FORBIDDEN_FLAGS,
    RunLimits,
    assert_argv_allowed,
    build_argv,
)
from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.manifests import (
    ModelRegistry,
    RuntimeManifest,
    load_model_registry,
    load_runtime_manifest,
    record_active,
    verify_installation,
)
from src.ai_assist.status import (
    MODEL_REGISTRY_PATH,
    RUNTIME_MANIFEST_PATH,
    STATE_NOT_INSTALLED,
    read_status,
)
from tools.qualification.ai111 import lfm3_contract as lfm3
from tools.qualification.ai111 import stage_a_report as report
from tools.qualification.ai111.baselines import ARMS
from tools.qualification.ai111.corpus import corpus_digest
from tools.qualification.ai111.final_plan import evaluate_final_gates, final_corpus, final_plan
from tools.qualification.ai111.plan import digest, frozen_plan
from tools.qualification.ai111.scoring import summarize_arm

GOLDEN_CONTRACT_SHA256 = "8119804fa062308a11c5bf55c2b9812bc20dff04016eab50b64095781268fad5"
GOLDEN_STAGE_A_IDS_SHA256 = "d0bbf7feabc5bd533130d2ab044cbe351218a47b2a0c7dd7edbbc5eb8e97d030"

DOC = lfm3.contract()
PRODUCTION = load_model_registry(MODEL_REGISTRY_PATH)
Q4 = copy.deepcopy(DOC["candidates"][0])


# -- determinism and preservation of the Qwen evidence ------------------------------------------------------------------


def test_the_contract_is_deterministic_and_pinned() -> None:
    assert lfm3.contract() == DOC
    assert (
        lfm3.contract_digest() == lfm3.contract_digest(DOC) == digest(DOC) == GOLDEN_CONTRACT_SHA256
    )
    assert lfm3.validate_contract(DOC) == []
    assert digest(DOC["stages"]["A"]["case_ids_sha256"]) != GOLDEN_CONTRACT_SHA256
    assert DOC["stages"]["A"]["case_ids_sha256"] == GOLDEN_STAGE_A_IDS_SHA256
    changed = copy.deepcopy(DOC)
    changed["stages"]["thresholds"]["refusal_rate_max"] = 0.5
    assert digest(changed) != GOLDEN_CONTRACT_SHA256


def test_the_qwen_plan_corpus_and_digests_are_unchanged() -> None:
    assert digest(frozen_plan()) == lfm3.QWEN_FROZEN["screening_plan_sha256"]
    assert digest(final_plan()) == lfm3.QWEN_FROZEN["final_plan_sha256"]
    assert corpus_digest(final_corpus()) == lfm3.QWEN_FROZEN["final_corpus_sha256"]
    assert DOC["qwen_preserved"] == lfm3.QWEN_FROZEN
    assert "lfm3" not in json.dumps(frozen_plan()).lower()
    broken = copy.deepcopy(DOC)
    broken["qwen_preserved"]["final_corpus_sha256"] = "0" * 64
    assert "Qwen plan, corpus or digests changed" in lfm3.validate_contract(broken)


def test_production_configuration_is_untouched_and_never_names_lfm3() -> None:
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    assert not registry.problems
    assert all(
        not e.model_id.startswith("lfm3-") and e.qualified is False for e in registry.entries
    )
    assert "lfm3" not in MODEL_REGISTRY_PATH.read_text(encoding="utf-8").lower()
    manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    assert manifest.builds == () and not manifest.problems
    assert "ai_model_registry" not in json.dumps(
        DOC["candidates"]
    )  # candidates live in the contract only


def test_the_contract_authorizes_nothing_and_promotes_nothing() -> None:
    assert DOC["status"] == "FROZEN_PROPOSAL_UNAPPROVED"
    assert set(DOC["authorization"]) == set(DOC["approvals"]) and not any(
        DOC["authorization"].values()
    )
    assert all(c["qualified"] is False for c in DOC["candidates"])
    granted = copy.deepcopy(DOC)
    granted["authorization"]["S3_stage_a"] = True
    assert "a contract may not carry a granted authorization" in lfm3.validate_contract(granted)
    assert "outside this contract" in DOC["promotion"]


# -- candidate metadata, provenance and licence ------------------------------------------------------------------------------


def test_pinned_candidates_are_internally_consistent_and_revision_locked() -> None:
    assert [lfm3.candidate_problems(c, PRODUCTION) for c in DOC["candidates"]] == [[], []]
    for entry in DOC["candidates"]:
        provenance = entry["provenance"]
        assert provenance["publisher_revision"] == lfm3.PUBLISHER_REVISION
        assert provenance["packager_revision"] == lfm3.PACKAGER_REVISION
        assert provenance["packager_revision"] in provenance["source_url"]
        assert provenance["source_url"].endswith(entry["filename"])
    sizes = {c["quantization"]: c["bytes"] for c in DOC["candidates"]}
    assert sizes == {"Q4_K_M": 1099627808, "Q8_0": 1846238496}


def _mutated(mutation: Any) -> dict[str, Any]:
    entry = copy.deepcopy(Q4)
    mutation(entry)
    return entry


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e.update(qualified=True),
        lambda e: e.update(architecture="qwen3_5"),
        lambda e: e.update(model_id="qwen-lfm3-impostor"),
        lambda e: e.update(sha256="0" * 64),
        lambda e: e.update(sha256=e["sha256"].upper()),
        lambda e: e.update(bytes=e["bytes"] + 1),
        lambda e: e.update(bytes=0),
        lambda e: e.update(filename="LFM3-1.7B-Q6_K.gguf"),
        lambda e: e.update(filename="../LFM3-1.7B-Q4_K_M.gguf"),
        lambda e: e.update(license_spdx="Apache-2.0"),
        lambda e: e.update(license_spdx=""),
        lambda e: e["provenance"].update(packager_revision="main"),
        lambda e: e["provenance"].update(
            publisher_revision=e["provenance"]["publisher_revision"][:39]
        ),
        lambda e: e["provenance"].update(packager_repo="someone/else-GGUF"),
        lambda e: e["provenance"].update(source_url="http://huggingface.co/x/resolve/y/f.gguf"),
        lambda e: e["provenance"].update(
            source_url=e["provenance"]["source_url"].replace("resolve", "blob")
        ),
        lambda e: e["provenance"].pop("converter"),
        lambda e: e.pop("provenance"),
    ],
)
def test_candidate_metadata_fails_closed(mutation: Any) -> None:
    assert lfm3.candidate_problems(_mutated(mutation), PRODUCTION)


def test_a_candidate_that_collides_with_production_is_refused() -> None:
    qwen = PRODUCTION.entries[0]
    collision = _mutated(lambda e: e.update(sha256=qwen.sha256))
    assert any(
        "differs" in p or "collides" in p for p in lfm3.candidate_problems(collision, PRODUCTION)
    )
    seeded = ModelRegistry(
        entries=(load_model_registry(json.dumps({"schema_version": 1, "models": [Q4]})).entries[0],)
    )
    assert "candidate collides with a production registry entry" in lfm3.candidate_problems(
        Q4, seeded
    )


def test_licence_is_recorded_hash_bound_and_blocks_until_acknowledged() -> None:
    record = DOC["license"]
    assert record["spdx"] == "LicenseRef-LFM-Open-License-1.0"
    assert record["commercial_use_threshold_usd_annual_revenue"] == 10_000_000
    assert lfm3.license_problems(record, require_acknowledged=False) == []
    assert lfm3.license_problems(record, require_acknowledged=True) == [
        "licence not acknowledged by the owner"
    ]
    assert (
        lfm3.license_problems({**record, "owner_acknowledged": True}, require_acknowledged=True)
        == []
    )
    assert lfm3.license_problems({**record, "text_sha256": "1" * 64}, require_acknowledged=False)
    assert lfm3.license_problems(
        {**record, "owner_acknowledgement_required": False}, require_acknowledged=False
    )
    assert lfm3.license_problems(
        {k: v for k, v in record.items() if k != "name"}, require_acknowledged=False
    )


# -- runtime candidates -------------------------------------------------------------------------------------------------------


def test_runtime_selection_is_b11960_and_b11938_is_evaluated_but_not_selected() -> None:
    candidates = DOC["runtime"]["candidates"]
    assert DOC["runtime"]["selected"] == "b11960"
    assert candidates["b11960"]["selected"] is True and candidates["b11938"]["selected"] is False
    assert "below the publisher's stated minimum" in candidates["b11938"]["lfm3_text_support"]
    for tag, entry in candidates.items():
        assert lfm3.runtime_problems(entry, require_members=False) == [], tag
        assert lfm3.runtime_problems(entry, require_members=True) == [
            "launchable member hashes are not recorded"
        ]
    both = copy.deepcopy(DOC)
    both["runtime"]["candidates"]["b11938"]["selected"] = True
    assert "exactly the selected runtime must be marked selected" in lfm3.validate_contract(both)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e.update(compute="cuda"),
        lambda e: e.update(asset="llama-b11960-bin-win-cuda-12.4-x64.zip"),
        lambda e: e.update(sha256="abc"),
        lambda e: e.update(commit="deadbeef"),
        lambda e: e.update(bytes=-1),
        lambda e: e.update(source_url="https://example.invalid/llama.zip"),
        lambda e: e.update(license="GPL-3.0-only"),
    ],
)
def test_runtime_metadata_fails_closed(mutation: Any) -> None:
    entry = copy.deepcopy(DOC["runtime"]["candidates"]["b11960"])
    mutation(entry)
    assert lfm3.runtime_problems(entry, require_members=False)


# -- closed command line ------------------------------------------------------------------------------------------------------


def test_lfm3_argv_is_the_production_prefix_plus_the_exact_vendor_sampling() -> None:
    model, prompt, schema = Path("m.gguf"), Path("p.txt"), Path("s.json")
    argv = lfm3.lfm3_argv("lfm3_vendor", model, prompt, schema)
    production = build_argv(model, prompt, schema, RunLimits())
    assert argv[:22] == production[:22]  # everything up to and including -t <threads>
    assert argv[22:] == [
        "--temp", "0.1", "--top-k", "50", "--top-p", "1.0", "--min-p", "0.0",
        "--repeat-penalty", "1.1", "--presence-penalty", "0.0", "--seed", "321",
    ]  # fmt: skip
    assert "--presence-penalty" in argv and argv[argv.index("--presence-penalty") + 1] == "0.0"
    assert not set(argv) & FORBIDDEN_FLAGS
    no_repeat = lfm3.lfm3_argv("lfm3_no_repeat", model, prompt, schema)
    assert no_repeat[no_repeat.index("--repeat-penalty") + 1] == "1.0"
    assert lfm3.lfm3_argv("lfm3_vendor", model, prompt, schema) == argv


def test_the_production_vocabulary_and_qwen_argv_are_unchanged() -> None:
    assert not lfm3.EXTRA_FLAGS & ALLOWED_FLAGS
    with pytest.raises(ValueError):
        assert_argv_allowed(["--repeat-penalty", "1.1"])  # the production default stays closed
    with pytest.raises(ValueError):
        assert_argv_allowed(["--min-p", "0.0"])
    production = build_argv(Path("m.gguf"), Path("p.txt"), Path("s.json"), RunLimits())
    assert "--repeat-penalty" not in production and "--min-p" not in production
    assert production[22:] == [
        "--temp", "0.7", "--top-p", "0.8", "--top-k", "20", "--presence-penalty", "1.5", "--seed", "321",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "extra",
    [
        ["-hf", "LiquidAI/LFM3-1.7B-GGUF"],
        ["--model-url", "https://x"],
        ["--host", "0.0.0.0"],
        ["--lora", "a.gguf"],
        ["--mmproj", "m.gguf"],
        ["--not-a-flag", "1"],
        ["-cnv"],
    ],
)
def test_the_lfm3_vocabulary_is_closed(extra: list[str]) -> None:
    argv = lfm3.lfm3_argv("lfm3_vendor", Path("m.gguf"), Path("p.txt"), Path("s.json"))
    with pytest.raises(ValueError):
        assert_argv_allowed([*argv, *extra], lfm3.LFM3_ALLOWED_FLAGS)


def test_an_unknown_sampling_profile_is_refused() -> None:
    with pytest.raises(ValueError):
        lfm3.lfm3_argv("qwen_frozen", Path("m.gguf"), Path("p.txt"), Path("s.json"))


def test_help_text_must_list_every_flag_the_contract_emits() -> None:
    full = " ".join(sorted(lfm3.LFM3_ALLOWED_FLAGS))
    assert lfm3.help_flag_report(full, truncated=False)["verdict"] == "PASS"
    short = full.replace("--repeat-penalty", "")
    assert lfm3.help_flag_report(short, truncated=False) == {
        "verdict": "FAIL",
        "missing": ["--repeat-penalty"],
        "truncated": False,
    }
    assert lfm3.help_flag_report(short, truncated=True)["verdict"] == "INCONCLUSIVE"
    assert lfm3.help_flag_report("   ", truncated=False)["verdict"] == "INCONCLUSIVE"


# -- arms, comparison and approval boundary ----------------------------------------------------------------------------------


def test_every_executable_arm_shares_one_runtime_and_has_a_matched_qwen_comparator() -> None:
    arms = {a["arm_id"]: a for a in DOC["arms"]}
    executable = [a for a in DOC["arms"] if a["kind"] != "baseline"]
    assert {a["runtime"] for a in executable} == {"b11960"}
    for lfm, qwen in lfm3.COMPARATORS.items():
        arm = arms[f"{lfm}@lfm3_vendor"]
        comparator = arms[arm["matched_comparator"]]
        assert comparator["model"]["model_id"] == qwen
        assert comparator["sampling"] == "qwen_frozen"
        assert comparator["model"]["sha256"] == next(
            e.sha256 for e in PRODUCTION.entries if e.model_id == qwen
        )
        assert comparator["model"]["quantization"] == arm_quant(lfm)
    assert arms["lfm3-1.7b-q4_k_m-liquidai@lfm3_no_repeat"]["stages"] == ["A"]
    drifted = copy.deepcopy(DOC)
    drifted["arms"][1]["runtime"] = "b11840"
    assert any("confounded" in p for p in lfm3.validate_contract(drifted))


def arm_quant(model_id: str) -> str:
    return next(c["quantization"] for c in DOC["candidates"] if c["model_id"] == model_id)


def _approval(step: str, document: dict[str, Any] = DOC, drop: str = "") -> str:
    names = DOC["approvals"][step]["artifacts"]
    tokens = [t for a in names for t in lfm3._artifact_tokens(a, document)]
    text = f"I approve {step} for contract {digest(document)}: " + " ".join(tokens)
    return text.replace(drop, "") if drop else text


@pytest.mark.parametrize("step", sorted(DOC["approvals"]))
def test_each_approval_must_name_its_step_this_digest_and_every_artifact(step: str) -> None:
    assert lfm3.approval_problems(step, _approval(step)) == []
    assert (
        lfm3.approval_problems(step, _approval(step).upper()) == []
    )  # case-insensitive identity match
    assert lfm3.approval_problems(step, "") == ["empty approval"]
    assert lfm3.approval_problems(step, _approval(step, drop=digest(DOC)))
    stale = copy.deepcopy(DOC)
    stale["stages"]["thresholds"]["latency_median_seconds_max"] = 99.0
    assert lfm3.approval_problems(
        step, _approval(step, stale)
    )  # an approval of an altered contract is stale
    assert lfm3.approval_problems(step, _approval(step).replace(step, "S9"))
    for artifact in DOC["approvals"][step]["artifacts"]:
        token = lfm3._artifact_tokens(artifact, DOC)[0]
        assert lfm3.approval_problems(step, _approval(step, drop=token))


def test_an_approval_for_one_step_or_for_qwen_never_satisfies_another() -> None:
    assert lfm3.approval_problems("S3_stage_a", _approval("S0_download"))
    qwen_only = f"approve S3_stage_a {lfm3.QWEN_FROZEN['final_plan_sha256']} {lfm3.QWEN_FROZEN['final_corpus_sha256']}"
    assert lfm3.approval_problems("S3_stage_a", qwen_only)
    assert lfm3.approval_problems("S5_promotion", "anything") == [
        "unknown approval step: S5_promotion"
    ]
    assert "S5_promotion" not in DOC["approvals"]


def test_readiness_fails_closed_on_missing_unknown_or_non_boolean_evidence() -> None:
    assert lfm3.readiness_blockers("S3_stage_a", {}) == [
        "approval_S3_stage_a",
        "license_acknowledged",
        "d12a_b11960_pass",
        "member_hashes_recorded",
        "harness_supports_contract",
        "protected_runtime",
        "canary_proof_current",
        "firewall_attested",
        "quiet_host",
    ]
    truthy_but_not_true = dict.fromkeys(lfm3.readiness_blockers("S3_stage_a", {}), "yes")
    assert lfm3.readiness_blockers("S3_stage_a", truthy_but_not_true) == list(truthy_but_not_true)
    everything = dict.fromkeys(truthy_but_not_true, True)
    assert lfm3.readiness_blockers("S3_stage_a", everything) == []
    assert lfm3.readiness_blockers("S9", everything) == ["unknown stage: S9"]
    assert set(lfm3.KNOWN_BLOCKERS) >= {
        "launchable_member_hashes_unrecorded_for_b11960",
        "harness_pinned_to_b11840_single_runtime_single_sampling",
        "license_not_acknowledged",
        "owner_approvals_absent",
    }


# -- records, synthetic telemetry and scoring --------------------------------------------------------------------------------


STAGE_A = [c for c in final_corpus() if c.case_id in set(lfm3.stage_a_case_ids())]
BY_ID = {c.case_id: c for c in STAGE_A}
ARM = "lfm3-1.7b-q4_k_m-liquidai@lfm3_vendor"


def _row(case: Any, index: int, **overrides: Any) -> dict[str, Any]:
    produced = ARMS["B1_engine"](case)
    if case.canary:
        produced = {
            k: v.replace(case.canary, "") if isinstance(v, str) else v for k, v in produced.items()
        }
    row: dict[str, Any] = {
        "case_id": case.case_id,
        "arm": ARM,
        "outcome": case.expected_outcome or "suggestion",
        "reason": "",
        "elapsed_ms": 6000,
        "positive": produced.get("positive"),
        "negative": produced.get("negative"),
        "choice": case.oracle or produced.get("choice"),
        "details": {
            "child_observed": True,
            "priority_verified": True,
            "observed_priority_class": 0x4000,
            "peak_tree_private_gib": 2.4,
            "peak_tree_working_set_gib": 2.2,
            "tree_cpu_seconds": 30.0,
            "max_tree_processes": 1,
            "egress_connections": 0,
        },
        "started_utc": f"2026-10-30T12:{index % 60:02d}:00+00:00",
        "ended_utc": f"2026-10-30T12:{index % 60:02d}:10+00:00",
        "phase": "cold" if index == 0 else "warm",
        "contract_sha256": digest(DOC),
        "sampling_profile": "lfm3_vendor",
        "runtime_asset_sha256": DOC["runtime"]["candidates"]["b11960"]["sha256"],
    }
    row.update(overrides)
    return row


def _rows(**overrides: Any) -> list[dict[str, Any]]:
    return [_row(c, i, **overrides) for i, c in enumerate(STAGE_A)]


def _judge(
    rows: list[dict[str, Any]], *, teardown: bool = True, violations: tuple[str, ...] = ()
) -> dict[str, Any]:
    summary = summarize_arm(BY_ID, rows)
    metrics = report.arm_metrics(ARM, rows, summary, BY_ID, [])
    session = {
        "teardown_verified": teardown,
        "violations": list(violations),
        "channels_lifetime_complete": True,
        "abort_reason": "",
    }
    probes = [{"stopped_as_intended": True, "teardown_verified": True}]
    return report.judge_arm(
        metrics,
        thresholds=DOC["stages"]["thresholds"],
        session=session,
        probes=probes,
        integrity_after=[],
        compatibility_verdict="PASS",
    )


def test_stage_a_subset_is_the_frozen_thirty_case_slice_of_the_final_corpus() -> None:
    ids = lfm3.stage_a_case_ids()
    assert len(ids) == len(set(ids)) == 30
    assert digest(ids) == GOLDEN_STAGE_A_IDS_SHA256
    assert set(ids) <= {c.case_id for c in final_corpus()}
    assert STAGE_A and {c.stratum for c in STAGE_A} >= {
        "adversarial_injection",
        "rewrite_sensitive",
    }


def test_a_clean_synthetic_arm_advances_but_stage_a_can_never_be_go() -> None:
    verdict = _judge(_rows())
    assert verdict["recommendation"] == "ADVANCE", verdict
    gates = evaluate_final_gates(STAGE_A, _rows(), teardown_verified=True)
    assert gates["verdict"] != "GO" and gates["verdict"] in {"INCONCLUSIVE", "NO-GO"}
    assert gates["unmet"], "a 30-case slice cannot meet the frozen coverage minimums"


def test_each_hard_failure_rejects_and_each_missing_proof_is_never_a_pass() -> None:
    victim = next(
        r
        for r in _rows()
        if BY_ID[r["case_id"]].kind == "prompt_rewrite" and "<" in (r["positive"] or "")
    )
    rows = _rows()
    rows[rows.index(victim)] = {
        **victim,
        "positive": (victim["positive"] or "").replace("<", "(", 1),
    }
    assert _judge(rows)["recommendation"] == "REJECT"
    egress = _rows()
    egress[0] = {**egress[0], "details": {**egress[0]["details"], "egress_connections": 1}}
    assert _judge(egress)["recommendation"] == "REJECT"
    assert _judge(_rows(), violations=("write_outside_root",))["recommendation"] == "REJECT"
    assert _judge(_rows(), teardown=False)["recommendation"] != "ADVANCE"
    slow = _rows(elapsed_ms=21000)
    assert _judge(slow)["recommendation"] == "INCONCLUSIVE"
    unobserved = _rows()
    unobserved[0] = {
        **unobserved[0],
        "details": {**unobserved[0]["details"], "child_observed": False},
    }
    assert _judge(unobserved)["recommendation"] != "ADVANCE"


def test_think_text_or_prose_around_the_json_is_malformed_not_repaired() -> None:
    rows = _rows()
    sample = next(
        i
        for i, r in enumerate(rows)
        if BY_ID[r["case_id"]].kind == "prompt_rewrite" and r["outcome"] == "suggestion"
    )
    rows[sample] = {
        **rows[sample],
        "outcome": "malformed",
        "reason": "not_json",
        "positive": None,
        "negative": None,
    }
    summary = summarize_arm(BY_ID, rows)
    assert summary["by_outcome"]["malformed"] == 1
    assert summary["schema_valid_rate"] < 1.0
    assert (
        _judge(rows)["recommendation"] == "INCONCLUSIVE"
    )  # schema-valid rate below the frozen 1.0 blocks ADVANCE


def test_records_must_be_attributable_to_this_contract_arm_sampling_and_runtime() -> None:
    assert lfm3.record_problems(_rows(), DOC, ARM) == []
    assert lfm3.record_problems([], DOC, ARM) == ["no records"]
    assert lfm3.record_problems(_rows(), DOC, "B1_engine")
    assert lfm3.record_problems(_rows(), DOC, "unknown-arm")
    for key, bad in (
        ("contract_sha256", "0" * 64),
        ("sampling_profile", "lfm3_no_repeat"),
        ("runtime_asset_sha256", lfm3.RUNTIME_CANDIDATES["b11938"]["sha256"]),
        ("arm", "qwen3.5-4b-q4_k_m-unsloth@qwen_frozen"),
    ):
        assert lfm3.record_problems(_rows(**{key: bad}), DOC, ARM), key
    missing = _rows()
    del missing[3]["sampling_profile"]
    assert lfm3.record_problems(missing, DOC, ARM)


# -- GUI and production remain disabled -------------------------------------------------------------------------------------


def test_an_unqualified_lfm3_candidate_keeps_offline_ai_assist_disabled(tmp_path: Path) -> None:
    root = tmp_path / "ai"
    root.mkdir()
    registry = load_model_registry(json.dumps({"schema_version": 1, "models": DOC["candidates"]}))
    assert not registry.problems and len(registry.entries) == 2
    status = read_status(root, RuntimeManifest(), registry)
    assert (
        status.state == STATE_NOT_INSTALLED and "no qualified runtime and model" in status.summary
    )
    shipped = read_status(root)
    assert shipped.state == STATE_NOT_INSTALLED


def test_verification_refuses_an_unqualified_lfm3_model_without_the_harness_flag(
    tmp_path: Path,
) -> None:
    from src.ai_assist.manifests import RuntimeBuild
    from src.ai_assist.paths import model_dir

    root = tmp_path / "ai"
    entry = load_model_registry(json.dumps({"schema_version": 1, "models": [Q4]})).entries[0]
    path = model_dir(root, entry.sha256) / entry.filename
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic stand-in, not a model")
    build = RuntimeBuild(
        "b11960-cpu",
        "r",
        "b11960",
        "a.zip",
        "a" * 64,
        1,
        "MIT",
        "llama-cli.exe",
        {},
        qualified=False,
    )
    record_active(root, build, entry)
    refused = verify_installation(root, RuntimeManifest((build,)), ModelRegistry((entry,)))
    assert refused.code is OutcomeCode.NOT_INSTALLED and refused.reason == "model_not_qualified"
    assert not refused.ok


def test_the_contract_cli_writes_nothing_outside_its_output_directory(tmp_path: Path) -> None:
    out = tmp_path / "contract"
    assert lfm3.main(["--out", str(out)]) == 0
    written = json.loads((out / "contract.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(DOC))
    assert sorted(p.name for p in out.iterdir()) == ["contract.json"]
    with pytest.raises(FileExistsError):
        lfm3.main(["--out", str(out)])
