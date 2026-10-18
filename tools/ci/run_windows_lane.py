"""Run the Windows platform-contract lane (audit P1-3).

StableNew is a Windows desktop application, but the census runs on Linux. This lane runs, on a Windows runner, the tests
whose behavior depends on the operating system: process containment and ownership, atomic file replacement and sharing
violations, Windows paths and path escaping in JSON, SQLite persistence, the Photo Optimize Windows migration recovery,
and a Tk construction smoke. It is a platform contract, not a substitute for GPU/Forge/SVD hardware qualification, which
stays opt-in and local.

Targets are explicit (a positive list, like the required smoke) so a new test never joins the lane by accident; the
policy test checks every entry still exists. Reuses the isolated, pollution-detecting pytest runner of the other gates.

    python tools/ci/run_windows_lane.py
"""

from __future__ import annotations

from run_collection_gate import repository_test_target, run_pytest_gate

WINDOWS_LANE_TARGETS = (
    # process ownership and containment (anonymous job objects; stopping one manager never reaches another's processes)
    "tests/utils/test_job_object_isolation.py",
    "tests/utils/test_process_container_v2.py",
    # fail-closed child containment: suspended start, job-object attach, tree kill, owner death (needs a real job object)
    "tests/utils/test_process_containment_failsafe.py",
    "tests/utils/test_managed_process.py",
    "tests/api",
    "tests/safety",
    "tests/services/test_runtime_transition_service.py",
    # crash-safe state writes, sharing violations on os.replace, Windows paths, JSON-escaped backslashes
    "tests/utils/test_atomic_io.py",
    "tests/state",
    "tests/assets",
    "tests/photo_optimize",
    "tests/tools/test_diagnose_asset_registry_cache_145.py",
    # SQLite persistence and legacy migration on NTFS
    "tests/queue/test_job_repository_sqlite.py",
    "tests/migrations",
    # production construction path (startup gate, NJR strictness) and application bootstrap
    "tests/controller/test_production_wiring_startup_gate.py",
    "tests/app",
    # Tk construction smoke on a real Windows desktop session
    "tests/gui_v2/test_p0_6_silent_failure_regressions.py",
)


def build_command() -> list[str]:
    return [
        "-q",
        "-rfE",
        "--tb=short",
        "--timeout=300",
        *(repository_test_target(t) for t in WINDOWS_LANE_TARGETS),
    ]


def main() -> int:
    return run_pytest_gate(build_command())


if __name__ == "__main__":
    raise SystemExit(main())
