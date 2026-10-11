"""Real Tk preview, production PromptPack compiler and transient projections; no runtime/GPU."""

from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.controller.app_controller_services.runtime_projection_coordinator import (
    RuntimeProjectionCoordinator,
)
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_projection_sink import AppStateProjectionSink
from src.gui.app_state_v2 import AppStateV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.controller.test_background_task_coordinator_v2 import _ThreadRegistryStub
from tests.helpers.njr_factory import make_pipeline_njr
from tests.pipeline.test_zimage_compile_policy import _pack


@pytest.fixture
def preview(tk_root, tmp_path, monkeypatch):
    builder, template, path, original = _pack(tmp_path, monkeypatch)
    state = AppStateV2()
    pipeline = object.__new__(PipelineController)
    pipeline._app_state = state
    pipeline._app_controller = None
    pipeline._app_state_preview_updates_managed_externally = True
    pipeline._get_prompt_pack_builder = lambda: builder
    app = object.__new__(AppController)
    app.app_state, app.pipeline_controller = state, pipeline
    app._append_log = lambda *_: None
    app._clear_active_operation = lambda *_: None
    coordinator = RuntimeProjectionCoordinator(
        sink=AppStateProjectionSink(state), background_tasks=BackgroundTaskCoordinator(run_inline=True),
        build_queue_projection=lambda: ([], []), load_history_entries=lambda _: [],
        summarize_running_job=lambda _: None,
    )
    app._runtime_projection_coordinator = coordinator
    panel = PreviewPanelV2(tk_root, controller=app, app_state=state)
    yield SimpleNamespace(state=state, pipeline=pipeline, app=app, panel=panel,
                          builder=builder, template=template, path=path, original=original)
    assert path.read_bytes() == original
    panel.destroy()


def add_entries(preview, *, width=1024, count=6, stage=None):
    entries = []
    for seed in range(count):
        entry = deepcopy(preview.template)
        entry.config_snapshot = {
            "txt2img": {**preview.builder._config_manager._config["txt2img"], "width": width, "seed": seed},
        }
        if stage:
            entry.stage_flags[stage] = True
        entries.append(entry)
    preview.state.add_packs_to_job_draft(entries)
    return entries


def refresh(preview):
    preview.app._refresh_preview_from_state_async()
    preview.panel.update_from_job_draft(preview.state.job_draft)
    preview.panel.update_from_app_state()


@pytest.mark.gui
def test_six_visible_draft_summaries_without_njrs_can_always_clear(preview):
    add_entries(preview, width=576)
    refresh(preview)
    assert len(preview.panel._job_summaries) == 6
    assert preview.state.preview_jobs == []
    assert all(item.job_id.startswith("draft-") for item in preview.panel._job_summaries)
    assert preview.panel.add_to_queue_button.instate(["disabled"])
    assert preview.panel.clear_draft_button.instate(["!disabled"])


@pytest.mark.gui
def test_invalid_geometry_explains_failure_then_clear_recovers(preview):
    add_entries(preview, width=576)
    refresh(preview)
    reason = preview.panel.preview_error_label.cget("text")
    assert "576" in reason and "1024" in reason and "Clear Draft" in reason
    preview.panel._on_clear_draft()
    assert not preview.state.job_draft.packs and not preview.state.preview_jobs
    assert not preview.panel._job_summaries
    assert preview.panel.add_to_queue_button.instate(["disabled"])
    assert preview.panel.clear_draft_button.instate(["disabled"])
    assert preview.panel.preview_error_label.cget("text") == ""
    add_entries(preview, count=1)
    refresh(preview)
    assert preview.panel.add_to_queue_button.instate(["!disabled"])


@pytest.mark.gui
def test_valid_zimage_completion_enables_queue_without_draft_rerender(preview):
    add_entries(preview)
    preview.panel.update_from_job_draft(preview.state.job_draft)
    assert preview.panel.add_to_queue_button.instate(["disabled"])
    preview.app._refresh_preview_from_state_async()
    assert len(preview.state.preview_jobs) == 6
    assert preview.panel.add_to_queue_button.instate(["!disabled"])
    assert preview.panel.preview_error_label.cget("text") == ""


