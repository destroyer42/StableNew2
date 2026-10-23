"""PR-GUI-UX-520: configuration precedence, effective-settings projection and preview-to-queue equivalence.

Real ``ConfigManager`` + ``PipelineController`` + ``PromptPackNormalizedJobBuilder`` over temporary folders; the only fake
is the ``JobService.submit_njrs`` boundary, which records what the queue would receive. No Tk, backend or GPU.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui_v2.effective_settings import EffectiveContext, project_effective_settings
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.utils.config import ConfigManager

PACK_SETTINGS = {
    "txt2img": {
        "model": "pack_model.safetensors",
        "sampler_name": "DPM++ 2M",
        "scheduler": "Karras",
        "steps": 31,
        "cfg_scale": 6.0,
        "width": 832,
        "height": 1216,
    },
    "pipeline": {"images_per_prompt": 2, "output_dir": "D:/pack_out", "image_format": "webp"},
}


class RecordingJobService:
    def __init__(self) -> None:
        self.submitted: list[list[NormalizedJobRecord]] = []

    def submit_njrs(self, records: list[NormalizedJobRecord], policy: Any) -> list[str]:
        self.submitted.append(list(records))
        return [record.job_id for record in records]


def _write_pack(
    manager: ConfigManager, stem: str = "hero", preset: dict[str, Any] | None = None
) -> Path:
    manager.packs_dir.mkdir(parents=True, exist_ok=True)
    path = manager.packs_dir / f"{stem}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": stem,
                    "slots": [
                        {"index": 0, "text": "a knight", "negative": "", "loras": [["armor", 0.7]]}
                    ],
                    "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
                },
                "preset_data": PACK_SETTINGS if preset is None else preset,
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "g",
    )
    _write_pack(manager)
    job_service = RecordingJobService()
    controller = PipelineController(app_state=AppStateV2(), config_manager=manager)
    controller._job_service = job_service  # the JobService.submit_njrs boundary is the only fake
    compiles: list[int] = []
    original = PromptPackNormalizedJobBuilder.build_jobs

    def counting(self: Any, entries: Any, *args: Any, **kwargs: Any) -> Any:
        compiles.append(1)
        return original(self, entries, *args, **kwargs)

    monkeypatch.setattr(PromptPackNormalizedJobBuilder, "build_jobs", counting)
    return controller, manager, job_service, compiles


def _entry(snapshot: dict[str, Any] | None = None) -> PackJobEntry:
    return PackJobEntry(
        pack_id="hero",
        pack_name="hero",
        config_snapshot=snapshot or {},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
    )


def _preview(
    controller: PipelineController, snapshot: dict[str, Any] | None = None
) -> list[NormalizedJobRecord]:
    controller._app_state.job_draft.packs = [_entry(snapshot)]
    controller.refresh_preview_from_state()
    return list(controller._app_state.preview_jobs)


# --------------------------------------------------------------------------- precedence table


def test_precedence_is_defaults_then_pack_settings_then_job_snapshot(env) -> None:
    controller, manager, _svc, _ = env
    # A named preset in the folder is NOT a layer of the pack compile path.
    assert manager.save_preset(
        "default", {"txt2img": {"steps": 99, "model": "preset_model.safetensors"}}
    )

    [job] = _preview(controller, {"txt2img": {"steps": 40}})
    config = job.config
    defaults = manager.get_default_config()

    # snapshot > pack > defaults; the preset never appears.
    assert config["steps"] == 40  # job snapshot wins over pack (31)
    assert config["cfg_scale"] == 6.0  # pack wins over the code default
    assert config["model"] == "pack_model.safetensors"  # pack, not the preset
    assert (config["width"], config["height"]) == (832, 1216)
    assert config["sampler"] == "DPM++ 2M" and config["scheduler"] == "Karras"
    assert config["pipeline"]["image_format"] == "webp"
    assert config["pipeline"]["output_dir"] == "D:/pack_out"
    assert config["clip_skip"] == defaults["txt2img"]["clip_skip"]  # untouched default survives
    assert job.workload.images_per_prompt == 2
    assert job.output_plan.base_output_dir == "D:/pack_out"


def test_resolve_config_includes_a_named_preset_only_when_asked(env) -> None:
    _controller, manager, _svc, _ = env
    assert manager.save_preset("look", {"txt2img": {"steps": 77}})

    assert manager.resolve_config(pack_overrides=PACK_SETTINGS)["txt2img"]["steps"] == 31
    assert (
        manager.resolve_config(preset_name="look", pack_overrides=PACK_SETTINGS)["txt2img"]["steps"]
        == 31
    )
    assert manager.resolve_config(preset_name="look")["txt2img"]["steps"] == 77
    layered = manager.resolve_config(
        preset_name="look", pack_overrides=PACK_SETTINGS, runtime_params={"txt2img": {"steps": 5}}
    )
    assert layered["txt2img"]["steps"] == 5


def test_loading_a_preset_or_editing_overrides_never_persists_into_the_pack(env) -> None:
    controller, manager, _svc, _ = env
    before = (manager.packs_dir / "hero.json").read_bytes()
    assert manager.save_preset("look", {"txt2img": {"steps": 77}})

    [job] = _preview(controller, {"txt2img": {"steps": 5}})  # a temporary override

    assert job.config["steps"] == 5
    assert (manager.packs_dir / "hero.json").read_bytes() == before
    assert json.loads(before)["preset_data"]["txt2img"]["steps"] == 31


# --------------------------------------------------------------------------- effective settings view


def test_effective_view_is_derived_from_the_compiled_jobs_and_states_its_limits(env) -> None:
    controller, _manager, _svc, _ = env
    jobs = _preview(controller, {"txt2img": {"steps": 40}})

    view = project_effective_settings(jobs, EffectiveContext(override_pack_config=False))

    assert view.job_count == len(jobs) >= 1
    assert view.value_of("Source").startswith("PromptPack 'hero'")
    assert view.value_of("Model") == "pack_model.safetensors"
    assert view.value_of("Steps") == "40"
    assert view.value_of("CFG") == "6.0"
    assert view.value_of("Size") == "832 x 1216"
    assert view.value_of("Sampler") == "DPM++ 2M / Karras"
    assert view.value_of("Stages") == "txt2img"
    assert view.value_of("Images").startswith("2 per prompt")
    assert view.value_of("Output folder") == "D:/pack_out"
    assert view.value_of("Output format") == "webp"
    assert view.value_of("LoRAs") == "armor @ 0.7"
    text = view.as_text()
    assert "not proof of where a value came from" in text
    assert "PromptPacks added to the job keep their own saved settings" in text
    assert "The compiler reported no adjustments" in text


def test_effective_view_redacts_asset_names_in_hidden_mode_and_never_shows_prompts(env) -> None:
    controller, _manager, _svc, _ = env
    jobs = _preview(controller)

    text = project_effective_settings(jobs, EffectiveContext(visible=False)).as_text()

    assert "armor" not in text
    assert "1 LoRA(s) (names hidden)" in text
    assert "a knight" not in text and "<lora" not in text


def test_effective_view_has_an_explained_empty_state_instead_of_stale_values() -> None:
    assert project_effective_settings([]).as_text().startswith("No compiled preview yet")
    assert project_effective_settings(None).job_count == 0


def test_a_source_that_cannot_compile_is_not_shown_as_a_successful_preview(env) -> None:
    controller, manager, _svc, _ = env
    assert _preview(controller)  # a good preview exists first
    (manager.packs_dir / "hero.json").write_text(
        '{"schema_version": 1, "pack_data": {"na', encoding="utf-8"
    )

    jobs = _preview(controller, {"txt2img": {"steps": 41}})

    assert jobs == []
    assert project_effective_settings(jobs).job_count == 0  # no stale settings presented as current


# --------------------------------------------------------------------------- preview == submission


def test_submitted_jobs_are_exactly_the_accepted_preview_records(env) -> None:
    controller, manager, svc, compiles = env
    jobs = _preview(controller, {"txt2img": {"steps": 40}})
    accepted = [job.to_dict() for job in jobs]
    effective_before = project_effective_settings(jobs).as_text()
    compiled_by_preview = len(compiles)
    assert compiled_by_preview >= 1

    # Settings change on disk after Preview (an apply to the pack, a new default): the frozen jobs must not follow.
    assert manager.save_pack_config(
        "hero", {"txt2img": {"steps": 5, "model": "changed.safetensors"}}
    )
    manager.save_settings({"output_dir": "E:/new_default"})

    submitted_count = controller.submit_preview_jobs_to_queue(
        records=list(controller._app_state.preview_jobs)
    )

    assert submitted_count == len(jobs)
    assert len(compiles) == compiled_by_preview  # no extra compile at admission
    [batch] = svc.submitted
    assert [record.to_dict() for record in batch] == accepted
    assert all(any(record is job for job in jobs) for record in batch)  # the same frozen objects
    assert project_effective_settings(batch).as_text() == effective_before


def test_replay_snapshot_ignores_later_defaults_and_pack_settings(env) -> None:
    controller, manager, _svc, _ = env
    [job] = _preview(controller, {"txt2img": {"steps": 40}})
    snapshot = json.loads(json.dumps(job.to_dict()))

    assert manager.save_pack_config("hero", {"txt2img": {"steps": 5}})
    manager.save_settings({"output_dir": "E:/new_default"})
    [replayed] = controller.reconstruct_jobs_from_snapshot(snapshot)

    assert replayed.job_id == job.job_id
    assert replayed.config == job.config
    assert replayed.to_dict()["output_plan"] == snapshot["output_plan"]
    assert replayed.to_dict()["workload"]["config"] == snapshot["workload"]["config"]
    assert replayed.config["steps"] == 40
    assert replayed.output_plan.base_output_dir == "D:/pack_out"


# --------------------------------------------------------------------------- application defaults


def test_application_output_folder_is_the_base_layer_under_pack_and_job_values(env) -> None:
    controller, manager, svc, _ = env
    _write_pack(
        manager, "plain", preset={"txt2img": {"model": "m.safetensors"}}
    )  # saves no output folder
    assert manager.update_settings({"output_dir": "D:/app_default"}) is True

    plain = PackJobEntry(
        pack_id="plain",
        pack_name="plain",
        config_snapshot={},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
    )
    controller._app_state.job_draft.packs = [plain, _entry()]
    controller.refresh_preview_from_state()
    by_pack = {job.source.id: job for job in controller._app_state.preview_jobs}

    assert (
        by_pack["plain"].output_plan.base_output_dir == "D:/app_default"
    )  # no explicit value: the default
    assert (
        by_pack["hero"].output_plan.base_output_dir == "D:/pack_out"
    )  # saved pack settings keep their meaning

    controller._app_state.job_draft.packs = [plain]
    controller._app_state.job_draft.packs[0].config_snapshot = {
        "pipeline": {"output_dir": "F:/job_override"}
    }
    controller.refresh_preview_from_state()
    [job] = controller._app_state.preview_jobs
    assert (
        job.output_plan.base_output_dir == "F:/job_override"
    )  # explicit job value beats the default


def test_editing_the_application_default_never_changes_queued_jobs(env) -> None:
    controller, manager, svc, _ = env
    _write_pack(manager, "plain", preset={"txt2img": {"model": "m.safetensors"}})
    assert manager.update_settings({"output_dir": "D:/first"})
    controller._app_state.job_draft.packs = [
        PackJobEntry(
            pack_id="plain",
            pack_name="plain",
            config_snapshot={},
            stage_flags={"txt2img": True},
            randomizer_metadata={"enabled": False},
            pack_row_index=0,
        )
    ]
    controller.refresh_preview_from_state()
    controller.submit_preview_jobs_to_queue(records=list(controller._app_state.preview_jobs))
    queued = [record.to_dict() for record in svc.submitted[0]]

    assert manager.update_settings({"output_dir": "D:/second"})

    assert [record.to_dict() for record in svc.submitted[0]] == queued
    assert svc.submitted[0][0].output_plan.base_output_dir == "D:/first"
    controller.refresh_preview_from_state()
    assert (
        controller._app_state.preview_jobs[0].output_plan.base_output_dir == "D:/second"
    )  # only new jobs


def test_without_a_stored_default_the_compile_is_unchanged(env) -> None:
    controller, manager, _svc, _ = env
    _write_pack(manager, "plain", preset={"txt2img": {"model": "m.safetensors"}})
    assert not (manager.presets_dir / "settings.json").exists()
    config = manager.resolve_config(pack_overrides=manager.get_pack_config("plain"))
    assert "output_dir" not in config.get("pipeline", {})
