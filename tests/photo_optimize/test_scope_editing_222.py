from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.photo_optimize.store import PhotoOptimizeStore
from tests.photo_optimize.test_photo_220 import image


def make_photos(tmp_path):
    store = PhotoOptimizeStore(tmp_path / "photos")
    ids = []
    for i in range(3):
        asset = store.import_photo(image(tmp_path / f"{i}.png", (320 + 64 * i, 480)))
        asset.baseline.prompt = f"portrait {i}, natural light"
        asset.baseline.model = f"model-{i}"
        asset.baseline.config["img2img"]["scheduler"] = ("normal", "karras", "exponential")[i]
        asset.baseline.stage_defaults["adetailer"] = bool(i % 2)
        asset.notes, asset.tags = f"note-{i}", [f"tag-{i}"]
        store.save_asset(asset)
        ids.append(asset.asset_id)
    return store, ids


@pytest.fixture
def photos(tmp_path):
    return make_photos(tmp_path)


def test_masked_batch_diff_preserves_unselected_fields(photos):
    from src.photo_optimize.editing import apply_edit, prepare_edit, selection_values

    store, ids = photos
    before = {i: store.get_asset(i).to_dict() for i in ids}
    assert selection_values([store.get_asset(i) for i in ids])["model"].mixed
    plan = prepare_edit(store, ids, {"stage.adetailer": False, "config.img2img.cfg_scale": 0})
    assert all(len(row.changes) == (1 if index != 1 else 2) for index, row in enumerate(plan.rows))
    result = apply_edit(store, plan)
    assert result.applied == ids and not result.failed
    for identity in ids:
        asset = store.get_asset(identity)
        expected = before[identity]
        assert asset.baseline.prompt == expected["baseline"]["prompt"]
        assert asset.baseline.model == expected["baseline"]["model"]
        assert asset.notes == expected["notes"] and asset.tags == expected["tags"]
        assert asset.baseline.geometry_policy == "auto"
        assert asset.baseline.config["img2img"]["cfg_scale"] == 0
        assert (
            asset.baseline.config["img2img"]["scheduler"]
            == expected["baseline"]["config"]["img2img"]["scheduler"]
        )


def test_single_stage_edit_does_not_write_other_selected_photos(photos, tmp_path):
    from tests.photo_optimize.test_photo_220_form import form

    store, ids = photos
    tab = form(tmp_path)
    tab.store = store
    tab._current_asset = store.get_asset(ids[0])
    tab._current_asset_id = ids[0]
    tab._asset_index_by_row = ids
    tab.assets_list.selection_set(1)
    tab.assets_list.selection_set(2)
    before = [store.sidecar_path(i).read_bytes() for i in ids[1:]]
    tab.stage_adetailer_var.set(True)
    tab._persist_current_asset_baseline()
    assert [store.sidecar_path(i).read_bytes() for i in ids[1:]] == before


def test_img2img_scheduler_form_load_and_collect(tmp_path):
    from tests.photo_optimize.test_photo_220_form import Variable, form

    tab = form(tmp_path)
    tab.img2img_scheduler_var = Variable()
    tab._load_baseline_config_form({"img2img": {"scheduler": "karras"}})
    assert tab.img2img_scheduler_var.get() == "karras"
    tab.img2img_scheduler_var.set("exponential")
    assert tab._collect_baseline_config_from_form()["img2img"]["scheduler"] == "exponential"


