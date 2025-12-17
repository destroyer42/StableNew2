"""Ensure src.utils does not import GUI modules at import time."""

import importlib
import sys
from types import ModuleType

import pytest

FORBIDDEN_SUBSTRINGS = (
    "src.gui",
    "tkinter",
    "PIL.ImageTk",
)


def _import_utils_module(module_name: str) -> ModuleType:
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)


@pytest.mark.parametrize(
    "module_path",
    [
        "src.utils.randomizer",
        "src.utils.config",
        "src.utils.file_io",
    ],
)
def test_utils_modules_do_not_import_gui(module_path):
    module = _import_utils_module(module_path)
    for attr_name, value in sys.modules.items():
        if value is None:
            continue
        if not attr_name.startswith("src.utils"):
            continue
        for forbidden in FORBIDDEN_SUBSTRINGS:
            assert forbidden not in attr_name, (
                f"{module_path} imported forbidden dependency {attr_name}"
            )
    assert module is not None
