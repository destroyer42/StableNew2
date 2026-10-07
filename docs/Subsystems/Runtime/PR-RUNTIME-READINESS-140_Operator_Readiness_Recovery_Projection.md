# PR-RUNTIME-READINESS-140: bounded Operator Readiness recovery projection

Date: 2026-10-07 (America/New_York)

Disposition: **LOCALLY VERIFIED / READY FOR PUBLICATION REVIEW / UNPUBLISHED**.
Deterministic contracts, two clean physical observations and the final local gate
pass. Required hosted CI/integration are pending; publication is not authorized.

## Execution Profile + Model/Reasoning Recommendation

Standard: a bounded read-projection repair within the existing repository and
readiness service. Recommend Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High,
per `docs/AI_MODEL_SELECTION.md`. Codex Local/Desktop fits the required real
SQLite/GUI acceptance. These tiers address cross-file semantic and runtime
validation with less expected rediscovery/retry cost than a cheaper nominal
model. One primary session; no delegation or architecture redesign.

## Controller Surface Assessment

The synchronous GUI consumers are first-run/open readiness and WebUI authority
binding. Only the service's scalar recovery query changes. No controller,
coordinator, panel, main-window, watchdog, bootstrap or process-manager source is
edited. Rendering, open/refresh behavior and current readiness authorities retain
their existing ownership. The four controller ratchets pass unchanged; no ceiling
increase is requested.

## Problem and resulting data path

The retained startup investigation identified two Tk heartbeat gaps of 23.274 s
and 21.136 s during readiness recovery. Repeated samples and a watchdog bundle
showed full repository job/NJR hydration merely to count recovery metadata. Its
single measured layout fit/idle call did not overlap either gap. That original
layout incident remains HOLD and is outside this repair.

The new authoritative API is:

```python
JobRepository.count_jobs_with_last_control_action(action: str) -> int
```

Its entire SQL data projection is:

```sql
SELECT execution_metadata FROM jobs
```

The repository lock protects the query/fetch. Outside the lock, the existing
`_json_loads` decoder reads only those metadata payloads; only dictionary payloads
with an exact top-level `last_control_action == action` contribute to the count.
Empty, missing, null, malformed and non-object metadata do not produce positive
matches. Nested values, similar strings and unrelated actions are excluded.
All statuses participate, as they did in the former recovery projection.

`OperatorReadinessService._recovery_record()` requests
`"restart_interrupted_action_required"` through this API. Zero retains OPTIONAL
and the existing no-interrupted-records text. Nonzero retains ACTION_REQUIRED,
the exact singular/plural count text, `INTERRUPTED_RESTART_ACTION_REQUIRED` and
intentional Replay guidance. A repository-query exception retains UNKNOWN/error
projection; there is no hydration fallback and no assumed zero on query failure.

The path never selects `njr_snapshot`, reconstructs a `Job` or NJR, or reads
result/artifact/history payloads. It adds no schema/index, cache, persisted
recovery state or lifecycle authority. It performs no writes. Work remains on
the canonical JobService/SQLite/NJR/runner path. This is a metadata scan, not a
constant-time query; its cost scales with metadata size. Physical timing decides
whether that narrow scan is sufficient at workstation scale.

## Token-Efficient Validation Plan and deterministic results

Use focused repository/readiness/panel tests first, then existing interrupted
restart/replay, auto-run persistence and affected startup/watchdog contracts.
Prove scale by query shape, access denial and fail-on-hydration seams rather than
wall-clock unit assertions. Perform bounded repair acceptance against the paused
real repository; reuse the retained causal evidence rather than repeat that
investigation. Freeze source/tests, confirm shutdown/quiescence, run the canonical
local PR gate once, inspect the aggregate diff and check whitespace.

Initial focused selections:

- Repository + readiness service + existing panel contracts: **51 passed**, 1.79 s.
- Auto-run persistence, history/pipeline replay, threaded bootstrap, off-Tk
  connection and watchdog ordering/first-trigger/context: **25 passed**, 10.34 s.
- Focused Ruff and controller ratchets passed.