@pytest.mark.gui
@pytest.mark.parametrize("model", ["sdxl.safetensors", "other.safetensors", "flux-2-klein-4b-fp8.safetensors"])
def test_model_switch_and_new_pack_can_recover_current_preview(preview, model):
    entries = add_entries(preview, width=576, count=1)
    refresh(preview)
    assert preview.state.preview_jobs == []
    entry = entries[0]
    entry.config_snapshot["txt2img"].update(model=model, width=512, height=512, steps=20,
                                             cfg_scale=7, scheduler="Normal")
    entry.config_snapshot["backend_options"] = {"image": {"backend_id": "forge_webui"}}
    if "klein" in model:
        entry.config_snapshot["txt2img"].update(width=768, height=1024, steps=4,
                                               cfg_scale=1, scheduler="Beta")
    preview.app._refresh_preview_from_state_async()
    assert len(preview.state.preview_jobs) == 1
    assert preview.panel.add_to_queue_button.instate(["!disabled"])
    preview.state.add_packs_to_job_draft([deepcopy(entry)])
    assert preview.panel.add_to_queue_button.instate(["disabled"])
    preview.app._refresh_preview_from_state_async()
    assert len(preview.state.preview_jobs) == 2
    assert preview.panel.add_to_queue_button.instate(["!disabled"])


@pytest.mark.gui
def test_stale_result_already_waiting_for_ui_cannot_restore_cleared_draft(preview):
    pending = []
    preview.app._runtime_projection_coordinator._background_tasks._dispatcher = pending.append
    add_entries(preview, count=1)
    preview.app._refresh_preview_from_state_async()
    assert pending and not preview.state.preview_jobs
    preview.panel._on_clear_draft()
    while pending:
        pending.pop(0)()
    assert not preview.state.preview_jobs and not preview.state.job_draft.packs
    assert not preview.panel._job_summaries
    assert preview.panel.add_to_queue_button.instate(["disabled"])


@pytest.mark.gui
def test_clear_preview_never_changes_queue_history_or_running_state(preview):
    queued, running, historical = object(), object(), object()
    preview.state.queue_jobs = [queued]
    preview.state.queue_items = ["queued"]
    preview.state.history_items = [historical]
    preview.state.running_job = running
    add_entries(preview, width=576)
    refresh(preview)
    preview.panel._on_clear_draft()
    assert preview.state.queue_jobs == [queued] and preview.state.queue_items == ["queued"]
    assert preview.state.history_items == [historical] and preview.state.running_job is running


@pytest.mark.gui
def test_clear_with_managed_pipeline_tab_subscriber_does_not_recompile_retained_prompt(preview):
    fallback_calls = []
    preview.state.prompt = "retained operator prompt"
    preview.pipeline._build_normalized_jobs_from_state = lambda **_: (
        fallback_calls.append(True) or [make_pipeline_njr()]
    )
    tab = SimpleNamespace(
        app_state=preview.state, app_controller=preview.app, pipeline_controller=preview.pipeline,
        _mark_hot_surface_dirty=lambda *_: None, _measure_callback=lambda _, callback: callback(),
    )
    preview.app.request_preview_refresh = preview.app._refresh_preview_from_state_async
    preview.state.subscribe("job_draft", lambda: PipelineTabFrame._on_job_draft_changed(tab))
    add_entries(preview, count=1)
    assert preview.state.preview_jobs
    preview.panel._on_clear_draft()
    assert not fallback_calls
    assert not preview.state.preview_jobs and not preview.panel._job_summaries
    assert preview.state.prompt == "retained operator prompt"
    assert preview.panel.clear_draft_button.instate(["disabled"])


@pytest.mark.gui
def test_unsupported_stage_explains_failure_and_can_be_cleared(preview):
    add_entries(preview, stage="adetailer")
    refresh(preview)
    assert not preview.state.preview_jobs
    assert "only the txt2img stage is supported" in preview.panel.preview_error_label.cget("text")
    assert preview.panel.clear_draft_button.instate(["!disabled"])
    preview.panel._on_clear_draft()
    assert not preview.state.job_draft.packs


