# PR-ARCH-243 - Archive Import Fencing and Reference Relocation

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Phase 7 - Structural and architectural cleanup queue
Date: 2026-03-27

## 1. Context & Motivation

After `PR-ARCH-242`, the active controller -> GUI inversion in the core path is
gone, but StableNew still keeps reference-only archive code under importable
runtime package paths:

- `src/controller/archive/`
- `src/gui/views/archive/`
- `src/gui/panels_v2/archive/`

Current repo truth:

- the only remaining non-archive import of archive code is compat-only:
  `tests/compat/test_end_to_end_legacy_submission_modes.py`
- active source modules no longer depend on `src.controller.archive.*`
- the risk is now accidental future reuse, not active runtime execution

This still violates the v2.6 architecture rule that archive/reference code must
not live as importable runtime dependencies under `src/`.

## 2. Goals & Non-Goals

### Goals

1. Remove Python archive/reference modules from importable `src/**/archive/**`
   paths.
2. Relocate reference-only archive code needed for compat/history context to a
   non-runtime location outside `src/`.
3. Update compat-only tests that still need legacy reference types so they
   import from the new reference location.
4. Add enforcement tests proving:
   - active source no longer imports archive/reference code
   - archive/reference Python modules do not remain under `src/**/archive/**`
   - compat-only tests are the only place allowed to import the relocated
     archive-reference package

### Non-Goals

1. Do not revive `PipelineConfig` execution or any legacy runtime path.
2. Do not widen this PR into `PipelineController` service extraction or runner
   refactors.
3. Do not remove compat tests that intentionally validate legacy-labeled flows.
4. Do not archive broad swaths of `tests/` or `docs/` in this PR.
5. Do not rename large GUI/runtime surfaces beyond what is required for
   relocation and fencing.

## 3. Guardrails

- `NormalizedJobRecord` remains the only executable outer job contract.
- Fresh execution remains queue-only.
- `PipelineRunner.run_njr(...)` remains the only production runner entrypoint.
- Relocated archive code is reference-only and must not become a new supported
  runtime API.
- Any remaining legacy reference imports must stay inside compat-only test
  surfaces.

## 4. Allowed Files

### Files to Create

- `tools/archive_reference/__init__.py`
- `tools/archive_reference/controller/__init__.py`
- `tools/archive_reference/controller/legacy_pipeline_config_types.py`
- `tools/archive_reference/controller/legacy_pipeline_config_assembler.py`
- `tools/archive_reference/gui/__init__.py`
- `tools/archive_reference/gui/pipeline_config_panel.py`
- `tools/archive_reference/gui/pipeline_config_panel_v2.py`
- `tools/archive_reference/README.md`
- `tests/safety/test_no_archive_python_modules_under_src.py`

### Files to Modify

- `tests/compat/test_end_to_end_legacy_submission_modes.py`
- `tests/system/test_architecture_enforcement_v2.py`
- `tests/system/test_test_taxonomy_enforcement_v26.py`
- `src/controller/archive/README.md`
- `src/gui/views/archive/README.md`
- `src/gui/panels_v2/archive/README.md`
- docs that describe the active post-`PR-241` queue if completion text needs
  to reference the new archive-reference location

### Files to Delete

- `src/controller/archive/pipeline_config_types.py`
- `src/controller/archive/pipeline_config_assembler.py`
- `src/gui/views/archive/pipeline_config_panel.py`
- `src/gui/panels_v2/archive/pipeline_config_panel_v2.py`

### Forbidden Files

- `src/queue/*`
- `src/video/*`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- canonical architecture docs except for targeted wording updates if strictly
  required by changed runtime truth

## 5. Implementation Plan

### Step 1 - Relocate archive Python modules out of `src/`

Move the archived reference modules into a non-runtime package under `tools/`,
keeping names explicit that they are legacy/reference-only.

Recommended destination layout:

- `tools/archive_reference/controller/legacy_pipeline_config_types.py`
- `tools/archive_reference/controller/legacy_pipeline_config_assembler.py`
- `tools/archive_reference/gui/pipeline_config_panel.py`
- `tools/archive_reference/gui/pipeline_config_panel_v2.py`

Why:

- `tools/` is already used for non-runtime utility/reference code
- this removes accidental import discoverability from `src/`
- compat tests can still import the legacy reference types explicitly

### Step 2 - Remove live Python files from `src/**/archive/**`

Delete the archived Python modules under `src/` once the relocated copies
exist.

Keep only README-level markers in the `src/**/archive/` directories if helpful,
or remove the directories entirely if they become empty.

Why:

- “archived but still importable under `src`” is the defect this PR closes

### Step 3 - Update compat-only legacy tests

Update any compat tests that still import legacy `PipelineConfig` reference
types to import from the new `tools.archive_reference...` location.

Current known file:

- `tests/compat/test_end_to_end_legacy_submission_modes.py`

Why:

- this preserves explicit legacy test intent without keeping runtime-path
  archive imports alive

### Step 4 - Tighten enforcement

Update architecture/test-taxonomy enforcement so:

- no active source file imports `src.controller.archive.*`
- no active source file imports `tools.archive_reference.*`
- compat-only tests remain the only allowed consumers of
  `tools.archive_reference.*`
- no Python modules remain under `src/**/archive/**`

Why:

- the relocation must be mechanically guarded or it will regress

### Step 5 - Validate canonical path integrity

Run focused tests covering:

- compat legacy tests that still use the relocated reference code
- architecture enforcement
- test taxonomy enforcement
- queue/controller smoke surfaces that should remain unaffected

## 6. Testing Plan

### Unit / safety / enforcement

- `pytest tests/safety/test_no_archive_python_modules_under_src.py -q`
- `pytest tests/system/test_architecture_enforcement_v2.py tests/system/test_test_taxonomy_enforcement_v26.py -q`

### Compat coverage

- `pytest tests/compat/test_end_to_end_legacy_submission_modes.py -q`

### Regression confidence

- `pytest tests/controller/test_core_run_path_v2.py tests/controller/test_pipeline_preview_to_queue_v2.py -q`

## 7. Acceptance Criteria

1. No Python modules remain under `src/controller/archive/`,
   `src/gui/views/archive/`, or `src/gui/panels_v2/archive/`.
2. Legacy reference code needed for compat/history context lives outside
   `src/`, under a clearly non-runtime reference path.
3. Active source imports of archive/reference modules are zero.
4. Compat-only tests remain green after import updates.
5. Enforcement tests fail if archive Python files are reintroduced under `src/`
   or if active source starts importing the relocated reference package.

## 8. Risks & Mitigations

### Risk: compat tests implicitly rely on `src.controller.archive` path shape

Mitigation:

- update only the known compat import surfaces in this PR
- keep relocated module names explicit and stable

### Risk: archive relocation is mistaken for runtime API support

Mitigation:

- use `legacy_` naming
- place the code under `tools/archive_reference/`
- add README language that the package is reference-only and non-runtime

### Risk: deleting `src/**/archive/*.py` breaks hidden imports

Mitigation:

- run explicit grep before and after relocation
- run architecture enforcement and compat tests in the same PR

## 9. Deferred Follow-ons

- `PR-HYGIENE-244` for broader tracked mutable-state cleanup
- `PR-ARCH-246` for wider architecture enforcement expansion
- `PR-CTRL-247` for further controller reduction after archive fencing is
  complete
