from pathlib import Path
from unittest.mock import Mock

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner, PipelineRunResult, normalize_run_result
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
