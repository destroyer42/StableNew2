from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from src.video.assembly_models import AssemblyRequest
from src.video.assembly_service import AssemblyService
from src.video.interpolation_contracts import InterpolationRequest, InterpolationResult


def test_assembly_service_exports_manual_frames(tmp_path: Path) -> None:
    frame0 = tmp_path / "frame0.png"
    frame1 = tmp_path / "frame1.png"
    frame0.write_bytes(b"png")
    frame1.write_bytes(b"png")
    calls: dict[str, object] = {}

    def _fake_image_exporter(**kwargs):
        calls.update(kwargs)
        output_path = Path(kwargs["output_path"])
        output_path.write_bytes(b"mp4")
        return output_path

    write_container_metadata = Mock(return_value=True)
    service = AssemblyService(image_exporter=_fake_image_exporter)
    service._write_video_container_metadata = write_container_metadata  # type: ignore[attr-defined]
    source = service.build_source_from_paths([frame0, frame1])

    result = service.assemble(
        AssemblyRequest(
            source=source,
            output_dir=tmp_path / "out",
            clip_name="manual_clip",
            fps=24,
        )
    )

    assert result.success is True
    assert result.stitched_output is None
    assert result.export_output is not None
    assert result.export_output.primary_path == str(tmp_path / "out" / "manual_clip.mp4")
    assert Path(result.manifest_path).exists()
    assert calls["image_paths"] == [frame0, frame1]
    write_container_metadata.assert_called_once()


def test_assembly_service_stitches_sequence_segments(tmp_path: Path) -> None:
    seg0 = tmp_path / "seg0.mp4"
    seg1 = tmp_path / "seg1.mp4"
    seg0.write_bytes(b"mp4-0")
    seg1.write_bytes(b"mp4-1")

    def _fake_stitcher(*, segment_paths, output_path):
        stitched = Path(output_path)
        stitched.write_bytes(b"stitched")
        assert segment_paths == [seg0, seg1]
        return stitched

    write_container_metadata = Mock(return_value=True)
    service = AssemblyService(segment_stitcher=_fake_stitcher)
    service._write_video_container_metadata = write_container_metadata  # type: ignore[attr-defined]
    source = service.build_source_from_bundle(
        {
            "sequence_id": "seq-217",
            "job_id": "job-217",
            "segment_provenance": [
                {"segment_index": 0, "segment_id": "seg0", "primary_output_path": str(seg0)},
                {"segment_index": 1, "segment_id": "seg1", "primary_output_path": str(seg1)},
            ],
        }
    )

    result = service.assemble(
        AssemblyRequest(
            source=source,
            output_dir=tmp_path / "out",
            clip_name="stitched_seq",
            fps=24,
        )
    )

    assert result.success is True
    assert result.stitched_output is not None
    assert result.stitched_output.source_segment_paths == [str(seg0), str(seg1)]
    assert result.export_output.primary_path == str(tmp_path / "out" / "stitched_seq.mp4")
    assert Path(result.manifest_path).exists()
    write_container_metadata.assert_called_once()


def test_assembly_service_invokes_interpolation_provider(tmp_path: Path) -> None:
    seg0 = tmp_path / "seg0.mp4"
    seg1 = tmp_path / "seg1.mp4"
    seg0.write_bytes(b"mp4-0")
    seg1.write_bytes(b"mp4-1")
    interpolated = tmp_path / "out" / "stitched_seq_interpolated.mp4"

    def _fake_stitcher(*, segment_paths, output_path):
        stitched = Path(output_path)
        stitched.parent.mkdir(parents=True, exist_ok=True)
        stitched.write_bytes(b"stitched")
        return stitched

    class _FakeInterpolationProvider:
        provider_id = "fake_interp"

        def interpolate(self, request: InterpolationRequest) -> InterpolationResult:
            interpolated.parent.mkdir(parents=True, exist_ok=True)
            interpolated.write_bytes(b"interpolated")
            return InterpolationResult(
                provider_id=self.provider_id,
                applied=True,
                input_paths=list(request.input_paths),
                output_paths=[str(interpolated)],
                primary_path=str(interpolated),
                metadata={"factor": request.factor},
            )

    service = AssemblyService(
        segment_stitcher=_fake_stitcher,
        interpolation_provider=_FakeInterpolationProvider(),
    )
    source = service.build_source_from_bundle(
        {
            "sequence_id": "seq-217",
            "job_id": "job-217",
            "segment_provenance": [
                {"segment_index": 0, "segment_id": "seg0", "primary_output_path": str(seg0)},
                {"segment_index": 1, "segment_id": "seg1", "primary_output_path": str(seg1)},
            ],
        }
    )

    result = service.assemble(
        AssemblyRequest(
            source=source,
            output_dir=tmp_path / "out",
            clip_name="stitched_seq",
            fps=24,
            interpolation_enabled=True,
            interpolation_factor=2,
        )
    )

    assert result.success is True
    assert result.interpolated_output is not None
    assert result.interpolated_output.applied is True
    assert result.interpolated_output.provider_id == "fake_interp"
    assert result.export_output.primary_path == str(interpolated)
