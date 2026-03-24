from pathlib import Path
from unittest.mock import Mock

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner, PipelineRunResult, normalize_run_result
from src.refinement.subject_scale_policy_service import SubjectScalePolicyService
from src.video.assembly_models import AssembledVideoResult, ExportReadyOutputBundle
from src.video import VideoBackendCapabilities, VideoBackendRegistry, VideoExecutionResult


def _minimal_normalized_record() -> NormalizedJobRecord:
    return NormalizedJobRecord(
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


def test_run_njr_emits_observation_only_adaptive_refinement_metadata() -> None:
    runner = PipelineRunner(Mock(), Mock())
    record = _minimal_normalized_record()
    record.positive_prompt = "full body portrait, profile, woman, detailed face"
    record.negative_prompt = "bad anatomy"
    record.prompt_pack_id = "pack-001"
    record.prompt_pack_name = "Pack 001"
    record.intent_config = {
        "adaptive_refinement": {
            "schema": "stablenew.adaptive-refinement.v1",
            "enabled": True,
            "mode": "observe",
            "profile_id": "auto_v1",
            "detector_preference": "null",
            "record_decisions": True,
            "algorithm_version": "v1",
        }
    }
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
    record.intent_config = {
        "adaptive_refinement": {
            "schema": "stablenew.adaptive-refinement.v1",
            "enabled": False,
            "mode": "observe",
        }
    }
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
    record.positive_prompt = "portrait woman"
    record.intent_config = {
        "adaptive_refinement": {
            "schema": "stablenew.adaptive-refinement.v1",
            "enabled": True,
            "mode": "observe",
            "profile_id": "auto_v1",
            "detector_preference": "opencv",
            "record_decisions": True,
            "algorithm_version": "v1",
        }
    }

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
    assert len(result.metadata["adaptive_refinement"]["decision_bundle"]["observation"]["image_assessments"]) == 2


def test_run_njr_records_detector_fallback_notes(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    output_path = tmp_path / "output.png"
    output_path.write_bytes(b"png")
    record = _minimal_normalized_record()
    record.positive_prompt = "portrait woman"
    record.intent_config = {
        "adaptive_refinement": {
            "schema": "stablenew.adaptive-refinement.v1",
            "enabled": True,
            "mode": "observe",
            "profile_id": "auto_v1",
            "detector_preference": "opencv",
            "record_decisions": True,
            "algorithm_version": "v1",
        }
    }
    runner._resolve_refinement_policy_service = (  # type: ignore[method-assign]
        lambda _pref: (SubjectScalePolicyService(), ["opencv_requested_but_unavailable_fell_back_to_null"])
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


def test_run_njr_applies_per_image_adetailer_refinement_without_leakage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_a = tmp_path / "input_a.png"
    input_b = tmp_path / "input_b.png"
    input_a.write_bytes(b"a")
    input_b.write_bytes(b"b")
    output_a = tmp_path / "output_a.png"
    output_b = tmp_path / "output_b.png"
    record = NormalizedJobRecord(
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
    record.positive_prompt = "profile portrait with detailed face"
    record.intent_config = {
        "adaptive_refinement": {
            "schema": "stablenew.adaptive-refinement.v1",
            "enabled": True,
            "mode": "adetailer",
            "profile_id": "auto_v1",
            "detector_preference": "null",
            "record_decisions": True,
            "algorithm_version": "v1",
        }
    }

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
                    "subject_assessment": {"detector_id": "null", "scale_band": "micro" if applied else "large"},
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

    def _run_adetailer_stage(*, input_image_path, config, output_dir, image_name, prompt=None, negative_prompt=None, cancel_token=None):
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
        result.metadata["adaptive_refinement"]["image_decisions"][0]["decision_bundle"]["applied_overrides"]["ad_confidence"]
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
    record = NormalizedJobRecord(
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
        stage_chain=[StageConfig(stage_type="upscale", enabled=True, extra={"upscale_mode": "img2img"})],
        input_image_paths=[str(input_a), str(input_b)],
        start_stage="upscale",
    )
    record.positive_prompt = "portrait woman, soft face"
    record.negative_prompt = "blurry"
    record.intent_config = {
        "adaptive_refinement": {
            "schema": "stablenew.adaptive-refinement.v1",
            "enabled": True,
            "mode": "full",
            "profile_id": "auto_v1",
            "detector_preference": "null",
            "record_decisions": True,
            "algorithm_version": "v1",
        }
    }

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
                    "subject_assessment": {"detector_id": "null", "scale_band": "small" if is_first else "large"},
                },
                "applied_overrides": (
                    {"upscale_steps": 18, "upscale_denoising_strength": 0.18}
                    if is_first
                    else {}
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
    assert captured_configs[0]["adaptive_refinement"]["decision_bundle"]["prompt_patch"]["add_positive"] == ["clear irises"]
    assert captured_configs[1]["steps"] is None
    assert captured_configs[1]["denoising_strength"] is None
    assert len(result.metadata["adaptive_refinement"]["image_decisions"]) == 2
    assert result.metadata["adaptive_refinement"]["image_decisions"][0]["stage_name"] == "upscale"
    assert (
        result.metadata["adaptive_refinement"]["image_decisions"][0]["decision_bundle"]["applied_overrides"]["upscale_steps"]
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


def test_run_njr_dispatches_animatediff_stage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")
    record = NormalizedJobRecord(
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
    pipeline.run_animatediff_stage.return_value = {
        "video_path": str(tmp_path / "clip.mp4"),
        "output_paths": [str(tmp_path / "clip.mp4")],
        "frame_paths": [str(tmp_path / "frame_000000.png")],
        "frame_count": 1,
        "manifest_path": str(tmp_path / "clip.json"),
        "artifact": {
            "schema": "stablenew.artifact.v2.6",
            "stage": "animatediff",
            "artifact_type": "video",
            "primary_path": str(tmp_path / "clip.mp4"),
            "output_paths": [str(tmp_path / "clip.mp4")],
            "manifest_path": str(tmp_path / "clip.json"),
            "input_image_path": str(input_path),
        },
    }
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    pipeline.run_animatediff_stage.assert_called_once()
    assert result.success is True
    assert result.metadata["animatediff_artifact"]["count"] == 1
    assert result.metadata["animatediff_artifact"]["primary_path"] == str(tmp_path / "clip.mp4")
    assert result.metadata["animatediff_artifact"]["manifest_paths"] == [str(tmp_path / "clip.json")]
    assert result.metadata["animatediff_artifact"]["artifacts"][0]["schema"] == "stablenew.artifact.v2.6"
    assert result.metadata["video_artifacts"]["animatediff"]["backend_id"] == "animatediff"
    assert result.metadata["video_primary_artifact"]["stage"] == "animatediff"
    assert result.metadata["video_primary_artifact"]["primary_path"] == str(tmp_path / "clip.mp4")
    assert result.metadata["video_backend_results"]["animatediff"]["backend_id"] == "animatediff"
    assert result.variants[0]["video_backend_id"] == "animatediff"


def test_run_njr_dispatches_svd_native_stage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")
    output_video = tmp_path / "svd.mp4"
    manifest = tmp_path / "svd.json"
    preview = tmp_path / "preview.png"
    record = NormalizedJobRecord(
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
    assert result.success is True
    assert result.metadata["svd_native_artifact"]["count"] == 1
    assert result.metadata["svd_native_artifact"]["primary_path"] == str(output_video)
    assert result.metadata["svd_native_artifact"]["artifacts"][0]["schema"] == "stablenew.artifact.v2.6"
    assert result.metadata["video_artifacts"]["svd_native"]["backend_id"] == "svd_native"
    assert result.metadata["video_primary_artifact"]["stage"] == "svd_native"
    assert result.metadata["video_primary_artifact"]["primary_path"] == str(output_video)
    assert result.metadata["video_backend_results"]["svd_native"]["backend_id"] == "svd_native"
    assert result.variants[0]["video_backend_id"] == "svd_native"
    assert record.thumbnail_path == str(preview)
    assert record.output_paths == [str(output_video)]


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
            assert request.workflow_id == "ltx_multiframe_anchor_v1"
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
    record = NormalizedJobRecord(
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
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "workflow_version": "1.0.0",
                    "end_anchor_path": str(end_path),
                },
            )
        ],
        input_image_paths=[str(input_path)],
        start_stage="video_workflow",
    )
    record.continuity_link = {
        "pack_id": "cont-001",
        "pack_summary": {
            "pack_id": "cont-001",
            "display_name": "Hero Pack",
        },
    }
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
    assert result.metadata["replay_descriptor"]["backends"][0]["workflow_id"] == "ltx_multiframe_anchor_v1"
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
    assert result.metadata["video_backend_results"]["video_workflow"]["continuity"]["pack_id"] == "cont-001"


def test_run_njr_emits_secondary_motion_policy_for_video_stage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    output_video = tmp_path / "workflow.mp4"
    input_path.write_bytes(b"seed")
    output_video.write_bytes(b"mp4")

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
            policy = request.context_metadata.get("secondary_motion_policy")
            assert isinstance(policy, dict)
            assert policy["enabled"] is True
            assert policy["backend_mode"] == "observe_shared_postprocess_candidate"
            return VideoExecutionResult.from_stage_result(
                backend_id="comfy",
                stage_name="video_workflow",
                result={
                    "path": str(output_video),
                    "video_path": str(output_video),
                    "output_paths": [str(output_video)],
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "video_workflow",
                        "artifact_type": "video",
                        "primary_path": str(output_video),
                        "output_paths": [str(output_video)],
                        "input_image_path": str(input_path),
                    },
                },
                backend_metadata={"workflow_id": request.workflow_id},
            )

    registry = VideoBackendRegistry()
    registry.register(_WorkflowBackend())
    runner._video_backends = registry
    record = NormalizedJobRecord(
        job_id="runner-secondary-motion",
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
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "workflow_version": "1.0.0",
                    "motion_profile": "cinematic",
                },
            )
        ],
        input_image_paths=[str(input_path)],
        start_stage="video_workflow",
    )
    record.positive_prompt = "portrait woman with flowing hair"
    record.negative_prompt = "camera shake"
    record.intent_config = {
        "secondary_motion": {
            "schema": "stablenew.secondary-motion.v1",
            "enabled": True,
            "mode": "observe",
            "intent": "micro_sway",
            "regions": ["hair", "fabric"],
            "allow_prompt_bias": False,
            "allow_native_backend": False,
            "record_decisions": True,
            "algorithm_version": "v1",
        }
    }

    runner._pipeline = Mock()

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert result.metadata["secondary_motion"]["intent"]["mode"] == "observe"
    assert result.metadata["secondary_motion"]["primary_policy"]["enabled"] is True
    assert len(result.metadata["secondary_motion"]["video_stage_policies"]) == 1
    stage_policy = result.metadata["secondary_motion"]["video_stage_policies"][0]
    assert stage_policy["stage_name"] == "video_workflow"
    assert stage_policy["backend_id"] == "comfy"
    assert stage_policy["motion_profile"] == "cinematic"
    assert stage_policy["policy"]["pose_class"] == "steady"


