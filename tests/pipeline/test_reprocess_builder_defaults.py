from __future__ import annotations

from pathlib import Path

from src.pipeline.reprocess_builder import ReprocessJobBuilder


def test_reprocess_builder_populates_img2img_stage_defaults_from_root_config(tmp_path: Path) -> None:
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"")
    builder = ReprocessJobBuilder()

    njr = builder.build_reprocess_job(
        input_image_paths=[image_path],
        stages=["img2img"],
        config={
            "steps": 24,
            "cfg_scale": 6.5,
            "sampler_name": "DPM++ 2M",
            "img2img": {"denoising_strength": 0.3},
        },
    )

    stage = njr.stage_chain[0]
    assert stage.stage_type == "img2img"
    assert stage.steps == 24
    assert stage.cfg_scale == 6.5
    assert stage.sampler_name == "DPM++ 2M"
    assert stage.denoising_strength == 0.3
