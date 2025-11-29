"""Test the improved matrix UI functionality."""

import tkinter as tk

from src.gui.main_window import StableNewGUI


def test_matrix_ui_basic():
    """Test basic matrix UI operations."""

    root = tk.Tk()
    try:
        # Create main window (this will build the UI)
        window = StableNewGUI()

        # Enable randomization and matrix to activate widgets
        window.randomization_vars["enabled"].set(True)
        window.randomization_vars["matrix_enabled"].set(True)
        window._update_randomization_states()

        # Test adding a slot row
        window._add_matrix_slot_row("time", "dawn | noon | dusk")
        assert len(window.randomization_widgets["matrix_slot_rows"]) == 1

        # Test adding another slot
        window._add_matrix_slot_row("location", "forest | beach")
        assert len(window.randomization_widgets["matrix_slot_rows"]) == 2

        # Test collecting config
        config = window._collect_randomization_config()
        matrix_config = config["matrix"]

        assert len(matrix_config["slots"]) == 2
        assert matrix_config["slots"][0]["name"] == "time"
        assert matrix_config["slots"][0]["values"] == ["dawn", "noon", "dusk"]
        assert matrix_config["slots"][1]["name"] == "location"
        assert matrix_config["slots"][1]["values"] == ["forest", "beach"]

        # Test base prompt
        base_prompt_widget = window.randomization_widgets.get("matrix_base_prompt")
        base_prompt_widget.insert(0, "A photo at [[time]] in a [[location]]")
        root.update()  # Process pending events

        config = window._collect_randomization_config()
        assert config["matrix"]["base_prompt"] == "A photo at [[time]] in a [[location]]"

        # Test clearing rows
        window._clear_matrix_slot_rows()
        assert len(window.randomization_widgets["matrix_slot_rows"]) == 0

        print("✅ All matrix UI tests passed!")

    finally:
        root.destroy()


def test_matrix_ui_load_save():
    """Test loading and saving matrix config."""

    root = tk.Tk()
    try:
        window = StableNewGUI()

        # Create test config
        test_config = {
            "randomization": {
                "enabled": True,
                "matrix": {
                    "enabled": True,
                    "mode": "fanout",
                    "limit": 8,
                    "base_prompt": "Portrait of a person at [[time]]",
                    "slots": [
                        {"name": "time", "values": ["dawn", "noon", "dusk"]},
                        {"name": "mood", "values": ["happy", "sad"]},
                    ],
                },
            },
        }

        # Load config
        window._load_randomization_config(test_config)

        # Verify UI was populated
        base_prompt_widget = window.randomization_widgets.get("matrix_base_prompt")
        assert base_prompt_widget.get() == "Portrait of a person at [[time]]"

        assert len(window.randomization_widgets["matrix_slot_rows"]) == 2

        row1 = window.randomization_widgets["matrix_slot_rows"][0]
        assert row1["name_entry"].get() == "time"
        assert row1["values_entry"].get() == "dawn | noon | dusk"

        row2 = window.randomization_widgets["matrix_slot_rows"][1]
        assert row2["name_entry"].get() == "mood"
        assert row2["values_entry"].get() == "happy | sad"

        # Collect config and verify round-trip
        saved_config = window._collect_randomization_config()
        assert saved_config["matrix"]["base_prompt"] == "Portrait of a person at [[time]]"
        assert len(saved_config["matrix"]["slots"]) == 2

        print("✅ Matrix UI load/save tests passed!")

    finally:
        root.destroy()


if __name__ == "__main__":
    test_matrix_ui_basic()
    test_matrix_ui_load_save()
    print("\n🎉 All matrix UI tests passed!")
