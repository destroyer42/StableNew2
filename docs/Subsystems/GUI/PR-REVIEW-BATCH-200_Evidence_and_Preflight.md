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
The initial package shrank the controller from 7,678 to 7,611 lines. After
integration with merged IMG-158, its ratchet is 7,615 versus updated main's
7,674; the added async admission wrapper reuses the existing coordinator and
the same synchronous admission method. The existing builder,
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
| Unsupported source stage appears successfully admitted: bug | `app_controller.py:1973,1983,2418`; `reprocess_builder.py:233,336` | Z-Image img2img admitted in each baseline case. IMG-158 subsequently fixed admission; the whole-selection preview now reuses its same operation assessment. Existing backend/profile validation stays authoritative. |
| Missing-file refusal: already supported, limited recovery | `reprocess_builder.py:233,236` | Zero admission with first error. Now aggregate per-item errors, explicitly exclude blocked items and re-preview; never silently omit. |
| Model/profile order choice: missing feature | `reprocess_builder.py:1033,1056` | Existing compatibility grouping keys include prompts/configuration and are not the requested ordering choice. Default new preview retains source order; optional stable model/profile sort only orders this new batch's NJRs. |
| Source lineage/shared identity: gap | `reprocess_builder.py:336`; `app_controller.py:1923,1973` | Parent job absent despite PNG job header; batch_id absent. Freeze header parent and content-hash artifact identity plus shared batch_id in existing NJR metadata. |
| Existing admission/lifecycle/output actions: already supported | `app_controller.py:2418`; `job_service.py:469,705`; `review_tab_frame_v2.py:1298,1361` | Reuse canonical submit/failure/cancel and existing recent-history import/Review curation. No new state store or batch execution authority. |

File names above resolve under `src/gui/views/`, `src/controller/` and
`src/pipeline/` respectively. Current fixes are in
`src/controller/review_batch_service.py:42,53,79`,
`src/controller/app_controller.py:1885,1906,1916,1925`,
`src/gui/review_batch_dialog.py:12,69,92,99,106` and
`src/gui/views/review_tab_frame_v2.py:1698`.

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
  jobs once through IMG-158's existing reprocess final preflight and
  `JobService.submit_njrs`. Any blocked row prevents
  admission until explicit exclusion/re-preview. Source bytes are hashed before
  and after preparation and rehashed immediately before final preflight/admission,
  including changes with identical size/mtime. GUI confirmation uses the existing
  background coordinator with one admission key per batch; Tk callbacks display
  completion/error. Confirmation disables repeat/close/re-preview actions while
  admission is pending. Cancel before confirmation does not touch queue/history;
  an error never auto-resubmits.
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

PR-IMG-MODELS-158 supplies global model-operation admission and selected-image
readiness. Its merged source is retained byte-for-byte in `reprocess_admission.py`,
`operation_compatibility.py`, the workflow adapter and reprocess builder.
Whole-selection preview assesses its compiled NJRs with `assess_njr`; final
submission independently requires each image operation through IMG-158's boundary.
No support envelope is widened here.

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

## Integration closeout after PR #88

PR #88 was first verified OPEN at head
`82389defe84f94838e4c303ed5998299667e6567`, with hosted `required` and `affected`
green. Work waited for the owner-authorized merge. It was then verified MERGED
at `2026-10-11T17:24:25Z`, merge commit
`6c977aef3628e1a1763f6466686acd2385cf53cd`. Fetched `origin/main` matched that
commit and contained the exact PR head and original baseline as ancestors.
The initially clean Review branch retained `814f983f` and merged updated main
without reset, rebase, overwrite or force-push. Conflicts were limited to
AppController imports, the two STATUS entries and the controller ratchet.
Shared Review GUI changes merged cleanly; the builder and admission source from
IMG-158 were preserved without additional modifications.

This is a Narrow integration/closeout pass using the same recommended
GPT-6.1 Sol High / Sonnet 5.5 High Local/Desktop profile. Baseline probe/evidence
was not rerun. Focused validation covers only the changed Review/controller/builder
integration surfaces and their existing regression cases. `integration-final.log`
records **66 passed in 8.23 seconds**: same-size/same-mtime source mutation before
admission and during preparation, selected/whole-selection readiness agreement,
explicit Klein edit, final-preflight bypass refusal, off-Tk hash/admission and
two independent batches retaining both callbacks, plus existing Review/builder
regressions. Initial test failures were expectation/API mismatches: the inherited
`OperationNotSupportedError` message and history entries accessed as mappings.
They were corrected to assert the canonical exception and actual entry attribute;
no validation assertion was removed or softened.

The integration canonical gate was invoked **once** and passed end-to-end
(`integration-pr-gate.log`): completeness (541 tracked Python files), controller
ratchet, Ruff, mypy smoke (10 files), isolated collection (8,473 tests) and required
smoke (386 passed in 34.01 seconds). Independent read-only aggregate review found
no concrete source/architecture blocker, verified final authority preservation,
hash binding, callback isolation and the exact controller ratchet. Aggregate and
staged whitespace checks pass. Initial-package evidence above remains dated to
that package and is not relabeled as integration-gate evidence. No new baseline,
physical generation, runtime launch, publication or Video implementation occurred.

## Corrected prioritization and remaining scope

The evidence justifies this small Review completion package, not a replacement
batch architecture. The implementation touches two existing application files,
adds two small modules, one deterministic regression suite and a lower controller
ratchet. Main risks are stale source inputs, compatibility-policy integration and
GUI callback lifetime; focused tests cover these boundaries. Hosted Python 3.14
CI remains before publication acceptance. Integration with PR-IMG-MODELS-158 is
complete locally; publication still requires owner authorization.

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
bounded review repair, tests, documentation and integration/closeout. Two initial
focused repair passes addressed independent-review findings and invalid empty-file
fixtures; integration corrected inherited exception expectations and the test's
history-entry attribute access, retaining all admission and immutability assertions.
One context compaction was observed. Efficiency judgment: appropriate for this
Standard package; no comparative measured cost claim.
