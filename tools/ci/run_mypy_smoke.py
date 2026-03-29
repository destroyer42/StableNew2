"""Run the bounded mypy smoke gate used by CI for typed architecture seams."""

from __future__ import annotations

import subprocess
import sys


MYPY_SMOKE_TARGETS = [
    "src/app/__init__.py",
    "src/app/bootstrap.py",
    "src/app/optional_dependency_probes.py",
    "src/controller/ports/runtime_ports.py",
    "src/controller/ports/default_runtime_ports.py",
    "src/pipeline/intent_artifact_contract.py",
    "src/pipeline/config_contract_v26.py",
    "src/pipeline/replay_engine.py",
    "src/video/workflow_contracts.py",
    "src/video/workflow_registry.py",
]


def build_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "mypy",
        "--follow-imports=silent",
        *MYPY_SMOKE_TARGETS,
    ]


def main() -> int:
    return subprocess.run(build_command(), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
