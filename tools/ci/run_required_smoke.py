"""Run the required deterministic smoke test gate used by CI."""

from __future__ import annotations

import subprocess
import sys


REQUIRED_SMOKE_ARGS = [
    "tests/",
    "--ignore=tests/gui/",
    "--ignore=tests/gui_v2/",
    "--ignore=tests/journey/",
    "--ignore=tests/journeys/",
    "--ignore=tests/integration/",
    "-x",
    "-q",
    "--disable-warnings",
]


def build_command() -> list[str]:
    return [sys.executable, "-m", "pytest", *REQUIRED_SMOKE_ARGS]


def main() -> int:
    return subprocess.run(build_command(), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
