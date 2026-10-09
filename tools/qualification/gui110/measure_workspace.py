"""Non-generating Windows/Tk workspace measurement for PR-GUI-110.

Builds the real ``MainWindowV2`` with the fake pipeline runner (no backend, no generation, no network),
isolated from the operator's workspace state, then measures usable scroll-viewport heights, primary-action
visibility, horizontal clipping and (optionally) screenshots for each long-form tab under a chosen set of
window sizes and Tk scaling factors. Run the same command on the baseline and on the changed SHA and diff
the two reports.

    python tools/qualification/gui110/measure_workspace.py --label after --out <dir> [--screenshots]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STABLENEW_TEST_MODE", "1")

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

DEFAULT_SIZES = ((1280, 680), (1342, 680), (1896, 984), (1900, 1000))
# (tab attribute on MainWindowV2, tab title fragment, scroll attribute on the tab frame, primary action attribute)
TABS = (
    ("review_tab", "Review", "_workspace_scroll", "reprocess_all_button"),
    ("svd_tab", "SVD", "_body_scroll", "animate_btn"),
    ("video_workflow_tab", "Video Workflow", "_body_scroll", "queue_workflow_button"),
)
_ACTIONABLE = (ttk.Button, ttk.Checkbutton, ttk.Combobox, ttk.Entry, ttk.Radiobutton, ttk.Spinbox, tk.Button)


def _isolate(workspace: Path) -> None:
    """Keep every process-wide mutable GUI state file inside a temporary workspace."""

    os.environ["STABLENEW_PROMPTPACK_DIR"] = str(workspace / "promptpacks")
    import src.gui.preview_panel_v2 as preview_panel_v2
    import src.gui.sidebar_panel_v2 as sidebar_panel_v2
    import src.photo_optimize.store as photo_store
    import src.services.ui_state_store as ui_state_store
    from src.controller import webui_connection_controller as connection

    ui_state_store.UI_STATE_PATH = workspace / "state" / "ui_state.json"
    ui_state_store._global_store = None
    photo_store._global_store = None
    sidebar_panel_v2.SIDEBAR_STATE_PATH = workspace / "state" / "sidebar_state.json"
    preview_panel_v2.PREVIEW_STATE_PATH = workspace / "state" / "preview_panel_state.json"

    def _ready(self: Any, autostart: bool = True) -> Any:
        self._set_state(connection.WebUIConnectionState.READY)
        return connection.WebUIConnectionState.READY

    connection.WebUIConnectionController.ensure_connected = _ready  # type: ignore[method-assign]


def _make_images(directory: Path, count: int = 3) -> list[Path]:
    from PIL import Image, ImageDraw

    paths = []
    for index in range(count):
        image = Image.new("RGB", (768, 1024), (40 + index * 40, 60, 110))
        ImageDraw.Draw(image).rectangle((96, 128, 672, 896), outline=(240, 240, 240), width=6)
        path = directory / f"sample_{index + 1}.png"
        image.save(path)
        paths.append(path)
    return paths


def _descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack = list(widget.winfo_children())
    while stack:
        child = stack.pop()
        found.append(child)
        stack.extend(child.winfo_children())
    return found


def _is_under(widget: tk.Misc, ancestor: tk.Misc) -> bool:
    node: tk.Misc | None = widget
    while node is not None:
        if node is ancestor:
            return True
        node = getattr(node, "master", None)
    return False


def _rect(widget: tk.Misc) -> tuple[int, int, int, int]:
    return (
        widget.winfo_rootx(),
        widget.winfo_rooty(),
        widget.winfo_rootx() + widget.winfo_width(),
        widget.winfo_rooty() + widget.winfo_height(),
    )


def _clipped_controls(tab: tk.Misc, scroll: Any) -> list[str]:
    """Mapped actionable controls cut off horizontally, or cut off vertically outside a scroll region."""

    tab_left, tab_top, tab_right, tab_bottom = _rect(tab)
    clipped: list[str] = []
    for widget in _descendants(tab):
        if not isinstance(widget, _ACTIONABLE) or not widget.winfo_ismapped() or widget.winfo_width() <= 1:
            continue
        left, top, right, bottom = _rect(widget)
        under_scroll = scroll is not None and _is_under(widget, scroll.inner)
        if right > tab_right + 1 or left < tab_left - 1:
            clipped.append(f"{widget.winfo_class()}:{widget.winfo_pathname(widget.winfo_id())}:x")
        elif not under_scroll and bottom > tab_bottom + 1:
            clipped.append(f"{widget.winfo_class()}:{widget.winfo_pathname(widget.winfo_id())}:y")
    return clipped


def _visible_without_scrolling(widget: tk.Misc, tab: tk.Misc, scroll: Any) -> bool:
    scroll._canvas.yview_moveto(0.0)
    scroll._canvas.update_idletasks()
    if not widget.winfo_ismapped() or widget.winfo_height() <= 1:
        return False
    left, top, right, bottom = _rect(widget)
    if _is_under(widget, scroll.inner):
        view = _rect(scroll._canvas)
        return top >= view[1] and bottom <= view[3] + 1 and left >= view[0] and right <= view[2] + 1
    tab_rect = _rect(tab)
    return top >= tab_rect[1] and bottom <= tab_rect[3] + 1


def _select_tab(window: Any, fragment: str) -> None:
    notebook = window.center_notebook
    for index in range(notebook.index("end")):
        if fragment in notebook.tab(index, "text"):
            notebook.select(index)
            return
    raise RuntimeError(f"tab not found: {fragment}")


def _pump(root: tk.Tk, seconds: float = 0.25) -> None:
    """Run the Tk main loop briefly: worker-thread callbacks (async thumbnails) only land inside a mainloop."""

    root.after(max(1, int(seconds * 1000)), root.quit)
    root.mainloop()


def _grab(root: tk.Tk, target: Path) -> None:
    from PIL import ImageGrab

    root.attributes("-topmost", True)
    root.lift()
    _pump(root, 0.4)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()), all_screens=True).save(target)
    root.attributes("-topmost", False)


def _build_window(root: tk.Tk) -> tuple[Any, Any]:
    """The real MainWindowV2 (with the operator log panel) over a fake runner: nothing can generate."""

    from src.controller.app_controller import AppController
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.main_window_v2 import MainWindowV2
    from tests.helpers.fake_pipeline_runner import FakePipelineRunner

    controller = AppController(None, threaded=False, pipeline_runner=FakePipelineRunner())
    controller.app_state = AppStateV2()
    window = MainWindowV2(
        root,
        app_state=controller.app_state,
        app_controller=controller,
        pipeline_controller=controller,
        gui_log_handler=controller.get_gui_log_handler(),
    )
    return controller, window


def _measure_condition(root: tk.Tk, window: Any, images: list[Path], scale_factor: float, width: int, height: int,
                       label: str, out: Path, screenshots: bool) -> dict[str, Any]:
    root.geometry(f"{width}x{height}+0+0")
    _pump(root, 0.3)
    root.geometry(f"{width}x{height}+0+0")
    _pump(root, 0.3)
    condition: dict[str, Any] = {
        "scaling_factor": scale_factor,
        "requested": [width, height],
        "root": [root.winfo_width(), root.winfo_height()],
        "bottom_zone_height": window.bottom_zone.winfo_height(),
        "tabs": {},
    }
    for attr, fragment, scroll_attr, action_attr in TABS:
        tab = getattr(window, attr)
        _select_tab(window, fragment)
        if attr == "review_tab":
            tab._set_selected_images(images)
            tab._show_image(images[0])
        _pump(root, 0.35)
        scroll = getattr(tab, scroll_attr)
        action = getattr(tab, action_attr)
        canvas = scroll._canvas
        condition["tabs"][attr] = {
            "tab_height": tab.winfo_height(),
            "scroll_viewport_height": canvas.winfo_height(),
            "scroll_viewport_width": canvas.winfo_width(),
            "content_height": scroll.inner.winfo_reqheight(),
            "overflow": bool(scroll.has_scroll_overflow()),
            "fixed_chrome_height": tab.winfo_height() - canvas.winfo_height(),
            "primary_action": action_attr,
            "primary_action_visible_without_scrolling": _visible_without_scrolling(action, tab, scroll),
            "clipped_controls": _clipped_controls(tab, scroll),
        }
        if screenshots and scale_factor == 1.0 and (width, height) in {(1342, 680), (1896, 984)}:
            shots = out / "screenshots"
            shots.mkdir(parents=True, exist_ok=True)
            _grab(root, shots / f"{label}_{attr}_{width}x{height}.png")
    return condition


def measure(label: str, out: Path, sizes: tuple[tuple[int, int], ...], scalings: tuple[float, ...], screenshots: bool) -> dict[str, Any]:
    workspace = Path(tempfile.mkdtemp(prefix="gui110-measure-"))
    _isolate(workspace)
    images = _make_images(workspace)
    report: dict[str, Any] = {"label": label, "conditions": []}
    for scale_factor in scalings:
        root = tk.Tk()
        base_scaling = float(root.tk.call("tk", "scaling"))
        # Scaling must be set before the widgets (and their scaled fonts/paddings) are built.
        root.tk.call("tk", "scaling", base_scaling * scale_factor)
        report.update(
            tk_patchlevel=str(root.tk.call("info", "patchlevel")),
            base_scaling=base_scaling,
            screen=[root.winfo_screenwidth(), root.winfo_screenheight()],
        )
        controller, window = _build_window(root)
        root.deiconify()
        try:
            for width, height in sizes:
                report["conditions"].append(
                    _measure_condition(root, window, images, scale_factor, width, height, label, out, screenshots)
                )
            if scale_factor == 1.0:
                _select_tab(window, "Pipeline")
                root.geometry("1342x680+0+0")
                _pump(root, 0.5)
                if screenshots:
                    shots = out / "screenshots"
                    shots.mkdir(parents=True, exist_ok=True)
                    _grab(root, shots / f"{label}_pipeline_1342x680.png")
        finally:
            try:
                window.cleanup()
            except Exception:
                pass
            root.destroy()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--scalings", type=float, nargs="+", default=[1.0, 1.5])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = measure(args.label, args.out, DEFAULT_SIZES, tuple(args.scalings), args.screenshots)
    target = args.out / f"{args.label}_workspace_measurements.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
