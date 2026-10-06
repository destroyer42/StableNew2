"""Frozen qualification intent reaches real executor payload building, without real HTTP/GPU.

All eight physical NJRs are previewed without submitting them. Pair-A integration uses distinct
temporary TEST identities and the existing JobService/SQLite/run_njr harness with fake transport.
"""
from __future__ import annotations

import base64
import copy
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from src.api.client import SDWebUIClient
from src.api.forge_client import ForgeWebUIClient
from src.controller.job_service import JobService
from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.image_backends.image_backend_registry import ImageBackendRegistry
from src.pipeline.executor import Pipeline
from src.pipeline.global_prompt_policy import (
    GLOBAL_NEGATIVE_STAGE_FLAGS,
    GLOBAL_POSITIVE_STAGE_FLAG,
    apply_global_prompt_policy,
    has_frozen_global_prompt_policy,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_model import JobStatus
from src.utils import StructuredLogger
from src.utils.config import ConfigManager
from tests.helpers.fake_webui_transport import TINY_PNG_B64, FakeWebUITransport
from tests.helpers.njr_queue_harness import run_njr_via_queue
from tools.qualification.img_forge_100 import provenance, run

FIXTURE = Path(__file__).resolve().parents[1] / "data/contracts/img_forge_100_frozen_intent.json"
POLICY_FLAGS = (GLOBAL_POSITIVE_STAGE_FLAG, *GLOBAL_NEGATIVE_STAGE_FLAGS)


@pytest.fixture
def frozen_matrix(tmp_path):
    fixture = json.loads(FIXTURE.read_text())
    assets = {}
    for name in ("checkpoint", "lora", "input", "face_detector", "hand_detector"):
        path = tmp_path / name
        path.write_bytes(base64.b64decode(TINY_PNG_B64) if name == "input" else b"fixture")
        assets[name] = {"path": str(path), "sha256": provenance.hash_file(path)}
    return {"package": "PR-IMG-FORGE-100", "stable_sha": "a" * 40, "assets": assets,
            "endpoints": {"a1111_webui": "http://127.0.0.1:7860",
                          "forge_webui": "http://127.0.0.1:7871"},
            "observed_comfy_endpoint": "http://127.0.0.1:8189", **fixture}


@pytest.fixture
def isolated_execution(monkeypatch, tmp_path):
    """Isolate mutable files, process/GPU observations, transitions and all HTTP in test fakes."""
    monkeypatch.chdir(tmp_path)
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "global-prompts",
    )
    # Deliberately hostile runtime values must never leak into frozen prompts.
    manager.save_global_positive_state("MUTABLE runtime positive", True)
    manager.save_global_negative_state("MUTABLE runtime negative", True)
    monkeypatch.setattr("src.pipeline.executor.ConfigManager", lambda: manager)
    monkeypatch.setattr(Pipeline, "_ensure_runtime_admissible",
                        lambda *_args, **_kwargs: {"status": "healthy", "reasons": []})
    monkeypatch.setattr(Pipeline, "_apply_webui_defaults_once", lambda *_args: None)
    monkeypatch.setattr(Pipeline, "_maybe_apply_workload_launch_policy", lambda *_args, **_kw: None)
    monkeypatch.setattr("src.pipeline.executor.collect_gpu_snapshot", lambda: {})
    monkeypatch.setattr(PipelineRunner, "_start_gpu_survivor_telemetry", lambda *_a, **_k: None)
    monkeypatch.setattr("src.api.healthcheck.probe_webui_endpoint", lambda *_a, **_k: "free")
    monkeypatch.setattr("src.video.comfy_healthcheck.probe_comfy_endpoint", lambda *_a, **_k: "free")
    # Absolute network denial: only the explicit instance fake can answer any request.
    def forbidden(*_args, **_kwargs):
        pytest.fail("Real HTTP is forbidden in frozen-intent tests")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    return manager


def _client(backend, settings):
    cls = ForgeWebUIClient if backend == "forge_webui" else SDWebUIClient
    transport = FakeWebUITransport(flavor="forge" if backend == "forge_webui" else "a1111",
                                   checkpoint=settings["checkpoint"], seed=settings["seed"])
    client = cls(base_url="http://invalid.test", options_write_enabled=True)
    client._session.request = transport
    client._options_min_interval_seconds = 0
    return client, transport


def _assert_policy(config):
    assert has_frozen_global_prompt_policy(config)
    assert config["global_prompt_policy_source"] == "frozen_njr"
    assert set(POLICY_FLAGS) == {
        "apply_global_positive_txt2img", "apply_global_negative_txt2img",
        "apply_global_negative_img2img", "apply_global_negative_adetailer",
        "apply_global_negative_upscale",
    }
    assert all(config["pipeline"][flag] is False for flag in POLICY_FLAGS)
    assert config["prompt_optimizer"] == {"enabled": False}


