"""GUI-PORT-742 hermetic checks: no PySide6, no display, no production application. Pure contracts and evidence rules."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import threading
from collections import deque
from dataclasses import replace
from pathlib import Path

import pytest

from src.contracts import HistoryProjection
from src.gui.ui_tokens import TOKENS
from src.gui_v2 import design_values
from src.gui_v2.history_browser_model import HistoryFilterError, HistoryFilters, build_history_query
from src.queue.history_query import HistoryQuery
from src.queue.job_model import JobStatus
from tools.qualification.gui_port_742 import (
    child_common,
    evidence,
    fixture,
    model,
    qt_style,
    scenario,
)
from tools.qualification.gui_port_742.evidence import EvidenceError
from tools.qualification.gui_port_742.run import main as run_main
from tools.qualification.gui_port_742.wiring import Plumbing

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "tools" / "qualification" / "gui_port_742"


# ----- fixture reproducibility and shared inputs ------------------------------------------------------------------
def test_fixture_is_deterministic_in_process_and_across_processes():
    first, again = fixture.fixture_fingerprint(), fixture.fixture_fingerprint()
    assert first == again and len(first) == 64
    code = (
        f"import sys; sys.path.insert(0, {str(ROOT)!r})\n"
        "from tools.qualification.gui_port_742.fixture import fixture_fingerprint\n"
        "print(fixture_fingerprint())\n"
    )
    other = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    assert other.returncode == 0, other.stderr
    assert other.stdout.strip() == first


def test_fixture_workload_is_representative():
    history, queue = fixture.history_entries(500), fixture.queue_summaries(500)
    assert len(history) == len(queue) == 500
    assert len({e.job_id for e in history}) == 500 and len({j.job_id for j in queue}) == 500
    assert [e.created_at for e in history] == sorted((e.created_at for e in history), reverse=True)
    assert {e.status for e in history} >= {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.RUNNING,
    }
    assert max(len(e.payload_summary) for e in history) > 150  # long text is exercised
    assert any(e.error_message and len(e.error_message) > 200 for e in history)
    assert {j.status for j in queue} == {"queued", "running"}
    assert history[0].job_id == "job-00499"


def test_revisions_change_membership_and_status_but_keep_stable_identity():
    r0, r2 = fixture.history_entries(500, 0), fixture.history_entries(500, 2)
    ids0, ids2 = {e.job_id for e in r0}, {e.job_id for e in r2}
    assert len(ids0 - ids2) == len(ids2 - ids0) == 6
    by0, by2 = {e.job_id: e for e in r0}, {e.job_id: e for e in r2}
    assert (
        by0["job-00251"].status == JobStatus.COMPLETED
        and by2["job-00251"].status == JobStatus.FAILED
    )
    assert "job-00251" not in {
        e.job_id for e in fixture.history_entries(500, 3, frozenset({"job-00251"}))
    }


def test_both_toolkit_children_share_one_fixture_and_one_scenario():
    for child in ("tk_child.py", "qt_child.py"):
        text = (PACKAGE / child).read_text(encoding="utf8")
        assert "fixture_fingerprint" in text and "run_matrix" in text and "run_benchmark" in text


@pytest.fixture
def disposable_repository(tmp_path):
    from src.pipeline.cli_njr_builder import build_cli_njr
    from src.queue.job_model import Job
    from src.queue.job_repository import JobRepository

    entries = fixture.history_entries(60)
    repository = JobRepository(tmp_path / "disposable-jobs.sqlite3")
    for entry in reversed(entries):  # insertion order = oldest first, like real submission
        record = build_cli_njr(
            prompt="fixture",
            batch_size=1,
            run_name=entry.job_id,
            config={
                "txt2img": {
                    "model": "m.safetensors",
                    "steps": 4,
                    "cfg_scale": 5.0,
                    "width": 64,
                    "height": 64,
                }
            },
        )
        record = replace(record, job_id=entry.job_id)
        job = Job(job_id=entry.job_id, snapshot={"normalized_job": record.to_dict()})
        job._normalized_record = record  # type: ignore[attr-defined]
        repository.record_job_submission(job)
        with repository.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET created_at = ?, status = ?, prompt_pack_id = ?, payload_summary = ? WHERE job_id = ?",
                (
                    entry.created_at.isoformat(),
                    entry.status.value,
                    entry.prompt_pack_id,
                    entry.payload_summary,
                    entry.job_id,
                ),
            )
    return repository, entries


@pytest.mark.parametrize(
    "filters",
    [
        HistoryFilters(),
        HistoryFilters(text="dragon"),
        HistoryFilters(text="Dragon HARBOR"),
        HistoryFilters(status_label="Failed"),
        HistoryFilters(text="dragon", status_label="Failed"),
        HistoryFilters(pack="pack-landscapes"),
        HistoryFilters(date_from="2026-10-01", date_to="2026-10-01"),
        HistoryFilters(text="harbor", status_label="Completed", pack="pack-portraits"),
    ],
)
def test_fixture_matcher_agrees_with_the_real_history_query(disposable_repository, filters):
    """Guards the bounded in-memory matcher against drifting from the real query semantics."""

    repository, entries = disposable_repository
    query = filters.to_query(limit=500)
    real = [e.job_id for e in repository.query_history(query).entries]
    ours = [e.job_id for e in fixture.filter_entries(query, entries)]
    assert ours == real


# ----- navigation, filters, selection, projections ---------------------------------------------------------------
def test_navigation_ids_hold_state_and_unknown_ids():
    entries = model.nav_entries()
    assert [tab for tab, _label in entries] == [
        "prompt",
        "pipeline",
        "review",
        "photo_optimize",
        "video_workflow",
        "svd",
        "movie_clips",
        "learning",
        "character_training",
    ]
    assert dict(entries)["character_training"] == "Character Training (HOLD)"
    assert model.placeholder_body("character_training").startswith(
        "HOLD: Character Training is on hold"
    )
    assert model.placeholder_body("learning").startswith("Qualification placeholder")
    assert model.nav_group_labels() == ("Create", "Edit", "Motion", "Learn", "Advanced")
    with pytest.raises(ValueError):
        model.placeholder_title("not-a-tab")
    workspace = model.WorkspaceModel()
    assert workspace.navigate("not-a-tab") is False and workspace.tab_id == "pipeline"
    assert workspace.navigate_group("edit") and workspace.tab_id == "review"
    assert workspace.navigate_group("nope") is False


def test_filter_errors_are_user_facing_and_leave_results_unchanged():
    workspace = model.WorkspaceModel()
    workspace.set_projection(fixture.history_entries(60), fixture.queue_summaries(60))
    before = workspace.visible
    assert workspace.apply_filters(HistoryFilters(date_from="2026-13-45")) is False
    assert (workspace.notice.kind, workspace.notice.word, workspace.notice.text) == (
        "error",
        "Error",
        "From must be a date like 2026-10-18.",
    )
    assert workspace.visible is before
    assert (
        workspace.apply_filters(HistoryFilters(date_from="2026-10-05", date_to="2026-10-01"))
        is False
    )
    assert workspace.notice.text == "From must not be after To."
    with pytest.raises(HistoryFilterError):
        build_history_query(status_label="Bogus")
    assert (
        workspace.apply_filters(HistoryFilters(text="harbor")) and workspace.notice.kind != "error"
    )


def test_selection_survives_updates_and_a_vanished_selection_warns_in_words():
    workspace = model.WorkspaceModel()
    workspace.set_projection(fixture.history_entries(500, 0), fixture.queue_summaries(500, 0))
    assert (
        workspace.select("job-00251") and workspace.selected_entry().status == JobStatus.COMPLETED
    )
    workspace.set_projection(fixture.history_entries(500, 2), fixture.queue_summaries(500, 2))
    assert (
        workspace.selected_id == "job-00251"
        and workspace.selected_entry().status == JobStatus.FAILED
    )
    workspace.set_projection(
        fixture.history_entries(500, 3, frozenset({"job-00251"})), workspace.queue
    )
    assert workspace.selected_id is None and workspace.details() == model.NO_SELECTION_TEXT
    assert workspace.notice.word == "Warning" and "job-00251" in workspace.notice.text
    assert workspace.select("job-99999") is False


def test_selection_is_never_color_only():
    entry = fixture.history_entry(7)
    assert model.history_cells(entry, True)[0].startswith(model.SELECTED_MARKER)
    assert not model.history_cells(entry, False)[0].startswith(model.SELECTED_MARKER)
    assert model.details_heading(entry).startswith("Selected job-00007")
    assert {
        model.Notice(kind, "x").word for kind in ("neutral", "info", "success", "warning", "error")
    } == {
        "Note",
        "Info",
        "Success",
        "Warning",
        "Error",
    }


def test_the_shared_scenario_passes_on_the_toolkit_free_driver():
    driver = scenario.ModelDriver()
    try:
        steps = scenario.run_scenario(driver)
    finally:
        driver.close()
    assert [s.name for s in steps][:2] == ["startup", "filter_text_and_status"]
    assert all(s.ok for s in steps), [(s.name, s.expected, s.observed) for s in steps if not s.ok]
    assert "keyboard_focus_order" not in {
        s.name for s in steps
    }  # needs a toolkit; offered only with "keyboard"


def test_the_scenario_detects_a_driver_that_loses_selection():
    class Broken(scenario.ModelDriver):
        def select(self, job_id: str) -> bool:
            return False

    driver = Broken()
    try:
        steps = {s.name: s for s in scenario.run_scenario(driver)}
    finally:
        driver.close()
    assert (
        steps["select_and_inspect"].ok is False and steps["refresh_preserves_selection"].ok is False
    )


def test_stale_projection_revisions_are_skipped_by_the_real_sink():
    delivered: list[int] = []
    plumbing = Plumbing(
        _ImmediateTestDispatcher(),
        on_history=lambda: delivered.append(1),
        on_queue=lambda: None,
        on_status=lambda: None,
        count=40,
    )
    plumbing.publish(2, sink_revision=5)
    plumbing.publish(1, sink_revision=4)  # older than the applied revision
    plumbing.publish(2, sink_revision=5)  # equal revision is also not newer
    metrics = plumbing.sink.get_metrics_snapshot()
    assert metrics["skipped_counts"]["history"] == 2 and metrics["applied_counts"]["history"] == 1
    assert plumbing.state.history_items[0].job_id == fixture.history_entries(40, 2)[0].job_id
    assert isinstance(HistoryProjection(revision=1), HistoryProjection)
    plumbing.close()


class _ImmediateTestDispatcher:
    def schedule(self, fn):
        fn()

    def invoke_later(self, delay_ms, fn):
        fn()

    def run_on_ui_thread(self, fn):
        fn()


class _QueueDispatcher:
    """A UI thread is whoever calls ``pump``; workers can only enqueue (the contract both toolkits implement)."""

    def __init__(self):
        self.queue, self.lock, self.ui = deque(), threading.Lock(), threading.get_ident()

    def schedule(self, fn):
        with self.lock:
            self.queue.append(fn)

    def invoke_later(self, delay_ms, fn):
        self.schedule(fn)

    def run_on_ui_thread(self, fn):
        fn() if threading.get_ident() == self.ui else self.schedule(fn)

    def pump(self):
        while True:
            with self.lock:
                if not self.queue:
                    return
                fn = self.queue.popleft()
            fn()


def test_worker_projections_reach_listeners_only_on_the_ui_thread_and_not_after_close():
    dispatcher, seen = _QueueDispatcher(), []
    plumbing = Plumbing(
        dispatcher,
        on_history=lambda: seen.append(threading.get_ident()),
        on_queue=lambda: None,
        on_status=lambda: None,
        count=30,
    )
    worker = threading.Thread(target=lambda: plumbing.publish(1, sink_revision=1))
    worker.start()
    worker.join()
    assert seen == []  # queued, not delivered from the worker
    dispatcher.pump()
    assert seen and set(seen) == {dispatcher.ui}
    count = len(seen)
    late = threading.Thread(target=lambda: plumbing.publish(2, sink_revision=2))
    late.start()
    late.join()
    plumbing.close()  # callbacks still queued behind the close must not reach the (destroyed) view
    dispatcher.pump()
    assert len(seen) == count


# ----- evidence validity ------------------------------------------------------------------------------------------
def test_summaries_reject_invalid_samples_and_report_p95_only_when_meaningful():
    assert evidence.summarize([3, 1, 2, 5, 4], expected_n=5) == {
        "n": 5,
        "min": 1,
        "median": 3,
        "p95": None,
        "max": 5,
    }
    twenty = evidence.summarize(list(range(1, 21)))
    assert twenty["p95"] == 19 and twenty["median"] == 10.5
    for bad in ([], [1, float("nan")], [1, float("inf")], [1, -1], [1, True], [1, "2"]):
        with pytest.raises(EvidenceError):
            evidence.summarize(bad)
    with pytest.raises(EvidenceError):
        evidence.summarize([1, 2, 3], expected_n=5)


def test_duplicate_missing_and_reordered_updates_are_rejected():
    evidence.validate_sequence(4, [0, 1, 2, 3], lossless=True)
    for broken in ([0, 1, 3], [0, 1, 1, 2, 3], [1, 0, 2, 3]):
        with pytest.raises(EvidenceError):
            evidence.validate_sequence(4, broken, lossless=True)
    evidence.validate_sequence(40, [3, 9, 20, 39], lossless=False)  # coalesced hot-key stream
    for broken in ([], [3, 3, 39], [9, 3, 39], [3, 9, 20], list(range(41))):
        with pytest.raises(EvidenceError):
            evidence.validate_sequence(40, broken, lossless=False)


def test_visibility_evidence_must_be_complete():
    first, result = (
        {"visible": True, "exposed": True, "clock_ns": 10},
        {"clock_ns": 20, "warm_visible_rendered": True},
    )
    evidence.validate_visibility(first, result, "qt", require_second_window=True)
    for bad_first, bad_result, toolkit in (
        (None, result, "tk"),
        ({"visible": False, "clock_ns": 10}, result, "tk"),
        ({"visible": True, "clock_ns": 10}, result, "qt"),  # Qt must also be exposed
        (
            {"visible": True, "exposed": True, "clock_ns": 30},
            result,
            "qt",
        ),  # stamp after the result
        ({"visible": True, "exposed": True}, result, "qt"),
        (first, {"clock_ns": 20}, "qt"),
        (first, None, "qt"),
    ):
        with pytest.raises(EvidenceError):
            evidence.validate_visibility(bad_first, bad_result, toolkit, require_second_window=True)
    evidence.validate_visibility(
        first, {"clock_ns": 20}, "qt"
    )  # second window only required for benchmarks


def test_process_records_reject_timeouts_failures_survivors_and_missing_containment():
    good = {
        "exit_code": 0,
        "timeout": False,
        "contained": True,
        "surviving_descendants": [],
        "result": {"status": "PASS"},
    }
    evidence.validate_process_record(good)
    for patch in (
        {"timeout": True},
        {"exit_code": 1},
        {"exit_code": None},
        {"result": None},
        {"contained": False},
        {"surviving_descendants": [123]},
        {"result": {"status": "FAIL"}},
    ):
        with pytest.raises(EvidenceError):
            evidence.validate_process_record(good | patch)


@pytest.mark.parametrize(
    ("record", "valid", "kind"),
    [
        (
            {
                "requested": "actual-100",
                "awareness": "per_monitor_v2",
                "monitor_dpi": 96,
                "window_dpi": 96,
            },
            True,
            "ACTUAL",
        ),
        (
            {
                "requested": "actual-150",
                "awareness": "per_monitor_v2",
                "monitor_dpi": 144,
                "window_dpi": 144,
            },
            True,
            "ACTUAL",
        ),
        (
            {
                "requested": "actual-150",
                "awareness": "per_monitor_v2",
                "monitor_dpi": 96,
                "window_dpi": 96,
            },
            False,
            "ACTUAL",
        ),
        (
            {
                "requested": "simulated-150",
                "awareness": "per_monitor_v2",
                "monitor_dpi": 96,
                "window_dpi": 96,
                "simulated_factor": 1.5,
            },
            True,
            "SIMULATED",
        ),
        (
            {
                "requested": "simulated-150",
                "awareness": "per_monitor_v2",
                "monitor_dpi": 96,
                "window_dpi": 96,
            },
            False,
            "ACTUAL",
        ),
        (
            {
                "requested": "actual-100",
                "awareness": "per_monitor_v2",
                "monitor_dpi": 96,
                "window_dpi": 96,
                "simulated_factor": 1.5,
            },
            False,
            "SIMULATED",
        ),
        (
            {"requested": "actual-100", "awareness": "other", "monitor_dpi": 96, "window_dpi": 96},
            False,
            "ACTUAL",
        ),
        (
            {
                "requested": "actual-100",
                "awareness": "per_monitor_v2",
                "monitor_dpi": 96,
                "window_dpi": 120,
            },
            False,
            "ACTUAL",
        ),
        ({"requested": "actual-100", "awareness": "per_monitor_v2"}, False, "ACTUAL"),
    ],
)
def test_dpi_records_never_pass_a_simulation_or_a_contradicted_claim_as_real(record, valid, kind):
    verdict = evidence.interpret_dpi(record)
    assert verdict["valid"] is valid and verdict["classification"] == kind


def test_reachability_flags_missing_hidden_offscreen_clipped_and_overlapping_controls():
    def box(x, y, w=100, h=30, **extra):
        return {"x": x, "y": y, "w": w, "h": h, "visible": True, "text_clipped": False} | extra

    controls = {name: box(i * 110, 0) for i, name in enumerate(evidence.REQUIRED_CONTROLS)}
    assert evidence.evaluate_reachability(controls, (110 * len(controls), 100)) == []
    broken = dict(controls)
    broken.pop("nav")
    broken["search"] = box(0, 0, visible=False)
    broken["apply"] = box(5000, 0)
    broken["clear"] = box(110 * 6, 0, text_clipped=True)
    broken["details"] = box(controls["queue_table"]["x"] + 10, 0)  # overlaps queue_table
    issues = " | ".join(evidence.evaluate_reachability(broken, (1500, 100)))
    for expected in (
        "nav: missing",
        "search: not visible",
        "apply: outside",
        "clear: text clipped",
        "queue_table overlaps details",
    ):
        assert expected in issues


def test_cross_toolkit_parity_reports_any_semantic_difference():
    a = [{"name": "s1", "ok": True, "expected": 1, "observed": 2}]
    assert evidence.compare_parity(a, [dict(a[0])]) == []
    assert evidence.compare_parity(a, [a[0] | {"observed": 3}])
    assert evidence.compare_parity(a, [a[0] | {"ok": False}])
    assert evidence.compare_parity(a, [])


def test_dispatch_policy_decomposition_and_invalid_inputs():
    verdict = evidence.dispatch_policy_ratio(2.0, 510.0, 537.0)
    assert verdict["policy_share"] == pytest.approx((510 - 2) / (537 - 2))
    assert verdict["residual_gap_ms"] == pytest.approx(27.0)
    assert (
        evidence.dispatch_policy_ratio(600.0, 600.0, 537.0)["policy_share"] is None
    )  # Qt not faster: no share
    for bad in (float("nan"), -1.0):
        with pytest.raises(EvidenceError):
            evidence.dispatch_policy_ratio(bad, 1.0, 1.0)


# ----- isolation, imports and write authority --------------------------------------------------------------------
def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


def test_toolkit_imports_stay_in_their_own_modules():
    tk_only, qt_only = (
        {"tk_view.py", "tk_child.py"},
        {"qt_view.py", "qt_child.py", "qt_dispatchers.py"},
    )
    for path in PACKAGE.glob("*.py"):
        modules = _imports(path)
        uses_tk = any(m == "tkinter" or m.startswith("tkinter.") for m in modules)
        uses_qt = any(m == "PySide6" or m.startswith("PySide6.") for m in modules)
        assert uses_tk == (path.name in tk_only), path.name
        assert uses_qt == (path.name in qt_only), path.name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "PySide6":
                assert {a.name for a in node.names} <= {"QtCore", "QtGui", "QtWidgets"}


def test_no_production_application_database_backend_or_runner_imports():
    forbidden = (
        "src.main",
        "src.app_factory",
        "src.controller.app_controller",
        "src.gui.main_window_v2",
        "src.queue.job_repository",
        "src.queue.single_node_runner",
        "src.pipeline.pipeline_runner",
        "src.api",
        "sqlite3",
        "requests",
        "socket",
        "urllib",
    )
    for path in PACKAGE.glob("*.py"):
        for module in _imports(path):
            assert not any(module == f or module.startswith(f + ".") for f in forbidden), (
                path.name,
                module,
            )


def test_only_the_parent_may_spawn_processes_or_write_files():
    for path in PACKAGE.glob("*.py"):
        modules = _imports(path)
        text = path.read_text(encoding="utf8")
        if path.name not in {"run.py", "launch.py"}:
            assert "subprocess" not in modules and "os.system" not in text, path.name
            assert not re.search(r"\.write_text\(|\.write_bytes\(|open\([^)]*['\"][wax]", text), (
                path.name
            )
        if path.name == "run.py":
            writes = re.findall(r"\.write_text\(", text)
            assert writes and all(
                "args.output" in line or "hold" in line or "report" in line
                for line in text.splitlines()
                if ".write_text(" in line
            )


@pytest.mark.parametrize(
    "module", ["fixture", "model", "scenario", "evidence", "qt_style", "wiring", "child_common"]
)
def test_pure_modules_import_with_neither_tkinter_nor_pyside_available(module):
    code = f"""
