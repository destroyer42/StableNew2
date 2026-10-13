# PR-IMG-PHOTO-221 — Windows Photo Optimize migration recovery

Execution Profile + Model/Reasoning Recommendation: Standard, bounded filesystem
recovery in existing migration/store/view seams. Codex GPT-6.1 Sol High; Claude Code
Sonnet 5.5 High. Local/Desktop is preferred for native Windows sharing behavior.
High effort targets total successful-work cost: distinguishing sharing, collisions,
partial copies and workspace permissions requires coherent persistence reasoning.

Controller Surface Assessment: no controller/coordinator changes. The existing photo
worker performs migration/retry; Tk polling renders results. No compiler, NJR, queue,
runner, history, runtime or GPU policy changes; no new persistence authority.

Token-Efficient Validation Plan: reproduce on the unmodified base with native Win32
handles in disposable roots, then deterministic injected faults and native handle
regressions. Validate the existing photo/controller, reprocess/NJR, workspace/routing,
scanner and GUI seams together. Run the canonical PR gate once near final verification,
reuse unchanged source evidence after documentation updates, inspect the aggregate diff
and run `git diff --check`. No physical generation or operator-data mutation.

## Baseline and proved failure

Base/local main and fetched remote main: `764564fbdad1c9d72a2676fa19d1e8b50af6c535`.
Feature branch: `codex/img-photo-221-migration-recovery`, isolated checkout
`C:/Users/rob/qual/StableNew-photo221`. The original checkout and its untracked
`data/photo_optimize/` were preserved.

Before editing, native `CreateFileW` handles without delete sharing proved:

| Temporary-root condition | Original directory rename | Original store initialization |
|---|---|---|
| Normal | Succeeds | Ready, two assets |
| Existing empty or populated destination | WinError 183 | Fails despite writable workspace |
| Held file within staging | WinError 5 | Fails despite writable workspace |
| Held staging directory | WinError 32 | Fails despite writable workspace |

The proved application defect is uncontained per-asset rename failure escaping store
construction. A held child file is a verified mechanism for WinError 5; it does not
identify the operator incident's process. Microsoft documents delete-sharing constraints
in [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).

Read-only inspection found the current destination absent, no explicit ACL deny and
owner FullControl on staging/assets. This does not exclude historical permissions or
a transient lock. UUID staging `0267c85841ac4c68b62f572b8d0dee5f` had three image hashes
matching both its marker and legacy source. Its marker identified
`photo_20261012_160436_16add3e0` (the supplied incident path spelled `1dadd3e0`). Its path
was 118 characters. These observations do not prove path length, collision, concurrency,
ACLs or the older partial staging folder caused the incident. Neither staging folder
nor any operator original, sidecar or output was written, reused, moved or deleted.

## Recovery and safety contract

- `MigrationReport` distinguishes migrated, already verified and failed/skipped assets;
  each issue carries phase, error/Windows code, rename attempt count and source,
  destination and retained staging paths. Scan failures are visible too.
- Each recognized legacy asset is independent. Failures are logged and displayed in a
  persistent tab summary; Migration Details gives actionable paths and remediation.
  New imports use the same writable store. Retry Legacy Migration uses the existing
  worker and GUI poll, never a runtime restart or job replay.
- Probe root/assets/staging_runs with owned temporary files before readiness and after
  migration. A write failure raises a clear workspace error; no fallback store opens.
- Recopy failed assets into unique fresh UUID staging. Hash copied bytes, recheck source
  bytes/sidecar, and route only current managed paths. All old staging, legacy originals,
  immutable queued inputs, baseline snapshots, historical paths and completed artifacts
  remain usable and unchanged. Old staging is never automatically reused or cleaned up.
- Publish atomically without replacement. Windows extended-path rename refuses existing
  destinations; Linux uses `renameat2(RENAME_NOREPLACE)` to retain that guarantee in CI.
  Other platforms or missing primitives fail per asset instead of an unsafe rename.
  See [Python rename](https://docs.python.org/3.14/library/os.html#os.rename) and
  [renameat2](https://man7.org/linux/man-pages/man2/rename.2.html).
- Check destination evidence before every publish attempt and after every error. A
  concurrent valid winner is already migrated; an unexpected or changed destination,
  including an empty directory, is retained and reported. A matching source identity,
  contained file-hash evidence and matching sidecar asset identity establish idempotence;
  later draft edits remain valid. Links/junctions and malformed markers are refused.
- Only Windows 5/32/33 get bounded retries: three attempts, waits 0.1s and 0.25s. WinError 5
  can also be permanent denial: exhaustion retains staging and reports failure. Disk full,
  collisions, generic permission errors and malformed data do not receive blind retries.

## Validation and limits

Before-edit reproduction: `C:/Users/rob/qual/photo221-baseline.py` and
`C:/Users/rob/qual/photo221-baseline.log`. Focused verification:
`C:/Users/rob/qual/photo221-focused.log`, Python 3.14.8, **148 passed**. This includes
real Windows WinError 5/32 handle tests and injected 5/32/33 faults, persistent denial,
empty/populated destination races, concurrent migration, interruption/retained partial
copy, later retry/repeated startup, corrupt/changed copies, writable/import and unwritable
workspace behavior, GUI warning/details/worker polling and import after failure.
Existing immutable-NJR/history and long Windows path regressions remain intact.

Focused command: `python -m pytest tests/photo_optimize
tests/controller/test_app_controller_photo_optimize.py tests/gui_v2/test_photo_optimize_tab_v2.py
tests/state/test_workspace_paths.py tests/state/test_output_routing.py
tests/learning_v2/test_output_scanner.py tests/pipeline/test_reprocess_builder_defaults.py
tests/pipeline/test_reprocess_batching.py -q` (fresh isolated basetemp under `C:/Users/rob/qual`).

Canonical `python tools/ci/run_pr_gate.py`: **PASS**, including repository completeness,
controller ratchet, Ruff, mypy smoke (10 files), isolated collection (**9,525 tests**) and
required smoke (**386 passed**). Log: `C:/Users/rob/qual/photo221-pr-gate.log`.
Final source/test blobs are unchanged from these accepted runs; documentation-only closeout
does not invalidate them. Aggregate scoped diff and `git diff --check` pass. Hosted CI is
not run: publication is not authorized. No new dependency or physical GPU/runtime operation.

Security Review passed with no blocking finding. Configured workspace ancestors remain a
trusted local boundary; hostile concurrent link replacement is residual hardening, not an
established incident cause. Windows paths were exercised natively; Linux no-replace behavior
awaits hosted Linux validation. Persistent locks/ACL failures need operator remediation;
this repair neither claims nor attempts to fix those external causes. Retained staging can
consume disk space; any cleanup/reuse policy is a separate product decision and is excluded.

Model / usage: Codex Local/Desktop handled discovery, implementation, validation, docs and
local closeout. Exact selected model, effort and host-reported token/cost deltas are not
exposed to this session; the recommendations above are not usage claims. One bounded
production repair; two test-double corrections during focused verification; one observable
context compaction. No required test or acceptance criterion was weakened.
