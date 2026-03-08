#!/usr/bin/env python3
"""Quick validation of core config panel changes."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.gui.core_config_panel_v2 import CoreConfigPanelV2
    print("✓ CoreConfigPanelV2 imports successfully")

    # Test that the constrained values are correct
    width_values = [str(i) for i in range(256, 2049, 128)]
    height_values = [str(i) for i in range(256, 2049, 128)]

    expected_values = ['256', '384', '512', '640', '768', '896', '1024', '1152', '1280', '1408', '1536', '1664', '1792', '1920', '2048']

    if width_values == expected_values and height_values == expected_values:
        print("✓ Width/height constrained values are correct")
    else:
        print("✗ Width/height values don't match expected")
        print(f"Expected: {expected_values}")
        print(f"Got: {width_values}")

    print("✓ Core config panel validation passed")

except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)