def test_pipeline_snapshot_matches_live_card_serializers():
    from src.controller.app_controller import AppController
    from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
    from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2

    def var(value):
        return SimpleNamespace(get=lambda: value)

    img = SimpleNamespace(
        **{
            k + "_var": var(v)
            for k, v in {
                "model": "live-img-model",
                "vae": "Automatic",
                "sampler": "DPM++ 2M",
                "steps": 31,
                "cfg": 0,
                "denoise": 0,
                "width": 768,
                "height": 1024,
                "mask_mode": "none",
            }.items()
        }
    )
    img.to_config_dict = lambda: AdvancedImg2ImgStageCardV2.to_config_dict(img)
    up = SimpleNamespace(
        _upscaler_name_map={},
        **{
            k + "_var": var(v)
            for k, v in {
                "upscaler": "test-upscaler",
                "mode": "img2img",
                "steps": 17,
                "denoise": 0.2,
                "factor": 2.5,
                "tile_size": 0,
                "face_restore": False,
                "face_restore_method": "CodeFormer",
                "sampler": "Euler",
                "scheduler": "karras",
            }.items()
        },
    )
    up.to_config_dict = lambda: AdvancedUpscaleStageCardV2.to_config_dict(up)
    controller = AppController.__new__(AppController)
    controller._get_stage_cards_panel = lambda: SimpleNamespace(img2img_card=img, upscale_card=up)
    controller._get_panel_randomizer_config = lambda: {}
    controller._read_prompt_optimizer_ui_config = lambda: None
    controller._append_log = Mock()
    controller.main_window = SimpleNamespace(
        pipeline_tab=SimpleNamespace(
            img2img_enabled=var(True), adetailer_enabled=var(False), upscale_enabled=var(True)
        )
    )
    result = controller.build_photo_optimize_defaults()
    assert result["model"] == "live-img-model" and result["vae"] == ""
    assert result["config"]["img2img"]["steps"] == 31
    assert result["config"]["img2img"]["cfg_scale"] == 0
    assert result["config"]["upscale"]["scheduler"] == "karras"
    assert result["config"]["upscale"]["upscaling_resize"] == 2.5
    assert result["stage_defaults"] == {"img2img": True, "adetailer": False, "upscale": True}


def test_pipeline_copy_excludes_normalization_defaults_not_exported_by_controls():
    from src.photo_optimize.editing import pipeline_mask
    from src.photo_optimize.submission import pipeline_defaults

    snapshot = pipeline_defaults({"img2img": {"steps": 31}, "upscale": {"scheduler": "karras"}})
    assert snapshot["config"]["img2img"]["scheduler"]  # normalization supplies a fallback
    assert pipeline_mask(snapshot, {"img2img", "upscale", "geometry"}) == {
        "config.img2img.steps": 31,
        "config.upscale.scheduler": "karras",
    }


@pytest.mark.parametrize(
    "mode,delta,expected",
    [
        ("append", "studio", "portrait 0, natural light, studio"),
        ("replace", "studio", "studio"),
        ("modify", "-natural light, +studio", "portrait 0, studio"),
    ],
)
def test_batch_saved_prompt_transform_uses_review_semantics(photos, mode, delta, expected):
    from src.photo_optimize.editing import PromptEdit, apply_edit, prepare_edit

    store, ids = photos
    plan = prepare_edit(store, ids, {"prompt": PromptEdit(mode, delta)})
    apply_edit(store, plan)
    assert store.get_asset(ids[0]).baseline.prompt == expected


def test_preflight_is_whole_selection_and_write_failures_are_explicit(photos, monkeypatch):
    from src.photo_optimize.editing import apply_edit, prepare_edit

    store, ids = photos
    before = [store.sidecar_path(i).read_bytes() for i in ids]
    with pytest.raises(ValueError):
        prepare_edit(store, ids, {"config.img2img.steps": -1})
    assert [store.sidecar_path(i).read_bytes() for i in ids] == before
    plan = prepare_edit(store, ids, {"stage.upscale": True})
    save = store.save_asset

    def fail(asset):
        if asset.asset_id == ids[1]:
            raise PermissionError("injected write failure")
        return save(asset)

    monkeypatch.setattr(store, "save_asset", fail)
    result = apply_edit(store, plan)
    assert result.applied == [ids[0], ids[2]] and list(result.failed) == [ids[1]]
    assert store.sidecar_path(ids[1]).read_bytes() == before[1]


