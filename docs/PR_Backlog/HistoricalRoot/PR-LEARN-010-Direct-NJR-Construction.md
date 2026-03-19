# PR-LEARN-010: Direct NJR Construction for Learning Jobs

**Related Discovery**: D-LEARN-001  
**Architecture Version**: v2.6  
**PR Date**: 2026-01-04  
**Dependencies**: None  
**Sequence**: 1 of 3 (PR-LEARN-010 → PR-LEARN-011 → PR-LEARN-012)

---

# EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

## READ FIRST — EXECUTION CONTRACT ACKNOWLEDGEMENT

You are acting as an **Executor** for the StableNew v2.6 codebase.

By proceeding, you **explicitly acknowledge** that:

1. You have read and understand the attached document  
   **`StableNew_v2.6_Canonical_Execution_Contract.md`** *(via .github/copilot-instructions.md)*

2. You agree that this document is the **single authoritative source of truth** for:
   - Architecture
   - Execution semantics
   - NJR enforcement
   - PromptPack lifecycle
   - Queue + Runner behavior

3. This PR **MUST**:
   - Replace manual PackJobEntry construction with direct NJR building
   - Remove all bypasses of the v2.6 canonical pipeline
   - Ensure learning jobs use explicit configuration from stage cards
   - Fix prompt duplication issue

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST modify **every file listed**
- Partial implementation is **explicitly forbidden**

### 2. NJR‑Only Enforcement
You MUST:
- Build `NormalizedJobRecord` directly for learning jobs
- Set all config fields explicitly (model, VAE, sampler, seed, etc.)
- Submit via `JobService` queue (not PackJobEntry path)

### 3. Proof Is Mandatory
For **every MUST**, you MUST provide:
- Full `git diff`
- pytest commands **with captured output**
- Grep output for forbidden patterns
- Exact file + line references

### 4. Tests Are Not Optional
You MUST:
- Run all tests specified in TEST PLAN
- Show command + full output
- Fix failures before proceeding

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you acknowledge:

> "I will replace the PackJobEntry-based learning job submission with direct NJR construction,  
> remove all manual PackJobEntry building, fix prompt duplication, and ensure full configuration  
> propagation from stage cards. I will provide verifiable proof of all changes."

---

# PR METADATA

## PR ID
`PR-LEARN-010-Direct-NJR-Construction`

## Related Canonical Sections
- **Architecture v2.6 §3.2**: NJR-only execution
- **Builder Pipeline Deep-Dive §2**: Job construction
- **D-LEARN-001**: Discovery of learning tab config issues

---

# INTENT (MANDATORY)

## What This PR Does

This PR **replaces** the broken learning job submission path that manually constructed `PackJobEntry` objects with direct `NormalizedJobRecord` construction. Learning jobs will now:

1. Build NJR directly in `LearningController._build_variant_njr()`
2. Populate ALL config fields explicitly from stage card baseline config
3. Submit via `JobService` using the standard v2.6 queue path
4. Include learning metadata for provenance tracking
5. Fix prompt duplication by setting prompt once in NJR.positive_prompt

## What This PR Does NOT Do

- Does NOT modify `PromptPackNormalizedJobBuilder` (learning bypasses it now)
- Does NOT change learning UI panels or state management
- Does NOT implement LearningExecutionController (deferred to PR-LEARN-012)
- Does NOT add config validation (deferred to PR-LEARN-011)

---

# SCOPE OF CHANGE (EXPLICIT)

## Files TO BE MODIFIED (REQUIRED)

### `src/gui/controllers/learning_controller.py`
**Purpose**: Replace PackJobEntry submission with direct NJR construction

**Specific Changes**:
1. **NEW METHOD**: `_build_variant_njr()` - constructs NormalizedJobRecord from baseline config + variant overrides
2. **NEW METHOD**: `_njr_to_queue_job()` - converts NJR to Queue Job
3. **MODIFY**: `_submit_variant_job()` - remove PackJobEntry path, use NJR path
4. **REMOVE**: Manual PackJobEntry construction (lines ~229-240)
5. **REMOVE**: `app_state.job_draft.packs.append()` calls (lines ~244-246)
6. **REMOVE**: `on_add_job_to_queue_v2()` calls (lines ~249-250)

