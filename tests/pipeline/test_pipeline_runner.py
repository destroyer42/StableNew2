from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.pipeline.animatediff_retirement import AnimateDiffRetiredError
from src.pipeline.job_models_v2 import (
    NormalizedJobRecord,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    migrate_legacy_njr,
)
from src.pipeline.pipeline_runner import PipelineRunner, PipelineRunResult, normalize_run_result
from src.refinement.quality_metrics import build_refinement_learning_context
from src.refinement.subject_scale_policy_service import SubjectScalePolicyService
from src.services.runtime_transition_service import RuntimeTransitionCoordinator
from src.utils.error_envelope_v2 import get_attached_envelope
from src.video import VideoBackendCapabilities, VideoBackendRegistry, VideoExecutionResult
from src.video.svd_native_backend import SVDNativeVideoBackend


@pytest.fixture(autouse=True)
def isolated_runtime_endpoints(monkeypatch):
    # These runner tests use fake executors. A live operator Forge endpoint must
    # never affect their refinement observations or trigger runtime interaction.
    from src.api import healthcheck
    from src.video import comfy_healthcheck

    monkeypatch.setattr(healthcheck, "probe_webui_endpoint", lambda *a, **k: "free")
    monkeypatch.setattr(comfy_healthcheck, "probe_comfy_endpoint", lambda *a, **k: "free")


def _record_from_legacy_kwargs(**values: object) -> NormalizedJobRecord:
    """Keep runner fixtures concise while crossing the explicit legacy boundary."""

    stages = values.get("stage_chain") or ()
    if any(getattr(stage, "stage_type", "") == "txt2img" for stage in stages):
        config = values.get("config")
        has_prompt = isinstance(config, dict) and bool(config.get("prompt"))
        if not values.get("positive_prompt") and not has_prompt:
            values["positive_prompt"] = "runner test prompt"
    return migrate_legacy_njr(values)


def _with_workload(
    record: NormalizedJobRecord,
    *,
    positive_prompt: str | None = None,
    negative_prompt: str | None = None,
    intent_config: dict[str, object] | None = None,
) -> NormalizedJobRecord:
    changes: dict[str, object] = {}
    if positive_prompt is not None:
        changes["positive_prompt"] = positive_prompt
    if negative_prompt is not None:
        changes["negative_prompt"] = negative_prompt
    if intent_config is not None:
        changes["intent_config"] = intent_config
    return replace(record, workload=replace(record.workload, **changes))


def _minimal_normalized_record() -> NormalizedJobRecord:
    return _record_from_legacy_kwargs(
        job_id="runner-test",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        randomizer_summary=None,
        stage_chain=[
            StageConfig(
                stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a"
            )
        ],
    )


def test_run_njr_is_only_public_entrypoint() -> None:
    runner = PipelineRunner(Mock(), Mock())
    assert hasattr(runner, "run_njr")
    assert not hasattr(runner, "run")


def test_run_njr_delegates_to_executor() -> None:
    runner = PipelineRunner(Mock(), Mock())
    record = _minimal_normalized_record()
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": "output.png"}
    runner._pipeline = pipeline
    result = runner.run_njr(record, cancel_token=None)
    pipeline.client.free_vram.assert_called_once_with(
        unload_model=False,
        refresh_checkpoints=False,
    )
    pipeline.run_txt2img_stage.assert_called_once()
    assert result.success is True
    assert result.variants[0]["path"] == "output.png"
    assert result.variants[0]["artifact"]["primary_path"] == "output.png"
    assert result.metadata["replay_descriptor"]["artifact_type"] == "image"
    assert result.metadata["replay_descriptor"]["primary_stage"] == "txt2img"
    assert result.metadata["diagnostics_descriptor"]["output_count"] == 1


def test_run_njr_rejects_invalid_plan_before_any_runtime_call() -> None:
    from types import SimpleNamespace

    import pytest

    runner = PipelineRunner(Mock(), Mock())
    pipeline = Mock()
    pipeline.client = Mock()
    runner._pipeline = pipeline
    malformed = SimpleNamespace(
        job_id="bad-plan",
        positive_prompt="portrait",
        stage_chain=(SimpleNamespace(stage_type="", enabled=True),),
    )

    with pytest.raises(ValueError, match="explicit stage_type"):
        runner.run_njr(malformed, cancel_token=None)  # type: ignore[arg-type]

    assert pipeline.mock_calls == []
    assert pipeline.client.mock_calls == []


