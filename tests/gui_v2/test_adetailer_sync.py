#!/usr/bin/env python3
"""
Test script to verify Adetailer visibility synchronization between sidebar and pipeline config panel.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
import tkinter as tk

def test_stage_synchronization():
    """Test that pipeline config panel updates sidebar stage states."""
    root = tk.Tk()
    root.title("Stage Synchronization Test")
    root.geometry("400x300")

    # Create mock controller with sidebar
    class MockController:
        def __init__(self):
            self.sidebar = None

    controller = MockController()

    # Create sidebar first
    sidebar = SidebarPanelV2(root, controller=controller)
    controller.sidebar = sidebar

    # Create pipeline config panel
    config_panel = PipelineConfigPanel(root, controller=controller)

    # Test initial state - sidebar should have adetailer enabled by default
    print("Initial sidebar stage states:")
    enabled_stages = sidebar.get_enabled_stages()
    print(f"Enabled stages: {enabled_stages}")
    print(f"Adetailer enabled: {'adetailer' in enabled_stages}")

    # Test pipeline config panel synchronization
    print("\nTesting pipeline config panel synchronization...")

    # Initially, pipeline config should reflect sidebar state
    # But let's manually set the combined img2img/adetailer checkbox to False
    config_panel.img2img_var.set(False)
    config_panel._on_stage_change()

    enabled_stages_after = sidebar.get_enabled_stages()
    print(f"After setting img2img/adetailer to False: {enabled_stages_after}")
    print(f"Adetailer enabled: {'adetailer' in enabled_stages_after}")

    # Now set it back to True
    config_panel.img2img_var.set(True)
    config_panel._on_stage_change()

    enabled_stages_final = sidebar.get_enabled_stages()
    print(f"After setting img2img/adetailer to True: {enabled_stages_final}")
    print(f"Adetailer enabled: {'adetailer' in enabled_stages_final}")

    # Check if synchronization worked
    if 'adetailer' in enabled_stages_final:
        print("\n✅ SUCCESS: Adetailer is properly synchronized and visible!")
        return True
    else:
        print("\n❌ FAILURE: Adetailer synchronization failed!")
        return False

if __name__ == "__main__":
    success = test_stage_synchronization()
    sys.exit(0 if success else 1)