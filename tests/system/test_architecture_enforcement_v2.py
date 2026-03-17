from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"

ALLOWED_ARCHIVE_IMPORT_PATHS = {
    Path("src/controller/app_controller.py"),
    Path("src/controller/pipeline_controller.py"),
    Path("src/pipeline/legacy_njr_adapter.py"),
}

ARCHIVE_IMPORT_PATTERNS = (
    re.compile(r"\bfrom\s+src\.controller\.archive\.pipeline_config_types\s+import\b"),
    re.compile(r"\bfrom\s+src\.controller\.archive\.pipeline_config_assembler\s+import\b"),
    re.compile(r"\bimport\s+src\.controller\.archive\.pipeline_config_types\b"),
    re.compile(r"\bimport\s+src\.controller\.archive\.pipeline_config_assembler\b"),
)

GUI_PIPELINE_IMPORT_PATTERNS = (
    re.compile(r"\bfrom\s+src\.pipeline\.(pipeline_runner|executor)\s+import\b"),
    re.compile(r"\bimport\s+src\.pipeline\.(pipeline_runner|executor)\b"),
)

GUI_DIRECT_RUN_PATTERNS = (
    re.compile(r"\bpipeline_runner\.run\s*\("),
    re.compile(r"\brun_njr_v2\s*\("),
)

LEGACY_ADAPTER_PATTERNS = (
    re.compile(r"\blegacy_njr_adapter\b"),
    re.compile(r"\bbuild_njr_from_legacy_pipeline_config\s*\("),
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
        "Unexpected non-legacy source imports of pipeline_config archive modules:\n"
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


def test_source_does_not_reference_legacy_njr_adapter_outside_legacy_module() -> None:
    source_files = _iter_python_files(SRC_ROOT)
    violations: list[str] = []
    for path in source_files:
        rel = path.relative_to(ROOT)
        if rel == Path("src/pipeline/legacy_njr_adapter.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in LEGACY_ADAPTER_PATTERNS:
            if pattern.search(text):
                violations.append(str(rel))
                break

    assert violations == [], (
        "Legacy NJR adapter must remain isolated to its own module:\n"
        + "\n".join(sorted(violations))
    )
