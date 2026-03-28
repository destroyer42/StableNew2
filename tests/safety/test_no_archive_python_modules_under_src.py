from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

ARCHIVE_DIRS = (
    ROOT / "src" / "controller" / "archive",
    ROOT / "src" / "gui" / "views" / "archive",
    ROOT / "src" / "gui" / "panels_v2" / "archive",
)


def test_no_python_modules_remain_under_src_archive_directories() -> None:
    violations: list[str] = []
    for archive_dir in ARCHIVE_DIRS:
        if not archive_dir.exists():
            continue
        for path in archive_dir.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            violations.append(str(path.relative_to(ROOT)))

    assert violations == [], (
        "Archive directories under src must not contain Python modules:\n"
        + "\n".join(sorted(violations))
    )
