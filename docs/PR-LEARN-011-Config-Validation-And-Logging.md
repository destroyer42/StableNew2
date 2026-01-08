# PR-LEARN-011: Config Validation & Logging for Learning Jobs

**Related Discovery**: D-LEARN-001  
**Architecture Version**: v2.6  
**PR Date**: 2026-01-04  
**Dependencies**: PR-LEARN-010 (must be merged first)  
**Sequence**: 2 of 3 (PR-LEARN-010 → **PR-LEARN-011** → PR-LEARN-012)

---

# EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

## READ FIRST — EXECUTION CONTRACT ACKNOWLEDGEMENT

By proceeding, you **explicitly acknowledge** that:

1. This PR **depends on PR-LEARN-010** being merged first
2. You will add comprehensive config validation to learning job submission
3. You will add detailed logging for debugging configuration issues
4. You will ensure baseline config has all required fields before NJR construction

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST add validation for ALL required config fields
- You MUST add logging at ALL critical decision points

### 2. Validation Requirements
You MUST:
- Validate baseline config before NJR construction
- Validate stage card config retrieval success
- Validate all required txt2img fields are present and non-empty
- Fail fast with clear error messages when validation fails

### 3. Logging Requirements
You MUST:
- Log baseline config retrieval (success/failure, keys present)
- Log stage card config structure (model, VAE, sampler values)
- Log variant override application
- Log NJR construction (all config fields)
- Log job submission (JobService call, job ID)

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you acknowledge:

> "I will add comprehensive config validation and logging to learning job submission,  
> ensuring that configuration errors are caught early with clear diagnostic output.  
> I will provide verifiable proof of all changes."

---

# PR METADATA

## PR ID
`PR-LEARN-011-Config-Validation-And-Logging`

## Related Canonical Sections
- **D-LEARN-001 §Issue 5**: Config snapshot structure mismatch
- **D-LEARN-001 §Fix 6**: Validate config structure

---

# INTENT (MANDATORY)

## What This PR Does

