"""Offline qualification contracts; synthetic files and no real backend/GPU calls."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from tools.qualification.img_backend_qual_100.capability import (
    DIM_CAPABILITY,
    VERIFIED,
    capability_matrix,
    validate_evidence,
)
from tools.qualification.img_backend_qual_100.cli import build_packet, main
from tools.qualification.img_backend_qual_100.comfy_graphs import (
    build_graph,
    graph_digest,
    required_models,
    validate_graph,
)
from tools.qualification.img_backend_qual_100.inventory import (
    model_visibility,
    parse_extra_model_paths,
)
from tools.qualification.img_backend_qual_100.protocol import (
    ACTION,
    RISK_ID,
    STOP_RULES,
    AuthorizationError,
    build_protocol,
    evaluate_preconditions,
    evaluate_sample,
    preconditions_hold,
    validate_protocol,
    verify_authorization,
)
from tools.qualification.img_backend_qual_100.spec import (
    REPO_ROOT,
    build_workloads,
    digest,
    spec_digest,
)


@pytest.fixture
def protocol():
    return build_protocol(build_workloads(), filenames={}, comfy_revision="pinned-source")


def test_offline_packet_is_deterministic_and_never_executes(monkeypatch):
    monkeypatch.setattr("subprocess.check_output", Mock(side_effect=AssertionError("process call")))
    monkeypatch.setattr("socket.socket", Mock(side_effect=AssertionError("network call")))
    packet = build_packet()
    assert packet == build_packet()
    assert packet["physical_generation_performed"] is False
    assert packet["quality_performance_outcome"] == "INCONCLUSIVE"
    assert packet["citations"]["problems"] == []
    assert packet["citations"]["unchecked"]
    assert {w["workload"]["family"] for w in packet["workloads"].values()} == {
        "sdxl",
        "flux2_klein",
    }
    for workload in packet["workloads"].values():
        if workload["workload"]["family"] == "flux2_klein":
            assert (
                workload["workload"]["settings"]["assets"]["transformer"]["filename"]
                == "flux-2-klein-4b-fp8.safetensors"
            )


def test_cli_has_no_execution_switch(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--execute"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_comfy_image_capability_is_source_evidence_not_physical_verdict():
    rows = capability_matrix()
    assert all(row.comfy.status != VERIFIED for row in rows if row.dimension == DIM_CAPABILITY)
    assert validate_evidence(rows, repo_root=REPO_ROOT)["problems"] == []
    submission = next(row for row in rows if row.row_id == "submission_semantics")
    assert "not an idempotency key" in submission.consequence


@pytest.mark.parametrize("workload_id", list(build_workloads()))
def test_graph_single_image_budget_and_digest(workload_id):
    workload = build_workloads()[workload_id]
    graph = build_graph(workload)
    assert graph_digest(graph) == graph_digest(build_graph(workload))
    latent = next(
        n
        for n in graph.values()
        if n["class_type"] in ("EmptyLatentImage", "EmptyFlux2LatentImage")
    )
    assert latent["inputs"]["batch_size"] == 1
    assert latent["inputs"]["width"] == workload.settings["width"]
    assert latent["inputs"]["height"] == workload.settings["height"]
    assert required_models(graph)


def test_spec_digest_covers_fairness_notes_and_parameters():
    workloads = build_workloads()
    before = spec_digest(workloads)
    workloads["S1_SDXL_BASELINE"].settings["steps"] += 1
    assert spec_digest(workloads) != before
    params = build_workloads()["S1_SDXL_BASELINE"].parameters
    assert next(p for p in params if p.name == "vae").parity == "unverified"
    assert next(p for p in params if p.name == "clip_skip").parity == "approximate"


@pytest.fixture
def schema():
    return {
        "Source": {"input": {"required": {}}, "output": ["MODEL"]},
        "Sink": {
            "input": {
                "required": {
                    "model": ["MODEL"],
                    "steps": ["INT", {"min": 1, "max": 10}],
                    "mode": [["supported"]],
                }
            },
            "output": [],
        },
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_class",
        "missing_input",
        "unknown_input",
        "enum",
        "index",
        "link",
        "type",
        "bool_index",
        "range",
    ],
)
def test_graph_schema_rejects_invalid_draft(schema, mutation):
    graph = {
        "1": {"class_type": "Source", "inputs": {}},
        "2": {"class_type": "Sink", "inputs": {"model": ["1", 0], "steps": 4, "mode": "supported"}},
    }
    assert validate_graph(graph, schema) == []
    inputs = graph["2"]["inputs"]
    if mutation == "missing_class":
        graph["2"]["class_type"] = "Unknown"
    elif mutation == "missing_input":
        del inputs["steps"]
    elif mutation == "unknown_input":
        inputs["guess"] = 1
    elif mutation == "enum":
        inputs["mode"] = "unsupported"
    elif mutation == "index":
        inputs["model"] = ["1", -1]
    elif mutation == "link":
        inputs["model"] = ["missing", 0]
    elif mutation == "type":
        schema["Source"]["output"] = ["CLIP"]
    elif mutation == "bool_index":
        inputs["model"] = ["1", True]
    elif mutation == "range":
        inputs["steps"] = 0
    assert validate_graph(graph, schema)


def test_inventory_relative_yaml_and_file_hash_are_not_name_proof(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    model = models / "toy.safetensors"
    model.write_bytes(b"weights")
    config = tmp_path / "extra.yaml"
    config.write_text("toy:\n  base_path: .\n  checkpoints: models\n", encoding="utf-8")
    roots = parse_extra_model_paths(config)
    graph = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "toy"}}}
    frozen = {model.name: {"size": 7, "sha256": hashlib.sha256(b"weights").hexdigest()}}
    assert model_visibility(graph, roots, frozen=frozen)[0]["status"] == "size_match"
    assert model_visibility(graph, roots, frozen=frozen, hash_files=True)[0]["status"] == "exact"
    model.write_bytes(b"changed")
    assert model_visibility(graph, roots, frozen=frozen, hash_files=True)[0]["status"] == "mismatch"


@pytest.mark.parametrize("fault", [True, None, False])
def test_recent_gpu_fault_blocks_even_otherwise_healthy_host(protocol, fault):
    host = {
        "gpu_fault_active": fault,
        "ram_total_gb": 34,
        "ram_available_gb": 30,
        "gpu": {"vram_used_mib": 700, "temp_c": 40},
    }
    findings = evaluate_preconditions(
        protocol["stages"][0]["preconditions"],
        host=host,
        repository_clean=True,
        qualification_port_free=True,
        models_exact=True,
    )
    assert preconditions_hold(findings) is (fault is False)


@pytest.mark.parametrize("alteration", ["case", "limits", "stop_rules", "stage_digest"])
def test_protocol_binding_rejects_tampering(protocol, alteration):
    validate_protocol(protocol)
    changed = copy.deepcopy(protocol)
    if alteration == "case":
        changed["stages"][0]["cases"][0]["graph_sha256"] = "changed"
    elif alteration == "limits":
        changed["stages"][0]["limits"]["retries"] = 2
    elif alteration == "stop_rules":
        changed["stop_rules"]["temp_stop_c"] = 100
    elif alteration == "stage_digest":
        changed["stages"][0]["stage_digest"] = "changed"
    with pytest.raises(AuthorizationError):
        validate_protocol(changed)
    changed["protocol_digest"] = digest(
        {k: v for k, v in changed.items() if k != "protocol_digest"}
    )
    with pytest.raises(AuthorizationError):
        validate_protocol(changed)


def test_record_validation_is_bound_and_never_execution_permission(protocol):
    now = datetime(2026, 10, 13, tzinfo=UTC)
    stage = protocol["stages"][0]
    record = {
        "owner": "Rob",
        "action": ACTION,
        "stage_id": stage["stage_id"],
        "stage_digest": stage["stage_digest"],
        "protocol_digest": protocol["protocol_digest"],
        "source_sha": "source",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "accepted_risk": RISK_ID,
    }
    verify_authorization(
        record,
        stage=stage,
        protocol=protocol,
        protocol_digest=protocol["protocol_digest"],
        source_sha="source",
        now=now,
    )
    with pytest.raises(AuthorizationError):
        verify_authorization(
            {**record, "owner": "someone"},
            stage=stage,
            protocol=protocol,
            protocol_digest=protocol["protocol_digest"],
            source_sha="source",
            now=now,
        )


def test_missing_gpu_and_safety_stops(protocol):
    findings = evaluate_preconditions(
        protocol["stages"][0]["preconditions"],
        host={"gpu": None},
        repository_clean=True,
        qualification_port_free=True,
        models_exact=True,
    )
    assert not preconditions_hold(findings)
    rules = asdict(STOP_RULES)
    assert evaluate_sample(rules, vram_mib=12282, temp_c=40, ram_available_gb=30, low_ram_streak=0)[
        0
    ]
    assert evaluate_sample(rules, vram_mib=700, temp_c=84, ram_available_gb=30, low_ram_streak=0)[0]
    assert evaluate_sample(rules, vram_mib=700, temp_c=40, ram_available_gb=0.1, low_ram_streak=4)[
        0
    ]
