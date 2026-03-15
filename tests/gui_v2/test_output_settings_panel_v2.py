from __future__ import annotations

import tkinter as tk

from src.gui.output_settings_panel_v2 import OutputSettingsPanelV2
from src.state.output_routing import OUTPUT_ROUTE_TESTING


def test_output_settings_panel_round_trips_explicit_output_route(tk_root: tk.Tk) -> None:
    panel = OutputSettingsPanelV2(tk_root)
    try:
        panel.apply_from_overrides({"output_route": OUTPUT_ROUTE_TESTING})
        overrides = panel.get_output_overrides()

        assert overrides["output_route"] == OUTPUT_ROUTE_TESTING
    finally:
        panel.destroy()
