User: Codex and myself have identified some issues with the current run pipeline. See the below issues, and plan out a comprehensive PR spec to address these issues, following this format/template:
# OpenSpec: PR-0114 – Pipeline Run Controls

## Context
Why this exists.

## Non-Goals
- Explicit exclusions

## Invariants
- Must always be true

## Allowed Files
- src/controller/app_controller.py
- src/services/job_service.py
- tests/controller/test_run_pipeline.py

## Do Not Touch
- src/services/queue_service.py

## Interfaces
- Method signatures
- DTOs
- Error behavior

## Implementation Steps (Order Matters)
1. ...
2. ...

## Acceptance Criteria
1. Given X, when Y, then Z
2. ...

## Test Plan
- pytest tests/controller/test_run_pipeline.py
- Expected failures before change
- Expected pass after change

## Rollback
- git revert <hash>
Order + explicit lists matter more than prose quality.

_____________________________________
List of issues/background, see terminal background for more info/context:
"The txt2img stage isn’t actually interrupted at ~2/3. The 62% (21/34) line is where the refiner model loads (Reusing loaded model ... to load babesByStableYogiPony_xlV4), which pauses sampling while weights/VAE load. It then resumes and completes (34/34 and txt2img completed successfully). The real failures happen after txt2img.

Issues

adetailer stage failed: name 'apply_global' is not defined triggers after each ADetailer img2img completes; this is a hard NameError that zeroes ADetailer output and cascades to failure.
Pipeline state mismatch: PipelineRunResult created with success=True but later canonical_result success=False with 'NoneType' object is not iterable suggests downstream code expects a list of images but gets None after the ADetailer failure.
upscale stage skipped: no input images from previous stage is a consequence of ADetailer producing 0 images, so the pipeline can’t proceed.
ADetailer detection repeatedly reports “nothing detected” for both settings; this isn’t a crash but means ADetailer would be a no-op even if the NameError were fixed (check model/thresholds vs content).
SafeMode blocks model option writes (Model switch ... requested but options writes are disabled), so the requested base model might not be applied as expected; this can cause config/model mismatches.
The mid-run model switch is coming from refiner being implicitly enabled by data flow, not from hires fix. The pack disables refiner/hires, but the run config still carries a non-empty refiner_checkpoint, and the executor treats that as “refiner on,” so it loads the refiner model at ~21/34 steps.

Trace

Pack says refiner/hires are off: SDXL_mythical_beasts_Fantasy.json (line 337) has enable_hr: false, and SDXL_mythical_beasts_Fantasy.json (line 346) has refiner_checkpoint: "None".
The manifest for this run shows refiner is set anyway: txt2img_p04_00_dungeon_txt2img.json contains refiner_checkpoint: "babesByStableYogiPony_xlV4" with enable_hr: false.
GUI stage card always writes refiner_checkpoint/refiner_model_name regardless of use_refiner, and loads a model name even when disabled: advanced_txt2img_stage_card_v2.py (line 714) and advanced_txt2img_stage_card_v2.py (line 760).
Model profile defaults inject a refiner model name even if refiner isn’t enabled, which then flows into the GUI: app_controller.py (line 2453).
Prompt pack job build path copies refiner_checkpoint unconditionally into the job config: prompt_pack_job_builder.py (line 318).
Pipeline runner then pushes refiner fields into the payload if refiner_checkpoint exists, ignoring use_refiner: pipeline_runner.py (line 159).
Executor turns refiner on purely based on refiner_checkpoint + refiner_switch_at, not refiner_enabled or use_refiner: executor.py (line 2317). That’s why WebUI switches models at ~21/34 (0.8 switch ratio).
SafeMode is enforced by config webui_options_write_enabled being false, so options writes (model/vae/hypernetwork switches) are blocked: client.py (line 137) plus defaults in default.json and Testing.json. This is why you see “options writes disabled,” but it doesn’t stop native refiner parameters.
What this means

The switch you’re seeing isn’t hires fix; it’s refiner being activated by the presence of a refiner checkpoint in the run config.
SafeMode only blocks /options writes; refiner still works because it uses top-level API fields, so SafeMode isn’t the reason refiner ran."