@pytest.mark.gui
def test_pending_worker_cannot_restore_cleared_preview(preview):
    started, release = Event(), Event()
    pending, registry = [], _ThreadRegistryStub()
    coordinator = preview.app._runtime_projection_coordinator
    coordinator._background_tasks = BackgroundTaskCoordinator(
        dispatcher=pending.append, thread_registry=registry,
    )
    original = preview.pipeline.get_preview_jobs_for_request

    def build(request):
        started.set()
        assert release.wait(2)
        return original(request)

    preview.pipeline.get_preview_jobs_for_request = build
    add_entries(preview, count=1)
    preview.app._refresh_preview_from_state_async()
    try:
        assert started.wait(2)
        preview.panel._on_clear_draft()
    finally:
        release.set()
        for thread in registry.threads:
            thread.join(2)
            assert not thread.is_alive()
    while pending:
        pending.pop(0)()
    assert not preview.state.preview_jobs and not preview.panel._job_summaries


@pytest.mark.gui
def test_projection_awaiting_second_ui_dispatch_is_rejected_after_clear(preview):
    pending = []
    preview.app._runtime_projection_coordinator._sink = AppStateProjectionSink(
        preview.state, dispatcher=pending.append,
    )
    add_entries(preview, count=1)
    preview.app._refresh_preview_from_state_async()
    assert pending
    preview.panel._on_clear_draft()
    while pending:
        pending.pop(0)()
    assert not preview.state.preview_jobs and not preview.panel._job_summaries


def test_preview_request_captures_config_before_draft_changes(preview):
    entries = add_entries(preview, count=1)
    request = preview.pipeline.build_preview_request()
    entries[0].config_snapshot["txt2img"]["width"] = 576
    assert request.pack_entries[0].config_snapshot["txt2img"]["width"] == 1024


@pytest.mark.gui
def test_explicit_manual_draft_preserves_state_compilation(preview):
    record = make_pipeline_njr()
    preview.pipeline._build_normalized_jobs_from_state = lambda **_: [record]
    preview.state.add_job_draft_part("manual operator prompt", "")
    preview.app._refresh_preview_from_state_async()
    assert preview.state.preview_jobs == [record]
    assert preview.panel.add_to_queue_button.instate(["!disabled"])


@pytest.mark.gui
def test_empty_pack_compilation_never_substitutes_unrelated_current_prompt(preview):
    add_entries(preview, count=1)
    preview.pipeline._build_njrs_from_pack_bundle = lambda _: []
    preview.pipeline._build_normalized_jobs_from_state = lambda **_: [make_pipeline_njr()]
    preview.app._refresh_preview_from_state_async()
    assert not preview.state.preview_jobs
    assert preview.panel.add_to_queue_button.instate(["disabled"])
    assert preview.panel.clear_draft_button.instate(["!disabled"])


@pytest.mark.gui
def test_six_promptpack_jobs_queue_once_and_clear_preserves_sqlite(preview, tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(queue)
    assert not service.auto_run_enabled
    preview.pipeline._job_service = service
    preview.pipeline._last_run_config = None
    preview.pipeline.can_enqueue_learning_jobs = lambda _: (True, "")
    preview.pipeline._is_queue_submission_blocked = lambda: False
    preview.pipeline._sort_jobs_by_model = lambda records: records
    preview.app._ensure_run_mode_default = lambda _: None
    preview.app._prepare_queue_run_config = lambda: {"run_mode": "queue"}
    preview.app._spawn_tracked_thread = lambda *, target, args, **_: target(*args)
    preview.app._ui_dispatch = lambda callback: callback()
    add_entries(preview)
    refresh(preview)
    expected = [job.job_id for job in preview.state.preview_jobs]
    assert len(set(expected)) == 6
    preview.panel._on_add_to_queue()
    assert {job.job_id for job in queue.list_jobs()} == set(expected)
    assert not preview.state.preview_jobs and not preview.state.job_draft.packs
    preview.panel._on_add_to_queue()
    assert len(repository.list_jobs()) == 6
    before = [repository.get_job(job_id) for job_id in expected]
    add_entries(preview, width=576)
    refresh(preview)
    preview.panel._on_clear_draft()
    assert [repository.get_job(job_id) for job_id in expected] == before
    assert len(queue.list_jobs()) == 6
