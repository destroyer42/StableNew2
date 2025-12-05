from __future__ import annotations

import tkinter as tk
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
from src.gui.randomizer_panel_v2 import RandomizerPanelV2


class FakeController:
    def __init__(self) -> None:
        self.toggle_calls: list[bool] = []
        self.max_variant_values: list[int] = []

    def get_current_config(self) -> dict[str, Any]:
        return {"pipeline": {}}

    def on_randomization_toggled(self, enabled: bool) -> None:
        self.toggle_calls.append(enabled)

    def on_randomizer_max_variants_changed(self, value: int) -> None:
        self.max_variant_values.append(value)


@pytest.mark.gui
def test_randomizer_panel_updates_controller_and_config() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        controller = FakeController()
        panel = PipelineConfigPanel(root, controller=controller, on_change=lambda: None)

        # Check spinbox initially disabled when randomization is off
        assert panel._max_variants_spinbox is not None
        state = str(panel._max_variants_spinbox.cget("state"))
        assert "disabled" in state

        # Enable randomization and ensure controller sees the toggle
        panel.randomizer_enabled_var.set(True)
        panel._on_randomizer_toggle()
        assert controller.toggle_calls == [True]
        assert str(panel._max_variants_spinbox.cget("state")) == "normal"

        # Change max variants via the spinbox handler
        panel.max_variants_var.set(5)
        panel._on_max_variants_change()
        assert 5 in controller.max_variant_values

        config = panel.get_randomizer_config()
        assert config["randomization_enabled"] is True
        assert config["max_variants"] == 5
    finally:
        root.destroy()


# ============================================================================
# PR-045: RandomizerPanelV2 Full Card Tests
# ============================================================================


