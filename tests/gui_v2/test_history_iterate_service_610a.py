"""PR-HISTORY-610A: Iterate from History hand-offs into the real Review tab and the real Pipeline draft state.

Real ``ReviewTabFrame`` (Tk), real ``prepare_review_batch``, real ``AppStateV2`` and temporary SQLite. A fake history
service supplies the persisted record. No GPU, WebUI, model or runtime start; nothing here may queue a job.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from PIL import Image

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.controller.review_batch_service import prepare_review_batch
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui.controllers.history_iterate_service import HistoryIterateRefused, HistoryIterateService
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.image_metadata import build_contract_kv, write_image_metadata
from tests.gui_v2.test_history_iterate_model_610a import _entry, _result
from tests.pipeline.test_history_variation_compiler_610a import _source

JOB_ID = "parent-job"


def _png(path, *, job_id: str | None = JOB_ID, color=(10, 20, 30)) -> str:
    Image.new("RGB", (32, 32), color).save(path)
    if job_id:
        payload = {
            "generation": {"model": "sdxlBase.safetensors"},
            "stage_manifest": {
                "stage": "txt2img",
                "final_prompt": "a red fox",
                "config": {"steps": 30, "cfg_scale": 6.5},
            },
        }
        assert write_image_metadata(
            path, build_contract_kv(payload, job_id=job_id, run_id="synthetic", stage="txt2img")
        )
    return str(path)


class Env:
    def __init__(self, tk_root, tmp_path, monkeypatch) -> None:
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.service = JobService(JobQueue(repository=self.repository))
        monkeypatch.setattr(
            self.service.runner, "start", lambda: pytest.fail("runtime start prohibited")
        )
        self.app = object.__new__(AppController)
        self.app.job_service = self.service
        self.app._append_log = lambda _: None
        self.app._build_reprocess_config = lambda _: {
            "model": "sdxl-fallback.safetensors",
            "steps": 20,
            "cfg_scale": 7,
            "img2img": {"denoising_strength": 0.3},
        }
        self.tab = ReviewTabFrame(tk_root, app_controller=self.app)
        self.app_state = AppStateV2()
        self.image = _png(tmp_path / "recorded.png")
        self.njr = _source(job_id=JOB_ID)
        self.entry = _entry(self.njr, result=_result(self.image))
        history = SimpleNamespace(
            get_history_record=lambda job_id: self.entry if job_id == JOB_ID else None
        )
        self.app.main_window = SimpleNamespace(
            review_tab=self.tab, center_notebook=None, pipeline_tab=None
        )
        self.app.app_state = self.app_state
        self.app.pipeline_controller = SimpleNamespace(get_job_history_service=lambda: history)
        self.iterate = HistoryIterateService(self.app)

    def prepare(self):
        meta = self.tab._active_handoff.source_metadata_by_path
        return prepare_review_batch(
            self.app,
            image_paths=[self.image],
            stages=["img2img"],
            fallback_config=self.app._build_reprocess_config(["img2img"]),
            source_metadata_by_image=meta,
        )


@pytest.fixture
def env(tk_root, tmp_path, monkeypatch):
    environment = Env(tk_root, tmp_path, monkeypatch)
    yield environment
    environment.tab.destroy()


def test_edit_in_review_loads_the_exact_image_with_no_stages_and_queues_nothing(env):
    outcome = env.iterate.edit_in_review(JOB_ID)
    assert outcome.done
    assert [str(p) for p in env.tab.selected_images] == [env.image]
    assert not any(
        v.get()
        for v in (env.tab.stage_img2img_var, env.tab.stage_adetailer_var, env.tab.stage_upscale_var)
    )
    claim = env.tab._active_handoff.source_metadata_by_path[env.image]
    assert claim["source_job_id"] == JOB_ID
    assert (
        claim["source_artifact_id"]
        == "sha256:" + hashlib.sha256(open(env.image, "rb").read()).hexdigest()
    )
    assert env.repository.list_jobs() == []


def test_review_job_compiled_from_the_handoff_records_the_history_job_as_parent(env):
    env.iterate.edit_in_review(JOB_ID)
    preview = env.prepare()
    assert not preview.blocked and len(preview.jobs) == 1
    job = preview.jobs[0]
    assert job.source.parent_job_id == JOB_ID
    assert (
        job.source.parent_artifact_id
        == env.tab._active_handoff.source_metadata_by_path[env.image]["source_artifact_id"]
    )
    assert list(job.input_image_paths) == [env.image]
    assert env.repository.list_jobs() == []  # previewing never queues


def test_contradicting_embedded_identity_is_refused_not_reattributed(env, tmp_path):
    env.iterate.edit_in_review(JOB_ID)
    _png(
        tmp_path / "recorded.png", job_id="some-other-job"
    )  # same bytes path, different embedded identity
    preview = env.prepare()
    assert preview.blocked and not preview.jobs
    assert "contradicts" in preview.blocked[0].error


def test_an_image_changed_after_the_handoff_is_refused(env, tmp_path):
    env.iterate.edit_in_review(JOB_ID)
    _png(tmp_path / "recorded.png", color=(200, 0, 0))  # same job id embedded, different pixels
    preview = env.prepare()
    assert preview.blocked and "changed since" in preview.blocked[0].error


def test_deleted_or_replaced_record_refuses_both_choices_and_loads_nothing(env, tmp_path):
    import os

    os.remove(env.image)
    for call in (env.iterate.edit_in_review, env.iterate.regenerate_in_pipeline):
        with pytest.raises(HistoryIterateRefused, match="missing"):
            call(JOB_ID)
    with pytest.raises(HistoryIterateRefused, match="no longer available"):
        env.iterate.edit_in_review("unknown-job")
    assert not env.tab.selected_images and env.app_state.job_draft.history_variation is None


def test_review_replace_guard_keeps_unsent_work_unless_confirmed(env, tmp_path):
    other = _png(tmp_path / "other.png", job_id="other")
    env.tab._set_selected_images([__import__("pathlib").Path(other)])
    asked = []
    declined = env.iterate.edit_in_review(
        JOB_ID, lambda title, message: asked.append(title) or False
    )
    assert not declined.done and asked and [str(p) for p in env.tab.selected_images] == [other]
    accepted = env.iterate.edit_in_review(JOB_ID, lambda *_: True)
    assert accepted.done and [str(p) for p in env.tab.selected_images] == [env.image]


def test_regenerate_starts_an_unsent_variation_with_true_lineage_and_queues_nothing(env):
    outcome = env.iterate.regenerate_in_pipeline(JOB_ID)
    assert outcome.done
    draft = env.app_state.job_draft.history_variation
    assert draft.source_job_id == JOB_ID and draft.edits == draft.baseline
    assert (
        draft.parent_artifact_id
        == "sha256:" + hashlib.sha256(open(env.image, "rb").read()).hexdigest()
    )
    assert env.app_state.preview_jobs == [] and env.repository.list_jobs() == []


def test_regenerate_replace_guard_preserves_an_unsent_pack_draft_unless_confirmed(env):
    env.app_state.job_draft.packs.append(
        PackJobEntry(pack_id="p", pack_name="Pack", config_snapshot={})
    )
    declined = env.iterate.regenerate_in_pipeline(JOB_ID, lambda *_: False)
    assert not declined.done
    assert env.app_state.job_draft.history_variation is None and env.app_state.job_draft.packs
    accepted = env.iterate.regenerate_in_pipeline(JOB_ID, lambda *_: True)
    assert accepted.done and env.app_state.job_draft.history_variation is not None
    assert not env.app_state.job_draft.packs


def test_a_variant_recipe_still_offers_edit_image_but_refuses_regenerate(
    tmp_path, tk_root, monkeypatch
):
    environment = Env(tk_root, tmp_path, monkeypatch)
    try:
        environment.entry = _entry(
            _source(job_id=JOB_ID, matrix_slot_values={"hair": "red"}),
            result=_result(environment.image),
        )
        assessment = environment.iterate.assess(JOB_ID)
        assert assessment.review.supported and not assessment.pipeline.supported
        with pytest.raises(HistoryIterateRefused, match="Matrix"):
            environment.iterate.regenerate_in_pipeline(JOB_ID)
        assert environment.iterate.edit_in_review(JOB_ID).done
    finally:
        environment.tab.destroy()
