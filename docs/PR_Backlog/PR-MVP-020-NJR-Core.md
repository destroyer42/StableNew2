# PR-MVP-020 - Immutable Eight-Part NJR Core

Status: In Progress
Priority: CRITICAL
Effort: LARGE
Phase: Phase 2 - Repair the core contract
Date: 2026-09-06

## 2. Context & Motivation

PR-MVP-010 established trustworthy gates. The current
`NormalizedJobRecord` still has more than 50 flat fields, includes mutable
status, completion, error, thumbnail, and produced-path facts, accepts broad
`Any` configuration, and is modified after construction by builders,
submission, replay, snapshots, and the runner. Its two snapshot serializers
emit different incomplete subsets.

The binding architecture instead defines NJR as the immutable eight-part
answer to “what work was authorized?” This PR replaces the mutable record with
that contract and makes legacy flat snapshots an explicit one-way input at the
repository boundary. PR-MVP-030 will build source-specific intent compilers and
replace the pack-shaped submission API after this core is stable.

## 3. Goals & Non-Goals

### Goals

1. Make the NJR top level exactly `schema_version`, `job_id`,
   `workload_kind`, `source`, `workload`, `stages`, `output_plan`,
   and `provenance`.
2. Provide frozen typed source descriptors and image, video, and training
   workload specifications.
3. Require source identity only for `prompt_pack`.
4. Reject source/workload/stage mismatches before submission.
5. Round-trip every accepted NJR field through one canonical serializer.
6. Read old flat snapshots only through a named, one-way migration reader that
   drops mutable execution facts.
7. Stop builders, replay, snapshots, runner, and services from mutating NJR.
8. Leave every touched source and test file free of Ruff findings.

### Non-goals

1. Do not replace `PipelineRunRequest` or the public JobService submission
   API; PR-MVP-030 owns that atomic cutover.
2. Do not add SQLite persistence; PR-MVP-040 owns it.
3. Do not migrate PromptPack storage; PR-MVP-050 owns it.
4. Do not promote Comfy, LTX, AnimateDiff, multi-shot, learning, or training to
   MVP release scope.
5. Do not retain a mutable compatibility NJR or a second executable job model.

## 4. Guardrails

- NJR remains the only public executable envelope and queue remains mandatory.
- The constructor accepts only the eight canonical fields.
- Nested mappings and sequences are frozen recursively; accessors may return
  detached read copies but may not expose mutable NJR storage.
- Status, timestamps, retry state, errors, output paths, thumbnails, and
  runtime results never serialize in NJR.
- PromptPack source requires an ID; all other supported source kinds may omit
  it and must not receive a fabricated pack ID.
- Legacy reading is explicit, one-way, and isolated to snapshot/migration
  boundaries. New builders may not call the legacy reader.
- Runner changes are limited to removing NJR mutation; execution algorithms
  and backend behavior do not change.
- Queue persistence format changes beyond embedding the complete NJR snapshot
  are forbidden.
- GUI view files and backend adapters are forbidden.

## 5. Allowed Files

### Files to Create

- `docs/PR_Backlog/PR-MVP-020-NJR-Core.md`
- `tests/pipeline/test_njr_core_v26.py`

### Files to Modify

- `src/pipeline/job_models_v2.py`
- `src/pipeline/job_builder_v2.py`
- `src/pipeline/prompt_pack_job_builder.py`
- `src/pipeline/reprocess_builder.py`
- `src/pipeline/cli_njr_builder.py`
- `src/pipeline/replay_engine.py`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/run_plan.py`
- `src/utils/snapshot_builder_v2.py`
- `src/controller/job_service.py`
- `src/controller/pipeline_controller_services/queue_submission_service.py`
- `src/controller/svd_controller.py`
- `src/controller/video_workflow_controller.py`
- `src/gui/controllers/learning_controller.py`
- `src/migrations/queue_history_migrator_v26.py`
- `tests/helpers/njr_factory.py`
- `tests/helpers/job_helpers.py`
- `tests/controller/test_app_controller_njr_exec.py`
- `tests/controller/test_core_run_path_v2.py`
- `tests/controller/test_job_service_njr_validation.py`
- `tests/pipeline/test_job_model_unification_v2.py`
- `tests/pipeline/test_job_service_njr_validation.py`
- `tests/pipeline/test_njr_prompt_pack_invariants.py`
- `tests/pipeline/test_prompt_pack_njr_invariants.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/pipeline/test_replay_run_plan_v2.py`
- `tests/queue/test_queue_njr_path.py`
- `tests/utils/test_snapshot_builder_v2.py`
- `tests/system/test_architecture_enforcement_v2.py`
- `tests/system/test_ci_truth_sync_v2.py`
- `tests/TEST_SURFACE_MANIFEST.md`
- `.github/copilot-instructions.md`
- `docs/ARCHITECTURE_v2.6.md`
- `docs/ARCHITECTURE_ENFORCEMENT_CHECKLIST_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/Subsystems/Testing/E2E_Golden_Path_Test_Matrix_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

