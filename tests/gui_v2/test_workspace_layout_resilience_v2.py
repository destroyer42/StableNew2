from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.theme_v2 import BACKGROUND_ELEVATED
from src.gui.view_contracts.pipeline_layout_contract import (
    PRIMARY_CONTROL_MIN_WIDTH,
    WORKSPACE_CENTER_COLUMN_MIN_WIDTH,
    WORKSPACE_LEFT_COLUMN_MIN_WIDTH,
)
from src.gui.view_contracts.window_layout_contract import (
    SCREEN_MARGIN_HEIGHT,
    SCREEN_MARGIN_WIDTH,
    compute_window_layout,
    normalize_saved_geometry,
)
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.services.ui_state_store import UIStateStore


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def test_review_tab_uses_shared_workspace_minimums(tk_root) -> None:
    tab = ReviewTabFrame(tk_root)
    try:
        assert tab._body_frame.columnconfigure(0)["minsize"] == WORKSPACE_LEFT_COLUMN_MIN_WIDTH
        assert tab._body_frame.columnconfigure(1)["minsize"] == WORKSPACE_CENTER_COLUMN_MIN_WIDTH
        assert int(tab._controls_frame.grid_info()["row"]) == 1  # below the body, inside the scrollable workspace
        assert tab.prompt_text.cget("bg") == BACKGROUND_ELEVATED
        assert tab.feedback_notes.cget("bg") == BACKGROUND_ELEVATED
    finally:
        tab.destroy()


def test_learning_tab_uses_shared_workspace_minimums_and_staged_rows(
    tk_root, tmp_path: Path
) -> None:
    state_path = tmp_path / "ui_state.json"
    experiments_root = tmp_path / "experiments"
    store = UIStateStore(state_path)

    with (
        patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store),
        patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
            return_value=experiments_root,
        ),
    ):
        tab = LearningTabFrame(
            tk_root,
            app_state=AppStateV2(),
            pipeline_controller=_StubPipelineController(),
        )
        try:
            assert str(tab.designed_horizontal_panes.cget("orient")) == "horizontal"
            assert tab.experiment_scroll._vsb.winfo_manager() == "grid"
            assert tab.experiment_panel.master is tab.experiment_scroll.inner
            assert (
                tab._discovered_tab_frame.columnconfigure(0)["minsize"]
                == WORKSPACE_LEFT_COLUMN_MIN_WIDTH
            )
            assert (
                tab._discovered_tab_frame.columnconfigure(1)["minsize"]
                == WORKSPACE_CENTER_COLUMN_MIN_WIDTH
            )
            assert int(tab._staged_action_frame.grid_info()["row"]) == 12
            assert int(tab._staged_derive_frame.grid_info()["row"]) == 13
            assert int(tab._staged_review_frame.grid_info()["row"]) == 14
            assert tab._staged_notes_text.cget("bg") == BACKGROUND_ELEVATED
        finally:
            tab.destroy()


def test_video_workflow_tab_uses_shared_form_minimums_and_themed_text(tk_root) -> None:
    tab = VideoWorkflowTabFrameV2(tk_root)
    try:
        assert tab._body_frame.columnconfigure(0)["minsize"] > 0
        assert tab._body_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
        assert tab.prompt_text.cget("bg") == BACKGROUND_ELEVATED
        assert tab.negative_prompt_text.cget("bg") == BACKGROUND_ELEVATED
    finally:
        tab.destroy()


def test_svd_and_movie_clips_keep_workspace_and_settings_widths(tk_root) -> None:
    svd_tab = SVDTabFrameV2(tk_root)
    movie_tab = MovieClipsTabFrameV2(tk_root)
    try:
        assert svd_tab._body_frame.columnconfigure(0)["minsize"] == 420
        assert svd_tab._body_frame.columnconfigure(1)["minsize"] == 320
        assert svd_tab._settings_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH

        assert movie_tab._body_frame.columnconfigure(0)["minsize"] == 420
        assert movie_tab._body_frame.columnconfigure(1)["minsize"] == 320
        assert movie_tab._settings_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
        assert movie_tab.image_list.cget("bg") == BACKGROUND_ELEVATED
    finally:
        movie_tab.destroy()
        svd_tab.destroy()


