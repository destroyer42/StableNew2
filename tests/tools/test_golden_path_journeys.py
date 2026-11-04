"""Golden-path journeys end to end (PR-TEST-DESKTOP-830).

* Simulated lane (``journey`` marker): the three journeys through the real GUI, intent, compiler, NJR, JobService,
  SQLite queue and runner, with loopback fakes only at the WebUI/Comfy API boundary.  Semantic Tk driver, hidden window.
* Windows desktop lane: opt-in (``STABLENEW_DESKTOP_LANE=1``), local interactive Windows desktop only, never in CI.  It
  drives the same journeys with real mouse and keyboard input and runs the narrow-window reachability check.  Its
  result is mandatory for local acceptance of this package.
Physical GPU execution has no test here by design: it is never run from pytest or CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.tools.test_operator_journey_gui import (
    REPO_ROOT,
    _journey_subprocess_env,
    _require_display,
    _shim_dir,
    _tracked_state,
)

pytestmark = pytest.mark.journey

_DESKTOP_LANE = os.environ.get("STABLENEW_DESKTOP_LANE") == "1"


def _run_suite(tmp_path: Path, *args: str, timeout: float = 580) -> tuple[int, dict, Path]:
    _require_display()
    env = _journey_subprocess_env(_shim_dir(tmp_path))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.operator_journey",
            "--suite",
            "golden-paths",
            "--evidence-dir",
            str(tmp_path),
            *args,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    bundle = next(tmp_path.iterdir())
    evidence = json.loads((bundle / "evidence.json").read_text(encoding="utf-8"))
    return result.returncode, evidence, bundle


@pytest.mark.parametrize("journey", ["image", "video", "learning"])
def test_simulated_journey_passes_through_the_canonical_path(tmp_path: Path, journey: str) -> None:
    before = _tracked_state()
    code, evidence, bundle = _run_suite(tmp_path, "--journey", journey, "--hide-window")
    ((journey_id, result),) = evidence["journeys"].items()
    if result["verdict"] == "HOLD" and "FFmpeg is not available" in (
        result.get("hold_reason") or ""
    ):
        # An honest HOLD (recorded in the evidence), not a PASS; the encoder tool is absent on this host.
        pytest.skip(result["hold_reason"])
    failed = [c for c in result["checks"] if not c["passed"]]
    assert code == 0 and result["verdict"] == "PASS", (result.get("failed_assertion"), failed)
    assert evidence["mode"] == "simulated" and evidence["desktop_driver"] == "tk"
    assert {t["driver"] for t in result["action_trace"]} == {"tk"}
    captured = result["captured_errors"]
    assert captured["gui"] == [] and captured["threads"] == [] and captured["logs"] == []
    assert result["isolation_violations"] == []
    for name in ("plan.json", "evidence.json", "summary.md", "actions.jsonl", "artifacts.json"):
        assert (bundle / name).is_file()
    assert _tracked_state() == before, "the journey left changes in tracked files"
    # a simulated run never claims physical evidence and labels its fixture values as such
    sources = {o["source"] for o in result["observations"]}
    assert "simulated_fixture" in sources or journey == "image"


def test_simulated_run_starts_no_model_runtime_and_refuses_real_backend_options(
    tmp_path: Path,
) -> None:
    _require_display()
    env = _journey_subprocess_env(_shim_dir(tmp_path))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.operator_journey",
            "--suite",
            "golden-paths",
            "--real-backend",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0 and "no real-backend options" in result.stderr


def _rehearse(tmp_path: Path, journey: str, *extra: str) -> tuple[int, dict, str]:
    _require_display()
    env = _journey_subprocess_env(_shim_dir(tmp_path))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.operator_journey.golden.rehearsal",
            "--journey",
            journey,
            "--evidence-dir",
            str(tmp_path),
            *extra,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=580,
    )
    evidence = json.loads((tmp_path / "rehearsal_evidence.json").read_text(encoding="utf-8"))
    return result.returncode, evidence, result.stderr


@pytest.mark.parametrize("journey", ["image", "video", "learning"])
def test_the_physical_code_path_needs_no_fake_backend_object_and_submits_the_frozen_plan(
    tmp_path: Path, journey: str
) -> None:
    """Regression for the PR-830 executor gaps: physical VID-01/LRN-01 touched fake objects, and values were not the plan's."""

    code, evidence, _ = _rehearse(tmp_path, journey)
    if evidence["verdict"] == "HOLD" and "FFmpeg is not available" in (
        evidence.get("hold_reason") or ""
    ):
        pytest.skip(evidence["hold_reason"])
    failed = [c for c in evidence["checks"] if not c["passed"]]
    assert code == 0 and evidence["verdict"] == "PASS", (
        evidence.get("failed_assertion"),
        evidence.get("abort_reason"),
        evidence.get("hold_reason"),
        failed,
    )
    assert evidence["execution_mode"] == "rehearsal" and evidence["backend_mode"] == "rehearsal"
    names = {o["name"] for o in evidence["observations"]}
    assert "fixture_image_generator" not in names and "fixture_video_generator" not in names
    assert (
        "fixture_backend" not in names and "comfy_runtime" not in names
    )  # nothing fake was handed to the journey
    assert any(o["name"] == "settings_report" for o in evidence["observations"])