GitHub Copilot: I'll analyze the issues and create a comprehensive PR spec. Let me first gather context on the key files mentioned in the issue trace. 

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/pipeline_runner.py#155-155), lines 155 to 165

Searched for files matching `**/advanced_txt2img_stage_card*.py`, 1 match

Searched for files matching `**/executor.py`, 1 match

Searched for files matching `**/prompt_pack_job_builder.py`, 1 match

Searched for text `apply_global`, 20 results

Read [](file:///c%3A/Users/rob/projects/StableNew/src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py#1-1), lines 1 to 50

Read [](file:///c%3A/Users/rob/projects/StableNew/src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py#710-710), lines 710 to 765

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/executor.py#2310-2310), lines 2310 to 2325

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/prompt_pack_job_builder.py#315-315), lines 315 to 325

Searched for text `name 'apply_global' is not defined`, no results

Searched for regex `def apply_global|apply_global\(` (`**/src/**/*.py`), no results

Read [](file:///c%3A/Users/rob/projects/StableNew/src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py#755-755), lines 755 to 770

Read [](file:///c%3A/Users/rob/projects/StableNew/src/controller/app_controller.py#2445-2445), lines 2445 to 2460

Searched for text `PipelineRunResult` (`**/src/pipeline/*.py`), 14 results

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/pipeline_runner.py#340-340), lines 340 to 370

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/pipeline_runner.py#795-795), lines 795 to 850

Searched for text `name 'apply_global' is not defined` (`**/logs/**/*.txt`), no results

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/executor.py#1-1), lines 1 to 150

Searched for regex `merge_global_(negative|positive)` (`**/src/**/*.py`), 9 results

Read [](file:///c%3A/Users/rob/projects/StableNew/src/utils/negative_helpers_v2.py)

Read [](file:///c%3A/Users/rob/projects/StableNew/src/utils/__init__.py#1-1), lines 1 to 50

Read [](file:///c%3A/Users/rob/projects/StableNew/src/utils)

Now let me search for where `apply_global` is actually referenced in the executor to understand the error: 

Searched for text `apply_global` (`**/src/pipeline/executor.py`), 17 results

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/executor.py#200-200), lines 200 to 250

Searched for files matching `**/*adetailer*.py`, 11 matches

Searched for text `adetailer` (`**/src/pipeline/executor.py`), 50 results

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/executor.py#2700-2700), lines 2700 to 2950

Now let me search for where the NameError occurs in adetailer execution: 

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/executor.py#1400-1400), lines 1400 to 1550

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/pipeline_runner.py#1-1), lines 1 to 140

Now let me check the specific line where apply_global causes the error. Based on the trace, it seems to be in the adetailer metadata construction: 

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/executor.py#1340-1340), lines 1340 to 1350

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/executor.py#1430-1430), lines 1430 to 1450

Found it! Line 1445 references `apply_global` but it's never defined in the `run_adetailer` method. Let me check the complete adetailer method: 

Read [](file:///c%3A/Users/rob/projects/StableNew/src/pipeline/executor.py#1284-1284), lines 1284 to 1460

Read [](file:///c%3A/Users/rob/projects/StableNew/docs/ARCHITECTURE_v2.6.md#1-1), lines 1 to 100

Perfect! Now I have all the context. Let me create a comprehensive PR spec following the requested format:

# OpenSpec: PR-CORE1-114 – Pipeline Run Controls & Refiner Logic Fix

## Context

Multiple critical issues exist in the current pipeline execution flow that cause runtime failures and unintended behavior:

1. **NameError in ADetailer**: `run_adetailer()` method references undefined variable `apply_global` at line 1445, causing hard failure that zeroes ADetailer output and cascades to downstream stages
2. **Refiner incorrectly enabled**: Multiple layers unconditionally write/propagate refiner settings regardless of `use_refiner` flag:
   - GUI stage card always writes `refiner_checkpoint`/`refiner_model_name` (line 714, 760)
   - Model profile defaults inject refiner model names even when disabled
   - Prompt pack job builder copies `refiner_checkpoint` unconditionally (line 318)
   - Pipeline runner pushes refiner fields if `refiner_checkpoint` exists, ignoring `use_refiner` (line 159)
   - Executor activates refiner based solely on `refiner_checkpoint` presence, not `use_refiner` flag (line 2317)
3. **Pipeline state mismatch**: `PipelineRunResult` created with `success=True` but downstream code receives `success=False` with `'NoneType' object is not iterable`, indicating improper error propagation
4. **SafeMode confusion**: SafeMode blocks `/options` writes but doesn't prevent refiner activation via top-level API fields, creating misleading behavior

These issues violate v2.6 architecture invariants:
- Stage execution must be deterministic based on config flags
- Errors must propagate correctly through result objects
- Config values must respect enable/disable flags throughout the stack

## Non-Goals

- Fixing ADetailer detection thresholds or model selection (working as designed, just "nothing detected")
- Changing SafeMode architecture (separate concern)
- Modifying prompt pack JSON schema
- Altering GUI layout or theming
- Refactoring unrelated executor methods

## Invariants

- ✅ ADetailer stage must never reference undefined variables
- ✅ Refiner must ONLY activate when `use_refiner` is explicitly `True`
- ✅ If `use_refiner` is `False` or missing, refiner fields must NOT be propagated to executor
- ✅ Pipeline result `success` flag must accurately reflect execution outcome
- ✅ Stage failures must set `success=False` and populate `error` field
- ✅ All stages must handle missing/None inputs gracefully
- ✅ Config flags must be honored at every layer: GUI → Builder → Runner → Executor

## Allowed Files

- executor.py (fix apply_global NameError)
- advanced_txt2img_stage_card_v2.py (conditional refiner write)
- prompt_pack_job_builder.py (conditional refiner propagation)
- pipeline_runner.py (conditional refiner propagation, result handling)
- app_controller.py (model profile defaults logic)
- `tests/pipeline/test_executor_adetailer.py` (NEW - test adetailer metadata)
- `tests/pipeline/test_refiner_control.py` (NEW - test refiner gating)
- `tests/pipeline/test_pipeline_result_state.py` (NEW - test success flag propagation)

## Do Not Touch

- client.py (SafeMode enforcement correct as-is)
- `src/services/queue_service.py` (unrelated to this issue)
- theme_v2.py
- Any test files not explicitly listed above

## Interfaces

### Executor.run_adetailer() – Fix NameError

**Before:**
```python
# Line 1345: apply_global referenced but never defined
metadata = {
    ...
    "global_negative_applied": apply_global,  # ❌ NameError
    "global_negative_terms": self.config_manager.get_global_negative_prompt()
        if apply_global
        else "",
```

**After:**
```python
# Determine if global negative was applied (always False for ADetailer per design)
apply_global = False  # ADetailer uses custom prompts, no global merging

metadata = {
    ...
    "global_negative_applied": apply_global,  # ✅ Defined
    "global_negative_terms": "",  # Always empty for ADetailer
```

### AdvancedTxt2ImgStageCardV2.to_config_dict() – Conditional Refiner Write

**Before:**
```python
# Lines 760-770: Always writes refiner fields regardless of use_refiner
"use_refiner": bool(self.refiner_enabled_var.get()),
"refiner_checkpoint": self._refiner_model_name_map.get(...),  # ❌ Always set
"refiner_model_name": self._refiner_model_name_map.get(...),  # ❌ Always set
"refiner_switch_at": float(self.refiner_switch_var.get() or 0.8),  # ❌ Always set
```

**After:**
```python
"use_refiner": bool(self.refiner_enabled_var.get()),
# Only write refiner fields if use_refiner is True
**({"refiner_checkpoint": self._refiner_model_name_map.get(...),
    "refiner_model_name": self._refiner_model_name_map.get(...),
    "refiner_switch_at": float(self.refiner_switch_var.get() or 0.8)}
   if bool(self.refiner_enabled_var.get()) else {}),
```

### PromptPackJobBuilder._build_txt2img_config() – Conditional Refiner Copy

**Before:**
```python
# Line 318-320: Unconditionally copies refiner fields
"use_refiner": txt2img.get("use_refiner"),
"refiner_checkpoint": txt2img.get("refiner_checkpoint"),  # ❌ Always copied
"refiner_switch_at": txt2img.get("refiner_switch_at"),  # ❌ Always copied
```

**After:**
```python
"use_refiner": txt2img.get("use_refiner", False),
# Only copy refiner fields if use_refiner is True
**({"refiner_checkpoint": txt2img.get("refiner_checkpoint"),
    "refiner_switch_at": txt2img.get("refiner_switch_at")}
   if txt2img.get("use_refiner") else {}),
```

### PipelineRunner.run_njr() – Conditional Refiner Payload

**Before:**
```python
# Line 159-161: Pushes refiner if refiner_checkpoint exists
if njr_config.get("refiner_checkpoint"):  # ❌ Ignores use_refiner flag
    payload["refiner_checkpoint"] = njr_config["refiner_checkpoint"]
    payload["refiner_switch_at"] = njr_config.get("refiner_switch_at", 0.8)
```

**After:**
```python
# Only add refiner settings if use_refiner is explicitly True
if njr_config.get("use_refiner") and njr_config.get("refiner_checkpoint"):
    payload["refiner_checkpoint"] = njr_config["refiner_checkpoint"]
    payload["refiner_switch_at"] = njr_config.get("refiner_switch_at", 0.8)
```

### Executor (Line 2317) – Conditional Refiner Activation

**Before:**
```python
# Line 2317-2322: use_refiner computed from refiner_checkpoint presence only
use_refiner = (
    refiner_checkpoint
    and refiner_checkpoint != "None"
    and refiner_checkpoint.strip() != ""
    and 0.0 < refiner_switch_at < 1.0
)  # ❌ Ignores explicit use_refiner flag
```

**After:**
```python
# use_refiner must be explicitly True in config AND valid checkpoint/ratio
use_refiner_flag = config.get("use_refiner", False)
use_refiner = (
    use_refiner_flag  # ✅ Explicit flag required
    and refiner_checkpoint
    and refiner_checkpoint != "None"
    and refiner_checkpoint.strip() != ""
    and 0.0 < refiner_switch_at < 1.0
)
```

### AppController._apply_model_profile_defaults() – No Change Required

Model profile defaults inject refiner model names, but this is **working as designed** because:
- The profile provides a *default* value
- The GUI/builder layers now gate propagation based on `use_refiner`
- Default != forced activation

**No change needed** – the conditional gating at GUI/builder/runner/executor layers will prevent unwanted refiner activation.

## Implementation Steps (Order Matters)

### Step 1: Fix NameError in Executor.run_adetailer()

**File:** executor.py

**Location:** Lines 1343-1450 (run_adetailer method)

**Action:**
1. After line 1353 (where `ad_neg_final` is determined), add:
   ```python
   # ADetailer uses custom prompts - never apply global negative merging
   apply_global = False
   ```
2. Update metadata dict at lines 1445-1448 to use the defined variable:
   ```python
   "global_negative_applied": apply_global,
   "global_negative_terms": "",  # Always empty for ADetailer per design
   ```

**Rationale:** ADetailer has custom prompts and should never merge global negatives (per line 1344 comment). The variable must be defined before metadata construction.

### Step 2: Conditional Refiner Write in GUI Stage Card

**File:** advanced_txt2img_stage_card_v2.py

**Location:** Lines 755-770 (`to_config_dict` method)

**Action:**
1. Store `use_refiner` flag in variable before building dict:
   ```python
   use_refiner = bool(self.refiner_enabled_var.get())
   ```
2. Replace lines 760-769 (refiner fields) with conditional dict merge:
   ```python
   "use_refiner": use_refiner,
   # Only write refiner fields if explicitly enabled
   **({"refiner_checkpoint": self._refiner_model_name_map.get(
           self.refiner_model_var.get(), 
           self.refiner_model_var.get().strip()
       ),
       "refiner_model_name": self._refiner_model_name_map.get(
           self.refiner_model_var.get(), 
           self.refiner_model_var.get().strip()
       ),
       "refiner_switch_at": float(self.refiner_switch_var.get() or 0.8)}
      if use_refiner else {}),
   ```

**Rationale:** Prevents GUI from writing refiner fields into config when refiner is disabled.

### Step 3: Conditional Refiner Copy in Builder

**File:** prompt_pack_job_builder.py

**Location:** Lines 315-325 (`_build_txt2img_config` method)

**Action:**
1. After line 317 (`"use_refiner": txt2img.get("use_refiner"),`), change to:
   ```python
   "use_refiner": txt2img.get("use_refiner", False),
   ```
2. Replace lines 318-320 (refiner field copies) with conditional merge:
   ```python
   **({"refiner_checkpoint": txt2img.get("refiner_checkpoint"),
       "refiner_switch_at": txt2img.get("refiner_switch_at")}
      if txt2img.get("use_refiner") else {}),
   ```

**Rationale:** Builder must not propagate refiner fields into NJR config unless explicitly enabled.

### Step 4: Conditional Refiner Payload in Runner

**File:** pipeline_runner.py

**Location:** Lines 155-165 (payload building in `run_njr`)

**Action:**
1. Replace lines 159-161 with:
   ```python
   # Add refiner settings only if use_refiner is explicitly True
   if njr_config.get("use_refiner") and njr_config.get("refiner_checkpoint"):
       payload["refiner_checkpoint"] = njr_config["refiner_checkpoint"]
       payload["refiner_switch_at"] = njr_config.get("refiner_switch_at", 0.8)
   ```

**Rationale:** Runner must respect `use_refiner` flag before adding refiner to API payload.

### Step 5: Conditional Refiner Activation in Executor

**File:** executor.py

**Location:** Lines 2310-2325 (refiner activation logic in `run_txt2img`)

**Action:**
1. Before line 2317, extract explicit flag:
   ```python
   use_refiner_flag = config.get("use_refiner", False)
   ```
2. Replace lines 2317-2322 with:
   ```python
   use_refiner = (
       use_refiner_flag  # Must be explicitly True
       and refiner_checkpoint
       and refiner_checkpoint != "None"
       and refiner_checkpoint.strip() != ""
       and 0.0 < refiner_switch_at < 1.0
   )
   ```
3. Add debug log after line 2322:
   ```python
   if not use_refiner_flag and refiner_checkpoint:
       logger.info("🚫 Refiner disabled via use_refiner=False (checkpoint present but ignored)")
   elif use_refiner:
       logger.info("✅ Refiner enabled: checkpoint=%s, switch_at=%.3f", refiner_checkpoint, refiner_switch_at)
   ```

**Rationale:** Executor is final enforcement point – must check explicit `use_refiner` flag before activating refiner, even if checkpoint is present.

### Step 6: Create Test – ADetailer Metadata

**File:** `tests/pipeline/test_executor_adetailer.py` (NEW)

**Action:**
Create new test file with:
```python
"""Test ADetailer metadata generation and apply_global handling."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from src.pipeline.executor import Pipeline

def test_adetailer_metadata_apply_global_defined():
    """Ensure apply_global is defined and False in ADetailer metadata."""
    pipeline = Pipeline(Mock(), Mock())
    
    with patch.object(pipeline, '_load_image_base64', return_value="fake_b64"), \
         patch.object(pipeline, '_generate_images', return_value={"images": ["result_b64"]}), \
         patch('src.pipeline.executor.save_image_from_base64', return_value=True), \
         patch('builtins.open', MagicMock()):
        
        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 28,
        }
        
        result = pipeline.run_adetailer(
            input_image_path=Path("input.png"),
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            run_dir=Path("output"),
            image_name="test"
        )
        
        assert result is not None
        assert "global_negative_applied" in result
        assert result["global_negative_applied"] is False
        assert result["global_negative_terms"] == ""
```

### Step 7: Create Test – Refiner Control

**File:** `tests/pipeline/test_refiner_control.py` (NEW)

**Action:**
Create new test file with:
```python
"""Test refiner gating logic across all layers."""
import pytest
from src.pipeline.prompt_pack_job_builder import PromptPackJobBuilder
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from unittest.mock import Mock

def test_gui_stage_card_no_refiner_fields_when_disabled():
    """GUI stage card must not write refiner fields when use_refiner=False."""
    card = AdvancedTxt2ImgStageCardV2(Mock(), controller=Mock(), theme=Mock())
    card.refiner_enabled_var.set(False)
    card.refiner_model_var.set("some_model")
    
    config = card.to_config_dict()
    
    assert config["txt2img"]["use_refiner"] is False
    assert "refiner_checkpoint" not in config["txt2img"]
    assert "refiner_model_name" not in config["txt2img"]
    assert "refiner_switch_at" not in config["txt2img"]

def test_builder_no_refiner_propagation_when_disabled():
    """Builder must not copy refiner fields into NJR when use_refiner=False."""
    builder = PromptPackJobBuilder()
    txt2img_config = {
        "use_refiner": False,
        "refiner_checkpoint": "unwanted_model.safetensors",
        "refiner_switch_at": 0.8,
    }
    
    result = builder._build_txt2img_config(txt2img_config, {})
    
    assert result["use_refiner"] is False
    assert "refiner_checkpoint" not in result
    assert "refiner_switch_at" not in result
```

### Step 8: Create Test – Pipeline Result State

**File:** `tests/pipeline/test_pipeline_result_state.py` (NEW)

**Action:**
Create new test file with:
```python
"""Test PipelineRunResult success flag propagation."""
import pytest
from src.pipeline.pipeline_runner import PipelineRunResult

def test_pipeline_result_success_false_on_empty_variants():
    """PipelineRunResult with zero variants should indicate failure."""
    result = PipelineRunResult(
        run_id="test",
        success=True,  # Initial value
        error=None,
        variants=[],  # No images produced
        learning_records=[],
    )
    
    result_dict = result.to_dict()
    # If variants is empty but success=True, downstream expects list but gets None
    # This should be validated/corrected
    assert isinstance(result_dict["variants"], list)

def test_pipeline_result_error_sets_success_false():
    """PipelineRunResult with error should have success=False."""
    result = PipelineRunResult(
        run_id="test",
        success=False,
        error="Stage failed",
        variants=[],
        learning_records=[],
    )
    
    result_dict = result.to_dict()
    assert result_dict["success"] is False
    assert result_dict["error"] == "Stage failed"
```

## Acceptance Criteria

### AC1: ADetailer Executes Without NameError
**Given** ADetailer stage is enabled in pipeline config  
**When** `run_adetailer()` constructs metadata dict  
**Then** `apply_global` variable is defined and set to `False`  
**And** metadata includes `"global_negative_applied": False`  
**And** no NameError is raised

### AC2: Refiner Disabled When use_refiner=False
**Given** GUI stage card has `use_refiner` checkbox unchecked  
**When** `to_config_dict()` is called  
**Then** config dict includes `"use_refiner": False`  
**And** config dict does NOT include `refiner_checkpoint`, `refiner_model_name`, or `refiner_switch_at` keys

### AC3: Builder Respects use_refiner Flag
**Given** txt2img config has `"use_refiner": False` and `"refiner_checkpoint": "model.safetensors"`  
**When** `_build_txt2img_config()` processes the config  
**Then** output dict includes `"use_refiner": False`  
**And** output dict does NOT include `refiner_checkpoint` or `refiner_switch_at`

### AC4: Runner Respects use_refiner Flag
**Given** NJR config has `"use_refiner": False` and `"refiner_checkpoint": "model.safetensors"`  
**When** `run_njr()` builds API payload  
**Then** payload does NOT include `refiner_checkpoint` or `refiner_switch_at` keys

### AC5: Executor Requires Explicit use_refiner=True
**Given** txt2img config has valid `refiner_checkpoint` but `"use_refiner": False` (or missing)  
**When** executor computes `use_refiner` flag  
**Then** `use_refiner` evaluates to `False`  
**And** no model switch occurs during sampling  
**And** log contains "Refiner disabled via use_refiner=False"

### AC6: Executor Activates Refiner Only When Enabled
**Given** txt2img config has `"use_refiner": True` and valid `refiner_checkpoint`  
**When** executor computes `use_refiner` flag  
**Then** `use_refiner` evaluates to `True`  
**And** refiner model switch occurs at specified ratio  
**And** log contains "Refiner enabled: checkpoint=..., switch_at=..."

## Test Plan

### Pre-Change Expected Failures

```bash
# Run existing pipeline tests - expect failures due to NameError
pytest tests/pipeline/test_executor_adetailer.py -v
# Expected: FAIL - NameError: name 'apply_global' is not defined

# Run journey tests with refiner disabled
pytest tests/journeys/ -k refiner -v
# Expected: Refiner activates even when use_refiner=False
```

### Post-Change Expected Pass

```bash
# Test ADetailer metadata
pytest tests/pipeline/test_executor_adetailer.py -v
# Expected: PASS - apply_global defined, metadata correct

# Test refiner gating
pytest tests/pipeline/test_refiner_control.py -v
# Expected: PASS - refiner fields absent when disabled

# Test pipeline result state
pytest tests/pipeline/test_pipeline_result_state.py -v
# Expected: PASS - success flags and variants consistent

# Full pipeline regression
pytest tests/pipeline/ -v
# Expected: ALL PASS

# Journey test with pack that disables refiner
pytest tests/journeys/test_jt04_img2img_adetailer_run.py -v
# Expected: PASS - refiner does not activate, ADetailer succeeds
```

### Manual Verification

1. **ADetailer NameError Fix:**
   - Run pack with ADetailer enabled
   - Verify no NameError in logs
   - Check manifest JSON has `"global_negative_applied": false`

2. **Refiner Disabled:**
   - Load pack with `"enable_hr": false`, `"refiner_checkpoint": "None"`
   - Uncheck "Use Refiner" in GUI
   - Run job
   - Verify WebUI logs show NO model switch during sampling
   - Verify manifest has no `refiner_checkpoint` field

3. **Refiner Enabled:**
   - Load pack with `"enable_hr": false`, `"refiner_checkpoint": "valid_model"`
   - Check "Use Refiner" in GUI
   - Run job
   - Verify WebUI logs show model switch at specified ratio
   - Verify manifest includes `"refiner_checkpoint": "valid_model"`

## Rollback

```bash
git revert <commit-hash>
```

All changes are isolated to specific methods within listed files. No schema changes, no DB migrations, no external dependencies altered.

Rollback restores:
- ADetailer NameError (non-critical if ADetailer not used)
- Refiner always activating when checkpoint present (annoying but not data-corrupting)
- Current behavior (suboptimal but functional)

---

## Additional Notes

### Root Cause Summary

The refiner issue is a **multi-layer propagation bug** where each layer independently decides whether to include refiner fields, but none respect the `use_refiner` flag:

1. **GUI** writes refiner fields unconditionally → config always has them
2. **Builder** copies refiner fields unconditionally → NJR always has them
3. **Runner** adds refiner to payload if checkpoint exists → API always gets them
4. **Executor** activates refiner if checkpoint + ratio valid → refiner always runs

The fix enforces **explicit opt-in** at every layer: `use_refiner` must be `True` for refiner fields to propagate.

### Why Model Profile Defaults Don't Need Changes

Model profile defaults provide *suggested values* for GUI fields. Even if they inject a refiner model name, the conditional gating now prevents propagation unless the user explicitly enables the refiner checkbox. This is correct behavior: defaults populate fields, but flags control execution.

### SafeMode Clarification

SafeMode blocks `/sdapi/v1/options` writes (model/VAE/hypernetwork switches) but does **not** block top-level API parameters like `refiner_checkpoint` in the `/sdapi/v1/txt2img` payload. This is by design – SafeMode prevents *global* option changes, not per-request parameters. The refiner fix ensures per-request parameters are only included when intended.