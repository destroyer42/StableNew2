from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.photo_optimize.store import PhotoOptimizeStore


def _write_image(path: Path, color: tuple[int, int, int] = (120, 90, 180)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)


def test_import_photo_creates_managed_copy_and_sidecar(tmp_path: Path) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    source = tmp_path / "source" / "face.png"
    _write_image(source)

    asset = store.import_photo(
        source,
        baseline_defaults={
            "model": "realisticVision.safetensors",
            "vae": "vae-ft-mse",
            "config": {"img2img": {"denoising_strength": 0.2}},
        },
    )

    managed_original = Path(asset.managed_original_path)
    assert managed_original.exists()
    assert managed_original.parent.name == "original"
    assert store.sidecar_path(asset.asset_id).exists()
    reloaded = store.get_asset(asset.asset_id)
    assert reloaded is not None
    assert reloaded.baseline.model == "realisticVision.safetensors"
    assert reloaded.baseline.config["img2img"]["denoising_strength"] == 0.2


def test_list_assets_loads_existing_sidecars(tmp_path: Path) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    first = tmp_path / "source" / "a.png"
    second = tmp_path / "source" / "b.png"
    _write_image(first, (255, 0, 0))
    _write_image(second, (0, 255, 0))

    asset_a = store.import_photo(first)
    asset_b = store.import_photo(second)

    assets = store.list_assets()
    ids = {asset.asset_id for asset in assets}
    assert asset_a.asset_id in ids
    assert asset_b.asset_id in ids


def test_record_history_promote_and_revert_baseline(tmp_path: Path) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    source = tmp_path / "source" / "portrait.png"
    _write_image(source)
    asset = store.import_photo(
        source,
        baseline_defaults={
            "prompt": "portrait",
            "negative_prompt": "blurry",
            "model": "modelA",
            "config": {"img2img": {"denoising_strength": 0.25}},
        },
    )

    staging = store.create_staging_run_dir("photo")
    output = staging / "img2img" / "portrait_fixed.png"
    _write_image(output, (20, 20, 20))
    manifest = output.with_suffix(".json")
    manifest.write_text('{"ok": true}', encoding="utf-8")

    updated = store.record_optimize_history(
        asset.asset_id,
        run_id="run_01",
        input_image_path=asset.managed_original_path,
        source_output_paths=[str(output)],
        prompt_mode="append",
        prompt_delta="straighten teeth",
        negative_prompt_mode="append",
        negative_prompt_delta="extra teeth",
        effective_prompt="portrait, straighten teeth",
        effective_negative_prompt="blurry, extra teeth",
        stages=["img2img"],
        config_snapshot={"img2img": {"denoising_strength": 0.33}},
        job_ids=["job_1"],
    )

    assert len(updated.history) == 1
    copied_output = Path(updated.history[0].output_paths[0])
    assert copied_output.exists()
    assert copied_output.parent.name == "outputs"

    promoted = store.promote_latest_output_as_baseline(asset.asset_id)
    assert promoted.baseline.prompt == "portrait, straighten teeth"
    assert promoted.baseline.negative_prompt == "blurry, extra teeth"
    assert Path(promoted.baseline.working_image_path).exists()

    reverted = store.revert_baseline(asset.asset_id)
    assert reverted.baseline.prompt == "portrait"
    assert reverted.baseline.negative_prompt == "blurry"
