# N11: failures explain themselves, logs are trustworthy

## Objective

- Outcome: after a walk-away batch, the owner can read why each failed job failed (in the job's error and History),
  and `logs/stablenew.log.jsonl` is a log he can trust: every record is timestamped, parseable, bounded in size, free
  of prompt text and secrets, and never written by the test suite.
- In scope (Way Forward item N11, 2026-11-25 assessment):
  1. Every JSONL record carries `ts`, `level` and `logger`. Exceptions stay inside the JSON line (`exc_text`) instead of
     breaking it into raw traceback lines (599 of 19,671 lines in the live log on 2026-11-26 were unparseable
     traceback text).
  2. Windows rotation. Rotation that cannot rename the live file no longer fails silently or destroys backups.
  3. Prompt text moves from INFO to DEBUG. Diagnostics bundles redact prompts and secrets. Gateway sync logging is
     checked for the same (RG-100 finding E1). Tests assert both.
  4. The generic "No images were generated successfully" fallback is replaced by the stage's actual reason, which
     reaches `PipelineRunResult.error`, the job's `error_message` and History.
  5. When the managed Forge (WebUI) process dies on its own, its exit cause is recorded.
  6. Tests can no longer write the checkout's `logs/`.
- Explicit exclusions:
  - No change to log consumers outside the repository, to the GUI log panel, or to the per-launch WebUI/Comfy logs
    (already isolated per test).
  - Historical records keep their text. The 483 jobs that already say "No images were generated successfully" are
    not rewritten.
  - No new log authority or log viewer. No change to the queue, runner or history authorities.

## Execution class and model recommendation

- Execution class: Bounded implementation (diagnostics, no architecture authority change).
- Execution location: Local, in worktree `n11-diagnostics-293c74`.
- Model recommendation: Claude Code Opus 5.5 (effort as the session runs).

## Exact start state and authorities

- Task start: 2026-11-26, session `n11-diagnostics-293c74`, started by `local_ecb8e9b1-c2ce-4303-95cf-308e8cc92d9e`.
- Repository and branch: `destroyer42/StableNew2`, `claude/n11-diagnostics-293c74`.
- Start SHA: `29fc22c5`.
- Authorities: `AGENTS.md`, `docs/work_packages/RG-100_phone_review_gateway.md` (existing-code findings),
  PRs #435 and #438 (checkout write guard).

## Evidence gathered before the change (read only)

- Live log `StableNew-main/logs/stablenew.log.jsonl` (read, never written): 19,671 lines; **no record has a timestamp
  or level**; 599 lines are raw traceback text. Files present: `.jsonl` (4.8 MB), `.jsonl.1` (148 MB), `.jsonl.5`
  (10 MB). `.2`-`.4` are missing.
- Rotation mechanism: `RotatingFileHandler.doRollover` shifts `.4 -> .5 ... .1 -> .2` before renaming the live file. On
  Windows the final rename fails while any other handle has the file open, and the override swallowed the error. It
  then retried on every record: each failed attempt shifted every backup by one and deleted the oldest, while the live
  file grew without bound (148 MB). That is why `.2`-`.4` are gone.
- Second handle in one process: `AppController.__init__` attaches a new `JsonlFileHandler` on every construction and
  never removes it. Two handlers on one file make each other's rename fail.
- Prompt text at INFO: `src/pipeline/executor.py` logs `ORIGINAL/OPTIMIZED POSITIVE/NEGATIVE`, "Applied global ...
  Enhanced: '<prompt>'" and "final negative prompt='<prompt>'" at INFO (385 jobs' worth in the current file).
- Diagnostics bundle (`src/utils/diagnostics_bundle_v2.py`) copies the JSONL files verbatim and writes GUI log
  entries, job snapshots and image metadata (which hold prompts) with only home/repo path anonymization.
- Gateway sync (`src/app/review_gateway_*.py`, `services/review_gateway/`): log calls carry codes, counts and type
  names only. No prompt or secret is logged today; a test now holds that.
- Job repository copy (scratch, read only): 483 jobs failed with exactly "No images were generated successfully"
  (Oct 1 - Nov 21). Their stage events say only `exit` with 0 images. The stage that produced nothing returned `None`
  after logging its reason, and the runner had no way to read it.
- Forge exit: the orphan monitor saw a natural exit only at DEBUG and without the exit code. `_finalize_process` logged
  an ERROR crash tail with a raw exit code, including after StableNew's own deliberate stop (terminate gives code 1).
- Tests and `logs/`: the write guard covers `output/`-like folders only. Every test that builds an `AppController`
  attaches a handler on the relative `logs/stablenew.log.jsonl`, that is the checkout's live log when run there.

## Design

1. `JsonlFileHandler.emit` adds `ts` (ISO 8601, local time with offset, milliseconds), `level` and `logger` to every
   payload, and `exc_text` when the record carries an exception. A payload's own keys are kept. Each record is
   exactly one line. Readers in the repository (only the diagnostics bundle) are unaffected: existing keys keep their
   names and meaning.
2. Rotation:
   - Rename the live file first, to a temporary name. Shift backups only after that succeeds, so a failure destroys
     nothing.
   - If the rename is refused (another handle is open), copy the live file to `.1` and truncate it through this
     handler's own handle.
   - If both fail, retry no sooner than 60 s later, and write one `log_rotation_failed` record into the log, with the
     error and size, plus a line to stderr. The failure is never silent.
   - `attach_jsonl_log_handler` returns the existing handler for the same file instead of adding a second one.
3. Prompt text and redaction:
   - The executor's prompt-bearing log calls move to DEBUG. The JSONL file stays at INFO, so prompts never reach it.
     A source scan test fails on any INFO-or-higher log call whose arguments carry prompt text.
   - New `src/utils/diagnostic_redaction.py` redacts prompt-like and secret-like keys, and prompt-bearing message
     text, from any JSON-like value.
   - The diagnostics bundle applies it to the GUI log entries, metadata, job snapshot, result summary, replay
     descriptor, queue state, image metadata, WebUI tail and every JSONL line it copies. Historical prompt lines in
     old logs are redacted on the way out.
4. No-output reason:
   - The executor records the first concrete reason a stage produced nothing (an exception, an empty backend response
     with its detail, a save failure, a missing input image).
   - `take_no_output_reason()` returns it, with a verified checkpoint mismatch first.
   - `PipelineRunner._no_output_reason` reads it. The generic text remains only when no stage recorded a reason, and
     it then names the stage.
5. Forge exit cause:
   - New `src/api/process_exit_cause.py` turns an exit code and output tail into one bounded sentence: Windows NTSTATUS
     names such as access violation and stack overflow, signals, and the last Python exception or CUDA out-of-memory
     line in stderr.
   - The orphan monitor reports an unexpected exit at ERROR within its 2 s poll, as a structured `webui_process_exited`
     record. The manager keeps it in `get_status()["last_exit_cause"]` and `exit_diagnostics()["exit_cause"]`.
   - A deliberate stop is logged as a stop, not a crash.
   - When a job fails after the managed process died during that job, the job's error ends with the exit cause.
6. Tests and `logs/`:
   - `logs` joins the write guard's guarded folders.
   - An autouse fixture points the JSONL config at a per-test directory and removes any JSONL handler a test left on
     the root logger.

## Acceptance

- `tests/utils/test_logger_v2.py` and new `tests/utils/test_jsonl_log_n11.py`: fields, single-line exceptions,
  rotation with a second open handle (Windows), backups preserved, failure reported, no duplicate handler.
- `tests/utils/test_diagnostic_redaction.py`: bundle contains no prompt or secret; gateway sync and apply logs carry
  none; source scan finds no INFO+ prompt log call.
- `tests/pipeline/test_no_output_reason_n11.py`: a stage's empty response, exception and save failure each reach
  `PipelineRunResult.error`; an end-to-end JobService run carries the reason to the history entry.
- `tests/api/test_process_exit_cause.py`: exit-code decoding, unexpected exit vs deliberate stop, status fields.
- Write guard: `logs` guarded; full PR gate, `tests/system` and `tests/tools` pass with no checkout write.

## Not done

- Records written before this change keep no timestamp. The 483 historical failure texts are unchanged.
- The live rotation fix is demonstrated by deterministic tests holding a second Windows handle, not yet observed in
  the owner's running app.

## Completion report

See the PR body (`AGENTS.md` section 8).
