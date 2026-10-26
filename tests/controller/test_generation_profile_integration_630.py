"""PR-IMG-PROFILE-630: checkpoint -> profile -> PromptPack -> override -> stage snapshot -> Preview/NJR -> fake JobService.

Real ``ConfigManager`` + ``PipelineController`` + ``PromptPackNormalizedJobBuilder`` + the profile controller; the fakes are
the Base Generation panel (no Tk) and the ``JobService.submit_njrs`` boundary. No backend, runtime or GPU.
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
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.utils.config import ConfigManager
from tests.controller.test_generation_profile_controller_630 import (
    KLEIN,
    FakeHost,
    FakePanel,
    _compat,
)

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
    "pipeline": {"images_per_prompt": 1, "adetailer_enabled": True},
    "adetailer": {"enabled": True, "adetailer_checkpoint_model": "face.safetensors"},
}


class RecordingJobService:
    def __init__(self) -> None:
        self.submitted: list[list[NormalizedJobRecord]] = []

    def submit_njrs(self, records: list[NormalizedJobRecord], policy: Any) -> list[str]:
        self.submitted.append(list(records))
        return [record.job_id for record in records]


@pytest.fixture
def env(tmp_path: Path):
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "g",
    )
    manager.packs_dir.mkdir(parents=True, exist_ok=True)
    pack = manager.packs_dir / "hero.json"
    pack.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": "hero",
                    "slots": [{"index": 0, "text": "a knight", "negative": "", "loras": []}],
                    "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
                },
                "preset_data": PACK_SETTINGS,
            }
        ),
        encoding="utf-8",
    )
    job_service = RecordingJobService()
    controller = PipelineController(app_state=AppStateV2(), config_manager=manager)
    controller._job_service = job_service
    host = FakeHost(FakePanel(), tmp_path)
    return controller, manager, job_service, host, pack


def _snapshot_from_panel(panel: FakePanel) -> dict[str, Any]:
    """What 'override ON' puts in the job's stage snapshot: the working Base Generation values."""
    v = panel.values
    return {
        "txt2img": {
            "model": v["model"],
            "sampler_name": v["sampler"],
            "scheduler": v["scheduler"],
            "steps": v["steps"],
            "cfg_scale": v["cfg_scale"],
            "width": v["width"],
            "height": v["height"],
        }
    }


def _add_to_draft(
    controller: PipelineController, host: FakeHost, snapshot: dict[str, Any], flags: dict[str, bool]
) -> list[NormalizedJobRecord]:
    controller._app_state.job_draft.packs = [
        PackJobEntry(
            pack_id="hero",
            pack_name="hero",
            config_snapshot=snapshot,
            stage_flags=flags,
            randomizer_metadata={"enabled": False},
            pack_row_index=0,
        )
    ]
    host.app_state.job_draft.packs = list(controller._app_state.job_draft.packs)
    host.profiles.note_draft_built()
    controller.refresh_preview_from_state()
    return list(controller._app_state.preview_jobs)


def test_checkpoint_to_profile_to_pack_override_snapshot_preview_and_submission(env) -> None:
    controller, manager, svc, host, pack = env
    pack_bytes = pack.read_bytes()

    # 1. Checkpoint selection applies the exact model's preferred profile to the working settings only.
    host.panel.values["model"] = KLEIN
    plan = host.profiles.on_model_chosen(KLEIN)
    assert plan is not None and plan.profile.profile_id.startswith("research-flux2_klein")
    assert (
        not svc.submitted and not controller._app_state.preview_jobs
    )  # nothing dispatched, nothing rewritten

    # 2. Override ON: the working stage snapshot (carrying the profile's values) is what the draft entry compiles from.
    host.override_pack_config_enabled = True
    flags = {"txt2img": True, "adetailer": False}
    [job] = _add_to_draft(controller, host, _snapshot_from_panel(host.panel), flags)
    assert job.config["model"] == KLEIN
    assert (job.config["width"], job.config["height"]) == (
        host.panel.values["width"],
        host.panel.values["height"],
    )
    assert [stage.stage_type for stage in job.stage_chain if stage.enabled] == ["txt2img"]
    adetailer = next(stage for stage in job.stage_chain if stage.stage_type == "adetailer")
    assert (
        adetailer.enabled is False
    )  # the profile never enabled a stage, and the operator's membership is final

    # 3. Preview Effective Settings tells the truth about model, profile, override, disabled stages and adjustments.
    context = EffectiveContext(
        override_pack_config=True,
        profile_lines=host.profiles.effective_lines(),
        draft_notices=host.profiles.draft_notices(),
    )
    view = project_effective_settings([job], context)
    text = view.as_text()
    assert view.value_of("Model") == KLEIN
    assert view.value_of("Stages") == "txt2img" and "adetailer" in view.value_of("Stages off")
    assert "Research - FLUX.2 Klein" in text and "Override is ON" in text
    assert "Preview may be out of date" not in text

    # 4. The operator turns ADetailer on afterwards: the existing Preview says it is stale instead of looking current.
    host.flags["adetailer"] = True
    stale = project_effective_settings(
        [job], EffectiveContext(draft_notices=host.profiles.draft_notices())
    ).as_text()
    assert "Preview may be out of date" in stale and "adetailer is on now" in stale

    # 5. Submission sends exactly the previewed frozen records; the profile layer had no part in it.
    accepted = [record.to_dict() for record in controller._app_state.preview_jobs]
    count = controller.submit_preview_jobs_to_queue(
        records=list(controller._app_state.preview_jobs)
    )
    assert count == 1 and [r.to_dict() for r in svc.submitted[0]] == accepted
    assert pack.read_bytes() == pack_bytes  # the saved PromptPack is untouched
    assert json.loads(pack_bytes)["preset_data"]["txt2img"]["model"] == "pack_model.safetensors"