def test_run_njr_injects_apply_mode_secondary_motion_and_collects_summary(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    output_video = tmp_path / "workflow.mp4"
    input_path.write_bytes(b"seed")
    output_video.write_bytes(b"mp4")

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
            assert request.stage_config["secondary_motion"]["enabled"] is True
            assert request.stage_config["secondary_motion"]["intent"]["mode"] == "apply"
            return VideoExecutionResult.from_stage_result(
                backend_id="comfy",
                stage_name="video_workflow",
                result={
                    "path": str(output_video),
                    "video_path": str(output_video),
                    "output_paths": [str(output_video)],
                    "secondary_motion": {
                        "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
                        "policy": {"enabled": True, "policy_id": "workflow_motion_v1"},
                        "apply_result": {
                            "status": "applied",
                            "application_path": "shared_postprocess_engine",
                            "metrics": {"frames_in": 16, "frames_out": 16},
                        },
                    },
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "video_workflow",
                        "artifact_type": "video",
                        "primary_path": str(output_video),
                        "output_paths": [str(output_video)],
                        "input_image_path": str(input_path),
                    },
                },
            )

    registry = VideoBackendRegistry()
    registry.register(_WorkflowBackend())
    runner._video_backends = registry
    record = NormalizedJobRecord(
        job_id="runner-secondary-motion-apply",
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
                extra={"workflow_id": "ltx_multiframe_anchor_v1", "workflow_version": "1.0.0"},
            )
        ],
        input_image_paths=[str(input_path)],
        start_stage="video_workflow",
    )
    record.positive_prompt = "portrait woman with flowing hair"
    record.negative_prompt = "camera shake"
    record.intent_config = {
        "secondary_motion": {
            "schema": "stablenew.secondary-motion.v1",
            "enabled": True,
            "mode": "apply",
            "intent": "micro_sway",
            "regions": ["hair"],
            "allow_native_backend": False,
            "algorithm_version": "v1",
        }
    }
    runner._pipeline = Mock()

    result = runner.run_njr(record, cancel_token=None)

    assert result.metadata["secondary_motion"]["summary"]["status"] == "applied"
    assert result.metadata["secondary_motion"]["summary"]["application_path"] == "shared_postprocess_engine"


