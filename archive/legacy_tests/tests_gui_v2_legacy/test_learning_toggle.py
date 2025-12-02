from __future__ import annotations

import pytest

from src.gui.main_window import StableNewGUI
from src.gui.main_window import enable_gui_test_mode


class StubLearningController:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.calls = []

    def set_learning_enabled(self, value: bool):
        self.enabled = bool(value)
        self.calls.append(value)

    def get_learning_enabled(self):
        return self.enabled

    def list_recent_records(self, limit=10):
        return []

    def save_feedback(self, record, rating, tags=None):
        return None


@pytest.fixture
def stub_learning_controller():
    return StubLearningController(enabled=False)


def test_learning_toggle_reflects_controller_state(gui_app_factory, stub_learning_controller):
    enable_gui_test_mode()
    app = gui_app_factory(controller=None)
    app.controller = stub_learning_controller
    app.learning_execution_controller = stub_learning_controller
    app.learning_enabled_var.set(stub_learning_controller.get_learning_enabled())
    app._on_learning_toggle(True)
    assert stub_learning_controller.enabled is True
    app._on_learning_toggle(False)
    assert stub_learning_controller.enabled is False
