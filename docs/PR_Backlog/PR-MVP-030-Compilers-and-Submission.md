# PR-MVP-030 - Typed Compilers and NJR-only Submission

Status: Approved
Priority: CRITICAL
Effort: LARGE
Phase: Phase 2 - Repair the application boundary
Date: 2026-09-07

## 1. Context and decision

PR-MVP-020 closed the immutable eight-part NJR contract, but the application
boundary still carries a pack-shaped `PipelineRunRequest` and the preview
submission adapter converts NJRs back into mutable queue jobs in controller
code. That seam is the remaining source-identity compensation identified in
the architecture gap register. This PR cuts it over atomically.

The existing source builders are retained as source compilers where they
already have typed inputs: PromptPack, reprocess/image-edit, CLI, SVD/video
workflow, and learning. Replay and training receive explicit compiler DTOs.
No compiler owns queue, runner, GUI, or persistence side effects.

## 2. Goals

1. Add a frozen `SubmissionPolicy` containing only queue priority and an
   optional immediate-start preference.
2. Make `JobService.submit_njrs(records, policy)` the fresh application
   submission boundary. It validates the complete batch before enqueueing,
   creates mutable execution `Job` records internally, and preserves the one
   NJR -> queue -> runner route.
3. Derive job source and PromptPack behavior from the typed NJR source
   descriptor; no submission request may require or fabricate pack identity.
4. Migrate preview, replay, reprocess, learning, SVD, video-workflow, and
   training callers to the NJR boundary.
5. Add explicit replay and training intent/compiler seams without queue or
   runner imports.
6. Delete `PipelineRunRequest` and its pack-shaped builder branch after its
   last production and test caller is migrated.
7. Delete the callback-heavy preview submission adapter and make queue
   submission pass NJRs plus policy directly to `JobService`.
8. Leave every touched Python file free of Ruff findings and do not increase
   the pinned global Ruff baseline.

## 3. Non-goals and guardrails

- No SQLite repository; PR-MVP-040 owns durable state convergence.
- No PromptPack storage migration; PR-MVP-050 owns the one-file format.
- No new video backend or training-product UX; SVD selection remains PR-MVP-070
  and training remains non-release-gating.
- Do not broaden `SubmissionPolicy` with source, prompt, config dictionaries,
  callbacks, output paths, or expansion limits.
- Compilers must return complete NJRs and must not enqueue, execute, persist,
  call GUI methods, or import queue/runner modules.
- `JobService` may retain low-level lifecycle methods needed by queue restore
  and execution internals, but no enabled source caller may use them to submit
  fresh work.
- All batch records are validated and converted before the first queue write;
  malformed source/workload records cannot produce partial submission.
- `Run Now` remains queue-first and differs from Add to Queue only through the
  `start_when_idle` policy bit.

## 4. Allowed files

### Create

- `src/controller/submission_policy_v26.py`
- `src/pipeline/training_njr_compiler.py`
- `src/pipeline/replay_njr_compiler.py`
- `tests/pipeline/test_training_njr_compiler.py`
- `tests/pipeline/test_replay_njr_compiler.py`
- `tests/controller/test_job_service_njr_submission.py`

### Modify

- `src/controller/job_service.py`
- `src/controller/pipeline_controller.py`
- `src/controller/pipeline_controller_services/queue_submission_service.py`
- `src/controller/pipeline_controller_services/history_handoff_service.py`
- `src/controller/app_controller.py`
- `src/controller/svd_controller.py`
- `src/controller/video_workflow_controller.py`
- `src/gui/controllers/learning_controller.py`
- `src/learning/execution_controller.py`
- `src/curation/curation_workflow_builder.py`
- `src/pipeline/job_builder_v2.py`
- `src/pipeline/reprocess_builder.py`
- `src/pipeline/job_requests_v2.py`
- `tests/controller/test_queue_submission_service.py`
- `tests/controller/test_svd_controller.py`
- `tests/controller/test_video_workflow_controller.py`
- `tests/controller/test_pipeline_preview_to_queue_v2.py`
- `tests/controller/test_core_run_path_v2.py`
- `tests/controller/test_job_service_njr_validation.py`
- `tests/controller/test_pipeline_controller_learning_queue_cap.py`
- `tests/controller/test_learning_controller_njr.py`
- `tests/learning_v2/test_phase2_job_completion_integration.py`
- `tests/pipeline/test_job_builder_v2.py`
- `tests/pipeline/test_txt2img_path_closeout_invariants.py`
- `tests/integration/test_video_golden_paths_v26.py`
- `tests/video/test_svd_integration.py`
- `tests/controller/test_svd_controller.py`
- `tests/gui_v2/test_discovered_review_inbox.py`
- `tests/helpers/job_service_di_test_helpers.py`
- `tests/controller/conftest.py`
- `tests/TEST_SURFACE_MANIFEST.md`
- `tests/system/test_architecture_enforcement_v2.py`

