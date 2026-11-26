# TEST-HERMETIC-750: selected runtime isolation and watchdog parity

## Execution Profile + Model/Reasoning Recommendation

Standard, Local/Desktop, one editing session. Model recommendation: Claude Code
Sonnet 5.5 High; Codex GPT-6.1 Sol High. Existing architecture and injection seams
are understood; interacting cancellation, threads and persistence justify High
for total successful-work cost. Expected usage: about 12M cache-read / 70k output.

Start: 2026-10-26T20:17:31.0210082-04:00, ROB-GAMING-DESK, Codex session/thread
`01a17ab8-07a6-73d2-8842-940716ed6348`. Parent:
`d8d69ab29c6ffbba16544344f096c83d6640759f` (fetched main, merged WF-740 #225).
Branch: `test/hermetic-750-runtime-isolation`; worktree:
`C:/Users/rob/qual/StableNew-hermetic750`. Original main checkout and its untracked
GUI assessment remain untouched. Roadmap #224 is still a draft, not merged authority.
Local implementation/commit only; publication and merging are not authorized.

## Controller Surface Assessment

No controller/coordinator production code is selected for modification. The only
production repair is `src/utils/watchdog_v2.py`; tests use existing registry,
coordinator, identity-attestor, configuration, per-instance Event and clock seams.
No controller line ceiling or import boundary changes are intended. No bootstrap,
SQLite owner, runtime owner, queue, cancellation authority or dispatch redesign.

## Evidence register (unchanged production parent)

| Source / trigger | Observation / intended behavior | Cause, classification and smallest remedy | Reproducer / assertion |
|---|---|---|---|
| Canonical txt2img cancellation harness `_build_pipeline_runner`, default registry -> `RuntimeTransitionCoordinator` | Fake client still probes configured Comfy `:8000` and WebUI `:7871`. Free endpoints permit work; simulated occupied/unresponsive endpoints refuse before POST. Production correctly refuses conflicting external runtimes; tests intend to exercise generation/cancellation with no real residency. | Confirmed test-harness defect: executor/client injection left transition and identity dependencies ambient. Inject real backend/transition with safe providers; retain real readiness/identity refusal logic. Apply same fix to sibling queue img2img harness. | New endpoint-tripwire test: all three states fail on unchanged source/harness; assert no ambient probes and exactly one fake POST. |
| `JobWatchdog.run`, pytest/test-mode flags present | `inspect()` unit tests pass, but `run()` returns without enforcing configured thresholds. Same configuration without flags delivers TIMEOUT after strictly exceeding the limit. | Confirmed production/test parity defect. Replace implicit environment bypass with existing `WatchdogConfig.enabled`; use explicit disabled service defaults in ordinary tests and enabled configs in enforcement tests. Per-instance virtual clock/wait preserves threshold and stop semantics. | New paired environment test: production mode passes; pytest mode fails with zero waits/callbacks. |
| `tests/pipeline/test_pipeline_runner.py` module fixture | Explicit free-endpoint probes already installed. | Previously repaired; do not repeat historical 35-test repair. | Current source inspection. |
| Repository construction / output routing / diagnostics accommodations | Pytest branches still exist. Repository identity changes may cross composition-root decision boundary. | Unselected candidates; no defect claim from search hits and no implementation in this two-class slice. | Deferred targeted equivalence investigation. |
| Existing GC, autostart, process-container, profile/prompt/log guards and fingerprint | Already provide targeted isolation, not a universal network/write guard. | Intentional harness configuration; preserve. | Existing contract tests and unchanged source. |

Initial red run: 4 failed / 4 passed in 8.53s (three endpoint tripwires and the
pytest watchdog configuration fail). Synthetic endpoint states only. Logs retained
outside the worktree at `C:/Users/rob/qual/hermetic750-red.log`.

## Token-Efficient Validation Plan

1. Red paired-mode and ambient-probe reproductions; record original assertions.
2. Focused cancellation, watchdog, backend identity, ambiguous POST, runtime hold,
   ownership and fingerprint tests, including deliberate outcome mutations.
3. One canonical CPython 3.14 pinned-tool gate near source freeze; sequential
   isolated census with one worker if feasible; preserve all active tests and lanes.
4. Aggregate source/test review, ratchets, final diff check, main comparison and
   session-filtered usage measurement. Hosted integration verdict unavailable
   before separately authorized publication.

## Selected-path acceptance and review

| Case | Evidence and limit |
|---|---|
| T01 | New three-state endpoint tripwire passes; selected txt2img/img2img cancellation tests prohibit HTTP, endpoint probes and global-manager lookup. No claim for all normal tests. |
| T02 | New injected Forge identity and conflicting residency both refuse before the fake POST; existing runtime-identity tests cover positive/unknown/mismatched evidence. Real endpoint availability is never the oracle. |
| T03 | Existing retry-policy and definite-HTTP tests retain one-POST/no-replay negative assertions. No dispatch implementation changed. |
| T04 | Existing outage-containment and runtime-handoff tests use isolated queues and retain QUEUED/hold behavior. No operator queue accessed by selected repaired paths. |
| T05 | Existing manager identity/safety tests pass; the two real Windows containment checks pass outside the sandbox (2 passed in 1.02s). The sandbox misclassified their own loopback listener as free; no source repair or assertion change was made for that restriction. |
| T06 | New watchdog integration and touched cancellation tests use temporary SQLite; existing explicit output-route tests pass. Default-construction/output-route pytest parity remains unselected, not claimed fixed. |
| T07 | New paired-mode run-loop tests enforce strictly-greater runtime thresholds; fake memory/idle limits, explicit disable, stop/join and real JobService cancellation/readback covered with per-instance virtual time/wait. |
| T08 | Representative tests pass in fresh pytest processes and alongside watchdog/cancellation/neighboring contracts; owned watchdog joins before return, queue workers quiesce before repository close. No suite-wide leak-freedom claim. |
| T09 | New watchdog waits assert exact inspection counts and success/timeout/stop outcomes; existing retry/startup/cleanup assertions remain. No global time monkeypatch added. |
| T10 | Existing fingerprint negative tests still fail on synthetic unauthorized writes; focused isolated runner preserves repository bytes; prompt/profile/log/GC guards unchanged. No newly proven ignored-write escape required a guard expansion. |
| T11 | Selected paths forbid ambient HTTP/runtime-manager access; existing host autostart/GPU/preflight guards retained. Full-suite machine independence remains unproven. |
| T12 | All active tests/lanes/assertions remain; mypy baselines lowered by 3 errors. Canonical Python 3.14 gate PASS: 14,386 collected, 358 smoke passed (one warning), repository unchanged; all controller, architecture, lint/type ratchets pass. Full census/Windows execution blocked locally by missing pinned pytest-timeout 2.4.0. Hosted verdict unavailable without publication. |

Focused results: 25 selected tests passed in 4.87s. Broader contracts: 294 passed
and two sandbox-only loopback failures in 24.54s; the exact two pass natively
with unchanged source and repository fingerprint. No repeated green suite run.

The same original eight reproduction cases pass after repair in 2.12s (before:
4 failed / 4 passed in 8.53s). This is diagnostic timing, not a performance claim:
the initial import was colder, and the occupied/unresponsive cases originally
refused rather than executing the intended fake-client stage.

Mutation challenge: replacing `JobWatchdog.run` with a no-op in a separate test
process makes both paired-mode enforcement tests fail (2 failed in 1.13s).
No repository source was mutated for the challenge. Existing cancellation,
readiness-before-POST, artifact suppression, exact POST/interrupt counts and
negative identity/refusal assertions are retained or strengthened.

Aggregate review: no new runtime, persistence or cancellation owner; no production
controller edits, no controller-ceiling increase, no unconditional readiness fake,
no broad network ban affecting owned fake-server tests. The opt-in tripwire records
swallowed attempts as failures. Explicit disabled service configuration is restored
by monkeypatch; enabled enforcement tests cannot inherit pytest bypasses.

Remaining nonblocking candidates: default repository/output-route/diagnostic
pytest accommodations and fake-executor paths outside the selected cancellation
harnesses. A follow-on would reproduce each selected default-vs-pytest discrepancy
with identical safe dependencies before removing a branch. No follow-on is started.

## Closeout

Outcome: **PARTIAL**. The two selected failure classes are repaired and locally
verified; a green complete merge gate is not established. The missing pinned
timeout plugin blocks the prescribed full census and Windows-lane execution;
no dependency was installed, timeout removed, lane skipped or test weakened.
The next step is restoring that pinned tool, then complete census/Windows evidence
and separately authorized publication/hosted required checks.

Production defaults remain enabled. Runtime ownership, cancellation authority,
queue/replay, SQLite ownership, output routing and backend dispatch code are
unchanged. Documentation changes explain the explicit configuration and injection
patterns; STATUS, roadmap and generated code-map content need no update because
no product priority, authority, module inventory or hold changed.

Repair budget: zero post-review source repair passes. The two sandbox failures
were reverified with unchanged source; the missing timeout plugin is a tooling
blocker, not a source repair. Final aggregate review found no current in-scope
blocking source finding. Remaining default-construction parity investigations are
unselected candidates, not proven defects or automatically authorized work.