### Forbidden Files

- `src/queue/**`
- `src/history/**`
- `src/services/**`
- `src/gui/views/**`
- `src/gui/panels_v2/**`
- `src/api/**`
- `src/video/**`
- `packs/**`
- `data/**`
- every file not listed above

## 6. Implementation Plan

### Step 1 - Define the canonical value model

In `job_models_v2.py`, add source/workload enums, recursively frozen JSON
values, frozen source, workload, stage, output-plan, and provenance dataclasses,
and the eight-field frozen `NormalizedJobRecord`. Validate IDs, supported
schema, source identity, workload discriminators, stage compatibility, counts,
and output intent in `__post_init__`.

Provide read-only derived properties needed by the current runner and
presentation projections. These properties must derive from typed nested
values or return detached copies. Do not expose setters or store mutable
execution facts.

### Step 2 - Make serialization complete and singular

Implement `to_dict` and strict `from_dict` on the canonical record. Require
all eight top-level keys and reject unknown schemas or malformed typed values.
Use explicit serializers for every nested value.

Add `read_njr` and `migrate_legacy_njr` for old flat snapshots. The legacy
reader infers workload only from explicit stage/config evidence, maps known
source names, preserves reproducibility input, and intentionally discards
status, timestamps, errors, thumbnails, results, and produced paths.

### Step 3 - Cut snapshots to the canonical serializer

Replace the duplicate serializer/deserializer in
`snapshot_builder_v2.py` with `record.to_dict()` and `read_njr`. Remove
PromptPack metadata repair. A malformed PromptPack NJR fails before a snapshot
is written.

Update the legacy queue/history migrator to construct the canonical record and
keep extracted lifecycle/output facts outside NJR.

### Step 4 - Make all current construction sites immutable

Update low-level, PromptPack, reprocess, CLI, learning, SVD, and video
construction to create complete typed values once. Intermediate builder
objects may be replaced with newly constructed NJRs before submission; no
post-construction field assignment is allowed.

Non-pack sources use their real source kind without synthetic
`prompt_pack_id`. Training uses only a training workload and `train_lora`
stage. Video uses a video workload and video stage. Reprocess/learning image
work retains explicit input paths and provenance without posing as a pack.

### Step 5 - Remove runtime mutation

Make JobService validation call the NJR contract and apply
`pack_required` only to a malformed PromptPack source. Build views with
execution-record status/timestamps rather than assigning them to NJR.

Make replay create a new NJR/workload value with parent lineage for resumed
work. Make the runner return artifacts/results without assigning output paths
or thumbnails to NJR. Remove queue-side metadata repair.

### Step 6 - Establish contract and enforcement tests

Cover image, native-video, training, replay, learning, CLI, PromptPack, and
non-pack examples; conditional source identity; recursive immutability;
source/workload/stage rejection; exact top-level shape; complete round trips;
unknown schema rejection; legacy mutable-field dropping; and new identity with
parent lineage.

Update only the listed older tests whose assertions directly defend mutable or
universal-pack behavior. Add an architecture scan rejecting assignments to
NJR execution/result fields and direct construction with noncanonical fields.

### Step 7 - Synchronize canon and close

After verification, mark the NJR-scope gap closed, narrow the source-identity
gap to remaining compiler/submission callers owned by PR-MVP-030, and record
actual evidence in all listed canonical documents. Move this one spec to
`docs/CompletedPR/` and make PR-MVP-030 the only active approved runtime PR.

## 7. Testing Plan

### Unit tests

```text
python -m pytest -q tests/pipeline/test_njr_core_v26.py
python -m pytest -q tests/utils/test_snapshot_builder_v2.py
python -m pytest -q tests/pipeline/test_njr_prompt_pack_invariants.py
python -m pytest -q tests/pipeline/test_prompt_pack_njr_invariants.py
python -m pytest -q tests/pipeline/test_replay_run_plan_v2.py
```

### Integration tests

