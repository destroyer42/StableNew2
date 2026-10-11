# PR-REVIEW-BATCH-200 — Evidence and whole-selection preflight

## Execution profile and model/reasoning recommendation

Standard, known-architecture package: reproduce Review's existing batching,
then repair only demonstrated preview, admission-preparation and lineage gaps.
Recommend Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High under
`docs/AI_MODEL_SELECTION.md`. The cross-file Tk, immutable-record and SQLite
verification warrants High to reduce retries and total successful-work cost.
Local/Desktop fits the real repository and native Tk test surface. No measured
model cost or success-rate comparison is claimed.

Controller surface assessment: AppController delegates compilation to
`review_batch_service.py` and presentation to `review_batch_dialog.py`.
Its physical-line ratchet falls from 7,678 to 7,611. The existing builder,
JobService, SQLite repository, queue, runner and backend authorities are retained.
There is no second lifecycle, runner, process manager or submission route.

## Baseline evidence before changes

Base: `94aac066596da11caaea9381d053dbac526b0c2d` (live `origin/main` snapshot).
The initial `StableNew-main` checkout contained unrelated staged
PR-IMG-MODELS-158 work on `codex/img-models-158-cross-workflow-compat` at that
same SHA. It was preserved. This package uses the initially clean worktree
`C:/Users/rob/qual/StableNew-review200`, branch
`codex/review-batch-200-evidence`, created from `origin/main`.

An external baseline probe drove real `ReviewTabFrame` widgets programmatically
under withdrawn native Tk, the actual AppController/builder and actual
JobService/SQLite admission. Synthetic 32x32 PNGs used three checkpoints,
distinct neutral prompts, shared appended instructions and 20% missing native
metadata. Auto-run was disabled and runner startup was guarded against use.
This is deterministic GUI-widget evidence, **not a manual interactive session,
generation result or physical backend test**. No Forge/Comfy process was launched.

| Sources | Visible entries | Mixed metadata: NJRs / admitted | Incompatible last: NJRs / admitted | Missing file last: NJRs / admitted |
|---:|---:|---:|---:|---:|
| 10 | 10 | 10 / 10 | 10 / 10 | 0 / 0 |
| 25 | 25 | 25 / 25 | 25 / 25 | 0 / 0 |
| 40 | 40 | 40 / 40 | 40 / 40 | 0 / 0 |

Mixed cases logged 8/10, 20/25 and 32/40 metadata baselines and 9, 21 and 33
compatibility groups. Every admitted job had exactly one source. All selected
sources were listed, but effective-settings text described only the selected
first image. The incompatible last item was an exact Z-Image v1 source requested
for img2img: baseline admission showed generic success despite its unsupported
stage. Missing files produced an explicit `Input image not found` error and no
admission. Native source job headers were present, but compiled parent job and
shared batch identity were absent.

Local detailed evidence is preserved outside user data:
`C:/Users/rob/qual/REVIEW200-evidence/{phase0.py,baseline.json,baseline.log}`.
The JSON records exact per-source NJR paths, prompts, models, parent/batch fields,
selected-preview text and dialogs for all nine cases.

## Claim ledger and corrected scope

References in the baseline column are at the base SHA above, not shifted lines
in this implementation.

| Claim / classification | Exact baseline source | Observation / disposition |
|---|---|---|
| 10–25-source admission, one job/source, shared edits: already supported | `review_tab_frame_v2.py:1641,1649,1706`; `app_controller.py:1884,1923,1973`; `reprocess_builder.py:983,1033,1059` | 10/25/40 admitted with exact mapping. Retain builder and append/replace/modify semantics; no batching rewrite. |
| Whole-selection preflight: missing feature | `review_tab_frame_v2.py:1501,1502` | Selected-image preview cannot expose other models, prompts or errors. Added asynchronous whole-selection compilation and explicit frozen-job confirmation. |
| Unsupported source stage appears successfully admitted: bug | `app_controller.py:1973,1983,2418`; `reprocess_builder.py:233,336` | Z-Image img2img admitted in each baseline case. Preflight now exposes every policy-stage refusal; existing backend/profile validation stays authoritative. |
| Missing-file refusal: already supported, limited recovery | `reprocess_builder.py:233,236` | Zero admission with first error. Now aggregate per-item errors, explicitly exclude blocked items and re-preview; never silently omit. |
| Model/profile order choice: missing feature | `reprocess_builder.py:1033,1056` | Existing compatibility grouping keys include prompts/configuration and are not the requested ordering choice. Default new preview retains source order; optional stable model/profile sort only orders this new batch's NJRs. |
| Source lineage/shared identity: gap | `reprocess_builder.py:336`; `app_controller.py:1923,1973` | Parent job absent despite PNG job header; batch_id absent. Freeze header parent and content-hash artifact identity plus shared batch_id in existing NJR metadata. |
| Existing admission/lifecycle/output actions: already supported | `app_controller.py:2418`; `job_service.py:469,705`; `review_tab_frame_v2.py:1298,1361` | Reuse canonical submit/failure/cancel and existing recent-history import/Review curation. No new state store or batch execution authority. |

File names above resolve under `src/gui/views/`, `src/controller/` and
`src/pipeline/` respectively. Current fixes are in
`src/controller/review_batch_service.py:37,61`,
`src/controller/app_controller.py:1884,1905,1915`,
`src/gui/review_batch_dialog.py:12,65,88,93,100` and
`src/gui/views/review_tab_frame_v2.py:1690`.

