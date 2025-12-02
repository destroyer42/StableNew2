"""GUI V2 randomizer panel structure tests."""

from __future__ import annotations


def test_randomizer_panel_widgets_and_roundtrip(gui_app_with_dummies):
    app, _controller, _config_manager = gui_app_with_dummies
    panel = app.randomizer_panel_v2

    assert panel.variant_mode_var.get() in {"off", "fanout", "rotate"}
    assert "model" in panel.matrix_vars
    assert "hypernetwork" in panel.matrix_vars
    assert panel.fanout_var.get() == "1"

    config = {
        "pipeline": {
            "variant_mode": "rotate",
            "variant_fanout": 3,
            "model_matrix": ["model_a", "model_b"],
            "hypernetworks": [{"name": "hyper_a", "strength": 0.5}],
        }
    }
    panel.load_from_config(config)
    options = panel.get_randomizer_options()

    assert options["variant_mode"] == "rotate"
    assert options["fanout"] == 3
    assert options["model_matrix"] == ["model_a", "model_b"]
    assert options["matrix"]["hypernetwork"][0]["name"] == "hyper_a"

    panel.update_variant_count(4)
    assert panel.get_variant_count() == 4
    assert "Total variants: 4" in panel.variant_count_var.get()
