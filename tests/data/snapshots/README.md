# Snapshot fixtures for Phase 10 regression tests

Each JSON file in this directory captures a single `build_job_snapshot` output
(`schema_version 1.0`) as produced by `src/utils/snapshot_builder_v2.py`.
These snapshots feed the regression suite in `tests/regression/test_snapshot_regression_v2.py`.

## How to add a new snapshot

1. Instantiate a `NormalizedJobRecord` that matches the desired pipeline job.
2. Create a lightweight `Job` instance (with `status=JobStatus.COMPLETED`) and call
   `build_job_snapshot(job, normalized_job, run_config=...)`.
3. Save the resulting dictionary to `tests/data/snapshots/job_snapshot_<name>.json`
   with `json.dumps(..., indent=2)` so the file is easy to review.
4. Add a targeted test in `tests/regression/test_snapshot_regression_v2.py` that
   loads the new snapshot via `snapshot_loader` and asserts the invariants you care about.

Use `pytest -m snapshot_regression` to run just the snapshot-based regression suite.
