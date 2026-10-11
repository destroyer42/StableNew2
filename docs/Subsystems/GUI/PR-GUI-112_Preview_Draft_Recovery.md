# PR-GUI-112 - Preview draft recovery

## Execution Profile + Model/Reasoning Recommendation

Narrow known-root-cause GUI/preview repair in the existing projection path.
Codex: GPT-6.1 Sol Medium. Claude Code: Sonnet 5.5 Medium. Preferred host:
Local/Desktop for real Tk reproduction. These tiers fit the bounded state and
projection changes; avoiding integration retries matters more than choosing
the cheapest nominal model. No new execution or persistence authority is needed.

## Demonstrated root cause and repair

Six Z-Image entries at 576x1024 render as draft-only summaries (`draft-*`),
with zero compiled NJRs. The compiler correctly rejects this geometry against
the immutable 1024x1024 v1 profile. Both buttons previously used the same queue
eligibility predicate, leaving Clear Draft disabled as well. The deterministic
real-Tk baseline failed at that Clear Draft assertion before implementation.

Clear Draft now depends only on transient draft/preview content. Add to Queue
requires current compiled NJRs plus a draft, and the action handler rechecks
eligibility. Completion refreshes button states even if summary rendering is
unchanged. Failed builds expose the existing compiler diagnostic and an action
to correct settings/rebuild or clear; draft counts never authorize submission.

Draft changes and preview requests invalidate the transient canonical preview.
Requests copy their pack intent and carry a preview generation through the
existing projection contracts. The AppState sink checks that generation at
final UI delivery, covering both pending workers and already-dispatched results.
Clear empties draft parts/packs, preview jobs and diagnostics. A new refresh
from the PipelineTab draft subscriber cannot reconstruct cleared jobs from the
retained current prompt: draft-preview state fallback is limited to explicit
manual draft parts, with no substitution for empty or unsuccessful pack work.

The normal path remains Intent -> Compiler -> NJR -> JobService -> SQLite
Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History.
Clearing modifies transient AppState only; saved packs and queued/running/history
records retain their existing authorities. Compiler and Z-Image capabilities
are unchanged. In particular, 576x1024 remains unsupported; this repair makes
that refusal recoverable and visible.

## Controller Surface Assessment

AppController still delegates background preview work to the existing runtime
projection coordinator. PipelineController captures pack intent and clears
transient state without rebuilding it. Coordination remains flat; no queue,
lifecycle, runner or process ownership logic is added. Physical controller
ceilings decrease from 7,683 to 7,678 lines for AppController and from 1,775 to
1,774 for PipelineController; the checked-in ratchet is lowered accordingly.

## Token-Efficient Validation Plan

Reproduce the six-summary/zero-NJR defect using a neutral temporary native pack,
the production PromptPack compiler and real withdrawn Tk widgets. Cover supported
1024x1024 and rejected 576x1024 Z-Image work, stage refusal, SDXL/Klein/other-model
recovery, newly added packs, managed PipelineTab refresh after Clear, manual
intent, copied request configuration and delayed completion at both UI dispatch
points. Admit six separate compiled jobs through the normal controllers and real
JobService/temporary SQLite with auto-run disabled; verify once-only admission
and unchanged persisted records after clearing a later invalid preview.

Run affected preview/Tk, AppState, controller/projection and submission tests,
then one final repository PR gate (including Ruff and applicable mypy smoke).
Use independent targeted read-only review. No physical generation, backend
startup, saved-pack inspection, publication or merge is part of this package.

## Local validation evidence

- Verified checkout/branch/base before mutation: main and live remote main were
  `9f00e240c00e80b65c0ba8d7a3c9f122cc9d646f`; the repair uses the separate
  `C:/Users/rob/qual/StableNew-gui112` worktree on `codex/gui-112-preview-recovery`.
- Affected suites: 84 passed, no skips, including 16 new regression cases with
  real Tk widgets, neutral temporary packs and temporary SQLite. The pre-repair
  six-summary test failed at Clear Draft being disabled, as expected.
- Exactly one final `python tools/ci/run_pr_gate.py` invocation passed repository
  completeness, controller ratchet, Ruff, mypy smoke (10 source files), isolated
  collection (8,367 tests) and required smoke (386 passed). The gate ran outside
  the filesystem/network sandbox to permit its deterministic localhost server.
  Source remained unchanged after these suites; later edits only recorded results.
- Independent targeted read-only review found the retained-prompt refresh gap;
  the bounded coordinator fix and subscriber regression resolved it. Follow-up
  review passed with no remaining actionable blockers. The reviewer inspected
  source/tests; execution evidence comes from the primary session.
- Aggregate scoped diff and `git diff --check` passed. Validation logs are under
  `C:/Users/rob/qual/GUI112-validation/` (`affected3.log`, `pr_gate.log`).
  Hosted CI is not exercised by this local-only package. No physical generation,
  backend startup, publication or merge was performed.

## Model / usage

Implementation uses the primary Codex Local/Desktop session and one independent
targeted read-only reviewer. The recommended models/efforts above are not measured
usage; host-reported token/cost metrics are unavailable.
