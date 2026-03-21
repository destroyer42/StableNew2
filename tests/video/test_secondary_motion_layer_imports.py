from __future__ import annotations

import ast
import pathlib

import pytest


MOTION_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "video" / "motion"

IMPORT_BLOCKLIST = {
    "tkinter",
    "ttk",
    "src.gui",
    "src.gui_v2",
    "src.controller",
    "src.pipeline.executor",
    "src.video.animatediff_backend",
    "src.video.svd_native_backend",
    "src.video.comfy_workflow_backend",
}


def _iter_motion_python_files():
    if not MOTION_ROOT.is_dir():
        pytest.skip(f"Motion root not found at {MOTION_ROOT}")
    yield from MOTION_ROOT.rglob("*.py")


def _extract_import_targets(module_path: pathlib.Path) -> list[str]:
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


def _is_blocked_import(name: str) -> bool:
    if name in IMPORT_BLOCKLIST:
        return True
    return (
        name.startswith("src.gui.")
        or name.startswith("src.gui_v2.")
        or name.startswith("src.controller.")
        or name.startswith("src.pipeline.executor.")
        or name.startswith("src.video.animatediff_backend.")
        or name.startswith("src.video.svd_native_backend.")
        or name.startswith("src.video.comfy_workflow_backend.")
    )


def test_secondary_motion_layer_has_no_gui_controller_or_backend_imports() -> None:
    violations: list[tuple[pathlib.Path, list[str]]] = []
    for py_file in _iter_motion_python_files():
        imports = _extract_import_targets(py_file)
        bad = [name for name in imports if _is_blocked_import(name)]
        if bad:
            violations.append((py_file, bad))

    if violations:
        lines = ["The following secondary-motion modules import forbidden code:"]
        for path, bad_imports in violations:
            rel = path.relative_to(MOTION_ROOT.parents[2])
            lines.append(f" - {rel}: {', '.join(sorted(set(bad_imports)))}")
        pytest.fail("\n".join(lines))
