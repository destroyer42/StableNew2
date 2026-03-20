from __future__ import annotations

from pathlib import Path

from src.video.assembly_models import (
    AssembledSequenceInput,
    AssembledVideoResult,
    AssemblyRequest,
    AssemblySegmentSource,
    ExportReadyOutputBundle,
)


def test_assembled_sequence_input_from_sequence_artifact() -> None:
    source = AssembledSequenceInput.from_sequence_artifact(
        {
            "sequence_id": "seq-217",
            "job_id": "job-217",
            "sequence_manifest_path": "C:/tmp/seq.json",
            "all_output_paths": ["C:/tmp/seg0.mp4", "C:/tmp/seg1.mp4"],
            "all_frame_paths": ["C:/tmp/frame0.png"],
            "segment_provenance": [
                {
                    "segment_index": 0,
                    "segment_id": "seg0",
                    "primary_output_path": "C:/tmp/seg0.mp4",
                    "source_image_path": "C:/tmp/start.png",
                },
                {
                    "segment_index": 1,
                    "segment_id": "seg1",
                    "primary_output_path": "C:/tmp/seg1.mp4",
                },
            ],
        }
    )

    assert source.source_kind == "sequence"
    assert source.source_id == "seq-217"
    assert source.job_id == "job-217"
    assert len(source.segment_sources) == 2
    assert source.resolved_segment_output_paths() == [
        "C:/tmp/seg0.mp4",
        "C:/tmp/seg1.mp4",
    ]
    assert source.source_image_path() == "C:/tmp/start.png"


def test_assembled_sequence_input_from_video_artifact_bundle() -> None:
    source = AssembledSequenceInput.from_video_artifact_bundle(
        {
            "stage": "video_workflow",
            "primary_path": "C:/tmp/workflow.mp4",
            "output_paths": ["C:/tmp/workflow.mp4"],
            "frame_paths": ["C:/tmp/frame0.png", "C:/tmp/frame1.png"],
            "manifest_path": "C:/tmp/workflow.json",
        }
    )

    assert source.source_kind == "video_bundle"
    assert source.resolved_segment_output_paths() == ["C:/tmp/workflow.mp4"]
    assert source.resolved_frame_paths() == [
        "C:/tmp/frame0.png",
        "C:/tmp/frame1.png",
    ]


def test_assembly_request_validate() -> None:
    request = AssemblyRequest(
        source=AssembledSequenceInput.from_paths(["C:/tmp/frame0.png"], source_kind="manual_frames"),
        output_dir="",
        fps=0,
        mode="invalid",
        interpolation_factor=0,
    )

    errors = request.validate()
    assert any("output_dir" in error for error in errors)
    assert any("fps" in error for error in errors)
    assert any("mode" in error for error in errors)
    assert any("interpolation_factor" in error for error in errors)


def test_assembled_video_result_to_dict() -> None:
    result = AssembledVideoResult(
        success=True,
        source=AssembledSequenceInput.from_paths(["C:/tmp/frame0.png"], source_kind="manual_frames"),
        export_settings={"fps": 24},
        export_output=ExportReadyOutputBundle(
            primary_path="C:/tmp/final.mp4",
            output_paths=["C:/tmp/final.mp4"],
            manifest_path="C:/tmp/final.json",
            artifact_bundle={"primary_path": "C:/tmp/final.mp4"},
        ),
        manifest_path="C:/tmp/final.json",
        clip_name="assembled",
    )

    data = result.to_dict()
    assert data["success"] is True
    assert data["clip_name"] == "assembled"
    assert data["primary_path"] == "C:/tmp/final.mp4"
    assert data["export_output"]["manifest_path"] == "C:/tmp/final.json"
