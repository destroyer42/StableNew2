"""Randomizer-specific import isolation tests."""

import importlib
import sys

import pytest


@pytest.mark.parametrize("module_name", ["src.utils.randomizer"])
def test_randomizer_module_does_not_import_gui(module_name):
    if module_name in sys.modules:
        del sys.modules[module_name]
    module = importlib.import_module(module_name)
    assert module is not None
    for attr_name in tuple(sys.modules):
        if not attr_name.startswith("src.utils"):
            continue
        if attr_name.startswith("src.gui"):
            raise AssertionError(f"{module_name} imported GUI module {attr_name}")
