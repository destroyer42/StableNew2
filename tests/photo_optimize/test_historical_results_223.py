from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from src.photo_optimize.store import PhotoOptimizeStore
from src.photo_optimize.submission import prepare_photo_plan


def picture(path, size=(320, 480), color="blue"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def recorded(store, asset, root, run, count=1):
    outputs = [
        str(picture(root / run / f"{i}.png", (640 + i * 64, 512), "red")) for i in range(count)
    ]
    for output in outputs:
        Path(output).with_suffix(".json").write_text('{"fixture_manifest": true}', encoding="utf-8")
    return store.record_optimize_history(
        asset.asset_id,
        run_id=run,
        input_image_path=str(asset.current_input_path),
        source_output_paths=outputs,
        prompt_mode="replace",
        prompt_delta="historical portrait",
        negative_prompt_mode="replace",
        negative_prompt_delta="blur",
        effective_prompt=f"portrait {run}",
        effective_negative_prompt="blur",
        stages=["img2img"],
        config_snapshot={
            "model": f"model-{run}",
            "vae": "",
            "img2img": {"steps": 31, "scheduler": "karras"},
        },
        job_ids=[f"job-{run}"],
    )


def make_library(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    asset = store.import_photo(
        picture(tmp_path / "original.png"),
        baseline_defaults={
            "prompt": "original portrait",
            "negative_prompt": "noise",
            "model": "original-model",
            "config": {"img2img": {"steps": 20}},
        },
    )
    recorded(store, asset, tmp_path, "older", 2)
    asset = recorded(store, store.get_asset(asset.asset_id), tmp_path, "latest")
    return store, asset


@pytest.fixture
def library(tmp_path):
    return make_library(tmp_path)


def candidate(store, asset, kind="history", history_index=0, output_index=0):
    return next(
        c
        for c in store.list_result_candidates(asset.asset_id)
        if c.kind == kind
        and (
            kind != "history" or (c.history_index, c.output_index) == (history_index, output_index)
        )
    )


def inventory(store, asset):
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in store.asset_dir(asset.asset_id).rglob("*")
        if p.is_file() and p.name != "sidecar.json"
    }


def promote(store, asset, result=None, mode="recorded"):
    plan = store.prepare_result_promotion(
        asset.asset_id, result or candidate(store, asset), mode=mode
    )
    return store.apply_result_promotion(plan)


def test_all_outputs_older_result_original_and_snapshot_restore(library):
    store, asset = library
    before = deepcopy(asset.to_dict())
    files = inventory(store, asset)
    rows = store.list_result_candidates(asset.asset_id)
    assert [c.kind for c in rows].count("history") == 3
    older_second = candidate(store, asset, output_index=1)
    updated = promote(store, asset, older_second)
    assert updated.baseline.working_image_path == older_second.path
    assert updated.baseline.prompt == "portrait older"
    assert updated.baseline.negative_prompt == "blur"
    assert updated.baseline.model == "model-older" and updated.baseline.vae == ""
    assert updated.baseline.config["img2img"]["steps"] == 31
    assert updated.baseline.config["img2img"]["width"] == 704
    assert len(updated.baseline_snapshots) == 1
    unchanged = store.sidecar_path(asset.asset_id).read_bytes()
    promote(store, updated, older_second)
    assert store.sidecar_path(asset.asset_id).read_bytes() == unchanged
    reverted = store.revert_baseline(asset.asset_id)
    assert reverted.baseline.to_dict() == before["baseline"]
    promote(store, reverted, older_second)
    original = promote(store, updated, candidate(store, updated, "original"))
    assert original.current_input_path == Path(asset.managed_original_path)
    assert original.baseline.prompt == "original portrait"
    assert original.baseline.model == "original-model"
    assert inventory(store, asset) == files
    assert original.to_dict()["history"] == before["history"]


def test_image_only_retains_prompts_settings_and_custom_geometry(library):
    store, asset = library
    asset.baseline.geometry_policy = "custom"
    asset.baseline.config["img2img"].update(width=768, height=1024)
    store.save_asset(asset)
    before = asset.baseline.to_dict()
    updated = promote(store, asset, mode="image_only")
    for key in (
        "prompt",
        "negative_prompt",
        "model",
        "vae",
        "stage_defaults",
        "config",
        "geometry_policy",
    ):
        assert updated.baseline.to_dict()[key] == before[key]


@pytest.mark.parametrize(
    "fault", ["missing", "corrupt", "changed", "outside", "wrong_index", "wrong_asset", "duplicate"]
)
def test_invalid_candidates_refuse_without_sidecar_mutation(library, tmp_path, fault):
    store, asset = library
    result = candidate(store, asset)
    if fault == "missing":
        Path(result.path).unlink()
    elif fault == "corrupt":
        Path(result.path).write_bytes(b"not an image")
    elif fault == "changed":
        picture(Path(result.path), color="green")
    elif fault == "outside":
        path = str(picture(tmp_path / "outside.png"))
        asset.history[0].output_paths[0] = path
        store.save_asset(asset)
        result = replace(result, path=path)
    elif fault == "wrong_index":
        result = replace(result, output_index=99)
    elif fault == "wrong_asset":
        result = replace(result, asset_id="someone-else")
    else:
        asset.history[1].output_paths.append(result.path)
        store.save_asset(asset)
    before = store.sidecar_path(asset.asset_id).read_bytes()
    with pytest.raises((ValueError, OSError)):
        store.prepare_result_promotion(asset.asset_id, result, mode="recorded")
    assert store.sidecar_path(asset.asset_id).read_bytes() == before


def test_incomplete_metadata_offers_explicit_image_only(library):
    store, asset = library
    asset.history[0].config_snapshot = {}
    store.save_asset(asset)
    result = candidate(store, asset)
    before = store.sidecar_path(asset.asset_id).read_bytes()
    with pytest.raises(ValueError, match="(?i)recorded.*settings|metadata"):
        store.prepare_result_promotion(asset.asset_id, result, mode="recorded")
    assert store.sidecar_path(asset.asset_id).read_bytes() == before
    updated = promote(store, asset, result, "image_only")
    assert updated.baseline.prompt == asset.baseline.prompt


def test_promotion_is_one_atomic_sidecar_save_and_refuses_stale_review(library, monkeypatch):
    store, asset = library
    plan = store.prepare_result_promotion(asset.asset_id, candidate(store, asset), mode="recorded")
    before = store.sidecar_path(asset.asset_id).read_bytes()
    calls = []

    def fail(updated):
        calls.append(deepcopy(updated.to_dict()))
        raise PermissionError("injected before atomic replacement")

    with monkeypatch.context() as patcher:
        patcher.setattr(store, "save_asset", fail)
        with pytest.raises(PermissionError):
            store.apply_result_promotion(plan)
    assert len(calls) == 1
    assert len(calls[0]["baseline_snapshots"]) == 1
    assert calls[0]["baseline"]["working_image_path"] != asset.baseline.working_image_path
    assert store.sidecar_path(asset.asset_id).read_bytes() == before
    asset.notes = "operator edit during review"
    store.save_asset(asset)
    before = store.sidecar_path(asset.asset_id).read_bytes()
    with pytest.raises(ValueError, match="(?i)changed|stale"):
        store.apply_result_promotion(plan)
    assert store.sidecar_path(asset.asset_id).read_bytes() == before


def test_restart_submission_and_frozen_jobs_artifacts_are_unchanged(library):
    store, asset = library

    def compile_plan(current):
        return prepare_photo_plan(
            assets=[current.to_dict()],
            stages=["img2img"],
            fallback_config={"img2img": {}},
            store=store,
            batch_size=1,
        )

    preexisting = compile_plan(asset)
    frozen = deepcopy([job.to_dict() for job in preexisting.jobs])
    files = inventory(store, asset)
    promoted = promote(store, asset)
    restarted = PhotoOptimizeStore(store.root).get_asset(asset.asset_id)
    assert restarted.baseline.to_dict() == promoted.baseline.to_dict()
    current = compile_plan(restarted)
    assert tuple(current.jobs[0].input_image_paths) == (promoted.baseline.working_image_path,)
    assert current.jobs[0].config["model"] == "model-older"
    assert [job.to_dict() for job in preexisting.jobs] == frozen
    assert inventory(store, asset) == files


def test_migration_mapping_uses_recorded_identity_not_current_legacy_link_target(
    tmp_path, monkeypatch
):
    from src.photo_optimize import results

    legacy, asset = make_library(tmp_path / "legacy-root")
    asset.history[0].output_sha256 = {}  # legacy history predates per-output hashes
    legacy.save_asset(asset)
    store = PhotoOptimizeStore(tmp_path / "migrated", legacy_root=legacy.root)
    migrated = store.get_asset(asset.asset_id)
    selected = candidate(store, migrated)
    actual_canonical = results.canonical

    def legacy_link_resolution(path):
        # Inject the filesystem resolution of a replaced legacy output link, without Windows privileges.
        if str(path) == selected.path:
            return actual_canonical(asset.managed_original_path)
        return actual_canonical(path)

    monkeypatch.setattr(results, "canonical", legacy_link_resolution)
    before = store.sidecar_path(asset.asset_id).read_bytes()
    plan = store.prepare_result_promotion(asset.asset_id, selected, mode="recorded")
    assert Path(plan.after.working_image_path).parent.name == "outputs"
    assert Path(plan.after.working_image_path).name == Path(selected.path).name
    assert store.sidecar_path(asset.asset_id).read_bytes() == before


def test_stale_output_bytes_and_atomic_replace_failure_never_split_snapshot(library, monkeypatch):
    store, asset = library
    result = candidate(store, asset)
    plan = store.prepare_result_promotion(asset.asset_id, result, mode="recorded")
    before = store.sidecar_path(asset.asset_id).read_bytes()
    actual_replace = os.replace

    def deny_replace(path, destination):
        # The sidecar write goes through src.utils.atomic_io (fsync, then os.replace with a Windows retry).
        if Path(destination) == store.sidecar_path(asset.asset_id):
            raise PermissionError("injected atomic replace denial")
        return actual_replace(path, destination)

    with monkeypatch.context() as patcher:
        patcher.setattr("src.utils.atomic_io.os.replace", deny_replace)
        patcher.setattr("src.utils.atomic_io._REPLACE_BACKOFF_S", 0)
        with pytest.raises(PermissionError):
            store.apply_result_promotion(plan)
    leftovers = [
        item.name
        for item in store.sidecar_path(asset.asset_id).parent.iterdir()
        if item.suffix == ".tmp"
    ]
    assert leftovers == []
    assert store.sidecar_path(asset.asset_id).read_bytes() == before
    picture(Path(result.path), color="yellow")
    with pytest.raises(ValueError, match="(?i)integrity|changed"):
        store.apply_result_promotion(plan)
    assert store.sidecar_path(asset.asset_id).read_bytes() == before


@pytest.mark.parametrize("fault", ["link", "junction", "traversal"])
def test_link_junction_and_traversal_candidates_are_ineligible(library, monkeypatch, fault):
    store, asset = library
    selected = candidate(store, asset)
    if fault == "traversal":
        tampered = str(Path(selected.path).parent / ".." / "outputs" / Path(selected.path).name)
        asset.history[0].output_paths[0] = tampered
        store.save_asset(asset)
        selected = replace(selected, path=tampered)
    else:
        attribute = "is_symlink" if fault == "link" else "is_junction"
        original = getattr(Path, attribute)
        monkeypatch.setattr(Path, attribute, lambda p: p == Path(selected.path) or original(p))
    before = store.sidecar_path(asset.asset_id).read_bytes()
    with pytest.raises(ValueError):
        store.prepare_result_promotion(asset.asset_id, selected, mode="image_only")
    assert store.sidecar_path(asset.asset_id).read_bytes() == before


def test_legacy_original_missing_metadata_and_explicit_recorded_geometry(library):
    store, asset = library
    asset.original_baseline = None
    asset.history[0].geometry_policy = "custom"
    asset.history[0].config_snapshot["img2img"].update(width=1024, height=768)
    store.save_asset(asset)
    sidecar = store.sidecar_path(asset.asset_id)
    legacy_payload = json.loads(sidecar.read_text(encoding="utf-8"))
    legacy_payload.pop("original_baseline", None)
    sidecar.write_text(json.dumps(legacy_payload), encoding="utf-8")
    asset = store.get_asset(asset.asset_id)
    result = promote(store, asset)
    assert result.baseline.geometry_policy == "custom"
    assert result.baseline.config["img2img"]["width"] == 1024
    before = store.sidecar_path(asset.asset_id).read_bytes()
    original = candidate(store, result, "original")
    with pytest.raises(ValueError, match="Original prompt/settings were not recorded"):
        store.prepare_result_promotion(asset.asset_id, original, mode="recorded")
    assert store.sidecar_path(asset.asset_id).read_bytes() == before
    retained = promote(store, result, original, "image_only")
    assert retained.current_input_path == Path(asset.managed_original_path)
    assert retained.baseline.prompt == result.baseline.prompt