def _assert_exact(actual, expected):
    assert actual == expected
    assert actual.encode("utf-8") == expected.encode("utf-8")


def test_all_eight_njrs_freeze_complete_policy_without_changing_matrix(frozen_matrix, tmp_path):
    original = copy.deepcopy(frozen_matrix)
    run.validate_matrix(frozen_matrix)
    for case in frozen_matrix["cases"]:
        record = run.compile_case(frozen_matrix, case, tmp_path)
        _assert_policy(record.config)
        assert record.seed == 424242
    assert frozen_matrix == original


def test_recorded_global_terms_are_frozen_but_application_is_disabled(frozen_matrix, tmp_path):
    frozen_matrix["settings"].update(global_positive_prompt="frozen positive",
                                     global_negative_prompt="frozen negative")
    record = run.compile_case(frozen_matrix, frozen_matrix["cases"][0], tmp_path)
    _assert_policy(record.config)
    assert record.config["global_positive_prompt"] == "frozen positive"
    assert record.config["global_negative_prompt"] == "frozen negative"


@pytest.mark.parametrize("case_id", run.CASE_IDS)
def test_eight_case_previews_preserve_every_stage_prompt_before_http(
    case_id, frozen_matrix, tmp_path, monkeypatch, isolated_execution,
):
    # Preview never submits any physical NJR; PipelineRunner still constructs real stage requests.
    monkeypatch.setattr(JobService, "submit_njrs", lambda *_a, **_k: pytest.fail("Preview submitted a job"))
    case = next(c for c in frozen_matrix["cases"] if c["case_id"] == case_id)
    record = run.compile_case(frozen_matrix, case, tmp_path)
    before = record.to_dict()
    _assert_policy(record.config)
    # Change the persisted runtime files AFTER freezing intent.
    isolated_execution.save_global_positive_state("CHANGED runtime positive", True)
    isolated_execution.save_global_negative_state("CHANGED runtime negative", True)
    client, transport = _client(case["backend"], frozen_matrix["settings"])
    transition = Mock()
    transition.prepare_for.return_value = Mock(ready=True)
    registry = ImageBackendRegistry()
    for backend in (A1111WebUIImageBackend, ForgeWebUIImageBackend):
        registry.register(backend(transition=transition))
    runner = PipelineRunner(client, StructuredLogger(), runs_base_dir=str(tmp_path / "output"),
                            image_backend_registry=registry)
    expected_positive = record.positive_prompt
    expected_negative = record.negative_prompt
    payloads = []
    translated = []
    original_generate = runner._pipeline._generate_images_with_progress
    def intercept(stage, payload, **_kwargs):
        payloads.append((stage, copy.deepcopy(payload)))
        # Mock response only: no HTTP generation call, no inference, tiny synthetic artifact.
        return {"images": [TINY_PNG_B64], "info": {"seed": 424242, "all_seeds": [424242]}}
    monkeypatch.setattr(runner._pipeline, "_generate_images_with_progress", intercept)
    # Capture exact optimizer/global intent received by executor for every stage, including extras.
    original_terms = runner._pipeline._global_prompt_terms
    def terms(config, key):
        translated.append(copy.deepcopy(config))
        return original_terms(config, key)
    monkeypatch.setattr(runner._pipeline, "_global_prompt_terms", terms)
    original_upscale = runner._pipeline.run_upscale_stage
    def upscale(**kwargs):
        config = kwargs["config"]
        _assert_policy(config)
        _assert_exact(config["prompt"], expected_positive)
        _assert_exact(config["negative_prompt"], expected_negative)
        return original_upscale(**kwargs)
    monkeypatch.setattr(runner._pipeline, "run_upscale_stage", upscale)
    image = Path(frozen_matrix["assets"]["input"]["path"])
    try:
        for stage in record.stage_chain:
            result = runner._execute_image_backend(
                backend_id=case["backend"], stage_name=stage.stage_type, njr=record,
                stage_config=stage.to_dict(), run_dir=tmp_path / "output",
                input_image_path=image if stage.stage_type != "txt2img" else None,
                image_name=stage.stage_type, prompt=expected_positive, negative_prompt=expected_negative,
                cancel_token=None, selected_model=record.base_model, selected_vae="Automatic",
            )
            assert result is not None, stage.stage_type
            if stage.stage_type == "upscale":
                outputs = result["prompt_optimizer_v3"]["outputs"]
                _assert_exact(outputs["positive_final"], expected_positive)
                _assert_exact(outputs["negative_final"], expected_negative)
        for _stage, payload in payloads:
            _assert_exact(payload["prompt"], expected_positive)
            _assert_exact(payload["negative_prompt"], expected_negative)
            assert payload["seed"] == 424242
            if case["scenario"] == "B":
                assert payload["prompt"].endswith(" <lora:add-detail-xl:0.82>")
            if "ADetailer" in payload.get("alwayson_scripts", {}):
                face, hand = payload["alwayson_scripts"]["ADetailer"]["args"][2:]
                assert face["ad_model"] == "face_yolov8n.pt"
                assert hand["ad_model"] == "hand_yolov8n.pt"
                for args in (face, hand):
                    _assert_exact(args["ad_prompt"], expected_positive)
                    _assert_exact(args["ad_negative_prompt"], expected_negative)
        assert len(payloads) == (2 if case["scenario"] == "D" else 1)
        assert translated
        for config in translated:
            _assert_policy(config)
        assert not any(path in ("/sdapi/v1/txt2img", "/sdapi/v1/img2img")
                       for _, path, _ in transport.calls)
        assert record.to_dict() == before
    finally:
        monkeypatch.setattr(runner._pipeline, "_generate_images_with_progress", original_generate)
        client.close()


