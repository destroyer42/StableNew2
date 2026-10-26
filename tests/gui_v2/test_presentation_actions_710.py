"""Tk attachment ownership, dispatcher delivery, handoff payloads and teardown."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.main_window_v2 import MainWindowV2
from src.utils.error_envelope_v2 import wrap_exception


class DeferredDispatcher:
    def __init__(self):
        self.owner = threading.get_ident()
        self.pending = []

    def schedule(self, fn):
        self.pending.append(fn)

    def invoke_later(self, delay_ms, fn):
        self.schedule(fn)

    def run_on_ui_thread(self, fn):
        if threading.get_ident() == self.owner:
            fn()
        else:
            self.schedule(fn)

    def drain(self):
        pending, self.pending = self.pending, []
        for fn in pending:
            fn()


def setup_host():
    window = MainWindowV2.__new__(MainWindowV2)
    window.root = Mock(winfo_exists=Mock(return_value=True))
    window._disposed = window._close_in_progress = False
    window._presentation_actions = None
    window._invoker = DeferredDispatcher()
    window.header_zone = Mock()
    window.left_zone = SimpleNamespace(
        load_pack_button=Mock(), edit_pack_button=Mock(), packs_list=Mock()
    )
    window.bottom_zone = object()
    window.video_workflow_tab = Mock()
    window.movie_clips_tab = Mock()
    window.center_notebook = Mock()
    controller = Mock(_is_shutting_down=False)
    actions = window.attach_controller_actions(controller)
    return window, controller, actions


def on_worker(fn):
    errors = []

    def run():
        try:
            fn()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert not errors


def test_repeated_attachment_reuses_owner_and_replaces_exact_bindings():
    window, controller, actions = setup_host()
    assert window.attach_controller_actions(controller) is actions
    window.header_zone.run_button.configure.assert_called_with(command=controller.run_txt2img_once)
    window.left_zone.packs_list.bind.assert_called_with(
        "<<ListboxSelect>>", controller._on_pack_list_select
    )
    assert all(not call.kwargs for call in window.left_zone.packs_list.bind.call_args_list)
    window.left_zone = SimpleNamespace(load_config_button=Mock(), packs_list=Mock())
    window.attach_controller_actions(controller)
    window.left_zone.packs_list.bind.assert_not_called()


def test_connect_keeps_the_existing_toolbar_replacement_order():
    window, controller, _ = setup_host()
    window.app_controller = None
    window.app_state = Mock()
    # Attachment has already installed the legacy callback.
    window.header_zone.run_button.configure.assert_called_with(command=controller.run_txt2img_once)
    window.connect_controller(controller)
    window.header_zone.run_button.configure.assert_called_with(command=controller.on_run_clicked)
    # A repeated attachment used to restore run_txt2img_once before connect.
    window.attach_controller_actions(controller)
    window.connect_controller(controller)
    window.header_zone.run_button.configure.assert_called_with(command=controller.run_txt2img_once)


def test_debug_and_explanation_use_existing_controller_and_root(monkeypatch):
    window, controller, actions = setup_host()
    debug, explain = Mock(), Mock()
    monkeypatch.setattr("src.gui.panels_v2.debug_hub_panel_v2.DebugHubPanelV2.open", debug)
    monkeypatch.setattr("src.gui.panels_v2.job_explanation_panel_v2.JobExplanationPanelV2", explain)
    on_worker(lambda: (actions.open_debug_hub(), actions.explain_job("job-1")))
    debug.assert_not_called()
    explain.assert_not_called()
    window._invoker.drain()
    debug.assert_called_once_with(
        master=window.root,
        controller=controller,
        app_state=controller.app_state,
        log_handler=controller.gui_log_handler,
    )
    explain.assert_called_once_with("job-1", master=window.root, controller=controller)
    # Explanations were never singleton windows: a second request still opens one.
    actions.explain_job("job-1")
    assert explain.call_count == 2


def test_error_duplicates_focus_existing_modal_and_close_allows_reopen(monkeypatch):
    window, _, actions = setup_host()
    modal = Mock(return_value=Mock(winfo_exists=Mock(return_value=True)))
    monkeypatch.setattr("src.gui.views.error_modal_v2.ErrorModalV2", modal)
    envelope = wrap_exception(ValueError("boom"), subsystem="test")
    on_worker(
        lambda: (actions.show_structured_error(envelope), actions.show_structured_error(envelope))
    )
    modal.assert_not_called()
    window._invoker.drain()
    modal.assert_called_once_with(
        window.root, envelope=envelope, on_close=actions._clear_error_modal
    )
    modal.return_value.lift.assert_called_once_with()
    modal.call_args.kwargs["on_close"]()
    actions.show_structured_error(envelope)
    assert modal.call_count == 2


def test_error_tracking_survives_detach_and_reattach(monkeypatch):
    window, controller, actions = setup_host()
    modal = Mock(return_value=Mock(winfo_exists=Mock(return_value=True)))
    monkeypatch.setattr("src.gui.views.error_modal_v2.ErrorModalV2", modal)
    envelope = wrap_exception(ValueError("boom"), subsystem="test")
    actions.show_structured_error(envelope)
    actions.detach()
    replacement = window.attach_controller_actions(controller)
    assert replacement is not actions
    replacement.show_structured_error(envelope)
    assert modal.call_count == 1
    modal.return_value.lift.assert_called_once_with()


def test_debug_reuses_the_existing_dialog_singleton(monkeypatch):
    from src.gui.panels_v2.debug_hub_panel_v2 import DebugHubPanelV2

    _, _, actions = setup_host()
    existing = Mock(winfo_exists=Mock(return_value=True))
    monkeypatch.setattr(DebugHubPanelV2, "_active_instance", existing)
    actions.open_debug_hub()
    actions.open_debug_hub()
    assert existing.lift.call_count == 2


@pytest.mark.gui
def test_real_tk_error_parent_and_legacy_button_selection_bindings(tk_root):
    from src.gui.main_window_v2 import HeaderZone, LeftZone

    window, controller, actions = setup_host()
    window.root = tk_root
    header, left = HeaderZone(tk_root), LeftZone(tk_root)
    window.header_zone, window.left_zone = header, left
    try:
        actions.bind_commands()
        header.run_button.invoke()
        controller.run_txt2img_once.assert_called_once_with()
        # Real Tk replaces the binding on repeat attachment; it never appends.
        window.attach_controller_actions(controller)
        tk_root.deiconify()
        left.pack()
        tk_root.update()
        left.packs_list.event_generate("<<ListboxSelect>>")
        controller._on_pack_list_select.assert_called_once()
        actions.show_structured_error(wrap_exception(ValueError("boom"), subsystem="test"))
        modal = window._structured_error_modal
        assert modal.master is tk_root
        actions.show_structured_error(wrap_exception(ValueError("again"), subsystem="test"))
        assert window._structured_error_modal is modal
        modal.destroy()
    finally:
        actions.detach()
        header.destroy()
        left.destroy()


@pytest.mark.parametrize("fence", ["detach", "replace", "shutdown", "cleanup", "destroy"])
def test_pending_actions_cannot_resurrect_windows(monkeypatch, fence):
    window, controller, actions = setup_host()
    debug, explain, modal = Mock(), Mock(), Mock()
    monkeypatch.setattr("src.gui.panels_v2.debug_hub_panel_v2.DebugHubPanelV2.open", debug)
    monkeypatch.setattr("src.gui.panels_v2.job_explanation_panel_v2.JobExplanationPanelV2", explain)
    monkeypatch.setattr("src.gui.views.error_modal_v2.ErrorModalV2", modal)
    on_worker(
        lambda: (
            actions.open_debug_hub(),
            actions.explain_job("job-1"),
            actions.show_structured_error(wrap_exception(ValueError("boom"), subsystem="test")),
            actions.image_to_video_workflow("source.png", status_message="queued"),
            actions.bind_commands(),
        )
    )
    window.header_zone.reset_mock()
    if fence == "detach":
        window._detach_presentation_actions()
    elif fence == "replace":
        window.attach_controller_actions(Mock(_is_shutting_down=False))
        window.header_zone.reset_mock()
    elif fence == "shutdown":
        controller._is_shutting_down = True
    elif fence == "cleanup":
        window._disposed = True
    else:
        window.root.winfo_exists.return_value = False
    window._invoker.drain()
    debug.assert_not_called()
    explain.assert_not_called()
    modal.assert_not_called()
    window.video_workflow_tab.set_source_image_path.assert_not_called()
    window.header_zone.run_button.configure.assert_not_called()


def test_navigation_snapshots_order_lineage_destination_status_and_returns():
    window, _, actions = setup_host()
    bundle = {
        "primary_path": "clip.mp4",
        "thumbnail_path": "thumb.png",
        "frame_paths": ["b.png", "a.png"],
    }
    lineage = {"source_job_id": "parent"}
    returns = []
    on_worker(
        lambda: returns.extend(
            [
                actions.image_to_video_workflow(
                    "input.png", status_message="image", lineage=lineage
                ),
                actions.bundle_to_video_workflow(bundle, status_message="bundle"),
                actions.image_to_movie_clips("input.png", status_message="movie image"),
                actions.bundle_to_movie_clips(bundle, status_message="movie bundle"),
            ]
        )
    )
    lineage["source_job_id"] = "changed"
    bundle["frame_paths"].reverse()
    window.center_notebook.select.assert_not_called()
    window._invoker.drain()
    assert returns == ["input.png", "thumb.png", ["input.png"], None]
    window.video_workflow_tab.set_source_image_path.assert_called_once_with(
        "input.png",
        status_message="image",
        lineage={"source_job_id": "parent"},
    )
    expected = {**bundle, "frame_paths": ["b.png", "a.png"]}
    window.video_workflow_tab.set_source_bundle.assert_called_once_with(
        expected, status_message="bundle"
    )
    window.movie_clips_tab.set_source_bundle.assert_called_once_with(
        expected, status_message="movie bundle"
    )
    window.movie_clips_tab.set_source_frame_paths.assert_called_once_with(
        ["input.png"], status_message="movie image"
    )
    assert [c.args[0] for c in window.center_notebook.select.call_args_list] == [
        window.video_workflow_tab,
        window.video_workflow_tab,
        window.movie_clips_tab,
        window.movie_clips_tab,
    ]


def test_missing_destinations_and_unsupported_handoffs_raise_before_delivery():
    window, _, actions = setup_host()
    window.video_workflow_tab = None
    with pytest.raises(RuntimeError, match="Video Workflow tab is not available"):
        actions.image_to_video_workflow("image.png", status_message="load")
    window.movie_clips_tab = object()
    with pytest.raises(RuntimeError, match="Movie Clips tab does not support bundle handoff"):
        actions.bundle_to_movie_clips({}, status_message="load")
    actions.detach()
    with pytest.raises(RuntimeError, match="detached"):
        actions.image_to_movie_clips("image.png", status_message="load")