## Files TO BE DELETED (REQUIRED)
None - this PR removes code paths, not files.

## Files VERIFIED UNCHANGED
- `src/pipeline/prompt_pack_job_builder.py` - not used for learning
- `src/gui/app_state_v2.py` - PackJobEntry still used for real packs
- `src/controller/pipeline_controller.py` - submission path unchanged
- All GUI view files - no UI changes

---

# ARCHITECTURAL COMPLIANCE

- [x] NJR‑only execution path - learning jobs use direct NJR
- [x] No PipelineConfig usage in runtime - NJR contains all config
- [x] No dict‑based execution configs - NJR fields are explicit
- [x] Legacy PackJobEntry path removed from learning
- [x] Prompt set once in NJR.positive_prompt (no duplication)

---

# IMPLEMENTATION STEPS (ORDERED, NON‑OPTIONAL)

## Step 1: Add `_build_variant_njr()` Method

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: After `_get_baseline_config()` method (~line 360)

**Implementation**:
```python
def _build_variant_njr(
    self, variant: LearningVariant, experiment: LearningExperiment
) -> NormalizedJobRecord:
    """Build a NormalizedJobRecord for a learning variant.
    
    This constructs the job directly with explicit config fields,
    bypassing PackJobEntry and PromptPackNormalizedJobBuilder.
    """
    import uuid
    from datetime import datetime, timezone
    from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
    
    # Get baseline config from stage cards
    baseline = self._get_baseline_config()
    if not baseline or "txt2img" not in baseline:
        raise ValueError("Baseline config missing txt2img section")
    
    # Build variant overrides
    overrides = self._build_variant_overrides(variant, experiment)
    
    # Merge overrides into baseline
    merged = self._apply_overrides_to_config(baseline, overrides, experiment)
    
    # Extract config sections
    txt2img = merged.get("txt2img", {})
    pipeline = merged.get("pipeline", {})
    
    # Build NJR with explicit fields
    record = NormalizedJobRecord(
        job_id=str(uuid.uuid4()),
        created_ts=datetime.now(timezone.utc),
        
        # Prompts - set ONCE to avoid duplication
        positive_prompt=experiment.prompt_text or "",
        negative_prompt=experiment.negative_prompt or "",
        positive_embeddings=[],
        negative_embeddings=[],
        lora_tags=[],
        
        # Explicit config from stage cards
        model_name=txt2img.get("model") or "",
        vae_name=txt2img.get("vae") or "",
        sampler_name=txt2img.get("sampler_name") or "Euler a",
        scheduler=txt2img.get("scheduler") or "normal",
        steps=int(txt2img.get("steps", 20)),
        cfg_scale=float(txt2img.get("cfg_scale", 7.0)),
        width=int(txt2img.get("width", 512)),
        height=int(txt2img.get("height", 512)),
        clip_skip=int(txt2img.get("clip_skip", 2)),
        
        # Seed parameters
        seed=int(txt2img.get("seed", -1)),
        subseed=int(txt2img.get("subseed", -1)),
        subseed_strength=float(txt2img.get("subseed_strength", 0.0)),
        seed_resize_from_h=int(txt2img.get("seed_resize_from_h", 0)),
        seed_resize_from_w=int(txt2img.get("seed_resize_from_w", 0)),
        
        # Stage chain
        stage_chain=[StageConfig(stage_type="txt2img", enabled=True)],
        
        # Batch settings
        batch_count=1,
        batch_size=int(pipeline.get("batch_size", 1)),
        images_per_prompt=variant.planned_images,
        
        # Learning metadata for provenance
        prompt_pack_id=f"learning_{experiment.name}_{variant.param_value}",
        prompt_pack_name=f"Learning: {experiment.name} ({experiment.variable_under_test}={variant.param_value})",
        learning_metadata={
            "learning_enabled": True,
            "experiment_name": experiment.name,
            "experiment_description": experiment.description or "",
            "stage": experiment.stage,
            "variable_under_test": experiment.variable_under_test,
            "variant_value": variant.param_value,
            "variant_index": self._get_variant_index(variant),
        },
        
        # Variant tracking
        variant_index=self._get_variant_index(variant),
        variant_total=len(self.learning_state.plan),
    )
    
    return record
```

**Verification**:
- Record has all required fields populated
- No null values for model, VAE, sampler
- Prompt set once in positive_prompt
- Learning metadata included

