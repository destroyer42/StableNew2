"""Storyboard tab layout: the viewer fits, the tree scrolls, the selection and Continue target are clear.

Design: docs/superpowers/specs/2026-11-24-storyboard-viewer-tree-layout-design.md
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest
from PIL import Image

from src.gui import theme_v2
from src.gui.app_state_v2 import AppStateV2
from src.gui.design_system_v2 import SELECTED_CARD_FRAME, Colors
from src.gui.view_contracts.storyboard_tree_contract import Card, Column
from src.gui.views.storyboard_tab_frame_v2 import StoryboardTabFrameV2
from src.gui.widgets.mirrored_text_v2 import FOCUS_LINES, FOCUS_SHRINK_MS, REST_LINES, MirroredText
from src.gui.widgets.storyboard_columns_v2 import StoryboardColumnsV2
from src.gui.widgets.storyboard_viewer_v2 import MIN_IMAGE_HEIGHT, StoryboardViewerV2, fit_size
from src.services.ui_state_store import UIStateStore
from src.video.sequence_plan import ROOT_PARENT
from tests.gui_v2.storyboard_tab_helpers import FakeService, fake_controller

pytestmark = pytest.mark.gui


# ---------------------------------------------------------------- Task 1: selected-card style


def test_selected_card_style_has_a_thick_accent_border(tk_root):
    style = theme_v2.apply_theme(tk_root)
    assert style.lookup(SELECTED_CARD_FRAME, "bordercolor") == Colors.PRIMARY_ACCENT
    assert int(style.lookup(SELECTED_CARD_FRAME, "borderwidth")) >= 3
    assert int(style.lookup("Card.TFrame", "borderwidth")) == 1
    assert isinstance(style, ttk.Style)


# ---------------------------------------------------------------- Task 2: the viewer fits its picture


def _settle(root, seconds: float = 0.15) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)


def _viewer(root, width: int = 400, height: int = 300) -> StoryboardViewerV2:
    root.geometry(f"{width}x{height}")
    root.deiconify()  # a withdrawn window never maps its children, so no real sizes
    viewer = StoryboardViewerV2(
        root,
        on_frame=lambda _i: None,
        on_continue=lambda _i: None,
        readout=lambda i: f"frame {i + 1}",
    )
    viewer.pack(fill="both", expand=True)
    viewer.set_cut(5, (), 16)
    _settle(root)
    return viewer


def test_fit_size_keeps_aspect_and_never_upscales():
    assert fit_size((800, 400), (400, 400)) == (400, 200)
    assert fit_size((16, 8), (400, 400)) == (16, 8)


def test_fit_size_never_returns_zero():
    for source, box in (((800, 400), (0, 0)), ((0, 0), (10, 10)), ((800, 400), (-5, 3))):
        width, height = fit_size(source, box)
        assert width >= 1 and height >= 1


def test_viewer_picture_is_scaled_to_a_short_window(tk_root):
    viewer = _viewer(tk_root, 400, 300)
    viewer.show_image(Image.new("RGB", (800, 600)))
    _settle(tk_root)
    assert viewer._photo is not None
    assert viewer._photo.height() <= viewer.image_area.winfo_height()
    assert viewer._photo.width() <= viewer.image_area.winfo_width()
    for control in (viewer.slider, viewer.continue_button):
        assert control.winfo_ismapped()
        assert control.winfo_y() + control.winfo_height() <= viewer.winfo_height()


def test_viewer_keeps_controls_when_window_is_too_short_for_the_minimum(tk_root):
    viewer = _viewer(tk_root, 400, 120)
    viewer.show_image(Image.new("RGB", (800, 600)))
    _settle(tk_root)
    assert viewer.image_area.winfo_height() >= 1
    assert MIN_IMAGE_HEIGHT >= 100
    assert viewer.slider.winfo_ismapped() and viewer.continue_button.winfo_ismapped()


def test_viewer_rescales_when_resized(tk_root):
    viewer = _viewer(tk_root, 400, 300)
    viewer.show_image(Image.new("RGB", (800, 600)))
    _settle(tk_root)
    small = viewer._photo.height()
    tk_root.geometry("400x600")
    _settle(tk_root, 0.3)
    assert viewer._photo.height() > small


def test_hidden_viewer_drops_a_late_frame(tk_root):
    viewer = _viewer(tk_root)
    viewer.set_media_visible(False)
    viewer.show_image(Image.new("RGB", (8, 8)))
    assert viewer._photo is None


# ---------------------------------------------------------------- Task 3: the take tree scrolls and shows the selection


def _card(take_id: str, *, selected: bool = False, on_path: bool = False) -> Card:
    return Card(
        take_id=take_id,
        label=f"Take {take_id}",
        excerpt="a prompt excerpt",
        status_text="completed",
        mark="none",
        on_path=on_path,
        selected=selected,
    )


def _tree(*, selected: str = "", on_path: tuple[str, ...] = ()) -> tuple[Column, ...]:
    tall = Column(
        "Shot 2",
        tuple(
            _card(f"c{n}", selected=f"c{n}" == selected, on_path=f"c{n}" in on_path)
            for n in range(1, 7)
        ),
    )
    others = tuple(Column(f"Shot {n}", (_card(f"d{n}"),)) for n in range(3, 7))
    return (Column("Shot 1", (_card("root"),)), tall, *others)


def _columns(root, columns: tuple[Column, ...], width: int = 600, height: int = 200):
    root.geometry(f"{width}x{height}")
    root.deiconify()
    widget = StoryboardColumnsV2(root, on_select=lambda _t: None, on_mark=lambda _t, _m: None)
    widget.pack(fill="both", expand=True)
    widget.render(columns)
    _settle(root)
    return widget


def _inside_viewport(widget: StoryboardColumnsV2, take_id: str) -> bool:
    frame, canvas = widget.card_frames[take_id], widget._canvas
    return (
        frame.winfo_rooty() >= canvas.winfo_rooty()
        and frame.winfo_rooty() + frame.winfo_height()
        <= canvas.winfo_rooty() + canvas.winfo_height()
        and frame.winfo_rootx() >= canvas.winfo_rootx()
        and frame.winfo_rootx() + frame.winfo_width() <= canvas.winfo_rootx() + canvas.winfo_width()
    )


def test_sixth_card_is_reachable_by_scrolling(tk_root):
    widget = _columns(tk_root, _tree())
    assert not _inside_viewport(widget, "c6")
    widget.see("c6")
    _settle(tk_root)
    assert _inside_viewport(widget, "c6")


def test_see_a_card_in_a_far_column(tk_root):
    widget = _columns(tk_root, _tree(), width=300)
    assert not _inside_viewport(widget, "d6")
    widget.see("d6")
    _settle(tk_root)
    assert _inside_viewport(widget, "d6")


def test_see_unknown_take_is_a_noop(tk_root):
    widget = _columns(tk_root, _tree())
    before = (widget._canvas.xview(), widget._canvas.yview())
    widget.see("nope")
    assert (widget._canvas.xview(), widget._canvas.yview()) == before


def test_selected_card_uses_the_selected_style_and_marker(tk_root):
    widget = _columns(tk_root, _tree(selected="c2", on_path=("c1", "c2")))
    frames = widget.card_frames
    assert str(frames["c2"].cget("style")) == SELECTED_CARD_FRAME
    assert str(frames["c1"].cget("style")) == "Card.TFrame"
    assert str(frames["c3"].cget("style")) == "Panel.TFrame"
    texts = [
        str(child.cget("text"))
        for child in frames["c2"].winfo_children()
        if isinstance(child, ttk.Label)
    ]
    assert any(text.startswith("▶ ") for text in texts)


def test_wheel_scrolls_vertically_and_shift_wheel_sideways(tk_root):
    widget = _columns(tk_root, _tree(), width=300)
    assert widget._on_wheel(SimpleNamespace(delta=-120, state=0)) == "break"
    assert widget._canvas.yview()[0] > 0
    assert widget._on_wheel(SimpleNamespace(delta=-120, state=1)) == "break"
    assert widget._canvas.xview()[0] > 0


def test_wheel_is_not_consumed_when_everything_fits(tk_root):
    widget = _columns(tk_root, (Column("Shot 1", (_card("root"),)),), width=600, height=400)
    assert widget._on_wheel(SimpleNamespace(delta=-120, state=0)) is None


def test_render_keeps_scroll_offsets(tk_root):
    widget = _columns(tk_root, _tree(), width=300)
    widget._canvas.yview_moveto(0.5)
    widget._canvas.xview_moveto(0.3)
    _settle(tk_root)
    before = (widget._canvas.yview()[0], widget._canvas.xview()[0])
    assert before[0] > 0 and before[1] > 0
    widget.render(_tree(selected="c3"))
    _settle(tk_root)
    after = (widget._canvas.yview()[0], widget._canvas.xview()[0])
    assert abs(after[0] - before[0]) < 0.02 and abs(after[1] - before[1]) < 0.02


# ---------------------------------------------------------------- Task 4: the pane split and the Continue banner


@pytest.fixture
def fake_service(tmp_path):
    return FakeService(tmp_path)


@pytest.fixture
def tab(tk_root, fake_service, tmp_path):
    created = StoryboardTabFrameV2(
        tk_root,
        app_controller=fake_controller(fake_service),
        app_state=AppStateV2(),
        ui_state_store=UIStateStore(tmp_path / "ui_state.json"),
    )
    created.pack(fill="both", expand=True)
    yield created
    created.destroy()


def _spy_see(tab: StoryboardTabFrameV2) -> list[str]:
    seen: list[str] = []
    real = tab.columns.see
    tab.columns.see = lambda take_id: (seen.append(take_id), real(take_id))[1]  # type: ignore[method-assign]
    return seen


def test_tree_and_body_share_a_draggable_pane(tab):
    assert [str(pane) for pane in tab.pane.panes()] == [str(tab.columns), str(tab._body)]


def test_banner_when_nothing_is_selected(tab):
    assert tab.banner_var.get() == "Nothing selected to continue from"


def test_banner_names_the_continue_target(tab, fake_service):
    tab.open_storyboard(fake_service.diner_id)
    tab.select_take("t1")
    text = tab.banner_var.get()
    assert text.startswith("Continuing from: ")
    assert tab.contract.label("t1") in text
    assert f"frame {tab.target[1] + 1}" in text


def test_banner_says_the_clip_when_the_root_is_selected(tab, fake_service):
    tab.open_storyboard(fake_service.diner_id)
    tab.select_take(ROOT_PARENT)
    assert tab.banner_var.get().startswith("Continuing from: ")
    assert tab.contract.label(ROOT_PARENT) in tab.banner_var.get()


def test_banner_follows_continue_from_this_frame(tab, fake_service):
    tab.open_storyboard(fake_service.diner_id)
    tab.select_take("t1")
    tab.viewer.seek(2)
    tab._continue_from_frame(2)
    assert f"frame {tab.target[1] + 1}" in tab.banner_var.get()
    assert tab.contract.label(tab.target[0]) in tab.banner_var.get()


def test_selecting_reveals_the_selected_card(tab, fake_service):
    tab.open_storyboard(fake_service.diner_id)
    seen = _spy_see(tab)
    tab.select_take("t3")
    assert seen == ["t3"]


def test_auto_refresh_does_not_scroll_the_tree(tab, fake_service):
    tab.open_storyboard(fake_service.diner_id)
    tab.select_take("t3")
    seen = _spy_see(tab)
    tab.refresh()
    assert seen == []


def test_hidden_selected_take_does_not_break_the_tree_or_banner(tab, fake_service):
    tab.open_storyboard(fake_service.diner_id)
    tab.select_take("t2")  # dropped, and "Show dropped" is off
    assert "t2" not in tab.columns.card_take_ids()
    tab.render(reveal_selected=True)
    assert tab.banner_var.get().startswith("Continuing from: ")


def test_refresh_and_reselecting_keep_a_chosen_continue_frame(tab, fake_service):
    tab.open_storyboard(fake_service.diner_id)
    tab.select_take("t1")
    tab._continue_from_frame(2)
    chosen = tab.target
    tab.refresh()
    assert tab.target == chosen
    tab.select_take("t1")  # the same take again is not a new clip to extend
    assert tab.target == chosen


# ---------------------------------------------------------------- Task 5: roomy prompt fields, scrolling Continue panel


def _field(root, value: str = "") -> tuple[MirroredText, tk.StringVar]:
    root.deiconify()
    variable = tk.StringVar(master=root, value=value)
    field = MirroredText(root, variable)
    field.pack()
    _settle(root, 0.05)
    return field, variable


def _contents(field: tk.Text) -> str:
    return field.get("1.0", "end-1c")


def test_mirrored_text_follows_the_variable(tk_root):
    field, variable = _field(tk_root, "start")
    assert _contents(field) == "start"
    variable.set("changed")
    assert _contents(field) == "changed"
    variable.set("")
    assert _contents(field) == ""


def test_typing_updates_the_variable(tk_root):
    field, variable = _field(tk_root)
    field.insert("end", "hello")
    _settle(tk_root, 0.05)
    assert variable.get() == "hello"
    field.delete("1.0", "end")
    _settle(tk_root, 0.05)
    assert variable.get() == ""


def test_enter_is_swallowed(tk_root):
    field, variable = _field(tk_root, "one line")
    field.focus_force()
    field.mark_set("insert", "end")
    field.event_generate("<Return>")
    _settle(tk_root, 0.05)
    assert _contents(field) == "one line" and variable.get() == "one line"


def test_pasted_newlines_become_spaces(tk_root):
    field, variable = _field(tk_root)
    field.insert("1.0", "a\nb\r\nc")
    _settle(tk_root, 0.05)
    assert variable.get() == "a b c" and _contents(field) == "a b c"


def test_tab_moves_focus_and_inserts_nothing(tk_root):
    first, _ = _field(tk_root, "x")
    second, _ = _field(tk_root, "y")
    first.focus_force()
    _settle(tk_root, 0.05)
    first.event_generate("<Tab>")
    _settle(tk_root, 0.05)
    assert _contents(first) == "x"
    assert tk_root.focus_get() is second


def test_field_grows_on_focus_and_shrinks_after_blur(tk_root):
    field, _ = _field(tk_root)
    assert int(field.cget("height")) == REST_LINES
    field.event_generate("<FocusIn>")
    assert int(field.cget("height")) == FOCUS_LINES
    field.event_generate("<FocusOut>")
    assert (
        int(field.cget("height")) == FOCUS_LINES
    )  # not at once: a click on the next row must not move
    _settle(tk_root, (FOCUS_SHRINK_MS + 150) / 1000)
    assert int(field.cget("height")) == REST_LINES


def test_refocusing_inside_the_delay_cancels_the_shrink(tk_root):
    field, _ = _field(tk_root)
    field.event_generate("<FocusIn>")
    field.event_generate("<FocusOut>")
    field.event_generate("<FocusIn>")
    _settle(tk_root, (FOCUS_SHRINK_MS + 150) / 1000)
    assert int(field.cget("height")) == FOCUS_LINES


def test_destroying_a_field_leaves_no_pending_shrink(tk_root):
    field, variable = _field(tk_root)
    field.event_generate("<FocusIn>")
    field.event_generate("<FocusOut>")
    field.destroy()
    variable.set("after destroy")  # the trace must be gone
    _settle(tk_root, (FOCUS_SHRINK_MS + 100) / 1000)


def _open_tab(tab, fake_service, width: int = 900, height: int = 520) -> None:
    tab.winfo_toplevel().geometry(f"{width}x{height}")
    tab.winfo_toplevel().deiconify()
    tab.open_storyboard(fake_service.diner_id)
    _settle(tab.winfo_toplevel(), 0.2)


def test_rows_use_prompt_fields_and_set_rows_shows_them(tab, fake_service):
    _open_tab(tab, fake_service)
    tab.set_rows(["one", "two"])
    assert all(isinstance(row.prompt_entry, MirroredText) for row in tab._row_widgets)
    assert [_contents(row.prompt_entry) for row in tab._row_widgets] == ["one", "two"]
    tab._row_widgets[0].negative_entry.insert("1.0", "blurry")
    _settle(tab.winfo_toplevel(), 0.05)
    rows, problems = tab._continue_rows()
    assert (rows[0].prompt, rows[0].negative_prompt, rows[1].prompt) == ("one", "blurry", "two")
    assert problems == []


def test_six_rows_scroll_instead_of_clipping_and_queue_stays_reachable(tab, fake_service):
    _open_tab(tab, fake_service, height=480)
    while not tab.rows_widget.full:
        tab.add_row("a prompt")
    for row in tab._row_widgets:
        row.prompt_entry.event_generate("<FocusIn>")  # every field grown
    _settle(tab.winfo_toplevel(), 0.2)
    assert tab.continue_scroll.has_scroll_overflow()
    host = tab.continue_host
    for button in (tab.queue_button, tab.preview_button):
        assert button.winfo_ismapped()
        assert (
            button.winfo_rooty() + button.winfo_height() <= host.winfo_rooty() + host.winfo_height()
        )
