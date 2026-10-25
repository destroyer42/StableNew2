"""Run StableNew's required local PR gate in fail-fast order.

    python tools/ci/run_pr_gate.py                  # the hosted ``required`` job
    python tools/ci/run_pr_gate.py --full           # also the hosted ``full-suite`` census, run locally
    python tools/ci/run_pr_gate.py --full --workers 3

``--full`` appends ``tools/ci/run_sharded_census.py``: the same path-hash shard partition and completeness verdict as
the hosted census, one isolated checkout per worker (a Windows/Tk suite shares ports, files and process-global state,
so workers must not share a tree; this is why it is not pytest-xdist). It is slow by nature; use it before opening a
PR that changes executable code, and let hosted CI remain the authority.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE_STEPS = (
    (
        "repository completeness",
        (sys.executable, str(ROOT / "tools/ci/check_repository_completeness.py")),
    ),
    (
        "controller surface ratchet",
        (sys.executable, str(ROOT / "tools/ci/check_controller_surface.py")),
    ),
    ("Ruff", ("ruff", "check", ".")),
    ("mypy smoke", (sys.executable, str(ROOT / "tools/ci/run_mypy_smoke.py"))),
    ("mypy ratchet", (sys.executable, str(ROOT / "tools/ci/run_mypy_ratchet.py"))),
    ("ruff ratchets", (sys.executable, str(ROOT / "tools/ci/run_ruff_ratchets.py"))),
    (
        "architecture ratchets",
        (sys.executable, str(ROOT / "tools/ci/run_architecture_ratchets.py")),
    ),
    (
        "controller Tk import boundary",
        (sys.executable, str(ROOT / "tools/ci/check_controller_tk_boundary.py")),
    ),
    ("isolated collection", (sys.executable, str(ROOT / "tools/ci/run_collection_gate.py"))),
    ("required smoke", (sys.executable, str(ROOT / "tools/ci/run_required_smoke.py"))),
)

DEFAULT_CENSUS_WORKERS = 2
FULL_CENSUS_LABEL = "full census (hosted full-suite equivalent)"
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
        "Install the pinned tools with `pip install -r requirements-dev.txt` (or use the supported CI "
        "environment) before running the full PR gate.",
        file=sys.stderr,
    )
    return False


def census_step(workers: int) -> tuple[str, tuple[str, ...]]:
    """The local equivalent of the hosted ``full-suite`` job: every active test file, sharded across ``workers``."""

    command = (
        sys.executable,
        str(ROOT / "tools/ci/run_sharded_census.py"),
        "--workers",
        str(workers),
    )
    return FULL_CENSUS_LABEL, command


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="after the required gate, run the sharded census locally",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"census worker processes with --full (default {DEFAULT_CENSUS_WORKERS})",
    )
    args = parser.parse_args(list(argv))
    if args.workers is not None and not args.full:
        parser.error("--workers only applies with --full")
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be >= 1")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or ())
    steps = GATE_STEPS
    if args.full:
        steps = (*GATE_STEPS, census_step(args.workers or DEFAULT_CENSUS_WORKERS))
    if not preflight_tools():
        return TOOLING_BLOCKER_EXIT_CODE
    for label, command in steps:
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
    print("PR gate OK" + (" (including the full census)" if args.full else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
