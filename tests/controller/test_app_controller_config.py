"""AppController config state tests."""

from __future__ import annotations

import pytest

from src.controller.app_controller import AppController
from tests.helpers.factories import make_run_config
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class NoopPipelineRunner:
    def run(self, config, cancel_token, log_fn=None):
        return


class DummyWidget:
    def configure(self, **_kwargs):
        return


class DummyButton(DummyWidget):
    def __init__(self):
        self.command = None

    def configure(self, **kwargs):
        self.command = kwargs.get("command")


class DummyListbox:
    def __init__(self):
        self.items: list[str] = []

    def bind(self, *_args, **_kwargs):
        return

    def delete(self, *_args):
        self.items = []

    def insert(self, _index, value):
        self.items.append(value)

    def curselection(self):
        return ()

    def get(self, _index):
        return ""


class DummyCombobox(DummyWidget):
    def bind(self, *_args, **_kwargs):
        return

    def get(self):
        return ""


class DummyText:
    def __init__(self):
        self.lines: list[str] = []

    def insert(self, _end, text: str):
        self.lines.append(text)

    def see(self, _end):
        return


class DummyLeftZone:
    def __init__(self):
        self.load_pack_button = DummyButton()
        self.edit_pack_button = DummyButton()
        self.packs_list = DummyListbox()
        self.preset_combo = DummyCombobox()


class DummyHeaderZone:
    def __init__(self):
        self.run_button = DummyButton()
        self.stop_button = DummyButton()
        self.preview_button = DummyButton()
        self.settings_button = DummyButton()
        self.help_button = DummyButton()


class DummyBottomZone:
    def __init__(self):
        self.status_label = DummyWidget()
        self.api_status_label = DummyWidget()
        self.log_text = DummyText()


class DummyWindow:
    def __init__(self):
        self.header_zone = DummyHeaderZone()
        self.left_zone = DummyLeftZone()
        self.bottom_zone = DummyBottomZone()
        self.updated_packs: list[list[str]] = []
        self.connected_controller = None

    def after(self, _delay, callback):
        callback()

    def update_pack_list(self, names: list[str]):
        self.updated_packs.append(names)

    def connect_controller(self, controller):
        self.connected_controller = controller


@pytest.fixture(autouse=True)
def fake_pack_discovery(monkeypatch, tmp_path):
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "demo.txt").write_text("prompt")
    monkeypatch.setattr(
        "src.controller.app_controller.discover_packs",
        lambda *_args, **_kwargs: [],
    )
    return tmp_path


def test_controller_config_defaults(tmp_path):
    window = DummyWindow()
    controller = AppController(
        window,
        threaded=False,
        packs_dir=tmp_path / "packs",
        pipeline_runner=NoopPipelineRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )
    controller.app_state.run_config = make_run_config()

    models = controller.get_available_models()
    samplers = controller.get_available_samplers()
    assert "StableNew-XL" in models
    assert "Euler" in samplers

    cfg = controller.get_current_config()
    assert cfg["width"] == 1024
    assert cfg["steps"] == 30
    assert cfg["cfg_scale"] == 7.5
    assert controller.app_state.run_config["pipeline"]["txt2img_enabled"]


def test_controller_update_config_only_updates_specified_fields(tmp_path):
    window = DummyWindow()
    controller = AppController(
        window,
        threaded=False,
        packs_dir=tmp_path / "packs",
        pipeline_runner=NoopPipelineRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )
    controller.app_state.run_config = make_run_config()

    controller.update_config(model="SDXL-Lightning", width=768, cfg_scale=9.0)
    cfg = controller.get_current_config()
    assert cfg["model"] == "SDXL-Lightning"
    assert cfg["width"] == 768
    assert cfg["cfg_scale"] == 9.0
    assert cfg["height"] == 1024  # unchanged