def test_override_off_keeps_the_pack_settings_and_says_the_profile_only_shaped_the_working_settings(
    env,
) -> None:
    controller, _manager, _svc, host, _pack = env
    host.panel.values["model"] = KLEIN
    host.profiles.on_model_chosen(KLEIN)
    host.override_pack_config_enabled = False

    [job] = _add_to_draft(controller, host, {}, {"txt2img": True, "adetailer": True})

    assert job.config["model"] == "pack_model.safetensors"  # PromptPack precedence preserved
    assert job.config["steps"] == 31
    assert (
        next(stage for stage in job.stage_chain if stage.stage_type == "adetailer").enabled is True
    )
    lines = "\n".join(host.profiles.effective_lines())
    assert "Override is OFF" in lines and "PromptPacks keep their own saved settings" in lines


def test_changing_the_checkpoint_after_adding_packs_does_not_rewrite_the_draft_or_the_queue(
    env,
) -> None:
    controller, _manager, svc, host, _pack = env
    host.override_pack_config_enabled = True
    host.panel.values["model"] = KLEIN
    host.profiles.on_model_chosen(KLEIN)
    [job] = _add_to_draft(controller, host, _snapshot_from_panel(host.panel), {"txt2img": True})
    before = job.to_dict()

    host.panel.values["model"] = "other.safetensors"
    host.profiles.on_model_chosen("other.safetensors")

    assert [record.to_dict() for record in controller._app_state.preview_jobs] == [
        before
    ]  # frozen, not recompiled
    assert not svc.submitted
    notices = host.profiles.draft_notices()
    assert any("model or generation profile changed" in notice for notice in notices)


def test_explicit_published_learning_profile_reaches_next_sqlite_njr(env, tmp_path):
    """Compose the existing publication, selection, compiler and real admission owners."""
    from src.controller.generation_profile_controller import GenerationProfileController
    from src.controller.job_service import JobService
    from src.generation_profiles.service import GenerationProfileService
    from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from tests.controller.test_job_service_unit import FakeRunner
    from tests.learning_v2.test_profile_publication_660 import make_publication, records

    controller, _manager, _service, host, pack = env
    controller._prompt_pack_builder = PromptPackNormalizedJobBuilder(
        config_manager=_manager,
        job_builder=controller._job_builder,
        packs_dir=_manager.packs_dir,
        model_family_lookup=lambda name: _compat("sdxl") if name == "test.safetensors" else None,
    )
    pack_bytes = pack.read_bytes()
    publication = make_publication(tmp_path)
    rows = records(publication)
    proposed = publication.evaluate(rows, "test.safetensors", experiment_id="experiment-1")
    published = publication.publish(
        proposed, rows, "test.safetensors", name="Qualified settings", confirmed=True
    )
    profile_bytes = next(publication.store.root.glob("profiles/learning/*/r0001.json")).read_bytes()
    host.profiles = GenerationProfileController(
        host, GenerationProfileService(publication.store, publication.resolver)
    )
    host.panel.values.update(
        model="test.safetensors",
        sampler="Euler",
        scheduler="Normal",
        steps=12,
        width=1024,
        height=1024,
        vae="",
    )
    host.override_pack_config_enabled = True
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    controller._job_service = JobService(
        JobQueue(repository=repository), runner=FakeRunner(), require_normalized_records=True
    )

    def preview_and_admit():
        snapshot = _snapshot_from_panel(host.panel)
        snapshot["txt2img"].update(vae="", seed=4242)
        [preview] = _add_to_draft(controller, host, snapshot, {"txt2img": True})
        # Repository snapshots use the NJR's canonical read/write representation
        # (for example an empty stage VAE becomes None); compare every field.
        expected = NormalizedJobRecord.from_dict(preview.to_dict()).to_dict()
        assert controller.enqueue_draft_jobs() == 1
        assert repository.get_job(preview.job_id).snapshot["normalized_job"] == preview.to_dict()
        stored = repository.get_job_model(preview.job_id)._normalized_record
        assert stored.to_dict() == expected
        assert stored.provenance.metadata["prompt_adaptation"]["family"] == "sdxl"
        effective = project_effective_settings(
            [stored], EffectiveContext(override_pack_config=True)
        )
        assert effective.value_of("Model") == "test.safetensors"
        assert [stage.stage_type for stage in stored.stage_chain if stage.enabled] == ["txt2img"]
        assert stored.config["seed"] == 4242
        return stored

    previous = preview_and_admit()
    previous_bytes = previous.to_dict()
    assert previous.config["steps"] == 12
    plan = host.profiles.on_profile_selected(published.ref)
    assert plan.changes == {"steps": 30}
    assert host.profiles.state().selected == published.ref
    following = preview_and_admit()
    assert following.config["steps"] == 30
    assert following.job_id != previous.job_id
    assert repository.get_job_model(previous.job_id)._normalized_record.to_dict() == previous_bytes
    assert len(repository.list_job_models()) == 2
    assert (
        next(publication.store.root.glob("profiles/learning/*/r0001.json")).read_bytes()
        == profile_bytes
    )
    assert pack.read_bytes() == pack_bytes
    assert publication.store.favorite_for(published.model.key) is None
    assert publication.store.load_startup_document() is None
