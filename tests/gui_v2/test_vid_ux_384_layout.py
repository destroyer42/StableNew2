"""VID-UX-384: Create / Evaluate views, two-pane layout, always-visible settings, media on demand."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from src.gui.views import video_workflow_layout_v2 as layout_module
from src.gui.views.video_workflow_layout_v2 import (
    BREAKPOINT_PX,
    PANE_FORM,
    PANE_MEDIA,
    VIEW_CREATE,
    VIEW_EVALUATE,
    TwoPaneLayout,
    media_allowed,
)
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from tests.helpers.make_video_313 import make_app, make_window

pytestmark = pytest.mark.gui


def _view(*, advisories=(), state="ready", driving=False, lines=("480x832 crop",)):
    return SimpleNamespace(
        advisory_lines=tuple(advisories),
        source_state=state,
        accepts_driving_video=driving,
        source_lines=tuple(lines),
    )


@pytest.fixture
def env(tk_root, tmp_path):
    app, controller, service = make_app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    yield SimpleNamespace(app=app, controller=controller, tab=tab, root=tk_root, tmp=tmp_path)
    tab.destroy()


# ---------------------------------------------------------------- layout scaffolding


def test_two_pane_layout_shows_one_pane_at_a_time_below_the_breakpoint(tk_root):
    panes = TwoPaneLayout(tk_root)
    try:
        assert panes.apply_width(BREAKPOINT_PX + 200) is False  # starts two-column
        assert not panes.stacked
        assert int(panes.left_pane.grid_info()["column"]) == 0
        assert int(panes.right_scroll.grid_info()["column"]) == 1
        assert panes.apply_width(BREAKPOINT_PX - 100) is True
        assert panes.stacked
        # Stacked: one pane at a time, each with the full height (no tiny nested viewport).
        assert panes.left_pane.winfo_manager() == "grid" and not panes.right_scroll.winfo_manager()
        panes.show_pane(PANE_MEDIA)
        assert panes.right_scroll.winfo_manager() == "grid" and not panes.left_pane.winfo_manager()
        panes.show_pane(PANE_FORM)
        assert panes.left_pane.winfo_manager() == "grid"
        assert panes.apply_width(BREAKPOINT_PX + 1) is True
        assert not panes.stacked
        assert (
            panes.left_pane.winfo_manager() == "grid"
            and panes.right_scroll.winfo_manager() == "grid"
        )
        assert int(panes.columnconfigure(0)["weight"]) > int(panes.columnconfigure(1)["weight"])
        assert int(panes.columnconfigure(1)["minsize"]) >= 360
    finally:
        panes.destroy()


def test_the_form_media_toggle_exists_only_while_stacked(env):
    tab = env.tab
    panes = tab._create_view
    panes.apply_width(BREAKPOINT_PX + 200)
    assert not tab.pane_switch.winfo_manager()
    panes.apply_width(BREAKPOINT_PX - 100)
    assert tab.pane_switch.winfo_manager() == "grid"
    tab.pane_switch.buttons[PANE_MEDIA].invoke()
    assert panes.active_pane == PANE_MEDIA and panes.right_scroll.winfo_manager() == "grid"
    tab.select_view(VIEW_EVALUATE)
    assert not tab.pane_switch.winfo_manager()
    tab.select_view(VIEW_CREATE)
    tab._on_readiness_chip()  # the chip opens the details, which live in the media pane
    assert panes.active_pane == PANE_MEDIA


# ---------------------------------------------------------------- Create / Evaluate


def test_create_is_the_default_view_and_evaluate_shows_the_eval_controls_immediately(env):
    tab = env.tab
    assert tab.current_view() == VIEW_CREATE
    assert tab._create_view.winfo_manager() == "grid"
    assert not tab.evaluate_view.winfo_manager()
    tab.view_switch.buttons[VIEW_EVALUATE].invoke()
    assert tab.current_view() == VIEW_EVALUATE
    assert tab.evaluate_view.winfo_manager() == "grid"
    assert not tab._create_view.winfo_manager()
    # No expanding needed: the controls are in the view itself.
    assert str(tab.eval_panel.queue_button.cget("text")).startswith("Queue")
    assert (
        tab.eval_panel.report_button.winfo_manager()
        or tab.eval_panel.report_button.master.winfo_manager()
    )
    assert tab.eval_panel.winfo_manager() == "grid"


def test_one_primary_button_per_visible_view(env):
    tab = env.tab
    assert str(tab.queue_workflow_button.cget("style")) == "Primary.TButton"
    assert not tab.evaluate_view.winfo_manager()  # the eval Primary is not on a visible surface
    tab.select_view(VIEW_EVALUATE)
    assert str(tab.queue_workflow_button.cget("style")) != "Primary.TButton"
    assert str(tab.eval_panel.queue_button.cget("style")) == "Primary.TButton"
    tab.select_view(VIEW_CREATE)
    assert str(tab.queue_workflow_button.cget("style")) == "Primary.TButton"


def test_switching_views_never_loses_form_state(env):
    tab = env.tab
    tab.prompt_text.insert("1.0", "a slow dolly shot")
    tab.seed_var.set("42")
    tab.select_view(VIEW_EVALUATE)
    tab.select_view(VIEW_CREATE)
    assert tab.prompt_text.get("1.0", "end").strip() == "a slow dolly shot"
    assert tab.seed_var.get() == "42"


def test_view_and_show_media_are_saved_and_restored_but_never_submitted(env):
    tab = env.tab
    tab.select_view(VIEW_EVALUATE)
    tab.show_media_var.set(False)
    saved = tab.get_video_workflow_state()
    assert saved["view"] == VIEW_EVALUATE and saved["show_media"] is False
    submitted = tab.get_video_workflow_state(for_submission=True)
    assert "view" not in submitted and "show_media" not in submitted
    tab.select_view(VIEW_CREATE)
    tab.show_media_var.set(True)
    tab.restore_video_workflow_state(saved)
    assert tab.current_view() == VIEW_EVALUATE
    assert tab.show_media_var.get() is False


def test_compare_one_control_explains_when_it_is_unavailable(env):
    view = env.tab.evaluate_view
    view.sync()
    offered = env.tab.experiment_panel.winfo_manager() != ""
    assert bool(view.experiment_empty_label.winfo_manager()) is (not offered)


# ---------------------------------------------------------------- settings visible by default


def test_the_settings_people_change_are_visible_without_opening_anything(env):
    tab = env.tab
    assert not tab.advanced_section.is_expanded()
    for widget in (tab.workflow_combo, tab.seed_entry, tab.smooth_check, tab.frame_count_frame):
        assert widget.winfo_manager()
    assert tab.settings_block.winfo_manager() == "grid"


def test_more_settings_keeps_the_rare_controls_and_the_old_attribute_name(env):
    tab = env.tab
    assert str(tab.advanced_section.toggle_button.cget("text")).startswith("More settings") or (
        "More settings" in str(tab.advanced_section.toggle_button.cget("text"))
    )
    assert tab.negative_prompt_text.master is tab.advanced_section.body


@pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop pixel geometry")
def test_default_task_shows_source_queue_prompt_and_settings_at_1280x680(env):
    tab, root = env.tab, env.root
    root.geometry("1280x680+0+0")
    root.deiconify()
    tab.pack(fill="both", expand=True)
    root.update()
    canvas = tab._body_scroll._canvas
    top, bottom = canvas.winfo_rooty(), canvas.winfo_rooty() + canvas.winfo_height()
    for widget in (tab.prompt_text, tab.workflow_combo, tab.seed_entry, tab.smooth_check):
        assert widget.winfo_rooty() >= top
        assert widget.winfo_rooty() + widget.winfo_height() <= bottom + 1
    header_bottom = tab._header_frame.winfo_rooty() + tab._header_frame.winfo_height()
    assert (
        tab.queue_workflow_button.winfo_rooty() + tab.queue_workflow_button.winfo_height()
        <= header_bottom
    )
    assert tab.task_selector.winfo_ismapped()


# ---------------------------------------------------------------- readiness visibility matrix


@pytest.mark.parametrize(
    ("task", "driving", "advisories", "state", "opened", "relevant"),
    [
        ("animate", False, (), "ready", False, False),  # nothing to say: chip only
        ("animate", False, ("crop is tight",), "ready", False, True),  # a warning earns the panel
        ("animate", False, (), "error", False, True),  # a problem too
        ("animate", True, (), "ready", False, True),  # the engine takes a driving video
        ("follow_clip", False, (), "ready", False, True),  # the driving-clip task
        ("animate", False, (), "ready", True, True),  # the operator opened it from the chip
    ],
)
def test_readiness_panel_visibility_matrix(env, task, driving, advisories, state, opened, relevant):
    tab = env.tab
    tab._task = task
    tab._readiness_opened = opened
    tab._on_readiness_rendered(_view(advisories=advisories, state=state, driving=driving))
    assert tab.motion_readiness_panel._relevant is relevant


def test_the_chip_summarises_readiness_and_opens_the_details(env):
    tab = env.tab
    tab.source_image_var.set(str(env.tmp / "a.png"))
    tab._on_readiness_rendered(_view())
    assert str(tab.readiness_chip.cget("text")).startswith("Source ready")
    assert "480x832" in str(tab.readiness_chip.cget("text"))
    tab._on_readiness_rendered(_view(state="error"))
    assert "problem" in str(tab.readiness_chip.cget("text")).lower()
    tab.select_view(VIEW_EVALUATE)
    tab.readiness_chip.invoke()
    assert tab.current_view() == VIEW_CREATE
    assert tab.motion_readiness_panel._relevant is True


# ---------------------------------------------------------------- Show media


def test_one_show_media_variable_drives_every_media_surface(env):
    tab = env.tab
    assert tab.show_media_var.get() is True
    assert tab.source_preview.shown_var is tab.show_media_var
    assert tab.recent_outputs_panel.preview.shown_var is tab.show_media_var
    assert not tab.source_preview.show_button.winfo_manager()  # the tab's checkbox replaces it
    tab.show_media_var.set(False)
    assert tab.source_preview.model.shown is False
    assert tab.recent_outputs_panel.preview.model.shown is False
    tab.show_media_var.set(True)
    assert tab.source_preview.model.shown is True


def test_show_media_off_hides_the_readiness_crop(env):
    tab = env.tab
    assert tab._readiness_media_allowed() is True
    tab.show_media_var.set(False)
    assert tab._readiness_media_allowed() is False


def test_application_visibility_mode_wins_over_show_media(env, monkeypatch):
    tab = env.tab
    tab.show_media_var.set(True)

    class _Hidden:
        def __init__(self, _mode):
            pass

        def is_visible(self, _item):
            return False

    monkeypatch.setattr(layout_module, "ContentVisibilityResolver", _Hidden)
    assert media_allowed("sfw", "x.png") is False
    assert tab._readiness_media_allowed() is False  # the checkbox is on; policy still hides it
