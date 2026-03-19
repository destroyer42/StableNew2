# D-QUEUE-004: Stage-Level Checkpoint Resume System

**Status:** Discovery  
**Priority:** High (Production Reliability)  
**Component:** Queue Runner, Pipeline Execution  
**Related:** [DEBUG HUB v2.6](DEBUG%20HUB%20v2.6.md), [ARCHITECTURE_v2.6](ARCHITECTURE_v2.6.md)

---

## Executive Summary

**Problem:** WebUI crashes due to VRAM exhaustion cause entire multi-stage jobs (txt2img → ADetailer → upscale) to restart from the beginning, wasting GPU time and duplicating successful stages.

**Discovery:** Intermediate images ARE ALREADY SAVED after each pipeline stage. The infrastructure for checkpointing exists, but there's no resume logic to leverage it.

**Opportunity:** Implement stage-level resume capability so that after WebUI restarts, jobs can continue from the last successfully completed stage instead of restarting from txt2img.

**Impact:**
- ✅ Recover from resource exhaustion crashes without wasting work
- ✅ Reduce job turnaround time by 50-90% for mid-job crashes
- ✅ Improve batch processing reliability for large reprocess jobs
- ✅ Better resource utilization (no duplicate stages)

---

## Context & Motivation

### User Report (Dec 25, 2024)

User experienced WebUI crash during a batch reprocess job:
- Job successfully completed 7+ images through txt2img → ADetailer passes
- WebUI crashed during tiled upscale (VRAM exhaustion)
- Current system restarts entire job from txt2img
- All successful stages are discarded despite intermediate images being saved

### Current System Behavior

**WebUI Crash Recovery (Implemented in [PR-CORE1-D21B])**:
```
Job Stage: txt2img → ADetailer (faces) → ADetailer (hands) → Upscale
                                                    ↓
                                                 CRASH (VRAM)
                                                    ↓
                                        WebUI Auto-Restart
                                                    ↓
                               Retry ENTIRE job from txt2img
```

**What We Have:**
- ✅ Crash detection via `_is_webui_crash_exception()`
- ✅ Automatic WebUI restart via `_restart_webui_process()`
- ✅ Job retry logic in `_run_with_webui_retry()` (up to 2 attempts)
- ✅ Intermediate images saved after each stage
- ❌ NO resume-from-checkpoint logic

**What We're Missing:**
- Stage completion tracking
- Checkpoint metadata (which stages succeeded)
- Resume logic to skip completed stages
- Differentiation between full-job failures and mid-stage crashes

---

## Architectural Analysis

### Current Pipeline Flow

**File:** [src/pipeline/pipeline_runner.py](../src/pipeline/pipeline_runner.py)

```python
def run_njr_v2(njr: NormalizedJobRecord, ...) -> dict:
    stages_enabled = _detect_active_stages(njr)
    current_stage_paths = []  # Tracks images through pipeline
    
    # Stage 1: Initial generation
    if "txt2img" in stages_enabled or "img2img" in stages_enabled:
        current_stage_paths = _run_initial_generation(...)
        # ✅ Images saved to disk here
    
    # Stage 2: ADetailer
    if "adetailer" in stages_enabled:
        current_stage_paths = _run_adetailer_stage(...)
        # ✅ Images saved to disk here
    
    # Stage 3: Upscale
    if "upscale" in stages_enabled:
        current_stage_paths = _run_upscale_stage(...)
        # ✅ Images saved to disk here
    
    return {"status": "completed", "images": current_stage_paths}
```

**Key Observation:** Each stage returns `current_stage_paths` which contains the saved image paths. This is the checkpoint data we need!

### Current Retry Logic

