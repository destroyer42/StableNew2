# SQLite job repository migration

Status: Active  
Applies to: StableNew v2.6 / PR-MVP-040

StableNew now reads and writes live job lifecycle state only through
`state/jobs.sqlite3`. Old queue JSON and history JSON/JSONL files are offline
migration inputs; the application never falls back to them.

## Before migration

1. Shut down StableNew and confirm no StableNew process is using the repository.
2. Keep the legacy files in place. The importer never edits or deletes them.
3. From the repository root, run a dry run with every applicable source:

```text
python tools/migrate_job_repository.py --database state/jobs.sqlite3 --queue state/queue_state_v2.json --history runs/job_history.json
```

The command is a dry run unless `--apply` is present. Review source SHA-256
checksums, discovered and valid counts, identities, duplicates, conflicts,
invalid records, and expected runnable/terminal totals. Any conflict or invalid
record blocks the whole write; resolve it explicitly rather than choosing one
record silently.

## Apply and validate

Run the same command with `--apply`:

```text
python tools/migrate_job_repository.py --database state/jobs.sqlite3 --queue state/queue_state_v2.json --history runs/job_history.json --apply
```

Before opening the repository for import, the tool copies every discovered
source and any pre-existing database into a timestamped directory under
`state/migration_backups/`. Its `manifest.json` records original paths,
checksums, and whether the database existed. The job batch is one SQLite
transaction. Validation compares counts, identities, statuses, and runnable
versus terminal classification before success is reported.

Re-running the same migration is safe: already imported identities are
reported as duplicates and are not inserted again. A changed record or an
identity that disagrees with canonical repository work is a conflict.

## Rollback rehearsal and recovery

Tests rehearse rejection against malformed/conflicting sources and prove that
the original sources and prior repository remain unchanged. For manual
recovery, keep StableNew stopped and inspect the selected backup's
`manifest.json`:

- if `database_existed` is `true`, move the current `jobs.sqlite3` aside and
  copy the backed-up database to the manifest's database path;
- if `database_existed` is `false`, move the newly created database aside;
- retain the failed database and all legacy sources until the restored
  repository has been opened and its queue/history projections checked.

Never combine restored JSON with SQLite as live state. Re-run a dry run after
recovery before attempting another import.
