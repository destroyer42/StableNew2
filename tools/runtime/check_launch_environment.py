"""Pre-launch check of the interpreter that is about to run StableNew (PR-DEVEX-LAUNCH-180).

``scripts/launch_stablenew.ps1`` runs this with the repository ``.venv`` Python before starting the
application. It is read-only, stdlib-only and cheap (no ML import, no pip): it applies the supported
interpreter policy (standard-GIL CPython 3.14, experimental JIT off) and then delegates the exact package
comparison to ``verify_runtime_pins``, the only package-version authority. It never installs, repairs or
recreates anything; a failure prints what to do and exits non-zero so the launcher does not start the app.
"""

from __future__ import annotations

import argparse
import sys
import sysconfig
from collections.abc import Sequence
from pathlib import Path

SUPPORTED_PYTHON_MINOR = (3, 14)
EXIT_UNSUPPORTED_INTERPRETER = 3


def interpreter_problems(
    version: Sequence[int], *, free_threaded: bool, jit_enabled: bool
) -> list[str]:
    """Why this interpreter is not the supported StableNew runtime (empty when it is)."""

    major, minor = int(version[0]), int(version[1])
    found = ".".join(str(int(part)) for part in version[:3])
    if (major, minor) != SUPPORTED_PYTHON_MINOR:
        wanted = ".".join(str(part) for part in SUPPORTED_PYTHON_MINOR)
        return [f"Python {wanted} is required; this environment is Python {found}."]
    problems = []
    if free_threaded:
        problems.append(
            f"Python {found} is the free-threaded build, which StableNew does not support; "
            "use the standard (GIL) build of Python 3.14."
        )
    if jit_enabled:
        problems.append(
            f"Python {found} has the experimental JIT enabled (PYTHON_JIT), which StableNew does not "
            "support; unset PYTHON_JIT and relaunch."
        )
    return problems


def current_interpreter_problems() -> list[str]:
    jit = getattr(sys, "_jit", None)
    return interpreter_problems(
        sys.version_info[:3],
        free_threaded=bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        jit_enabled=bool(jit is not None and jit.is_enabled()),
    )


def _verify_pins():
    # Load the sibling module by path so the check works both as `python tools/runtime/<this>.py`
    # (script directory on sys.path) and as an imported module, without importing the `src` package.
    import importlib.util

    path = Path(__file__).resolve().with_name("verify_runtime_pins.py")
    spec = importlib.util.spec_from_file_location("_stablenew_verify_runtime_pins", path)
    if spec is None or spec.loader is None:  # pragma: no cover - the file is part of this directory
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constraints", type=Path, default=None)
    parser.add_argument("--with-postprocess", action="store_true")
    args = parser.parse_args(argv)

    problems = current_interpreter_problems()
    if problems:
        print("UNSUPPORTED INTERPRETER for StableNew:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "Build a supported environment with scripts/bootstrap_windows.ps1 (use -Recreate only on a "
            "dedicated venv path); StableNew will not launch with another interpreter.",
            file=sys.stderr,
        )
        return EXIT_UNSUPPORTED_INTERPRETER

    verifier = _verify_pins()
    forwarded = ["--constraints", str(args.constraints or verifier.DEFAULT_CONSTRAINTS)]
    if args.with_postprocess:
        forwarded.append("--with-postprocess")
    return int(verifier.main(forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
