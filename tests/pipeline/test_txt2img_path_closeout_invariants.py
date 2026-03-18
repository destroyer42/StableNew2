from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATTERNS = (
    "run_full_pipeline(",
    "_run_full_pipeline_impl(",
    "def run_txt2img(",
    "def _run_txt2img_impl(",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_cli_uses_canonical_njr_txt2img_path() -> None:
    cli_text = _read_text(REPO_ROOT / "src" / "cli.py")

    assert "build_cli_njr(" in cli_text
    assert "run_njr(" in cli_text
    assert "run_full_pipeline(" not in cli_text


def test_live_source_and_active_tests_do_not_reintroduce_retired_txt2img_entrypoints() -> None:
    scanned_files = list((REPO_ROOT / "src").rglob("*.py"))
    scanned_files.extend((REPO_ROOT / "tests").rglob("*.py"))

    violations: list[str] = []
    for path in scanned_files:
        if path == Path(__file__).resolve():
            continue
        text = _read_text(path)
        for pattern in LEGACY_PATTERNS:
            if pattern in text:
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}: {pattern}")

    assert violations == []
