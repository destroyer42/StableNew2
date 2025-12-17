import ast
import pathlib

import pytest

UTILS_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "utils"


GUI_IMPORT_BLOCKLIST = {
    "tkinter",
    "ttk",
    "src.gui",
    "src.gui.theme",
}


def iter_utils_python_files():
    if not UTILS_ROOT.is_dir():
        pytest.skip(f"Utils root not found at {UTILS_ROOT}")
    yield from UTILS_ROOT.rglob("*.py")


def extract_import_targets(module_path: pathlib.Path):
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imports.append(node.module)
    return imports


def is_blocked_import(name: str) -> bool:
    if name in GUI_IMPORT_BLOCKLIST:
        return True
    # Handle prefixes like "src.gui.something"
    if name.startswith("src.gui."):
        return True
    return False


def test_no_gui_imports_in_utils():
    violations = []

    for py_file in iter_utils_python_files():
        imports = extract_import_targets(py_file)
        bad = [name for name in imports if is_blocked_import(name)]
        if bad:
            violations.append((py_file, bad))

    if violations:
        lines = ["The following utils modules import GUI/theme/Tkinter code:"]
        for path, bad_imports in violations:
            rel = path.relative_to(UTILS_ROOT.parents[1])
            lines.append(f" - {rel}: {', '.join(sorted(set(bad_imports)))}")
        pytest.fail("\n".join(lines))
