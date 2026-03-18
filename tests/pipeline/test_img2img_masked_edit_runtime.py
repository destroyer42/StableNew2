from __future__ import annotations

from pathlib import Path
from typing import Any

from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger


class _Client:
    options_write_enabled = True

    def get_current_model(self) -> str:
        return "model.safetensors"

    def get_current_vae(self) -> str:
        return "vae.pt"


def _fake_save_image(_data: str, path: Path, metadata_builder=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("image", encoding="utf-8")
    return path


def test_img2img_stage_sends_mask_payload_for_image_edit(tmp_path: Path, monkeypatch) -> None:
    input_image = tmp_path / "input.png"
    mask_image = tmp_path / "mask.png"
    input_image.write_bytes(b"")
    mask_image.write_bytes(b"")

    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_load_image_base64",
        lambda path: "MASK_BASE64" if Path(path) == mask_image else "INPUT_BASE64",
    )

    captured: dict[str, Any] = {}

    def _fake_generate(stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured["stage"] = stage
        captured["payload"] = dict(payload)
        return {
            "images": ["ignored"],
            "info": {"seed": 123, "subseed": 456, "all_seeds": [123], "all_subseeds": [456]},
        }

    monkeypatch.setattr(pipeline, "_generate_images", _fake_generate)
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)

    result = pipeline.run_img2img_stage(
        input_image_path=input_image,
        prompt="fix eyes",
        config={
            "steps": 20,
            "cfg_scale": 7.0,
            "denoising_strength": 0.25,
            "width": 512,
            "height": 512,
            "mask_image_path": str(mask_image),
            "mask_blur": 6,
            "inpaint_full_res": True,
            "inpaint_full_res_padding": 24,
            "inpainting_fill": 2,
            "inpainting_mask_invert": True,
        },
        output_dir=tmp_path,
        image_name="masked_edit",
    )

    assert result is not None
    assert captured["stage"] == "img2img"
    assert captured["payload"]["init_images"] == ["INPUT_BASE64"]
    assert captured["payload"]["mask"] == "MASK_BASE64"
    assert captured["payload"]["mask_blur"] == 6
    assert captured["payload"]["inpaint_full_res"] is True
    assert captured["payload"]["inpaint_full_res_padding"] == 24
    assert captured["payload"]["inpainting_fill"] == 2
    assert captured["payload"]["inpainting_mask_invert"] == 1
    assert result["mask_image_path"] == str(mask_image)
