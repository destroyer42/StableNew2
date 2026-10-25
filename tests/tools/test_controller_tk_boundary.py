from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    path = ROOT / "tools" / "ci" / "check_controller_tk_boundary.py"
    spec = importlib.util.spec_from_file_location("controller_tk_boundary_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skeleton(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    for package in ("", "controller", "gui"):
        _write(src / package / "__init__.py", "")
    return src


def test_direct_controller_tk_import_is_rejected(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(src / "controller" / "bad.py", "import tkinter\n")

    paths = _load_checker().controller_tk_paths(src)

    assert paths == [["src.controller.bad", "tkinter"]]


def test_transitive_controller_tk_import_is_rejected(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(src / "controller" / "bad.py", "from src.gui.adapter import Adapter\n")
    _write(src / "gui" / "adapter.py", "import tkinter as tk\n")

    paths = _load_checker().controller_tk_paths(src)

    assert paths == [["src.controller.bad", "src.gui.adapter", "tkinter"]]


def test_from_package_import_module_is_followed(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(src / "controller" / "bad.py", "from src.gui import adapter\n")
    _write(src / "gui" / "adapter.py", "from tkinter import ttk\n")

    assert _load_checker().controller_tk_paths(src)


def test_relative_import_is_followed(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(src / "controller" / "bad.py", "from . import helper\n")
    _write(src / "controller" / "helper.py", "import tkinter\n")

    paths = _load_checker().controller_tk_paths(src)

    assert ["src.controller.bad", "src.controller.helper", "tkinter"] in paths


def test_package_init_import_is_part_of_the_closure(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(src / "gui" / "__init__.py", "import tkinter\n")
    _write(src / "gui" / "neutral.py", "VALUE = 1\n")
    _write(src / "controller" / "bad.py", "from src.gui.neutral import VALUE\n")

    assert _load_checker().controller_tk_paths(src)


def test_type_checking_import_does_not_create_runtime_edge(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(
        src / "controller" / "good.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from src.gui.tk_view import TkView\n",
    )
    _write(src / "gui" / "tk_view.py", "import tkinter\n")

    assert _load_checker().controller_tk_paths(src) == []


def test_function_local_gui_import_is_not_module_import_closure(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(
        src / "controller" / "legacy_action.py",
        "def open_dialog():\n    from src.gui.tk_dialog import TkDialog\n    return TkDialog\n",
    )
    _write(src / "gui" / "tk_dialog.py", "import tkinter\n")

    assert _load_checker().controller_tk_paths(src) == []


def test_try_block_import_is_conservatively_followed(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(
        src / "controller" / "bad.py",
        "try:\n    import tkinter\nexcept ImportError:\n    tkinter = None\n",
    )

    assert _load_checker().controller_tk_paths(src)


def test_inventory_reports_direct_tk_sources(tmp_path: Path) -> None:
    src = _skeleton(tmp_path)
    _write(src / "gui" / "view.py", "from tkinter import ttk\n")
    _write(src / "gui" / "neutral.py", "VALUE = 1\n")

    assert _load_checker().direct_tk_inventory(src) == ["src/gui/view.py"]


def test_boundary_check_is_wired_into_gate_and_hosted_required() -> None:
    gate = (ROOT / "tools" / "ci" / "run_pr_gate.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "check_controller_tk_boundary.py" in gate
    assert "python tools/ci/check_controller_tk_boundary.py" in workflow


def test_repository_controller_closure_is_tk_free() -> None:
    assert _load_checker().controller_tk_paths() == []
