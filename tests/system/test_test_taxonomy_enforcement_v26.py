from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "tests"

ALLOWED_ARCHIVE_IMPORT_TEST_PREFIXES = (
    TEST_ROOT / "compat",
    TEST_ROOT / "quarantine",
    TEST_ROOT / "legacy",
)

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


def _iter_test_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("test_*.py")
        if "__pycache__" not in path.parts
    ]


def _is_allowed_archive_import_path(path: Path) -> bool:
    return any(prefix in path.parents or path == prefix for prefix in ALLOWED_ARCHIVE_IMPORT_TEST_PREFIXES)


def test_archive_pipeline_config_imports_are_isolated_to_compat_surfaces() -> None:
    violations: list[str] = []
    for path in _iter_test_files(TEST_ROOT):
        text = path.read_text(encoding="utf-8")
        if not any(pattern.search(text) for pattern in ARCHIVE_IMPORT_PATTERNS):
            continue
        if _is_allowed_archive_import_path(path):
            continue
        violations.append(str(path.relative_to(ROOT)))

    assert violations == [], (
        "Archive/reference imports must stay in compat-only test surfaces:\n"
        + "\n".join(sorted(violations))
    )
