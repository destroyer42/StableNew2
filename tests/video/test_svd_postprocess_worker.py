from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("cv2")
pytest.importorskip("torch")

from src.video import svd_postprocess_worker as worker


def test_install_torchvision_compat_shims_registers_functional_tensor(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.modules.pop("torchvision.transforms.functional_tensor", None)

    torchvision_module = types.ModuleType("torchvision")
    transforms_module = types.ModuleType("torchvision.transforms")
    functional_module = types.ModuleType("torchvision.transforms.functional")
    functional_module.normalize = object()
    functional_module.fake_op = lambda value: value

    monkeypatch.setitem(sys.modules, "torchvision", torchvision_module)
    monkeypatch.setitem(sys.modules, "torchvision.transforms", transforms_module)
    monkeypatch.setitem(sys.modules, "torchvision.transforms.functional", functional_module)

    worker._install_torchvision_compat_shims()

    shim = sys.modules.get("torchvision.transforms.functional_tensor")
    assert shim is not None
    assert getattr(shim, "fake_op") is functional_module.fake_op


def test_run_face_restore_uses_gfpgan_runtime(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    Image.new("RGB", (16, 16), "white").save(input_dir / "frame_001.png")

    calls: list[tuple[str, float]] = []

    monkeypatch.setattr(worker, "_build_gfpgan", lambda payload: "gfpgan-runtime")

    def _fake_apply(image, *, restorer, fidelity_weight: float):
        calls.append((restorer, fidelity_weight))
        return image.copy()

    monkeypatch.setattr(worker, "_apply_gfpgan", _fake_apply)

    worker._run_face_restore(
        input_dir,
        output_dir,
        {
            "method": "GFPGAN",
            "fidelity_weight": 0.55,
        },
    )

    assert calls == [("gfpgan-runtime", 0.55)]
    assert (output_dir / "frame_001.png").exists()


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
