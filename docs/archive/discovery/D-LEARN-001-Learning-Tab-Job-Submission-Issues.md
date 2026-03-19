# D-LEARN-001: Learning Tab Job Submission & Configuration Issues

**Discovery Date**: 2026-01-04  
**Status**: DISCOVERY COMPLETE  
**Priority**: CRITICAL  
**Architecture Version**: v2.6

---

## Executive Summary

The Learning tab's job submission pathway has multiple critical configuration propagation failures causing submitted jobs to use empty/null values for model, VAE, sampler, scheduler, and seed parameters. Additionally, prompts are being duplicated. While jobs execute without crashing (after previous subseed fixes), they use incorrect or default configurations rather than the user's intended stage card settings.

**Root Cause**: Learning controller uses an outdated job submission path that bypasses the canonical v2.6 PromptPack→Builder→NJR→Queue pipeline, instead manually constructing PackJobEntry objects with incomplete baseline configs.

---

## Evidence

### Symptom 1: Empty Configuration Values in run_metadata.json
```json
{
  "model": "",
  "sampler": null,
  "vae": "",
  "scheduler": "",
  "seed": null
}
```

### Symptom 2: Configuration Values Present in Job Manifest
The txt2img manifest shows real values WERE used:
```json
{
  "model": "sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE.safetensors",
  "vae": "sdxl_vae.safetensors",
  "sampler_name": "Euler a"
}
```

**Analysis**: The config is being retrieved somewhere downstream (likely WebUI defaults or residual state), but NOT from the learning controller's baseline config retrieval.

### Symptom 3: Duplicated Prompt
```json
{
  "prompt": "a test prompt a test prompt"
}
```

**Analysis**: Prompt is likely being concatenated or duplicated during PackJobEntry construction or prompt resolution.

---

## Architectural Analysis

### Current Flow (BROKEN)

```
Learning Controller
  └─> _get_baseline_config()
      ├─> app_controller._get_stage_cards_panel()  ✅ (Fixed recently)
      │   └─> Returns stage card config dict
      │
      └─> Returns baseline config with txt2img, pipeline sections
  
  └─> _submit_variant_job()
      ├─> _build_variant_overrides()  # Builds CFG/steps/sampler overrides
      ├─> _apply_overrides_to_config()  # Merges overrides into baseline
      │
      └─> Manually constructs PackJobEntry ❌ PROBLEM
          ├─> pack_id: f"learning_{experiment}_{value}"
          ├─> config_snapshot: baseline + overrides
          ├─> prompt_text: experiment.prompt_text
          │
          └─> Adds to app_state.job_draft.packs
              └─> Calls pipeline_controller.on_add_job_to_queue_v2()
                  └─> ???  # Unclear how this processes PackJobEntry
```

### Expected v2.6 Flow (MISSING)

```
Learning Controller
  └─> Submit via LearningExecutionController ❌ NOT USED
      └─> Or directly via PipelineController.start_pipeline_v2()
          └─> Calls PromptPackNormalizedJobBuilder
              ├─> Resolves pack entry config
              ├─> Calls JobBuilderV2.build_jobs()
              └─> Returns NormalizedJobRecord[]
                  └─> Converts to Queue Jobs
                      └─> Submits via JobService
```

---

## Issues Identified

### Issue 1: Baseline Config Retrieval (PARTIALLY FIXED)
**File**: `src/gui/controllers/learning_controller.py:264-360`

**Problem**: 
- Recently fixed to use `app_controller._get_stage_cards_panel()`
- Now properly retrieves stage card config
- **BUT** the config dict structure returned may not match what downstream expects

**Status**: NEEDS VALIDATION - config retrieval works but downstream usage unclear

---

### Issue 2: Manual PackJobEntry Construction
**File**: `src/gui/controllers/learning_controller.py:229-240`

**Problem**:
```python
pack_entry = PackJobEntry(
    pack_id=f"learning_{experiment.name}_{variant.param_value}",
    pack_name=f"Learning: {experiment.name} ...",
    config_snapshot=config_snapshot,  # ❌ Manually built dict
    prompt_text=experiment.prompt_text or "a test prompt",  # ❌ Direct string
    negative_prompt_text="",  # ❌ Empty string
    stage_flags=stage_flags,
    learning_metadata=learning_metadata,
)
```

**Issues**:
1. `PackJobEntry` is designed for **ACTUAL prompt pack files**, not ad-hoc configs
2. `config_snapshot` dict format may not align with builder expectations
3. No guarantee `PromptPackNormalizedJobBuilder` handles learning-originated PackJobEntry correctly
4. Bypasses standard config resolution, prompt resolution, and builder validation

