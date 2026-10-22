"""PR-VID-UX-313: one Make Video entry, a Basic/Advanced form, friendly names, inline errors.

The Video Workflow tab, the Review tab, the Job History panel and the Pipeline preview panel are real Tk
widgets; the production ``VideoWorkflowController`` and NJR builder sit behind a recording stand-in for
``JobService.submit_njrs``, and the production ``AppController`` handoff methods run over a fake main window.
No GPU, Comfy process, model, WebUI or network is involved.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.gui.app_state_v2 import AppStateV2
from src.gui.controllers.video_workspace_handoff import (
    route_image_to_video_workflow,
    route_images_to_video_workflow,
    show_queue_view,
)
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.gui.widgets import submission_notice_v2
from src.pipeline.job_models_v2 import NormalizedJobRecord, SourceKind
from src.queue.job_history_store import JobHistoryEntry, JobStatus
from tests.helpers.make_video_313 import (
    ANIMATE2_ID,
    TI2V_ID,
    HandoffApp,
    make_app,
    make_image,
    make_window,
)

pytestmark = pytest.mark.gui


def _pump(root: tk.Misc, milliseconds: int = 120) -> None:
    import time

    end = time.monotonic() + milliseconds / 1000.0
    while time.monotonic() < end:
        root.update()
        time.sleep(0.005)


@pytest.fixture
def env(tk_root, tmp_path):
    app, controller, service = make_app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    window = make_window(tab)
    app.main_window = window
    handoff = HandoffApp(window)
    yield SimpleNamespace(
        app=app,
        controller=controller,
        service=service,
        tab=tab,
        window=window,
        handoff=handoff,
        root=tk_root,
        tmp=tmp_path,
    )
    tab.destroy()


def _history_entry(job_id: str, image: str) -> JobHistoryEntry:
    return JobHistoryEntry(
        job_id=job_id,
        created_at="2025-01-01T12:00:00",
        status=JobStatus.COMPLETED,
        payload_summary="PackA",
        completed_at="2025-01-01T12:00:00",
        result={
            "artifact": {
                "schema": "stablenew.artifact.v2.6",
                "artifact_type": "image",
                "primary_path": image,
                "output_paths": [image],
            }
        },
    )


# ------------------------------------------------------------------ source handoff from every entry point


def _from_review(env, paths: list[str], row: int) -> None:
    review = ReviewTabFrame(env.root, app_controller=env.handoff)
    try:
        review._set_selected_images([Path(p) for p in paths])
        review.images_list.selection_clear(0, "end")
        review.images_list.selection_set(row)
        review._on_send_selected_to_video_workflow()
    finally:
        review.destroy()


def _from_history(env, paths: list[str], row: int) -> None:
    entries = [_history_entry(f"job-{i}", path) for i, path in enumerate(paths)]
    env.handoff.app_state.history_items = entries
    state = AppStateV2()
    panel = JobHistoryPanelV2(env.root, controller=env.handoff, app_state=state)
    try:
        state.set_history_items(entries)
        env.root.update_idletasks()
        item = panel.history_tree.get_children()[row]
        panel.history_tree.selection_set(item)
        panel.history_tree.event_generate("<<TreeviewSelect>>")
        assert panel.video_workflow_btn.cget("text") == "Make Video"
        panel.video_workflow_btn.invoke()
        assert panel.replay_status_var.get() == ""
    finally:
        panel.destroy()


def _from_pipeline(env, paths: list[str], row: int, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.gui.preview_panel_v2.PREVIEW_STATE_PATH", tmp_path / "preview.json")
    panel = PreviewPanelV2(env.root, controller=env.handoff, app_state=AppStateV2())
    try:
        assert str(panel.make_video_button.cget("state")) == "disabled"  # nothing previewed yet
        panel.thumbnail.set_image_from_path(paths[row])
        assert str(panel.make_video_button.cget("state")) == "normal"
        panel.make_video_button.invoke()
        assert panel.make_video_status_var.get() == ""
    finally:
        panel.destroy()


@pytest.mark.parametrize("origin", ["review", "history", "pipeline"])
def test_make_video_loads_the_selected_image_and_the_recommended_workflow(
    env, origin, monkeypatch
) -> None:
    paths = [
        make_image(env.tmp / f"img_{i}.png", color=color)
        for i, color in enumerate(("red", "green", "blue"))
    ]
    env.tab.workflow_var.set(
        ANIMATE2_ID
    )  # an experimental choice is replaced by the approved backend
    send = {
        "review": lambda row: _from_review(env, paths, row),
        "history": lambda row: _from_history(env, paths, row),
        "pipeline": lambda row: _from_pipeline(env, paths, row, monkeypatch, env.tmp),
    }[origin]

    send(1)
    assert (
        env.tab.source_image_var.get() == paths[1]
    )  # the selected image, not the first or the latest
    assert env.tab.workflow_var.get() == TI2V_ID
    assert "(recommended)" in env.tab.workflow_label_var.get()
    assert env.window.center_notebook.selected[-1] is env.tab
    assert env.service.calls == []  # a handoff queues nothing

    send(2)  # a second selection replaces the first
    assert env.tab.source_image_var.get() == paths[2]


def test_history_make_video_records_the_producing_job_as_the_parent(env) -> None:
    path = make_image(env.tmp / "from_history.png")
    _from_history(env, [path], 0)
    assert env.tab._current_lineage() == {"source_job_id": "job-0"}

    env.tab.source_image_var.set(
        path.replace("from_history", "other")
    )  # any other source drops the lineage
    assert env.tab._current_lineage() == {}


def test_review_make_video_of_one_image_keeps_its_trusted_lineage(env) -> None:
    path = make_image(env.tmp / "reviewed.png")
    window = make_window(env.tab)
    routed = route_images_to_video_workflow(
        main_window=window,
        image_paths=[path],
        lineage_by_path={path: {"source_job_id": "job-r", "source_artifact_id": "art-r"}},
    )
    assert routed == [path]
    assert env.tab._current_lineage() == {"source_job_id": "job-r", "source_artifact_id": "art-r"}


def test_a_history_handoff_failure_is_shown_and_not_swallowed(env) -> None:
    missing = str(env.tmp / "gone.png")
    entries = [_history_entry("job-gone", missing)]
    env.handoff.app_state.history_items = entries
    state = AppStateV2()
    panel = JobHistoryPanelV2(env.root, controller=env.handoff, app_state=state)
    try:
        panel._selected_job_id = "job-gone"
        panel._entries = {"job-gone": entries[0]}
        panel._history_action_state = lambda _entry: SimpleNamespace(
            svd=True, video_workflow=True, movie_clips=True
        )
        panel._on_send_to_video_workflow()
        assert "Make Video failed" in panel.replay_status_var.get()
        panel._on_send_to_svd()
        assert "Animate with SVD failed" in panel.replay_status_var.get()
    finally:
        panel.destroy()


def test_the_pipeline_make_video_failure_is_shown_beside_the_button(env, monkeypatch) -> None:
    monkeypatch.setattr("src.gui.preview_panel_v2.PREVIEW_STATE_PATH", env.tmp / "preview.json")
    panel = PreviewPanelV2(env.root, controller=env.handoff, app_state=AppStateV2())
    try:
        panel.thumbnail.set_image_from_path(str(env.tmp / "vanished.png"))
        panel.make_video_button.invoke()
        assert "Make Video failed" in panel.make_video_status_var.get()
    finally:
        panel.destroy()


# ------------------------------------------------------------------ approved versus experimental


def test_make_video_keeps_an_approved_choice_and_never_carries_an_opt_in(env) -> None:
    path = make_image(env.tmp / "src.png")
    route_image_to_video_workflow(main_window=env.window, image_path=path)
    assert env.tab.workflow_var.get() == TI2V_ID  # the recommended approved workflow

    env.tab.workflow_var.set(ANIMATE2_ID)
    env.tab.experimental_opt_in_var.set(True)
    route_image_to_video_workflow(main_window=env.window, image_path=path)
    assert env.tab.workflow_var.get() == TI2V_ID
    assert env.tab.experimental_opt_in_var.get() is False
    assert env.tab.get_video_workflow_state(for_submission=True)["experimental_opt_in"] is False


def test_an_experimental_workflow_stays_selectable_and_needs_its_own_opt_in(env) -> None:
    labels = list(env.tab.workflow_combo["values"])
    assert any("(Experimental" in label or "(experimental)" in label for label in labels)
    experimental_label = next(label for label in labels if "Driving Video" in label)
    env.tab.workflow_label_var.set(experimental_label)  # chosen through the friendly picker
    assert env.tab.workflow_var.get() == ANIMATE2_ID

    assert "experimental opt-in" in env.tab._queue_block_reason()
    assert str(env.tab.queue_workflow_button.cget("state")) == "disabled"
    assert env.tab.get_video_workflow_state(for_submission=True)["experimental_opt_in"] is False

    env.tab.experimental_opt_in_var.set(True)
    assert env.tab._queue_block_reason() == ""
    assert env.tab.get_video_workflow_state(for_submission=True)["experimental_opt_in"] is True

    env.tab.workflow_var.set(TI2V_ID)  # leaving the experimental workflow drops the authorisation
    assert env.tab.experimental_opt_in_var.get() is False


# ------------------------------------------------------------------ friendly names, persisted state


def test_the_picker_shows_friendly_names_but_state_keeps_the_workflow_id(env) -> None:
    labels = list(env.tab.workflow_combo["values"])
    assert labels and all(TI2V_ID not in label and ANIMATE2_ID not in label for label in labels)
    assert env.tab.workflow_label_var.get() == "Wan2.2 TI2V-5B Prompt-Directed I2V (recommended)"

    state = env.tab.get_video_workflow_state()
    assert state["workflow_id"] == TI2V_ID  # persisted state is unchanged by the picker
    env.tab.restore_video_workflow_state({**state, "workflow_id": ANIMATE2_ID})
    assert env.tab.workflow_var.get() == ANIMATE2_ID
    assert "Driving Video" in env.tab.workflow_label_var.get()

    env.tab.restore_video_workflow_state({**state, "workflow_id": "retired_workflow_v0"})
    assert (
        env.tab.workflow_label_var.get() == "retired_workflow_v0"
    )  # an unknown id is shown, not hidden


# ------------------------------------------------------------------ Basic / Advanced


def _under(widget: tk.Misc, ancestor: tk.Misc) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.master
    return False


def test_basic_controls_are_separate_from_the_collapsed_advanced_options(env) -> None:
    tab = env.tab
    advanced = tab._advanced_frame
    for widget in (
        tab.workflow_combo,
        tab.frame_count_combo,
        tab.prompt_text,
        tab.runtime_readiness_strip,
    ):
        assert not _under(widget, advanced)
    for widget in (
        tab.end_anchor_entry,
        tab.mid_anchors_entry,
        tab.seed_entry,
        tab.negative_prompt_text,
        tab.smooth_check,
        tab.conditioning_section,
        tab.workflow_controls_panel,
        tab.experiment_panel,
        tab.eval_panel,
    ):
        assert _under(widget, advanced)
    assert tab.advanced_section.is_expanded() is False
    assert tab.use_svd_button.winfo_exists()


def test_advanced_values_survive_collapse_and_are_announced(env) -> None:
    tab = env.tab
    tab.seed_var.set("123")
    tab.smooth_var.set(True)
    tab._set_text_value(tab.negative_prompt_text, "blurry")
    header = tab.advanced_section.header_text()
    assert "seed" in header and "smoothing" in header and "negative prompt" in header

    state = tab.get_video_workflow_state()  # collapsed: every value is still read and submitted
    assert state["seed"] == "123" and state["negative_prompt"] == "blurry"
    assert state["interpolation"] == {"enabled": True}

    tab.advanced_section.toggle()
    tab.advanced_section.toggle()
    assert tab.seed_var.get() == "123"


def test_conditioning_fields_are_hidden_unless_the_workflow_declares_them(env) -> None:
    tab = env.tab
    assert tab.workflow_var.get() == TI2V_ID
    assert tab.conditioning_section.winfo_manager() == ""  # no camera, depth or ControlNet for TI2V
    tab.workflow_var.set(ANIMATE2_ID)
    assert tab.conditioning_section.winfo_manager() == ""


def test_advanced_opens_by_itself_for_a_workflow_that_requires_a_driving_video(env) -> None:
    tab = env.tab
    assert tab.advanced_section.is_expanded() is False
    tab.workflow_var.set(ANIMATE2_ID)
    assert tab.advanced_section.is_expanded() is True
    assert tab.pose_video_frame.winfo_manager() == "grid"


# ------------------------------------------------------------------ queueing through the canonical boundary


def _ready_tab(env, *, name: str = "portrait.png"):
    path = make_image(env.tmp / name, size=(60, 90))
    env.tab.set_source_image_path(path)
    env.tab.workflow_var.set(TI2V_ID)
    env.tab._set_text_value(env.tab.prompt_text, "she turns her head and smiles")
    env.tab.seed_var.set("77")
    return path


def test_queue_submits_one_frozen_njr_through_the_job_service_boundary(env) -> None:
    path = _ready_tab(env)
    with (
        patch("tkinter.messagebox.showinfo") as info,
        patch("tkinter.messagebox.showerror") as error,
    ):
        env.tab.queue_workflow_button.invoke()
    assert not info.called and not error.called  # nothing modal

    [(njrs, policy)] = env.service.calls
    assert isinstance(policy, SubmissionPolicy)
    [njr] = njrs
    assert isinstance(njr, NormalizedJobRecord) and njr.source.kind is SourceKind.VIDEO_WORKFLOW
    block = njr.config["video_workflow"]
    assert block["workflow_id"] == TI2V_ID and block["workflow_version"] == "1.2.0"
    assert block["seed"] == 77 and block["frame_count"] == 49
    assert block["source_preparation"]["original_source_path"] == str(Path(path))
    assert block["video_execution"]["experimental_opt_in"] is False  # approved: no per-job opt-in
    assert "source_lineage" not in block  # the handoff hint never leaks into the frozen record

    notice = env.tab.submission_notice
    assert notice.kind == "queued" and "job-1-0" in notice.message_var.get()
    assert notice.view_button.winfo_ismapped() or notice.view_button.winfo_manager() == "grid"


def test_view_in_queue_selects_the_pipeline_tab_and_dismisses_the_notice(env) -> None:
    _ready_tab(env)
    env.tab._on_submit()
    env.tab.submission_notice.view_button.invoke()
    assert env.window.center_notebook.selected[-1] is env.window.pipeline_tab
    assert env.tab.submission_notice.kind == ""
    assert show_queue_view(SimpleNamespace()) is False  # no window, no crash


def test_the_queued_notice_dismisses_itself_and_is_cancelled_on_destroy(env, monkeypatch) -> None:
    monkeypatch.setattr(submission_notice_v2, "QUEUED_NOTICE_MS", 40)
    _ready_tab(env)
    env.tab._on_submit()
    assert env.tab.submission_notice.kind == "queued"
    _pump(env.root, 200)
    assert env.tab.submission_notice.kind == ""

    env.tab.submission_notice.show_queued("again")
    env.tab.destroy()  # the pending dismissal is cancelled with the widget
    _pump(env.root, 120)


def test_history_lineage_reaches_the_frozen_record_and_survives_replay_hydration(
    env, tmp_path
) -> None:
    from src.controller.pipeline_controller_services.history_handoff_service import (
        HistoryHandoffService,
    )
    from src.queue.job_repository import JobRepository
    from tests.helpers.job_helpers import make_test_job_from_njr

    path = make_image(env.tmp / "parent.png")
    _from_history(env, [path], 0)
    env.tab._set_text_value(env.tab.prompt_text, "slow dolly")
    env.tab._on_submit()
    [njr] = env.service.submitted

    meta = njr.extra_metadata
    assert meta["parent_job_id"] == "job-0"
    assert meta["video_workflow"]["source_identity"]["source_job_id"] == "job-0"
    assert meta["video_workflow"]["source_identity"]["original_path"] == str(Path(path))

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    job = make_test_job_from_njr(njr, prompt_source="manual")
    repository.record_job_submissions([job])
    stored = repository.get_job(job.job_id)
    hydrated = HistoryHandoffService().hydrate_njr_from_snapshot(stored.snapshot)
    assert hydrated is not None
    assert hydrated.config == njr.config  # replay starts from exactly the frozen record
    assert hydrated.extra_metadata["parent_job_id"] == "job-0"
    frozen_seed = njr.extra_metadata["video_workflow"]["seed"]
    assert (
        hydrated.extra_metadata["video_workflow"]["seed"] == frozen_seed
    )  # the same sampler seed on replay


def test_a_job_without_a_trusted_parent_records_no_lineage(env) -> None:
    _ready_tab(env)
    env.tab._on_submit()
    [njr] = env.service.submitted
    assert "parent_job_id" not in njr.extra_metadata
    assert "source_identity" not in njr.extra_metadata["video_workflow"]


# ------------------------------------------------------------------ failures are visible, inline and recoverable


def test_queue_without_a_source_shows_an_inline_error_and_submits_nothing(env) -> None:
    with patch("tkinter.messagebox.showerror") as error:
        env.tab._on_submit()
    assert not error.called
    notice = env.tab.submission_notice
    assert notice.kind == "error" and "source image" in notice.message_var.get()
    assert env.tab.status_var.get() == notice.message_var.get()
    assert env.service.calls == []


def test_a_builder_refusal_is_shown_inline_and_cleared_by_the_next_attempt(env) -> None:
    env.tab.source_image_var.set(str(env.tmp / "not_there.png"))
    env.tab._on_submit()
    notice = env.tab.submission_notice
    assert notice.kind == "error" and notice.message_var.get().startswith("Not queued:")
    assert env.service.calls == []

    _ready_tab(env)
    env.tab._on_submit()
    assert env.tab.submission_notice.kind == "queued"  # a retry replaces the error


def test_a_job_service_refusal_is_shown_inline(tk_root, tmp_path) -> None:
    app, _controller, service = make_app(tmp_path, refuse=RuntimeError("queue admission is closed"))
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    try:
        path = make_image(tmp_path / "x.png")
        tab.set_source_image_path(path)
        tab._set_text_value(tab.prompt_text, "a slow push-in")
        tab._on_submit()
        assert tab.submission_notice.kind == "error"
        assert "queue admission is closed" in tab.submission_notice.message_var.get()
        assert service.calls == []
    finally:
        tab.destroy()


def test_use_native_svd_hands_the_same_source_to_the_svd_tab_or_explains(env) -> None:
    path = make_image(env.tmp / "svd_src.png")
    env.tab.set_source_image_path(path)
    sent: list[str] = []
    env.app.send_image_to_svd = sent.append
    env.tab.use_svd_button.invoke()
    assert sent == [path]

    env.app.send_image_to_svd = lambda _p: (_ for _ in ()).throw(
        RuntimeError("SVD tab is not available")
    )
    env.tab.use_svd_button.invoke()
    assert "SVD tab is not available" in env.tab.submission_notice.message_var.get()


# ------------------------------------------------------------------ the native SVD tab uses the same feedback


def test_the_svd_tab_acknowledges_and_reports_inline_without_dialogs(tk_root, tmp_path) -> None:
    from unittest.mock import Mock

    from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2

    image = make_image(tmp_path / "svd.png")
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.submit_svd_job.return_value = "job-svd-1"
    controller.main_window = make_window(None)
    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        with (
            patch("tkinter.messagebox.showinfo") as info,
            patch("tkinter.messagebox.showerror") as error,
            patch("tkinter.messagebox.showwarning") as warning,
        ):
            tab._on_submit()  # no source yet
            assert (
                tab.submission_notice.kind == "error"
                and "image file" in tab.submission_notice.message_var.get()
            )

            tab.source_image_var.set(image)
            tab._on_submit()
            assert (
                tab.submission_notice.kind == "queued"
                and "job-svd-1" in tab.submission_notice.message_var.get()
            )
            tab.submission_notice.view_button.invoke()
            assert (
                controller.main_window.center_notebook.selected[-1]
                is controller.main_window.pipeline_tab
            )

            controller.submit_svd_job.side_effect = RuntimeError("model files are missing")
            tab._on_submit()
            assert tab.submission_notice.kind == "error"
            assert "model files are missing" in tab.submission_notice.message_var.get()
        assert not (info.called or error.called or warning.called)
    finally:
        tab.destroy()