@pytest.mark.parametrize(
    ("journey", "tamper"),
    [
        ("image", "steps"),
        ("image", "width"),
        ("image", "model"),
        ("image", "prompt"),
        ("video", "frames"),
        ("video", "seed"),
    ],
)
def test_a_plan_that_disagrees_with_the_njr_is_no_go_before_anything_is_queued(
    tmp_path: Path, journey: str, tamper: str
) -> None:
    code, evidence, _ = _rehearse(tmp_path, journey, "--tamper", tamper)
    if evidence["verdict"] == "HOLD" and "FFmpeg is not available" in (
        evidence.get("hold_reason") or ""
    ):
        pytest.skip(evidence["hold_reason"])
    # The journey applied the true plan; the gate compared against a corrupted copy.  The gate must decline the
    # submission (NO-GO) before anything reaches the queue.
    assert evidence["verdict"] == "NO-GO" and code == 3, evidence
    reason = evidence.get("no_go_reason") or ""
    assert "frozen plan" in reason, reason
    jobs = [o for o in evidence["observations"] if o["name"] == "job_row"]
    assert jobs == [], "a job reached the queue although the plan disagreed with the NJR"


needs_desktop = pytest.mark.skipif(
    not (_DESKTOP_LANE and sys.platform == "win32") or os.environ.get("CI"),
    reason="Windows desktop lane is opt-in: set STABLENEW_DESKTOP_LANE=1 on an interactive Windows desktop (never CI)",
)


@needs_desktop
def test_windows_desktop_lane_runs_all_three_journeys_with_real_input(tmp_path: Path) -> None:
    code, evidence, _bundle = _run_suite(
        tmp_path, "--journey", "all", "--desktop-driver", "windows"
    )
    assert code == 0 and evidence["overall_verdict"] == "PASS", {
        k: v.get("failed_assertion") for k, v in evidence["journeys"].items()
    }
    assert evidence["display"]["scaling_percent"] and evidence["display"]["width"]
    for journey_id, result in evidence["journeys"].items():
        drivers = {t["driver"] for t in result["action_trace"]}
        assert drivers == {"windows"}, (journey_id, drivers)
        assert any(t["action"] == "click" for t in result["action_trace"])
        assert any(t["action"] == "close_window" for t in result["action_trace"]), (
            "no normal exit path"
        )


@needs_desktop
def test_windows_desktop_lane_narrow_window_reachability(tmp_path: Path) -> None:
    _require_display()
    env = _journey_subprocess_env(_shim_dir(tmp_path))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.operator_journey.golden.narrow",
            "--evidence-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    evidence = json.loads((tmp_path / "narrow_evidence.json").read_text(encoding="utf-8"))
    blocked = [(c["name"], c["detail"]) for c in evidence["checks"] if not c["passed"]]
    assert result.returncode == 0 and evidence["verdict"] == "PASS" and not blocked, (
        evidence.get("failed_assertion"),
        blocked,
    )
    assert {t["driver"] for t in evidence["action_trace"]} == {"windows"}
