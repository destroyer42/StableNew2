# D-VIDEO-004 - AnimateDiff Current-State Discovery

**Status:** Discovery  
**Version:** v2.6  
**Date:** 2026-03-13  
**Subsystem:** Pipeline / Video / WebUI extension integration  
**Author:** Codex

---

## 1. Purpose

This discovery supersedes the implementation assumptions in
[`docs/D-VIDEO-001-AnimateDiff-Integration-Discovery.md`](./D-VIDEO-001-AnimateDiff-Integration-Discovery.md)
for immediate planning purposes.

Its purpose is to answer one narrower question:

1. What is the smallest architecture-aligned Phase 1 AnimateDiff feature that
   can be implemented against the current StableNew runtime?

This document does not approve implementation by itself. It exists to support a
fresh PR specification that matches the codebase as it exists on 2026-03-13.

---

## 2. Executive Summary

### Conclusion

StableNew can support a **Phase 1 AnimateDiff runtime foundation** if it is
implemented as a **capability-gated pipeline stage** named `animatediff`,
executed through the existing NJR -> RunPlan -> PipelineRunner path.

### Phase 1 should include

1. `animatediff` stage type support in runtime-only code.
2. WebUI capability detection via the existing `/sdapi/v1/scripts` path.
3. AnimateDiff payload construction through `alwayson_scripts["AnimateDiff"]`.
4. Frame extraction plus MP4 assembly through the already working
   [`src/pipeline/video.py`](../src/pipeline/video.py) path.
5. Runtime metadata for video outputs.

### Phase 1 should not include

1. GUI cards or preset wiring.
2. Learning integration.
3. History/review playback UI changes.
4. ControlNet / Deforum / audio / interpolation backends.

### Key correction versus older repo docs

The older repo PR draft assumes a simpler, fixed AnimateDiff API contract.
Current extension docs indicate:

1. the script key is `AnimateDiff`, not `animatediff`
2. save format behavior is configurable
3. returning frames versus saving them is a contract choice, not a given

That means the repo should implement **contract-gated payload building**, not a
hardcoded payload copied from older notes.

---

## 3. Current Runtime Reality

### 3.1 What exists today

The current codebase already has:

1. canonical stage sequencing in
   [`src/pipeline/stage_models.py`](../src/pipeline/stage_models.py) and
   [`src/pipeline/stage_sequencer.py`](../src/pipeline/stage_sequencer.py)
2. NJR runtime execution through
   [`src/pipeline/run_plan.py`](../src/pipeline/run_plan.py) and
   [`src/pipeline/pipeline_runner.py`](../src/pipeline/pipeline_runner.py)
3. stage execution helpers in
   [`src/pipeline/executor.py`](../src/pipeline/executor.py)
4. an FFmpeg-backed video assembly path in
   [`src/pipeline/video.py`](../src/pipeline/video.py)
5. an API client that already talks to `/sdapi/v1/txt2img`,
   `/sdapi/v1/img2img`, and `/sdapi/v1/scripts` in
   [`src/api/client.py`](../src/api/client.py)

### 3.2 What does not exist today

The current codebase does not yet have:

1. `animatediff` in the stage type system
2. motion-module discovery helpers
3. capability detection for the AnimateDiff extension
4. a stage executor that converts WebUI frame results into a clip artifact
5. NJR builder support for `animatediff`
6. any GUI or preset plumbing for animation parameters

---

## 4. Drift In Existing AnimateDiff Docs

### 4.1 Older docs are directionally useful, but stale

The following documents are useful context but not safe to execute literally:

1. [`docs/D-VIDEO-001-AnimateDiff-Integration-Discovery.md`](./D-VIDEO-001-AnimateDiff-Integration-Discovery.md)
2. [`docs/PR-VIDEO-001-Core-AnimateDiff-Stage.md`](./PR-VIDEO-001-Core-AnimateDiff-Stage.md)
3. [`docs/PR-VIDEO-002-AnimateDiff-GUI-Integration.md`](./PR-VIDEO-002-AnimateDiff-GUI-Integration.md)

### 4.2 Specific drift

1. `src/api/client.py` now has a clear `txt2img(payload)` /
   `img2img(payload)` shape; older docs assume looser calling patterns.
2. `src/pipeline/run_plan.py` is very lightweight and stage-name driven; any
   phase plan must fit that reality.
3. `src/pipeline/job_models_v2.py` currently constrains stage types to
   `"txt2img" | "img2img" | "adetailer" | "upscale"`.
4. `docs/D-VIDEO-003-AnimateDiff-Research-Scaffold.md` explicitly says do not
   start implementation until the extension contract and artifact semantics are
   pinned down.

This discovery addresses that gap for a narrow Phase 1.

---

## 5. External Contract Findings

### 5.1 Primary-source findings

From the current AnimateDiff extension materials:

