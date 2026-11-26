"""N5 owner decision 3: a model with a saved recipe uses its own settings in a batch, unless the owner turns it off."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller_services import pack_model_batch_recipes as recipes
from src.controller.app_controller_services import pack_model_batch_service as batch
from src.controller.app_controller_services.gui_config_service import build_stage_overrides
from src.generation_profiles.service import GenerationProfileService
from tests.controller.test_pack_model_batch_n5 import Harness
from tests.generation_profiles.test_profile_service import (
    OTHER_SDXL,
    SD15_MODEL,
    SDXL_MODEL,
    _service,
)
from tests.pipeline.test_prompt_pack_job_builder import BASE_PACK_CONFIG

RECIPE = {"sampler_name": "Euler a", "steps": 40, "cfg_scale": 5.5}
MODELS = (SDXL_MODEL, SD15_MODEL)


def _working() -> dict[str, Any]:
    txt2img = BASE_PACK_CONFIG["txt2img"]
    values = {
        key: txt2img[key]
        for key in ("sampler_name", "scheduler", "steps", "cfg_scale", "width", "height")
    }
    values["model"] = txt2img["model"]
    return values


@pytest.fixture
def profiles(tmp_path: Path) -> GenerationProfileService:
    service = _service(tmp_path)
    saved = service.save_custom("Batch fav", SDXL_MODEL, {**_working(), **RECIPE})
    service.set_favorite(SDXL_MODEL, saved.ref)
    return service


@pytest.fixture
def harness(tmp_path: Path, profiles: GenerationProfileService) -> Harness:
    h = Harness(tmp_path)
    h.base = replace(h.base, recipe_context=recipes.RecipeContext(profiles, _working(), {}, {}))
    return h


def _plan(harness: Harness, *, use_recipes: bool = True, pack_config: dict | None = None):
    request = batch.BatchRequest("recipes", ("castles",), MODELS, use_recipes=use_recipes)
    resolved = recipes.resolve_recipes(harness.base.recipe_context, MODELS) if use_recipes else {}
    sources = harness.sources("castles")
    if pack_config is not None:
        sources = [replace(source, pack_config=pack_config) for source in sources]
    cells = batch.compile_cells(
        request, harness.base, sources, harness.builder.build_jobs, resolved
    )
    return batch.build_plan(request, cells, None, resolved)


def _record(plan: batch.BatchPlan, model: str) -> Any:
    (cell,) = [cell for cell in plan.cells if cell.model == model]
    (record,) = cell.records
    return record


def test_a_model_with_a_saved_recipe_uses_it_and_a_model_without_one_uses_the_pipeline_settings(
    harness: Harness,
):
    plan = _plan(harness)

    with_recipe = _record(plan, SDXL_MODEL)
    assert (with_recipe.sampler_name, with_recipe.steps, with_recipe.cfg_scale) == (
        "Euler a",
        40,
        5.5,
    )
    without = _record(plan, SD15_MODEL)
    pipeline = BASE_PACK_CONFIG["txt2img"]
    assert (without.sampler_name, without.steps, without.cfg_scale) == (
        pipeline["sampler_name"],
        pipeline["steps"],
        pipeline["cfg_scale"],
    )

    text = "\n".join(plan.summary_lines())
    assert "Settings per model" in text
    assert f"{SDXL_MODEL}: recipe Custom: Batch fav (sampler Euler a, steps 40, CFG 5.5)" in text
    assert f"{SD15_MODEL}: Pipeline tab settings (no saved recipe)" in text


def test_the_owner_can_use_the_pipeline_settings_for_every_model(harness: Harness):
    plan = _plan(harness, use_recipes=False)

    for model in MODELS:
        assert _record(plan, model).steps == BASE_PACK_CONFIG["txt2img"]["steps"]
    assert plan.recipes == {}
    assert "the Pipeline tab's settings for every model (saved recipes off)" in "\n".join(
        plan.summary_lines()
    )
    for record in batch.stamp_batch(plan, "b-1"):
        identity = batch.batch_identity(record)
        assert identity["settings"] == "pipeline_tab"
        assert identity["cell"]["recipe"] is None


def test_the_batch_provenance_records_which_recipe_each_cell_used(harness: Harness):
    plan = _plan(harness)
    stamped = {
        batch.batch_identity(r)["cell"]["model"]: batch.batch_identity(r)
        for r in batch.stamp_batch(plan, "b-2")
    }

    sdxl = stamped[SDXL_MODEL]
    assert sdxl["settings"] == "model_recipes"
    assert sdxl["cell"]["recipe"]["label"] == "Custom: Batch fav"
    assert sdxl["cell"]["recipe"]["ref"]["kind"] == "custom"
    assert sdxl["cell"]["recipe"]["changes"] == RECIPE
    assert sdxl["cell"]["recipe_replaced_by_pack"] == []
    assert stamped[SD15_MODEL]["cell"]["recipe"] is None


def test_a_packs_own_saved_settings_still_win_and_the_summary_says_so(harness: Harness):
    pack_txt2img = {**copy.deepcopy(BASE_PACK_CONFIG["txt2img"]), "steps": 12}
    plan = _plan(harness, pack_config={"txt2img": pack_txt2img})

    record = _record(plan, SDXL_MODEL)
    assert record.steps == 12
    (cell,) = [cell for cell in plan.cells if cell.model == SDXL_MODEL]
    assert set(cell.replaced) == {"sampler", "steps", "CFG"}
    assert "The pack's saved settings replace the recipe's" in "\n".join(plan.summary_lines())


def test_with_the_pack_settings_override_on_the_recipe_reaches_the_override_bundle(
    harness: Harness,
):
    draft = replace(
        harness.base.draft_config,
        stage_overrides=build_stage_overrides(copy.deepcopy(BASE_PACK_CONFIG)),
    )
    recipe = recipes.ModelRecipe(
        SDXL_MODEL, {"kind": "custom", "profile_id": "x"}, "Custom: x", RECIPE
    )

    applied = recipes.with_recipe(draft, recipe)

    stage = applied.stage_overrides.txt2img
    assert (stage.sampler, stage.steps, stage.cfg_scale) == ("Euler a", 40, 5.5)
    assert applied.base_config["txt2img"]["steps"] == 40
    assert draft.base_config["txt2img"]["steps"] == BASE_PACK_CONFIG["txt2img"]["steps"]
    assert draft.stage_overrides.txt2img.steps == BASE_PACK_CONFIG["txt2img"]["steps"]


def test_unreadable_recipes_fall_back_to_the_pipeline_settings():
    assert recipes.resolve_recipes(None, ["a"])["a"].note == "saved recipes are unavailable"

    class Broken:
        def resolve(self, _model):
            raise RuntimeError("store locked")

        def vae_options(self, _model, _resources):
            return None

        def plan_for_model(self, *_args, **_kwargs):
            raise RuntimeError("store locked")

    context = recipes.RecipeContext(Broken(), {"model": "x"}, {}, {})
    recipe = recipes.resolve_recipes(context, ["a"])["a"]
    assert not recipe.applies and "store locked" in recipe.note


def test_planning_a_model_does_not_select_its_profile(profiles: GenerationProfileService):
    before = profiles.state_for(OTHER_SDXL).selected

    plan, profile = profiles.plan_for_model(OTHER_SDXL, {**_working(), "model": OTHER_SDXL})

    assert profile is not None and plan.profile == profile.ref
    assert profiles.state_for(OTHER_SDXL).selected == before is None


def test_capture_reads_the_pipeline_profiles_on_the_gui_thread(profiles: GenerationProfileService):
    controller = SimpleNamespace(
        service=profiles,
        working_values=lambda: {"model": SDXL_MODEL, "steps": 24},
        catalogs=lambda: {"samplers": ["Euler a"]},
        _resources=lambda: {"models": []},
    )
    context = recipes.capture_recipe_context(SimpleNamespace(generation_profiles=controller))
    assert context.service is profiles
    assert context.working == {"model": SDXL_MODEL, "steps": 24}
    assert recipes.capture_recipe_context(SimpleNamespace()) is None