Repository tests cover empty/zero/one/multiple matches, exact actions and malformed
metadata, unchanged rows/status counts and no writes. Hydration seams
`_row_to_job` and `normalized_job_from_snapshot` fail if invoked. A SQLite
authorizer rejects reads of every jobs column except `execution_metadata`.
The scale fixture contains **10,926 rows / 34 queued**, with poisoned NJR,
result and artifact payloads. It asserts one exact metadata SELECT, the exact
recovery count, no hydration and unchanged SQLite `total_changes`.

Service tests forbid `list_job_models`, verify zero/nonzero text/state and require
UNKNOWN on query failure without fallback. Existing panel tests remain green.

## Physical acceptance and pending user-work protection

Read-only preflight confirms **10,926 persisted jobs**, including **34 queued**,
zero running, queue paused true and auto-run preference true. The former path's
metadata decoder, applied to a metadata-only read, yields **one** interrupted
restart record. This establishes the semantic baseline without hydrating NJRs.

All queued columns and IDs are fingerprinted before/through/after each run.
Every persisted job row is fingerprinted before/after, covering lifecycle,
immutable snapshots, ordering and execution evidence. Repository settings are
compared too. The application uses its normal supported
`.venv/Scripts/python.exe -m src.main` entrypoint and existing bounded auto-exit.
The queue remains paused and no job is submitted, replayed, reordered or executed.

Temporary measurement lives only in ignored diagnostics. Process-scoped
`sitecustomize` import hooks wrap the new projection, readiness collection and
rendering, existing heartbeat updates and actual watchdog triggers. Hooks preserve
results and exceptions, add no timers/probes/idle drains, and do not update or
mask heartbeat state. A separate bounded writer saves observations for 90 s.
Only the existing GUI renderer reads its resulting badge/detail text on Tk;
the writer makes no Tk call. No `startup_trace.py` or instrumentation-branch
commit is brought into production source.

The preliminary run showed two recovery queries at 330.556 / 330.656 ms, count
one, zero hydration calls, matching ACTION_REQUIRED text, maximum heartbeat gap
984.443 ms and no observed watchdog trigger. The application exited normally,
with all jobs/settings unchanged. Its observer environment reached a managed
child, whose diagnostic writer encountered the existing trace file. That harness
error was corrected by restricting hook/writer installation to the exact
`-m src.main` process. The run is retained as preliminary; two clean observations
supplied final acceptance.

| Observation | Recovery projection | Count/state/rendering | Maximum heartbeat gap | UI-stall watchdog | Queue after |
|---|---|---|---|---|---|
| Clean 1 (attempt 2) | 252.801 / 194.245 ms | 1 / ACTION_REQUIRED / exact existing badge and detail | 946.093 ms | none | 34 queued, zero running, paused |
| Clean 2 (attempt 3) | 281.115 / 307.929 ms | 1 / ACTION_REQUIRED / exact existing badge and detail | 676.901 ms | none | 34 queued, zero running, paused |

Each clean run recorded two projection calls, two collections and two rendered
recovery rows. Full readiness collection took 258.668 / 200.047 ms in clean 1
and 297.935 / 313.562 ms in clean 2. All four projection calls reported zero
`_row_to_job` calls. Both rendered `[Action required]`,
`1 interrupted job requires operator review.`, the unchanged blocking identifier
and Replay guidance. This verifies the resulting Tk text, not visual appearance.

Clean 1 observed 267 heartbeat updates from `11:46:24.789993Z` to
`11:47:54.849437Z`; clean 2 observed 267 from `11:48:47.030644Z` to
`11:50:17.039052Z`. Those endpoints bound the observer windows, not the first and
last heartbeat themselves. Maximum gaps describe between-update observations;
pre-first-heartbeat construction/import time is outside that metric. Both
90-second windows have an observer-stop record and zero dropped events. Actual
watchdog-trigger hooks and complete runtime logs contain no UI-stall event.
No different readiness failure class appeared. The four-call latency sample is
workstation evidence, not a general timing guarantee.

Both normal auto-exits completed with exit 0 in about 100.74 s including startup
and shutdown. Every observed descendant was gone before the next run or final
validation. Existing hypernetwork 404 retries and Learning warning noise remain
visible and unrepaired; they are retained debt, not a new repair objective.

There were 96 pending-work checks per run: 192 in the two clean observations,
plus 96 in the retained preliminary run. Full-job-row hashes, queued-row hashes
and repository settings match the baseline after every run. Counts before and
after are cancelled 2,534, completed 8,221, failed 137, queued 34, running zero.
The queue remains paused, auto-run preference remains true, schema version stays
1 and the same 34 NJRs/identities/order/execution metadata remain unchanged.
No readiness collection or diagnostic hook writes lifecycle state.

