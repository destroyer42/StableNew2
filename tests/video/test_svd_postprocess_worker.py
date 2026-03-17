from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("cv2")

from src.video import svd_postprocess_worker as worker


def test_install_torchvision_compat_shims_registers_functional_tensor() -> None:
    sys.modules.pop("torchvision.transforms.functional_tensor", None)

    worker._install_torchvision_compat_shims()

    assert "torchvision.transforms.functional_tensor" in sys.modules


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
