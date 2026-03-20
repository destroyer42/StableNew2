from __future__ import annotations

from src.video.interpolation_contracts import (
    InterpolationRequest,
    InterpolationResult,
    NoOpInterpolationProvider,
)


def test_interpolation_request_validate() -> None:
    request = InterpolationRequest(input_paths=[], output_dir="", clip_name="clip", factor=0)
    errors = request.validate()
    assert any("input_paths" in error for error in errors)
    assert any("output_dir" in error for error in errors)
    assert any("factor" in error for error in errors)


def test_interpolation_result_round_trip() -> None:
    result = InterpolationResult(
        provider_id="test",
        applied=True,
        input_paths=["C:/tmp/in.mp4"],
        output_paths=["C:/tmp/out.mp4"],
        primary_path="C:/tmp/out.mp4",
        manifest_path="C:/tmp/out.json",
        metadata={"factor": 2},
    )

    restored = InterpolationResult.from_dict(result.to_dict())
    assert restored.provider_id == "test"
    assert restored.applied is True
    assert restored.primary_path == "C:/tmp/out.mp4"
    assert restored.metadata["factor"] == 2


def test_noop_interpolation_provider_preserves_inputs() -> None:
    provider = NoOpInterpolationProvider()
    result = provider.interpolate(
        InterpolationRequest(
            input_paths=["C:/tmp/clip.mp4"],
            output_dir="C:/tmp",
            clip_name="clip",
        )
    )

    assert result.provider_id == "noop"
    assert result.applied is False
    assert result.output_paths == ["C:/tmp/clip.mp4"]
    assert result.primary_path == "C:/tmp/clip.mp4"
