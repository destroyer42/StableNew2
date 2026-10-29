"""AI-QUAL-115: the frozen LFM3 qualification contract, on synthetic data only.

No artifact is downloaded, extracted or executed, no model is loaded and no telemetry is real. These tests prove that the
contract is deterministic, anchored to one frozen digest, leaves the Qwen evidence and production configuration untouched,
and fails closed.
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
from src.ai_assist.contracts import SUGGESTION_SCHEMA_ID, OutcomeCode
from src.ai_assist.manifests import (
    ModelRegistry,
    RuntimeBuild,
    RuntimeManifest,
    load_model_registry,
    load_runtime_manifest,
    record_active,
    verify_installation,
)
from src.ai_assist.paths import model_dir
from src.ai_assist.status import (
    MODEL_REGISTRY_PATH,
    RUNTIME_MANIFEST_PATH,
    STATE_NOT_INSTALLED,
    read_status,
)
from src.ai_assist.validators import validate_output
from tools.qualification.ai111 import lfm3_contract as lfm3
from tools.qualification.ai111 import stage_a_report as report
from tools.qualification.ai111.baselines import ARMS
from tools.qualification.ai111.corpus import corpus_digest
from tools.qualification.ai111.final_plan import (
    MINIMUMS,
    evaluate_final_gates,
    final_corpus,
    final_plan,
)
from tools.qualification.ai111.plan import digest, frozen_plan
from tools.qualification.ai111.scoring import summarize_arm

# Independent literal copies, so editing lfm3_contract.py alone cannot silently move any of these.
GOLDEN_CONTRACT_SHA256 = "41e65d6769cd4090dc0e8f978014c97e82fd23c3351261f3ff276efd8a129f60"
# Measured from the S0 download of llama-b11960-bin-win-cpu-x64.zip (hashed in memory, never extracted).
GOLDEN_B11960_MEMBERS = {
    "llama-cli.exe": "02c8fcdbf3e89c0c36757ee0cffb091844181a43d15995699bb6f3400f932de0",
    "llama-completion.exe": "2b4759ec5f0343d7421cae98fadd6d2de1c9bdae64cb128da52628606ab35090",
}
GOLDEN_STAGE_A_IDS_SHA256 = "d0bbf7feabc5bd533130d2ab044cbe351218a47b2a0c7dd7edbbc5eb8e97d030"
GOLDEN_QWEN = {
    "screening_plan_sha256": "17814e4050049323dc4f5206417bac67f94307d7791ce580af2948e2310df338",
    "final_plan_sha256": "3017c427c7f5c15bc900e6e5d1ef2d3e86b45c7bbb30d3a9d0a0d2f58b1eccbf",
    "final_corpus_sha256": "a89297beb3ae86246eb25214738d91ba3f24dc1e2cd8a4f7547ae49c68a774d5",
}
DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/Subsystems/AiAssist/PR-AI-115_LFM3_Qualification_Contract.md"
)

DOC = lfm3.contract()
PRODUCTION = load_model_registry(MODEL_REGISTRY_PATH)
Q4 = copy.deepcopy(DOC["candidates"][0])


# -- determinism, anchoring and preservation of the Qwen evidence ----------------------------------------------------------


def test_the_contract_is_deterministic_and_pinned() -> None:
    assert lfm3.contract() == DOC
    assert (
        digest(DOC)
        == lfm3.contract_digest()
        == lfm3.FROZEN_CONTRACT_SHA256
        == GOLDEN_CONTRACT_SHA256
    )
    assert lfm3.validate_contract(DOC) == []
    assert DOC["stages"]["A"]["case_ids_sha256"] == GOLDEN_STAGE_A_IDS_SHA256


def _tamper(path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    document = copy.deepcopy(DOC)
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return document


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("stages", "thresholds", "latency_median_seconds_max"), 999.0),
        (("stages", "A", "case_ids_sha256"), "0" * 64),
        (("stages", "B", "corpus_sha256"), "0" * 64),
        (("sampling", "lfm3_vendor", "repeat_penalty"), 2.0),
        (("monitoring",), {}),
        (("known_blockers",), []),
        (("approvals", "S3_stage_a", "artifacts"), []),
        (("runtime", "candidates", "b11960", "members"), {"llama-cli.exe": "a" * 64}),
        (("runtime", "candidates", "b11960", "sha256"), "b" * 64),
        (("license", "owner_threshold_position"), "we are under the threshold"),
        (("limits", "timeout_seconds"), 600.0),
    ],
)
def test_any_edit_to_the_frozen_document_is_refused(path: tuple[Any, ...], value: Any) -> None:
    assert "contract differs from the frozen digest" in lfm3.validate_contract(_tamper(path, value))


def test_a_runtime_swapped_for_another_archive_is_refused_field_by_field() -> None:
    candidates = DOC["runtime"]["candidates"]
    swapped = copy.deepcopy(DOC)
    swapped["runtime"]["candidates"]["b11960"] = {
        **copy.deepcopy(candidates["b11938"]),
        "selected": True,
    }
    assert lfm3.validate_contract(swapped)  # refused outright by the frozen digest
    relabelled = copy.deepcopy(candidates["b11938"])
    relabelled["tag"] = "b11960"
    problems = lfm3.runtime_problems(relabelled, require_members=False)
    assert any("differs from the pinned candidate" in p for p in problems)


def test_the_qwen_plan_corpus_and_digests_are_unchanged() -> None:
    assert lfm3.QWEN_FROZEN == GOLDEN_QWEN == DOC["qwen_preserved"]
    assert digest(frozen_plan()) == GOLDEN_QWEN["screening_plan_sha256"]
    assert digest(final_plan()) == GOLDEN_QWEN["final_plan_sha256"]
    assert corpus_digest(final_corpus()) == GOLDEN_QWEN["final_corpus_sha256"]
    assert "lfm3" not in json.dumps(frozen_plan()).lower()


def test_production_configuration_is_untouched_and_never_names_lfm3() -> None:
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    assert not registry.problems
    assert all(
        not e.model_id.startswith("lfm3-") and e.qualified is False for e in registry.entries
    )
    assert "lfm3" not in MODEL_REGISTRY_PATH.read_text(encoding="utf-8").lower()
    manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    assert manifest.builds == () and not manifest.problems


def test_the_contract_authorizes_nothing_and_promotes_nothing() -> None:
    assert DOC["status"] == "FROZEN_PROPOSAL_UNAPPROVED"
    assert set(DOC["authorization"]) == set(DOC["approvals"]) and not any(
        DOC["authorization"].values()
    )
    assert all(c["qualified"] is False for c in DOC["candidates"])
    assert "outside this contract" in DOC["promotion"]


def test_the_documentation_quotes_the_values_the_code_computes() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    total = (
        sum(c["bytes"] for c in DOC["candidates"]) + DOC["runtime"]["candidates"]["b11960"]["bytes"]
    )
    for needle in (
        GOLDEN_CONTRACT_SHA256,
        GOLDEN_STAGE_A_IDS_SHA256,
        lfm3.LICENSE["text_sha256"],
        *(c["sha256"] for c in DOC["candidates"]),
        *(e["sha256"] for e in DOC["runtime"]["candidates"].values()),
        lfm3.PUBLISHER_REVISION,
        lfm3.PACKAGER_REVISION,
        f"{total:,}",
    ):
        assert needle in text, needle[:20]


# -- candidate metadata, provenance and licence ------------------------------------------------------------------------------


def test_pinned_candidates_are_internally_consistent_and_revision_locked() -> None:
    assert [lfm3.candidate_problems(c, PRODUCTION) for c in DOC["candidates"]] == [[], []]
    for entry in DOC["candidates"]:
        provenance = entry["provenance"]
        assert provenance["publisher_revision"] == lfm3.PUBLISHER_REVISION
        assert provenance["packager_revision"] == lfm3.PACKAGER_REVISION
        assert provenance["packager_revision"] in provenance["source_url"]
        assert provenance["source_url"].endswith(entry["filename"])
    assert {c["quantization"]: c["bytes"] for c in DOC["candidates"]} == {
        "Q4_K_M": 1099627808,
        "Q8_0": 1846238496,
    }


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


def test_a_candidate_that_shares_identity_with_production_is_refused() -> None:
    qwen = PRODUCTION.entries[0]
    assert lfm3.candidate_problems(_mutated(lambda e: e.update(sha256=qwen.sha256)), PRODUCTION)
    assert lfm3.candidate_problems(_mutated(lambda e: e.update(model_id=qwen.model_id)), PRODUCTION)


def test_licence_is_recorded_hash_bound_and_blocks_until_acknowledged_with_a_threshold_position() -> (
    None
):
    record = DOC["license"]
    assert record["spdx"] == "LicenseRef-LFM-Open-License-1.0"
    assert record["commercial_use_threshold_usd_annual_revenue"] == 10_000_000
    clauses = " ".join(record["clauses_that_bind_the_owner"])
    assert "indirect commercial advantage" in clauses and "delete" in clauses
    assert lfm3.license_problems(record, require_acknowledged=False) == []
    blocked = lfm3.license_problems(record, require_acknowledged=True)
    assert "licence not acknowledged by the owner" in blocked
    assert "owner has not stated a Threshold position" in blocked
    ack = {**record, "owner_acknowledged": True}
    assert lfm3.license_problems(ack, require_acknowledged=True) == [
        "owner has not stated a Threshold position"
    ]
    assert lfm3.license_problems(
        {**ack, "owner_threshold_position": "  "}, require_acknowledged=True
    )
    full = {**ack, "owner_threshold_position": "recorded by the owner"}
    assert lfm3.license_problems(full, require_acknowledged=True) == []
    assert lfm3.license_problems({**record, "text_sha256": "1" * 64}, require_acknowledged=False)
    assert lfm3.license_problems({**record, "name": "MIT"}, require_acknowledged=False)
    assert lfm3.license_problems(
        {**record, "owner_acknowledgement_required": False}, require_acknowledged=False
    )


# -- runtime candidates -------------------------------------------------------------------------------------------------------


def test_runtime_selection_is_b11960_and_b11938_is_evaluated_but_not_selected() -> None:
    candidates = DOC["runtime"]["candidates"]
    assert DOC["runtime"]["selected"] == "b11960"
    assert candidates["b11960"]["selected"] is True and candidates["b11938"]["selected"] is False
    assert "below the publisher's stated minimum" in candidates["b11938"]["lfm3_text_support"]
    for tag, entry in candidates.items():
        assert lfm3.runtime_problems(entry, require_members=False) == [], tag
    assert lfm3.runtime_problems(candidates["b11960"], require_members=True) == []
    assert lfm3.runtime_problems(candidates["b11938"], require_members=True) == [
        "launchable member hashes are not recorded"
    ]


def test_the_two_contracts_are_separate_and_the_runtime_floor_is_b11960_or_later() -> None:
    assert set(DOC["separation"]) == {"qwen", "lfm3"}
    assert "b11840" in DOC["separation"]["qwen"] and "only reads them" in DOC["separation"]["qwen"]
    assert "b11960" in DOC["separation"]["lfm3"]
    assert DOC["runtime"]["minimum_tag"] == "b11960"
    assert (
        "later" in DOC["runtime"]["later_build_rule"]
        and "new frozen contract" in DOC["runtime"]["later_build_rule"]
    )
    assert int(DOC["runtime"]["selected"][1:]) >= int(DOC["runtime"]["minimum_tag"][1:])


def test_the_measured_b11960_archive_contents_are_pinned() -> None:
    entry = DOC["runtime"]["candidates"]["b11960"]
    assert entry["members"] == GOLDEN_B11960_MEMBERS
    files = entry["files"]
    assert len(files) == 51 and all(n.endswith((".exe", ".dll")) and "/" not in n for n in files)
    assert all(files[n] == h for n, h in GOLDEN_B11960_MEMBERS.items())
    assert {"llama-cli-impl.dll", "llama-completion-impl.dll", "llama.dll", "ggml.dll"} <= set(
        files
    )
    assert not any(t in n for n in files for t in ("cuda", "vulkan", "hip", "sycl", "opencl"))
    assert {"ggml-rpc.dll", "ggml-rpc-server.exe"} <= set(
        files
    )  # present, so the monitoring rule must name them
    assert (
        "ggml-rpc" in DOC["monitoring"]["gpu"]["rpc_backend"]
        and "--rpc" in DOC["monitoring"]["gpu"]["rpc_backend"]
    )
    assert any("ggml_rpc" in b for b in DOC["known_blockers"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e.update(compute="cuda"),
        lambda e: e.update(asset="llama-b11960-bin-win-cuda-12.4-x64.zip"),
        lambda e: e.update(asset="llama-b11960-bin-win-vulkan-x64.zip"),
        lambda e: e.update(asset="llama-b11960-bin-win-cpu-arm64.zip"),
        lambda e: e.update(asset="llama-b11938-bin-win-cpu-x64.zip"),
        lambda e: e.update(sha256="abc"),
        lambda e: e.update(sha256="0" * 64),
        lambda e: e.update(commit="deadbeef"),
        lambda e: e.update(bytes=-1),
        lambda e: e.update(bytes=1),
        lambda e: e.update(tag="b99999"),
        lambda e: e.update(source_url="https://example.invalid/llama.zip"),
        lambda e: e.update(license="GPL-3.0-only"),
        lambda e: e.update(members={"evil.exe": "a" * 64}),
        lambda e: e.update(members={"llama-cli.exe": "not-a-hash"}),
        lambda e: e.update(members="yes"),
        lambda e: e.update(members={"llama-cli.exe": "a" * 64}),  # differs from the measured pin
        lambda e: e.update(files={}),
        lambda e: e.update(files="x"),
        lambda e: e["files"].update(
            {"evil.exe": "a" * 64}
        ),  # a loadable file the archive does not hold
        lambda e: e["files"].update({"notes.txt": "a" * 64}),
        lambda e: e["files"].update({"llama.dll": "not-a-hash"}),
        lambda e: e["files"].pop("llama-completion.exe"),
        lambda e: e["files"].update(
            {"llama-completion.exe": "e" * 64}
        ),  # member disagrees with the file map
    ],
)
def test_runtime_metadata_fails_closed(mutation: Any) -> None:
    entry = copy.deepcopy(DOC["runtime"]["candidates"]["b11960"])
    mutation(entry)
    assert lfm3.runtime_problems(entry, require_members=False)


def test_a_never_measured_candidate_needs_consistent_member_and_file_maps_before_use() -> None:
    entry = copy.deepcopy(DOC["runtime"]["candidates"]["b11938"])
    entry["files"] = {"llama-completion.exe": "a" * 64, "llama.dll": "b" * 64}
    entry["members"] = {"llama-completion.exe": "a" * 64}
    assert lfm3.runtime_problems(entry, require_members=True) == []
    entry["members"] = {"llama-completion.exe": "c" * 64}
    assert lfm3.runtime_problems(entry, require_members=True)


# -- closed command line ------------------------------------------------------------------------------------------------------


def test_lfm3_argv_is_the_production_prefix_plus_the_exact_vendor_sampling() -> None:
    model, prompt, schema = Path("m.gguf"), Path("p.txt"), Path("s.json")
    argv = lfm3.lfm3_argv("lfm3_vendor", model, prompt, schema)
    production = build_argv(model, prompt, schema, RunLimits())
    prefix = production.index("--temp")
    assert argv[:prefix] == production[:prefix]
    assert argv[prefix:] == [
        "--temp", "0.1", "--top-k", "50", "--top-p", "1.0", "--min-p", "0.0",
        "--repeat-penalty", "1.1", "--presence-penalty", "0.0", "--seed", "321",
    ]  # fmt: skip
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
    assert production[production.index("--temp") :] == [
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
    with pytest.raises((ValueError, KeyError)):
        lfm3.lfm3_argv("qwen_frozen", Path("m.gguf"), Path("p.txt"), Path("s.json"))


def test_help_text_must_list_every_flag_the_contract_emits() -> None:
    full = " ".join(sorted(lfm3.LFM3_ALLOWED_FLAGS))
    assert lfm3.help_flag_report(full, truncated=False)["verdict"] == "PASS"
    short = full.replace("--repeat-penalty", "")
    failed = lfm3.help_flag_report(short, truncated=False)
    assert failed["verdict"] == "FAIL" and "--repeat-penalty" in failed["missing"]
    assert lfm3.help_flag_report(short, truncated=True)["verdict"] == "INCONCLUSIVE"
    assert lfm3.help_flag_report("   ", truncated=False)["verdict"] == "INCONCLUSIVE"


# -- arms, comparison and approval boundary -----------------------------------------------------------------------------------


def _quant(model_id: str) -> str:
    return next(c["quantization"] for c in DOC["candidates"] if c["model_id"] == model_id)


def test_every_executable_arm_shares_one_runtime_and_has_a_matched_qwen_comparator() -> None:
    arms = {a["arm_id"]: a for a in DOC["arms"]}
    assert {a["runtime"] for a in DOC["arms"] if a["kind"] != "baseline"} == {"b11960"}
    for lfm, qwen in lfm3.COMPARATORS.items():
        arm = arms[f"{lfm}@lfm3_vendor"]
        comparator = arms[arm["matched_comparator"]]
        assert comparator["model"]["model_id"] == qwen and comparator["sampling"] == "qwen_frozen"
        assert comparator["model"]["sha256"] == next(
            e.sha256 for e in PRODUCTION.entries if e.model_id == qwen
        )
        assert comparator["model"]["quantization"] == _quant(lfm)
    assert arms["lfm3-1.7b-q4_k_m-liquidai@lfm3_no_repeat"]["stages"] == ["A"]
    drifted = copy.deepcopy(DOC)
    drifted["arms"][1]["runtime"] = "b11840"
    assert lfm3.validate_contract(drifted)


def _approval(step: str, document: dict[str, Any] = DOC, drop: str = "") -> str:
    tokens = [
        t
        for a in document["approvals"][step]["artifacts"]
        for t in lfm3._artifact_tokens(a, document)
    ]
    text = f"I approve {step} for contract {digest(document)}: " + " ".join(tokens)
    return text.replace(drop, "") if drop else text


@pytest.mark.parametrize("step", sorted(DOC["approvals"]))
def test_each_approval_must_name_its_step_this_digest_and_every_artifact(step: str) -> None:
    assert lfm3.approval_problems(step, _approval(step)) == []
    assert lfm3.approval_problems(step, "") != []
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


def test_stage_approvals_cover_the_qwen_comparators_they_would_execute() -> None:
    qwen_hashes = {a["model"]["sha256"] for a in DOC["arms"] if a["kind"] == "comparator"}
    assert len(qwen_hashes) == 2
    for step in ("S3_stage_a", "S4_stage_b"):
        tokens = {
            t for a in DOC["approvals"][step]["artifacts"] for t in lfm3._artifact_tokens(a, DOC)
        }
        assert qwen_hashes <= tokens
        assert lfm3.approval_problems(step, _approval(step, drop=sorted(qwen_hashes)[0]))
    for step in ("S0_download", "S1_license", "S2_d12a_b11960"):
        assert not any(a.startswith("qwen:") for a in DOC["approvals"][step]["artifacts"])


def test_an_approval_for_one_step_or_for_qwen_never_satisfies_another() -> None:
    assert lfm3.approval_problems("S3_stage_a", _approval("S0_download"))
    qwen_only = f"approve S3_stage_a {GOLDEN_QWEN['final_plan_sha256']} {GOLDEN_QWEN['final_corpus_sha256']}"
    assert lfm3.approval_problems("S3_stage_a", qwen_only)
    assert lfm3.approval_problems("S5_promotion", "anything")
    assert "S5_promotion" not in DOC["approvals"]


def _ready_evidence(stage: str) -> dict[str, Any]:
    steps = lfm3._STAGE_STEPS[stage]
    runtime = copy.deepcopy(DOC["runtime"]["candidates"]["b11960"])
    evidence: dict[str, Any] = {
        "approvals": {step: _approval(step) for step in steps},
        "license": {
            **DOC["license"],
            "owner_acknowledged": True,
            "owner_threshold_position": "recorded by the owner",
        },
        "runtime": runtime,
        "help_report": lfm3.help_flag_report(
            " ".join(sorted(lfm3.LFM3_ALLOWED_FLAGS)), truncated=False
        ),
    }
    evidence.update(dict.fromkeys(lfm3._STAGE_FLAGS[stage], True))
    return evidence


@pytest.mark.parametrize("stage", ["S0_download", "S2_d12a_b11960", "S3_stage_a", "S4_stage_b"])
def test_readiness_is_derived_from_evidence_and_complete_evidence_clears_it(stage: str) -> None:
    assert lfm3.readiness_blockers(stage, _ready_evidence(stage)) == []
    assert lfm3.readiness_blockers(stage, {})  # nothing supplied: every item blocks
    assert lfm3.readiness_blockers("S9", {}) == ["unknown stage: S9"]


def test_readiness_refuses_each_missing_or_forged_item() -> None:
    base = _ready_evidence("S4_stage_b")
    for key in lfm3._STAGE_FLAGS["S4_stage_b"]:
        assert lfm3.readiness_blockers("S4_stage_b", {**base, key: "yes"}) == [
            key
        ]  # not exactly True
        assert lfm3.readiness_blockers("S4_stage_b", {**base, key: False}) == [key]
    approvals = dict(base["approvals"])
    approvals["S2_d12a_b11960"] = approvals[
        "S0_download"
    ]  # one step's approval cannot stand in for another
    assert lfm3.readiness_blockers("S4_stage_b", {**base, "approvals": approvals}) == [
        "approval_S2_d12a_b11960"
    ]
    assert lfm3.readiness_blockers("S4_stage_b", {**base, "license": DOC["license"]}) == [
        "license_acknowledged"
    ]
    no_members = {**base, "runtime": {**base["runtime"], "members": {}, "files": {}}}
    assert lfm3.readiness_blockers("S4_stage_b", no_members) == ["runtime_members_recorded"]
    short = lfm3.help_flag_report("--offline", truncated=False)
    assert lfm3.readiness_blockers("S4_stage_b", {**base, "help_report": short}) == [
        "help_lists_every_contract_flag"
    ]
    assert lfm3.readiness_blockers("S4_stage_b", {**base, "approvals": "approved"}) == [
        f"approval_{step}" for step in lfm3._STAGE_STEPS["S4_stage_b"]
    ]


def test_stage_b_needs_everything_stage_a_needs_and_known_blockers_are_recorded() -> None:
    assert set(lfm3._STAGE_FLAGS["S3_stage_a"]) <= set(lfm3._STAGE_FLAGS["S4_stage_b"])
    assert set(lfm3._STAGE_STEPS["S3_stage_a"]) < set(lfm3._STAGE_STEPS["S4_stage_b"])
    assert {
        "harness_pinned_to_b11840_single_runtime_single_sampling",
        "stage_a_report_and_d12a_defaults_pinned_to_the_qwen_screening_plan_and_b11840",
        "derive_runtime_build_without_a_named_member_does_not_pin_the_member_hash",
        "stage_b_arm_exceeds_one_1024mb_capture_and_the_split_and_record_merge_are_undefined",
        "owner_approvals_absent",
        "b11960_archive_holds_ggml_rpc_dll_and_rpc_server_exe_so_zero_connections_must_be_shown_by_d12a_and_the_capture",
    } <= set(lfm3.KNOWN_BLOCKERS)


# -- records, synthetic telemetry and scoring ---------------------------------------------------------------------------------

FULL = final_corpus()
FULL_BY_ID = {c.case_id: c for c in FULL}
STAGE_A = [FULL_BY_ID[i] for i in lfm3.stage_a_case_ids()]
BY_ID = {c.case_id: c for c in STAGE_A}
ARM = "lfm3-1.7b-q4_k_m-liquidai@lfm3_vendor"
MEMBER_SHA = GOLDEN_B11960_MEMBERS["llama-completion.exe"]


def _doc_with_members() -> dict[str, Any]:
    return copy.deepcopy(DOC)


def _row(case: Any, index: int, document: dict[str, Any], **overrides: Any) -> dict[str, Any]:
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
        "contract_sha256": digest(document),
        "sampling_profile": "lfm3_vendor",
        "runtime_asset_sha256": document["runtime"]["candidates"]["b11960"]["sha256"],
        "model_sha256": document["candidates"][0]["sha256"],
        "runtime_member_sha256": MEMBER_SHA,
        "monitor_kind": "host",
    }
    row.update(overrides)
    return row


def _rows(
    cases: list[Any] | None = None, document: dict[str, Any] | None = None, **overrides: Any
) -> list[dict[str, Any]]:
    document = document or _doc_with_members()
    return [_row(c, i, document, **overrides) for i, c in enumerate(cases or STAGE_A)]


def test_stage_a_subset_is_the_frozen_thirty_case_slice_of_the_final_corpus() -> None:
    ids = lfm3.stage_a_case_ids()
    assert len(ids) == len(set(ids)) == 30
    assert digest(ids) == GOLDEN_STAGE_A_IDS_SHA256
    assert set(ids) <= set(FULL_BY_ID)


def test_thirty_rows_can_never_satisfy_the_stage_b_gates() -> None:
    gates = evaluate_final_gates(FULL, _rows(), teardown_verified=True)
    assert gates["verdict"] == "INCONCLUSIVE"
    assert (
        "frozen_final_corpus" not in gates["unmet"]
    )  # the full corpus was supplied, so coverage is what fails
    assert set(gates["unmet"]) & set(MINIMUMS), gates["unmet"]


def test_think_text_prose_and_fences_around_json_are_never_a_suggestion_in_the_real_validator() -> (
    None
):
    case = next(c for c in FULL if c.stratum == "rewrite_natural")
    request = case.request("probe")
    body = json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "prompt_rewrite",
            "positive": request.positive_text,
            "negative": request.negative_text,
            "changes": [],
        }
    )
    for wrapped in (
        f"<think>planning</think>\n{body}",
        f"```json\n{body}\n```",
        f"Here you go: {body}",
        f"{body}\ndone",
    ):
        result = validate_output(wrapped, request)
        assert result.code is OutcomeCode.MALFORMED and result.reason == "not_json", wrapped[:30]
    refusal = validate_output(f"Sorry, but I cannot help with that. {body}", request)
    assert (
        refusal.code is OutcomeCode.REFUSED_BY_MODEL
    )  # refusal-shaped opening text is classed a refusal


def test_a_protected_token_change_is_malformed_with_the_reason_the_sensitivity_rule_keys_on() -> (
    None
):
    case = next(c for c in FULL if c.stratum == "rewrite_tokens")
    request = case.request("probe")
    assert "<lora:" in request.positive_text
    body = json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "prompt_rewrite",
            "positive": request.positive_text.replace("<lora:", "<lora ", 1),
            "negative": request.negative_text,
            "changes": [],
        }
    )
    result = validate_output(body, request)
    assert result.code is OutcomeCode.MALFORMED and result.reason == "protected_tokens_changed"
    rule = DOC["stages"]["A"]["sensitivity_rule"]
    assert "protected_tokens_changed" in rule and "structurally zero" in rule


def test_records_must_be_attributable_to_contract_arm_model_sampling_runtime_and_member() -> None:
    document = _doc_with_members()
    assert lfm3.record_problems(_rows(document=document), document, ARM) == []
    assert lfm3.record_problems([], document, ARM) == ["no records"]
    assert lfm3.record_problems(_rows(document=document), document, "B1_engine")
    assert lfm3.record_problems(_rows(document=document), document, "unknown-arm")
    for key, bad in (
        ("contract_sha256", "0" * 64),
        ("sampling_profile", "lfm3_no_repeat"),
        ("runtime_asset_sha256", lfm3.RUNTIME_CANDIDATES["b11938"]["sha256"]),
        ("arm", "qwen3.5-4b-q4_k_m-unsloth@qwen_frozen"),
        (
            "model_sha256",
            DOC["candidates"][1]["sha256"],
        ),  # the Q8_0 file labelled as the Q4_K_M arm
        ("runtime_member_sha256", "d" * 64),  # a launched member that was never recorded
        ("monitor_kind", "hermetic"),
        ("monitor_kind", "cooperative"),
    ):
        assert lfm3.record_problems(_rows(document=document, **{key: bad}), document, ARM), key
    missing = _rows(document=document)
    del missing[3]["sampling_profile"]
    assert lfm3.record_problems(missing, document, ARM)


def test_a_record_naming_the_other_launchable_member_is_still_a_recorded_member_but_a_foreign_one_is_not() -> (
    None
):
    other = GOLDEN_B11960_MEMBERS["llama-cli.exe"]
    assert lfm3.record_problems(_rows(document=DOC, runtime_member_sha256=other), DOC, ARM) == []
    assert any(
        "recorded member" in p
        for p in lfm3.record_problems(_rows(document=DOC, runtime_member_sha256="f" * 64), DOC, ARM)
    )


def test_record_sets_must_be_complete_and_unique() -> None:
    document = _doc_with_members()
    rows = _rows(document=document)
    ids = [c.case_id for c in STAGE_A]
    assert lfm3.record_problems(rows, document, ARM, ids) == []
    assert "duplicate case records" in lfm3.record_problems([*rows, rows[0]], document, ARM, ids)
    assert "record set differs from the frozen case list" in lfm3.record_problems(
        rows[:-1], document, ARM, ids
    )


def test_stage_b_verdict_is_inconclusive_on_any_missing_proof() -> None:
    document = _doc_with_members()
    rows = _rows(FULL, document)
    args: dict[str, Any] = {
        "teardown_verified": True,
        "preference": {"win_rate_lower95": 0.7, "decided": 120, "judged_pairs": 120},
        "capture_verdicts": ["PASS"],
    }
    assert lfm3.stage_b_verdict(rows, document, ARM, FULL, **{**args, "capture_verdicts": []})[
        "unmet"
    ] == ["no capture analysis"]
    mixed = lfm3.stage_b_verdict(
        rows, document, ARM, FULL, **{**args, "capture_verdicts": ["PASS", "INCONCLUSIVE"]}
    )
    assert mixed["verdict"] == "INCONCLUSIVE"
    assert "capture analysis is INCONCLUSIVE, not PASS" in mixed["unmet"]
    assert lfm3.stage_b_verdict(rows[:-1], document, ARM, FULL, **args)["verdict"] == "INCONCLUSIVE"
    assert lfm3.stage_b_verdict(rows, document, ARM, FULL[:-1], **args)["verdict"] == "INCONCLUSIVE"
    hermetic = _rows(FULL, document, monitor_kind="hermetic")
    assert lfm3.stage_b_verdict(hermetic, document, ARM, FULL, **args)["verdict"] == "INCONCLUSIVE"


def _judge(rows: list[dict[str, Any]], *, teardown: bool = True) -> dict[str, Any]:
    summary = summarize_arm(BY_ID, rows)
    metrics = report.arm_metrics(ARM, rows, summary, BY_ID, [])
    session = {
        "teardown_verified": teardown,
        "violations": [],
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


def _launched(rows: list[dict[str, Any]], **detail: Any) -> list[dict[str, Any]]:
    """Rows with ``detail`` merged into the first request that actually launched a child (refused ones never do)."""

    index = next(i for i, r in enumerate(rows) if r["outcome"] == "suggestion")
    out = list(rows)
    out[index] = {**rows[index], "details": {**rows[index]["details"], **detail}}
    return out


def test_stage_a_judging_advances_only_clean_complete_evidence_and_never_returns_go() -> None:
    assert _judge(_rows())["recommendation"] == "ADVANCE"
    assert _judge(_launched(_rows(), egress_connections=1))["recommendation"] == "REJECT"
    assert _judge(_rows(), teardown=False)["recommendation"] != "ADVANCE"
    slow = _judge(_rows(elapsed_ms=60000))
    assert slow["recommendation"] != "ADVANCE" and slow["measured_thresholds_missed"]
    assert _judge(_launched(_rows(), child_observed=False))["recommendation"] != "ADVANCE"
    assert _judge(_launched(_rows(), priority_verified=False))["recommendation"] != "ADVANCE"


# -- GUI and production remain disabled ---------------------------------------------------------------------------------------


def _qualified(entries: list[dict[str, Any]], value: bool) -> ModelRegistry:
    return load_model_registry(
        json.dumps({"schema_version": 1, "models": [{**e, "qualified": value} for e in entries]})
    )


def test_an_unqualified_lfm3_candidate_keeps_offline_ai_assist_disabled(tmp_path: Path) -> None:
    root = tmp_path / "ai"
    root.mkdir()
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
        qualified=True,
    )
    unqualified = read_status(root, RuntimeManifest((build,)), _qualified(DOC["candidates"], False))
    assert unqualified.state == STATE_NOT_INSTALLED
    assert "no qualified runtime and model" in unqualified.summary
    assert read_status(root).state == STATE_NOT_INSTALLED  # the shipped configuration


def test_verification_refuses_an_unqualified_lfm3_model_without_the_harness_flag(
    tmp_path: Path,
) -> None:
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


def test_the_contract_cli_writes_only_its_contract_and_refuses_an_existing_directory(
    tmp_path: Path,
) -> None:
    out = tmp_path / "contract"
    assert lfm3.main(["--out", str(out)]) == 0
    assert json.loads((out / "contract.json").read_text(encoding="utf-8")) == json.loads(
        json.dumps(DOC)
    )
    assert sorted(p.name for p in out.iterdir()) == ["contract.json"]
    with pytest.raises(FileExistsError):
        lfm3.main(["--out", str(out)])
