"""MEC-901/905: the catalog's Compatibility Probe dialog, options and confirmed admission."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.gui.controllers import model_evidence_probe as probe_module
from src.gui.controllers.model_evidence_probe import probe_options, sidecar_base_model
from src.gui.views import model_evidence_window as module
from src.gui.views.compatibility_probe_dialog import CompatibilityProbeDialog
from src.gui.views.model_evidence_window import ModelEvidenceWindow
from src.learning.compatibility_probe import RECIPES
from src.learning.model_run_history import ModelRunSummary
from tests.gui_v2.test_model_evidence_catalog_900 import census_row, make_owner, pump

RESOURCES = {
    "samplers": ["Euler a", "Euler", "DPM++ 2M"],
    "schedulers": ["automatic", "Karras", "SGM Uniform"],
}
HISTORY = ModelRunSummary(
    completed=32,
    settings=(
        ("sampler_name", (("DPM++ 2M", 30),)),
        ("scheduler", (("Karras", 30),)),
        ("steps", (("36", 30),)),
        ("cfg_scale", (("8.1", 30),)),
    ),
    resolution=(("1024x1024", 30),),
)


def test_options_put_your_usual_settings_first_and_match_backend_spelling():
    options = probe_options(
        family="sdxl", variant="turbo", base_model_hint="", history=HISTORY, resources=RESOURCES
    )
    assert options.preselected[0] == "history"
    usual = next(r for r in options.recipes if r.key == "history")
    assert usual.settings["steps"] == 36 and usual.settings["cfg_scale"] == 8.1
    assert "sdxl_turbo" in options.preselected and len(options.preselected) <= 4
    sd15 = next(r for r in options.recipes if r.key == "sd15")
    assert sd15.settings["scheduler"] == "automatic"  # the backend's own spelling, not a substitute
    assert any("Simple" in problem for problem in options.unavailable)  # flux's scheduler is missing
    assert any("not a recommendation" in note for note in options.notes)


def test_options_without_backend_inventory_keep_names_and_say_so():
    options = probe_options(
        family="unknown", variant="", base_model_hint="SD 1.5", history=None, resources={}
    )
    assert options.preselected[0] == "sd15" and not options.unavailable
    assert any("not loaded" in note for note in options.notes)


def test_sidecar_base_model_is_read_from_either_sidecar_name(tmp_path):
    model = tmp_path / "m.safetensors"
    model.write_bytes(b"x")
    assert sidecar_base_model(model) == ""
    (tmp_path / "m.civitai.info").write_text(json.dumps({"baseModel": "Pony"}), encoding="utf-8")
    assert sidecar_base_model(model) == "Pony"


def dialog(tk_root, queued=None):
    return CompatibilityProbeDialog(
        tk_root,
        model="test.safetensors",
        sha256="a" * 64,
        family="sdxl",
        recipes=[RECIPES["sdxl"], RECIPES["sd15"], RECIPES["flux"]],
        preselected=["sdxl", "sd15"],
        unavailable=[],
        notes=["note"],
        on_queue=(queued or []).append,
    )


def test_dialog_totals_and_validates_the_design(tk_root):
    view = dialog(tk_root)
    assert view.total.get() == "2 recipes × 2 images = 4 images"
    assert view.design().total_images == 4
    view.selected["sd15"].set(False)
    with pytest.raises(ValueError, match="Choose 2"):
        view.design()
    view.selected["flux"].set(True)
    view.images.set(3)
    view._update_total()
    assert view.total.get() == "2 recipes × 3 images = 6 images"
    view.destroy()


def probe_window(tk_root, monkeypatch, *, confirm=True):
    calls = SimpleNamespace(prepared=[], admitted=[], asked=[])
    batch = SimpleNamespace(
        confirmation="Queue this probe?", experiments=(SimpleNamespace(records=("njr",)),)
    )

    def prepare(service, design, context, cancelled):
        calls.prepared.append((design, context))
        return batch

    service = SimpleNamespace(
        admit=lambda b, context, confirmed, cancelled: calls.admitted.append((b, confirmed))
        or SimpleNamespace(describe=lambda: "Confirmed admissions: 1 experiments")
    )
    monkeypatch.setattr(probe_module, "prepare_probe", prepare)
    monkeypatch.setattr(
        module.messagebox, "askyesno", lambda *a, **k: calls.asked.append(a) or confirm
    )
    window = ModelEvidenceWindow(make_owner(tk_root, qualification_batch=service))
    window.census = {"assets": [census_row(), census_row("models/Stable-diffusion/b.safetensors")]}
    window._render_assets()
    window._capture_planning_inputs = lambda row=None: ("inputs", row["relative"])
    window._context = lambda inputs: SimpleNamespace(inputs=inputs)
    view = dialog(tk_root)
    view.relative = "models/Stable-diffusion/test.safetensors"
    window._probe_dialog = view
    return window, view, calls, batch


def test_queue_probe_admits_only_after_confirmation(tk_root, monkeypatch):
    window, view, calls, batch = probe_window(tk_root, monkeypatch)
    window._queue_probe(view)
    pump(tk_root, lambda: bool(calls.admitted))
    design, context = calls.prepared[0]
    assert design.sha256 == "a" * 64 and len(design.recipes) == 2
    assert context.inputs == ("inputs", "models/Stable-diffusion/test.safetensors")
    assert calls.asked and calls.admitted == [(batch, True)]
    assert "Experiment Library" in view.text.get("1.0", "end")
    window._close()


def test_declined_probe_admits_nothing(tk_root, monkeypatch):
    window, view, calls, _batch = probe_window(tk_root, monkeypatch, confirm=False)
    window._queue_probe(view)
    pump(tk_root, lambda: "not confirmed" in view.status.get())
    assert calls.admitted == []
    window._close()


def test_selecting_another_checkpoint_makes_the_probe_stale(tk_root, monkeypatch):
    window, view, calls, _batch = probe_window(tk_root, monkeypatch)
    window._plan = lambda **_kw: None
    window.tree.selection_set("1")
    window._selected_model_changed()
    assert view._stale and str(view.queue_button.cget("state")) == "disabled"
    window._queue_probe(view)
    tk_root.update()
    assert calls.prepared == []
    window._close()