def test_run_njr_emits_observation_only_adaptive_refinement_metadata() -> None:
    runner = PipelineRunner(Mock(), Mock())
    record = _minimal_normalized_record()
    record = replace(
        _with_workload(
            record,
            positive_prompt="full body portrait, profile, woman, detailed face",
            negative_prompt="bad anatomy",
            intent_config={
                "adaptive_refinement": {
                    "schema": "stablenew.adaptive-refinement.v1",
                    "enabled": True,
                    "mode": "observe",
                    "profile_id": "auto_v1",
                    "detector_preference": "null",
                    "record_decisions": True,
                    "algorithm_version": "v1",
                }
            },
        ),
        source=SourceDescriptor(
            kind=SourceKind.PROMPT_PACK,
            id="pack-001",
            display_name="Pack 001",
        ),
    )
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": "output.png"}
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert "adaptive_refinement" in result.metadata
    refinement = result.metadata["adaptive_refinement"]
    assert refinement["intent"]["mode"] == "observe"
    assert refinement["prompt_intent"]["requested_pose"] == "profile"
    assert refinement["decision_bundle"]["mode"] == "observe"
    assert refinement["decision_bundle"]["policy_id"] == "observe_only_v1"
    assert refinement["decision_bundle"]["applied_overrides"] == {}
    pipeline.run_txt2img_stage.assert_called_once()


def test_run_njr_does_not_emit_adaptive_refinement_metadata_when_disabled() -> None:
    runner = PipelineRunner(Mock(), Mock())
    record = _minimal_normalized_record()
    record = _with_workload(
        record,
        intent_config={
            "adaptive_refinement": {
                "schema": "stablenew.adaptive-refinement.v1",
                "enabled": False,
                "mode": "observe",
            }
        },
    )
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": "output.png"}
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert "adaptive_refinement" not in result.metadata


