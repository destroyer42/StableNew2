"""PR-VID-POST-304: the post-process worker's model choice, temporal state and stage report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.video import svd_postprocess_worker as worker
from src.video.svd_config import DEFAULT_FACE_RESTORE_FIDELITY


@pytest.fixture(autouse=True)
def _no_gpu_memory_calls(monkeypatch):
    """Per-frame memory release asks torch about CUDA; these tests must not touch a driver."""

    monkeypatch.setattr(worker, "_release_worker_memory", lambda: None)


def _frames(tmp_path: Path, count: int = 3) -> tuple[Path, Path]:
    input_dir, output_dir = tmp_path / "input", tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    for index in range(count):
        Image.new("RGB", (8, 8), (index * 30, 0, 0)).save(input_dir / f"frame_{index:03d}.png")
    return input_dir, output_dir


def test_the_runner_selected_weights_take_precedence_over_the_general_model(
    tmp_path: Path, monkeypatch
) -> None:
    general, selected = tmp_path / "x4.pth", tmp_path / "x2.pth"
    general.write_bytes(b"g")
    selected.write_bytes(b"s")
    loaded: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "src.video.restoration.upscaler.RRDBUpscaler",
        lambda path, *, tile: loaded.append((Path(path).name, tile)) or "upscaler",
    )

    result = worker._build_realesrgan(
        {"model_path": str(general), "selected_model_path": str(selected), "tile": 64}
    )

    assert result == "upscaler"
    assert loaded == [("x2.pth", 64)]


def test_the_general_model_is_used_when_no_selection_is_passed(tmp_path: Path, monkeypatch) -> None:
    general = tmp_path / "x4.pth"
    general.write_bytes(b"g")
    loaded: list[str] = []
    monkeypatch.setattr(
        "src.video.restoration.upscaler.RRDBUpscaler",
        lambda path, *, tile: loaded.append(Path(path).name),
    )

    worker._build_realesrgan({"model_path": str(general)})

    assert loaded == ["x4.pth"]


def test_a_selected_weight_that_vanished_fails_instead_of_falling_back(tmp_path: Path) -> None:
    general = tmp_path / "x4.pth"
    general.write_bytes(b"g")

    with pytest.raises(RuntimeError, match="RealESRGAN model file not found"):
        worker._build_realesrgan(
            {"model_path": str(general), "selected_model_path": str(tmp_path / "gone_x2.pth")}
        )


@pytest.mark.parametrize(
    ("native_scale", "scale", "resized"),
    [(2, 2.0, False), (4, 2.0, True), (4, 4.0, False), (2, 4.0, True)],
)
def test_the_upscale_report_says_whether_the_network_scale_matched_the_request(
    tmp_path: Path, monkeypatch, native_scale: int, scale: float, resized: bool
) -> None:
    input_dir, output_dir = _frames(tmp_path)
    monkeypatch.setattr(
        worker, "_build_realesrgan", lambda payload: SimpleNamespace(scale=native_scale)
    )
    monkeypatch.setattr(
        worker, "_apply_realesrgan", lambda image, *, upsampler, scale: image.copy()
    )

    report = worker._run_upscale(
        input_dir, output_dir, {"scale": scale, "selected_model_path": str(tmp_path / "m_x2.pth")}
    )

    assert report == {
        "model": "m_x2.pth",
        "requested_scale": scale,
        "native_scale": native_scale,
        "resized": resized,
        "frames": 3,
    }


def test_temporal_smoothing_is_on_by_default_and_can_be_disabled(
    monkeypatch, tmp_path: Path
) -> None:
    weight = tmp_path / "codeformer.pth"
    weight.write_bytes(b"w")
    built: list[dict] = []

    class _Restorer:
        def __init__(self, **kwargs) -> None:
            built.append(kwargs)
            self.temporal = kwargs["temporal"]

    monkeypatch.setattr("src.video.restoration.codeformer.CodeFormerRestorer", _Restorer)

    worker._build_codeformer({"codeformer_weight_path": str(weight), "facelib_model_root": "x"})
    worker._build_codeformer(
        {
            "codeformer_weight_path": str(weight),
            "facelib_model_root": "x",
            "temporal_smoothing": False,
        }
    )

    assert built[0]["temporal"] is not None
    assert built[1]["temporal"] is None


def test_one_stabilizer_serves_every_frame_of_the_clip_and_is_reported(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir, output_dir = _frames(tmp_path, count=4)
    from src.video.restoration.temporal import TemporalFaceStabilizer

    stabilizer = TemporalFaceStabilizer()
    seen: list[object] = []
    monkeypatch.setattr(
        worker, "_build_codeformer", lambda payload: SimpleNamespace(temporal=stabilizer)
    )
    monkeypatch.setattr(
        worker,
        "_apply_codeformer",
        lambda image, *, restorer, fidelity_weight: seen.append(restorer.temporal) or image.copy(),
    )

    report = worker._run_face_restore(input_dir, output_dir, {"method": "CodeFormer"})

    assert seen == [stabilizer] * 4  # the same state object for every frame, in order
    assert report["frames"] == 4
    assert report["fidelity_weight"] == DEFAULT_FACE_RESTORE_FIDELITY == 0.85
    assert report["temporal"] == stabilizer.report()


def test_the_report_marks_temporal_smoothing_off_when_the_restorer_has_none(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir, output_dir = _frames(tmp_path, count=1)
    monkeypatch.setattr(worker, "_build_codeformer", lambda payload: SimpleNamespace(temporal=None))
    monkeypatch.setattr(
        worker, "_apply_codeformer", lambda image, *, restorer, fidelity_weight: image.copy()
    )

    report = worker._run_face_restore(input_dir, output_dir, {"temporal_smoothing": False})

    assert report["temporal"] == {"enabled": False}


def test_main_writes_the_stage_report_next_to_the_frames(tmp_path: Path, monkeypatch) -> None:
    input_dir, output_dir = _frames(tmp_path, count=2)
    report_path = output_dir / "worker_report.json"
    monkeypatch.setattr(worker, "_build_realesrgan", lambda payload: SimpleNamespace(scale=2))
    monkeypatch.setattr(
        worker, "_apply_realesrgan", lambda image, *, upsampler, scale: image.copy()
    )
    config = {
        "action": "upscale",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "report_path": str(report_path),
        "payload": {"scale": 2.0, "selected_model_path": "RealESRGAN_x2plus.pth"},
    }
    monkeypatch.setattr(sys, "argv", ["worker", "--config-json", json.dumps(config)])

    assert worker.main() == 0

    assert json.loads(report_path.read_text(encoding="utf-8"))["native_scale"] == 2


def test_main_without_a_report_path_writes_no_report(tmp_path: Path, monkeypatch) -> None:
    input_dir, output_dir = _frames(tmp_path, count=1)
    monkeypatch.setattr(worker, "_build_realesrgan", lambda payload: SimpleNamespace(scale=4))
    monkeypatch.setattr(
        worker, "_apply_realesrgan", lambda image, *, upsampler, scale: image.copy()
    )
    config = {
        "action": "upscale",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "payload": {"scale": 2.0, "model_path": "m.pth"},
    }
    monkeypatch.setattr(sys, "argv", ["worker", "--config-json", json.dumps(config)])

    assert worker.main() == 0

    assert sorted(path.suffix for path in output_dir.iterdir()) == [".png"]