### Delete

- `src/controller/pipeline_submission_service.py`

### Forbidden

- `src/queue/**`, `src/history/**`, `src/services/**`, `src/gui/views/**`,
  `src/gui/panels_v2/**`, `src/api/**`, `packs/**`, `data/**`
- any file not listed above

## 5. Implementation plan

### Step 1 - Submission policy and JobService boundary

Create a frozen `SubmissionPolicy(priority, start_when_idle)` with validated
priority. Add `submit_njrs(records, policy)` to `JobService`; reject non-NJR
inputs, duplicate IDs, invalid records, and empty batches before queue writes.
Construct execution `Job` objects from the immutable source/workload data, use
one canonical snapshot serializer, emit one coalesced queue update, and start
the queue worker only when the policy requests it. Do not write policy into the
NJR.

### Step 2 - Source callers

Replace every production `PipelineRunRequest` construction and `enqueue_njrs`
call with a source compiler result plus `SubmissionPolicy`. Preserve source
metadata in NJR provenance/source descriptors. PromptPack callers continue to
use the PromptPack builder; reprocess/SVD/video callers continue using typed
reprocess inputs; learning uses its existing typed records; CLI remains a pure
NJR compiler.

### Step 3 - Explicit replay and training compilers

Add `ReplayIntent`/`compile_replay_intent` that hydrates a valid source record,
creates a new identity with `HISTORY_REPLAY` source and parent lineage, and
returns an NJR without running it. Add `TrainingIntent`/
`compile_training_intent` for the existing train-LoRA configuration, replacing
the generic `JobBuilderV2.build_from_run_request` training branch.

### Step 4 - Remove generic and duplicate adapters

Delete `PipelineRunRequest`, its serialization/enums, the generic builder
method, `ReprocessJobBuilder.build_run_request`, and the preview submission
service. Simplify `QueueSubmissionService` to enforce learning/shutdown policy,
ordering, and then call `JobService.submit_njrs`.

### Step 5 - Guard the boundary

Add tests that scan production source for `PipelineRunRequest`, `enqueue_njrs`,
and fresh `submit_job_with_run_mode` callers; scan compiler modules for queue,
runner, GUI, and persistence imports; verify all source families submit NJRs,
Run Now is queue-first, invalid batches are atomic, replay identity changes,
and non-pack NJRs never acquire pack identity.

## 6. Verification plan

```text
python tools/ci/check_repository_completeness.py
python tools/ci/run_ruff_baseline.py
python tools/ci/run_mypy_smoke.py
python tools/ci/run_collection_gate.py
python tools/ci/run_required_smoke.py
python -m pytest -q tests/controller/test_job_service_njr_submission.py tests/pipeline/test_training_njr_compiler.py tests/pipeline/test_replay_njr_compiler.py tests/controller/test_queue_submission_service.py tests/controller/test_svd_controller.py tests/controller/test_video_workflow_controller.py
ruff check <every touched Python file>
git diff --check
```

Run the gates in disposable Python 3.11 and 3.12 environments. No network,
GUI display, model, GPU, WebUI, or user-data migration is permitted.

## 7. Exit criteria

- No production or test source imports `PipelineRunRequest` or calls
  `enqueue_njrs`.
- Every enabled source reaches the queue as a complete NJR through
  `JobService.submit_njrs`.
- PromptPack identity is conditional on the NJR source kind.
- Replay creates a new identity with parent lineage before submission.
- Training no longer uses a PromptPack-shaped request.
- No compiler or GUI module invokes the runner.
- Focused and supported-version gates pass; Ruff findings do not increase and
  touched files have zero findings.

## 8. Approval

Planner: Codex
Executor: Codex
Reviewer: Rob (Human Owner)
Approval Status: Approved

The owner’s instruction to generate, approve, and implement the next roadmap
PR authorizes this exact allowlist and ordered plan. Any additional file or
behavior requires a written amendment before change.

## 9. Rollback

Revert the single implementation commit. No queue/history data is rewritten;
the old generic request is removed only from source, not from persisted NJR
snapshots.
