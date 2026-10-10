"""PR-IMG-MODELS-150: the explicit, read-only, background model readiness line (no network/hash/scan on Tk)."""

from __future__ import annotations

import threading
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.model_readiness_presenter import NOT_CHECKED, ModelReadinessPresenter
from src.image_backends.model_readiness import ModelReadiness, ReadinessStatus


def _settle(root: tk.Tk, ms: int = 150) -> None:
    root.after(ms, root.quit)
    root.mainloop()  # worker callbacks only land inside a real main loop


def _readiness(model: str, reason: str = "r") -> ModelReadiness:
    return ModelReadiness(model, ReadinessStatus.SELECTED_UNQUALIFIED, reason, (f"details for {model}.",))


@pytest.fixture
def parts(tk_root: tk.Tk):
    holder = tk.Frame(tk_root)
    holder.pack()
    panel = SimpleNamespace(model_var=tk.StringVar(master=tk_root, value="flux-2-klein-base-9b.safetensors"))
    yield tk_root, holder, panel
    holder.destroy()


def _presenter(holder, panel, *, probe, client=object()):
    return ModelReadinessPresenter(panel, holder, controller=SimpleNamespace(_api_client=client), probe=probe)


def test_nothing_runs_until_the_button_is_pressed_and_a_model_change_only_marks_stale(parts) -> None:
    root, holder, panel = parts
    probe = Mock(return_value=_readiness("x"))
    presenter = _presenter(holder, panel, probe=probe)
    panel.model_var.set("another.safetensors")
    _settle(root, 80)
    probe.assert_not_called()  # construction and selection changes never touch Forge or a file
    assert presenter.label.cget("text") == NOT_CHECKED


def test_the_probe_runs_off_the_tk_thread_and_the_verdict_is_published(parts) -> None:
    root, holder, panel = parts
    threads: list[str] = []

    def probe(client, model):
        threads.append(threading.current_thread().name)
        return _readiness(model)

    presenter = _presenter(holder, panel, probe=probe)
    presenter.button.invoke()
    assert "Checking" in presenter.label.cget("text")  # immediate, non-blocking feedback
    _settle(root, 300)
    assert threads and threads[0] != threading.main_thread().name  # never on the GUI thread
    text = presenter.label.cget("text")
    assert "selected but execution unqualified" in text and "flux-2-klein-base-9b.safetensors" in text


def test_a_result_for_a_model_that_is_no_longer_selected_is_dropped(parts) -> None:
    root, holder, panel = parts
    release = threading.Event()

    def probe(client, model):
        release.wait(timeout=5)
        return _readiness(model)

    presenter = _presenter(holder, panel, probe=probe)
    presenter.button.invoke()
    panel.model_var.set("different.safetensors")  # the operator moved on while the check was in flight
    release.set()
    _settle(root, 300)
    assert presenter.label.cget("text") == NOT_CHECKED  # the obsolete answer never overwrote the newer state


def test_latest_request_wins_when_an_older_check_finishes_late(parts) -> None:
    root, holder, panel = parts
    gates = [threading.Event(), threading.Event()]
    calls: list[int] = []

    def probe(client, model):
        index = len(calls)
        calls.append(index)
        gates[index].wait(timeout=5)
        return _readiness(model, reason=f"call{index}")

    presenter = _presenter(holder, panel, probe=probe)
    presenter.button.invoke()
    presenter.button.invoke()
    gates[1].set()
    _settle(root, 200)
    gates[0].set()  # the older request finishes after the newer one
    _settle(root, 200)
    assert len(calls) == 2
    assert presenter.label.cget("text").startswith("Discovered")  # the newer verdict stands, once


def test_missing_connection_empty_selection_probe_failure_and_destroy_are_all_safe(parts) -> None:
    root, holder, panel = parts
    presenter = ModelReadinessPresenter(panel, holder, controller=SimpleNamespace(), probe=Mock())
    presenter.button.invoke()
    assert "no WebUI connection" in presenter.label.cget("text")

    panel.model_var.set("")
    presenter.check()
    assert "select a model" in presenter.label.cget("text")

    panel.model_var.set("m.safetensors")
    failing = _presenter(holder, panel, probe=Mock(side_effect=RuntimeError("boom")))
    failing.check()
    _settle(root, 300)
    assert "check failed" in failing.label.cget("text")

    late = _presenter(holder, panel, probe=lambda client, model: _readiness(model))
    late.check()
    holder.destroy()  # a callback arriving after destruction must not raise
    _settle(root, 200)


def test_the_base_generation_panel_exposes_the_check_without_touching_the_endpoint(tk_root: tk.Tk) -> None:
    from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2

    client = Mock()
    panel = BaseGenerationPanelV2(tk_root, controller=SimpleNamespace(_api_client=client))
    try:
        assert panel._model_readiness.label.cget("text") == NOT_CHECKED
        assert panel._model_readiness.button.winfo_exists()
        assert client.method_calls == []  # constructing the panel performed no endpoint call at all
    finally:
        panel.destroy()
