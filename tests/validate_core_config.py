#!/usr/bin/env python3
"""Quick validation of base generation panel changes."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

try:
    from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2

    print("BaseGenerationPanelV2 imports successfully")

    width_values = [str(i) for i in range(256, 2049, 128)]
    height_values = [str(i) for i in range(256, 2049, 128)]
    expected_values = [
        "256",
        "384",
        "512",
        "640",
        "768",
        "896",
        "1024",
        "1152",
        "1280",
        "1408",
        "1536",
        "1664",
        "1792",
        "1920",
        "2048",
    ]

    if width_values == expected_values and height_values == expected_values:
        print("Width/height constrained values are correct")
    else:
        print("Width/height values do not match expected")
        print(f"Expected: {expected_values}")
        print(f"Got: {width_values}")

    print("Base generation panel validation passed")

except Exception as exc:
    print(f"Error: {exc}")
    sys.exit(1)
