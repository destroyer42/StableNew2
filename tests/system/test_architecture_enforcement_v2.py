from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"

ALLOWED_ARCHIVE_IMPORT_PATHS: set[Path] = set()
ALLOWED_CONTROLLER_BACKEND_IMPORT_PATHS: set[Path] = {
    ROOT / "src" / "controller" / "ports" / "default_runtime_ports.py",
}

ARCHIVE_IMPORT_PATTERNS = (
    re.compile(r"\bfrom\s+src\.controller\.archive\.pipeline_config_types\s+import\b"),
    re.compile(r"\bfrom\s+src\.controller\.archive\.pipeline_config_assembler\s+import\b"),
    re.compile(r"\bimport\s+src\.controller\.archive\.pipeline_config_types\b"),
    re.compile(r"\bimport\s+src\.controller\.archive\.pipeline_config_assembler\b"),
    re.compile(
        r"\bfrom\s+tools\.archive_reference(?:\.[A-Za-z_][A-Za-z0-9_]*)+\s+import\b"
    ),
    re.compile(
        r"\bimport\s+tools\.archive_reference(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b"
    ),
)

GUI_PIPELINE_IMPORT_PATTERNS = (
    re.compile(r"\bfrom\s+src\.pipeline\.(pipeline_runner|executor)\s+import\b"),
    re.compile(r"\bimport\s+src\.pipeline\.(pipeline_runner|executor)\b"),
)

GUI_DIRECT_RUN_PATTERNS = (
    re.compile(r"\bpipeline_runner\.run\s*\("),
    re.compile(r"\brun_njr_v2\s*\("),
)

CONTROLLER_TK_IMPORT_PATTERNS = (
    re.compile(r"\bimport\s+tkinter\b"),
    re.compile(r"\bfrom\s+tkinter\s+import\b"),
)

CONTROLLER_DIRECT_WIDGET_MUTATION_PATTERNS = (
    re.compile(r"\blog_text\.(?:insert|delete|see)\s*\("),
    re.compile(r"\bapi_status_label\.configure\s*\("),
    re.compile(r"\bstatus_label\.configure\s*\("),
)

LEGACY_ADAPTER_PATTERNS = (
    re.compile(r"\blegacy_njr_adapter\b"),
    re.compile(r"\bbuild_njr_from_legacy_pipeline_config\s*\("),
)

CONTROLLER_BACKEND_IMPORT_PATTERNS = (
    re.compile(r"\bfrom\s+src\.api\.client\s+import\s+SDWebUIClient\b"),
    re.compile(r"\bfrom\s+src\.pipeline\.pipeline_runner\s+import\s+PipelineRunner\b"),
    re.compile(
        r"\bfrom\s+src\.video\.workflow_registry\s+import\s+(?:WorkflowRegistry,\s*)?build_default_workflow_registry\b"
    ),
    re.compile(r"\bfrom\s+src\.video\.workflow_registry\s+import\s+WorkflowRegistry\b"),
)


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if "archive" in path.parts or "__pycache__" in path.parts:
            continue
        files.append(path)
    return files


def _find_pattern_hits(files: list[Path], patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for pattern in patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append(f"{rel}:{line}: {pattern.pattern}")
    return hits


def test_only_allowlisted_source_modules_import_legacy_pipeline_config_archive() -> None:
    source_files = _iter_python_files(SRC_ROOT)
    violations: list[str] = []
    for path in source_files:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in ARCHIVE_IMPORT_PATTERNS):
            if rel not in ALLOWED_ARCHIVE_IMPORT_PATHS:
                violations.append(str(rel))

    assert violations == [], (
        "Unexpected source imports of archive/reference modules:\n"
        + "\n".join(sorted(violations))
    )


def test_gui_modules_do_not_import_pipeline_runner_or_executor() -> None:
    gui_files = _iter_python_files(SRC_ROOT / "gui")
    violations = _find_pattern_hits(gui_files, GUI_PIPELINE_IMPORT_PATTERNS)
    assert violations == [], (
        "GUI modules must not import pipeline runner/executor directly:\n"
        + "\n".join(sorted(violations))
    )


def test_gui_modules_do_not_call_runner_entrypoints_directly() -> None:
    gui_files = _iter_python_files(SRC_ROOT / "gui")
    violations = _find_pattern_hits(gui_files, GUI_DIRECT_RUN_PATTERNS)
    assert violations == [], (
        "GUI modules must not invoke runner entrypoints directly:\n"
        + "\n".join(sorted(violations))
    )


def test_controller_modules_do_not_import_tkinter_directly() -> None:
    controller_files = _iter_python_files(SRC_ROOT / "controller")
    violations = _find_pattern_hits(controller_files, CONTROLLER_TK_IMPORT_PATTERNS)
    assert violations == [], (
        "Controller modules must not import tkinter directly:\n"
        + "\n".join(sorted(violations))
    )


def test_controller_modules_do_not_mutate_widgets_directly() -> None:
    controller_files = _iter_python_files(SRC_ROOT / "controller")
    violations = _find_pattern_hits(controller_files, CONTROLLER_DIRECT_WIDGET_MUTATION_PATTERNS)
    assert violations == [], (
        "Controller modules must not mutate Tk widgets directly:\n"
        + "\n".join(sorted(violations))
    )


def test_controller_modules_only_use_backend_runtime_imports_via_ports_layer() -> None:
    controller_files = _iter_python_files(SRC_ROOT / "controller")
    violations: list[str] = []
    for path in controller_files:
        text = path.read_text(encoding="utf-8")
        if not any(pattern.search(text) for pattern in CONTROLLER_BACKEND_IMPORT_PATTERNS):
            continue
        if path in ALLOWED_CONTROLLER_BACKEND_IMPORT_PATHS:
            continue
        violations.append(str(path.relative_to(ROOT)))

    assert violations == [], (
        "Controller backend/runtime imports must stay behind controller ports:\n"
        + "\n".join(sorted(violations))
    )


def test_source_does_not_reference_legacy_njr_adapter_outside_legacy_module() -> None:
    source_files = _iter_python_files(SRC_ROOT)
    violations: list[str] = []
    for path in source_files:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for pattern in LEGACY_ADAPTER_PATTERNS:
            if pattern.search(text):
                violations.append(str(rel))
                break

    assert violations == [], (
        "Legacy NJR adapter must remain isolated to its own module:\n"
        + "\n".join(sorted(violations))
    )


def test_legacy_njr_adapter_module_is_deleted() -> None:
    assert not (ROOT / "src" / "pipeline" / "legacy_njr_adapter.py").exists()
