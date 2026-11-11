from __future__ import annotations

from unittest.mock import Mock

import pytest

from src import main


@pytest.mark.parametrize("owns_process", [False, True])
def test_emergency_cleanup_resolves_the_current_owner(monkeypatch, owns_process) -> None:
    manager = Mock(owns_process=owns_process)
    monkeypatch.setattr(main, "get_global_comfy_process_manager", lambda: manager)

    main._emergency_comfy_cleanup()

    if owns_process:
        manager.stop.assert_called_once_with(grace_seconds=1.0)
    else:
        manager.stop.assert_not_called()