---

## Step 2: Add `_njr_to_queue_job()` Method

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: After `_build_variant_njr()` method

**Implementation**:
```python
def _njr_to_queue_job(self, record: NormalizedJobRecord) -> Any:
    """Convert NormalizedJobRecord to Queue Job.
    
    This follows the same pattern as PipelineController._to_queue_job().
    """
    from src.queue.job_model import Job, JobPriority
    
    # Build config snapshot for history
    config_snapshot = {
        "prompt": record.positive_prompt,
        "negative_prompt": record.negative_prompt,
        "model": record.model_name,
        "vae": record.vae_name,
        "sampler": record.sampler_name,
        "scheduler": record.scheduler,
        "steps": record.steps,
        "cfg_scale": record.cfg_scale,
        "width": record.width,
        "height": record.height,
        "seed": record.seed,
        "subseed": record.subseed,
        "subseed_strength": record.subseed_strength,
        "clip_skip": record.clip_skip,
    }
    
    # Create Job
    job = Job(
        job_id=record.job_id,
        priority=JobPriority.NORMAL,
        run_mode="queue",
        source="learning",
        prompt_source="manual",
        prompt_pack_id=record.prompt_pack_id,
        config_snapshot=config_snapshot,
        learning_enabled=True,
    )
    
    # Attach NormalizedJobRecord for NJR-only execution
    job._normalized_record = record  # type: ignore[attr-defined]
    
    return job
```

**Verification**:
- Job has `_normalized_record` attached
- config_snapshot contains all values
- source="learning" for provenance

---

## Step 3: Replace `_submit_variant_job()` Implementation

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: Lines 192-260 (current `_submit_variant_job` method)

**OLD CODE TO REMOVE**:
```python
def _submit_variant_job(self, variant: LearningVariant) -> None:
    """Submit a pipeline job for a single learning variant."""
    if not self.learning_state.current_experiment or not self.pipeline_controller:
        return

    experiment = self.learning_state.current_experiment

    # Get baseline config from pipeline state (current GUI configuration)
    baseline_config = self._get_baseline_config()
    
    # Build overrides for this variant based on variable_under_test
    variant_overrides = self._build_variant_overrides(variant, experiment)
    
    # BUGFIX: Apply overrides to the correct nested config section
    config_snapshot = self._apply_overrides_to_config(baseline_config, variant_overrides, experiment)
    
    # Build learning metadata for provenance
    learning_metadata = {
        "learning_enabled": True,
        "learning_experiment_name": experiment.name,
        "learning_stage": experiment.stage,
        "learning_variable": experiment.variable_under_test,
        "learning_variant_value": variant.param_value,
        "variant_index": self._get_variant_index(variant),
    }
    
    # Build stage flags based on experiment stage
    stage_flags = self._build_stage_flags_for_experiment(experiment)

    # Submit the job via pipeline controller
    try:
        from src.gui.app_state_v2 import PackJobEntry
        
        # Build PackJobEntry with complete config
        pack_entry = PackJobEntry(
            pack_id=f"learning_{experiment.name}_{variant.param_value}",
            pack_name=f"Learning: {experiment.name} ({experiment.variable_under_test}={variant.param_value})",
            config_snapshot=config_snapshot,
            prompt_text=experiment.prompt_text or "a test prompt",
            negative_prompt_text="",
            stage_flags=stage_flags,
            learning_metadata=learning_metadata,
        )
        
        # Add to app_state job draft and trigger submission
        app_state = getattr(self.pipeline_controller, "_app_state", None)
        if app_state and hasattr(app_state, "job_draft"):
            # Add pack entry to draft
            app_state.job_draft.packs.append(pack_entry)
            
            # Trigger job submission via pipeline controller
            if hasattr(self.pipeline_controller, "on_add_job_to_queue_v2"):
                self.pipeline_controller.on_add_job_to_queue_v2()
                variant.status = "queued"
                variant_index = self._get_variant_index(variant)
                if variant_index >= 0:
                    self._update_variant_status(variant_index, "queued")
                    self._highlight_variant(variant_index, True)
            else:
                variant.status = "failed"
                variant_index = self._get_variant_index(variant)
                if variant_index >= 0:
                    self._update_variant_status(variant_index, "failed")
        else:
            variant.status = "failed"

    except Exception as exc:
        import logging
        logging.exception(f"[LearningController] Error submitting variant job: {exc}")
        variant.status = "failed"
```

