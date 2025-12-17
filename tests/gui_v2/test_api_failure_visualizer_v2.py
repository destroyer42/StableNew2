import tkinter as tk

import pytest

from src.gui.panels_v2.api_failure_visualizer_v2 import ApiFailureVisualizerV2
from src.utils.api_failure_store_v2 import clear_api_failures, record_api_failure


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_visualizer_displays_failure(tk_root):
    clear_api_failures()
    record_api_failure(
        stage="upscale",
        endpoint="/sdapi/v1/extra-single-image",
        method="POST",
        payload={
            "image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
        },
        status_code=500,
        response_text="Invalid encoded image",
        error_message="HTTPError",
    )
    panel = ApiFailureVisualizerV2(tk_root)
    panel.refresh()
    assert panel._tree.get_children()
    panel._tree.selection_set(panel._tree.get_children()[0])
    panel._show_selected()
    assert "extra-single-image" in panel._detail_label.cget("text")
    panel.destroy()
