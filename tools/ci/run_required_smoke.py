"""Run the required positive-list gate used by CI: the smoke list plus the cross-boundary contract suite."""

from __future__ import annotations

from run_collection_gate import repository_test_target, run_pytest_gate

REQUIRED_SMOKE_TARGETS = (
    "tests/system/test_repository_completeness_v2.py",
    "tests/system/test_architecture_enforcement_v2.py",
    "tests/system/test_ci_truth_sync_v2.py",
    "tests/system/test_controller_surface_ratchet.py",
    "tests/system/test_pr_gate.py",
    "tests/system/test_runtime_constraints.py",
    "tests/video/test_svd_restoration_readiness.py",
    "tests/safety/test_runtime_state_hygiene.py",
    "tests/state/test_workspace_paths.py",
    "tests/state/test_output_routing.py",
    "tests/queue/test_job_repository_sqlite.py",
    "tests/migrations/test_sqlite_job_importer.py",
    "tests/controller/test_core_run_path_v2.py",
    "tests/tools/test_operator_journey_harness.py",
    "tests/queue/test_job_service_pipeline_integration_v2.py::TestQueuedModeExecution",
    "tests/queue/test_job_service_pipeline_integration_v2.py::TestQueueErrorHandling",
)


# Always-required cross-boundary contract suite (PR-DEVEX-CI-110): invariants BETWEEN subsystems, kept small and fast.
# Feature behavior belongs to the affected lanes (tools/ci/validation_plan.py), not here. Each group names the invariant.
CONTRACT_GATE_TARGETS = (
    # immutable job identity survives construction boundaries; foreign backend/profile combinations fail closed
    "tests/system/test_construction_identity_contract.py",
    "tests/image_backends/test_image_backend_contract.py",
    "tests/integration/test_pr_img_forge_100_canonical_path.py::test_identity_mismatch_fails_the_job_before_any_generation_post",
    "tests/integration/test_pr_img_forge_100_canonical_path.py::test_a1111_njr_on_a1111_endpoint_is_unchanged_by_the_forge_guard",
    # canonical production path (NJR -> JobService -> SQLite -> run_njr) and queue-first submission: the smoke list above
    # (core_run_path, TestQueuedModeExecution) plus test_fake_backend_traverses_job_service_sqlite_and_canonical_result in the
    # image-backend contract file listed first in this group.
    # replay: new identity, parent lineage
    "tests/controller/test_pipeline_replay_job_v2.py",
    "tests/pipeline/test_replay_vs_fresh_v2.py",
    # runtime ownership: only owned runtimes are mutated; external runtimes are never adopted or stopped
    "tests/services/test_runtime_transition_service.py",
    "tests/api/test_webui_process_manager_identity.py",
    "tests/safety/test_forge_backend_isolation_safety.py",
    # an ambiguous generation POST is never automatically replayed
    "tests/api/test_webui_retry_policy_v2.py::test_txt2img_read_timeout_does_not_replay_generation_post",
    "tests/api/test_webui_retry_policy_v2.py::test_img2img_read_timeout_does_not_replay_generation_post",
    "tests/api/test_webui_retry_policy_v2.py::test_generic_connection_error_does_not_replay_generation_post",
    "tests/api/test_webui_retry_policy_v2.py::test_adetailer_remains_single_attempt_on_ambiguous_timeout",
    "tests/integration/test_pr_img_forge_100_canonical_path.py::test_ambiguous_dispatched_forge_generation_post_is_never_replayed",
    "tests/pipeline/test_executor_generate_errors.py::test_ambiguous_external_generation_fails_without_recovery_or_replay",
    # the validation policy that routes every other test
    "tests/tools/test_ci_validation_plan.py",
    "tests/tools/test_ci_census_summary.py",
    "tests/tools/test_ci_previous_evidence.py",
)


def build_command() -> list[str]:
    """Return the pytest arguments after resolving repo-relative node IDs."""

    return [
        "-x",
        "-q",
        *(repository_test_target(target) for target in (*REQUIRED_SMOKE_TARGETS, *CONTRACT_GATE_TARGETS)),
    ]


def main() -> int:
    return run_pytest_gate(build_command())


if __name__ == "__main__":
    raise SystemExit(main())