@pytest.mark.gui
def test_randomizer_panel_v2_mode_and_fanout_wiring() -> None:
    """Test that variant_mode and fanout are included in config."""
    root = tk.Tk()
    root.withdraw()
    try:
        controller = FakeController()
        panel = RandomizerPanelV2(root, controller=controller)

        # Set mode and fanout
        panel.variant_mode_var.set("rotate")
        panel.fanout_var.set("3")
        panel.randomization_enabled_var.set(True)

        config = panel.get_randomizer_config()
        assert config["variant_mode"] == "rotate"
        assert config["variant_fanout"] == 3
        assert config["randomization_enabled"] is True
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_matrix_row_parsing() -> None:
    """Test that matrix rows are parsed into config."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        # The panel should have 2 default rows (model, hypernetwork)
        assert len(panel._rows) >= 2

        # Set model matrix entries
        panel._rows[0].value_var.set("modelA, modelB, modelC")
        panel._rows[0].enabled_var.set(True)

        config = panel.get_randomizer_config()
        assert "model_matrix" in config
        assert config["model_matrix"] == ["modelA", "modelB", "modelC"]

        # Also check matrix payload
        assert "matrix" in config
        assert config["matrix"].get("model") == ["modelA", "modelB", "modelC"]
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_hypernetwork_parsing() -> None:
    """Test hypernetwork entries in name[:strength] format."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        # Set hypernetwork entries
        panel._rows[1].value_var.set("hyper1:0.5, hyper2, hyper3:1.2")
        panel._rows[1].enabled_var.set(True)

        config = panel.get_randomizer_config()
        assert "hypernetworks" in config
        hypers = config["hypernetworks"]
        assert len(hypers) == 3
        assert hypers[0] == {"name": "hyper1", "strength": 0.5}
        assert hypers[1] == {"name": "hyper2", "strength": None}
        assert hypers[2] == {"name": "hyper3", "strength": 1.2}
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_controller_callbacks() -> None:
    """Test that toggle and max variants call controller methods."""
    root = tk.Tk()
    root.withdraw()
    try:
        controller = FakeController()
        panel = RandomizerPanelV2(root, controller=controller)

        # Toggle randomization
        panel.randomization_enabled_var.set(True)
        panel._on_randomizer_toggle()
        assert True in controller.toggle_calls

        # Change max variants
        panel.max_variants_var.set(10)
        panel._on_max_variants_change()
        assert 10 in controller.max_variant_values
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_controls_state_toggle() -> None:
    """Test that controls are disabled when randomization is off."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        # Initially disabled
        panel.randomization_enabled_var.set(False)
        panel._update_controls_state()

        assert panel._max_variants_spinbox is not None
        assert "disabled" in str(panel._max_variants_spinbox.cget("state"))

        # Enable and check
        panel.randomization_enabled_var.set(True)
        panel._update_controls_state()
        assert str(panel._max_variants_spinbox.cget("state")) == "normal"
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_stats_update() -> None:
    """Test that stats vars update when randomizer is enabled."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        # Enable randomization
        panel.randomization_enabled_var.set(True)
        panel._refresh_plan_and_stats()

        # Stats should be updated (not the OFF message)
        assert "OFF" not in panel.variant_explainer_var.get()
        assert "Variants:" in panel.variant_count_var.get()
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_load_from_config() -> None:
    """Test loading panel state from a config dict."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        config = {
            "randomization_enabled": True,
            "max_variants": 16,
            "pipeline": {
                "variant_mode": "sequential",
                "variant_fanout": 2,
                "model_matrix": ["model1", "model2"],
                "hypernetworks": [
                    {"name": "hyper1", "strength": 0.8},
                ],
            },
        }

        panel.load_from_config(config)

        assert panel.randomization_enabled_var.get() is True
        assert panel.max_variants_var.get() == 16
        assert panel.variant_mode_var.get() == "sequential"
        assert panel.fanout_var.get() == "2"

        # Check model matrix was loaded
        assert "model1" in panel._rows[0].value_var.get()
        assert "model2" in panel._rows[0].value_var.get()

        # Check hypernetwork was loaded
        assert "hyper1" in panel._rows[1].value_var.get()
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_add_delete_matrix_rows() -> None:
    """Test adding and deleting matrix rows."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        initial_count = len(panel._rows)

        # Add a row
        panel._add_matrix_row(label="Custom dim", values="val1, val2")
        assert len(panel._rows) == initial_count + 1

        # Delete the last row
        panel._delete_matrix_row(len(panel._rows) - 1)
        assert len(panel._rows) == initial_count
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_clone_matrix_row() -> None:
    """Test cloning a matrix row."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        # Set values on first row
        panel._rows[0].value_var.set("testA, testB")
        initial_count = len(panel._rows)

        # Clone first row
        panel._clone_matrix_row(0)
        assert len(panel._rows) == initial_count + 1

        # Check cloned values
        cloned = panel._rows[-1]
        assert "testA" in cloned.value_var.get()
        assert "testB" in cloned.value_var.get()
    finally:
        root.destroy()


# ============================================================================
# PR-046: Seed Mode & Base Seed Controls Tests
# ============================================================================


@pytest.mark.gui
def test_randomizer_panel_v2_seed_mode_in_config() -> None:
    """Test that seed_mode and base_seed are included in get_randomizer_config."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        # Set seed mode to "fixed" and base_seed to "1234"
        panel.seed_mode_var.set("fixed")
        panel.base_seed_var.set("1234")

        config = panel.get_randomizer_config()

        assert config["seed_mode"] == "fixed"
        assert config["base_seed"] == 1234
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_seed_mode_none_allows_empty_base_seed() -> None:
    """Test that seed_mode 'none' allows empty base_seed (returns None)."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        # Set seed mode to "none" with empty base_seed
        panel.seed_mode_var.set("none")
        panel.base_seed_var.set("")

        config = panel.get_randomizer_config()

        assert config["seed_mode"] == "none"
        assert config["base_seed"] is None
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_seed_normalization_non_numeric() -> None:
    """Test that non-numeric base_seed is normalized to None."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        # Set base_seed to non-numeric value
        panel.seed_mode_var.set("fixed")
        panel.base_seed_var.set("abc")

        config = panel.get_randomizer_config()

        # Non-numeric should become None
        assert config["base_seed"] is None
    finally:
        root.destroy()


@pytest.mark.gui
def test_randomizer_panel_v2_load_seed_settings_from_config() -> None:
    """Test that seed settings are restored via load_from_config."""
    root = tk.Tk()
    root.withdraw()
    try:
        panel = RandomizerPanelV2(root)

        config = {
            "randomization_enabled": True,
            "seed_mode": "per_variant",
            "base_seed": 9999,
        }

        panel.load_from_config(config)

        assert panel.seed_mode_var.get() == "per_variant"
        assert panel.base_seed_var.get() == "9999"
    finally:
        root.destroy()

