"""GUI module"""

# Import controller-owned runtime modules which don't require tkinter
from src.controller.runtime_state import CancellationError, CancelToken, GUIState, StateManager

# Don't import StableNewGUI here to avoid tkinter dependency in tests
# Users should import it directly: from src.gui.main_window import StableNewGUI

__all__ = [
    "GUIState",
    "StateManager",
    "CancelToken",
    "CancellationError",
]
