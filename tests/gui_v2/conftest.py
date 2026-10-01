"""Shared fixtures for GUI v2 tests."""

from __future__ import annotations

import threading
import tkinter as tk
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.services.config_service import ConfigService
from src.utils.config import ConfigManager
from src.utils.preferences import PreferencesManager

DEFAULT_TXT2IMG_CFG = {
    "model": "sd_xl_base_1.0",
    "vae": "sdxl_vae.safetensors",
    "sampler_name": "Euler",
    "scheduler": "Normal",
    "steps": 20,
    "cfg_scale": 7.5,
    "width": 832,
    "height": 1216,
}

DEFAULT_IMG2IMG_CFG = {
    "model": "sd_xl_base_1.0",
    "vae": "sdxl_vae.safetensors",
    "sampler_name": "Euler",
    "denoising_strength": 0.35,
    "cfg_scale": 7.0,
    "steps": 20,
}

DEFAULT_UPSCALE_CFG = {
    "upscaler": "R-ESRGAN 4x+",
    "upscale_mode": "single",
    "steps": 20,
    "denoising_strength": 0.35,
}


@pytest.fixture(autouse=True)
def _isolate_prompt_pack_dir(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:
    """Keep GUI tests off the owner's per-user PromptPack directory.

    ``resolve_prompt_pack_dir`` falls back to ``%LOCALAPPDATA%/StableNew/PromptPacks``
    when no explicit directory is injected, which leaks the host's real packs into
    (and lets tests write into) the owner's storage. Tests that inject an explicit
    ``packs_dir`` are unaffected because explicit injection wins.
    """

    monkeypatch.setenv(
        "STABLENEW_PROMPTPACK_DIR", str(tmp_path_factory.mktemp("isolated_promptpacks"))
    )


@pytest.fixture(autouse=True)
def _isolate_gui_workspace_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Redirect process-wide mutable GUI state away from the repository workspace.

    Production defaults resolve UI/sidebar/preview state under ``<repo>/state``.
    Without this, tests read state persisted by earlier tests (for example the
    content-visibility mode or auto-run flag) and write into the operator's real
    workspace when run from the owner's checkout, making results order- and
    host-dependent. ``workspace_paths`` itself is deliberately left alone: moving
    its root also moves the Asset Registry cache and forces a cold model scan in
    every test.
    """

    import src.gui.preview_panel_v2 as preview_panel_v2
    import src.gui.sidebar_panel_v2 as sidebar_panel_v2
    import src.photo_optimize.store as photo_store
    import src.services.ui_state_store as ui_state_store

    root = tmp_path_factory.mktemp("gui_workspace")
    monkeypatch.setattr(ui_state_store, "UI_STATE_PATH", root / "state" / "ui_state.json")
    monkeypatch.setattr(ui_state_store, "_global_store", None)
    monkeypatch.setattr(photo_store, "_global_store", None)
    monkeypatch.setattr(
        sidebar_panel_v2, "SIDEBAR_STATE_PATH", root / "state" / "sidebar_state.json"
    )
    monkeypatch.setattr(
        preview_panel_v2, "PREVIEW_STATE_PATH", root / "state" / "preview_panel_state.json"
    )


simpledialog_stub = SimpleNamespace(
    askstring=lambda *args, **kwargs: None,
)


class DummyConfigManager:
    def __init__(self):
        self._default_config = {
            "txt2img": deepcopy(DEFAULT_TXT2IMG_CFG),
            "img2img": deepcopy(DEFAULT_IMG2IMG_CFG),
            "upscale": deepcopy(DEFAULT_UPSCALE_CFG),
        }
        self._presets = {"default": deepcopy(self._default_config)}
        self._pack_configs: dict[str, dict] = {}
        self._default_preset = "default"

    def get_default_config(self):
        return deepcopy(self._default_config)

    def list_presets(self):
        return sorted(self._presets.keys())

    def save_preset(self, name, config):
        self._presets[name] = deepcopy(config)
        return True

    def get_default_preset(self):
        return self._default_preset

    def set_default_preset(self, name):
        if name in self._presets:
            self._default_preset = name
        return True

    def load_preset(self, name):
        return deepcopy(self._presets.get(name) or self._default_config)

    def ensure_pack_config(self, _pack_name, preset_name):
        preset = preset_name or self._default_preset
        return deepcopy(self._pack_configs.get(_pack_name) or self.load_preset(preset))

    def load_pack_config(self, pack_name):
        return deepcopy(self._pack_configs.get(pack_name) or self._default_config)

    def save_pack_config(self, pack_name, config):
        self._pack_configs[pack_name] = deepcopy(config)
        return True

    def delete_preset(self, name):
        self._presets.pop(name, None)
        if self._default_preset == name:
            self._default_preset = "default"
        return True


class DummyCancelToken:
    def is_cancelled(self):
        return False


class DummyController:
    def __init__(self):
        self.start_calls = 0
        self.lifecycle_event = threading.Event()
        self.cancel_token = DummyCancelToken()
        self._log_messages: list[str] = []
        self.pipeline = None
        self.last_run_config = None
        self.is_terminal = False
        self.structured_logger = None
        self.progress_callbacks: dict[str, callable] = {}
        self.learning_enabled = False

    def start_pipeline(self, *_args, **_kwargs):
        self.start_calls += 1
        self.lifecycle_event.set()
        return True

    def stop_pipeline(self):
        return True

    def get_log_messages(self):
        return list(self._log_messages)

    def set_pipeline(self, pipeline):
        self.pipeline = pipeline

    def report_progress(self, *_args, **_kwargs):
        return None

    def configure_progress_callbacks(self, **callbacks):
        self.progress_callbacks.update(callbacks)

    register_progress_callbacks = configure_progress_callbacks
    set_progress_callbacks = configure_progress_callbacks

    def record_run_config(self, config: dict):
        self.last_run_config = config

    def set_learning_enabled(self, enabled: bool):
        self.learning_enabled = bool(enabled)


def _create_messagebox_stub():
    class _MessageboxStub:
        @staticmethod
        def showerror(*_args, **_kwargs):
            return None

        @staticmethod
        def showwarning(*_args, **_kwargs):
            return None

        @staticmethod
        def showinfo(*_args, **_kwargs):
            return None

        @staticmethod
        def askyesno(*_args, **_kwargs):
            return True

    return _MessageboxStub()


@pytest.fixture
def tk_root():
    """Provide a Tk root window or skip if Tk/Tcl is unavailable."""

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")
    root.withdraw()
    # Masterless ``tk.BooleanVar()``/``tk.StringVar()`` bind to tkinter's default
    # root. Other GUI tests keep a process-wide shared root alive, which then stays
    # the default root, so such variables would live in a different Tcl interpreter
    # than this test's widgets (checkbuttons then report the "alternate" state and
    # ignore toggles). Make this test's root the default for the test's duration.
    previous_default_root = getattr(tk, "_default_root", None)
    tk._default_root = root  # noqa: SLF001
    yield root
    try:
        root.destroy()
    except Exception:
        pass
    try:
        if previous_default_root is not None and previous_default_root.winfo_exists():
            tk._default_root = previous_default_root  # noqa: SLF001
    except Exception:
        pass


@pytest.fixture
def dummy_config_manager():
    return DummyConfigManager()


@pytest.fixture
def dummy_controller():
    return DummyController()


@pytest.fixture
def gui_app_factory(monkeypatch: pytest.MonkeyPatch, tk_root: tk.Tk, tmp_path):
    """Factory that builds a StableNewGUI instance with heavy hooks disabled."""

    from src.gui.main_window import (
        StableNewGUI,
        enable_gui_test_mode,
        reset_gui_test_mode,
    )

    packs_dir = tmp_path / "packs"
    presets_dir = tmp_path / "presets"
    lists_dir = tmp_path / "lists"
    output_dir = tmp_path / "output"
    monkeypatch.setattr("src.gui.main_window.tk.simpledialog", simpledialog_stub, raising=False)

    def _build(**kwargs):
        controller_override = kwargs.pop("controller", None)
        config_manager_override = kwargs.pop("config_manager", None)

        enable_gui_test_mode()
        monkeypatch.setenv("STABLENEW_GUI_TEST_MODE", "1")
        monkeypatch.setattr(
            "src.gui.main_window.StableNewGUI._launch_webui",
            lambda self: None,
        )
        monkeypatch.setattr(
            "src.gui.main_window.StableNewGUI._check_api_connection",
            lambda self: None,
        )
        monkeypatch.setattr(
            "src.gui.main_window.StableNewGUI._maybe_show_new_features_dialog",
            lambda self: None,
        )

        config_manager = config_manager_override or ConfigManager(str(presets_dir))
        preferences = PreferencesManager(str(tmp_path / "prefs.json"))

        app = StableNewGUI(
            root=tk_root,
            config_manager=config_manager,
            preferences=preferences,
            controller=controller_override,
            title="StableNew Test",
            geometry="1024x720",
            **kwargs,
        )
        app.config_service = ConfigService(packs_dir, presets_dir, lists_dir)
        app.structured_logger.output_dir = output_dir
        app.structured_logger.output_dir.mkdir(exist_ok=True)
        app.api_connected = True
        app._confirm_run_with_dirty = lambda: True
        return app

    yield _build

    reset_gui_test_mode()


@pytest.fixture
def gui_app_with_dummies(gui_app_factory, dummy_controller, dummy_config_manager):
    app = gui_app_factory(controller=dummy_controller, config_manager=dummy_config_manager)
    return app, dummy_controller, dummy_config_manager
