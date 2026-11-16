"""Checkpoint policy and image performance at the canonical runner and fake Forge transport."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.api.forge_client import ForgeWebUIClient
from src.controller.runtime_state import CancellationError
from src.pipeline.adetailer_checkpoint import CHECKPOINT_SELECTION_KEY
from src.pipeline.adetailer_localized import EXECUTION_MODE_KEY, LOCALIZED_ONLY
from src.pipeline.image_performance import ImagePerformanceTrace, observe_cleanup
from src.pipeline.njr_compiler import _with_fresh_adetailer_mode
from src.pipeline.njr_core_v26 import StageConfig
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from tests.helpers.fake_webui_transport import FakeResponse, FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr
from tests.pipeline.test_adetailer_localized_240b import mask, respond, source_image

BASE = "sdxl.safetensors"
ALTERNATE = "alternate.safetensors"
LOCALIZED_PATH = "/stablenew/v1/adetailer/localized"


class ForgeTransport(FakeWebUITransport):
    def __init__(self, *, checkpoint=BASE, masks=0, fail_after=None, failure_status=503):
        super().__init__(checkpoint=checkpoint)
        self.masks = masks
        self.fail_after = fail_after
        self.failure_status = failure_status
        self.localized_calls = 0
        self.models_at_dispatch = []

    def _post(self, path, body):
        if path == "/sdapi/v1/txt2img":
            self.models_at_dispatch.append(self.options["sd_model_checkpoint"])
            result = super()._post(path, body).json()
            from src.pipeline.adetailer_localized import encode_png

            result["images"] = [encode_png(source_image()) for _ in result["images"]]
            return FakeResponse(result)
        if path == LOCALIZED_PATH:
            self.localized_calls += 1
            self.models_at_dispatch.append(self.options["sd_model_checkpoint"])
            if self.fail_after is not None and self.localized_calls > self.fail_after:
                return FakeResponse({"detail": "companion unavailable"}, self.failure_status)
            passes = tuple((entry["label"], entry["args"]) for entry in body["passes"])
            regions = [mask((3 + index * 20, 4, 8 + index * 20, 9)) for index in range(self.masks)]
            evidence = respond(
                source_image(),
                dict.fromkeys((label for label, _ in passes), regions),
                passes=passes,
            )
            for entry in evidence["passes"]:
                entry["sampled_masks"] = entry["mask_count"]
            return FakeResponse(evidence)
        return super()._post(path, body)

    @property
    def model_writes(self):
        return [
            body["sd_model_checkpoint"]
            for method, path, body in self.calls
            if method == "POST" and path == "/sdapi/v1/options" and "sd_model_checkpoint" in body
        ]


def _njr(tmp_path: Path, *, images=1, extra=None, fresh=True, with_adetailer=True, vae=None):
    stages = (StageConfig("txt2img", enabled=True, model=BASE, vae=vae),)
    if with_adetailer:
        stages += (StageConfig("adetailer", enabled=True, extra=extra or {}),)
    if fresh:
        stages = _with_fresh_adetailer_mode(stages)
    return make_pipeline_njr(
        images_per_prompt=images,
        path_output_dir=str(tmp_path),
        stage_chain=stages,
        config={"model": BASE, "width": 96, "height": 72},
        backend_options={"image": {"backend_id": "forge_webui"}},
    )


def _runner(tmp_path, monkeypatch, transport):
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    monkeypatch.setattr(client._session, "request", transport)
    monkeypatch.setattr("src.pipeline.executor.collect_gpu_snapshot", lambda: None)
    client._options_min_interval_seconds = 0.0
    runner = PipelineRunner(client, Mock(), runs_base_dir=str(tmp_path))
    monkeypatch.setattr(
        runner._pipeline, "_ensure_runtime_admissible", lambda **_: {"status": "healthy"}
    )
    monkeypatch.setattr(runner._pipeline, "_ensure_webui_true_ready", lambda: None)
    monkeypatch.setattr(runner._pipeline, "_check_webui_health_before_stage", lambda _stage: None)
    return runner


@pytest.mark.parametrize(
    ("count", "masks", "with_adetailer"), [(1, 0, False), (1, 1, True), (4, 2, True), (4, 0, True)]
)
def test_two_warm_jobs_count_final_outputs_and_keep_checkpoint(
    tmp_path, monkeypatch, count, masks, with_adetailer
):
    transport = ForgeTransport(masks=masks)
    runner = _runner(tmp_path, monkeypatch, transport)
    for _ in range(2):
        result = runner.run_njr(_njr(tmp_path, images=count, with_adetailer=with_adetailer))
        assert result.success, result.error
        metrics = result.metadata["efficiency_metrics"]
        assert metrics["requested_image_count"] == metrics["returned_base_image_count"] == count
        assert metrics["images_processed"] == metrics["final_output_image_count"] == count
        assert metrics["stage_execution_count"] == 1 + count * with_adetailer
        assert metrics["model_switches"] == metrics["vae_switches"] == 0
        trace = result.metadata["image_performance"]
        assert trace["schema"] == "stablenew.image-performance.v1"
        assert len(trace["stages"]) == 1 + count * with_adetailer
        for stage in trace["stages"][1:]:
            assert stage["checkpoint"]["selection"] == "inherit"
            assert stage["checkpoint"]["effective"] == stage["checkpoint"]["observed"] == BASE
            assert stage["mode"] == LOCALIZED_ONLY
            assert stage["mask_count"] == masks
            assert stage["source_passthrough"] == (masks == 0)
            assert stage["passes"][0]["sampled_masks"] == masks
            assert stage["passes"][1]["effective_masks"] is None
            assert stage["timing_ms"]["backend_request"] is not None
            assert stage["backend_internal_timing"] == {"status": "not_instrumented"}
        job_cleanup = [item for item in trace["operations"] if item["reason"] == "job_start"]
        assert len(job_cleanup) == 1 and not job_cleanup[0]["unload_checkpoint_requested"]
        assert job_cleanup[0]["operations"]["python_gc"]["outcome"] == "completed"
    assert set(transport.models_at_dispatch) == {BASE}
    assert transport.model_writes == []
    assert "/sdapi/v1/unload-checkpoint" not in transport.paths("POST")


def test_cold_switch_then_inherit_and_explicit_selection_agree_with_forge_preflight(
    tmp_path, monkeypatch
):
    transport = ForgeTransport(checkpoint=ALTERNATE)
    runner = _runner(tmp_path, monkeypatch, transport)
    preflight = []
    backend = runner._image_backends.get("forge_webui")
    dependency_gate = backend._dependency_gate

    def observe(pipeline, request):
        preflight.append(request.selected_model)
        return dependency_gate(pipeline, request)

    monkeypatch.setattr(backend, "_dependency_gate", observe)
    warm = runner.run_njr(_njr(tmp_path))
    assert warm.success, warm.error
    assert transport.model_writes == [BASE]
    switches = [
        op
        for op in warm.metadata["image_performance"]["operations"]
        if op["operation"] == "model_sync"
    ]
    assert [op["outcome"] for op in switches] == ["switch_verified", "already_verified"]
    assert switches[0]["duration_ms"] >= 0
    assert warm.metadata["efficiency_metrics"]["model_switches"] == 1

    explicit = runner.run_njr(
        _njr(
            tmp_path,
            extra={
                CHECKPOINT_SELECTION_KEY: {"mode": "explicit", "checkpoint": ALTERNATE},
                "adetailer_checkpoint_model": "stale.safetensors",
            },
        )
    )
    assert explicit.success, explicit.error
    assert transport.model_writes == [BASE, ALTERNATE]
    assert preflight == transport.models_at_dispatch == [BASE, BASE, BASE, ALTERNATE]
    stage = explicit.metadata["image_performance"]["stages"][-1]
    assert stage["checkpoint"]["selection"] == "explicit"
    assert stage["checkpoint"]["effective"] == ALTERNATE


def test_ambiguous_frozen_checkpoint_refuses_before_cleanup_transition_or_posts(
    tmp_path, monkeypatch
):
    transport = ForgeTransport()
    runner = _runner(tmp_path, monkeypatch, transport)
    no_transition = Mock(side_effect=AssertionError("runtime transition"))
    monkeypatch.setattr(
        runner._image_backends.get("forge_webui")._transition, "prepare_for", no_transition
    )
    original = _njr(tmp_path, fresh=False, extra={"adetailer_checkpoint_model": ALTERNATE})
    replay = compile_replay_intent(ReplayIntent(record=original), id_fn=lambda: "replayed")
    assert original.stage_chain == replay.stage_chain
    for njr in (original, replay):
        with pytest.raises(ValueError, match=r"checkpoint conflict.*Create a fresh job"):
            runner.run_njr(njr)
    assert transport.calls == []
    no_transition.assert_not_called()


def test_unambiguous_legacy_keeps_img2img_and_unknown_masks(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch, transport := ForgeTransport())
    result = runner.run_njr(_njr(tmp_path, fresh=False, extra={"sd_model_checkpoint": BASE}))
    assert result.success, result.error
    assert transport.paths("POST")[-1] == "/sdapi/v1/img2img"
    assert transport.model_writes == []
    stage = result.metadata["image_performance"]["stages"][-1]
    assert stage["mode"] == "legacy_whole_image"
    assert stage["checkpoint"]["selection"] == "legacy"
    assert all(entry["effective_masks"] is None for entry in stage["passes"])
    assert stage["mask_count"] is None


def test_partial_failure_counts_only_completed_final_paths(tmp_path, monkeypatch):
    transport = ForgeTransport(fail_after=2, masks=1, failure_status=404)
    runner = _runner(tmp_path, monkeypatch, transport)
    result = runner.run_njr(_njr(tmp_path, images=4))
    metrics = result.metadata["efficiency_metrics"]
    assert metrics["requested_image_count"] == metrics["returned_base_image_count"] == 4
    assert metrics["images_processed"] == 2
    trace = result.metadata["image_performance"]
    failed = trace["stages"][-1]
    assert failed["outcome"] == "failed" and failed["timing_ms"]["backend_request"] is not None
    assert failed["timing_ms"]["finalization"] is None
    assert transport.localized_calls == 3
    assert "/sdapi/v1/img2img" not in transport.paths("POST")


def test_operation_boundaries_cancel_and_diagnostic_data(tmp_path, monkeypatch):
    transport = ForgeTransport(masks=1)
    runner = _runner(tmp_path, monkeypatch, transport)
    executor = runner._pipeline
    now = [0.0]
    trace = ImagePerformanceTrace(clock=lambda: now[0])
    executor._image_performance = trace
    client_generate = executor.client.generate_images

    def request(*args, **kwargs):
        now[0] += 2.0
        return client_generate(*args, **kwargs)

    prep = executor._load_image_base64

    def prepare(*args):
        now[0] += 1.0
        return prep(*args)

    def cancel(_token, where):
        if where == "adetailer post-call":
            raise CancellationError()

    monkeypatch.setattr(executor, "_load_image_base64", prepare)
    monkeypatch.setattr(executor.client, "generate_images", request)
    monkeypatch.setattr(executor, "_ensure_not_cancelled", cancel)
    src = tmp_path / "private-input.png"
    source_image().save(src)
    with pytest.raises(CancellationError):
        executor.run_adetailer_stage(
            src,
            {"adetailer_enabled": True, EXECUTION_MODE_KEY: LOCALIZED_ONLY},
            tmp_path,
            "cancelled",
            prompt="private prompt",
        )
    stage = trace.stages[-1]
    assert stage["outcome"] == "cancelled"
    assert stage["timing_ms"] == {
        "preparation": 1000.0,
        "backend_request": 2000.0,
        "finalization": None,
        "stage_total": 3000.0,
        "model_sync": None,
        "memory_cleanup": None,
    }
    assert "private" not in str(trace.snapshot("cancelled"))
    assert not (tmp_path / "cancelled.png").exists()


def test_cleanup_does_not_confuse_local_gc_with_successful_unload():
    from contextlib import nullcontext

    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861")
    client._request_context = Mock(return_value=nullcontext(None))
    trace = ImagePerformanceTrace()
    observe_cleanup(client, trace, reason="reprocessing_before_image", unload_model=True)
    unload = trace.operations[-1]
    assert unload["outcome"] == "partial"
    assert unload["operations"]["unload_checkpoint"]["outcome"] == "failed"
    assert unload["operations"]["python_gc"]["outcome"] == "completed"
    observe_cleanup(client, trace, reason="pressure_mitigation", unload_model=False)
    assert trace.operations[-1]["unload_checkpoint_requested"] is False
    assert client._request_context.call_count == 1


def test_stale_stage_model_does_not_become_frozen_base_checkpoint(tmp_path):
    job = _njr(tmp_path, fresh=False)
    job = replace(
        job, stages=(replace(job.stages[0], model=None), replace(job.stages[1], model=ALTERNATE))
    )
    assert PipelineRunner._selected_stage_model("txt2img", job.stages[0].to_dict(), njr=job) == BASE
    with pytest.raises(ValueError, match="checkpoint conflict"):
        PipelineRunner._selected_stage_model("adetailer", job.stages[1].to_dict(), njr=job)


def test_request_local_checkpoint_and_vae_are_distinct_from_ambient_state(tmp_path, monkeypatch):
    transport = ForgeTransport(masks=1)
    runner = _runner(tmp_path, monkeypatch, transport)
    monkeypatch.setattr(
        "src.pipeline.executor.app_config.adetailer_request_local_pinning_enabled", lambda: True
    )
    extra = {
        CHECKPOINT_SELECTION_KEY: {"mode": "explicit", "checkpoint": ALTERNATE},
        "enable_hands_pass": True,
    }
    vae = "sdxl_vae.safetensors"
    for _ in range(2):
        result = runner.run_njr(_njr(tmp_path, extra=extra, vae=vae))
        assert result.success, result.error
        stage = result.metadata["image_performance"]["stages"][-1]
        assert stage["checkpoint"] == {
            "selection": "explicit",
            "effective": ALTERNATE,
            "observed": None,
            "switch_requested": False,
            "switch_verified": False,
            "request_local_pinning": True,
            "ambient_entry": BASE,
            "ambient_exit": BASE,
        }
        assert stage["mask_count"] == 2
        hands = stage["passes"][1]
        assert hands["detector_id"].startswith("hand_")
        assert hands["sampled_masks"] == hands["effective_masks"] == 1
    requests = [
        body for verb, path, body in transport.calls if verb == "POST" and path == LOCALIZED_PATH
    ]
    assert all(
        body["override_settings"]
        == {
            "sd_model_checkpoint": ALTERNATE,
            "sd_vae": vae,
        }
        for body in requests
    )
    assert (
        len(
            [
                body
                for verb, path, body in transport.calls
                if verb == "POST"
                and path == "/sdapi/v1/options"
                and "forge_additional_modules" in body
            ]
        )
        == 1
    )
    assert transport.model_writes == []


def test_cancelled_job_records_zero_final_images_in_run_metadata(tmp_path, monkeypatch):
    transport = ForgeTransport(masks=1)
    runner = _runner(tmp_path, monkeypatch, transport)
    write_metadata = Mock()
    monkeypatch.setattr("src.pipeline.pipeline_runner.write_run_metadata", write_metadata)
    executor = runner._pipeline

    def cancel(_token, where):
        if where == "adetailer post-call":
            raise CancellationError()

    monkeypatch.setattr(executor, "_ensure_not_cancelled", cancel)
    with pytest.raises(CancellationError):
        runner.run_njr(_njr(tmp_path))
    metadata = write_metadata.call_args.args[1]
    assert metadata["efficiency_metrics"]["final_output_image_count"] == 0
    trace = metadata["image_performance"]
    assert trace["outcome"] == trace["stages"][-1]["outcome"] == "cancelled"
    assert trace["stages"][-1]["timing_ms"]["finalization"] is None


def test_verified_exact_profile_is_refused_for_adetailer_before_runtime(tmp_path, monkeypatch):
    from src.image_backends.forge_klein_profile import latest_klein_profile

    transport = ForgeTransport()
    runner = _runner(tmp_path, monkeypatch, transport)
    extra = {
        CHECKPOINT_SELECTION_KEY: {
            "mode": "explicit",
            "checkpoint": latest_klein_profile().transformer.filename,
        }
    }
    with pytest.raises(ValueError, match="ADetailer cannot run with"):
        runner.run_njr(_njr(tmp_path, extra=extra))
    assert transport.calls == []


def test_forge_refuses_known_ambiguous_served_checkpoint_before_adetailer_post(
    tmp_path, monkeypatch
):
    transport = ForgeTransport()
    transport.checkpoint_files = {
        ALTERNATE: "first/alternate.safetensors",
        "second/alternate.safetensors": "second/alternate.safetensors",
    }
    runner = _runner(tmp_path, monkeypatch, transport)
    extra = {CHECKPOINT_SELECTION_KEY: {"mode": "explicit", "checkpoint": ALTERNATE}}
    result = runner.run_njr(_njr(tmp_path, extra=extra))
    assert not result.success
    assert "Forge lists multiple files" in result.error
    assert transport.model_writes == []
    assert LOCALIZED_PATH not in transport.paths("POST")
    assert result.metadata["efficiency_metrics"]["final_output_image_count"] == 0
