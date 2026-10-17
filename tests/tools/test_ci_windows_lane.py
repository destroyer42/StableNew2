"""The Windows platform-contract lane (audit P1-3): a positive target list that stays valid, and a workflow job that cannot mask."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import run_windows_lane as lane  # noqa: E402

WORKFLOW = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _windows_job() -> str:
    return WORKFLOW[WORKFLOW.index("\n  windows:") :]


def test_every_lane_target_still_exists() -> None:
    missing = [
        target
        for target in lane.WINDOWS_LANE_TARGETS
        if not (ROOT / target.partition("::")[0]).exists()
    ]
    assert missing == []


def test_the_lane_covers_each_platform_contract_it_exists_for() -> None:
    targets = " ".join(lane.WINDOWS_LANE_TARGETS)
    for contract, marker in {
        "process containment": "test_job_object_isolation",
        "atomic replacement": "test_atomic_io",
        "windows path escaping": "test_diagnose_asset_registry_cache_145",
        "sqlite persistence": "test_job_repository_sqlite",
        "production wiring": "test_production_wiring_startup_gate",
        "photo optimize windows migration": "tests/photo_optimize",
        "tk construction": "test_p0_6_silent_failure_regressions",
    }.items():
        assert marker in targets, contract


def test_the_lane_uses_the_isolated_pollution_detecting_runner_with_a_per_test_timeout() -> None:
    source = (ROOT / "tools" / "ci" / "run_windows_lane.py").read_text(encoding="utf-8")
    assert "run_pytest_gate" in source and "subprocess" not in source  # no second pytest runner
    runner = (ROOT / "tools" / "ci" / "run_collection_gate.py").read_text(encoding="utf-8")
    assert (
        "ignore_cleanup_errors=True" in runner
    )  # Windows long/locked test paths must not fail a green gate on cleanup
    command = lane.build_command()
    assert "--timeout=300" in command and "-x" not in command  # runs to completion, like the census


def test_the_workflow_job_runs_on_windows_with_the_pinned_tools_and_never_masks_a_failure() -> None:
    job = _windows_job()
    assert "runs-on: windows-latest" in job
    assert "needs: required" in job and "needs.required.outputs.full_census == 'true'" in job
    assert "pip install -r requirements.txt -r requirements-dev.txt" in job
    assert "python tools/ci/run_windows_lane.py" in job
    assert "timeout-minutes:" in job
    assert "continue-on-error" not in job


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only expectations")
def test_on_windows_the_lane_targets_are_collectable() -> None:
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *lane.WINDOWS_LANE_TARGETS,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-800:]