This PR adds **comprehensive validation and logging** to the learning job submission path (after PR-LEARN-010's NJR construction). It:

1. Validates baseline config structure before NJR construction
2. Validates all required txt2img fields are present and non-empty
3. Adds detailed logging at every stage of config retrieval and job building
4. Provides clear error messages when validation fails
5. Helps diagnose configuration propagation issues

## What This PR Does NOT Do

- Does NOT change NJR construction logic (that's PR-LEARN-010)
- Does NOT implement LearningExecutionController (that's PR-LEARN-012)
- Does NOT modify UI panels or state management
- Does NOT change job execution path

---

# SCOPE OF CHANGE (EXPLICIT)

## Files TO BE MODIFIED (REQUIRED)

### `src/gui/controllers/learning_controller.py`
**Purpose**: Add config validation and comprehensive logging

**Specific Changes**:
1. **NEW METHOD**: `_validate_baseline_config()` - validates config structure
2. **NEW METHOD**: `_validate_txt2img_config()` - validates required txt2img fields
3. **NEW METHOD**: `_log_baseline_config()` - logs config retrieval details
4. **MODIFY**: `_get_baseline_config()` - add logging after retrieval
5. **MODIFY**: `_build_variant_njr()` - add validation before construction, logging after
6. **MODIFY**: `_submit_variant_job()` - add logging around job submission

## Files TO BE DELETED (REQUIRED)
None

## Files VERIFIED UNCHANGED
- `src/pipeline/job_models_v2.py` - NJR structure unchanged
- `src/queue/job_model.py` - Job model unchanged
- All GUI view files - no UI changes

---

# ARCHITECTURAL COMPLIANCE

- [x] Validation prevents invalid NJR construction
- [x] Logging provides full diagnostic trail
- [x] Fail-fast behavior with clear error messages
- [x] No changes to execution path (only validation/logging)

---

# IMPLEMENTATION STEPS (ORDERED, NON‑OPTIONAL)

## Step 1: Add `_validate_baseline_config()` Method

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: After `_get_baseline_config()` method

**Implementation**:
```python
def _validate_baseline_config(self, config: dict[str, Any]) -> tuple[bool, str]:
    """Validate baseline config structure and required fields.
    
    Returns:
        (is_valid, error_message)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Check top-level structure
    if not config:
        return False, "Baseline config is empty"
    
    if "txt2img" not in config:
        return False, "Baseline config missing 'txt2img' section"
    
    if "pipeline" not in config:
        logger.warning("[LearningController] Baseline config missing 'pipeline' section, will use defaults")
    
    # Validate txt2img section
    is_valid, error = self._validate_txt2img_config(config["txt2img"])
    if not is_valid:
        return False, f"txt2img validation failed: {error}"
    
    return True, ""


def _validate_txt2img_config(self, txt2img: dict[str, Any]) -> tuple[bool, str]:
    """Validate txt2img config has all required fields.
    
    Returns:
        (is_valid, error_message)
    """
    required_fields = {
        "model": "Model name",
        "vae": "VAE name",
        "sampler_name": "Sampler name",
        "scheduler": "Scheduler name",
        "steps": "Steps count",
        "cfg_scale": "CFG scale",
        "width": "Image width",
        "height": "Image height",
    }
    
    missing = []
    empty = []
    
    for field, description in required_fields.items():
        if field not in txt2img:
            missing.append(description)
        elif not txt2img[field]:
            empty.append(description)
    
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    
    if empty:
        return False, f"Empty required fields: {', '.join(empty)}"
    
    return True, ""
```

**Verification**:
- Returns clear error messages
- Validates structure and field presence
- Distinguishes between missing and empty fields

---

## Step 2: Add `_log_baseline_config()` Method

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: After `_validate_txt2img_config()` method

**Implementation**:
```python
def _log_baseline_config(self, config: dict[str, Any], source: str = "unknown") -> None:
    """Log baseline config details for debugging.
    
    Args:
        config: The baseline config dict
        source: Where the config came from (e.g., "stage_cards", "fallback")
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[LearningController] Baseline config from {source}")
    logger.info(f"[LearningController]   Top-level keys: {list(config.keys())}")
    
    if "txt2img" in config:
        txt2img = config["txt2img"]
        logger.info(f"[LearningController]   txt2img keys: {list(txt2img.keys())}")
        logger.info(f"[LearningController]   model: {txt2img.get('model', 'MISSING')}")
        logger.info(f"[LearningController]   vae: {txt2img.get('vae', 'MISSING')}")
        logger.info(f"[LearningController]   sampler_name: {txt2img.get('sampler_name', 'MISSING')}")
        logger.info(f"[LearningController]   scheduler: {txt2img.get('scheduler', 'MISSING')}")
        logger.info(f"[LearningController]   steps: {txt2img.get('steps', 'MISSING')}")
        logger.info(f"[LearningController]   cfg_scale: {txt2img.get('cfg_scale', 'MISSING')}")
        logger.info(f"[LearningController]   seed: {txt2img.get('seed', 'MISSING')}")
    else:
        logger.error("[LearningController]   txt2img section MISSING")
    
    if "pipeline" in config:
        pipeline = config["pipeline"]
        logger.info(f"[LearningController]   pipeline keys: {list(pipeline.keys())}")
        logger.info(f"[LearningController]   batch_size: {pipeline.get('batch_size', 'MISSING')}")
    else:
        logger.warning("[LearningController]   pipeline section MISSING")
```

**Verification**:
- Logs all critical config values
- Easy to read log output
- Helps diagnose empty/missing fields

---

## Step 3: Enhance `_get_baseline_config()` with Logging

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: Modify existing `_get_baseline_config()` method

**Add logging after successful stage card retrieval**:
```python
# After: if txt2img_section.get("model") and txt2img_section.get("vae"):
    # Successfully got config from stage card
    baseline = card_config
    
    # ADD THIS LOGGING:
    self._log_baseline_config(baseline, source="stage_cards")
    
    # ... rest of subseed parameter addition ...
    
    logger.info(f"[LearningController] Successfully loaded baseline config from stage cards")
    return baseline
```

**Add logging in fallback path**:
```python
# After: baseline = { "txt2img": { ... }, "pipeline": { ... } }

# ADD THIS LOGGING:
self._log_baseline_config(baseline, source="fallback")
logger.warning(f"[LearningController] Using fallback baseline config (app_state.current_config)")

return baseline
```

---

## Step 4: Enhance `_build_variant_njr()` with Validation and Logging

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: Modify `_build_variant_njr()` method (from PR-LEARN-010)

**Add validation at start**:
```python
def _build_variant_njr(self, variant: LearningVariant, experiment: LearningExperiment) -> NormalizedJobRecord:
    """Build a NormalizedJobRecord for a learning variant."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Get baseline config from stage cards
    baseline = self._get_baseline_config()
    
    # VALIDATE CONFIG:
    is_valid, error_msg = self._validate_baseline_config(baseline)
    if not is_valid:
        logger.error(f"[LearningController] Baseline config validation failed: {error_msg}")
        raise ValueError(f"Invalid baseline config: {error_msg}")
    
    # Build variant overrides
    overrides = self._build_variant_overrides(variant, experiment)
    logger.info(f"[LearningController] Variant overrides: {overrides}")
    
    # Merge overrides into baseline
    merged = self._apply_overrides_to_config(baseline, overrides, experiment)
    
    # Extract config sections
    txt2img = merged.get("txt2img", {})
    pipeline = merged.get("pipeline", {})
    
    # LOG FINAL CONFIG VALUES:
    logger.info(f"[LearningController] Building NJR for variant {variant.param_value}")
    logger.info(f"[LearningController]   model: {txt2img.get('model')}")
    logger.info(f"[LearningController]   vae: {txt2img.get('vae')}")
    logger.info(f"[LearningController]   sampler: {txt2img.get('sampler_name')}")
    logger.info(f"[LearningController]   scheduler: {txt2img.get('scheduler')}")
    logger.info(f"[LearningController]   steps: {txt2img.get('steps')}")
    logger.info(f"[LearningController]   cfg_scale: {txt2img.get('cfg_scale')}")
    logger.info(f"[LearningController]   prompt: {experiment.prompt_text}")
    
    # ... rest of NJR construction ...
    
    logger.info(f"[LearningController] Successfully built NJR: job_id={record.job_id}")
    return record
```

---

## Step 5: Enhance `_submit_variant_job()` with Logging

**File**: `src/gui/controllers/learning_controller.py`  
**Location**: Modify `_submit_variant_job()` method (from PR-LEARN-010)

**Add logging around job submission**:
```python
def _submit_variant_job(self, variant: LearningVariant) -> None:
    """Submit a learning job using direct NJR construction."""
    import logging
    logger = logging.getLogger(__name__)
    
    if not self.learning_state.current_experiment:
        logger.error("[LearningController] Cannot submit: no current experiment")
        variant.status = "failed"
        return
    
    if not self.pipeline_controller:
        logger.error("[LearningController] Cannot submit: no pipeline controller")
        variant.status = "failed"
        return
    
    experiment = self.learning_state.current_experiment
    logger.info(f"[LearningController] Submitting variant: experiment={experiment.name}, value={variant.param_value}")
    
    try:
        # Build NormalizedJobRecord with explicit config
        logger.debug("[LearningController] Building NJR...")
        record = self._build_variant_njr(variant, experiment)
        logger.debug(f"[LearningController] NJR built: job_id={record.job_id}")
        
        # Convert to Queue Job
        logger.debug("[LearningController] Converting NJR to Queue Job...")
        job = self._njr_to_queue_job(record)
        logger.debug(f"[LearningController] Queue Job created: job_id={job.job_id}")
        
        # Set job payload
        job.payload = lambda j=job: self._execute_learning_job(j)
        
        # Submit via JobService
        job_service = getattr(self.pipeline_controller, "_job_service", None)
        if not job_service:
            logger.error("[LearningController] JobService not available on pipeline_controller")
            raise RuntimeError("JobService not available on pipeline_controller")
        
        logger.info(f"[LearningController] Submitting job to JobService: job_id={job.job_id}")
        job_service.submit_job_with_run_mode(job)
        logger.info(f"[LearningController] Job submitted successfully: job_id={job.job_id}")
        
        # Update variant status
        variant.status = "queued"
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, "queued")
            self._highlight_variant(variant_index, True)
        
        logger.info(
            f"[LearningController] ✓ Submitted learning job: "
            f"experiment={experiment.name}, variant={variant.param_value}, "
            f"job_id={record.job_id}, model={record.model_name}, vae={record.vae_name}"
        )
        
    except Exception as exc:
        logger.exception(f"[LearningController] Failed to submit variant job: {exc}")
        variant.status = "failed"
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, "failed")
```

---

# TEST PLAN (MANDATORY)

## Unit Tests

### Test 1: Config Validation - Valid Config
**File**: `tests/controller/test_learning_controller_validation.py` (NEW)

```python
def test_validate_baseline_config_success():
    """Verify validation passes for complete config."""
    from src.gui.learning_state import LearningState
    from src.gui.controllers.learning_controller import LearningController
    
    config = {
        "txt2img": {
            "model": "test_model.safetensors",
            "vae": "test_vae.safetensors",
            "sampler_name": "Euler a",
            "scheduler": "normal",
            "steps": 25,
            "cfg_scale": 7.5,
            "width": 512,
            "height": 768,
        },
        "pipeline": {"batch_size": 1}
    }
    
    controller = LearningController(learning_state=LearningState())
    is_valid, error = controller._validate_baseline_config(config)
    
    assert is_valid is True
    assert error == ""
```

### Test 2: Config Validation - Missing Fields
```python
def test_validate_baseline_config_missing_model():
    """Verify validation fails when model is missing."""
    config = {
        "txt2img": {
            "vae": "test_vae.safetensors",
            "sampler_name": "Euler a",
            # model missing
        },
        "pipeline": {}
    }
    
    controller = LearningController(learning_state=LearningState())
    is_valid, error = controller._validate_baseline_config(config)
    
    assert is_valid is False
    assert "Model name" in error
```

### Test 3: Config Validation - Empty Fields
```python
def test_validate_baseline_config_empty_vae():
    """Verify validation fails when VAE is empty."""
    config = {
        "txt2img": {
            "model": "test_model.safetensors",
            "vae": "",  # Empty
            "sampler_name": "Euler a",
            "scheduler": "normal",
            "steps": 25,
            "cfg_scale": 7.5,
            "width": 512,
            "height": 768,
        },
        "pipeline": {}
    }
    
    controller = LearningController(learning_state=LearningState())
    is_valid, error = controller._validate_baseline_config(config)
    
    assert is_valid is False
    assert "VAE name" in error
```

### Test 4: Logging Output Verification
```python
def test_log_baseline_config_output(caplog):
    """Verify logging produces expected output."""
    import logging
    
    config = {
        "txt2img": {
            "model": "test_model.safetensors",
            "vae": "test_vae.safetensors",
            "sampler_name": "Euler a",
        },
        "pipeline": {"batch_size": 1}
    }
    
    controller = LearningController(learning_state=LearningState())
    
    with caplog.at_level(logging.INFO):
        controller._log_baseline_config(config, source="test")
    
    # Verify log messages
    assert "Baseline config from test" in caplog.text
    assert "model: test_model.safetensors" in caplog.text
    assert "vae: test_vae.safetensors" in caplog.text
    assert "sampler_name: Euler a" in caplog.text
```

## Integration Tests

### Test 5: NJR Construction with Invalid Config
```python
def test_build_variant_njr_fails_with_invalid_config():
    """Verify NJR construction raises error with invalid config."""
    from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
    from src.gui.controllers.learning_controller import LearningController
    
    # Mock app_controller that returns incomplete config
    class MockAppController:
        def _get_stage_cards_panel(self):
            class MockCard:
                def to_config_dict(self):
                    return {"txt2img": {"model": "", "vae": ""}}  # Empty values
            class MockPanel:
                txt2img_card = MockCard()
            return MockPanel()
    
    state = LearningState()
    experiment = LearningExperiment(name="Test", prompt_text="test", stage="txt2img", variable_under_test="CFG")
    variant = LearningVariant(param_value=8.0, planned_images=1)
    state.current_experiment = experiment
    state.plan = [variant]
    
    controller = LearningController(learning_state=state, app_controller=MockAppController())
    
    # Should raise ValueError with clear message
    with pytest.raises(ValueError, match="Invalid baseline config"):
        controller._build_variant_njr(variant, experiment)
```

## Commands Executed
```bash
# Unit tests
python -m pytest tests/controller/test_learning_controller_validation.py -v

# Check logging output
python -m pytest tests/controller/test_learning_controller_validation.py::test_log_baseline_config_output -v -s

# Integration test
python -m pytest tests/controller/test_learning_controller_validation.py::test_build_variant_njr_fails_with_invalid_config -v
```

---

# VERIFICATION & PROOF

## git diff
```bash
git diff src/gui/controllers/learning_controller.py
```

**Expected changes**:
- NEW: `_validate_baseline_config()` method (~30 lines)
- NEW: `_validate_txt2img_config()` method (~30 lines)
- NEW: `_log_baseline_config()` method (~30 lines)
- MODIFIED: `_get_baseline_config()` - added logging (~4 lines added)
- MODIFIED: `_build_variant_njr()` - added validation and logging (~15 lines added)
- MODIFIED: `_submit_variant_job()` - added comprehensive logging (~10 lines added)

## Validation Check
```bash
# Verify validation methods exist
grep -n "_validate_baseline_config" src/gui/controllers/learning_controller.py
grep -n "_validate_txt2img_config" src/gui/controllers/learning_controller.py

# Verify logging methods exist
grep -n "_log_baseline_config" src/gui/controllers/learning_controller.py

# Count logging statements
grep -c "logger.info\|logger.error\|logger.warning\|logger.debug" src/gui/controllers/learning_controller.py
# Expected: Significant increase (20+ new logging statements)
```

---

# LOGGING OUTPUT EXAMPLE

## Expected Log Output for Successful Job Submission

```
INFO [LearningController] Got stage card config: keys=['txt2img', 'pipeline']
INFO [LearningController] txt2img section keys: ['model', 'vae', 'sampler_name', 'scheduler', 'steps', 'cfg_scale', 'width', 'height', 'seed', 'clip_skip']
INFO [LearningController] txt2img model=sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE.safetensors, vae=sdxl_vae.safetensors
INFO [LearningController] Successfully loaded baseline config from stage cards
INFO [LearningController] Baseline config from stage_cards
INFO [LearningController]   Top-level keys: ['txt2img', 'pipeline']
INFO [LearningController]   txt2img keys: ['model', 'vae', 'sampler_name', 'scheduler', 'steps', 'cfg_scale', 'width', 'height', 'seed', 'subseed', 'subseed_strength', 'seed_resize_from_h', 'seed_resize_from_w', 'clip_skip']
INFO [LearningController]   model: sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE.safetensors
INFO [LearningController]   vae: sdxl_vae.safetensors
INFO [LearningController]   sampler_name: Euler a
INFO [LearningController]   scheduler: normal
INFO [LearningController]   steps: 25
INFO [LearningController]   cfg_scale: 7.5
INFO [LearningController]   seed: 42
INFO [LearningController]   pipeline keys: ['batch_size', 'txt2img_enabled']
INFO [LearningController]   batch_size: 1
INFO [LearningController] Submitting variant: experiment=Test Experiment, value=8.0
DEBUG [LearningController] Building NJR...
INFO [LearningController] Variant overrides: {'cfg_scale': 8.0}
INFO [LearningController] Building NJR for variant 8.0
INFO [LearningController]   model: sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE.safetensors
INFO [LearningController]   vae: sdxl_vae.safetensors
INFO [LearningController]   sampler: Euler a
INFO [LearningController]   scheduler: normal
INFO [LearningController]   steps: 25
INFO [LearningController]   cfg_scale: 8.0
INFO [LearningController]   prompt: a cute cat
INFO [LearningController] Successfully built NJR: job_id=abc-123-def
DEBUG [LearningController] NJR built: job_id=abc-123-def
DEBUG [LearningController] Converting NJR to Queue Job...
DEBUG [LearningController] Queue Job created: job_id=abc-123-def
INFO [LearningController] Submitting job to JobService: job_id=abc-123-def
INFO [LearningController] Job submitted successfully: job_id=abc-123-def
INFO [LearningController] ✓ Submitted learning job: experiment=Test Experiment, variant=8.0, job_id=abc-123-def, model=sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE.safetensors, vae=sdxl_vae.safetensors
```

## Expected Log Output for Failed Validation

```
INFO [LearningController] Got stage card config: keys=['txt2img']
INFO [LearningController] txt2img section keys: ['model', 'vae']
WARNING [LearningController] Stage card has no model/VAE, falling back
WARNING [LearningController] Using fallback baseline config
ERROR [LearningController] Baseline config validation failed: Empty required fields: Model name, VAE name, Sampler name, Scheduler name
ERROR [LearningController] Failed to submit variant job: Invalid baseline config: Empty required fields: Model name, VAE name, Sampler name, Scheduler name
```

---

# FINAL DECLARATION

This PR:
- [x] Adds comprehensive config validation
- [x] Adds detailed logging at all critical points
- [x] Provides clear error messages for validation failures
- [x] Helps diagnose configuration issues
- [x] Includes comprehensive tests
- [x] Depends on PR-LEARN-010 being merged first

**Status**: READY FOR EXECUTION (after PR-LEARN-010)

---

# DEPENDENCIES

**Requires**: PR-LEARN-010 merged (NJR construction methods must exist)

**Enables**: PR-LEARN-012 (execution controller can rely on validated configs)

---

END OF PR-LEARN-011
