from __future__ import annotations

import ast
import pathlib

import pytest


REFINEMENT_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "refinement"

IMPORT_BLOCKLIST = {
    "tkinter",
    "ttk",
    "src.gui",
    "src.gui_v2",
    "src.video",
}


def iter_refinement_python_files():
    if not REFINEMENT_ROOT.is_dir():
        pytest.skip(f"Refinement root not found at {REFINEMENT_ROOT}")
    yield from REFINEMENT_ROOT.rglob("*.py")


def extract_import_targets(module_path: pathlib.Path) -> list[str]:
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)
    return imports


def is_blocked_import(name: str) -> bool:
    if name in IMPORT_BLOCKLIST:
        return True
    return (
        name.startswith("src.gui.")
        or name.startswith("src.gui_v2.")
        or name.startswith("src.video.")
    )


def test_refinement_layer_has_no_gui_or_video_imports() -> None:
    violations: list[tuple[pathlib.Path, list[str]]] = []
    for py_file in iter_refinement_python_files():
        imports = extract_import_targets(py_file)
        bad = [name for name in imports if is_blocked_import(name)]
        if bad:
            violations.append((py_file, bad))

    if violations:
        lines = ["The following refinement modules import GUI/video code:"]
        for path, bad_imports in violations:
            rel = path.relative_to(REFINEMENT_ROOT.parents[1])
            lines.append(f" - {rel}: {', '.join(sorted(set(bad_imports)))}")
        pytest.fail("\n".join(lines))
