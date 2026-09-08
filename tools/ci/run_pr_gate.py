"""Run StableNew's required local PR gate in fail-fast order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE_STEPS = (
    ("repository completeness", "tools/ci/check_repository_completeness.py"),
    ("controller surface ratchet", "tools/ci/check_controller_surface.py"),
    ("Ruff baseline", "tools/ci/run_ruff_baseline.py"),
    ("mypy smoke", "tools/ci/run_mypy_smoke.py"),
    ("isolated collection", "tools/ci/run_collection_gate.py"),
    ("required smoke", "tools/ci/run_required_smoke.py"),
)


def main() -> int:
    for label, relative_script in GATE_STEPS:
        print(f"==> {label}", flush=True)
        completed = subprocess.run(
            [sys.executable, str(ROOT / relative_script)],
            cwd=ROOT,
            check=False,
        )
        if completed.returncode:
            print(
                f"PR gate FAILED at {label} (exit {completed.returncode})",
                file=sys.stderr,
            )
            return completed.returncode
    print("PR gate OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
