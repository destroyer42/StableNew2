#!/usr/bin/env python3
"""Test script to verify CoreConfigPanelV2 uses controller methods for data sources."""

import tkinter as tk
from unittest.mock import Mock

from src.gui.core_config_panel_v2 import CoreConfigPanelV2


class DummyAdapter:
    def get_model_names(self):
        return ["adapter_model1", "adapter_model2"]

    def get_vae_names(self):
        return ["adapter_vae1"]

    def get_sampler_names(self):
        return ["adapter_sampler1"]


def test_controller_priority():
    """Test that controller methods are used when available."""
    root = tk.Tk()
    root.withdraw()

    # Create mock controller with methods
    controller = Mock()
    controller.list_models.return_value = [
        Mock(display_name="controller_model1"),
        Mock(display_name="controller_model2")
    ]
    controller.list_vaes.return_value = [
        Mock(display_name="controller_vae1")
    ]
    controller.get_available_samplers.return_value = [
        Mock(display_name="controller_sampler1")
    ]

    # Create adapters with different data
    adapter = DummyAdapter()

    # Create panel with both controller and adapters
    panel = CoreConfigPanelV2(
        root,
        controller=controller,
        include_vae=True,
        include_refresh=True,
        model_adapter=adapter,
        vae_adapter=adapter,
        sampler_adapter=adapter,
    )

    # Test that controller methods are called with correct mapping
    models = panel._names_from_adapter(adapter, "get_model_names", "list_models")
    vaes = panel._names_from_adapter(adapter, "get_vae_names", "list_vaes")
    samplers = panel._names_from_adapter(adapter, "get_sampler_names", "get_available_samplers")

    print("Models from controller:", models)
    print("VAEs from controller:", vaes)
    print("Samplers from controller:", samplers)

    # Verify controller data is used
    assert models == ["controller_model1", "controller_model2"]
    assert vaes == ["controller_vae1"]
    assert samplers == ["controller_sampler1"]

    print("✓ Controller methods are prioritized over adapters")

    # Test fallback to adapter when controller method doesn't exist
    models_fallback = panel._names_from_adapter(adapter, "get_model_names", None)
    print("Models fallback to adapter:", models_fallback)
    assert models_fallback == ["adapter_model1", "adapter_model2"]

    print("✓ Adapter fallback works when controller method unavailable")

    # Test refresh_from_adapters uses controller methods
    panel.refresh_from_adapters()
    print("✓ refresh_from_adapters completed without error")

    root.destroy()
    print("✓ All tests passed!")


if __name__ == "__main__":
    test_controller_priority()