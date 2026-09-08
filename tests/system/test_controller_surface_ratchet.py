from __future__ import annotations

import json
from pathlib import Path

from tools.ci.check_controller_surface import inspect_controller_surfaces


def _source(lines: int) -> str:
    return "".join(f"VALUE_{index} = {index}\n" for index in range(lines))


def _write_baseline(root: Path, *, ceiling: int, new_limit: int = 5) -> Path:
    baseline = root / "tools/ci/controller_surface_baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "metric": "physical_lines",
                "new_controller_limit": new_limit,
                "ceilings": {"src/controller/app_controller.py": ceiling},
            }
        ),
        encoding="utf-8",
    )
    return baseline


def _controller(root: Path, name: str, lines: int) -> None:
    path = root / "src/controller" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_source(lines), encoding="utf-8")


def _codes(root: Path, baseline: Path) -> set[str]:
    return {issue.code for issue in inspect_controller_surfaces(root, baseline)}


def test_equal_current_ceiling_passes(tmp_path: Path) -> None:
    baseline = _write_baseline(tmp_path, ceiling=3)
    _controller(tmp_path, "app_controller.py", 3)

    assert inspect_controller_surfaces(tmp_path, baseline) == []


def test_growth_fails(tmp_path: Path) -> None:
    baseline = _write_baseline(tmp_path, ceiling=3)
    _controller(tmp_path, "app_controller.py", 4)

    assert _codes(tmp_path, baseline) == {"CONTROLLER_GROWTH"}


def test_reduction_without_lowering_ceiling_fails_actionably(tmp_path: Path) -> None:
    baseline = _write_baseline(tmp_path, ceiling=3)
    _controller(tmp_path, "app_controller.py", 2)

    issues = inspect_controller_surfaces(tmp_path, baseline)

    assert {issue.code for issue in issues} == {"CEILING_NOT_LOWERED"}
    assert "lower the checked-in ceiling" in issues[0].detail


def test_reduction_with_lowered_ceiling_passes(tmp_path: Path) -> None:
    baseline = _write_baseline(tmp_path, ceiling=2)
    _controller(tmp_path, "app_controller.py", 2)

    assert inspect_controller_surfaces(tmp_path, baseline) == []


def test_new_oversized_top_level_controller_fails(tmp_path: Path) -> None:
    baseline = _write_baseline(tmp_path, ceiling=3, new_limit=5)
    _controller(tmp_path, "app_controller.py", 3)
    _controller(tmp_path, "new_controller.py", 6)

    assert _codes(tmp_path, baseline) == {"NEW_OVERSIZED_CONTROLLER"}
