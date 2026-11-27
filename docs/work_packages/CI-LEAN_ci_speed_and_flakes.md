# CI-LEAN: CI speed, flakes and local/CI parity

Status: implemented on a branch; hosted timing not yet observed (2026-11-27). Package 11 of the 2026-11-27 Value Assessment (formerly Way Forward N21).

Execution class: **Standard** (test infrastructure, repository tools and the CI workflow; no product behaviour change).
Model recommendation: Claude Code, Claude Sonnet 5.5, high effort.

## Outcome

Required CI is faster and fails less for reasons that are not the change's fault, and the local PR gate reports what CI
would report before the push.

## Starting evidence

- Hosted wall time (assessment note `02_code_tests_ci.md`, 200 runs to 2026-11-27): median 17.9 min on `main`,
  16.8 min on PRs; `required` 2.2 min, census shards about 13 min each (slowest median 14.6), `windows` 3.1 min.
- Shard balance drifts: the timing manifest dates from 2026-11-05.
- Most failures are found about 13 minutes in, although many are static guards that need no 13 minutes.
- Local runs differ from CI: live Forge on `127.0.0.1:7871`, a local FFmpeg and RIFE, another display size.

## Slices

1. **Triage** every required-CI failure since 2026-11-20 as real defect, flake, environment gap or stale
   test/artefact; repair flakes and stale tests at their root (deterministic waits, no wall-clock thresholds).
2. **Host independence:** tests never reach the operator's real runtimes, and do not change verdict with the host's
   FFmpeg, RIFE, GPU tool or display.
3. **CI parity** mode in `tools/ci/run_pr_gate.py` for what hosted CI runs that the local gate skips, without making
   the default gate much slower.
4. **Wall time:** measure per job and cut where cheap (shard balance, shard count, caching). Report before and after.

## Rules

- No required check is weakened, removed or made non-blocking; no real failure is skipped or deselected.
- Every active test file still runs for every executable change.
- Branch-protection identities (`required`, `full-suite`, `windows`) keep their names.
- No application, Forge or ComfyUI start; the live checkout is read-only. Local commits only; the orchestrator
  publishes.

## Controller Surface Assessment

No controller or coordinator code is expected to change. A product defect found by triage is reported as a follow-up
unless it is a few lines.

## Token-efficient validation plan

Focused tests per change; one `python tools/ci/run_pr_gate.py` from this worktree with a short `TEMP`; one local
sharded census before and after for the host-independence claim; hosted CI (run by the orchestrator) is the verdict.

## Acceptance

- Triage table and before/after timing numbers in the PR body.
- Gate green on the committed SHA.
- Unverified until hosted CI runs: the new wall time and any behaviour that only exists on the hosted runner.

## Result (2026-11-27)

| Slice | Delivered | Evidence |
|---|---|---|
| 1 | All 65 failed CI runs since 2026-11-20 classified; AI-VL cancel race, nested-pytest `%TEMP%` scan, `apt-get` outage and sub-second timing assertions fixed; static guards, pins and goldens moved into `required` | triage table in the PR body |
| 2 | `tests/helpers/host_isolation.py` (operator runtime ports refused); screen-size cap lifted in the four GUI modules that need it | 31 of 31 failures under a live-Forge stand-in pass; those four modules pass on a 1024x768 display |
| 3 | `run_pr_gate.py --parity` and `tools/ci/affected_tests.py` | 69 of 87 PR-edited existing tests selected over 30 merges, about 170 s mean |
| 4 | Five census shards, refreshed shard weights | predicted full run about 13 min against a 19.7 min median; hosted observation pending |

Regrouping the shards exposed order and timing dependencies, repaired the same day: the suite now resets the
registered WebUI process manager and retires the shared persistence worker after each test, and one queue-projection
test waits for its background refresh. A new test file reshuffles the shards, so treat a failure that appears only
after a regrouping as leftover state first.

Contract for maintenance: `docs/Subsystems/Testing/TESTING_AND_CI.md` sections 4, 5, 10 and 11. Close this work
package after the first hosted run confirms the timing.
