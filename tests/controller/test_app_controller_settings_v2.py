from __future__ import annotations

from pathlib import Path

from src.controller.app_controller import AppController
from src.utils.config import ConfigManager
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class DummyButton:
    def configure(self, **kwargs) -> None:
        pass


class DummyListbox:
    def bind(self, *_args, **_kwargs) -> None:
        pass


class DummyCombo:
    def bind(self, *_args, **_kwargs) -> None:
        pass


class DummyLabel:
    def configure(self, **kwargs) -> None:
        pass


class DummyZone:
    def __init__(self) -> None:
        self.load_pack_button = DummyButton()
        self.edit_pack_button = DummyButton()
        self.packs_list = DummyListbox()
        self.preset_combo = DummyCombo()


class DummyHeader:
    def __init__(self) -> None:
        self.run_button = DummyButton()
        self.stop_button = DummyButton()
        self.preview_button = DummyButton()
        self.settings_button = DummyButton()
        self.help_button = DummyButton()


class DummyBottom:
    def __init__(self) -> None:
        self.api_status_label = DummyLabel()


class DummyMainWindow:
    def __init__(self) -> None:
        self.header_zone = DummyHeader()
        self.left_zone = DummyZone()
        self.bottom_zone = DummyBottom()
        self.after = lambda delay, callback: callback()
        self._pack_names: list[str] = []

    def update_pack_list(self, packs: list[str]) -> None:
        self._pack_names = packs


def test_app_controller_settings_saved(tmp_path: Path) -> None:
    config_manager = ConfigManager(tmp_path / "presets")
    window = DummyMainWindow()
    controller = AppController(
        window,
        threaded=False,
        packs_dir=tmp_path,
        config_manager=config_manager,
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )

    controller.on_settings_saved(
        {"webui_base_url": "http://localhost:1234", "output_dir": "test/output"}
    )

    assert config_manager.get_setting("webui_base_url") == "http://localhost:1234"
    assert config_manager.get_setting("output_dir") == "test/output"