import importlib.abc, sys
sys.path.insert(0, {str(ROOT)!r})
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('tkinter', '_tkinter', 'PySide6', 'shiboken6'):
            raise ImportError('blocked ' + name)
sys.meta_path.insert(0, Block())
import importlib
importlib.import_module('tools.qualification.gui_port_742.{module}')
print('ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_qt_style_adapter_introduces_no_palette_of_its_own():
    sheet = qt_style.build_stylesheet()
    allowed = {
        v.upper()
        for v in vars(design_values.Colors).values()
        if isinstance(v, str) and v.startswith("#")
    }
    allowed |= {
        v.upper()
        for v in (
            *(getattr(TOKENS.colors, f) for f in TOKENS.colors.__dataclass_fields__),
            *(
                c
                for kind in design_values.NOTICE_KINDS
                for c in (
                    TOKENS.notices.role(kind).foreground,
                    TOKENS.notices.role(kind).label_foreground,
                    TOKENS.notices.role(kind).background,
                    TOKENS.notices.role(kind).accent,
                )
            ),
        )
        if isinstance(v, str) and v.startswith("#")
    }
    used = {m.upper() for m in re.findall(r"#[0-9A-Fa-f]{6}\b", sheet)}
    assert used and used <= allowed, used - allowed
    assert f":focus {{ border: 2px solid {TOKENS.colors.focus_ring}; }}" in sheet
    for kind in design_values.NOTICE_KINDS:
        assert f"noticeKind='{kind}'" in sheet


def test_proof_dependencies_and_lock_stay_out_of_production_requirements():
    for name in ("requirements.txt", "requirements-dev.txt", "pyproject.toml"):
        assert "pyside" not in (ROOT / name).read_text(encoding="utf8").lower(), name
    assert not any(p.name.startswith("gui_qt") for p in (ROOT / "src").iterdir())


# ----- opt-in entry point and argument bounds --------------------------------------------------------------------
def test_default_entrypoint_is_not_run_and_imports_no_toolkit(capsys):
    before = {m for m in sys.modules if m.startswith("PySide6")}
    assert run_main([]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT RUN"
    assert {m for m in sys.modules if m.startswith("PySide6")} == before


@pytest.mark.parametrize(
    "extra", [["--samples", "4"], ["--samples", "11"], ["--rows", "10"], ["--phases", "bogus"]]
)
def test_invalid_run_bounds_are_refused_before_any_directory_or_window(tmp_path, extra):
    with pytest.raises(SystemExit):
        run_main(["--allow-gui", "--output", str(tmp_path / "unused"), *extra])
    assert not (tmp_path / "unused").exists()
    with pytest.raises(SystemExit):
        run_main(["--allow-gui", "--output", "relative-dir"])


def test_child_arguments_are_bounded():
    parser = child_common.build_parser("x")
    for bad in (
        ["--mode", "matrix", "--rows", "5"],
        ["--mode", "matrix", "--sim-scale", "9"],
        ["--mode", "a11y"],
    ):
        with pytest.raises(SystemExit):
            child_common.validate_args(parser, parser.parse_args(bad))
    child_common.validate_args(parser, parser.parse_args(["--mode", "benchmark"]))
    assert child_common.parse_viewport("max") == (None, None) and child_common.parse_viewport(
        "1366x768"
    ) == (1366, 768)


def test_forbid_modules_refuses_the_import_itself():
    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from tools.qualification.gui_port_742 import child_common as cc
cc.forbid(('json',))
try:
    import json
except ImportError as error:
    print('refused', error)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    assert "refused GUI-PORT-742 forbids importing json" in result.stdout, result.stderr


def test_a_query_built_from_the_filter_bar_is_the_one_the_matcher_receives():
    query = HistoryFilters(text="dragon", status_label="Failed").to_query(limit=500)
    assert isinstance(query, HistoryQuery) and query.statuses == frozenset({JobStatus.FAILED})
    assert query.terms == ("dragon",)


def test_timing_dependent_counts_are_never_part_of_the_parity_compared_outcome():
    driver = scenario.ModelDriver()
    try:
        steps = {s.name: s for s in scenario.run_scenario(driver)}
    finally:
        driver.close()
    stream = steps["worker_status_stream"]
    assert "deliveries" not in stream.observed and "deliveries" not in stream.semantic()["observed"]
    assert "updates delivered" in stream.note


def test_tk_heartbeat_stopped_chain_never_feeds_the_next_run() -> None:
    """A pending ``after`` from a stopped heartbeat must not double the rate of the next one (loaded-gap bias)."""

    from types import SimpleNamespace

    from tools.qualification.gui_port_742.tk_view import TkWorkspace

    pending: list = []
    view = SimpleNamespace(toplevel=SimpleNamespace(after=lambda _ms, fn: pending.append(fn)))
    TkWorkspace.start_heartbeat(view)
    stale = pending.pop()
    TkWorkspace.stop_heartbeat(view)
    TkWorkspace.start_heartbeat(view)  # the second run begins before the first run's timer fires
    stale()
    assert (
        view._gaps == [] and len(pending) == 1
    )  # the stale callback neither records nor reschedules
    pending.pop()()
    assert len(view._gaps) == 1 and len(pending) == 1


def test_expected_step_count_matches_the_scenario_and_empty_parity_is_rejected() -> None:
    from tools.qualification.gui_port_742.run import EXPECTED_STEPS

    driver = scenario.ModelDriver()
    try:
        steps = scenario.run_scenario(driver)
    finally:
        driver.close()
    # the toolkit-free driver offers no keyboard capability, which adds exactly these three steps
    keyboard = {"keyboard_focus_order", "keyboard_row_navigation", "scroll_to_selection"}
    source = Path(scenario.__file__).read_text(encoding="utf8")
    assert all(f'"{name}"' in source for name in keyboard)
    assert len(steps) + len(keyboard) == EXPECTED_STEPS
    assert evidence.compare_parity([], [])


def test_tk_heartbeat_is_drift_compensated_and_never_below_one_millisecond() -> None:
    from types import SimpleNamespace

    from tools.qualification.gui_port_742.tk_view import TkWorkspace

    delays: list[int] = []
    pending: list = []

    def after(ms, fn) -> None:
        delays.append(ms)
        pending.append(fn)

    view = SimpleNamespace(toplevel=SimpleNamespace(after=after))
    TkWorkspace.start_heartbeat(view)
    pending.pop()()  # a late beat re-arms against the original schedule, not "interval after now"
    assert all(delay >= 1 for delay in delays)
