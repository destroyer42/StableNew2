"""Run StableNew's required local PR gate in fail-fast order."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE_STEPS = (
    ("repository completeness", (sys.executable, str(ROOT / "tools/ci/check_repository_completeness.py"))),
    ("controller surface ratchet", (sys.executable, str(ROOT / "tools/ci/check_controller_surface.py"))),
    ("Ruff", ("ruff", "check", ".")),
    ("mypy smoke", (sys.executable, str(ROOT / "tools/ci/run_mypy_smoke.py"))),
    ("isolated collection", (sys.executable, str(ROOT / "tools/ci/run_collection_gate.py"))),
    ("required smoke", (sys.executable, str(ROOT / "tools/ci/run_required_smoke.py"))),
)

TOOLING_BLOCKER_EXIT_CODE = 2
REQUIRED_TOOL_MODULES = ("mypy", "pytest")


def missing_required_tools() -> list[str]:
    """Return obvious local tool prerequisites missing before the gate starts."""

    missing = [
        module for module in REQUIRED_TOOL_MODULES if importlib.util.find_spec(module) is None
    ]
    if shutil.which("ruff") is None:
        missing.append("ruff")
    return missing


def preflight_tools() -> bool:
    missing = missing_required_tools()
    if not missing:
        return True
    print(
        "TOOLING BLOCKER: missing local gate tool(s): " + ", ".join(sorted(missing)),
        file=sys.stderr,
    )
    print(
        "Install the pinned tools or use the supported CI environment before "
        "running the full PR gate.",
        file=sys.stderr,
    )
    return False


def main() -> int:
    if not preflight_tools():
        return TOOLING_BLOCKER_EXIT_CODE
    for label, command in GATE_STEPS:
        print(f"==> {label}", flush=True)
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
            )
        except OSError as exc:
            print(
                f"TOOLING BLOCKER while starting {label}: {exc}",
                file=sys.stderr,
            )
            return TOOLING_BLOCKER_EXIT_CODE
        if completed.returncode:
            print(
                f"SOURCE/TEST FAILURE at {label} (exit {completed.returncode})",
                file=sys.stderr,
            )
            return completed.returncode
    print("PR gate OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