## Evidence checkpoint and closeout

- Worktree: `C:\Users\rob\projects\StableNew-main`.
- New branch: `runtime/operator-readiness-recovery-140`.
- Fresh authoritative base: `61bf38681f9174b26c79495e556ad23618776d73`.
- Retained evidence branch: `runtime/physical-startup-stall-130`, checkpoint
  `0424172dbe9b327d1fdf2911c21ad422590cf382`. Its report was read with `git show`:
  `docs/Subsystems/Runtime/PR-RUNTIME-STARTUP-130_Physical_Startup_Investigation.md`.
  The repair branch is based directly on main; nothing was merged/cherry-picked.
- Operational evidence: `reports/diagnostics/readiness140_20261007/` (baseline,
  observations, runtime logs, `acceptance_analysis.json` and capture invariants).
  Attempts 2 and 3 are the accepted observations. Artifacts are preserved.
- Clean 1 trace / runtime-log SHA-256:
  `cc08261a0462c9ae46b3e79396d8961b97b3dd4b4d769ffee0b562aff86b7d0f` /
  `842d9af3f3062c44df2f63067d46d6d1ad51f0d8126ec3e986ae8c40f6235c25`.
- Clean 2 trace / runtime-log SHA-256:
  `dacacf6d7f6688085de522b2ce07b915e7dccdfcd78404e3ee6cf7eeafba3e5f` /
  `77ef61961cb5fe83b96cefefad39beab6fced4d707a577c71ec9d337270dbb2e`.
- Queued-row SHA-256:
  `6a4c6c342f1b356cf09561480554a79c3793fa9f7d54914a567f8e6d5ba118ea`.
- All-job-row SHA-256:
  `39592e0f072439eb3a423d85255b1558ead7d29f1fdb6a98b5d4fe31fef439eb`.

Physical acceptance is PASS for this repair: no recovery NJR/job hydration,
unchanged interrupted-restart semantics/rendered result, no readiness recovery
watchdog stall and no pending-work/lifecycle mutation. The original investigation
HOLD is not converted into a layout-fix verdict.

After all three runs exited, quiescence verification found no StableNew/managed
runtime process and no size/mtime change across 34,429 `logs/` and `output/`
files over two seconds. No artifact cleanup, reset or deletion was performed.
Tested source hashes are retained in `quiescence_source.json`; source/tests were
unchanged through physical acceptance and final validation. The already-green
focused selections (76 tests in total) were reused rather than repeated.

The canonical local PR gate ran **once**, using repository CPython 3.14.8, and
passed with exit 0: completeness (502 tracked Python source files), all four
controller ratchets, Ruff, mypy smoke (10 files), isolated collection (**5,675
tests**, 3.11 s) and required smoke (**371 passed**, 40.67 s). Both isolation
checks report repository unchanged. The complete log is `pr_gate.log` in the
evidence directory. Final aggregate and staged whitespace checks passed.
Subsequent edits are documentation only and do not invalidate source/runtime
evidence. Required hosted Python 3.14 CI remains unrun; pushing/opening a PR
needs separate authorization. Recommendation: ready for owner-authorized branch
publication and required CI, with no local repair blocker.

Changed-file inventory:

- `src/queue/job_repository.py`: metadata-only scalar API.
- `src/services/operator_readiness_service.py`: use that API, retain semantics/errors.
- `tests/queue/test_job_repository_sqlite.py`: exact/no-hydration/read-only/scale contracts.
- `tests/services/test_operator_readiness_service.py`: narrow-call/semantic/error contracts.
- This package report: acceptance and evidence.
- `docs/CODEX_MAP.md`: the narrow repository projection seam and tests.
- `STATUS.md`: locally verified/unpublished truth, without claiming integration.

Retained debt: Python entrypoint version guard, optional Forge hypernetwork 404
fail-fast, Learning fallback-log cleanup, duplicate diagnostics ZIP names and
original Pipeline layout attribution. Watchdog thresholds, retries, generation
dispatch, replay and process ownership remain unchanged. Do not broaden this
package to async readiness or repair another component if a new stall appears.
