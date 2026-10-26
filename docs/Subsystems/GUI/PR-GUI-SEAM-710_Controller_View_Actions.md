# GUI-SEAM-710 — Controller-to-view actions

## Execution Profile + Model/Reasoning Recommendation

Standard, lifecycle-sensitive UI-thread extraction; one top-level Local Desktop session.
Model recommendation: Codex GPT-6.1 Sol XHigh / Claude Code Sonnet 5.5 XHigh. Cross-file callback order and teardown
justify this tier to minimize total successful-work cost and retries. Stay in the current host.
Expected usage: about 10M cache-read and 60k output tokens (planning estimate, not measured usage).

Task start: `2026-10-25T20:41:02.955-04:00` (session metadata, before discovery).
Host/session: `codex:01a175a7-549a-7f50-92bc-5a4fe9dfba9d`.
Parent: `7ceb683f6cf1ae1ae9e222f8db9ede0072780e08`; local `main`, `origin/main` and connected GitHub `main` agreed.
Feature: `codex/gui-seam-710`, worktree `C:/Users/rob/qual/StableNew-gui710`.
Original checkout: `C:/Users/rob/projects/StableNew-main`; its unrelated untracked GUI modernization report is preserved.
PR #214 is merged at `46a2f5d7`; its implementation, GUI-SEAM-700 assessment, ownership map, current authorities,
code map, model guidance, work-package template and testing guidance were inspected. GitHub reported no open PRs at start;
the merged Learning prompt-slot work is included in the parent. No old test verdict is reused as current source evidence.

## Outcome and Controller Surface Assessment

`PresentationActions` carries typed intents and payloads for Debug Hub, Job Explanation, structured errors and the four
Video Workflow/Movie Clips image/bundle handoffs. A headless implementation can be injected into `AppController`.
`MainWindowV2` supplies `TkPresentationActions`, using its existing invoker, dialogs and handoff functions. Selected
header/legacy-list bindings now live in the Tk layer; V2 pack-loader bindings and subsequent toolbar replacement order stay
intact. Debug Hub remains a singleton, Job Explanation keeps its multiple-window behavior and the window tracks errors.

The adapter snapshots queued handoff payloads and fences delivery after detach, replacement, shutdown or destruction.
Missing destinations and unsupported setters retain their errors. UI-thread requests execute inline; worker requests
queue through the existing dispatcher and return the accepted source payload. Controller messages and history fallback,
source ordering, destination selection, lineage and return values are retained.

Controller assessment: extraction only; `AppController` shrinks 6,860 -> 6,816 physical lines, and its checked-in ceiling
is lowered accordingly. Controller-to-GUI imports fall 17 -> 10 overall (AppController 12 -> 5). Remaining AppController
imports are AppStateV2, AppStateProjectionSink, ReviewWorkflowAdapter, LearningState and lazy DropdownLoader. No selected
GUI imports move to another controller namespace. The controller Tk import-closure gate remains required.

No material architecture change: the existing Tk host, composition path and invoker ownership remain; owner decision 11
is unresolved. No execution authority, bus, persisted representation, queue, NJR, JobService, backend or GPU change.
The GUI Ownership Map describes the port; the code map and decreased baselines reflect the source.

## Token-Efficient Validation Plan

1. Headless command/attachment tests and Tk adapter tests cover callback identity, repeated attachment, missing views,
   dialog focus/reopen, delayed worker delivery, stale callbacks, payload snapshots, status, destination and lineage.
2. Exercise existing diagnostics, video handoff, Preview/queue/history, shutdown and Windows Tk construction tests.
3. Run `python tools/ci/run_pr_gate.py` once near completion using the existing project Python 3.14 environment.
4. Inspect one aggregate diff and `git diff --check`; one batched repair/reverification pass per confirmed failure class.
   Hosted `required`, `full-suite` and `windows` remain the integration verdict after separately authorized publication.

## Evidence and limitations

The default system interpreter lacks development tools; validation uses
the existing `StableNew-main/.venv` (CPython 3.14.8), without installing dependencies. Sandboxed pytest could not create
its default temporary directory; subsequent tests use a writable temporary root outside the checkout. Two sandboxed
Tk runs exited with Windows exception `0xc0000008` inside Tk update/teardown; desktop-enabled verification is required.

Final local evidence:

- Initial focused controller/adapter/diagnostics/video-handoff/dispatcher selection: 62 passed.
- Desktop-enabled navigation-shell, silent-failure and Windows workspace-construction selection: 60 passed.
- Broad controller, queue, presentation and shutdown selection: 1,404 passed, one opt-in leak test skipped, two failures.
  The new Tk test generated an event before mapping completed; its fixture now pumps the mapped window before generating
  the event. The unchanged external-Comfy cold-start test observed `recovering` instead of `operator_action_required`.
  No queue/runtime implementation was changed. That run also emitted an unchanged queued-to-completed lifecycle warning
  and the clean-shutdown test's intentional worker-crash warning.
- One batched test repair/reverification: 49 passed, covering the final presentation tests, Make Video/Recent Outputs,
  final-source nine-tab construction and the isolated cold-start test. The borrowed Make Video test harness now supplies
  the port and its new application helper. The cold-start failure did not reproduce in this selection; its timing risk
  remains outside this package. No assertion, skip policy or acceptance criterion was weakened.
- `run_pr_gate.py` first stopped at completeness because new sources were not staged. After staging, it passed completeness,
  controller surface, ruff, mypy smoke, mypy ratchet, ruff ratchets, architecture ratchets and the controller Tk boundary.
  Collection then failed its repository-unchanged check while concurrent regression tests were writing logs. After those
  processes exited, only collection and the remaining smoke step were run: 13,691 tests collected and 358 smoke tests
  passed (one warning), both with the repository unchanged. All gate steps are green; the original aggregate invocation
  itself exited nonzero. Already-green static steps were reused because source was unchanged.
- Final aggregate diff inspected; `git diff --check` passed. Hosted `required`, `full-suite` and `windows` are not run for
  this unpublished branch. Local evidence supports review; the next functional seam awaits integration acceptance.

Files changed: application controller; new controller presentation port; Tk main window; new Tk action adapter;
existing diagnostics and SVD controller tests; new controller and Tk presentation tests; Make Video test helper;
GUI Ownership Map; this work-package record; generated code map; current-state import count; architecture, controller
surface and ruff baselines. No execution/persistence/backend implementation files changed.

Actual executor: Codex GPT-6.1 Sol High (host-reported effort; XHigh remains the recommendation), one batched
repair/reverification pass. Measured session usage is reported in the completion message, not estimated here.

Publication, opening a PR and merge are not authorized. No remote mutation or physical generation is performed.