```text
python -m pytest -q tests/controller/test_job_service_njr_validation.py
python -m pytest -q tests/pipeline/test_job_service_njr_validation.py
python -m pytest -q tests/controller/test_core_run_path_v2.py
python -m pytest -q tests/queue/test_queue_njr_path.py
```

### Journey or smoke coverage

```text
python tools/ci/run_collection_gate.py
python tools/ci/run_required_smoke.py
```

### Manual verification

```text
python tools/ci/check_repository_completeness.py
python tools/ci/run_ruff_baseline.py
python tools/ci/run_mypy_smoke.py
ruff check <every touched Python file>
git diff --check
```

Inspect canonical serialized image, video, and training examples and verify the
top-level key set is exact.

## 8. Verification Criteria

### Success criteria

1. NJR has exactly eight top-level fields and is recursively immutable.
2. Canonical serialization round-trips every nested accepted field.
3. PromptPack identity is conditional and valid non-pack examples pass.
4. Mutable execution/result facts are absent from class fields and serialized
   output.
5. No source, builder, snapshot, replay, service, or runner code assigns to an
   NJR after construction.
6. Legacy reading is explicit and never used by fresh builders.
7. Supported-version required gates pass without repository pollution.
8. Ruff baseline decreases and every touched Python file is clean.

### Failure criteria

1. A second job envelope, legacy constructor, setter, or mutable nested value
   remains.
2. Any non-pack source receives or requires fabricated PromptPack identity.
3. Serialization omits an accepted value or silently accepts unknown schema.
4. Runner/service writes status, result, error, thumbnail, or path into NJR.
5. Fresh construction calls the legacy migration reader.
6. A touched file retains Ruff findings or the global baseline increases.

## 9. Risk Assessment

### Low-risk areas

- Enum/value-object definitions and focused serialization fixtures.

### Medium-risk areas with mitigation

- Presentation code reads flat convenience fields. Preserve only derived,
  read-only accessors and test that returned mappings cannot mutate NJR.
- Old snapshots vary. Keep migration explicit, table-driven, and covered with
  representative shapes.

### High-risk areas with mitigation

- Broad constructor replacement can strand a hidden producer. Scan every
  production `NormalizedJobRecord(` call and run strict collection plus the
  focused builder/controller suites.
- Runner mutation removal can lose outputs. Assert outputs remain in typed
  runner results and queue/history execution records, never NJR.

### Rollback plan

Revert the single PR-MVP-020 implementation commit. No persisted user file is
rewritten, and legacy snapshots remain untouched inputs.

## 10. Tech Debt Analysis

### Debt removed

- Broad mutable NJR and duplicate incomplete serializers.
- Universal PromptPack identity validation.
- Runner/service/snapshot mutation of authorized work.
- Ambiguous legacy hydration inside normal construction.

### Debt intentionally deferred

| Debt | Owner |
|---|---|
| Pack-shaped `PipelineRunRequest` and old JobService entry | `PR-MVP-030` |
| Source-specific intent DTO/compiler organization | `PR-MVP-030` |
| Queue/history SQLite authority and execution records | `PR-MVP-040` |
| PromptPack storage migration | `PR-MVP-050` |
| Non-MVP learning/training UI quarantine | `PR-MVP-080` |
| Untouched Ruff baseline debt | `PR-MVP-080` / `PR-MVP-090` |

## 11. Documentation Updates

The listed Tier 1/Tier 2 architecture, governance, builder, PromptPack,
testing, golden-path, roadmap, and index files change only after implementation
evidence exists. The PR spec moves to one CompletedPR record at closeout.
README does not change because operator commands remain the same.

## 12. Dependencies

### Internal module dependencies

- Completed PR-MVP-010 trustworthy test and lint gates.
- Binding eight-part contract in `ARCHITECTURE_v2.6.md`.
- PR-MVP-005 rejection of PromptPack identity compensation.

### External tools or runtimes

- Python 3.11 and 3.12, pytest, Ruff 0.14.9, and mypy.
- No network, WebUI, model, GPU, display, or migration write.

## 13. Approval & Execution

Planner: Codex
Executor: Codex
Reviewer: Rob (Human Owner)
Approval Status: Approved

The owner's 2026-09-06 instruction to generate, approve, and implement the next
two roadmap PRs approves this exact allowlist and ordered plan. Any additional
file requires a written amendment before it changes.

## 14. Next Steps

1. Implement and close PR-MVP-020.
2. Generate, approve, and implement PR-MVP-030 on the verified immutable core.
3. Preserve the non-increasing lint ratchet throughout.
