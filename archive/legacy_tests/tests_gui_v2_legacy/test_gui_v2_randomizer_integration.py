"""Randomizer adapter + GUI wiring tests for V2."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

randomizer_adapter = importlib.import_module("src.gui_v2.randomizer_adapter")


def _flush(root):
    root.update_idletasks()
    root.update()


def test_randomizer_adapter_imports_without_tk(monkeypatch):
    module_name = "src.gui_v2.randomizer_adapter"
    sys.modules.pop(module_name, None)
    before = set(sys.modules.keys())
    module = importlib.import_module(module_name)
    globals()["randomizer_adapter"] = module
    added = set(sys.modules.keys()) - before
    assert "tkinter" not in added


def test_adapter_generates_variants_from_matrix_entries():
    base_config = {"txt2img": {"model": "base_model"}}
    options = {"variant_mode": "fanout", "fanout": 2, "model_matrix": ["model_a", "model_b"]}

    result = randomizer_adapter.build_randomizer_plan(base_config, options)

    assert result.variant_count == 4
    models = [cfg["txt2img"]["model"] for cfg in result.configs]
    assert models[:2] == ["model_a", "model_a"]
    assert result.options["model_matrix"] == ["model_a", "model_b"]


def test_gui_run_uses_first_variant(gui_app_with_dummies):
    app, controller, _cfg_manager = gui_app_with_dummies
    app.api_connected = True
    app._apply_run_button_state()
    app._get_selected_packs = lambda: [SimpleNamespace(name="pack1", stem="pack1")]

    panel = app.randomizer_panel_v2
    panel.variant_mode_var.set("fanout")
    panel.matrix_vars["model"].set("model_x, model_y")
    panel.matrix_vars["hypernetwork"].set("hyper_a")
    _flush(app.root)

    run_button = getattr(app, "run_button", app.run_pipeline_btn)
    run_button.invoke()

    assert controller.start_calls == 1
    recorded_cfg = controller.last_run_config
    assert recorded_cfg
    assert recorded_cfg["txt2img"]["model"] == "model_x"

    plan_result = getattr(app, "_last_randomizer_plan_result", None)
    assert plan_result is not None
    assert plan_result.variant_count == panel.get_variant_count()
