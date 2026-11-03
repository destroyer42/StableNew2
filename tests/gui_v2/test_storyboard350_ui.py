"""Persistent sequence authoring through the real Tk panel and production admission, with fake execution."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.app_state_v2 import AppStateV2
from src.gui.view_contracts.edit_work_runner import EditWorkRunner
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.video.sequence_shots import ShotDraft
from src.video.storyboard_store import StoryboardStore
from tests.helpers.make_video_313 import TI2V_ID, make_app, make_image

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.gui.view_contracts.edit_work_runner.coordinator_factory",
        lambda _widget: BackgroundTaskCoordinator(run_inline=True),
    )
    app, controller, service = make_app(tmp_path)
    state = AppStateV2()
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=state)
    tab.workflow_var.set(TI2V_ID)
    tab._on_workflow_id_changed()
    tab.source_image_var.set(make_image(tmp_path / "source.png", (480, 832)))
    tab.prompt_text.insert("1.0", "waves")
    panel = tab.sequence_panel
    panel.store = StoryboardStore(tmp_path / "storyboards")
    yield SimpleNamespace(
        panel=panel,
        tab=tab,
        app=app,
        controller=controller,
        service=service,
        root=tk_root,
        tmp=tmp_path,
        state=state,
    )
    tab.destroy()


def test_save_restart_open_reorder_edit_and_duplicate(editor, monkeypatch):
    panel = editor.panel
    panel._rows[0].prompt_var.set("first")
    row = panel._rows[1]
    row.prompt_var.set("second")
    row.seed_var.set("42")
    row.shot_label_var.set("turn")
    row.keyframe_var.set(make_image(editor.tmp / "anchor.png", (480, 832), "red"))
    panel._select_length(row, 21)
    panel._save_storyboard()
    assert panel.dirty_var.get().startswith("Saved") and editor.service.calls == []
    saved = panel.storyboard.draft
    assert saved.revision == 1 and saved.source_sha256 and saved.shots[1].keyframe_sha256
    panel._move_row(row, -1)
    moved = panel.shots()
    assert moved == list(reversed(saved.shots))
    assert panel.dirty_var.get() == "Unsaved changes"
    panel._on_queue()
    assert "unused keyframe" in panel.status_var.get() and editor.service.calls == []
    assert panel.load_storyboard(
        StoryboardStore(panel.store.root).load(saved.storyboard_id), confirm=False
    )
    assert panel.shots() == list(saved.shots) and panel.dirty_var.get().startswith("Saved")
    panel._duplicate_row(panel._rows[1])
    assert panel.shots()[1].shot_id != panel.shots()[2].shot_id
    assert replace(panel.shots()[2], shot_id=panel.shots()[1].shot_id) == panel.shots()[1]
    panel._remove_row(panel._rows[2])
    panel._save_storyboard(as_copy=True)
    copied = panel.storyboard.draft
    assert copied.storyboard_id != saved.storyboard_id and copied.revision == 1
    assert panel.store.load(saved.storyboard_id) == saved
    assert panel.dirty_var.get().startswith("Saved")


def test_preview_only_projects_intent_and_mismatch_requires_accept(editor, monkeypatch):
    panel = editor.panel
    panel._save_storyboard()
    saved_hash = panel.storyboard.draft.source_sha256
    panel._preview_storyboard()
    assert "Authoring summary (not a frozen plan)" in panel.status_var.get()
    assert "random" in panel.status_var.get() and editor.service.calls == []
    make_image(editor.tmp / "source.png", (480, 832), "green")
    panel._preview_storyboard()
    assert "SHA-256 mismatch" in panel.status_var.get()
    assert panel.storyboard.draft.source_sha256 == saved_hash
    panel._on_queue()
    assert editor.service.calls == []
    monkeypatch.setattr(
        "src.gui.views.storyboard_panel_actions.messagebox.askyesno", lambda *_a, **_k: True
    )
    panel._accept_media()
    assert panel.storyboard.draft.source_sha256 != saved_hash
    assert panel.dirty_var.get() == "Unsaved changes"
    panel._on_queue()
    assert len(editor.service.calls) == 1


def test_workflow_change_preserves_lengths_and_pinned_version_does_not_fallback(editor):
    panel = editor.panel
    shot = ShotDraft(prompt="short", frame_count=21, seed="5")
    draft = replace(
        panel._capture_storyboard(),
        workflow_version="1.2.0",
        shots=(shot, ShotDraft(frame_count=17)),
    )
    panel.load_storyboard(draft, confirm=False)
    assert panel._capture_storyboard().workflow_version == "1.2.0"
    assert [s.frame_count for s in panel.shots()] == [21, 17]
    panel._preview_storyboard()
    assert "1.2.0" in panel.status_var.get()
    panel._use_selected_workflow()
    assert panel._capture_storyboard().workflow_version == "1.3.0"
    assert [s.frame_count for s in panel.shots()] == [21, 17]
    editor.tab._apply_frame_count_choices({}, True)
    assert [s.frame_count for s in panel.shots()] == [21, 17]
    assert str(panel.queue_button.cget("state")) == "disabled"


def test_unsaved_form_edit_and_content_visibility_do_not_lose_draft(editor):
    panel = editor.panel
    panel._save_storyboard()
    saved = panel.storyboard.draft
    editor.tab.prompt_text.insert("end", " changed")
    panel._changed()
    assert panel.dirty_var.get() == "Unsaved changes"
    editor.state.set_content_visibility_mode("sfw")
    editor.tab.on_content_visibility_mode_changed("sfw")
    assert panel.shots() == list(saved.shots)
    assert panel.store.load(saved.storyboard_id) == saved and editor.service.calls == []


def test_worker_delivers_through_dispatcher_and_drops_after_disposal():
    dispatched = []
    results = []
    coordinator = BackgroundTaskCoordinator(run_inline=True, dispatcher=dispatched.append)
    runner = EditWorkRunner(coordinator, is_alive=lambda: True)
    runner.submit("draft", lambda: "value", on_result=results.append)
    assert results == []
    for callback in dispatched:
        callback()
    assert results == ["value"]
    dispatched.clear()
    runner.submit("draft", lambda: "late", on_result=results.append)
    runner.close()
    for callback in dispatched:
        callback()
    assert results == ["value"]


def test_history_action_rereads_repository_and_opens_a_new_editable_draft(editor, monkeypatch):
    from src.gui.job_history_panel_v2 import JobHistoryPanelV2
    from src.queue.job_model import Job
    from src.queue.job_repository import JobRepository
    from src.video.sequence_shots import build_sequence_intent

    repository = JobRepository(editor.tmp / "history.sqlite")
    history = None
    try:
        source, form = editor.panel._read_form()
        built = editor.controller.build_sequence_job(
            source_image_path=source,
            form_data=form,
            sequence_intent=build_sequence_intent(editor.panel.shots()),
        )
        job = Job(job_id=built.njr.job_id)
        job._normalized_record = built.njr
        repository.record_job_submission(job)
        entry = repository.list_recent_jobs(limit=1)[0]
        editor.service.history_store = repository
        selected = []
        editor.app.main_window = SimpleNamespace(
            video_workflow_tab=editor.tab, center_notebook=SimpleNamespace(select=selected.append)
        )
        monkeypatch.setattr(
            "src.gui.views.storyboard_panel_actions.messagebox.askyesno", lambda *_a, **_k: True
        )
        history = JobHistoryPanelV2(editor.root, controller=editor.app, app_state=editor.state)
        editor.state.set_history_items([entry])
        editor.root.update_idletasks()
        item = history.history_tree.get_children()[0]
        history.history_tree.selection_set(item)
        history.history_tree.event_generate("<<TreeviewSelect>>")
        editor.root.update_idletasks()
        assert str(history.storyboard_sequence_btn.cget("state")) == "normal"
        old_id = editor.panel.storyboard.draft.storyboard_id
        history.storyboard_sequence_btn.invoke()
        draft = editor.panel.storyboard.draft
        assert draft.storyboard_id != old_id and draft.origin_job_id == job.job_id
        assert draft.revision == 0 and editor.panel.dirty_var.get() == "Unsaved changes"
        assert "nothing queued or saved" in history.replay_status_var.get()
        assert editor.service.calls == [] and selected == [editor.tab]
        assert repository.get_job_model(job.job_id).snapshot == entry.snapshot
    finally:
        if history is not None:
            history.destroy()
        repository.close()


@pytest.mark.parametrize("as_copy", [False, True])
def test_edit_during_save_retains_saved_hashes_and_independent_copy_ids(editor, as_copy):
    from src.video.storyboard import StoryboardError
    from src.video.storyboard_readiness import verify_images

    panel = editor.panel
    panel._rows[1].keyframe_var.set(make_image(editor.tmp / "anchor.png", (480, 832), "red"))
    original_ids = [s.shot_id for s in panel.shots()]
    original_runner = panel._runner
    pending = []

    def submit(_key, work, **callbacks):
        pending.append((work, callbacks))

    panel._runner = SimpleNamespace(submit=submit, close=lambda: None)
    try:
        panel._save_storyboard(as_copy=as_copy)
        panel._rows[1].prompt_var.set("edited while saving")
        work, callbacks = pending.pop()
        saved = work()
        # The disk snapshot has identities, even if a linked file changes before GUI delivery.
        assert saved.source_sha256 and saved.shots[1].keyframe_sha256
        make_image(editor.tmp / "source.png", (480, 832), "green")
        callbacks["on_result"](saved)
        callbacks["on_complete"](True, None)
        current = panel._capture_storyboard()
        assert current.source_sha256 == saved.source_sha256
        assert current.shots[1].keyframe_sha256 == saved.shots[1].keyframe_sha256
        assert current.shots[1].prompt == "edited while saving"
        assert [s.shot_id for s in current.shots] == [s.shot_id for s in saved.shots]
        if as_copy:
            assert set(original_ids).isdisjoint(s.shot_id for s in current.shots)
        assert panel.dirty_var.get() == "Unsaved changes"
        with pytest.raises(StoryboardError, match="SHA-256 mismatch"):
            verify_images(current)
        assert editor.service.calls == []
    finally:
        panel._runner = original_runner