def test_run_njr_injects_apply_mode_secondary_motion_under_svd_postprocess(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    output_video = tmp_path / "svd.mp4"
    input_path.write_bytes(b"seed")
    output_video.write_bytes(b"mp4")

    class _SVDBackend:
        backend_id = "svd_native"
        capabilities = VideoBackendCapabilities(
            backend_id="svd_native",
            stage_types=("svd_native",),
            requires_input_image=True,
            supports_prompt_text=False,
            supports_negative_prompt=False,
        )

        def execute(self, pipeline, request):
            assert "secondary_motion" not in request.stage_config
            postprocess = request.stage_config.get("postprocess")
            assert isinstance(postprocess, dict)
            runtime_block = postprocess.get("secondary_motion")
            assert isinstance(runtime_block, dict)
            assert runtime_block["enabled"] is True
            assert runtime_block["intent"]["mode"] == "apply"
            assert runtime_block["policy_id"]
            assert runtime_block["intensity"] > 0.0
            assert runtime_block["cap_pixels"] > 0
            assert runtime_block["regions"] == ["hair"]
            return VideoExecutionResult.from_stage_result(
                backend_id="svd_native",
                stage_name="svd_native",
                result={
                    "path": str(output_video),
                    "video_path": str(output_video),
                    "output_paths": [str(output_video)],
                    "secondary_motion": {
                        "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
                        "policy": {
                            "enabled": True,
                            "policy_id": str(runtime_block["policy_id"]),
                            "backend_mode": str(runtime_block["backend_mode"]),
                        },
                        "apply_result": {
                            "status": "applied",
                            "application_path": "frame_directory_worker",
                            "metrics": {"frames_in": 25, "frames_out": 25},
                        },
                    },
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "svd_native",
                        "artifact_type": "video",
                        "primary_path": str(output_video),
                        "output_paths": [str(output_video)],
                        "input_image_path": str(input_path),
                    },
                },
            )

    registry = VideoBackendRegistry()
    registry.register(_SVDBackend())
    runner._video_backends = registry
    record = NormalizedJobRecord(
        job_id="runner-svd-secondary-motion-apply",
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
                stage_type="svd_native",
                enabled=True,
                extra={"postprocess": {"upscale": {"enabled": False}}},
            )
        ],
        input_image_paths=[str(input_path)],
        start_stage="svd_native",
    )
    record.positive_prompt = "portrait woman with flowing hair"
    record.negative_prompt = "camera shake"
    record.intent_config = {
        "secondary_motion": {
            "schema": "stablenew.secondary-motion.v1",
            "enabled": True,
            "mode": "apply",
            "intent": "micro_sway",
            "regions": ["hair"],
            "allow_native_backend": False,
            "algorithm_version": "v1",
        }
    }
    original_extra = dict(record.stage_chain[0].extra or {})
    runner._pipeline = Mock()

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert record.stage_chain[0].extra == original_extra
    assert result.metadata["secondary_motion"]["summary"]["status"] == "applied"
    assert result.metadata["secondary_motion"]["summary"]["application_path"] == "frame_directory_worker"


