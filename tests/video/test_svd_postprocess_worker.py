from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.video import svd_postprocess_worker as worker


def _frames(tmp_path: Path, count: int = 2) -> tuple[Path, Path]:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    for index in range(count):
        Image.new("RGB", (16, 16), (index * 40, 0, 0)).save(input_dir / f"frame_{index:03d}.png")
    return input_dir, output_dir


def test_codeformer_dispatch_forwards_fidelity_and_writes_every_frame(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir, output_dir = _frames(tmp_path)
    built: list[dict] = []
    applied: list[tuple[object, float]] = []
    released: list[bool] = []

    monkeypatch.setattr(
        worker, "_build_codeformer", lambda payload: built.append(payload) or "runtime"
    )

    def _fake_apply(image, *, restorer, fidelity_weight: float):
        applied.append((restorer, fidelity_weight))
        return image.copy()

    monkeypatch.setattr(worker, "_apply_codeformer", _fake_apply)
    monkeypatch.setattr(worker, "_release_worker_memory", lambda: released.append(True))

    worker._run_face_restore(
        input_dir, output_dir, {"method": "CodeFormer", "fidelity_weight": 0.55}
    )

    assert len(built) == 1  # the model is built once, not per frame
    assert applied == [("runtime", 0.55), ("runtime", 0.55)]
    assert sorted(path.name for path in output_dir.iterdir()) == ["frame_000.png", "frame_001.png"]
    assert len(released) == 2  # memory is released after every frame


def test_default_face_restore_method_is_codeformer(tmp_path: Path, monkeypatch) -> None:
    input_dir, output_dir = _frames(tmp_path, count=1)
    monkeypatch.setattr(worker, "_build_codeformer", lambda payload: "codeformer-runtime")
    monkeypatch.setattr(
        worker, "_apply_codeformer", lambda image, *, restorer, fidelity_weight: image.copy()
    )

    worker._run_face_restore(input_dir, output_dir, {})

    assert (output_dir / "frame_000.png").exists()


def test_gfpgan_stays_a_named_method_but_fails_closed(tmp_path: Path) -> None:
    input_dir, output_dir = _frames(tmp_path, count=1)

    with pytest.raises(RuntimeError, match="GFPGAN' is not available"):
        worker._run_face_restore(input_dir, output_dir, {"method": "GFPGAN"})

    assert list(output_dir.iterdir()) == []


def test_upscale_dispatch_forwards_scale_and_tile(tmp_path: Path, monkeypatch) -> None:
    input_dir, output_dir = _frames(tmp_path)
    payloads: list[dict] = []
    calls: list[float] = []
    monkeypatch.setattr(
        worker, "_build_realesrgan", lambda payload: payloads.append(payload) or "up"
    )

    def _fake_apply(image, *, upsampler, scale: float):
        calls.append(scale)
        return image.resize((image.width * 2, image.height * 2))

    monkeypatch.setattr(worker, "_apply_realesrgan", _fake_apply)

    worker._run_upscale(input_dir, output_dir, {"scale": 3.5, "tile": 128, "model_path": "m"})

    assert payloads == [{"scale": 3.5, "tile": 128, "model_path": "m"}]
    assert calls == [3.5, 3.5]
    assert all(Image.open(path).size == (32, 32) for path in output_dir.iterdir())


def test_missing_weights_fail_before_any_model_library_is_touched(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="CodeFormer weight file not found"):
        worker._build_codeformer({"codeformer_weight_path": str(tmp_path / "nope.pth")})
    with pytest.raises(RuntimeError, match="RealESRGAN model file not found"):
        worker._build_realesrgan({"model_path": str(tmp_path / "nope.pth")})


def test_inference_failure_propagates_instead_of_being_swallowed(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir, output_dir = _frames(tmp_path, count=1)
    monkeypatch.setattr(worker, "_build_realesrgan", lambda payload: "up")

    def _boom(image, *, upsampler, scale):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(worker, "_apply_realesrgan", _boom)

    with pytest.raises(RuntimeError, match="out of memory"):
        worker._run_upscale(input_dir, output_dir, {"scale": 2.0})

    assert list(output_dir.iterdir()) == []


def test_apply_realesrgan_converts_rgb_to_bgr_and_back() -> None:
    pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    seen: dict[str, object] = {}

    class _Upsampler:
        def enhance(self, bgr, *, outscale):
            seen["first_pixel_bgr"] = tuple(int(v) for v in bgr[0, 0])
            seen["outscale"] = outscale
            return np.ascontiguousarray(bgr)

    image = Image.new("RGB", (4, 4), (10, 20, 30))

    result = worker._apply_realesrgan(image, upsampler=_Upsampler(), scale=2.0)

    assert seen == {"first_pixel_bgr": (30, 20, 10), "outscale": 2.0}
    assert result.mode == "RGB" and result.getpixel((0, 0)) == (10, 20, 30)


def test_run_secondary_motion_routes_through_shared_worker(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    Image.new("RGB", (16, 16), "white").save(input_dir / "frame_001.png")

    captured: dict[str, object] = {}

    def _fake_worker(payload):
        captured.update(payload)
        target = output_dir / "frame_001.png"
        Image.new("RGB", (16, 16), "red").save(target)
        return {"status": "applied", "output_paths": [str(target)]}

    monkeypatch.setattr(worker, "run_secondary_motion_worker", _fake_worker)

    result = worker._run_secondary_motion(
        input_dir,
        output_dir,
        {
            "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
            "policy": {"enabled": True, "policy_id": "motion_v1"},
            "seed": 123,
        },
    )

    assert captured["seed"] == 123
    assert result["status"] == "applied"