**File:** [src/queue/single_node_runner.py:188-229](../src/queue/single_node_runner.py#L188-L229)

```python
def _run_with_webui_retry(self, job: Job) -> dict | None:
    max_attempts = _MAX_WEBUI_CRASH_RETRIES + 1  # Now 3 (2 retries)
    attempt = 1
    while attempt <= max_attempts:
        try:
            return self.run_callable(job)  # ← Runs ENTIRE pipeline
        except Exception as exc:
            crash_eligible, stage = _is_webui_crash_exception(exc)
            if not crash_eligible:
                raise
            # ... logs, records retry attempt ...
            _restart_webui_process(job.job_id)
            attempt += 1
    return None
```

**Problem:** `self.run_callable(job)` always starts from the beginning. There's no way to pass checkpoint information to skip completed stages.

---

## Proposed Solution

### Architecture Design

**Core Concept:** Store stage completion checkpoints in the Job's `execution_metadata`, then use that data to skip completed stages during retry.

### Phase 1: Checkpoint Storage (Minimal Invasive)

**Add to Job Model:**
```python
# src/queue/job_model.py
@dataclass
class ExecutionMetadata:
    # ... existing fields ...
    
    stage_checkpoints: list[StageCheckpoint] = field(default_factory=list)

@dataclass
class StageCheckpoint:
    """Records completion of a pipeline stage"""
    stage_name: str  # "txt2img", "adetailer", "upscale"
    completed_at: float  # timestamp
    output_images: list[str]  # Paths to saved images
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Checkpoint Recording:**
```python
# In pipeline_runner.py, after each stage:
def _record_stage_checkpoint(job: Job, stage: str, images: list[str]):
    checkpoint = StageCheckpoint(
        stage_name=stage,
        completed_at=time.time(),
        output_images=images,
        metadata={"image_count": len(images)}
    )
    job.execution_metadata.stage_checkpoints.append(checkpoint)
```

### Phase 2: Resume Logic

**Modify pipeline_runner.py:**
```python
def run_njr_v2(njr: NormalizedJobRecord, job: Job | None = None, ...) -> dict:
    # NEW: Check for existing checkpoints
    completed_stages = set()
    current_stage_paths = []
    
    if job and job.execution_metadata.stage_checkpoints:
        # Resume from last checkpoint
        last_checkpoint = job.execution_metadata.stage_checkpoints[-1]
        completed_stages = {cp.stage_name for cp in job.execution_metadata.stage_checkpoints}
        current_stage_paths = last_checkpoint.output_images
        
        logger.info(
            f"🔄 RESUMING from checkpoint: {last_checkpoint.stage_name} "
            f"({len(current_stage_paths)} images)"
        )
    
    stages_enabled = _detect_active_stages(njr)
    
    # Stage 1: Initial generation
    if "txt2img" in stages_enabled and "txt2img" not in completed_stages:
        current_stage_paths = _run_initial_generation(...)
        _record_stage_checkpoint(job, "txt2img", current_stage_paths)
    
    # Stage 2: ADetailer
    if "adetailer" in stages_enabled and "adetailer" not in completed_stages:
        current_stage_paths = _run_adetailer_stage(...)
        _record_stage_checkpoint(job, "adetailer", current_stage_paths)
    
    # Stage 3: Upscale
    if "upscale" in stages_enabled and "upscale" not in completed_stages:
        current_stage_paths = _run_upscale_stage(...)
        _record_stage_checkpoint(job, "upscale", current_stage_paths)
    
    return {"status": "completed", "images": current_stage_paths}
```

**Key Features:**
- ✅ Skips completed stages using `completed_stages` set
- ✅ Uses saved images from last checkpoint as input
- ✅ Preserves existing logic (no behavioral changes if no checkpoint)
- ✅ Works with existing crash detection and restart logic

### Phase 3: Retry Integration

**No changes needed!** The existing `_run_with_webui_retry()` loop will automatically benefit:

```python
# First attempt: txt2img succeeds, adetailer succeeds, upscale CRASHES
# Checkpoint stored: ["txt2img", "adetailer"]

# WebUI restarts...

# Second attempt: run_callable(job) sees checkpoints
# → Skips txt2img (already done)
# → Skips adetailer (already done)
# → Runs upscale from adetailer outputs
```

---

## Implementation Phases

### ✅ Phase 0: Foundation (COMPLETE)
- [x] VRAM clearing infrastructure (`free_vram()`)
- [x] WebUI restart capability (`_restart_webui_process()`)
- [x] Crash detection (`_is_webui_crash_exception()`)
- [x] Retry loop (`_run_with_webui_retry()`)
- [x] Increased retry limit from 1 → 2 (Dec 25, 2024)
- [x] Aggressive VRAM clearing for reprocess jobs (`unload_model=True`)

### 🔄 Phase 1: Checkpoint Storage (2-3 hours)
**PR-QUEUE-004A: Add Stage Checkpoint Data Model**

**Files to Modify:**
1. `src/queue/job_model.py`
   - Add `StageCheckpoint` dataclass
   - Add `stage_checkpoints: list[StageCheckpoint]` to `ExecutionMetadata`

2. `src/pipeline/pipeline_runner.py`
   - Add `_record_stage_checkpoint(job, stage, images)` helper
   - Call after each stage completion (3 locations: txt2img, adetailer, upscale)

**Testing:**
- Unit test: Verify checkpoint recording
- Integration test: Run job, inspect `job.execution_metadata.stage_checkpoints`
- Verify no behavioral changes (checkpoints stored but not used yet)

**Success Criteria:**
- ✅ Checkpoints recorded after each stage
- ✅ No regression in normal job execution
- ✅ Checkpoint data serializable (JSON-compatible)

---

### 🔄 Phase 2: Resume Logic (3-4 hours)
**PR-QUEUE-004B: Implement Resume-from-Checkpoint**

**Files to Modify:**
1. `src/pipeline/pipeline_runner.py`
   - Modify `run_njr_v2()` to check for existing checkpoints
   - Skip completed stages
   - Load images from last checkpoint
   - Add logging for resume events

**Testing:**
- Unit test: Mock job with checkpoints, verify stages skipped
- Integration test: Manually inject checkpoint, verify resume
- End-to-end test: Force crash, verify automatic resume after restart

**Success Criteria:**
- ✅ Jobs resume from last successful stage
- ✅ No duplicate stages executed
- ✅ Image continuity preserved (checkpoint images used as input)
- ✅ Logs clearly show resume behavior

---

### 🔄 Phase 3: Checkpoint Persistence (2 hours)
**PR-QUEUE-004C: Persist Checkpoints to Queue State**

**Files to Modify:**
1. `src/controller/app_controller.py`
   - Enhance `_save_queue_state()` to include checkpoints
   - Enhance `_load_queue_state()` to restore checkpoints

**Testing:**
- Integration test: Crash job mid-stage, restart app, verify resume
- Verify checkpoints survive app restarts

**Success Criteria:**
- ✅ Checkpoints survive app restarts
- ✅ Jobs resume correctly after full application restart

---

### 🔄 Phase 4: Validation & Edge Cases (2-3 hours)
**PR-QUEUE-004D: Checkpoint Validation & Edge Cases**

**Edge Cases to Handle:**
1. **Checkpoint Staleness**
   - What if checkpoint images are deleted?
   - Solution: Validate image paths exist before resume; if missing, restart from beginning

2. **Configuration Changes**
   - What if user changes NJR settings between retries?
   - Solution: Store NJR hash in checkpoint; invalidate if hash changes

3. **Partial Stage Completion**
   - What if ADetailer crashes mid-batch (processed 3/5 images)?
   - Solution: Phase 5 enhancement (image-level checkpoints)

4. **Stage Dependencies**
   - What if upscale needs different inputs than ADetailer outputs?
   - Current: Not an issue (linear pipeline)
   - Future: Add stage dependency validation

**Testing:**
- Test checkpoint with deleted images (should fallback gracefully)
- Test checkpoint with modified NJR (should detect and restart)
- Stress test: Force crashes at each stage boundary

**Success Criteria:**
- ✅ Graceful degradation (fallback to full restart if checkpoint invalid)
- ✅ Clear error messages for checkpoint failures
- ✅ No data corruption or partial-state bugs

---

## Technical Details

### Checkpoint Data Structure

```python
# Example checkpoint after ADetailer completion:
{
    "stage_checkpoints": [
        {
            "stage_name": "txt2img",
            "completed_at": 1735142300.123,
            "output_images": [
                "output/2024-12-25/batch_001_0000.png",
                "output/2024-12-25/batch_001_0001.png"
            ],
            "metadata": {"image_count": 2}
        },
        {
            "stage_name": "adetailer",
            "completed_at": 1735142456.789,
            "output_images": [
                "output/2024-12-25/batch_001_0000_adetailer.png",
                "output/2024-12-25/batch_001_0001_adetailer.png"
            ],
            "metadata": {
                "image_count": 2,
                "models_applied": ["face_yolov8n.pt", "hand_yolov8n.pt"]
            }
        }
    ]
}
```

### Stage Detection Logic

**Current:** `_detect_active_stages(njr)` returns set of enabled stages

**Enhanced:**
```python
def _determine_remaining_stages(njr, completed_checkpoints):
    """Calculate which stages still need to run"""
    enabled = _detect_active_stages(njr)
    completed = {cp.stage_name for cp in completed_checkpoints}
    remaining = enabled - completed
    return remaining, completed
```

### Resume Flow Diagram

```
┌─────────────────────────────────────────────────────┐
│  Job Execution Start                                │
└───────────────┬─────────────────────────────────────┘
                │
                ▼
       ┌────────────────────┐
       │ Check for          │
       │ Checkpoints?       │
       └────┬──────────┬────┘
            │          │
     NO     │          │ YES
            │          │
            ▼          ▼
    ┌───────────┐  ┌──────────────────┐
    │ Run all   │  │ Load last        │
    │ stages    │  │ checkpoint       │
    └────┬──────┘  └────┬─────────────┘
         │              │
         │              ▼
         │         ┌──────────────────┐
         │         │ Skip completed   │
         │         │ stages           │
         │         └────┬─────────────┘
         │              │
         └──────┬───────┘
                │
                ▼
       ┌────────────────────┐
       │ Run remaining      │
       │ stages             │
       └────┬───────────────┘
            │
            ▼
    ┌──────────────────┐
    │ Record new       │
    │ checkpoints      │
    └────┬─────────────┘
         │
         ▼
    ┌──────────────────┐
    │ Job Complete     │
    └──────────────────┘
```

---

## Success Metrics

### Before Implementation
- **WebUI Crash Recovery Time:** Full job restart (~5-15 minutes for large batches)
- **Wasted GPU Time:** 100% of completed stages re-executed
- **User Frustration:** High (manual intervention, lost progress)

### After Implementation
- **WebUI Crash Recovery Time:** Resume from checkpoint (~30 seconds to 2 minutes)
- **Wasted GPU Time:** 0% (no duplicate stages)
- **User Satisfaction:** High (automatic recovery, progress preserved)
- **Batch Job Reliability:** 90%+ completion rate even with resource crashes

---

## Risk Analysis

### Low Risk
- ✅ Checkpoint storage is purely additive (no breaking changes)
- ✅ Resume logic only activates on retry (no impact on normal flow)
- ✅ Fallback to full restart if checkpoint invalid

### Medium Risk
- ⚠️ Checkpoint data grows with long job chains (mitigation: limit to last 10 checkpoints)
- ⚠️ Image path assumptions (mitigation: validate paths before resume)

### Mitigations
1. **Checkpoint Validation:** Always verify image paths exist
2. **Hash Validation:** Detect NJR modifications between retries
3. **Graceful Degradation:** Log warning and restart if checkpoint unusable
4. **Size Limits:** Cap checkpoint history to prevent unbounded growth

---

## Future Enhancements (Post-v2.6)

### Phase 5: Image-Level Checkpoints
For even finer-grained recovery:
- Track per-image completion within stages
- Resume at image N instead of stage boundary
- Useful for large batches (50+ images)

### Phase 6: Multi-Stage Rollback
Allow manual rollback to any checkpoint:
- "Re-run from ADetailer" UI button
- Useful for tweaking settings mid-job

### Phase 7: Checkpoint Compression
For very large batches:
- Store image hashes instead of full paths
- Compress checkpoint metadata

---

## Related Documents

- [DEBUG HUB v2.6](DEBUG%20HUB%20v2.6.md) — Error handling patterns
- [ARCHITECTURE_v2.6](ARCHITECTURE_v2.6.md) — Pipeline architecture
- [Builder Pipeline Deep-Dive (v2.6)](Builder%20Pipeline%20Deep-Dive%20(v2.6).md) — Stage execution details
- [KNOWN_PITFALLS_QUEUE_TESTING](KNOWN_PITFALLS_QUEUE_TESTING.md) — Queue testing gotchas

---

## Approval & Next Steps

**Recommendation:** Proceed with Phase 1 (Checkpoint Storage) immediately.

**Implementation Order:**
1. ✅ Phase 0 foundation changes (COMPLETE — Dec 25, 2024)
2. PR-QUEUE-004A: Checkpoint data model + recording
3. PR-QUEUE-004B: Resume logic
4. PR-QUEUE-004C: Persistence integration
5. PR-QUEUE-004D: Edge case handling + stress testing

**Estimated Total Effort:** 9-12 hours across 4 PRs

**Expected Completion:** End of December 2024 / Early January 2025

---

**Document Version:** 1.0  
**Date:** December 25, 2024  
**Author:** GitHub Copilot (Claude Sonnet 4.5)  
**Reviewed By:** [Pending]
