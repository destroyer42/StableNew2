# PR-MIG-203: One-Time History/Queue Migration Tool

## Status

Completed on 2026-03-18.

## Purpose

Provide an explicit, operator-run migration tool for legacy persisted queue and
history data so the runtime can stop carrying broad live compatibility for old
serialized shapes.

This PR also fixes the baseline async history-store race discovered during
`PR-NJR-202`, because migration and persistence verification were not reliable
while history writes were only eventually visible.

## What Changed

### History-store baseline fix

- [src/queue/job_history_store.py](/c:/Users/rob/projects/StableNew/src/queue/job_history_store.py)
  now keeps an in-memory overlay of pending async history entries so
  `record_job_submission()`, `record_status_change()`, `list_jobs()`, and
  `get_job()` remain self-consistent before the persistence worker flushes to
  disk.

### One-time migration library

- [src/migrations/queue_history_migrator_v26.py](/c:/Users/rob/projects/StableNew/src/migrations/queue_history_migrator_v26.py)
  adds explicit queue/history migration functions with:
  - dry-run mode
  - schema/version detection
  - backup creation
  - structured per-file report output
  - strict rewrite into the canonical v2.6 queue/history formats
- [src/migrations/__init__.py](/c:/Users/rob/projects/StableNew/src/migrations/__init__.py)
  exports the supported migration entrypoints.

### Operator entrypoint

- [scripts/migrate_queue_history_v26.py](/c:/Users/rob/projects/StableNew/scripts/migrate_queue_history_v26.py)
  provides a CLI for operators to migrate persisted queue/history files and
  emit a JSON report.

## Migration Behavior

### Queue migration

Legacy queue payloads are converted into strict queue snapshot entries with:

- `queue_id`
- `njr_snapshot["normalized_job"]`
- `priority`
- `status`
- `created_at`
- `queue_schema = "2.6"`
- bounded `metadata` noting migration provenance

Terminal legacy queue entries (`completed`, `failed`, `cancelled`) are skipped,
because the persisted queue file should only retain resumable work.

### History migration

Legacy history entries are rewritten into strict
[HistoryRecord](/c:/Users/rob/projects/StableNew/src/history/history_record.py)
entries with:

- `history_schema = "2.6"`
- `njr_snapshot["normalized_job"]`
- canonical `metadata`, `runtime`, and `ui_summary`
- migrated output metadata preserved under safe canonical fields

## Tests Updated

- [tests/queue/test_job_history_store.py](/c:/Users/rob/projects/StableNew/tests/queue/test_job_history_store.py)
- [tests/compat/test_history_migration.py](/c:/Users/rob/projects/StableNew/tests/compat/test_history_migration.py)
- [tests/compat/test_queue_history_migrator_v26.py](/c:/Users/rob/projects/StableNew/tests/compat/test_queue_history_migrator_v26.py)

## Verification

Passed:

- `pytest tests/queue/test_job_history_store.py tests/compat/test_history_migration.py tests/compat/test_queue_history_migrator_v26.py tests/pipeline/test_job_queue_persistence_v2.py -q`
- `pytest --collect-only -q`
- `python -m compileall src/queue/job_history_store.py src/migrations scripts/migrate_queue_history_v26.py`

## Operator Guidance

Dry-run example:

```powershell
python scripts/migrate_queue_history_v26.py `
  --queue-path state/queue_state_v2.json `
  --history-path state/job_history.jsonl `
  --dry-run
```

Real migration example:

```powershell
python scripts/migrate_queue_history_v26.py `
  --queue-path state/queue_state_v2.json `
  --history-path state/job_history.jsonl `
  --backup-dir state/migration_backups `
  --report-path state/migration_report.json
```

Rollback rule:

1. stop StableNew
2. restore the original files from the backup paths reported by the migrator
3. restart StableNew only after confirming the restored files are the intended version

## Boundary and Follow-On

This PR adds the explicit migration tool, but it does not yet remove the live
legacy runtime seams. That remains the next migration cut:

- `PR-MIG-204-Delete-Live-Legacy-Execution-Seams`
