# PR-QUEUE-WEBUI-172 — Dead Forge Endpoint Cascade Repair

## Execution Profile + Model/Reasoning Recommendation

Standard, bounded reliability repair on baseline `2aca72e93f46fd0a38c4bf4413050d254550f90d`.
PR-170/#92 and PR-171/#93 are integrated there. Codex: GPT-6.1 Sol XHigh; Claude Code:
Sonnet 5.5 XHigh, per the owner's package recommendation and `docs/AI_MODEL_SELECTION.md`.
Local/Desktop fits the retained incident context. Higher effort is appropriate for dispatch certainty,
partial execution and concurrent recovery: avoiding an unsafe retry matters more than nominal model cost.
One primary session; one explicitly requested independent read-only aggregate review.

Worktree: `C:/Users/rob/qual/StableNew-queue172`, branch
`codex/queue-webui-172-dead-forge-cascade`. The original clean PR #94 branch at
`a6275ae18d992ebba126d533fc18b19099e272d2` remains separate and unchanged. Future PR #94 integration
must verify ancestry again. This package authorizes a local commit only.

## Controller Surface Assessment

The existing connection controller observes process liveness, fresh health and the existing coordinator's
projection. The existing outage coordinator retains recovery decisions. No AppController/JobService growth,
new queue, process manager or runner. Connection controller: 437 -> 478 physical lines; outage coordinator:
491 -> 524, both below the existing 600-line limit. Checked-in ratchet ceilings are unchanged.
`src/main.py` loses the three-disconnect restart counter and uses its existing single-flight off-Tk helper
for read-only periodic health. Launch/Retry retains the process manager's existing launch lock.

## Token-Efficient Validation Plan

Freeze six baseline reproductions before edits. Test the transport/stage boundary first, then the canonical
JobService/SQLite/run_njr path and 25-job incident, then PR-170/171 and affected executor, identity, manager,
queue and Tk projection regressions. Use fake transports/processes and temporary SQLite/output roots.
Run the canonical PR gate once after focused checks, inspect the aggregate diff, and independently review
no replay, owned-child recovery, checkpoint safety and concurrent readiness. No physical Forge/GPU run.

## Baseline claim ledger

All baseline references below are at `2aca72e93f46fd0a38c4bf4413050d254550f90d`.
Saved reproductions: `C:/Users/rob/qual/QUEUE172-evidence/test_baseline_172.py`;
results: `baseline.log` in the same directory, **6 passed**. These are offline observations, not
an interactive GUI or physical incident reproduction.

| Class | Exact source | Observed baseline |
|---|---|---|
| A | `src/pipeline/executor.py:5442`; `src/api/webui_failure_evidence.py:93` | Real txt2img stage receives typed OUTCOME_UNKNOWN once and returns None, erasing evidence before the runner's generic no-images path. The baseline invokes the stage, not a complete run_njr. |
| B | `src/api/webui_failure_evidence.py:196`; `src/controller/webui_outage_coordinator.py:197` | Real unknown/complete_endpoint_loss exception assesses ordinary, not applicable, no suspicion/requeue; coordinator does not hold it. |
| C | `src/pipeline/executor.py:2355`; `src/api/webui_process_manager.py:288` | Owned PID retained but is_running false: executor declines recovery. Manager ownership/restart already permits an exited owned child; no manager change was needed. |
| D | `src/controller/webui_connection_controller.py:115`, `:416` | Cached get_state remains READY after a separately failed fresh strict probe. This is a controller projection reproduction, not an interactive GUI observation. |
| E | `src/api/webui_failure_evidence.py:140`; `src/queue/single_node_runner.py:58` | Earlier production phase=exit is missed; later typed unavailability assesses safe_to_requeue and coordinator permits it. |
| F | `src/controller/webui_outage_coordinator.py:182`, `:197` | Real queue/runner and temporary SQLite: 25 identity-refused jobs become FAILED, zero held, zero restarts. |

## Implemented contract

- Typed txt2img/img2img/ADetailer/upscale failures are raised through the existing failure result contract.
  Extra-single-image upscale opts into the existing client's strict-error pattern; its default callers
  retain intentional None behavior. A 10054-style lost POST response retains OUTCOME_UNKNOWN, unknown
  certainty, transport type, endpoint and attempt count. It is terminal/action-required, never replayed.
  An explicit request-may-have-executed flag remains authoritative even with another error code.
