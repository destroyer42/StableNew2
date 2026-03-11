from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from src.controller.app_controller import AppController
from src.photo_optimize.store import PhotoOptimizeStore
from src.queue.job_model import JobStatus


def _write_image(path: Path, color: tuple[int, int, int] = (30, 60, 90)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)


def _build_controller() -> AppController:
    with patch("src.controller.app_controller.AppController.__init__", return_value=None):
        controller = AppController.__new__(AppController)
    controller.job_service = Mock()
    controller._append_log = Mock()
    controller._api_client = Mock()
    controller.cancel_token = None
    controller.main_window = None
    controller._ui_dispatch = lambda callback: callback()
    controller._build_reprocess_config = Mock(
        return_value={
            "txt2img": {"model": "baseModel", "vae": "baseVae"},
            "img2img": {"denoising_strength": 0.2},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
        }
    )
    return controller


def test_build_photo_optimize_defaults_uses_current_pipeline_config() -> None:
    controller = _build_controller()

    defaults = controller.build_photo_optimize_defaults()

    assert defaults["model"] == "baseModel"
    assert defaults["vae"] == "baseVae"
    assert defaults["stage_defaults"]["img2img"] is True
    assert defaults["config"]["img2img"]["denoising_strength"] == 0.2


def test_interrogate_photo_path_uses_api_client(tmp_path: Path) -> None:
    controller = _build_controller()
    source = tmp_path / "source" / "portrait.png"
    _write_image(source)
    controller._api_client.interrogate.return_value = "portrait, clean face"

    caption = controller.interrogate_photo_path(source)

    assert caption == "portrait, clean face"
    controller._api_client.interrogate.assert_called_once()
    assert controller._append_log.called


def test_on_optimize_photo_assets_groups_by_compatible_baseline(tmp_path: Path) -> None:
    controller = _build_controller()
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.png"
    image_c = tmp_path / "c.png"
    _write_image(image_a)
    _write_image(image_b)
    _write_image(image_c)

    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    assets = [
        {
            "asset_id": "asset_a",
            "input_image_path": str(image_a),
            "baseline": {"prompt": "portrait", "negative_prompt": "", "model": "modelA", "config": {}},
        },
        {
            "asset_id": "asset_b",
            "input_image_path": str(image_b),
            "baseline": {"prompt": "portrait", "negative_prompt": "", "model": "modelA", "config": {}},
        },
        {
            "asset_id": "asset_c",
            "input_image_path": str(image_c),
            "baseline": {"prompt": "portrait", "negative_prompt": "", "model": "modelB", "config": {}},
        },
    ]

    with patch("src.controller.app_controller.get_photo_optimize_store", return_value=store):
        submitted = controller.on_optimize_photo_assets(
            assets=assets,
            stages=["img2img"],
            prompt_delta="straight teeth",
            negative_prompt_delta="extra fingers",
            prompt_mode="append",
            negative_prompt_mode="append",
            batch_size=2,
        )

    assert submitted == 2
    jobs = [call.args[0] for call in controller.job_service.submit_queued.call_args_list]
    batch_sizes = sorted(len(job._normalized_record.input_image_paths) for job in jobs)
    assert batch_sizes == [1, 2]
    for job in jobs:
        photo_meta = job._normalized_record.extra_metadata["photo_optimize"]
        assert photo_meta["source"] == "photo_optimize_tab"


def test_photo_optimize_completion_records_asset_history_and_refreshes_ui(tmp_path: Path) -> None:
    controller = _build_controller()
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    source = tmp_path / "source" / "portrait.png"
    _write_image(source)
    asset = store.import_photo(source, baseline_defaults={"prompt": "portrait", "negative_prompt": "blurry"})

    staging = store.create_staging_run_dir("photo_optimize")
    output = staging / "img2img" / "portrait_fix.png"
    _write_image(output, (0, 0, 0))
    output.with_suffix(".json").write_text('{"ok": true}', encoding="utf-8")

    refreshed: list[list[str]] = []
    controller.main_window = SimpleNamespace(
        photo_optimize_tab=SimpleNamespace(on_assets_updated=lambda asset_ids: refreshed.append(list(asset_ids)))
    )

    job = SimpleNamespace(
        job_id="job_123",
        status=JobStatus.COMPLETED,
        result={"variants": [{"path": str(output)}]},
        _normalized_record=SimpleNamespace(
            output_paths=[],
            input_image_paths=[asset.managed_original_path],
            extra_metadata={
                "photo_optimize": {
                    "run_id": staging.name,
                    "prompt_mode": "append",
                    "prompt_delta": "straight teeth",
                    "negative_prompt_mode": "append",
                    "negative_prompt_delta": "extra fingers",
                    "stages": ["img2img"],
                    "assets": [
                        {
                            "asset_id": asset.asset_id,
                            "input_image_path": asset.managed_original_path,
                            "effective_prompt": "portrait, straight teeth",
                            "effective_negative_prompt": "blurry, extra fingers",
                            "config_snapshot": {"img2img": {"denoising_strength": 0.2}},
                            "stages": ["img2img"],
                        }
                    ],
                }
            },
        ),
    )

    with patch("src.controller.app_controller.get_photo_optimize_store", return_value=store):
        controller._handle_photo_optimize_completion(job, job.result)

    reloaded = store.get_asset(asset.asset_id)
    assert reloaded is not None
    assert len(reloaded.history) == 1
    assert Path(reloaded.history[0].output_paths[0]).exists()
    assert refreshed == [[asset.asset_id]]