def test_run_njr_injects_apply_mode_secondary_motion_into_animatediff_stage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    output_video = tmp_path / "animatediff.mp4"
    input_path.write_bytes(b"seed")
    output_video.write_bytes(b"mp4")

    class _AnimateDiffBackend:
        backend_id = "animatediff"
        capabilities = VideoBackendCapabilities(
            backend_id="animatediff",
            stage_types=("animatediff",),
            requires_input_image=True,
            supports_prompt_text=True,
            supports_negative_prompt=True,
        )

        def execute(self, pipeline, request):
            runtime_block = request.stage_config.get("secondary_motion")
            assert isinstance(runtime_block, dict)
            assert runtime_block["enabled"] is True
            assert runtime_block["intent"]["mode"] == "apply"
            assert runtime_block["policy_id"]
            assert runtime_block["intensity"] > 0.0
            assert runtime_block["cap_pixels"] > 0
            assert runtime_block["regions"] == ["hair"]
            return VideoExecutionResult.from_stage_result(
                backend_id="animatediff",
                stage_name="animatediff",
                result={
                    "path": str(output_video),
                    "video_path": str(output_video),
                    "output_paths": [str(output_video)],
                    "secondary_motion": {
                        "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
                        "policy": {
                            "enabled": True,
                            "policy_id": str(runtime_block["policy_id"]),
                            "backend_mode": str(runtime_block["backend_mode"]),
                        },
                        "apply_result": {
                            "status": "applied",
                            "application_path": "frame_directory_worker",
                            "metrics": {"frames_in": 16, "frames_out": 16},
                        },
                    },
                    "secondary_motion_summary": {
                        "schema": "stablenew.secondary-motion-summary.v1",
                        "enabled": True,
                        "status": "applied",
                        "policy_id": str(runtime_block["policy_id"]),
                        "application_path": "frame_directory_worker",
                        "intent": {"mode": "apply", "intent": "micro_sway"},
                        "backend_mode": str(runtime_block["backend_mode"]),
                        "skip_reason": "",
                        "metrics": {"frames_in": 16, "frames_out": 16},
                    },
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "animatediff",
                        "artifact_type": "video",
                        "primary_path": str(output_video),
                        "output_paths": [str(output_video)],
                        "input_image_path": str(input_path),
                    },
                },
            )

    registry = VideoBackendRegistry()
    registry.register(_AnimateDiffBackend())
    runner._video_backends = registry
    record = NormalizedJobRecord(
        job_id="runner-animatediff-secondary-motion-apply",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[StageConfig(stage_type="animatediff", enabled=True, extra={"enabled": True, "fps": 12})],
        input_image_paths=[str(input_path)],
        start_stage="animatediff",
    )
    record.positive_prompt = "portrait woman with flowing hair"
    record.negative_prompt = "camera shake"
    record.intent_config = {
        "secondary_motion": {
            "schema": "stablenew.secondary-motion.v1",
            "enabled": True,
            "mode": "apply",
            "intent": "micro_sway",
            "regions": ["hair"],
            "allow_native_backend": False,
            "algorithm_version": "v1",
        }
    }
    original_extra = dict(record.stage_chain[0].extra or {})
    runner._pipeline = Mock()

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert record.stage_chain[0].extra == original_extra
    assert result.metadata["secondary_motion"]["summary"]["status"] == "applied"
    assert result.metadata["secondary_motion"]["summary"]["application_path"] == "frame_directory_worker"


