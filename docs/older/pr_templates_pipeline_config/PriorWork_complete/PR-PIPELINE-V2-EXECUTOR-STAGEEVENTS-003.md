# PR-PIPELINE-V2-EXECUTOR-STAGEEVENTS-003
(Fully Expanded PR — Includes Adetailer as Its Own Stage)

## 1. Title
Pipeline V2 — Executor StageEvents Implementation (Including Adetailer Stage Support)

## 2. Summary
This PR wires the V2 executor so that every pipeline stage — **txt2img, img2img, adetailer, upscale** — emits structured **StageEvents** according to the Stage Sequencer contract.
This closes all remaining XFAILs and brings the executor up to the full V2 architecture requirements.

## 3. Problem Statement
The executor currently performs the real work but **emits no StageEvents**, causing:
- Stage-level diagnostics to fail
- Missing metadata for learning/feedback
- GUI status bar unable to display correct per-stage progress
- Randomizer + multi-node foundations lacking required telemetry

Additionally, **Adetailer was not treated as its own stage**, even though:
- It runs after txt2img/img2img
- It mutates images in-place
- It has its own config block
- Users rely heavily on it for faces/hands

We fix this fully.

## 4. Goals
- Emit StageStart / StageEnd / StageImageProgress events for all sequenced stages.
- Add **AdetailerStageExecution** and treat adetailer as a top-level stage.
- Store all emitted events in PipelineRunResult.
- Update PipelineRunner so that controller receives events live.
- Remove all XFAILs in test_upscale_hang_diag.py.

## 5. Non‑Goals
- No UI/UX changes except event handling hookup.
- No multi-node execution.
- No async queueing.
- No scheduler/sampler rewrites.

## 6. Allowed Files
- src/pipeline/executor.py
- src/pipeline/pipeline_runner.py
- src/pipeline/stage_sequencer.py
- src/pipeline/__init__.py
- src/controller/pipeline_controller.py
- tests/pipeline/*
- tests/controller/*
- tests/gui_v2/* (only for wiring validations)

## 7. Forbidden Files
- src/gui/* (except minimal event hookup)
- src/utils/randomizer*
- src/learning/*
- src/gui_v1 legacy files
- Any network API clients

## 8. Implementation Plan (Step‑by‑Step)

### 8.1 Add Adetailer to Stage Sequencer
- Add `StageType.ADETAILER`
- Add `AdetailerStageConfig` & `AdetailerStageExecution`
- Update `build_stage_execution_plan()` to include adetailer whenever config.adetailer.enabled == True.

### 8.2 Expand StageEvent model
Add:
- stage_type
- image_index (optional)
- total_images
- timestamp

### 8.3 Modify executor to emit events
In executor:
- Before each stage → emit StageStart
- For each image → emit StageImageProgress
- After stage → emit StageEnd

### 8.4 Integrate with PipelineRunner
Runner must:
- Accumulate events into PipelineRunResult
- Forward events to controller callbacks
- Provide events to learning module

### 8.5 Controller Wiring
PipelineController must:
- Register event callbacks
- Push events into:
  - StatusBarV2
  - LearningRecordWriter (if enabled)
  - Any test harness

### 8.6 Update Tests
- Remove XFAIL from:
  - test_upscale_hang_diag.py::test_multi_image_run_upscale_is_serial_and_honors_cancel
  - test_upscale_hang_diag.py::test_upscale_stage_logs_stage_and_image_progress
- Update sequencer tests to include adetailer stage
- Add new coverage for all StageEvents

### 8.7 Smoke Tests
- Validate correct order:
  1. txt2img
  2. img2img
  3. adetailer
  4. upscale
- Validate event counts
- Validate GUI progress bar receives correct events

## 9. Acceptance Criteria
- ✔ StageEvents emitted for all stages
- ✔ Adetailer treated as distinct stage
- ✔ No XFAILs in pipeline suite
- ✔ PipelineRunResult contains full event timeline
- ✔ GUI V2 receives and displays events
- ✔ No GUI/Tk imports in pipeline code
- ✔ Runner + Controller integrate cleanly

## 10. Rollback Plan
- Revert changes to executor, sequencer, runner, controller
- Reinstate XFAIL markers
- Restore prior pipeline contract tests

## 11. Codex Execution Block
Paste the following into CODEX:

```
You are CODEX-5.1-MAX.
Follow these instructions exactly.

PR: PR-PIPELINE-V2-EXECUTOR-STAGEEVENTS-003

ALLOWED FILES:
- src/pipeline/executor.py
- src/pipeline/pipeline_runner.py
- src/pipeline/stage_sequencer.py
- src/pipeline/__init__.py
- src/controller/pipeline_controller.py
- tests/pipeline/*
- tests/controller/*
- tests/gui_v2/* (only where needed)

FORBIDDEN FILES:
- Any GUI v1 files
- Any theme files
- randomizer modules
- learning modules
- utils modules
- external API modules

INSTRUCTIONS:
1. Add full StageEvents emission (start/end/progress).
2. Implement Adetailer as its own stage.
3. Update sequencer, executor, runner, controller accordingly.
4. Update PipelineRunResult to include event list.
5. Remove two XFAILS in test_upscale_hang_diag.py and make them pass.
6. Add new tests where needed.
7. Ensure no GUI/Tk imports in pipeline code.
8. Show full diff ONLY, no explanations.
```

---