def test_pipeline_field_mask_and_geometry_are_explicit(photos):
    from src.photo_optimize.editing import apply_edit, pipeline_mask, prepare_edit

    store, ids = photos
    snapshot = {
        "model": "live",
        "vae": "",
        "stage_defaults": {"img2img": False},
        "config": {
            "img2img": {"width": 1024, "height": 768, "scheduler": "karras", "steps": 37},
            "adetailer": {"ad_mask_blur": 11},
        },
    }
    candidates = pipeline_mask(snapshot, {"img2img", "adetailer"})
    assert "config.img2img.width" not in candidates and "geometry_policy" not in candidates
    assert candidates["config.adetailer.ad_mask_blur"] == 11
    before = [store.get_asset(i).to_dict() for i in ids]
    apply_edit(
        store,
        prepare_edit(
            store, ids, {"config.img2img.scheduler": candidates["config.img2img.scheduler"]}
        ),
    )
    for i, identity in enumerate(ids):
        current = store.get_asset(identity)
        assert current.baseline.geometry_policy == "auto"
        assert current.baseline.config["img2img"]["width"] == 320 + 64 * i
        assert (
            current.baseline.config["img2img"]["steps"]
            == before[i]["baseline"]["config"]["img2img"]["steps"]
        )
        assert current.baseline.model == before[i]["baseline"]["model"]
    with pytest.raises(ValueError, match="explicitly selecting Custom"):
        prepare_edit(store, ids, {"config.img2img.width": 768})
    with pytest.raises(ValueError, match="explicit width and height"):
        prepare_edit(store, ids, {"geometry_policy": "custom"})
    apply_edit(store, prepare_edit(store, ids, pipeline_mask(snapshot, {"geometry"})))
    assert all(store.get_asset(i).baseline.geometry_policy == "custom" for i in ids)
    assert all(store.get_asset(i).baseline.config["img2img"]["width"] == 1024 for i in ids)


def test_stale_review_refuses_all_writes(photos):
    from src.photo_optimize.editing import apply_edit, prepare_edit

    store, ids = photos
    plan = prepare_edit(store, ids, {"stage.upscale": True})
    changed = store.get_asset(ids[2])
    changed.notes = "owner edit after preview"
    store.save_asset(changed)
    before = [store.sidecar_path(i).read_bytes() for i in ids]
    with pytest.raises(ValueError, match="nothing applied"):
        apply_edit(store, plan)
    assert [store.sidecar_path(i).read_bytes() for i in ids] == before


def test_after_replace_exception_is_classified_by_readback(photos, monkeypatch):
    from src.photo_optimize.editing import apply_edit, prepare_edit

    store, ids = photos
    plan = prepare_edit(store, ids, {"stage.upscale": True})
    save = store.save_asset

    def fail_after_replace(asset):
        save(asset)
        raise PermissionError("after replacement")

    monkeypatch.setattr(store, "save_asset", fail_after_replace)
    result = apply_edit(store, plan)
    assert result.applied == ids and not result.failed and not result.unconfirmed


def test_missing_final_input_preflights_before_first_write(photos):
    from src.photo_optimize.editing import prepare_edit

    store, ids = photos
    store.get_asset(ids[-1]).current_input_path.unlink()  # disposable fixture only
    before = [store.sidecar_path(i).read_bytes() for i in ids]
    with pytest.raises(ValueError, match="decode"):
        prepare_edit(store, ids, {"stage.upscale": True})
    assert [store.sidecar_path(i).read_bytes() for i in ids] == before


def test_archived_draft_and_history_remain_archived_and_unchanged(photos):
    from src.photo_optimize.editing import apply_edit, prepare_edit

    store, ids = photos
    asset = store.get_asset(ids[1])
    asset.archived = True
    store.save_asset(asset)
    original = deepcopy(asset.to_dict())
    apply_edit(store, prepare_edit(store, ids, {"config.upscale.face_restore": False}))
    saved = store.get_asset(ids[1]).to_dict()
    for key in ("archived", "notes", "tags", "history", "baseline_snapshots"):
        assert saved[key] == original[key]


def test_scheduler_parity_and_unchanged_frozen_grouping(photos):
    from src.photo_optimize.editing import apply_edit, prepare_edit
    from src.photo_optimize.submission import prepare_photo_plan

    store, ids = photos

    def prepare():
        return prepare_photo_plan(
            assets=[store.get_asset(i).to_dict() for i in ids],
            stages=["img2img"],
            fallback_config={"img2img": {}},
            store=store,
            batch_size=3,
        )

    plan = prepare()
    frozen = [job.to_dict() for job in plan.jobs]
    expected = dict(zip(ids, ["normal", "karras", "exponential"], strict=True))
    assert {
        row["asset_id"]: job.stage_chain[0].scheduler
        for job in plan.jobs
        for row in job.extra_metadata["photo_optimize"]["assets"]
    } == expected
    apply_edit(store, prepare_edit(store, ids, {"config.img2img.scheduler": "karras"}))
    assert [job.to_dict() for job in plan.jobs] == frozen
    revised = prepare()
    assert (
        len(revised.jobs) == len(plan.jobs) == 3
    )  # distinct per-photo models/prompts still partition
    assert all(job.stage_chain[0].scheduler == "karras" for job in revised.jobs)
