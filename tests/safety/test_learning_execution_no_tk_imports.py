from __future__ import annotations

import sys


def test_learning_execution_modules_do_not_import_tk():
    for module in (
        "src.learning.learning_execution",
        "src.controller.learning_execution_controller",
    ):
        sys.modules.pop(module, None)
        before = set(sys.modules)
        __import__(module)
        loaded = set(sys.modules) - before
        assert "tkinter" not in loaded
        assert "src.gui" not in loaded
