# LEARN-QUAL-BATCH-810

## Execution Profile + Model/Reasoning Recommendation

Standard, high-risk lifecycle/persistence. Base local and remote main:
`4016da7ec37e9c4e4144de5875e23eba9900fc50`. Dedicated worktree
`C:/Users/rob/qual/StableNew-learn810`, branch `codex/learn-qual-batch-810`.
The original clean `codex/gui-seam-730` checkout and its commits are preserved.

Model recommendation: Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh.
Known architecture with difficult callback, persistence and ambiguous-admission
interactions warrants careful reasoning to reduce retries and total work cost.
Expected approximately 20M cache-read / 100k output; no host preference.
Primary Codex session `01a1858c-d3d0-7781-93f5-434c9289fd88`;
measurement starts `2026-10-29T02:46:01Z` (session-start boundary before discovery).
Independent reviewer: `01a1859a-2672-7901-b307-296ab3f765ed`.

## Controller Surface Assessment

Retain LearningExecutionController as the sole Learning JobService callback owner.
Extend its experiment-scoped associations rather than changing the visible Tk
experiment during execution. The batch service coordinates existing isolated
Learning freeze/compiler instances, durable Experiment Library sessions and
per-experiment JobService admission. No new queue, compiler, runner, scanner,
rating store or lifecycle authority. Large GUI controller ceilings do not increase.

## Token-Efficient Validation Plan

Use Python 3.14, temporary Library and real SQLite/JobService with inert runtime.
Cover whole-selection preflight refusal, exact counts, one/three experiments,
idempotency, partial/ambiguous admission, admission-time completion, visible-state
switches, restart, outcome/readback truth, and untouched publication stores.
Exercise Tk selection, keyboard, geometry, busy/cancel and stale delivery.
Run focused tests while editing, independent integrity/security review once
substantially complete, then canonical run_pr_gate.py once near closeout. Inspect
aggregate diff and diff --check. Hosted required/full-suite/windows require later
publication authorization. No GPU generation, runtime restart, push, PR or merge.

## Acceptance and validation

- Complete batch path: eligible selection, shared prompt, create-only drafts,
  full-selection freeze/compiler preflight, explicit generation confirmation,
  per-experiment canonical admission, durable callbacks/restart and Library review.
- Existing execution owner retains per-experiment associations. Ordinary Run also
  fences stale batch drafts; Library writes preserve exact associations and newer
  terminal projections. Background checkpoints preserve newer review/authoring fields.
  No SQLite schema, lifecycle/queue/runner ownership, rating or publication change.
- Python 3.14.9: **1,242 passed in 39.56 s**, covering the full Learning suite,
  prior 800 integration/Tk and new 810 integration/Tk. New batch integration:
  **26 passed**; independent repetition **26 passed in 10.00 s**.
- Independent security/integrity review initially found stale foreground duplicate
  admission and background restore/presentation/checkpoint ownership defects. One
  batched repair and bounded reverification: **PASS**, both original reproductions
  repaired, no additional blocking findings. Legacy explicit synthetic tracking
  seams remain covered by the Learning suite.
- Canonical gate: repository completeness (781 modules), four controller ceilings,
  Ruff, mypy smoke/ratchet, exception/format and architecture ratchets, Tk import
  boundary and clean isolated collection (**14,516 tests**) passed. Required smoke
  initially hit sandbox localhost denial (`WinError 10013`); rerunning only that
  step outside the sandbox passed (**358 passed, one warning, 40.87 s**). Accepted
  unchanged static/collection evidence was reused instead of rerunning the wrapper.
- A sandboxed combined regression attempt hit Windows native Tk teardown exception
  `0xc0000008`; the serialized run outside the sandbox passed all 1,242 tests with
  unchanged assertions/source. No product fix or platform skip was inferred.
- Aggregate scoped diff and `git diff HEAD --check` inspected. Local evidence:
  `C:/Users/rob/qual/learn810-validation/learning-serial.log`,
  `pr-gate-final.log` and `required-smoke-unsandboxed.log`.
- Canonical Learning section 3.15, its callback documentation, STATUS and code maps
  updated to match the implemented workflow. No physical GPU/runtime acceptance or
  full local census is claimed. Hosted `required`, `full-suite`, `windows` have not
  run for this unpublished branch; publication and integration remain unauthorized.
- At closeout the shared tracking ref `origin/main` advanced to
  `7ccb9a8b8f2c06c69e990715c6303c1000ef0f97` (PR #230, GUI-SEAM-730).
  This package and its validation remain on the verified `4016da7e` base.
  No rebase, merge or synchronization was inferred; current-main compatibility
  and hosted CI must be revalidated before any later authorized integration.

## Model / usage

Primary and independent reviewer: Local/Desktop Codex, actual GPT-6.1 Sol High;
one batched review repair/reverification, local validation PASS. Usage is measured
at closeout by `tools/usage_report.py` with both session IDs and the start above.
Reviewer telemetry uses `token_usage_record` records unsupported by this version
of the reporter, so its tokens are unavailable through the prescribed tool;
the final measured line explicitly reports that limitation without an estimate.