**Architecture Violation**: Learning should NOT construct PackJobEntry manually. It should either:
- Use a dedicated learning job builder, OR
- Submit via standard pipeline with overrides

---

### Issue 3: Unclear Job Submission Path
**File**: `src/gui/controllers/learning_controller.py:244-250`

**Problem**:
```python
app_state.job_draft.packs.append(pack_entry)

if hasattr(self.pipeline_controller, "on_add_job_to_queue_v2"):
    self.pipeline_controller.on_add_job_to_queue_v2()
```

**Issues**:
1. `on_add_job_to_queue_v2()` is NOT a standard v2.6 submission entrypoint
2. Method may be legacy/experimental
3. Unclear how it processes PackJobEntry from job_draft
4. No proof this path uses `PromptPackNormalizedJobBuilder` correctly

**Grep Results**: 
- `on_add_job_to_queue_v2` appears in AppController and PipelineController
- Used for GUI button handlers, not programmatic submission
- May not validate/process learning metadata properly

---

### Issue 4: Prompt Duplication
**File**: `src/gui/controllers/learning_controller.py:234`

**Problem**:
```python
prompt_text=experiment.prompt_text or "a test prompt",
```

**Analysis**:
- Prompt is set in PackJobEntry
- Then processed by `PromptPackNormalizedJobBuilder` 
- Prompt resolution may concatenate or duplicate if:
  - `config_snapshot` ALSO contains prompt
  - Builder applies prompt twice (from entry + from config)
  - Global positive prompt is being applied redundantly

**Evidence**: Output shows `"a test prompt a test prompt"` - exact duplication suggests concatenation.

---

### Issue 5: Config Snapshot Structure Mismatch
**File**: `src/gui/controllers/learning_controller.py:207-215`

**Problem**:
```python
baseline_config = self._get_baseline_config()  # Returns nested dict
variant_overrides = self._build_variant_overrides(variant, experiment)
config_snapshot = self._apply_overrides_to_config(baseline_config, variant_overrides, experiment)
```

**Baseline config structure**:
```python
{
  "txt2img": { "model": "...", "vae": "...", ... },
  "pipeline": { "batch_size": 1, ... },
  "upscale": { ... }
}
```

**PackJobEntry expectations** (from PromptPackNormalizedJobBuilder):
- Expects config from actual pack file JSON structure
- May expect flat config or different nesting
- `PromptPackNormalizedJobBuilder._merge_configs()` may not handle learning's structure

**Evidence**: Empty values in run_metadata suggest config is not being read correctly from PackJobEntry.

---

### Issue 6: No LearningExecutionController Usage
**File**: `src/gui/controllers/learning_controller.py:48-50`

**Problem**:
```python
def __init__(self, ..., execution_controller: Any | None = None):
    ...
    self.execution_controller = execution_controller  # PR-LEARN-002
```

**Analysis**:
- `execution_controller` is passed but NEVER USED in `run_plan()` or `_submit_variant_job()`
- PR-LEARN-002 introduced this for learning job execution
- Controller bypasses it completely, using manual PackJobEntry path instead

**Architecture Intent**: LearningExecutionController should handle:
- Building learning job configs
- Submitting via proper v2.6 pipeline
- Tracking learning job completion
- Linking results to variants

**Current State**: Dead code path, not wired up.

---

## Root Cause Summary

1. **Baseline config works** but returns dict that doesn't align with PackJobEntry processing
2. **Manual PackJobEntry construction** bypasses builder validation and resolution
3. **Unclear submission path** via `on_add_job_to_queue_v2()` may not use PromptPackNormalizedJobBuilder correctly
4. **Prompt duplication** from double-setting (PackJobEntry + config_snapshot)
5. **Config structure mismatch** between learning's nested dict and builder expectations
6. **LearningExecutionController unused** - proper execution path not wired

---

## Impact Assessment

| Issue | Severity | Impact |
|-------|----------|--------|
| Empty model/VAE/sampler | CRITICAL | Jobs use wrong models, produce unpredictable results |
| Prompt duplication | HIGH | Jobs run with concatenated prompts, wrong outputs |
| Bypassed builder pipeline | HIGH | No validation, resolution, or proper NJR construction |
| Unused execution controller | MEDIUM | Architecture drift, incomplete PR-LEARN-002 implementation |
| Config structure mismatch | HIGH | Builder may ignore or misinterpret learning configs |

**Overall**: Learning tab produces UNRELIABLE results. All experiments are invalid due to configuration issues.

---

## Downstream Effects

### run_metadata.json
- ✅ Contains learning metadata (experiment name, variable, value)
- ❌ Contains empty/null config values (model, VAE, sampler, scheduler, seed)
- ⚠️ Contains duplicated prompt

