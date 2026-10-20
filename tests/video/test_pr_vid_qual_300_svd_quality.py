"""PR-VID-QUAL-300: SVD conditioning truth, admission freezing and source orientation."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.controller.svd_controller import SVDController
from src.video import svd_service as svd_service_module
from src.video.svd_config import SVDConfig, SVDInferenceConfig, SVDPreprocessConfig
from src.video.svd_preprocess import (
    load_svd_source_image,
    prepare_svd_input,
    probe_svd_source_image,
    read_svd_source_size,
)
from src.video.svd_service import SVDService, balanced_decode_chunk_size

_XT = "stabilityai/stable-video-diffusion-img2vid-xt"
_XT_11 = "stabilityai/stable-video-diffusion-img2vid-xt-1-1"
_BASE = "stabilityai/stable-video-diffusion-img2vid"


# --- decode chunking -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frames", "max_chunk", "expected"),
    [
        (25, 8, 7),  # 7/7/7/4 instead of 8/8/8/1
        (25, 13, 13),  # 13/12
        (25, 25, 25),
        (25, 2, 2),  # legacy configs keep their chunk size
        (14, 4, 4),
        (14, 7, 7),
        (14, 8, 7),
        (14, 50, 14),  # never larger than the clip
        (1, 8, 1),
    ],
)
def test_balanced_decode_chunk_size(frames: int, max_chunk: int, expected: int) -> None:
    assert balanced_decode_chunk_size(frames, max_chunk) == expected


def _run_generate(monkeypatch, tmp_path, pipeline, config: SVDInferenceConfig) -> None:
    prepared_path = tmp_path / "prepared.png"
    Image.new("RGB", (64, 64), "white").save(prepared_path)
    service = SVDService()
    monkeypatch.setattr(service, "is_available", lambda: (True, None))
    monkeypatch.setattr(service, "_get_pipeline", lambda _config: pipeline)
    monkeypatch.setattr(service, "_release_runtime_memory", lambda: None)
    monkeypatch.setattr(
        svd_service_module,
        "importlib",
        SimpleNamespace(
            import_module=lambda name: SimpleNamespace(Generator=lambda device: _Generator())
            if name == "torch"
            else None
        ),
    )
    service.generate_frames(prepared_image_path=prepared_path, config=config)


class _Generator:
    def manual_seed(self, seed: int) -> _Generator:
        self.seed = seed
        return self


def test_generate_frames_passes_fps_conditioning_and_balanced_chunk(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class _DiffusersLikePipeline:
        def __call__(self, image, *, fps=7, decode_chunk_size=None, **kwargs):
            captured.update(kwargs, fps=fps, decode_chunk_size=decode_chunk_size)
            return SimpleNamespace(frames=[[Image.new("RGB", (64, 64), "black")]])

    config = SVDInferenceConfig(num_frames=25, fps=11, decode_chunk_size=8, seed=5)
    _run_generate(monkeypatch, tmp_path, _DiffusersLikePipeline(), config)

    assert captured["fps"] == 11
    assert captured["decode_chunk_size"] == 7
    assert captured["num_frames"] == 25


def test_generate_frames_omits_fps_for_a_pipeline_without_the_parameter(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    class _LegacyPipeline:
        def __call__(self, image, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(frames=[Image.new("RGB", (64, 64), "black")])

    _run_generate(monkeypatch, tmp_path, _LegacyPipeline(), SVDInferenceConfig(seed=1))

    assert "fps" not in captured


# --- admission freezing ----------------------------------------------------------------------


def _controller() -> SVDController:
    return SVDController(
        app_controller=SimpleNamespace(output_dir="output", job_service=Mock()),
        svd_service=Mock(),
    )


def _config(**inference: object) -> SVDConfig:
    return SVDConfig.from_dict({"inference": {"model_id": _XT, **inference}})


@pytest.mark.parametrize("seed", [None, -1])
def test_admission_freezes_a_blank_or_negative_seed(seed) -> None:
    prepared = _controller().prepare_for_admission(_config(seed=seed))
    assert isinstance(prepared.inference.seed, int)
    assert 0 <= prepared.inference.seed < 2**32


def test_admission_keeps_an_explicit_seed_and_unlocked_conditioning() -> None:
    config = _config(seed=1234, motion_bucket_id=90, fps=8)
    prepared = _controller().prepare_for_admission(config)
    assert prepared == config


def test_admission_applies_the_xt_1_1_trained_conditioning() -> None:
    prepared = _controller().prepare_for_admission(
        SVDConfig.from_dict(
            {"inference": {"model_id": _XT_11, "seed": 3, "motion_bucket_id": 48, "fps": 7}}
        )
    )
    assert prepared.inference.motion_bucket_id == 127
    assert prepared.inference.fps == 6
    assert prepared.inference.seed == 3


@pytest.mark.parametrize(("model_id", "frames"), [(_XT, 26), (_BASE, 15)])
def test_admission_refuses_more_frames_than_the_model_was_trained_for(model_id, frames) -> None:
    config = SVDConfig.from_dict({"inference": {"model_id": model_id, "num_frames": frames}})
    with pytest.raises(RuntimeError, match="supports at most"):
        _controller().prepare_for_admission(config)


def test_submit_svd_job_records_the_frozen_seed_in_the_njr(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (64, 64), "white").save(source)
    captured: dict[str, object] = {}
    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(
            submit_njrs=lambda njrs, _policy: captured.setdefault("njrs", list(njrs)) and ["job"]
        ),
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda *_args, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )

    controller.submit_svd_job(source_image_path=source, config=_config(seed=None))

    seed = captured["njrs"][0].config["svd_native"]["inference"]["seed"]
    assert isinstance(seed, int) and seed >= 0


def test_submit_svd_job_refuses_an_illegal_frame_count_before_submission(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (64, 64), "white").save(source)
    submit = Mock()
    controller = SVDController(
        app_controller=SimpleNamespace(
            output_dir=str(tmp_path), job_service=SimpleNamespace(submit_njrs=submit)
        ),
        svd_service=Mock(),
    )
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda *_args, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )
    with pytest.raises(RuntimeError, match="at most 25"):
        controller.submit_svd_job(source_image_path=source, config=_config(num_frames=40))
    submit.assert_not_called()


# --- source orientation and transparency -----------------------------------------------------


def _save_with_orientation(path, size: tuple[int, int], orientation: int) -> None:
    image = Image.new("RGB", size, (200, 30, 30))
    # Mark the left column so a rotation is observable.
    for y in range(size[1]):
        image.putpixel((0, y), (0, 0, 255))
    exif = Image.Exif()
    exif[0x0112] = orientation
    image.save(path, format="JPEG", exif=exif, quality=95)


def test_exif_rotated_source_is_loaded_and_measured_upright(tmp_path) -> None:
    path = tmp_path / "phone.jpg"
    _save_with_orientation(path, (80, 40), orientation=6)  # stored landscape, displayed portrait

    assert read_svd_source_size(path) == (40, 80)
    assert (probe_svd_source_image(path).width, probe_svd_source_image(path).height) == (40, 80)
    with load_svd_source_image(path) as loaded:
        assert loaded.size == (40, 80)


def test_unrotated_source_size_is_unchanged(tmp_path) -> None:
    path = tmp_path / "plain.png"
    Image.new("RGB", (96, 32), "white").save(path)
    assert read_svd_source_size(path) == (96, 32)


def test_transparent_source_is_composited_over_the_pad_colour(tmp_path) -> None:
    path = tmp_path / "cutout.png"
    image = Image.new("RGBA", (16, 16), (255, 0, 0, 0))  # fully transparent red
    image.putpixel((8, 8), (0, 255, 0, 255))
    image.save(path)

    config = replace(SVDPreprocessConfig(), target_width=16, target_height=16)
    config = replace(config, pad_color=(10, 20, 30))
    result = prepare_svd_input(source_path=path, config=config, temp_dir=tmp_path / "prep")

    with Image.open(result.prepared_path) as prepared:
        assert prepared.mode == "RGB"
        assert prepared.getpixel((0, 0)) == (10, 20, 30)
        assert prepared.getpixel((8, 8)) == (0, 255, 0)
