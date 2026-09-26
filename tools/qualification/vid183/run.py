"""PR-VID-183 controlled Animate runner: exactly A then B, one submission each, no retry.

The implementation delegates process ownership, preflight, telemetry, graph construction, and
cleanup to the accepted PR-VID-181 runner.  This module only substitutes the PR-VID-183 frozen
controls and report/workspace roots; it cannot add a third case or ``face_video``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.qualification.vid181 import run as accepted_runner

REPORTS_ROOT = Path("reports/vid183")
WORKSPACE = Path(r"C:\Users\rob\qual\vid183\out")
CASES = ["A", "B"]
CONTROLS: dict[str, dict[str, str]] = {
    "A": {
        "workspace": "A/final_pose_480x832_13f.mp4",
        "staged": "reports/vid183/control_a_480x832_13f.mp4",
        "sha256": "ac2e52c476176cfcc023b60552e29f817c10e73ba61ac4b0cc43895d3f43fc82",
    },
    "B": {
        "workspace": "B/final_pose_480x832_13f.mp4",
        "staged": "reports/vid183/control_b_480x832_13f.mp4",
        "sha256": "eb4aa6fb701a15dbfcf28fe7d4c7dc70e871a6fd9e052d07ec3e4e67bb2e3dde",
    },
}


def _resolved_controls() -> dict[str, dict[str, str]]:
    """The only accepted controls are the recorded CPU-gated A/B files."""

    return CONTROLS


def verify_pair_evidence() -> None:
    """Refuse GPU submission unless the CPU pair gate verified both frozen bytes."""

    path = WORKSPACE / "B" / "pair_validation.json"
    if not path.exists():
        raise RuntimeError("BASIC_RETARGET_CONTROL_INVALID: missing CPU pair-validation evidence")
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {"a_sha256": CONTROLS["A"]["sha256"], "b_sha256": CONTROLS["B"]["sha256"]}
    if {key: record.get(key) for key in expected} != expected:
        raise RuntimeError("BASIC_RETARGET_CONTROL_INVALID: pair-validation hashes do not match")
    if record.get("mean_frame_pixel_delta", 0.0) < 1.0 or record.get("motion_energy_b", 0.0) <= 0.0:
        raise RuntimeError(
            "BASIC_RETARGET_CONTROL_INVALID: CPU pair validation did not retain motion"
        )


def verify_control(case: str) -> Path:
    if case not in CASES:
        raise ValueError(f"unknown case {case!r}; expected A or B")
    original_controls, original_workspace = accepted_runner.CONTROLS, accepted_runner.WORKSPACE
    try:
        accepted_runner.CONTROLS, accepted_runner.WORKSPACE = _resolved_controls(), WORKSPACE
        return accepted_runner.verify_control(case, workspace=WORKSPACE)
    finally:
        accepted_runner.CONTROLS, accepted_runner.WORKSPACE = original_controls, original_workspace


def run_case(args: argparse.Namespace) -> int:
    """Delegate exactly one eligible A or B run; no retry or external-endpoint adoption."""

    verify_pair_evidence()
    verify_control(args.case)
    original_controls, original_workspace, original_reports = (
        accepted_runner.CONTROLS,
        accepted_runner.WORKSPACE,
        accepted_runner.REPORTS_ROOT,
    )
    try:
        accepted_runner.CONTROLS, accepted_runner.WORKSPACE = _resolved_controls(), WORKSPACE
        accepted_runner.REPORTS_ROOT = REPORTS_ROOT
        return accepted_runner.run_case(args)
    finally:
        accepted_runner.CONTROLS, accepted_runner.WORKSPACE, accepted_runner.REPORTS_ROOT = (
            original_controls,
            original_workspace,
            original_reports,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_image")
    parser.add_argument("--case", required=True, choices=CASES)
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args(argv)
    state = accepted_runner.preflight()
    print(state)
    if state["endpoint_state"] == "healthy":
        print(
            "STOP: an external ComfyUI already serves the configured endpoint; it will not be adopted or restarted."
        )
        return 3
    if args.dry:
        verify_control(args.case)
        return 0
    return run_case(args)


if __name__ == "__main__":
    raise SystemExit(main())