### Job Manifests
- ✅ Shows real model/VAE were used (from WebUI defaults or residual state)
- ⚠️ Config may not match user's stage cards
- ❌ No guarantee configuration consistency across variants

### Learning Results
- ❌ Cannot compare variants reliably if base config differs
- ❌ Ratings may be based on wrong configurations
- ❌ Recommendations will be invalid

---

## Required Fixes

### Fix 1: Use Standard v2.6 Submission Path (**REQUIRED**)
**Why**: Learning must use the same PromptPack→Builder→NJR→Queue pipeline as all other jobs

**Options**:
1. **Option A**: Wire up LearningExecutionController to build NJRs
   - Create `LearningJobBuilder` that wraps `JobBuilderV2`
   - Build `ConfigVariantPlanV2` from learning variants
   - Submit via `PipelineController.start_pipeline_v2()`

2. **Option B**: Create synthetic prompt pack files for learning experiments
   - Generate pack file with baseline config
   - Submit via standard `PromptPackNormalizedJobBuilder`
   - Add learning metadata as pack annotations

3. **Option C**: Use direct NJR construction (cleanest)
   - Build `NormalizedJobRecord` directly in learning controller
   - Set all fields explicitly (model, VAE, sampler, seed, etc.)
   - Submit via `JobService` queue
   - Bypass PackJobEntry entirely

**Recommendation**: Option C - direct NJR construction
- Cleanest separation of concerns
- No fake pack files
- Full control over job configuration
- Aligns with v2.6 "NJR is the single job runtime"

---

### Fix 2: Remove Manual PackJobEntry Construction (**REQUIRED**)
**Why**: PackJobEntry is for pack files, not programmatic jobs

**Changes**:
- Remove `PackJobEntry` construction in `_submit_variant_job()`
- Remove `app_state.job_draft.packs.append()` path
- Remove `on_add_job_to_queue_v2()` call

---

### Fix 3: Direct NJR Construction (**REQUIRED**)
**Why**: Learning needs explicit config control, not pack-based config merging

**Implementation**:
```python
def _build_variant_njr(self, variant: LearningVariant, experiment: LearningExperiment) -> NormalizedJobRecord:
    baseline = self._get_baseline_config()  # Returns nested dict with txt2img, pipeline, etc.
    overrides = self._build_variant_overrides(variant, experiment)
    merged = self._apply_overrides_to_config(baseline, overrides, experiment)
    
    txt2img = merged.get("txt2img", {})
    pipeline = merged.get("pipeline", {})
    
    record = NormalizedJobRecord(
        job_id=str(uuid.uuid4()),
        created_ts=datetime.utcnow(),
        positive_prompt=experiment.prompt_text,
        negative_prompt=experiment.negative_prompt or "",
        
        # Explicit config from stage cards
        model_name=txt2img.get("model"),
        vae_name=txt2img.get("vae"),
        sampler_name=txt2img.get("sampler_name"),
        scheduler=txt2img.get("scheduler"),
        steps=int(txt2img.get("steps", 20)),
        cfg_scale=float(txt2img.get("cfg_scale", 7.0)),
        width=int(txt2img.get("width", 512)),
        height=int(txt2img.get("height", 512)),
        seed=int(txt2img.get("seed", -1)),
        subseed=int(txt2img.get("subseed", -1)),
        subseed_strength=float(txt2img.get("subseed_strength", 0.0)),
        clip_skip=int(txt2img.get("clip_skip", 2)),
        
        # Learning metadata
        prompt_pack_id=f"learning_{experiment.name}_{variant.param_value}",
        prompt_pack_name=f"Learning: {experiment.name}",
        learning_metadata={
            "experiment_name": experiment.name,
            "variable": experiment.variable_under_test,
            "value": variant.param_value,
        },
        
        # Stage chain
        stage_chain=[StageConfig(stage_type="txt2img", enabled=True)],
        
        # Batch settings
        batch_count=1,
        batch_size=pipeline.get("batch_size", 1),
        images_per_prompt=variant.planned_images,
    )
    
    return record
```

---

### Fix 4: Submit via JobService (**REQUIRED**)
**Why**: Standard v2.6 queue submission path

**Implementation**:
```python
def _submit_variant_job(self, variant: LearningVariant) -> None:
    if not self.learning_state.current_experiment:
        return
    
    experiment = self.learning_state.current_experiment
    record = self._build_variant_njr(variant, experiment)
    
    # Convert to Queue Job
    job = self._njr_to_queue_job(record)
    job.payload = lambda: self._execute_learning_job(record)
    
    # Submit via JobService
    if self.pipeline_controller and hasattr(self.pipeline_controller, "_job_service"):
        self.pipeline_controller._job_service.submit_job_with_run_mode(job)
        variant.status = "queued"
    else:
        variant.status = "failed"
```

