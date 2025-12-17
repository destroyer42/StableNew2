import importlib
import pathlib
import sys
import types

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"


GUI_MODULE_PREFIXES = (
    "src.gui",
    "tkinter",
    "ttk",
)


@pytest.mark.parametrize("module_name", ["src.utils.randomizer"])
def test_randomizer_import_does_not_pull_gui_modules(module_name):
    if not (SRC_ROOT / "utils" / "randomizer.py").exists():
        pytest.skip(f"randomizer module not found at {SRC_ROOT / 'utils' / 'randomizer.py'}")

    # Clean import environment as much as possible for this test
    to_delete = [name for name in sys.modules if name.startswith("src.utils.randomizer")]
    for name in to_delete:
        sys.modules.pop(name, None)

    # Temporarily remove any pre-loaded GUI/Tk modules so we can detect new ones
    removed_gui: dict[str, types.ModuleType] = {}
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in GUI_MODULE_PREFIXES):
            removed_gui[name] = sys.modules.pop(name)

    try:
        mod = importlib.import_module(module_name)
        assert isinstance(mod, types.ModuleType)

        gui_loaded = [
            name
            for name in sys.modules
            if any(
                name == prefix or name.startswith(prefix + ".") for prefix in GUI_MODULE_PREFIXES
            )
        ]

        if gui_loaded:
            details = "\n".join(f" - {name}" for name in sorted(gui_loaded))
            pytest.fail(
                "Importing src.utils.randomizer should not load GUI/Tkinter modules, "
                f"but found these in sys.modules:\n{details}"
            )
    finally:
        sys.modules.update(removed_gui)