# --- PR-GUI-100: screen-aware window layout and reachable long-form workspaces ---------------------------------------


@pytest.mark.parametrize("screen", [(1366, 768), (1920, 1080), (2560, 1440), (1024, 600)])
def test_window_layout_always_fits_the_screen(screen) -> None:
    width, height = screen
    layout = compute_window_layout(width, height)

    assert layout.min_width <= layout.width <= width - SCREEN_MARGIN_WIDTH
    assert layout.min_height <= layout.height <= height - SCREEN_MARGIN_HEIGHT
    assert layout.default_geometry == f"{layout.width}x{layout.height}"
    if screen == (2560, 1440):
        assert layout.width < width // 1.3  # no giant blank window on a large display
    if screen == (1920, 1080):
        assert layout.width == 1920 - SCREEN_MARGIN_WIDTH  # measured: the Pipeline columns need ~1896 px


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        ("1984x1350+10+10", "1342x672+10+10"),  # saved on a bigger display: clamped, not forced oversized
        ("1342x672+0+0", "1342x672+0+0"),  # valid saved geometry restores unchanged
        ("1000x500+50+50", "1280x672+50+50"),  # below the minimum is raised to it
        ("1984x1350", "1342x672"),
        ("1984x1110+-32000+-32000", None),  # off-screen sentinel recovers to the default
        ("1342x672+1360+700", None),  # no longer overlaps this display
        ("not-a-geometry", None),
    ],
)
def test_saved_geometry_is_normalized_for_the_current_screen(saved, expected) -> None:
    assert normalize_saved_geometry(saved, compute_window_layout(1366, 768)) == expected


@pytest.mark.parametrize(
    ("tab_factory", "scroll_attr", "last_control_attr"),
    [
        (ReviewTabFrame, "_workspace_scroll", "reprocess_all_button"),
        # PR-GUI-110: the primary submit actions left the scroll region; the lowest scrolled control is now the
        # Recent SVD Outputs action / the Video Workflow Recent outputs section (PR-VID-UX-313/314: the negative
        # prompt moved into the collapsed Advanced options).
        (SVDTabFrameV2, "_body_scroll", "open_manifest_btn"),
        (VideoWorkflowTabFrameV2, "_body_scroll", "recent_outputs_panel"),
    ],
    ids=["review", "svd", "video_workflow"],
)
def test_long_form_tabs_reach_their_lowest_control_on_a_laptop_viewport(
    tk_root, tab_factory, scroll_attr, last_control_attr
) -> None:
    layout = compute_window_layout(1366, 768)
    tk_root.geometry(f"{layout.width}x{layout.height}+0+0")
    tk_root.deiconify()  # a withdrawn root never realizes its children's sizes
    tab = tab_factory(tk_root)
    try:
        tab.pack(fill="both", expand=True)
        tk_root.update()
        scroll = getattr(tab, scroll_attr)
        control = getattr(tab, last_control_attr)

        # A workspace may fit entirely (collapsed sections); when it does not it must scroll, never grow the window.
        assert tk_root.winfo_height() <= layout.screen_height - SCREEN_MARGIN_HEIGHT

        scroll._canvas.yview_moveto(1.0)
        tk_root.update()
        view_top, view_bottom = scroll._canvas.winfo_rooty(), scroll._canvas.winfo_rooty() + scroll._canvas.winfo_height()
        control_top = control.winfo_rooty()
        control_bottom = control_top + control.winfo_height()
        assert control_top >= view_top and control_bottom <= view_bottom + 1, "lowest control must be inside the viewport"
    finally:
        tab.destroy()
        tk_root.withdraw()


