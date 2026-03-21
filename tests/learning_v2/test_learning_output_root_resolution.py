from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.gui.views.learning_tab_frame_v2 import LearningTabFrame


def _build_frame(*, config_manager: object | None = None) -> LearningTabFrame:
    frame = LearningTabFrame.__new__(LearningTabFrame)
    frame.pipeline_controller = SimpleNamespace(_config_manager=config_manager)
    frame.app_state = SimpleNamespace(output_dir="wrong/output/animatediff")
    frame.learning_controller = SimpleNamespace(trigger_background_scan=MagicMock())
    frame.discovered_inbox_panel = SimpleNamespace(set_scanning=MagicMock())
    frame._on_discovered_scan_complete = MagicMock()
    return frame


def test_resolve_discovered_output_root_uses_pipeline_config_manager(tmp_path) -> None:
    configured = tmp_path / "output" / "animatediff"
    config_manager = SimpleNamespace(get_setting=lambda key, default=None: str(configured))
    frame = _build_frame(config_manager=config_manager)

    resolved = frame._resolve_discovered_output_root()

    assert Path(resolved) == tmp_path / "output"


def test_resolve_discovered_output_root_falls_back_to_engine_settings(
    monkeypatch, tmp_path
) -> None:
    configured = tmp_path / "output" / "SVD"

    class _FakeConfigManager:
        def get_setting(self, key: str, default: object | None = None) -> str:
            return str(configured)

    monkeypatch.setattr(
        "src.gui.views.learning_tab_frame_v2.ConfigManager",
        _FakeConfigManager,
    )
    frame = _build_frame(config_manager=None)

    resolved = frame._resolve_discovered_output_root()

    assert Path(resolved) == tmp_path / "output"


def test_on_discovered_rescan_uses_resolved_output_root(tmp_path) -> None:
    configured = tmp_path / "output" / "animatediff"
    config_manager = SimpleNamespace(get_setting=lambda key, default=None: str(configured))
    frame = _build_frame(config_manager=config_manager)

    frame._on_discovered_rescan()

    frame.discovered_inbox_panel.set_scanning.assert_called_once_with(True)
    frame.learning_controller.trigger_background_scan.assert_called_once_with(
        output_root=str(tmp_path / "output"),
        on_complete=frame._on_discovered_scan_complete,
    )
