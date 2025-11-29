# Minimal V2-only shim for GUI entrypoint.
# Legacy StableNewGUI implementation has been archived under archive/gui_v1/.

from src.gui.main_window_v2 import MainWindowV2


# Compatibility aliases for old entrypoint / tests
StableNewGUI = MainWindowV2
ENTRYPOINT_GUI_CLASS = StableNewGUI


def enable_gui_test_mode() -> None:
    """No-op stub retained for legacy tests."""
    return None


def reset_gui_test_mode() -> None:
    """No-op stub retained for legacy tests."""
    return None
