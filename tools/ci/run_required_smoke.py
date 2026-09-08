"""Run the required positive-list deterministic smoke gate used by CI."""

from __future__ import annotations

from run_collection_gate import repository_test_target, run_pytest_gate

REQUIRED_SMOKE_TARGETS = (
    "tests/system/test_repository_completeness_v2.py",
    "tests/system/test_architecture_enforcement_v2.py",
    "tests/system/test_ci_truth_sync_v2.py",
    "tests/system/test_controller_surface_ratchet.py",
    "tests/system/test_pr_gate.py",
    "tests/safety/test_runtime_state_hygiene.py",
    "tests/state/test_workspace_paths.py",
    "tests/state/test_output_routing.py",
    "tests/queue/test_job_repository_sqlite.py",
    "tests/migrations/test_sqlite_job_importer.py",
    "tests/controller/test_core_run_path_v2.py",
    "tests/queue/test_job_service_pipeline_integration_v2.py::TestQueuedModeExecution",
    "tests/queue/test_job_service_pipeline_integration_v2.py::TestQueueErrorHandling",
)


def build_command() -> list[str]:
    """Return the pytest arguments after resolving repo-relative node IDs."""

    return [
        "-x",
        "-q",
        *(repository_test_target(target) for target in REQUIRED_SMOKE_TARGETS),
    ]


def main() -> int:
    return run_pytest_gate(build_command())


if __name__ == "__main__":
    raise SystemExit(main())