def test_run_njr_fails_when_final_enabled_stage_produces_no_outputs(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    record = NormalizedJobRecord(
        job_id="runner-final-stage-failure",
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
            StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a"),
            StageConfig(stage_type="animatediff", enabled=True, extra={"enabled": True}),
        ],
    )
    pipeline = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": str(tmp_path / "image.png"), "all_paths": [str(tmp_path / "image.png")]}
    pipeline.run_animatediff_stage.return_value = None
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is False
    assert result.error == "No images were generated successfully"


def test_run_njr_executes_sequence_plan_for_video_workflow_stage(tmp_path: Path) -> None:
    """PR-VIDEO-216: runner detects multi-segment sequence intent and calls
    _execute_sequence, which iterates segments and stamps sequence_artifact."""
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")

    seg0_video = tmp_path / "seg0.mp4"
    seg1_video = tmp_path / "seg1.mp4"
    seg0_video.write_bytes(b"mp4-0")
    seg1_video.write_bytes(b"mp4-1")

    _call_count = [0]

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
            idx = _call_count[0]
            _call_count[0] += 1
            out = [seg0_video, seg1_video][idx] if idx < 2 else seg1_video
            return VideoExecutionResult.from_stage_result(
                backend_id="comfy",
                stage_name="video_workflow",
                result={
                    "path": str(out),
                    "video_path": str(out),
                    "output_paths": [str(out)],
                    "manifest_path": None,
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "video_workflow",
                        "artifact_type": "video",
                        "primary_path": str(out),
                        "output_paths": [str(out)],
                        "manifest_path": None,
                        "input_image_path": str(input_path),
                    },
                },
                backend_metadata={"workflow_id": "ltx_multiframe_anchor_v1"},
                replay_manifest_fragment={"workflow_id": "ltx_multiframe_anchor_v1"},
            )

    registry = VideoBackendRegistry()
    registry.register(_WorkflowBackend())
    runner._video_backends = registry

    record = NormalizedJobRecord(
        job_id="runner-video-sequence",
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
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "sequence_metadata": {
                        "sequence_id": "seq-test-216",
                        "total_segments": 2,
                        "carry_forward_policy": "last_frame",
                        "segment_length_frames": 25,
                        "overlap_frames": 0,
                    },
                },
            )
        ],
        input_image_paths=[str(input_path)],
        start_stage="video_workflow",
    )
    record.continuity_link = {
        "pack_id": "cont-seq-001",
        "pack_summary": {
            "pack_id": "cont-seq-001",
            "display_name": "Sequence Pack",
        },
    }

    pipeline = Mock()
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    # The backend must have been called once per segment.
    assert _call_count[0] == 2
    # sequence_artifact must be stamped in metadata.
    assert "sequence_artifact" in result.metadata
    seq = result.metadata["sequence_artifact"]
    assert seq["sequence_id"] == "seq-test-216"
    assert seq["completed_segments"] == 2
    assert seq["total_segments"] == 2
    assert seq["is_complete"] is True
    assert len(seq["segment_provenance"]) == 2
    assert len(seq["all_output_paths"]) == 2
    assert seq["continuity_link"]["pack_id"] == "cont-seq-001"
    assert result.metadata["continuity"]["pack_id"] == "cont-seq-001"