@pytest.mark.parametrize("backend", run.BACKENDS)
def test_pair_a_exact_prompt_through_jobservice_sqlite_runner_executor(
    backend, frozen_matrix, tmp_path, isolated_execution, monkeypatch,
):
    case = next(c for c in frozen_matrix["cases"] if c["case_id"] == f"A-{backend}")
    physical_record = run.compile_case(frozen_matrix, case, tmp_path)
    # TEST identity only; neither a physical cohort submission nor reuse of a failed ID.
    record = replace(physical_record, job_id=f"test-frozen-intent-{backend}")
    client, transport = _client(backend, frozen_matrix["settings"])
    seen = []
    original_generate = Pipeline._generate_images_with_progress
    def intercept(self, stage, payload, **kwargs):
        _assert_exact(payload["prompt"], record.positive_prompt)
        _assert_exact(payload["negative_prompt"], record.negative_prompt)
        assert payload["seed"] == 424242
        seen.append(copy.deepcopy(payload))
        return {"images": [TINY_PNG_B64], "info": {"seed": 424242, "all_seeds": [424242]}}
    monkeypatch.setattr(Pipeline, "_generate_images_with_progress", intercept)
    try:
        entry = run_njr_via_queue(record, client, artifact_root=tmp_path / "test-queue")
        assert entry.status is JobStatus.COMPLETED, entry.error_message
        assert len(seen) == 1
        snapshot_config = entry.snapshot["normalized_job"]["workload"]["config"]
        _assert_policy(snapshot_config)
        assert entry.result["metadata"]["image_backend_id"] == backend
        assert not transport.generation_calls  # No HTTP generation even against the instance fake.
    finally:
        monkeypatch.setattr(Pipeline, "_generate_images_with_progress", original_generate)
        client.close()


@pytest.mark.parametrize("backend", run.BACKENDS)
def test_normal_enabled_frozen_policy_still_applies_through_backend(
    backend, frozen_matrix, tmp_path, monkeypatch, isolated_execution,
):
    case = next(c for c in frozen_matrix["cases"] if c["case_id"] == f"A-{backend}")
    record = run.compile_case(frozen_matrix, case, tmp_path)
    enabled = apply_global_prompt_policy(record.config, positive_enabled=True, negative_enabled=True,
                                         positive_text="frozen positive", negative_text="frozen negative")
    record = replace(record, workload=replace(record.workload, config=enabled))
    client, _ = _client(backend, frozen_matrix["settings"])
    captured = []
    monkeypatch.setattr(Pipeline, "_generate_images_with_progress",
                        lambda _self, _stage, payload, **_kwargs: captured.append(dict(payload)) or
                        {"images": [TINY_PNG_B64], "info": {"seed": 424242}})
    try:
        entry = run_njr_via_queue(replace(record, job_id=f"test-enabled-policy-{backend}"), client,
                                  artifact_root=tmp_path / "enabled-queue")
        assert entry.status is JobStatus.COMPLETED, entry.error_message
        assert captured[0]["prompt"] == "frozen positive, " + record.positive_prompt
        assert captured[0]["negative_prompt"] == record.negative_prompt + ", frozen negative"
        assert "MUTABLE" not in str(captured[0])
    finally:
        client.close()