**NEW CODE**:
```python
def _submit_variant_job(self, variant: LearningVariant) -> None:
    """Submit a learning job using direct NJR construction.
    
    PR-LEARN-010: Replaces PackJobEntry path with direct NJR building.
    This ensures full config propagation from stage cards and fixes
    prompt duplication issue.
    """
    if not self.learning_state.current_experiment:
        variant.status = "failed"
        return
    
    if not self.pipeline_controller:
        variant.status = "failed"
        return
    
    experiment = self.learning_state.current_experiment
    
    try:
        # Build NormalizedJobRecord with explicit config
        record = self._build_variant_njr(variant, experiment)
        
        # Convert to Queue Job
        job = self._njr_to_queue_job(record)
        
        # Set job payload to execute via runner
        job.payload = lambda j=job: self._execute_learning_job(j)
        
        # Submit via JobService
        job_service = getattr(self.pipeline_controller, "_job_service", None)
        if not job_service:
            raise RuntimeError("JobService not available on pipeline_controller")
        
        job_service.submit_job_with_run_mode(job)
        
        # Update variant status
        variant.status = "queued"
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, "queued")
            self._highlight_variant(variant_index, True)
        
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"[LearningController] Submitted learning job: "
            f"experiment={experiment.name}, variant={variant.param_value}, "
            f"model={record.model_name}, vae={record.vae_name}"
        )
        
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception(f"[LearningController] Failed to submit variant job: {exc}")
        variant.status = "failed"
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, "failed")
```

**Verification**:
- No PackJobEntry construction
- No app_state.job_draft manipulation
- No on_add_job_to_queue_v2() call
- Direct JobService submission
- Full config logging for debugging

---

## Step 4: Add `_execute_learning_job()` Method

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: After `_njr_to_queue_job()` method

**Implementation**:
```python
def _execute_learning_job(self, job: Any) -> dict[str, Any]:
    """Execute a learning job via the runner.
    
    This is called by SingleNodeJobRunner when the job is dequeued.
    It uses the attached NormalizedJobRecord to run the pipeline.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Get attached NormalizedJobRecord
    record = getattr(job, "_normalized_record", None)
    if not record:
        logger.error("[LearningController] Job missing _normalized_record")
        return {"status": "failed", "error": "Missing NormalizedJobRecord"}
    
    # Delegate to pipeline controller's runner
    if not self.pipeline_controller:
        logger.error("[LearningController] No pipeline_controller available")
        return {"status": "failed", "error": "No pipeline controller"}
    
    # Use pipeline controller's _run_job method
    if hasattr(self.pipeline_controller, "_run_job"):
        result = self.pipeline_controller._run_job(job)
        
        # Find variant and update status
        learning_metadata = record.learning_metadata or {}
        variant_value = learning_metadata.get("variant_value")
        
        for variant in self.learning_state.plan:
            if variant.param_value == variant_value:
                self._on_variant_job_completed(variant, result)
                break
        
        return result
    else:
        logger.error("[LearningController] pipeline_controller missing _run_job method")
        return {"status": "failed", "error": "No _run_job method"}
```

**Verification**:
- Uses job._normalized_record
- Delegates to pipeline_controller._run_job
- Links result back to variant
- Comprehensive error logging

---

## Step 5: Remove `_build_stage_flags_for_experiment()` Method

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: Lines ~361-378 (if present)

**Reason**: No longer needed - stage_chain in NJR replaces stage_flags

**Action**: DELETE this method entirely if it exists

---

## Step 6: Update Imports

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: Top of file

**Add**:
```python
from datetime import datetime, timezone
import uuid
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.queue.job_model import Job, JobPriority
```

**Verify**: All imports resolve, no circular dependencies

---

# TEST PLAN (MANDATORY)

## Unit Tests

### Test 1: NJR Construction
**File**: `tests/controller/test_learning_controller_njr.py` (NEW)

