# PR-MULTISTAGE-002 — Fix Stage Enablement.md

## EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK

By proceeding, I acknowledge the StableNew v2.6 Canonical Execution Contract. I understand that partial compliance, undocumented deviations, or unverifiable claims constitute failure. I will either complete the PR exactly as specified with proof, or I will stop.

---

## PR ID
**PR-MULTISTAGE-002-STAGE-EXECUTION-FIX**

---

## 1. Purpose / Intent (DECLARATIVE)

**Invariant enforced:** Pipeline stages execute through real WebUI API calls when enabled in NJR stage_chain.

**Illegal states eliminated:**
- "All stages marked disabled" due to type mismatch (StageConfig vs string comparison)
- "Stage enabled but executor not called" due to placeholder `_execute_stage()` implementation
- "Jobs complete in ~60-100ms with no images" because pipeline is a no-op

**Provably incorrect current behavior:**
1. `build_run_plan()` line 110 compares `stage_name in stage_types` but extracts types incorrectly when `stage_chain` contains `StageConfig` objects with `enabled=False` default
2. `_execute_stage()` contains TODO placeholder code that returns empty `StageOutput` without calling any executor methods
3. `STAGE_ORDER` includes "refiner" and "hires" which are not runnable stages (handled inside txt2img via flags)

---

## 2. Scope Declaration

### 2.1 Files That MUST Be Modified

| Path | Why |
|------|-----|
| run_plan.py | Fix stage enablement extraction from StageConfig objects |
| pipeline_runner.py | Wire `_execute_stage()` to real Pipeline executor methods |

### 2.2 Files That MUST NOT Be Modified (HARD FAIL)

- executor.py
- main_window_v2.py
- theme_v2.py
- main.py

### 2.3 Files That MAY Be Created

| Path | Why |
|------|-----|
| `tests/pipeline/test_stage_enablement_fix.py` | Prove stage enablement works with StageConfig objects |

---

## 3. Architectural Invariants (HARD FAIL IF VIOLATED)

- ❌ No PipelineConfig enters runner execution
- ❌ No dict-based runner return values
- ✅ PipelineRunResult is the only runner output type
- ✅ run_njr() is the only public entrypoint
- ✅ Real executor methods are called for enabled stages

---

## 4. Implementation Requirements

### 4.1 FILE: run_plan.py

**Problem:** Lines 101-115 attempt to extract stage types but fail when StageConfig.enabled is False (which it defaults to in some paths).

**Current broken logic:**
```python
if stage_chain and hasattr(stage_chain[0], "stage_type"):
    stage_types = {s.stage_type for s in stage_chain}
else:
    stage_types = set(stage_chain)
```

This extracts ALL stage_types regardless of whether `StageConfig.enabled` is True.

**Required fix:**
```python
if stage_chain and hasattr(stage_chain[0], "stage_type"):
    # Extract only ENABLED stages from StageConfig objects
    stage_types = {s.stage_type for s in stage_chain if getattr(s, "enabled", True)}
else:
    stage_types = set(stage_chain)
```

**Additional fix:** Remove non-runnable stages from `STAGE_ORDER`:
```python
# Change from:
STAGE_ORDER = ["txt2img", "refiner", "hires", "img2img", "upscale", "adetailer"]

# Change to:
STAGE_ORDER = ["txt2img", "img2img", "upscale", "adetailer"]
```

**Reason:** "refiner" and "hires" are handled inside txt2img via WebUI flags, not as separate executable stages.

### 4.2 FILE: pipeline_runner.py

**Problem:** `_execute_stage()` is a placeholder that doesn't call real executor methods.

**Required changes:**

1. **Update `__init__` to properly wrap executor:**
   - If executor is `Pipeline` type, use directly
   - If executor is `SDWebUIClient`, create `Pipeline` wrapper
   - Store as `self._pipeline` for stage execution

2. **Implement `_execute_stage()` to call real Pipeline methods:**
   - `txt2img` → `self._pipeline.run_txt2img(...)` 
   - `img2img` → `self._pipeline.run_img2img_stage(...)`
   - `upscale` → `self._pipeline.run_upscale_stage(...)`
   - `adetailer` → `self._pipeline.run_adetailer_stage(...)`

3. **Extract image paths from executor return values:**
   - Pipeline methods return dict with `"path"` or `"output_path"` keys
   - Populate `StageOutput.image_paths` from these values