---

### Fix 5: Fix Prompt Duplication (**REQUIRED**)
**Why**: Prompt should be set once in NJR.positive_prompt, not duplicated

**Changes**:
- Set `positive_prompt` directly from `experiment.prompt_text`
- Do NOT set prompt in `config_snapshot`
- Remove any prompt concatenation logic

---

### Fix 6: Validate Config Structure (**REQUIRED**)
**Why**: Ensure baseline config has all required fields

**Implementation**:
```python
def _validate_baseline_config(self, config: dict[str, Any]) -> bool:
    required_txt2img = ["model", "vae", "sampler_name", "scheduler", "steps", "cfg_scale"]
    txt2img = config.get("txt2img", {})
    
    for field in required_txt2img:
        if not txt2img.get(field):
            logger.error(f"[LearningController] Missing required field: txt2img.{field}")
            return False
    
    return True
```

---

## Testing Requirements

### Test 1: Config Propagation
1. Set specific model, VAE, sampler in txt2img stage card
2. Create learning experiment
3. Submit variant
4. Verify `run_metadata.json` contains exact model/VAE/sampler from stage card

### Test 2: Prompt Handling
1. Set prompt: "a cute cat"
2. Create learning experiment
3. Submit variant
4. Verify run_metadata and manifest show: `"prompt": "a cute cat"` (not duplicated)

### Test 3: Variant Overrides
1. Create CFG Scale experiment with values [4.0, 8.0, 12.0]
2. Submit all variants
3. Verify each run_metadata has correct cfg_scale value

### Test 4: NJR Structure
1. Submit learning job
2. Inspect NJR before queue submission
3. Verify all fields populated (no nulls)

---

## File Inventory

### Files Requiring Changes

| File | Lines | Issues |
|------|-------|--------|
| `src/gui/controllers/learning_controller.py` | 190-260 | Manual PackJobEntry, unclear submission path |
| `src/gui/controllers/learning_controller.py` | 264-360 | Baseline config structure (needs validation) |
| `src/gui/controllers/learning_controller.py` | 375-453 | Override building and merging logic |

### Files to Investigate

| File | Purpose |
|------|---------|
| `src/controller/pipeline_controller.py` | `on_add_job_to_queue_v2()` method - what does it do? |
| `src/pipeline/prompt_pack_job_builder.py` | How does it handle learning PackJobEntry? |
| `src/learning/execution_controller.py` | Is this implemented? Should it be used? |

### Related Architecture Docs

- `ARCHITECTURE_v2.6.md` - NJR-only enforcement
- `Builder Pipeline Deep-Dive (v2.6).md` - Job construction pipeline
- `PromptPack Lifecycle v2.6.md` - Pack-based job building
- `PR-LEARN-002` - LearningExecutionController introduction (incomplete?)

---

## Recommended PR Sequence

### PR-LEARN-010: Direct NJR Construction for Learning Jobs
**Scope**: Replace PackJobEntry path with direct NJR building
**Files**: `src/gui/controllers/learning_controller.py`
**Tests**: Config propagation, prompt handling

### PR-LEARN-011: Config Validation & Logging
**Scope**: Add validation for baseline config, comprehensive logging
**Files**: `src/gui/controllers/learning_controller.py`
**Tests**: Config validation, error handling

### PR-LEARN-012: Learning Job Execution Integration
**Scope**: Wire up proper job execution, completion callbacks
**Files**: `src/gui/controllers/learning_controller.py`, `src/learning/execution_controller.py`
**Tests**: Job completion, variant status updates

---

## Open Questions

1. **Is `LearningExecutionController` implemented?** If so, why is it unused?
2. **What does `on_add_job_to_queue_v2()` actually do?** Does it use PromptPackNormalizedJobBuilder?
3. **Should learning jobs use pack files or direct NJR?** Pack files add indirection but provide audit trail.
4. **How should learning metadata flow to history?** Need to link completed jobs back to variants.

---

## Conclusion

Learning tab's job submission is **architecturally broken**. It bypasses v2.6's canonical PromptPack→Builder→NJR→Queue pipeline, manually constructs PackJobEntry objects, and uses an unclear submission path that produces jobs with empty/null configuration values.

**Required Action**: Full refactor to use direct NJR construction, removing PackJobEntry path entirely, and properly integrating with JobService queue submission.

**Priority**: CRITICAL - learning tab is non-functional for reliable experimentation.

---

**Next Steps**: Produce PR-LEARN-010, PR-LEARN-011, PR-LEARN-012 following v2.7.1 template.