```python
def test_build_variant_njr_with_stage_config():
    """Verify NJR is built with explicit config from stage cards."""
    from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
    from src.gui.controllers.learning_controller import LearningController
    
    # Mock app_controller with stage cards
    class MockStageCard:
        def to_config_dict(self):
            return {
                "txt2img": {
                    "model": "test_model.safetensors",
                    "vae": "test_vae.safetensors",
                    "sampler_name": "Euler a",
                    "scheduler": "normal",
                    "steps": 25,
                    "cfg_scale": 7.5,
                    "width": 512,
                    "height": 768,
                    "seed": 42,
                    "clip_skip": 2,
                },
                "pipeline": {"batch_size": 1}
            }
    
    class MockStagePanel:
        def __init__(self):
            self.txt2img_card = MockStageCard()
    
    class MockAppController:
        def _get_stage_cards_panel(self):
            return MockStagePanel()
    
    # Create learning state
    state = LearningState()
    experiment = LearningExperiment(
        name="Test Experiment",
        prompt_text="a cat",
        stage="txt2img",
        variable_under_test="CFG Scale"
    )
    variant = LearningVariant(param_value=8.0, planned_images=1)
    state.current_experiment = experiment
    state.plan = [variant]
    
    # Create controller
    controller = LearningController(
        learning_state=state,
        app_controller=MockAppController()
    )
    
    # Build NJR
    record = controller._build_variant_njr(variant, experiment)
    
    # Verify all fields populated
    assert record.model_name == "test_model.safetensors"
    assert record.vae_name == "test_vae.safetensors"
    assert record.sampler_name == "Euler a"
    assert record.scheduler == "normal"
    assert record.steps == 25
    assert record.cfg_scale == 8.0  # Overridden by variant
    assert record.width == 512
    assert record.height == 768
    assert record.seed == 42
    assert record.subseed == -1
    assert record.subseed_strength == 0.0
    assert record.positive_prompt == "a cat"
    assert record.learning_metadata["experiment_name"] == "Test Experiment"
    assert record.learning_metadata["variant_value"] == 8.0
```

### Test 2: No Prompt Duplication
```python
def test_njr_prompt_not_duplicated():
    """Verify prompt is set once in NJR, not duplicated."""
    # ... setup similar to Test 1 ...
    
    record = controller._build_variant_njr(variant, experiment)
    
    # Prompt should appear exactly once
    assert record.positive_prompt == "a cat"
    assert record.positive_prompt.count("a cat") == 1
    
    # Config snapshot should not have duplicate prompt
    job = controller._njr_to_queue_job(record)
    assert job.config_snapshot["prompt"] == "a cat"
```

### Test 3: Job Submission
```python
def test_submit_variant_job_uses_job_service():
    """Verify submission goes through JobService, not PackJobEntry."""
    # ... setup with mock JobService ...
    
    class MockJobService:
        def __init__(self):
            self.submitted_jobs = []
        
        def submit_job_with_run_mode(self, job):
            self.submitted_jobs.append(job)
    
    # ... attach MockJobService to pipeline_controller ...
    
    controller._submit_variant_job(variant)
    
    # Verify job was submitted
    assert len(mock_job_service.submitted_jobs) == 1
    job = mock_job_service.submitted_jobs[0]
    
    # Verify NJR attached
    assert hasattr(job, "_normalized_record")
    assert job._normalized_record.model_name == "test_model.safetensors"
    
    # Verify NOT using PackJobEntry path
    assert not hasattr(job, "pack_entry")
```

## Integration Tests

### Test 4: End-to-End Learning Job
```bash
python -m pytest tests/integration/test_learning_job_submission.py::test_learning_job_full_config_propagation -v
```

**Expected**: 
- Job runs successfully
- run_metadata.json has model, VAE, sampler populated
- Prompt not duplicated

## Commands Executed
```bash
# Unit tests
python -m pytest tests/controller/test_learning_controller_njr.py -v

# Integration test
python -m pytest tests/integration/test_learning_job_submission.py -v

# Verify no PackJobEntry usage in learning
grep -n "PackJobEntry" src/gui/controllers/learning_controller.py

# Verify NJR usage
grep -n "NormalizedJobRecord" src/gui/controllers/learning_controller.py
```

---

# VERIFICATION & PROOF

## git diff
```bash
git diff src/gui/controllers/learning_controller.py
```

