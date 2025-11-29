"""Variant count preview behavior tests."""

from __future__ import annotations

from src.gui_v2.randomizer_adapter import compute_variant_count


def _flush(root):
    root.update_idletasks()
    root.update()


def test_variant_count_label_tracks_matrix_and_fanout(gui_app_with_dummies):
    app, _controller, _cfg_manager = gui_app_with_dummies
    panel = app.randomizer_panel_v2

    panel.matrix_vars["model"].set("model_a, model_b")
    panel.matrix_vars["hypernetwork"].set("hyper_a, hyper_b")
    _flush(app.root)

    assert panel.get_variant_count() == 4

    panel.fanout_var.set("2")
    _flush(app.root)
    assert panel.get_variant_count() == 8

    options = panel.get_randomizer_options()
    base_config = getattr(app, "current_config", {}) or {}
    assert compute_variant_count(base_config, options) == panel.get_variant_count()
