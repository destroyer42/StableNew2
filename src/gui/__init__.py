"""GUI module"""

# Import controller-owned runtime/controller modules which don't require tkinter
from src.controller.runtime_state import CancellationError, CancelToken, GUIState, StateManager
from .controller import LogMessage, PipelineController

# Don't import StableNewGUI here to avoid tkinter dependency in tests
# Users should import it directly: from src.gui.main_window import StableNewGUI

__all__ = [
    "GUIState",
    "StateManager",
    "CancelToken",
    "CancellationError",
    "PipelineController",
    "LogMessage",
]
