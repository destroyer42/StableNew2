from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

TRACKED_RUNTIME_PATHS = (
    "state",
    "src/state/queue_state_v2.json",
)


def test_runtime_state_files_are_not_tracked_by_git() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--", *TRACKED_RUNTIME_PATHS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert tracked == [], (
        "Runtime state files must not be tracked by git:\n"
        + "\n".join(sorted(tracked))
    )