**Method signatures from executor.py:**
```python
# txt2img returns dict with "path" key
run_txt2img(prompt, negative_prompt, config, output_dir, image_name, cancel_token)

# img2img returns dict with "path" key  
run_img2img_stage(input_image_path, prompt, config, output_dir, image_name, cancel_token)

# upscale returns dict with "path" key
run_upscale_stage(input_image_path, config, output_dir, image_name, cancel_token)

# adetailer returns dict with "path" key
run_adetailer_stage(input_image_path, config, output_dir, image_name, prompt, cancel_token)
```

---

## 5. Tests (NO EXCEPTIONS)

### Required test file: `tests/pipeline/test_stage_enablement_fix.py`

```python
"""Tests proving stage enablement fix works with StageConfig objects."""

import pytest
from src.pipeline.job_models_v2 import StageConfig, NormalizedJobRecord, JobStatusV2
from src.pipeline.run_plan import build_run_plan, STAGE_ORDER
from src.services.output_layout_service import OutputLayoutService


class TestStageEnablementFromStageConfig:
    """Prove stages are correctly enabled from StageConfig objects."""

    def test_enabled_stage_config_produces_enabled_stage(self):
        """StageConfig with enabled=True should produce enabled StagePlan."""
        service = OutputLayoutService("outputs")
        
        njr = NormalizedJobRecord(
            job_id="test-1",
            prompt_pack_id="pack",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="upscale", enabled=True, steps=20, cfg_scale=7.0),
            ],
            status=JobStatusV2.QUEUED,
        )
        
        layout = service.compute_layout(njr)
        run_plan = build_run_plan(njr, layout)
        
        enabled = run_plan.enabled_stages()
        enabled_names = [s.stage_name for s in enabled]
        
        assert "txt2img" in enabled_names
        assert "upscale" in enabled_names

    def test_disabled_stage_config_produces_disabled_stage(self):
        """StageConfig with enabled=False should NOT produce enabled StagePlan."""
        service = OutputLayoutService("outputs")
        
        njr = NormalizedJobRecord(
            job_id="test-2",
            prompt_pack_id="pack",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="upscale", enabled=False, steps=20, cfg_scale=7.0),
            ],
            status=JobStatusV2.QUEUED,
        )
        
        layout = service.compute_layout(njr)
        run_plan = build_run_plan(njr, layout)
        
        enabled = run_plan.enabled_stages()
        enabled_names = [s.stage_name for s in enabled]
        
        assert "txt2img" in enabled_names
        assert "upscale" not in enabled_names

    def test_stage_order_excludes_refiner_and_hires(self):
        """STAGE_ORDER should not include non-runnable stages."""
        assert "refiner" not in STAGE_ORDER
        assert "hires" not in STAGE_ORDER
        assert "txt2img" in STAGE_ORDER
        assert "upscale" in STAGE_ORDER
        assert "adetailer" in STAGE_ORDER
```

### Executor MUST run:
```bash
pytest tests/pipeline/test_stage_enablement_fix.py -v
pytest tests/pipeline/test_run_plan_output_layout.py -v
pytest tests/pipeline/test_pipeline_runner_true_ready_and_stages.py -v
```

---

## 6. Verification Commands

Executor MUST run and show output:

```powershell
# Verify no forbidden files modified
git diff --name-only | Select-String -Pattern "(executor\.py|main_window_v2\.py|theme_v2\.py|src\\main\.py)"

# Verify STAGE_ORDER change
Select-String -Path "src\pipeline\run_plan.py" -Pattern "STAGE_ORDER"

# Verify stage enablement logic includes enabled check
Select-String -Path "src\pipeline\run_plan.py" -Pattern "getattr.*enabled"

# Run all pipeline tests
pytest tests/pipeline -v
```

---

## 7. Success Criteria

1. ✅ `STAGE_ORDER` contains only runnable stages: `["txt2img", "img2img", "upscale", "adetailer"]`
2. ✅ `build_run_plan()` respects `StageConfig.enabled` flag when extracting stage types
3. ✅ `_execute_stage()` calls real Pipeline executor methods
4. ✅ Jobs with enabled stages produce actual images (not empty outputs)
5. ✅ All tests pass
6. ✅ Forbidden files unchanged

---

## 8. Diff Bundle Output (MANDATORY)

Executor MUST output:
- `git status --short`
- `git diff`
- Test outputs for all pytest commands
- Grep output confirming STAGE_ORDER and enabled check