def test_run_njr_caches_refinement_assessment_per_output_path(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    output_path = tmp_path / "output.png"
    output_path.write_bytes(b"png")
    record = _minimal_normalized_record()
    record = _with_workload(
        record,
        positive_prompt="portrait woman",
        intent_config={
            "adaptive_refinement": {
                "schema": "stablenew.adaptive-refinement.v1",
                "enabled": True,
                "mode": "observe",
                "profile_id": "auto_v1",
                "detector_preference": "opencv",
                "record_decisions": True,
                "algorithm_version": "v1",
            }
        },
    )

    class _ServiceStub:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def build_bundle(self, **_kwargs):
            return {
                "schema": "stablenew.refinement-decision.v1",
                "algorithm_version": "v1",
                "mode": "observe",
                "policy_id": "observe_only_v1",
                "detector_id": "null",
                "observation": {},
                "applied_overrides": {},
                "prompt_patch": {},
                "notes": [],
            }

        def assess(self, image_path):
            key = str(image_path)
            self.calls.append(key)
            return {
                "detector_id": "opencv",
                "algorithm_version": "v1",
                "image_path": key,
                "image_width": 100,
                "image_height": 100,
                "detections": [],
                "detection_count": 0,
                "primary_detection_index": None,
                "face_area_ratio": None,
                "face_height_ratio": None,
                "face_width_ratio": None,
                "scale_band": "no_face",
                "pose_band": "unknown",
                "notes": ["no_face_detected"],
            }

    service = _ServiceStub()
    runner._resolve_refinement_policy_service = lambda _pref: (service, ["opencv_requested"])  # type: ignore[method-assign]
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_txt2img_stage.return_value = {
        "path": str(output_path),
        "all_paths": [str(output_path), str(output_path)],
    }
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert service.calls == [str(output_path)]
    assert result.metadata["adaptive_refinement"]["decision_bundle"]["detector_id"] == "opencv"
    assert result.metadata["adaptive_refinement"]["detector_notes"] == ["opencv_requested"]
    assert (
        len(
            result.metadata["adaptive_refinement"]["decision_bundle"]["observation"][
                "image_assessments"
            ]
        )
        == 2
    )


def test_run_njr_records_detector_fallback_notes(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    output_path = tmp_path / "output.png"
    output_path.write_bytes(b"png")
    record = _minimal_normalized_record()
    record = _with_workload(
        record,
        positive_prompt="portrait woman",
        intent_config={
            "adaptive_refinement": {
                "schema": "stablenew.adaptive-refinement.v1",
                "enabled": True,
                "mode": "observe",
                "profile_id": "auto_v1",
                "detector_preference": "opencv",
                "record_decisions": True,
                "algorithm_version": "v1",
            }
        },
    )
    runner._resolve_refinement_policy_service = (  # type: ignore[method-assign]
        lambda _pref: (
            SubjectScalePolicyService(),
            ["opencv_requested_but_unavailable_fell_back_to_null"],
        )
    )
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": str(output_path)}
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert (
        "opencv_requested_but_unavailable_fell_back_to_null"
        in result.metadata["adaptive_refinement"]["detector_notes"]
    )


def test_collect_refinement_assessments_times_out_to_null_fallback(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    output_path = tmp_path / "late.png"
    output_path.write_bytes(b"png")

    class _SlowService:
        def assess(self, _image_path):
            raise AssertionError("timeout fallback should short-circuit before assess")

    assessments, notes = runner._collect_refinement_assessments(
        service=_SlowService(),  # type: ignore[arg-type]
        output_paths=[str(output_path)],
        timeout_seconds=-1.0,
    )

    assert notes == ["detector_timeout_fell_back_to_null"]
    assert assessments[0]["detector_id"] == "null"
    assert assessments[0]["image_path"] == str(output_path)
    assert assessments[0]["notes"] == ["detector_timeout_fell_back_to_null"]
    assert assessments[0]["scale_band"] == "unknown"
    assert assessments[0]["detection_status"] == "timeout"
    context = build_refinement_learning_context(
        {"decision_bundle": {"observation": {"image_assessments": assessments}}}
    )
    assert context["face_detected"] is None


def test_refinement_unavailable_yunet_is_not_no_face(monkeypatch, tmp_path: Path) -> None:
    import src.refinement.detectors.opencv_face_detector as detector_module

    def unavailable():
        raise RuntimeError("YuNet model missing; restore repository asset")

    monkeypatch.setattr(detector_module, "OpenCvFaceDetector", unavailable)
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    service, notes = runner._resolve_refinement_policy_service("opencv")
    assessment = service.assess(tmp_path / "output.png")
    assert "restore repository asset" in notes[-1]
    assert assessment["scale_band"] == "unknown"
    assert assessment["detection_status"] == "unavailable"


def test_refinement_unexpected_assessment_error_is_unknown(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    service = Mock()
    service.assess.side_effect = RuntimeError("unexpected failure")
    assessments, notes = runner._collect_refinement_assessments(
        service=service, output_paths=[str(tmp_path / "output.png")],
    )
    assert assessments[0]["scale_band"] == "unknown"
    assert assessments[0]["detection_status"] == "error"
    assert notes == ["detector_error_fell_back_to_null"]


def test_run_njr_executes_train_lora_and_returns_weight_artifact(tmp_path: Path) -> None:
    weight_path = tmp_path / "ada.safetensors"
    weight_path.write_bytes(b"weights")
    embedder = Mock()
    embedder.run_to_completion.return_value = {
        "success": True,
        "running": False,
        "cancelled": False,
        "error": None,
        "weight_path": str(weight_path),
        "command": ["trainer.exe", "--flag"],
        "log_tail": ["done"],
        "duration_seconds": 1.25,
    }
    lora_manager = Mock()
    lora_manager.register.return_value = {
        "character_name": "Ada",
        "weight_path": str(weight_path),
        "manifest_path": str(tmp_path / "manifest.json"),
    }
    runner = PipelineRunner(
        Mock(),
        Mock(),
        character_embedder=embedder,
        lora_manager=lora_manager,
    )
    pipeline = Mock()
    pipeline.client = Mock()
    runner._pipeline = pipeline
    record = _record_from_legacy_kwargs(
        job_id="train-job",
        config={
            "train_lora": {
                "enabled": True,
                "character_name": "Ada",
                "image_dir": str(tmp_path / "images"),
                "output_dir": str(tmp_path),
                "epochs": 10,
                "learning_rate": 0.0001,
                "base_model": "sdxl",
                "trigger_phrase": "ada person",
            },
            "pipeline": {"train_lora_enabled": True},
        },
        path_output_dir=str(tmp_path),
        filename_template="{seed}",
        created_ts=0.0,
        prompt_pack_id="character-training:ada",
        prompt_pack_name="Character Training: Ada",
        positive_prompt="Train LoRA for Ada",
        base_model="sdxl",
        stage_chain=[StageConfig(stage_type="train_lora", enabled=True, model="sdxl")],
    )

    result = runner.run_njr(record, cancel_token=None)

    embedder.run_to_completion.assert_called_once()
    lora_manager.register.assert_called_once()
    assert lora_manager.register.call_args.kwargs["metadata"]["trigger_phrase"] == "ada person"
    assert result.success is True
    assert result.variants[0]["artifact"]["artifact_type"] == "weights"
    assert result.variants[0]["artifact"]["primary_path"] == str(weight_path)
    assert result.metadata["replay_descriptor"]["artifact_type"] == "weights"
    assert result.metadata["diagnostics_descriptor"]["primary_stage"] == "train_lora"


def test_run_njr_rejects_mixed_train_lora_stage_plan(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    pipeline = Mock()
    pipeline.client = Mock()
    runner._pipeline = pipeline
    try:
        _record_from_legacy_kwargs(
            job_id="train-mixed",
            config={
                "train_lora": {
                    "enabled": True,
                    "character_name": "Ada",
                    "image_dir": str(tmp_path / "images"),
                    "output_dir": str(tmp_path),
                    "epochs": 10,
                    "learning_rate": 0.0001,
                },
                "pipeline": {
                    "train_lora_enabled": True,
                    "txt2img_enabled": True,
                },
                "txt2img": {
                    "enabled": True,
                    "model": "sdxl",
                    "sampler_name": "Euler",
                    "steps": 20,
                    "cfg_scale": 7.0,
                },
            },
            path_output_dir=str(tmp_path),
            filename_template="{seed}",
            created_ts=0.0,
            prompt_pack_id="character-training:ada",
            positive_prompt="Train LoRA for Ada",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, model="sdxl"),
                StageConfig(stage_type="train_lora", enabled=True),
            ],
        )
    except ValueError as exc:
        assert "incompatible stages" in str(exc)
    else:
        raise AssertionError("Expected train_lora mixed plan to be rejected")

    # Invalid authorized work never reaches the runner.
    assert pipeline.mock_calls == []


def test_pipeline_runner_keeps_character_embedder_lazy(monkeypatch) -> None:
    created: list[object] = []

    class _FakeEmbedder:
        def __init__(self) -> None:
            created.append(object())

    monkeypatch.setattr("src.pipeline.pipeline_runner.CharacterEmbedder", _FakeEmbedder)

    runner = PipelineRunner(Mock(), Mock())

    assert created == []
    assert runner._character_embedder is None


def test_run_njr_applies_per_image_adetailer_refinement_without_leakage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_a = tmp_path / "input_a.png"
    input_b = tmp_path / "input_b.png"
    input_a.write_bytes(b"a")
    input_b.write_bytes(b"b")
    output_a = tmp_path / "output_a.png"
    output_b = tmp_path / "output_b.png"
    record = _record_from_legacy_kwargs(
        job_id="runner-adetailer-refine",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[StageConfig(stage_type="adetailer", enabled=True, extra={})],
        input_image_paths=[str(input_a), str(input_b)],
        start_stage="adetailer",
    )
    record = _with_workload(
        record,
        positive_prompt="profile portrait with detailed face",
        intent_config={
            "adaptive_refinement": {
                "schema": "stablenew.adaptive-refinement.v1",
                "enabled": True,
                "mode": "adetailer",
                "profile_id": "auto_v1",
                "detector_preference": "null",
                "record_decisions": True,
                "algorithm_version": "v1",
            }
        },
    )

    class _ServiceStub:
        def build_bundle(self, *, mode, prompt_intent, image_path, extra_observation=None):
            applied = (
                {
                    "ad_confidence": 0.22,
                    "ad_mask_min_ratio": 0.003,
                    "ad_inpaint_only_masked_padding": 48,
                }
                if str(image_path).endswith("input_a.png")
                else {}
            )
            return {
                "schema": "stablenew.refinement-decision.v1",
                "algorithm_version": "v1",
                "mode": mode,
                "policy_id": "adetailer_micro_face_v1" if applied else None,
                "detector_id": "null",
                "observation": {
                    "prompt_intent": dict(prompt_intent),
                    "subject_assessment": {
                        "detector_id": "null",
                        "scale_band": "micro" if applied else "large",
                    },
                },
                "applied_overrides": applied,
                "prompt_patch": {},
                "notes": [],
            }

        def assess(self, _image_path):
            return {
                "detector_id": "null",
                "algorithm_version": "v1",
                "image_path": None,
                "image_width": None,
                "image_height": None,
                "detections": [],
                "detection_count": 0,
                "primary_detection_index": None,
                "face_area_ratio": None,
                "face_height_ratio": None,
                "face_width_ratio": None,
                "scale_band": "no_face",
                "pose_band": "unknown",
                "notes": ["no_face_detected"],
            }

    captured_configs: list[dict[str, object]] = []

    def _run_adetailer_stage(
        *,
        input_image_path,
        config,
        output_dir,
        image_name,
        prompt=None,
        negative_prompt=None,
        cancel_token=None,
    ):
        captured_configs.append(dict(config))
        output_path = output_a if str(input_image_path).endswith("input_a.png") else output_b
        return {
            "path": str(output_path),
            "adaptive_refinement": dict(config.get("adaptive_refinement") or {}),
        }

    runner._resolve_refinement_policy_service = lambda _pref: (_ServiceStub(), [])  # type: ignore[method-assign]
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_adetailer_stage.side_effect = _run_adetailer_stage
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert pipeline.run_adetailer_stage.call_count == 2
    assert captured_configs[0]["adetailer_confidence"] == 0.22
    assert captured_configs[0]["ad_mask_min_ratio"] == 0.003
    assert captured_configs[0]["adetailer_padding"] == 48
    assert "adetailer_confidence" not in captured_configs[1]
    assert "ad_mask_min_ratio" not in captured_configs[1]
    assert "adetailer_padding" not in captured_configs[1]
    assert len(result.metadata["adaptive_refinement"]["image_decisions"]) == 2
    assert (
        result.metadata["adaptive_refinement"]["image_decisions"][0]["decision_bundle"][
            "applied_overrides"
        ]["ad_confidence"]
        == 0.22
    )


def test_run_njr_applies_full_mode_upscale_refinement_without_leakage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_a = tmp_path / "input_a.png"
    input_b = tmp_path / "input_b.png"
    input_a.write_bytes(b"a")
    input_b.write_bytes(b"b")
    output_a = tmp_path / "upscaled_a.png"
    output_b = tmp_path / "upscaled_b.png"
    record = _record_from_legacy_kwargs(
        job_id="runner-upscale-refine",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[
            StageConfig(stage_type="upscale", enabled=True, extra={"upscale_mode": "img2img"})
        ],
        input_image_paths=[str(input_a), str(input_b)],
        start_stage="upscale",
    )
    record = _with_workload(
        record,
        positive_prompt="portrait woman, soft face",
        negative_prompt="blurry",
        intent_config={
            "adaptive_refinement": {
                "schema": "stablenew.adaptive-refinement.v1",
                "enabled": True,
                "mode": "full",
                "profile_id": "auto_v1",
                "detector_preference": "null",
                "record_decisions": True,
                "algorithm_version": "v1",
            }
        },
    )

    class _ServiceStub:
        def build_bundle(self, *, mode, prompt_intent, image_path, extra_observation=None):
            is_first = str(image_path).endswith("input_a.png")
            return {
                "schema": "stablenew.refinement-decision.v1",
                "algorithm_version": "v1",
                "mode": mode,
                "policy_id": "full_upscale_detail_v1" if is_first else None,
                "detector_id": "null",
                "observation": {
                    "prompt_intent": dict(prompt_intent),
                    "subject_assessment": {
                        "detector_id": "null",
                        "scale_band": "small" if is_first else "large",
                    },
                },
                "applied_overrides": (
                    {"upscale_steps": 18, "upscale_denoising_strength": 0.18} if is_first else {}
                ),
                "prompt_patch": (
                    {
                        "add_positive": ["clear irises"],
                        "remove_positive": ["soft face"],
                        "add_negative": ["blurred eyes"],
                    }
                    if is_first
                    else {}
                ),
                "notes": [],
            }

        def assess(self, _image_path):
            return {
                "detector_id": "null",
                "algorithm_version": "v1",
                "image_path": None,
                "image_width": None,
                "image_height": None,
                "detections": [],
                "detection_count": 0,
                "primary_detection_index": None,
                "face_area_ratio": None,
                "face_height_ratio": None,
                "face_width_ratio": None,
                "scale_band": "no_face",
                "pose_band": "unknown",
                "notes": ["no_face_detected"],
            }

    captured_configs: list[dict[str, object]] = []

    def _run_upscale_stage(*, input_image_path, config, output_dir, image_name, cancel_token=None):
        captured_configs.append(dict(config))
        output_path = output_a if str(input_image_path).endswith("input_a.png") else output_b
        return {
            "path": str(output_path),
            "adaptive_refinement": dict(config.get("adaptive_refinement") or {}),
        }

    runner._resolve_refinement_policy_service = lambda _pref: (_ServiceStub(), [])  # type: ignore[method-assign]
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_upscale_stage.side_effect = _run_upscale_stage
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert pipeline.run_upscale_stage.call_count == 2
    assert captured_configs[0]["steps"] == 18
    assert captured_configs[0]["denoising_strength"] == 0.18
    assert captured_configs[0]["prompt"] == "portrait woman, soft face"
    assert captured_configs[0]["negative_prompt"] == "blurry"
    assert captured_configs[0]["adaptive_refinement"]["decision_bundle"]["prompt_patch"][
        "add_positive"
    ] == ["clear irises"]
    assert captured_configs[1]["steps"] is None
    assert captured_configs[1]["denoising_strength"] is None
    assert len(result.metadata["adaptive_refinement"]["image_decisions"]) == 2
    assert result.metadata["adaptive_refinement"]["image_decisions"][0]["stage_name"] == "upscale"
    assert (
        result.metadata["adaptive_refinement"]["image_decisions"][0]["decision_bundle"][
            "applied_overrides"
        ]["upscale_steps"]
        == 18
    )


def test_pipeline_run_result_to_dict_and_back() -> None:
    result = PipelineRunResult(
        run_id="roundtrip-001",
        success=True,
        error=None,
        variants=[{"variant": "a"}],
        learning_records=[],
        metadata={"note": "test"},
        stage_plan=None,
        stage_events=[{"stage": "txt2img"}],
    )
    data = result.to_dict()
    assert data["run_id"] == "roundtrip-001"
    assert data["metadata"]["note"] == "test"
    restored = PipelineRunResult.from_dict(data)
    assert restored.run_id == result.run_id
    assert restored.success == result.success
    assert restored.metadata == result.metadata


def test_normalize_run_result_accepts_dicts_and_defaults() -> None:
    canonical = normalize_run_result(
        {"run_id": "from-dict", "success": True}, default_run_id="fallback"
    )
    assert canonical["run_id"] == "from-dict"
    assert canonical["success"] is True
    fallback = normalize_run_result("unexpected", default_run_id="fallback")
    assert fallback["run_id"] == "fallback"
    assert fallback["success"] is False
    assert fallback["error"] == "unexpected"


def test_normalize_run_result_preserves_missing_success_as_unknown() -> None:
    canonical = normalize_run_result({"run_id": "legacy-dict"}, default_run_id="fallback")

    assert canonical["run_id"] == "legacy-dict"
    assert canonical["success"] is None
    assert canonical["error"] is None


def test_run_njr_refuses_enabled_animatediff_stage_before_any_client_call(tmp_path: Path) -> None:
    """AnimateDiff execution is retired: run_njr fails at entry, before metrics, cleanup or any client call."""

    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")
    record = _record_from_legacy_kwargs(
        job_id="runner-animatediff",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[StageConfig(stage_type="animatediff", enabled=True, extra={"enabled": True})],
        input_image_paths=[str(input_path)],
        start_stage="animatediff",
    )
    pipeline = Mock()
    runner._pipeline = pipeline

    with pytest.raises(AnimateDiffRetiredError, match="AnimateDiff execution is retired") as caught:
        runner.run_njr(record, cancel_token=None)

    # Nothing was touched: no executor call, no client call (cleanup, probe or request), no output directory.
    assert pipeline.mock_calls == []
    assert pipeline.client.mock_calls == []
    assert not (tmp_path / "runs").exists()
    envelope = get_attached_envelope(caught.value)
    assert envelope is not None and envelope.error_type == "AnimateDiffRetiredError"
    assert envelope.job_id == "runner-animatediff"


def test_run_njr_dispatches_svd_native_stage(tmp_path: Path) -> None:
    # Hermetic runtime transition: no managed runtime and no live endpoint, so a developer's
    # real local A1111/Comfy cannot influence dispatch (the default coordinator probes localhost).
    free_transition = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: None,
        comfy_manager_getter=lambda: None,
        svd_service_factory=lambda: Mock(),
        webui_endpoint_present=lambda: False,
        comfy_endpoint_present=lambda: False,
    )
    video_backends = VideoBackendRegistry()
    video_backends.register(SVDNativeVideoBackend(transition=free_transition))
    runner = PipelineRunner(
        Mock(),
        Mock(),
        runs_base_dir=str(tmp_path / "runs"),
        video_backend_registry=video_backends,
    )
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")
    output_video = tmp_path / "svd.mp4"
    manifest = tmp_path / "svd.json"
    preview = tmp_path / "preview.png"
    record = _record_from_legacy_kwargs(
        job_id="runner-svd-native",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[StageConfig(stage_type="svd_native", enabled=True, extra={})],
        input_image_paths=[str(input_path)],
        start_stage="svd_native",
    )
    record = replace(
        record,
        source=replace(
            record.source,
            parent_job_id="parent-job-1",
            parent_artifact_id="parent-artifact-1",
        ),
    )
    pipeline = Mock()
    pipeline.run_svd_native_stage.return_value = {
        "path": str(output_video),
        "video_path": str(output_video),
        "gif_path": None,
        "frame_paths": [],
        "manifest_path": str(manifest),
        "thumbnail_path": str(preview),
        "frame_count": 25,
        "artifact": {
            "schema": "stablenew.artifact.v2.6",
            "stage": "svd_native",
            "artifact_type": "video",
            "primary_path": str(output_video),
            "output_paths": [str(output_video)],
            "manifest_path": str(manifest),
            "thumbnail_path": str(preview),
            "input_image_path": str(input_path),
        },
    }
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    pipeline.run_svd_native_stage.assert_called_once()
    provenance_context = pipeline.run_svd_native_stage.call_args.kwargs["context_metadata"]
    assert len(provenance_context["current_njr_sha256"]) == 64
    assert provenance_context["source_descriptor"]["parent_job_id"] == "parent-job-1"
    assert provenance_context["source_descriptor"]["parent_artifact_id"] == "parent-artifact-1"
    assert result.success is True
    assert result.metadata["svd_native_artifact"]["count"] == 1
    assert result.metadata["svd_native_artifact"]["primary_path"] == str(output_video)
    assert (
        result.metadata["svd_native_artifact"]["artifacts"][0]["schema"]
        == "stablenew.artifact.v2.6"
    )
    assert result.metadata["video_artifacts"]["svd_native"]["backend_id"] == "svd_native"
    assert result.metadata["video_primary_artifact"]["stage"] == "svd_native"
    assert result.metadata["video_primary_artifact"]["primary_path"] == str(output_video)
    assert result.metadata["video_backend_results"]["svd_native"]["backend_id"] == "svd_native"
    assert result.variants[0]["video_backend_id"] == "svd_native"
    assert not hasattr(record, "thumbnail_path")
    assert not hasattr(record, "output_paths")


def test_run_njr_dispatches_video_workflow_stage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    end_path = tmp_path / "end.png"
    preview_frame = tmp_path / "frame_001.png"
    input_path.write_bytes(b"seed")
    end_path.write_bytes(b"end")
    preview_frame.write_bytes(b"png")
    output_video = tmp_path / "workflow.mp4"
    manifest = tmp_path / "workflow.json"
    output_video.write_bytes(b"mp4")
    manifest.write_text("{}", encoding="utf-8")

    class _WorkflowBackend:
        backend_id = "comfy"
        capabilities = VideoBackendCapabilities(
            backend_id="comfy",
            stage_types=("video_workflow",),
            requires_input_image=True,
            supports_prompt_text=True,
            supports_negative_prompt=True,
            supports_multiple_anchors=True,
        )

        def execute(self, pipeline, request):
            assert request.workflow_id == "synthetic_anchor_video_v1"
            assert request.end_anchor_path == end_path
            return VideoExecutionResult.from_stage_result(
                backend_id="comfy",
                stage_name="video_workflow",
                result={
                    "path": str(output_video),
                    "video_path": str(output_video),
                    "output_paths": [str(output_video)],
                    "manifest_path": str(manifest),
                    "thumbnail_path": str(preview_frame),
                    "frame_paths": [str(preview_frame)],
                    "source_image_path": str(input_path),
                    "workflow_id": request.workflow_id,
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "video_workflow",
                        "artifact_type": "video",
                        "primary_path": str(output_video),
                        "output_paths": [str(output_video)],
                        "manifest_path": str(manifest),
                        "input_image_path": str(input_path),
                    },
                },
                backend_metadata={"workflow_id": request.workflow_id},
                replay_manifest_fragment={"workflow_id": request.workflow_id},
            )

    registry = VideoBackendRegistry()
    registry.register(_WorkflowBackend())
    runner._video_backends = registry
    record = _record_from_legacy_kwargs(
        job_id="runner-video-workflow",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[
            StageConfig(
                stage_type="video_workflow",
                enabled=True,
                extra={
                    "workflow_id": "synthetic_anchor_video_v1",
                    "workflow_version": "1.0.0",
                    "end_anchor_path": str(end_path),
                },
            )
        ],
        input_image_paths=[str(input_path)],
        start_stage="video_workflow",
    )
    record = replace(
        record,
        workload=replace(
            record.workload,
            continuity_link={
                "pack_id": "cont-001",
                "pack_summary": {
                    "pack_id": "cont-001",
                    "display_name": "Hero Pack",
                },
            },
        ),
    )
    pipeline = Mock()
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert result.metadata["video_artifacts"]["video_workflow"]["backend_id"] == "comfy"
    assert result.metadata["video_primary_artifact"]["stage"] == "video_workflow"
    assert result.metadata["video_backend_results"]["video_workflow"]["backend_id"] == "comfy"
    assert result.variants[0]["video_backend_id"] == "comfy"
    assert result.variants[0]["artifact"]["primary_path"] == str(output_video)
    assert result.metadata["replay_descriptor"]["artifact_type"] == "video"
    assert result.metadata["replay_descriptor"]["primary_stage"] == "video_workflow"
    assert result.metadata["replay_descriptor"]["backends"][0]["backend_id"] == "comfy"
    assert (
        result.metadata["replay_descriptor"]["backends"][0]["workflow_id"]
        == "synthetic_anchor_video_v1"
    )
    assert result.metadata["diagnostics_descriptor"]["primary_stage"] == "video_workflow"
    # PR-VIDEO-215: stage-specific key for video_workflow must be stamped
    assert "video_workflow_artifact" in result.metadata
    assert result.metadata["video_workflow_artifact"]["stage"] == "video_workflow"
    assert result.metadata["video_workflow_artifact"]["backend_id"] == "comfy"
    assert result.metadata["video_workflow_artifact"]["primary_path"] == str(output_video)
    assert result.metadata["video_workflow_artifact"]["frame_paths"] == [str(preview_frame)]
    assert result.metadata["video_workflow_artifact"]["source_image_path"] == str(input_path)
    assert result.metadata["continuity"]["pack_id"] == "cont-001"
    assert result.metadata["video_workflow_artifact"]["continuity"]["pack_id"] == "cont-001"
    assert (
        result.metadata["video_backend_results"]["video_workflow"]["continuity"]["pack_id"]
        == "cont-001"
    )


def test_mixed_image_and_video_stage_plan_is_rejected_before_runner(
    tmp_path: Path,
) -> None:
    try:
        _record_from_legacy_kwargs(
            job_id="runner-final-stage-failure",
            config={},
            path_output_dir="output",
            filename_template="{seed}",
            seed=42,
            created_ts=0.0,
            stage_chain=[
                StageConfig(
                    stage_type="txt2img",
                    enabled=True,
                    steps=20,
                    cfg_scale=7.5,
                    sampler_name="Euler a",
                ),
                StageConfig(
                    stage_type="animatediff",
                    enabled=True,
                    extra={"enabled": True},
                ),
            ],
        )
    except ValueError as exc:
        assert "incompatible stages" in str(exc)
    else:
        raise AssertionError("Expected mixed image/video stages to be rejected")


def _runner_with_fake_pipeline() -> tuple[PipelineRunner, Mock]:
    runner = PipelineRunner(Mock(), Mock())
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": "output.png"}
    runner._pipeline = pipeline
    return runner, pipeline


def test_run_njr_stamps_the_repository_fingerprint_as_the_njr_identity() -> None:
    from src.utils.njr_identity import snapshot_envelope, snapshot_fingerprint

    runner, pipeline = _runner_with_fake_pipeline()
    record = _minimal_normalized_record()
    seen: list[object] = []

    def _stage(*_args, **_kwargs):
        seen.append(pipeline._current_njr_sha256)  # the identity the executor stamps into artifacts
        return {"path": "output.png"}

    pipeline.run_txt2img_stage.side_effect = _stage
    runner.run_njr(record, cancel_token=None)
    assert seen == [
        snapshot_fingerprint(snapshot_envelope(record.job_id, record.to_queue_snapshot()))
    ]


def test_run_njr_reports_images_saved_without_provenance_in_the_result_metadata() -> None:
    runner, pipeline = _runner_with_fake_pipeline()

    def _stage(*_args, **_kwargs):
        pipeline._provenance_incomplete.append(
            {"stage": "txt2img", "image": "output.png", "reason": "metadata_build_failed"}
        )
        return {"path": "output.png"}

    pipeline.run_txt2img_stage.side_effect = _stage
    result = runner.run_njr(_minimal_normalized_record(), cancel_token=None)
    assert result.success is True
    assert result.metadata["provenance_incomplete"] == [
        {"stage": "txt2img", "image": "output.png", "reason": "metadata_build_failed"}
    ]


def test_run_njr_has_no_provenance_incomplete_key_when_nothing_was_lost() -> None:
    runner, _pipeline = _runner_with_fake_pipeline()
    result = runner.run_njr(_minimal_normalized_record(), cancel_token=None)
    assert "provenance_incomplete" not in result.metadata


def test_a_failing_run_metadata_write_is_logged_and_does_not_fail_the_job(
    monkeypatch, caplog
) -> None:
    import logging

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("src.pipeline.pipeline_runner.write_run_metadata", _boom)
    runner, _pipeline = _runner_with_fake_pipeline()
    with caplog.at_level(logging.WARNING):
        result = runner.run_njr(_minimal_normalized_record(), cancel_token=None)
    assert result.success is True
    assert "Run metadata could not be written" in caplog.text
    assert "disk full" in caplog.text
