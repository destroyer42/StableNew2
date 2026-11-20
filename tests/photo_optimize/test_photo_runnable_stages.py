"""A managed photo is imported with a runnable stage, and a photo without one is refused by name with the fix.

Operator report 2026-11-19: photos imported while the Pipeline was a txt2img run (img2img, ADetailer and Upscale
all off) carried no photo stage at all, so every Optimize refused them with an opaque asset-id error.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.photo_optimize.store import PhotoOptimizeStore
from src.photo_optimize.submission import pipeline_defaults, prepare_photo_plan
from tests.photo_optimize.test_photo_220 import image

ALL_OFF = {"img2img": False, "adetailer": False, "upscale": False}


def _txt2img_pipeline() -> dict:
    return {
        "txt2img": {"enabled": True, "model": "sdxl-base.safetensors", "steps": 30},
        "img2img": {"enabled": False, "denoising_strength": 0.3},
        "adetailer": {"enabled": False},
        "upscale": {"enabled": False, "upscaler": "R-ESRGAN 4x+"},
    }


def _plan_input(asset) -> dict:
    return {
        "asset_id": asset.asset_id,
        "source_filename": asset.source_filename,
        "managed_original_path": asset.managed_original_path,
        "input_image_path": str(asset.current_input_path),
        "baseline": asset.baseline.to_dict(),
        "archived": asset.archived,
    }


def _store_stub(tmp_path):
    counter = iter(range(100))
    return SimpleNamespace(
        create_staging_run_dir=lambda _kind: tmp_path / "runs" / f"run-{next(counter)}"
    )


def test_import_with_every_photo_stage_off_in_the_pipeline_defaults_to_img2img(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")

    asset = store.import_photo(
        image(tmp_path / "a.png"), baseline_defaults={"stage_defaults": dict(ALL_OFF)}
    )

    assert asset.baseline.stage_defaults == {"img2img": True, "adetailer": False, "upscale": False}
    assert store.get_asset(asset.asset_id).baseline.stage_defaults["img2img"] is True


def test_import_keeps_the_pipeline_stages_when_one_of_them_is_on(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    chosen = {"img2img": False, "adetailer": True, "upscale": False}

    asset = store.import_photo(
        image(tmp_path / "a.png"), baseline_defaults={"stage_defaults": dict(chosen)}
    )

    assert asset.baseline.stage_defaults == chosen


def test_a_photo_imported_from_a_txt2img_pipeline_queues_img2img(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    defaults = pipeline_defaults(_txt2img_pipeline())
    assert not any(defaults["stage_defaults"].values())  # the live Pipeline enables no photo stage
    asset = store.import_photo(image(tmp_path / "a.png"), baseline_defaults=defaults)

    plan = prepare_photo_plan(
        assets=[_plan_input(asset)],
        stages=[],
        fallback_config=_txt2img_pipeline(),
        store=_store_stub(tmp_path),
        batch_size=1,
    )

    assert [stage.stage_type for job in plan.jobs for stage in job.stage_chain] == ["img2img"]


def test_photos_with_no_stage_are_all_named_with_the_fix(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    assets = []
    for name in ("first.png", "second.png", "ready.png"):
        asset = store.import_photo(image(tmp_path / name))
        asset.baseline.stage_defaults = dict(ALL_OFF) if name != "ready.png" else {"img2img": True}
        store.save_asset(asset)
        assets.append(store.get_asset(asset.asset_id))

    with pytest.raises(ValueError) as refused:
        prepare_photo_plan(
            assets=[_plan_input(asset) for asset in assets],
            stages=[],
            fallback_config=_txt2img_pipeline(),
            store=_store_stub(tmp_path),
            batch_size=1,
        )

    message = str(refused.value)
    assert "first.png" in message and "second.png" in message
    assert "ready.png" not in message
    assert "img2img" in message and "Batch Edit" in message


def test_an_unknown_stage_name_is_still_refused(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    asset = store.import_photo(image(tmp_path / "a.png"))
    row = _plan_input(asset)
    row["stages"] = ["img2img", "txt2img"]

    with pytest.raises(ValueError, match="unsupported stage"):
        prepare_photo_plan(
            assets=[row],
            stages=[],
            fallback_config=_txt2img_pipeline(),
            store=_store_stub(tmp_path),
            batch_size=1,
        )
