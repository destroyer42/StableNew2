"""Storyboard tab layout: the viewer fits, the tree scrolls, the selection and Continue target are clear.

Design: docs/superpowers/specs/2026-11-24-storyboard-viewer-tree-layout-design.md
"""

from __future__ import annotations

from tkinter import ttk

import pytest

from src.gui import theme_v2
from src.gui.design_system_v2 import SELECTED_CARD_FRAME, Colors

pytestmark = pytest.mark.gui


# ---------------------------------------------------------------- Task 1: selected-card style


def test_selected_card_style_has_a_thick_accent_border(tk_root):
    style = theme_v2.apply_theme(tk_root)
    assert style.lookup(SELECTED_CARD_FRAME, "bordercolor") == Colors.PRIMARY_ACCENT
    assert int(style.lookup(SELECTED_CARD_FRAME, "borderwidth")) >= 3
    assert int(style.lookup("Card.TFrame", "borderwidth")) == 1
    assert isinstance(style, ttk.Style)


# ---------------------------------------------------------------- Task 2: the viewer fits its picture

import time  # noqa: E402

from PIL import Image  # noqa: E402

from src.gui.widgets.storyboard_viewer_v2 import MIN_IMAGE_HEIGHT, StoryboardViewerV2, fit_size  # noqa: E402


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

from types import SimpleNamespace  # noqa: E402

from src.gui.view_contracts.storyboard_tree_contract import Card, Column  # noqa: E402
from src.gui.widgets.storyboard_columns_v2 import StoryboardColumnsV2  # noqa: E402


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
        tuple(_card(f"c{n}", selected=f"c{n}" == selected, on_path=f"c{n}" in on_path) for n in range(1, 7)),
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
        and frame.winfo_rooty() + frame.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()
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
    texts = [str(child.cget("text")) for child in frames["c2"].winfo_children() if isinstance(child, ttk.Label)]
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