**Expected changes**:
- NEW: `_build_variant_njr()` method (~100 lines)
- NEW: `_njr_to_queue_job()` method (~40 lines)
- NEW: `_execute_learning_job()` method (~40 lines)
- MODIFIED: `_submit_variant_job()` method (~60 lines removed, ~40 lines added)
- REMOVED: PackJobEntry import and usage
- REMOVED: app_state.job_draft manipulation
- REMOVED: on_add_job_to_queue_v2() calls

## git status
```bash
git status --short
```

**Expected**:
```
M  src/gui/controllers/learning_controller.py
A  tests/controller/test_learning_controller_njr.py
```

## Forbidden Pattern Check
```bash
# Verify no PackJobEntry in learning controller
grep -n "PackJobEntry" src/gui/controllers/learning_controller.py
# Expected: No matches

# Verify no job_draft manipulation
grep -n "job_draft.packs.append" src/gui/controllers/learning_controller.py
# Expected: No matches

# Verify no on_add_job_to_queue_v2 calls
grep -n "on_add_job_to_queue_v2" src/gui/controllers/learning_controller.py
# Expected: No matches
```

## NJR Usage Verification
```bash
# Verify NJR construction
grep -n "NormalizedJobRecord" src/gui/controllers/learning_controller.py
# Expected: Multiple matches in _build_variant_njr

# Verify _normalized_record attachment
grep -n "_normalized_record" src/gui/controllers/learning_controller.py
# Expected: Matches in _njr_to_queue_job and _execute_learning_job
```

---

# CONFIG PROPAGATION TEST

## Manual Verification Steps

1. **Set specific config in GUI**:
   - Model: "sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE.safetensors"
   - VAE: "sdxl_vae.safetensors"
   - Sampler: "DPM++ 2M Karras"
   - Steps: 30
   - CFG: 7.0

2. **Create learning experiment**:
   - Variable: CFG Scale
   - Values: [4.0, 8.0, 12.0]
   - Prompt: "a cute cat"

3. **Submit plan**

4. **Verify run_metadata.json**:
```json
{
  "model": "sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE.safetensors",
  "vae": "sdxl_vae.safetensors",
  "sampler": "DPM++ 2M Karras",
  "steps": 30,
  "cfg_scale": 4.0,  // First variant
  "prompt": "a cute cat",  // NOT DUPLICATED
  "seed": <actual seed>,
  "subseed": -1
}
```

5. **Verify no duplication**:
   - Prompt appears exactly once
   - No "a cute cat a cute cat"

---

# ARCHITECTURAL COMPLIANCE VERIFICATION

## NJR-Only Execution
- [x] Learning jobs build NormalizedJobRecord directly
- [x] All config fields set explicitly (no nulls)
- [x] NJR attached to Job via `_normalized_record`
- [x] Runner uses NJR for execution

## No Legacy Paths
- [x] No PackJobEntry construction
- [x] No app_state.job_draft manipulation
- [x] No on_add_job_to_queue_v2() calls
- [x] No manual config dict passing

## Prompt Handling
- [x] Prompt set once in NJR.positive_prompt
- [x] No duplication in config_snapshot
- [x] No concatenation logic

---

# GOLDEN PATH CONFIRMATION

## Golden Path: GUI → Learning → Queue → Runner → History

**Test Command**:
```bash
python -m pytest tests/integration/test_learning_golden_path.py -v
```

**Expected Result**:
1. Learning controller builds NJR
2. NJR submitted to JobService queue
3. Runner dequeues job
4. Runner uses job._normalized_record
5. Pipeline executes with correct config
6. History records learning metadata
7. Variant status updates to "completed"

---

# FINAL DECLARATION

This PR:
- [x] Fully implements the declared scope
- [x] Removes all PackJobEntry usage from learning
- [x] Fixes prompt duplication issue
- [x] Ensures full config propagation from stage cards
- [x] Uses direct NJR construction
- [x] Submits via JobService standard path
- [x] Includes comprehensive tests
- [x] Provides verifiable proof

**Status**: READY FOR EXECUTION

---

# DEPENDENCIES FOR NEXT PR

**PR-LEARN-011** requires:
- This PR merged (direct NJR construction working)
- Config validation logic
- Comprehensive logging for debugging

**PR-LEARN-012** requires:
- This PR merged
- PR-LEARN-011 merged (validation working)
- LearningExecutionController implementation

---

END OF PR-LEARN-010