def test_run_njr_sequence_assembly_stamps_assembled_video_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")

    seg0_video = tmp_path / "seg0.mp4"
    seg1_video = tmp_path / "seg1.mp4"
    assembled_video = tmp_path / "assembled.mp4"
    assembled_manifest = tmp_path / "assembled_manifest.json"
    seg0_video.write_bytes(b"mp4-0")
    seg1_video.write_bytes(b"mp4-1")
    assembled_video.write_bytes(b"assembled")
    assembled_manifest.write_text("{}", encoding="utf-8")

    call_count = [0]

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
            idx = call_count[0]
            call_count[0] += 1
            out = [seg0_video, seg1_video][idx] if idx < 2 else seg1_video
            return VideoExecutionResult.from_stage_result(
                backend_id="comfy",
                stage_name="video_workflow",
                result={
                    "path": str(out),
                    "video_path": str(out),
                    "output_paths": [str(out)],
                    "manifest_path": None,
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "video_workflow",
                        "artifact_type": "video",
                        "primary_path": str(out),
                        "output_paths": [str(out)],
                        "manifest_path": None,
                        "input_image_path": str(input_path),
                    },
                },
                backend_metadata={"workflow_id": "ltx_multiframe_anchor_v1"},
                replay_manifest_fragment={"workflow_id": "ltx_multiframe_anchor_v1"},
            )

    def _fake_assemble(self, request):
        return AssembledVideoResult(
            success=True,
            source=request.source,
            export_settings=request.export_settings_dict(),
            export_output=ExportReadyOutputBundle(
                primary_path=str(assembled_video),
                output_paths=[str(assembled_video)],
                manifest_path=str(assembled_manifest),
                artifact_bundle={
                    "stage": "assembled_video",
                    "backend_id": "stablenew",
                    "artifact_type": "video",
                    "primary_path": str(assembled_video),
                    "output_paths": [str(assembled_video)],
                    "manifest_path": str(assembled_manifest),
                    "count": 1,
                },
            ),
            manifest_path=str(assembled_manifest),
            clip_name=request.clip_name,
        )

    monkeypatch.setattr("src.video.assembly_service.AssemblyService.assemble", _fake_assemble)

    registry = VideoBackendRegistry()
    registry.register(_WorkflowBackend())
    runner._video_backends = registry

    record = NormalizedJobRecord(
        job_id="runner-video-sequence-assembly",
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
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "sequence_metadata": {
                        "sequence_id": "seq-test-217",
                        "total_segments": 2,
                        "carry_forward_policy": "last_frame",
                        "segment_length_frames": 25,
                        "overlap_frames": 0,
                        "assembly": {
                            "enabled": True,
                            "clip_name": "assembled_sequence",
                        },
                    },
                },
            )
        ],
        input_image_paths=[str(input_path)],
        start_stage="video_workflow",
    )

    pipeline = Mock()
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert call_count[0] == 2
    assert result.metadata["assembled_video_artifact"]["primary_path"] == str(assembled_video)
    assert result.metadata["video_artifacts"]["assembled_video"]["primary_path"] == str(assembled_video)
    assert result.metadata["assembled_video_result"]["success"] is True
    assert result.metadata["sequence_artifact"]["assembled_video"]["clip_name"] == "assembled_sequence"