- Identity refusal uses actual exception fields and `identity_gap()`. Missing/settling unknown evidence
  suspects outage; a fresh health/identity probe decides containment. A positive wrong identity or an
  inconsistent unknown with readable options never authorizes restart, adoption or fallback. Configuration
  and model/payload failures remain ordinary. Attestation stays strict.
- Unknown generation recovery is deferred to the existing queue coordinator. It uses owns_process rather
  than liveness, retains one incident budget and counts prior executor/stall recovery. A successful restart
  alone cannot release held jobs: fresh readiness and matching identity are mandatory. A failed/refused
  recovery leaves held WebUI work queued. Manager launch serialization is unchanged.
- Completed variants, output paths, stage outputs, current phase/event exits and persisted checkpoints
  prevent whole-job requeue. Normalization preserves partial-work proof. Immutable NJRs, lineage, queue
  order, statuses and historical FAILED records are unchanged.
- Cached READY cannot mask a confirmed owned-child exit or active hold. Periodic health is read-only and
  off Tk. READY publication and epoch advancement are atomic, so stale health completion cannot replace
  newer readiness. Existing diagnostics project endpoint (test endpoint 7871), ownership/PID/liveness,
  initial code/certainty/gap, incident, held/independent counts, attempts and result without prompt content.

## Acceptance evidence

`tests/queue/test_dead_forge_cascade_172.py` exercises the real canonical JobService submission, temporary
SQLite, single-node worker, run_njr, Forge adapter, executor and HTTP client with fake transport. Readiness
and asset preflight seams are controlled there; separate existing identity/attestation tests remain authoritative.

| Synthetic sequence | Result |
|---|---|
| 10054 reset through canonical path | One POST, normalized typed failure persisted, action required; no replay. |
| Single-image upscale reset / HTTP 500 | One POST each; unknown / dispatched certainty preserved. |
| 25 WebUI jobs, unknown first outcome, failed owned recovery | One FAILED, 24 QUEUED/held in original order; one restart. Manual Run Next cannot claim held work. |
| Same 25-job sequence, successful owned recovery and fresh proof | First remains FAILED; later 24 complete; first is never dispatched again. |
| 25 pre-dispatch identity-refused jobs | First safely restored once in its original place, all 25 QUEUED/held; one restart, second claim blocked. |
| Mixed native SVD/Comfy jobs during failed recovery | Both independent jobs complete sequentially; held WebUI work remains intact. |
| Earlier work / persisted checkpoint / historical exit | No automatic requeue. |
| External/unowned runtime; positive wrong identity | No process-control calls or backend substitution. |
| Stale periodic health completion versus real manager READY event | New READY epoch wins; dead child/active outage overrides cached READY. |

Existing PR-170/171 tests cover launch/restart serialization, bounded budget, proof-gated release, ordinary
failures, pause/shutdown/auto-run, queue ordering and history preservation. The affected suite also covers
existing cancellation behavior. The ownership preference test now verifies both initial standard and guarded
preferences are unchanged, instead of assuming the host preference was never guarded. No production launch
profile or configuration changed. The old executor regression that expected a second dispatched POST after
HTTP 500 now requires one POST and no restart.

Focused transport/upscale/ownership/refinement verification: **52 passed**. Broader affected pipeline/API/
queue/controller/application/projection verification: **662 passed**. Logs and baseline reproductions are
under `C:/Users/rob/qual/QUEUE172-evidence`. The canonical gate ran once: completeness, controller ratchet,
Ruff, ten-file mypy smoke and isolated collection (**8,705 tests**, repository unchanged) passed. Required
smoke was interrupted by the sandbox denying the fake harness's loopback socket (WinError 10013 after
186 passes). Only that step was rerun with local socket access: **386 passed**, repository unchanged.
Final independent aggregate review: **PASS** after repairing its two narrow findings (atomic READY epoch
publication and action-required metadata for an alternate error code with an ambiguity flag). Diff check passed.

## Limits

The user's live SQLite/history, remaining 15 jobs, generated outputs, logs and application state were never
used as test fixtures or mutated. No real Forge launch, generation, runtime/configuration change, push or
merge. These deterministic results demonstrate software containment, not the underlying cause of Forge's
exit or physical runtime recovery. That investigation remains outside this package.
