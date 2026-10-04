"""PR-DEVEX-CI-110: the JUnit test-census summarizer (measurement only; deterministic fixture)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ci"))

import census_summary as cs  # noqa: E402

XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="5" time="12.5">
  <testcase classname="tests.queue.test_repo" name="test_a" time="1.5"/>
  <testcase classname="tests.queue.test_repo.TestX" name="test_b" time="3.0"/>
  <testcase classname="tests.gui_v2.test_panel" name="test_c" time="6.0"/>
  <testcase classname="tests.test_top" name="test_d" time="0.5"><skipped message="needs cv2" type="pytest.skip"/></testcase>
  <testcase classname="tests.queue.test_repo" name="test_e" time="0.5"><failure message="boom"/></testcase>
</testsuite></testsuites>
"""


def test_the_summary_reports_totals_files_areas_slowest_and_skip_reasons(tmp_path: Path) -> None:
    path = tmp_path / "census.xml"
    path.write_text(XML, encoding="utf-8")
    summary = cs.summarize(path, top=2)
    assert (summary["collected"], summary["passed"], summary["failed"], summary["skipped"]) == (5, 3, 1, 1)
    assert summary["suite_wall_seconds"] == 12.5 and summary["sum_test_seconds"] == 11.5
    assert [r["id"] for r in summary["slowest"]] == ["tests/gui_v2/test_panel.py::test_c", "tests/queue/test_repo.py::test_b"]
    assert summary["by_file"][0] == {"file": "tests/gui_v2/test_panel.py", "tests": 1, "seconds": 6.0}
    assert {r["area"]: r["seconds"] for r in summary["by_area"]} == {"gui_v2": 6.0, "queue": 5.0, "(top-level)": 0.5}
    assert summary["skipped_reasons"] == [("needs cv2", 1)]


def test_markdown_rendering_is_deterministic_and_complete(tmp_path: Path) -> None:
    path = tmp_path / "census.xml"
    path.write_text(XML, encoding="utf-8")
    text = cs.render_markdown(cs.summarize(path))
    for heading in ("## Test census", "### Time by top-level area", "### Skipped reasons"):
        assert heading in text
    assert "collected 5: 3 passed, 1 failed" in text and "needs cv2" in text


def test_module_file_is_derived_from_the_first_test_segment() -> None:
    assert cs.module_file_from_classname("tests.system.test_x.TestY.TestZ") == "tests/system/test_x.py"
    assert cs.area_of("tests/system/test_x.py") == "system" and cs.area_of("tests/test_top.py") == "(top-level)"
