"""Real Tk routing: explicit work, main-thread delivery and close/cancel suppression."""

import threading
import time
from tkinter import ttk

from src.assets.registry import AssetRegistry
from src.gui.views.model_evidence_window import ModelEvidenceWindow


def test_catalog_opens_without_scan_and_filters_relative_assets(tk_root, monkeypatch):
    calls = []
    monkeypatch.setattr(AssetRegistry, "observe", lambda *a, **kw: calls.append(1))
    owner = ttk.Frame(tk_root)
    owner._on_open_experiment_library = lambda: None
    window = ModelEvidenceWindow(owner)
    assert not calls and not window._busy
    window.census = {
        "assets": [
            {
                "kind": "checkpoint",
                "relative": "models/Stable-diffusion/test.safetensors",
                "identity_status": "pending",
                "family": "unknown",
                "size": 10,
            }
        ]
    }
    window._render_assets()
    assert len(window.tree.get_children()) == 1
    window.filter.set("no match")
    assert not window.tree.get_children()
    window._close()


def test_worker_delivers_on_tk_thread_and_suppresses_stale_results(tk_root):
    owner = ttk.Frame(tk_root)
    owner._on_open_experiment_library = lambda: None
    window = ModelEvidenceWindow(owner)
    received = []
    window._work(
        lambda _cancelled, _progress: threading.get_ident(),
        lambda worker_id: received.append((worker_id, threading.get_ident())),
    )
    deadline = time.monotonic() + 3
    while window._busy and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.01)
    assert received and received[0][0] != received[0][1] == threading.get_ident()
    window._events.put(
        (window._generation - 1, "done", "stale", lambda value: received.append(value))
    )
    window._poll()
    assert len(received) == 1
    window._close()


def test_lookup_disclosure_is_before_worker_start(tk_root, monkeypatch):
    from src.generation_profiles.evidence_refresh import Lookup

    owner = ttk.Frame(tk_root)
    owner._on_open_experiment_library = lambda: None
    window = ModelEvidenceWindow(owner)
    shown = []
    monkeypatch.setattr(
        "src.gui.views.model_evidence_window.messagebox.askyesno",
        lambda title, text, **kw: shown.append(text) or False,
    )
    window._lookup_source(Lookup("civitai", "a" * 64))
    assert "a" * 64 in shown[0] and not window._busy
    window._close()


def test_parent_destruction_cancels_worker_with_full_progress_queue(tk_root):
    owner = ttk.Frame(tk_root)
    owner._on_open_experiment_library = lambda: None
    window = ModelEvidenceWindow(owner)
    waiting, finished = threading.Event(), threading.Event()

    def worker(cancelled, progress):
        for _ in range(100):
            progress("bounded progress")
        waiting.set()
        cancelled_event = window._cancel
        cancelled_event.wait(2)
        assert cancelled()
        finished.set()
        return None

    window._work(worker, lambda value: None)
    assert waiting.wait(2)
    window.destroy()  # Parent teardown uses this path, bypassing WM_DELETE_WINDOW.
    assert window._closed and window._cancel.is_set() and finished.wait(2)