## Final behavior and architectural limits

- Every source is decoded, read and hashed off the GUI thread before admission.
  Missing/corrupt files and incompatible target stages remain visible blocked
  rows. Missing metadata retains the established fallback; malformed native
  metadata explicitly labels the fallback. No saved source or PromptPack is edited.
- Default compilation produces one immutable NJR per source, preserving its
  prompt baseline, shared edit, model, source path, source-job parent when available
  and SHA-256 artifact identity. All jobs share batch_id in the existing immutable
  metadata snapshot. Existing explicit compatible multi-source batch_size remains
  supported; it is not made the default.
- The optional checkpoint/profile order is a stable sort of only prepared new
  NJRs. Prior queued jobs remain unchanged. Cross-checkpoint retargeting is deferred.
- The transient dialog shows each source, final prompts, stage settings,
  backend/profile, output directory and lineage. It submits exactly those frozen
  jobs once through existing `JobService.submit_njrs`. Any blocked row prevents
  admission until explicit exclusion/re-preview. Source size/mtime changes require
  re-preview. Cancel does not touch queue/history; an error never auto-resubmits.
- Existing job failure/cancellation remains per job through queue/repository and
  JobService. No automatic replay of dispatched work, backend fallback, runtime
  ownership change, or generation request is added.
- Preparation reads existing sources; it creates no derived images or output
  files. Disk-space forecasting remains absent. A reliable forecast needs the
  actual output/preparation policy and filesystem evidence, not a guessed threshold.
  Existing execution owns output creation and reports storage failures normally.
- Existing recent-history import and Review/curation actions provide output access.
  A dedicated batch-id output filter/shortcut remains a lower-priority feature;
  this package only supplies provenance for a future repository projection.

Separate PR-IMG-MODELS-158 addresses global model-operation admission and
selected-image readiness. This package does not copy those edits. Publication
should integrate/check against that package first, including any changed controller
ratchet and shared Review sections. No support envelope is widened here.

## Token-efficient validation plan and evidence

Reuse baseline results at the unchanged base. Run focused deterministic tests on
the real builder/Tk/temporary SQLite path, inspect the aggregate, then run the
canonical PR gate once near final verification. No GPU/backend environment or
physical retry is needed for this package.

- `tests/gui_v2/test_review_batch_200.py`: 10/25/40 mapping and admission,
  immutable provenance, optional grouping with existing queued work, explicit
  blocked exclusion, corrupt/missing/malformed inputs, cancellation, source-change
  re-preview, worker/GUI dispatch, detail projection and legacy batch_size.
- Existing affected controller, prompt-mode, Review, builder and queue/history
  regressions are retained. Empty-file controller fixtures are changed to valid
  synthetic PNGs to exercise the new decoder check; assertions are unchanged.
- Focused validation: 72 affected tests passed, including synthetic running-to-failed
  transition and queued cancellation through existing lifecycle APIs with unchanged
  immutable snapshots (`affected-final2.log`, 7.12 seconds).
- `python tools/ci/run_pr_gate.py` was invoked **once**. It stopped at completeness
  because the two new source modules had not yet been staged (`pr_gate.log`). After
  staging, completeness passed with 538 tracked Python files. The remaining steps
  were run individually: controller ratchet PASS; Ruff PASS (after correcting the
  new lifecycle test's import order); mypy smoke PASS on 10 files; isolated collection
  PASS with 8,384 tests (`collection.log`); required smoke PASS with 386 tests
  (`required-smoke.log`). This is not reported as a successful canonical invocation.
- `git diff HEAD --check` passed. Independent final aggregate read-only review
  verified the ledger references, all nine baseline cases, 17 new cases and the
  exact controller ratchet, and found no concrete source/architecture blocker.
  Required smoke finished successfully after that reviewer inspected the log.
  Logs are under the evidence root above; hosted CI has not been run for this branch.

## Corrected prioritization and remaining scope

The evidence justifies this small Review completion package, not a replacement
batch architecture. The implementation touches two existing application files,
adds two small modules, one deterministic regression suite and a lower controller
ratchet. Main risks are stale source inputs, compatibility-policy integration and
GUI callback lifetime; focused tests cover these boundaries. Hosted Python 3.14
CI and integration with PR-IMG-MODELS-158 remain before publication acceptance.

Next recommendation: **PR-VID-BATCH-200**, multi-source Video Workflow through the
existing compiler/JobService/SQLite path. Scope it by the Video intent/controller,
source mapping, whole-selection validation and corresponding regression surfaces.
No Video implementation begins here. Cross-checkpoint reprocessing, disk forecasts
and a dedicated batch-output view remain separate outcomes; a batch-output view
would need a repository projection and GUI tests, not a new store.

## Model / usage

Host: Codex Local/Desktop. Recommended profile: GPT-6.1 Sol High. Exact selected
model/effort telemetry, token deltas, cost/credits and reliable package elapsed
time are unavailable in the current host. Phases: discovery, implementation,
bounded review repair, tests, documentation and closeout. Two focused repair
passes addressed independent-review findings and invalid empty-file fixtures.
One context compaction was observed. Efficiency judgment: appropriate for this
Standard package; no comparative measured cost claim.