@pytest.mark.parametrize("font_scale", [1.0, 1.5])
def test_recent_video_controls_and_detach_return_fit_the_compact_viewport(tk_root, tmp_path, font_scale):
    import time

    from src.video.recent_video_outputs import RecentVideoOutput
    from src.video.review_preview import PreviewClip, PreviewResult

    base = float(tk_root.tk.call("tk", "scaling"))
    tk_root.tk.call("tk", "scaling", base * font_scale)
    layout = compute_window_layout(1366, 768)
    tk_root.geometry(f"{layout.width}x{layout.height}+0+0")
    tab = VideoWorkflowTabFrameV2(tk_root)
    panel = tab.recent_outputs_panel
    clip_path = tmp_path / "recorded.mp4"
    clip_path.write_bytes(b"fixture; injected decoding only")

    def decode(path, cancel):
        assert not cancel.is_set()
        # Tall preview at the existing maximum edge, not a tiny frame hiding a layout problem.
        clip = PreviewClip(path, 128, 256, 768, 1536, 24, 1, 1, 1.0, bytes(128 * 256 * 3))
        return PreviewResult(path=path, status="ok", clip=clip)

    panel.preview._decode_video = decode

    def settle(predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            tk_root.update()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Injected Recent Outputs preview did not settle")

    try:
        tab.pack(fill="both", expand=True)
        tk_root.deiconify()
        settle(lambda: panel.session.loaded)
        panel.session.outputs = (RecentVideoOutput(
            job_id="recorded", video_path=str(clip_path), completed_at=None,
            bundle={"primary_path": str(clip_path), "video_paths": [str(clip_path)]},
        ),)
        panel.session.select("recorded")
        settle(lambda: panel.preview._video is not None and panel.preview._video.session.clip is not None)
        for detached in (False, True, False):
            panel.preview.detach() if detached else panel.preview.dock()
            tk_root.update()
            tab._body_scroll._canvas.yview_moveto(1.0)
            tk_root.update()
            viewport = tab._body_scroll._canvas
            left, top = viewport.winfo_rootx(), viewport.winfo_rooty()
            right, bottom = left + viewport.winfo_width(), top + viewport.winfo_height()
            if panel.winfo_height() <= viewport.winfo_height():
                assert panel.winfo_rooty() >= top
                assert panel.winfo_rooty() + panel.winfo_height() <= bottom + 1
            else:
                # At 150%, the measured panel is 453px and its viewport 361px. No scroll position can
                # contain both edges. Preserve the normal-size containment contract; at stress scale,
                # require each complete viewing unit and every real action to remain reachable.
                assert font_scale == 1.5
            for unit in (panel.tree, panel.preview):
                assert unit.winfo_height() <= viewport.winfo_height()
                tab._body_scroll.reveal(unit)
                tk_root.update()
                assert left <= unit.winfo_rootx()
                assert unit.winfo_rootx() + unit.winfo_width() <= right + 1
                assert top <= unit.winfo_rooty()
                assert unit.winfo_rooty() + unit.winfo_height() <= bottom + 1
            for control in (panel.refresh_button, panel.open_button, panel.reveal_button,
                            panel.movie_button, panel.preview.show_button, panel.preview.detach_button):
                # Exercise the production FocusIn router, starting with the panel scrolled away.
                tk_root.focus_force()
                viewport.yview_moveto(0.0)
                tk_root.update()
                control.focus_force()
                tk_root.update()
                assert tk_root.focus_get() is control
                assert control.winfo_ismapped()
                assert left <= control.winfo_rootx()
                assert control.winfo_rootx() + control.winfo_width() <= right + 1
                assert top <= control.winfo_rooty()
                assert control.winfo_rooty() + control.winfo_height() <= bottom + 1
            assert panel.preview.current_path() == str(clip_path)
            assert not panel.preview._zoom_bar.winfo_manager()
            if detached:
                labels = [child.cget("text") for child in panel.preview._window.winfo_children()[0].winfo_children() if "text" in child.keys()]
                assert "Show media" in labels and "Return to dock" in labels
                window = panel.preview._window
                for control in window.winfo_children()[0].winfo_children():
                    if "text" in control.keys() and control.cget("text") in ("Show media", "Return to dock"):
                        assert control.winfo_ismapped()
                        assert window.winfo_rootx() <= control.winfo_rootx()
                        assert control.winfo_rootx() + control.winfo_width() <= window.winfo_rootx() + window.winfo_width()
                        assert window.winfo_rooty() <= control.winfo_rooty()
                        assert control.winfo_rooty() + control.winfo_height() <= window.winfo_rooty() + window.winfo_height()
            else:
                assert panel.preview._video.session.clip is not None
                assert panel.preview._video._tick_id is not None
                assert "Bounded preview" in panel.preview._video.caption.cget("text")
    finally:
        tab.destroy()
        tk_root.tk.call("tk", "scaling", base)
        tk_root.withdraw()
