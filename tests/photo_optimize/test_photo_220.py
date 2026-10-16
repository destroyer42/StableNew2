from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from src.controller.app_controller import AppController
from src.photo_optimize.migration import migrate_assets
from src.photo_optimize.models import PhotoOptimizeBaseline
from src.photo_optimize.settings import copy_pipeline_settings, normalize_settings, resolve_geometry
from src.photo_optimize.store import PhotoOptimizeStore
from src.state.output_routing import iter_output_run_dirs, rebalance_output_tree
from src.state.workspace_paths import WorkspacePaths


def image(path: Path, size=(640, 960)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size).save(path)
    return path


def test_import_uses_decoded_geometry_over_pipeline_defaults(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    asset = store.import_photo(
        image(tmp_path / "a.png"),
        baseline_defaults={
            "config": {"width": 512, "height": 512, "img2img": {"width": 512, "height": 512}}
        },
    )
    assert asset.baseline.geometry_policy == "auto"
    assert asset.baseline.config["img2img"]["width"] == 640
    assert asset.baseline.config["img2img"]["height"] == 960


def test_bad_import_creates_no_asset(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    with pytest.raises(ValueError, match="decode"):
        store.import_photo(bad)
    assert list((store.root / "assets").iterdir()) == []


def test_archive_clear_and_restore_persist_without_deleting(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    assets = [store.import_photo(image(tmp_path / f"{n}.png")) for n in range(2)]
    store.archive_assets([assets[0].asset_id])
    assert [a.asset_id for a in store.list_assets()] == [assets[1].asset_id]
    store.archive_assets([assets[1].asset_id])
    assert PhotoOptimizeStore(store.root).list_assets() == []
    assert len(store.list_assets(include_archived=True)) == 2
    store.restore_assets([assets[0].asset_id])
    assert len(store.list_assets()) == 1
    assert all(Path(a.managed_original_path).exists() for a in assets)


def test_workspace_is_routed_and_excluded_from_runs(tmp_path):
    paths = WorkspacePaths(tmp_path)
    managed = paths.photo_optimize_root(output_root=tmp_path / "custom" / "Pipeline")
    assert managed == tmp_path / "custom" / "PhotoOptimize" / "workspace"
    run = managed.parent / "photo_run"
    run.mkdir()
    assert iter_output_run_dirs(tmp_path / "custom") == [run]
    rebalance_output_tree(tmp_path / "custom")
    assert managed.exists()


def controller():
    with patch.object(AppController, "__init__", return_value=None):
        result = AppController()
    result._append_log = Mock()
    result._collect_current_stage_configs = Mock(
        return_value={
            "img2img": {"model": "photoModel", "vae": "", "steps": 24, "cfg_scale": 0.0},
        }
    )
    result.job_service = SimpleNamespace(
        submit_njrs=Mock(side_effect=lambda jobs, policy: [j.job_id for j in jobs])
    )
    return result


def test_copy_reads_live_pipeline_even_with_pack_override_off():
    app = controller()
    app.override_pack_config_enabled = False
    app._build_reprocess_config = Mock(return_value={"model": "wrongPack"})
    defaults = app.build_photo_optimize_defaults()
    assert defaults["model"] == "photoModel"
    assert defaults["config"]["img2img"]["cfg_scale"] == 0.0
    app._build_reprocess_config.assert_not_called()


def test_mixed_plans_and_dimensions_freeze_per_photo_and_admit_once(tmp_path):
    app = controller()
    store = PhotoOptimizeStore(tmp_path / "photos")
    assets = [
        store.import_photo(image(tmp_path / f"{n}.png", size))
        for n, size in enumerate([(640, 960), (800, 600)])
    ]
    assets[1].baseline.stage_defaults = {"img2img": False, "adetailer": False, "upscale": True}
    assets[0].baseline.config["img2img"]["denoising_strength"] = 0.0
    payloads = [a.to_dict() for a in assets]
    with patch("src.controller.app_controller.get_photo_optimize_store", return_value=store):
        count = app.on_optimize_photo_assets(assets=payloads, stages=["img2img"], batch_size=8)
    assert count == 2
    app.job_service.submit_njrs.assert_called_once()
    jobs = app.job_service.submit_njrs.call_args.args[0]
    assert [[s.stage_type for s in j.stage_chain] for j in jobs] == [["img2img"], ["upscale"]]
    assert jobs[0].stage_chain[0].denoising_strength == 0.0
    assert jobs[0].config["img2img"]["width"] == 640
    assert jobs[1].config["img2img"]["width"] == 800
    for job in jobs:
        snapshot = job.extra_metadata["photo_optimize"]["assets"][0]["config_snapshot"]
        assert snapshot == job.config
        assert json.loads(json.dumps(job.to_dict()))["workload"]["config"] == job.config


def test_legacy_geometry_retains_explicit_custom_dimensions():
    baseline = PhotoOptimizeBaseline.from_dict(
        {"config": {"img2img": {"width": 768, "height": 1024}}}
    )
    assert baseline.geometry_policy == "custom"


@pytest.mark.parametrize("policy, expected", [("auto", (900, 500)), ("custom", (768, 1024))])
def test_promotion_recomputes_auto_and_preserves_custom(tmp_path, policy, expected):
    store = PhotoOptimizeStore(tmp_path / "photos")
    asset = store.import_photo(image(tmp_path / "input.png"))
    asset.baseline.geometry_policy = policy
    asset.baseline.config["img2img"].update(width=768, height=1024)
    store.save_asset(asset)
    store.record_optimize_history(
        asset.asset_id,
        run_id="run",
        input_image_path=asset.managed_original_path,
        source_output_paths=[str(image(tmp_path / "result.png", (900, 500)))],
        prompt_mode="append",
        prompt_delta="",
        negative_prompt_mode="append",
        negative_prompt_delta="",
        effective_prompt="portrait",
        effective_negative_prompt="",
        stages=["img2img"],
        config_snapshot={**asset.baseline.config, "model": "test-model", "vae": ""},
        job_ids=["job"],
    )
    promoted = store.promote_latest_output_as_baseline(asset.asset_id)
    config = resolve_geometry(promoted.baseline, promoted.current_input_path)
    assert (config["width"], config["height"]) == expected
    reloaded = store.get_asset(asset.asset_id)
    assert reloaded.baseline.geometry_policy == policy
    assert len(reloaded.history) == 1
    assert store.revert_baseline(asset.asset_id).current_input_path == Path(
        asset.managed_original_path
    )


def test_copy_preserves_metadata_prompts_and_each_geometry(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    auto = store.import_photo(image(tmp_path / "auto.png", (400, 800)))
    custom = store.import_photo(image(tmp_path / "custom.png"))
    custom.baseline.geometry_policy = "custom"
    custom.baseline.config["img2img"].update(width=768, height=1024)
    defaults = controller().build_photo_optimize_defaults()
    for asset in (auto, custom):
        asset.baseline.prompt = "keep prompt"
        asset.baseline.negative_prompt = "keep negative"
        copied = copy_pipeline_settings(asset.baseline, defaults)
        assert copied.prompt == "keep prompt"
        assert copied.negative_prompt == "keep negative"
        assert copied.vae == ""
        assert copied.config["img2img"]["cfg_scale"] == 0.0
        expected = (400, 800) if asset is auto else (768, 1024)
        assert (copied.config["width"], copied.config["height"]) == expected
        assert copied.geometry_policy == asset.baseline.geometry_policy


@pytest.mark.parametrize("config", [{}, None])
def test_missing_pipeline_source_is_actionable(config):
    with pytest.raises(ValueError, match="unavailable"):
        copy_pipeline_settings(PhotoOptimizeBaseline(), {"config": config})


def test_alias_precedence_keeps_zero_false_empty_and_unrelated_fields():
    normalized = normalize_settings(
        {
            "img2img": {"denoising_strength": 0.0, "cfg_scale": 0.0, "sampler_name": ""},
            "img2img_denoising_strength": 0.7,
            "upscale": {"face_restore": False},
            "custom_extension": {"keep": 1},
        }
    )
    assert normalized["img2img_denoising_strength"] == 0.0
    assert normalized["img2img_cfg_scale"] == 0.0
    assert normalized["img2img_sampler_name"] == ""
    assert normalized["upscale"]["face_restore"] is False
    assert normalized["custom_extension"] == {"keep": 1}


@pytest.mark.parametrize(
    "bad_case", ["missing", "malformed", "no_stages", "custom_zero", "archived"]
)
def test_whole_request_refuses_invalid_photo_without_partial_admission(tmp_path, bad_case):
    app = controller()
    store = PhotoOptimizeStore(tmp_path / "photos")
    good = store.import_photo(image(tmp_path / "good.png"))
    bad = store.import_photo(image(tmp_path / "bad.png"))
    payload = bad.to_dict()
    if bad_case == "missing":
        payload["baseline"]["working_image_path"] = str(tmp_path / "absent.png")
    elif bad_case == "malformed":
        broken = tmp_path / "broken.png"
        broken.write_text("invalid")
        payload["baseline"]["working_image_path"] = str(broken)
    elif bad_case == "no_stages":
        payload["baseline"]["stage_defaults"] = {}
    elif bad_case == "custom_zero":
        payload["baseline"]["geometry_policy"] = "custom"
        payload["baseline"]["config"]["img2img"]["width"] = 0
    else:
        payload["archived"] = True
    with patch("src.controller.app_controller.get_photo_optimize_store", return_value=store):
        with pytest.raises(ValueError):
            app.on_optimize_photo_assets(
                assets=[good.to_dict(), payload], stages=["img2img"], batch_size=4
            )
    app.job_service.submit_njrs.assert_not_called()


def test_unsupported_profile_refuses_whole_batch(tmp_path):
    from src.image_backends.forge_klein_profile import latest_klein_profile
    from src.image_backends.operation_compatibility import OperationNotSupportedError

    app = controller()
    store = PhotoOptimizeStore(tmp_path / "photos")
    assets = [store.import_photo(image(tmp_path / f"{n}.png")) for n in range(2)]
    assets[1].baseline.model = latest_klein_profile().transformer.filename
    with patch("src.controller.app_controller.get_photo_optimize_store", return_value=store):
        with pytest.raises(OperationNotSupportedError):
            app.on_optimize_photo_assets(assets=[a.to_dict() for a in assets], stages=["img2img"])
    app.job_service.submit_njrs.assert_not_called()


def test_migration_preserves_queued_inputs_and_history_and_is_idempotent(tmp_path):
    from src.pipeline.reprocess_builder import ReprocessJobBuilder

    legacy = PhotoOptimizeStore(tmp_path / "legacy")
    asset = legacy.import_photo(image(tmp_path / "source.png"))
    queued_input = Path(asset.current_input_path)
    legacy.record_optimize_history(
        asset.asset_id, run_id="old_run", input_image_path=str(queued_input),
        source_output_paths=[str(image(tmp_path / "old_result.png"))],
        prompt_mode="append", prompt_delta="", negative_prompt_mode="append",
        negative_prompt_delta="", effective_prompt="old prompt", effective_negative_prompt="",
        stages=["img2img"], config_snapshot={**asset.baseline.config, "model": "test-model", "vae": ""}, job_ids=["old_job"],
    )
    asset = legacy.promote_latest_output_as_baseline(asset.asset_id)
    history_before = [entry.to_dict() for entry in asset.history]
    snapshots_before = [entry.to_dict() for entry in asset.baseline_snapshots]
    sidecar_before = legacy.sidecar_path(asset.asset_id).read_bytes()
    original_before = queued_input.read_bytes()
    queued_njr = ReprocessJobBuilder().build_reprocess_job(
        input_image_paths=[queued_input], stages=["img2img"], config=asset.baseline.config,
    )
    frozen_before = queued_njr.to_dict()
    target = tmp_path / "output" / "PhotoOptimize" / "workspace"
    first = migrate_assets(legacy.root, target)
    assert first.migrated == [asset.asset_id] and not first.failures
    migrated = PhotoOptimizeStore(target).get_asset(asset.asset_id)
    assert migrated.current_input_path.is_relative_to(target)
    assert migrated.current_input_path.read_bytes() == original_before
    assert list(queued_njr.input_image_paths) == [str(queued_input)]
    assert queued_njr.to_dict() == frozen_before
    assert queued_input.read_bytes() == original_before
    assert legacy.sidecar_path(asset.asset_id).read_bytes() == sidecar_before
    repeated = migrate_assets(legacy.root, target)
    assert repeated.migrated == [] and repeated.already_present == [asset.asset_id] and not repeated.failures
    assert [entry.to_dict() for entry in migrated.history] == history_before
    assert [entry.to_dict() for entry in migrated.baseline_snapshots] == snapshots_before


def test_migration_collision_leaves_both_trees_untouched(tmp_path):
    legacy = PhotoOptimizeStore(tmp_path / "legacy")
    asset = legacy.import_photo(image(tmp_path / "source.png"))
    target = tmp_path / "target"
    collision = target / "assets" / asset.asset_id
    collision.mkdir(parents=True)
    user_data = collision / "owner.txt"
    user_data.write_text("keep")
    before = legacy.sidecar_path(asset.asset_id).read_bytes()
    report = migrate_assets(legacy.root, target)
    assert len(report.failures) == 1 and "collision" in report.failures[0].error
    assert not report.migrated
    assert user_data.read_text() == "keep"
    assert legacy.sidecar_path(asset.asset_id).read_bytes() == before


def test_failed_migration_never_publishes_partial_asset(tmp_path):
    legacy = PhotoOptimizeStore(tmp_path / "legacy")
    asset = legacy.import_photo(image(tmp_path / "source.png"))
    target = tmp_path / "target"
    with patch("src.photo_optimize.migration.shutil.copytree", side_effect=OSError("copy failed")):
        report = migrate_assets(legacy.root, target)
    assert len(report.failures) == 1 and "copy failed" in report.failures[0].error
    assert not report.migrated
    assert not (target / "assets" / asset.asset_id).exists()
    assert legacy.get_asset(asset.asset_id) is not None
    assert asset.current_input_path.exists()


def test_scanner_excludes_managed_duplicates(tmp_path):
    from src.learning.output_scanner import OutputScanner

    managed = WorkspacePaths(tmp_path).photo_optimize_root()
    image(managed / "assets" / "a" / "outputs" / "copy.png")
    scanner = OutputScanner(tmp_path / "output")
    with patch("src.learning.output_scanner._record_from_embedded") as read:
        assert scanner.scan_full() == []
    read.assert_not_called()


def test_empty_selection_refuses(tmp_path):
    app = controller()
    with patch(
        "src.controller.app_controller.get_photo_optimize_store",
        return_value=PhotoOptimizeStore(tmp_path / "photos"),
    ):
        with pytest.raises(ValueError, match="No photo assets"):
            app.on_optimize_photo_assets(assets=[], stages=["img2img"])
    app.job_service.submit_njrs.assert_not_called()


def test_gui_snapshot_is_the_only_worker_fallback_source(tmp_path):
    app = controller()
    snapshot = app.build_photo_optimize_defaults()
    app._collect_current_stage_configs.side_effect = AssertionError("Worker read Tk settings")
    store = PhotoOptimizeStore(tmp_path / "photos")
    asset = store.import_photo(image(tmp_path / "photo.png"))
    with patch("src.controller.app_controller.get_photo_optimize_store", return_value=store):
        assert app.on_optimize_photo_assets(assets=[asset.to_dict()], stages=["img2img"],
                                           pipeline_defaults_snapshot=snapshot) == 1


def test_mixed_photo_jobs_retain_output_history_association(tmp_path):
    from src.queue.job_model import JobStatus

    app = controller()
    app.main_window = None
    store = PhotoOptimizeStore(tmp_path / "photos")
    assets = [store.import_photo(image(tmp_path / f"source_{n}.png")) for n in range(3)]
    assets[2].baseline.stage_defaults = {"img2img": False, "adetailer": False, "upscale": True}
    with patch("src.controller.app_controller.get_photo_optimize_store", return_value=store):
        assert app.on_optimize_photo_assets(assets=[a.to_dict() for a in assets], stages=["img2img"], batch_size=4) == 2
        jobs = app.job_service.submit_njrs.call_args.args[0]
        store.archive_assets([assets[0].asset_id])
        for record in jobs:
            outputs = [str(image(tmp_path / "generated" / f"{record.job_id}_{n}.png"))
                       for n in range(len(record.input_image_paths))]
            job = SimpleNamespace(job_id=record.job_id, status=JobStatus.COMPLETED,
                                  result={"output_paths": outputs}, _normalized_record=record)
            app._handle_photo_optimize_completion(job, job.result)
            app._handle_photo_optimize_completion(job, job.result)
            for index, info in enumerate(record.extra_metadata["photo_optimize"]["assets"]):
                persisted = store.get_asset(info["asset_id"])
                assert len(persisted.history) == 1
                entry = persisted.history[0]
                assert entry.job_ids == [record.job_id]
                assert entry.input_image_path == record.input_image_paths[index]
                assert entry.stages == info["stages"]
                assert entry.config_snapshot == record.config
                assert Path(entry.output_paths[0]).name.endswith(Path(outputs[index]).name)
    assert store.get_asset(assets[0].asset_id).archived is True


def test_migration_handles_long_windows_provenance_names(tmp_path):
    from src.photo_optimize.paths import io_path

    legacy = PhotoOptimizeStore(tmp_path / "legacy")
    asset = legacy.import_photo(image(tmp_path / "source.png"))
    long_output = io_path(legacy.outputs_dir(asset.asset_id) / ("x" * 150 + ".png"))
    Image.new("RGB", (40, 60)).save(long_output)
    asset.baseline.working_image_path = str(long_output)
    legacy.save_asset(asset)
    target = tmp_path / "routed-output" / "PhotoOptimize" / "workspace"
    migrate_assets(legacy.root, target)
    migrated = PhotoOptimizeStore(target).get_asset(asset.asset_id)
    assert migrated.current_input_path.read_bytes() == long_output.read_bytes()
    assert resolve_geometry(migrated.baseline, migrated.current_input_path)["width"] == 40
    repeated = migrate_assets(legacy.root, target)
    assert repeated.migrated == [] and not repeated.failures


def test_cleared_model_uses_live_pipeline_instead_of_stale_nested_identity(tmp_path):
    app = controller()
    store = PhotoOptimizeStore(tmp_path / "photos")
    asset = store.import_photo(image(tmp_path / "photo.png"), baseline_defaults={
        "model": "oldModel", "config": {"model": "oldModel", "img2img": {"model": "oldModel"}},
    })
    asset.baseline.model = ""  # Explicit form edit: use Pipeline fallback.
    with patch("src.controller.app_controller.get_photo_optimize_store", return_value=store):
        app.on_optimize_photo_assets(assets=[asset.to_dict()], stages=["img2img"])
    record = app.job_service.submit_njrs.call_args.args[0][0]
    assert record.config["model"] == "photoModel"
    assert record.stage_chain[0].model == "photoModel"


def test_empty_img2img_pipeline_model_inherits_live_txt2img_identity():
    from src.photo_optimize.submission import pipeline_defaults

    defaults = pipeline_defaults({"img2img": {"model": "", "vae": ""},
                                  "txt2img": {"model": "selectedModel", "vae": "oldVae"}})
    assert defaults["model"] == "selectedModel"
    assert defaults["vae"] == ""
