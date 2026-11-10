"""Repository guard for the Qt Widgets design workspace (``design/qt_widgets``, QT-DS-01).

The workspace is a design aid, not product code. The default pytest run only needs to prove that:

* its Qt-free tests (theme contract, theme store, static consistency, mock workflow, production
  independence) still pass, so the workspace cannot silently rot;
* nothing in the application imports it and it imports nothing from the application;
* it carries no second production theme or settings authority.

The Qt display tests need PySide6, which the production environment must not install; they stay
opt-in (``STABLENEW_QT_PROTOTYPE_TEST=1`` in a separate environment, see the workspace README).
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "design" / "qt_widgets"
PACKAGE = WORKSPACE / "stablenew_qt_proto"


def test_workspace_pure_suite_passes_without_qt() -> None:
    env = {k: v for k, v in os.environ.items() if k != "STABLENEW_QT_PROTOTYPE_TEST"}
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("STABLENEW_QT_PROTO_THEME_DIR", None)  # the suite uses its own temporary directories
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=WORKSPACE,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]
    ran = re.search(r"Ran (\d+) tests", output)
    assert ran and int(ran.group(1)) >= 150, output[-1000:]  # guards against silent non-discovery


def test_application_never_imports_the_design_workspace() -> None:
    needles = ("stablenew_qt_proto", "design.qt_widgets", "design/qt_widgets")
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in needles:
            assert needle not in text, f"{path.relative_to(ROOT)} references the design workspace"


def test_design_workspace_never_imports_the_application() -> None:
    pattern = re.compile(r"^\s*(?:from|import)\s+(src|tkinter)\b", re.MULTILINE)
    for path in PACKAGE.rglob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def _string_literals(source: str) -> list[str]:
    """String constants that are real values (docstrings, which may name what is excluded, are skipped)."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]


def test_design_workspace_declares_no_production_settings_authority() -> None:
    forbidden = ("presets/settings.json", "ui_tokens", "design_values", "config/ui")
    for path in PACKAGE.rglob("*.py"):
        if path.name == "theme_store.py":
            continue  # its own static test asserts the same on its stricter list
        for value in _string_literals(path.read_text(encoding="utf-8")):
            for needle in forbidden:
                assert needle not in value, f"{path.name} uses {needle}"
    themes = sorted(p.name for p in (PACKAGE / "themes").glob("*.json"))
    assert themes == ["blue-modern.theme.json", "concept-a.theme.json"]
