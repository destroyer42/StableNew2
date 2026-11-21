"""The remote input manifest preserves the AI-111 freeze and separates its stages."""

import json

import pytest

from tools.qualification.ai111.baselines import ARMS
from tools.qualification.ai111.final_plan import final_corpus
from tools.qualification.ai111.lfm3_contract import QWEN_FROZEN, stage_a_case_ids
from tools.qualification.ai111.plan import digest
from tools.qualification.ai111.remote_plan import freeze_inputs, main

IDENTITIES = {
    "qwen_manifest_sha256": "a" * 64,
    "lfm_manifest_sha256": "b" * 64,
    "worker_attestation_sha256": "c" * 64,
}


def test_pilot_and_full_use_the_unchanged_corpus_and_baselines():
    pilot = freeze_inputs("pilot", **IDENTITIES)
    full = freeze_inputs("full", **IDENTITIES)
    assert len(pilot["case_ids"]) == 30
    assert pilot["case_ids"] == stage_a_case_ids()
    assert len(full["case_ids"]) == 460
    assert full["case_ids"] == [case.case_id for case in final_corpus()]
    assert full["selected_corpus_sha256"] == QWEN_FROZEN["final_corpus_sha256"]
    assert pilot["selected_corpus_sha256"] != full["selected_corpus_sha256"]
    assert digest(pilot) != digest(full)
    for inputs in (pilot, full):
        assert inputs["final_plan_sha256"] == QWEN_FROZEN["final_plan_sha256"]
        assert inputs["final_corpus_sha256"] == QWEN_FROZEN["final_corpus_sha256"]
        assert inputs["baseline_arms"] == list(ARMS)
        assert inputs["execution_authorized"] is False


@pytest.mark.parametrize("field", IDENTITIES)
def test_each_exact_identity_changes_the_digest(field):
    original = freeze_inputs("pilot", **IDENTITIES)
    changed = freeze_inputs("pilot", **{**IDENTITIES, field: "d" * 64})
    assert digest(original) != digest(changed)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qwen_manifest_sha256", "latest"),
        ("lfm_manifest_sha256", "a" * 64),
        ("lfm_manifest_sha256", "b" * 63),
        ("worker_attestation_sha256", "C" * 64),
    ],
)
def test_bad_or_aliased_identities_are_refused(field, value):
    with pytest.raises(ValueError):
        freeze_inputs("pilot", **{**IDENTITIES, field: value})


def test_cli_emits_reproducible_content_free_inputs(capsys):
    assert (
        main(
            [
                "--stage",
                "pilot",
                "--qwen-manifest-sha256",
                IDENTITIES["qwen_manifest_sha256"],
                "--lfm-manifest-sha256",
                IDENTITIES["lfm_manifest_sha256"],
                "--worker-attestation-sha256",
                IDENTITIES["worker_attestation_sha256"],
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    inputs = output["inputs"]
    assert output["inputs_sha256"] == digest(inputs)
    assert inputs == freeze_inputs("pilot", **IDENTITIES)
    assert inputs["model_arms"] == [
        {"name": "qwen3.5:4b-q4_K_M", "ollama_manifest_sha256": "a" * 64},
        {"name": "lfm3:1.7b", "ollama_manifest_sha256": "b" * 64},
    ]
    assert "positive" not in json.dumps(inputs)
    assert "negative" not in json.dumps(inputs)
