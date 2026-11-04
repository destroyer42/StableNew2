from __future__ import annotations

import pytest

from src.gui.widgets.lora_picker_panel import LoRAPickerPanel


@pytest.mark.gui
def test_lora_picker_long_name_preserves_controls(tk_root) -> None:
    panel = LoRAPickerPanel(tk_root)
    try:
        long_name = "LoRA-" + ("VeryLongName-" * 8)
        panel.set_loras([(long_name, 0.8)])
        widgets = panel._entry_widgets[long_name]

        assert widgets["name_label"].winfo_exists()
        assert widgets["remove_button"].winfo_exists()
        assert widgets["keywords_button"].winfo_exists()
        assert widgets["strength_slider"].winfo_exists()
        assert widgets["name_row"] is not widgets["controls_row"]
        assert widgets["controls_row"].columnconfigure(0)["minsize"] == panel.CONTROL_ROW_MIN_WIDTH
        assert widgets["remove_button"].winfo_manager() == "grid"
    finally:
        panel.destroy()


@pytest.mark.gui
def test_lora_picker_exact_entry_updates_weight(tk_root) -> None:
    panel = LoRAPickerPanel(tk_root)
    try:
        panel.set_loras([("LoRA-Alpha", 0.8)])
        slider = panel._entry_widgets["LoRA-Alpha"]["strength_slider"]
        slider.value_entry.delete(0, "end")
        slider.value_entry.insert(0, "1.23")
        slider._on_entry_commit()

        assert panel.get_loras() == [("LoRA-Alpha", pytest.approx(1.23, rel=1e-3))]
    finally:
        panel.destroy()


@pytest.mark.gui
def test_application_shutdown_cancels_an_in_flight_discovery_scan(tk_root) -> None:
    """Shutdown joins the scan before any widget is destroyed, so the scan must hear the exit request itself."""

    import threading
    import time

    from src.utils.thread_registry import get_thread_registry

    started = threading.Event()

    class SlowScanner:
        registry = None

        def scan_loras(self, read_only=True, cancelled=None):
            started.set()
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                if cancelled is not None and cancelled():
                    raise InterruptedError("cancelled")
                time.sleep(0.01)
            return {}

    panel = LoRAPickerPanel(tk_root)
    try:
        panel.scanner = SlowScanner()
        panel.refresh_loras()
        assert started.wait(5.0)
        began = time.monotonic()

        stats = get_thread_registry().shutdown_all(timeout=10.0)

        assert stats["timeout"] == 0
        assert time.monotonic() - began < 3.0
    finally:
        panel.destroy()