def test_run_njr_sequence_plan_stamps_plan_origin_metadata(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")

    output_video = tmp_path / "shot.mp4"
    output_video.write_bytes(b"mp4")

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
            return VideoExecutionResult.from_stage_result(
                backend_id="comfy",
                stage_name="video_workflow",
                result={
                    "path": str(output_video),
                    "video_path": str(output_video),
                    "output_paths": [str(output_video)],
                    "manifest_path": None,
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "video_workflow",
                        "artifact_type": "video",
                        "primary_path": str(output_video),
                        "output_paths": [str(output_video)],
                        "manifest_path": None,
                        "input_image_path": str(input_path),
                    },
                },
                backend_metadata={"workflow_id": "ltx_multiframe_anchor_v1"},
                replay_manifest_fragment={"workflow_id": "ltx_multiframe_anchor_v1"},
            )

    registry = VideoBackendRegistry()
    registry.register(_WorkflowBackend())
    runner._video_backends = registry

    record = NormalizedJobRecord(
        job_id="runner-video-plan-origin",
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
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "sequence_metadata": {
                        "sequence_id": "seq-plan-219",
                        "total_segments": 2,
                        "carry_forward_policy": "last_frame",
                        "segment_length_frames": 24,
                        "overlap_frames": 0,
                        "plan_origin": {
                            "plan_id": "story-001",
                            "scene_id": "scene-001",
                            "shot_id": "shot-001",
                        },
                    },
                },
            )
        ],
        input_image_paths=[str(input_path)],
        start_stage="video_workflow",
    )

    runner._pipeline = Mock()

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert result.metadata["plan_origin"]["plan_id"] == "story-001"
    assert result.metadata["sequence_artifact"]["plan_origin"]["shot_id"] == "shot-001"