1. AnimateDiff is invoked through A1111 `alwayson_scripts`.
2. The current documented script key is `AnimateDiff`.
3. Save/return behavior is format-dependent.
4. A1111 can still be called through normal `txt2img` / `img2img` endpoints.

### 5.2 Practical implication for StableNew

StableNew should model AnimateDiff as:

1. a **distinct pipeline stage**
2. whose executor internally builds a normal WebUI generation payload
3. then attaches `alwayson_scripts["AnimateDiff"]`
4. then collects either returned frames or saved frames
5. then assembles MP4 through `VideoCreator`

This keeps the StableNew architecture clear even though the underlying WebUI
extension is implemented as a generation-script modifier.

---

## 6. Recommended Phase 1 Architecture

### 6.1 Stage model decision

For StableNew, AnimateDiff should be represented as:

1. `StageType.ANIMATEDIFF = "animatediff"`

This is still the best architecture fit because:

1. it preserves explicit stage-chain semantics in NJR
2. it avoids hiding motion generation inside txt2img/img2img flags
3. it keeps GUI and learning work optional in later PRs
4. it makes capability-gating explicit

### 6.2 Execution semantics

Recommended canonical ordering for Phase 1:

1. `txt2img -> animatediff`
2. `img2img -> animatediff`
3. `txt2img -> upscale -> animatediff`

Recommended validation rules:

1. `animatediff` requires a preceding image-producing stage
2. `animatediff` must be the final runtime stage in Phase 1
3. Phase 1 does not allow multiple `animatediff` stages

### 6.3 Artifact semantics

Recommended Phase 1 output contract:

1. primary artifact: MP4 clip
2. secondary artifact: frame directory
3. stage metadata includes:
   - `video_path`
   - `frame_paths`
   - `frame_count`
   - `fps`
   - `motion_module`
   - `extension_contract`

This gives enough metadata for history/learning later without forcing immediate
UI changes now.

---

## 7. Required Runtime Changes

### 7.1 Core files affected

Phase 1 necessarily touches:

1. [`src/pipeline/stage_models.py`](../src/pipeline/stage_models.py)
2. [`src/pipeline/job_models_v2.py`](../src/pipeline/job_models_v2.py)
3. [`src/pipeline/stage_sequencer.py`](../src/pipeline/stage_sequencer.py)
4. [`src/pipeline/run_plan.py`](../src/pipeline/run_plan.py)
5. [`src/pipeline/prompt_pack_job_builder.py`](../src/pipeline/prompt_pack_job_builder.py)
6. [`src/pipeline/reprocess_builder.py`](../src/pipeline/reprocess_builder.py)
7. [`src/pipeline/pipeline_runner.py`](../src/pipeline/pipeline_runner.py)
8. [`src/pipeline/executor.py`](../src/pipeline/executor.py)
9. [`src/pipeline/video.py`](../src/pipeline/video.py)
10. [`src/api/client.py`](../src/api/client.py)

### 7.2 Why these are required

1. stage types and display text must admit `animatediff`
2. builders must be able to emit `StageConfig(stage_type="animatediff", ...)`
3. runner must dispatch the stage
4. executor must build the payload and interpret frame/video outputs
5. video assembly and cleanup must be deterministic
6. client must expose capability/motion-module discovery helpers

---

## 8. Risks

### High risk

1. The extension contract is version-sensitive.
2. Returned artifact shape can vary by save format.
3. WebUI installs without AnimateDiff must fail clearly, not opaquely.

### Medium risk

1. Current pipeline code assumes image outputs more often than generic artifacts.
2. Frame storage can consume disk quickly.
3. `RunPlan` currently carries minimal per-stage detail.

### Low risk

1. FFmpeg assembly itself is now working locally.
2. The API client already has a `/sdapi/v1/scripts` access pattern.

---

## 9. Recommendation

Proceed with a **runtime-only, capability-gated AnimateDiff Phase 1 PR** before
any GUI work.

That PR should:

1. add the stage type
2. add extension discovery
3. execute AnimateDiff through `alwayson_scripts`
4. assemble MP4 output
5. add deterministic runtime tests

Then, and only then, plan GUI and learning follow-ons.

---

## 10. References

### Internal

1. [`docs/D-VIDEO-003-AnimateDiff-Research-Scaffold.md`](./D-VIDEO-003-AnimateDiff-Research-Scaffold.md)
2. [`docs/D-VIDEO-001-AnimateDiff-Integration-Discovery.md`](./D-VIDEO-001-AnimateDiff-Integration-Discovery.md)
3. [`src/api/client.py`](../src/api/client.py)
4. [`src/pipeline/pipeline_runner.py`](../src/pipeline/pipeline_runner.py)
5. [`src/pipeline/video.py`](../src/pipeline/video.py)

### External

1. AnimateDiff extension repo:
   https://github.com/continue-revolution/sd-webui-animatediff
2. AnimateDiff API/features docs:
   https://github.com/continue-revolution/sd-webui-animatediff/blob/master/docs/features/README.md

