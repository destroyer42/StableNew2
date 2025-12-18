# D-GUI-002: Research — Batch Size, Output Organization, Process Cleanup

**Status:** Research Complete  
**Date:** 2025-12-17  
**Priority:** HIGH  
**Related Issues:** Batch size not working, orphaned processes, output folder structure

---

## Executive Summary

Three critical issues identified:
1. **Batch size field has no effect** - `images_per_prompt` is stored in NJR but never passed to WebUI
2. **Orphaned WebUI processes remain after exit** - aggressive cleanup code exists but may have edge cases
3. **Output folder structure needs reorganization** - flat structure instead of hierarchical by job/pack

---

## Issue 1: Batch Size Not Working

### Current Behavior
- User sets `batch_size=2` in GUI
- Pack has 10 prompts
- Expected: 20 images (10 prompts × 2 images each)
- **Actual: 10 images** (batch_size ignored)

### Root Cause Analysis

**Discovery Path:**
1. `images_per_prompt` is correctly stored in `NormalizedJobRecord.images_per_prompt` (src/pipeline/job_models_v2.py:513)
2. Value is correctly loaded from pack config `pipeline.images_per_prompt` (src/pipeline/prompt_pack_job_builder.py:120)
3. **BROKEN:** NJR runner doesn't pass batch_size to stage executors

**Code Evidence:**

**✅ Config gathering works:**
```python
# src/controller/app_controller.py:3648
current_config["pipeline"]["images_per_prompt"] = output_overrides.get("batch_size", 1)
```

**✅ NJR stores it:**
```python
# src/pipeline/prompt_pack_job_builder.py:120
record.images_per_prompt = int(pipeline_section.get("images_per_prompt", 1))
```

**❌ Pipeline runner IGNORES it:**
```python
# src/pipeline/pipeline_runner.py:91-97
# Builds payload for txt2img but doesn't include batch_size!
payload = {
    "prompt": stage.prompt_text,
    "negative_prompt": negative_prompt,
    "model": stage.model,
    "sampler_name": stage.sampler,
    "steps": njr.steps or 20,
    # MISSING: "batch_size": njr.images_per_prompt
}
```

**❌ Stage executor doesn't receive batch_size:**
```python
# src/pipeline/executor.py:2159
def run_txt2img_stage(
    self,
    prompt: str,
    negative_prompt: str,
    config: dict[str, Any],  # batch_size not in config
    output_dir: Path,
    image_name: str,
    cancel_token=None,
) -> dict[str, Any] | None:
```

### Fix Strategy

**Option A: Pass batch_size in stage payload (RECOMMENDED)**
```python
# In pipeline_runner.py, when building txt2img payload:
payload = {
    "prompt": stage.prompt_text,
    "negative_prompt": negative_prompt,
    "model": stage.model,
    "sampler_name": stage.sampler,
    "steps": njr.steps or 20,
    "batch_size": njr.images_per_prompt or 1,  # ADD THIS
    "cfg_scale": stage.cfg_scale or njr.cfg_scale or 7.5,
    "width": njr.width or 1024,
    "height": njr.height or 1024,
}
```

Then in executor.py, extract and use it:
```python
# run_txt2img_stage should extract batch_size from config
batch_size = txt2img_config.get("batch_size", 1)
# Then pass to actual WebUI payload building
```

**Option B: Add batch_size parameter to stage methods**
- More invasive, requires signature changes
- Not recommended due to scope

### Files to Modify
1. **src/pipeline/pipeline_runner.py** - Add `batch_size` to payload
2. **src/pipeline/executor.py:run_txt2img_stage** - Extract and use batch_size
3. **src/pipeline/executor.py:run_img2img_stage** - Same for img2img

---

## Issue 2: Orphaned WebUI Processes

### Current Behavior
- User exits StableNew
- 5-7 python.exe processes remain running
- Memory consumption: 1.8 GB + 6.5 GB (8.3 GB total)
- Processes persist until manually killed

### Existing Cleanup Code

**Aggressive process killing IS implemented:**
```python
# src/api/webui_process_manager.py:463-505
def _finalize_process(self, process: subprocess.Popen) -> None:
    # ... tries to kill parent first
    
    # AGGRESSIVE: Find and kill ALL python.exe processes
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'memory_info']):
        if proc.info['name'] and 'python' in proc.info['name'].lower():
            # Check 1: cmdline contains webui keywords
            # Check 2: cwd matches WebUI directory
            # Check 3: FAILSAFE - Memory > 500MB
            
            if is_webui:
                proc.kill()
```

**Cleanup IS called:**
```python
# src/api/webui_process_manager.py:259
def stop_webui(self, grace_seconds: float = 10.0) -> bool:
    # ... terminate, wait, kill
    self._finalize_process(process)  # ✅ Called
```

### Why It's Not Working - Investigation Needed

**Possible causes:**

1. **Process spawning pattern:**
   - WebUI may spawn processes that don't match detection criteria
   - Need to check actual cmdline of orphaned processes
   - User reports 5-7 python.exe - one parent might spawn multiple workers

2. **Timing issue:**
   - Cleanup runs but processes respawn after
   - Check if WebUI has auto-restart logic

3. **Parent-child relationship:**
   - Orphaned processes may have different parent after original dies
   - `psutil.process_iter` might miss them if they become system orphans

4. **Working directory mismatch:**
   - Processes might change cwd after launch
   - `Path(cwd) == Path(webui_dir)` comparison might fail due to symlinks/case

5. **StableNew exits before cleanup completes:**
   - Need to verify shutdown sequence waits for cleanup
   - Check if app exit happens while `_finalize_process` is running

### Diagnostic Steps Needed

**Add aggressive logging:**
```python
# List ALL python.exe processes before cleanup
logger.warning("=== BEFORE CLEANUP ===")
for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'memory_info']):
    if 'python' in proc.info['name'].lower():
        logger.warning("Python PID %s: cmdline=%s, cwd=%s, mem=%.1fMB",
            proc.pid, proc.info['cmdline'], proc.info['cwd'],
            proc.info['memory_info'].rss / (1024*1024))
```

**Verify shutdown sequence:**
```python
# In app_controller.py shutdown
logger.warning("Starting WebUI process manager shutdown...")
if self.webui_process_manager:
    self.webui_process_manager.stop_webui()
    logger.warning("WebUI shutdown complete")
    
# Wait and verify
time.sleep(2)
logger.warning("=== AFTER CLEANUP ===")
# List remaining python.exe processes
```

### Fix Strategy

**Phase 1: Diagnostic (IMMEDIATE)**
- Add comprehensive logging before/after cleanup
- Log all python.exe process details during shutdown
- User runs app, exits, captures full log
- Analyze what processes survive and why

**Phase 2: Enhanced Cleanup (AFTER DIAGNOSTICS)**
Based on diagnostic results, likely fixes:
- Add broader process name matching (not just 'python')
- Kill ALL processes in working directory tree
- Add `SIGTERM` to entire process group
- Implement Windows-specific `taskkill /F /T` fallback
- Add post-cleanup verification loop

**Suggested immediate enhancement:**
```python
# Kill entire process tree more aggressively
import subprocess
if platform.system() == "Windows":
    try:
        # Use Windows taskkill to force-kill tree
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            check=False,
            capture_output=True
        )
    except Exception as e:
        logger.error("taskkill failed: %s", e)
```

---

## Issue 3: Output Folder Structure

### Current Structure
```
output/
  d080593f-689e-4085-9371-3099a960bbad/   # UUID run ID
    txt2img/
      txt2img_20251217_213134.png
    adetailer/
      adetailer_20251217_213134.png
    img2img/
      ...
    manifests/
      txt2img_20251217_213134.json
      adetailer_20251217_213134.json
```

### Desired Structure
```
output/
  20251217-2132/                          # Date-time of run
    SDXL_beautiful_women_Fantasy/         # Prompt pack name (job name)
      txt2img_00.png                      # All images at this level
      txt2img_01.png
      adetailer_00.png
      adetailer_01.png
      img2img_00.png
      upscale_00.png
      manifests/                          # Child folder for configs
        txt2img_00.json
        txt2img_01.json
        adetailer_00.json
        ...
    SDXL_angelic_warriors_Fantasy/        # Another pack/job
      txt2img_00.png
      ...
      manifests/
        ...
```

### Nomenclature Clarification

**User's mental model:**
- **Job** = One prompt pack with its configs
  - Contains: 1 to N prompts
  - Example: "SDXL_beautiful_women_Fantasy" pack with 10 prompts
- **Total images in job** = num_prompts × batch_size
  - Example: 10 prompts × 2 batch = 20 images
- **Job Bundle** = Collection of multiple jobs sent to queue together
  - Example: Beautiful_women + Angelic_warriors = 2 jobs in bundle
- **Queue** = Receives job bundles
- **Output organization** = One folder per job (pack name)

**Current code model (DIFFERENT):**
- **NormalizedJobRecord** = ONE prompt configuration
  - One prompt pack with 10 prompts → 10 NJRs
- **Job bundle** = List of NJRs
- **images_per_prompt** = Batch multiplier per NJR
- **Output** = One UUID folder per execution

**Gap:**
- No concept of "job = pack" in current architecture
- No grouping of NJRs by pack name
- Output uses UUID instead of datetime + pack name

### Implementation Strategy

**Phase 1: Output Path Generation**

Currently in `pipeline_runner.py:60`:
```python
run_id = str(uuid4())
run_dir = Path(self._runs_base_dir) / run_id
```

Change to:
```python
# Generate datetime prefix
from datetime import datetime
timestamp = datetime.now().strftime("%Y%m%d-%H%M")

# Get pack name from NJR
pack_name = njr.prompt_pack_name or "unknown_pack"

# Build hierarchical path
run_dir = Path(self._runs_base_dir) / timestamp / pack_name
run_dir.mkdir(parents=True, exist_ok=True)
```

**Phase 2: Manifest Subfolder**

Currently manifests are saved alongside images. Change to:
```python
# In executor.py save_manifest calls
manifest_dir = run_dir / "manifests"
manifest_dir.mkdir(exist_ok=True)
manifest_path = manifest_dir / f"{image_name}.json"
```

**Phase 3: Handle Multiple Packs in Same Timestamp**

If two packs run at same minute:
```
output/
  20251217-2132/
    SDXL_beautiful_women_Fantasy/
    SDXL_angelic_warriors_Fantasy/
```

This naturally groups them by time while separating by pack.

**Phase 4: Image Naming Simplification**

Instead of:
```
txt2img_20251217_213134_001.png
```

Use:
```
txt2img_00.png
txt2img_01.png
```

Counter resets per job (pack folder), so no timestamp needed in filename.

### Files to Modify

1. **src/pipeline/pipeline_runner.py**
   - Line 60: Change UUID to datetime/pack_name structure
   - Pass pack_name through to all stage methods

2. **src/pipeline/executor.py**
   - All `save_manifest` calls: Use `manifests/` subfolder
   - All image naming: Simplify to stage_##.png format
   - Methods affected:
     - `run_txt2img_stage` (~line 2159)
     - `run_img2img_stage` (~line 2424)
     - `run_adetailer_stage` (~line 2878)
     - `run_upscale_stage` (~line 2607)

3. **src/utils/manifest_logger.py** (if exists)
   - Update save paths to use manifests subfolder

4. **Tests**
   - Update path assertions in journey tests
   - Update manifest location expectations

---

## Issue 4: ADetailer Model Dropdown

### Current Behavior
- Dropdown has hardcoded defaults: `["face_yolov8n.pt", "adetailer_v1.pt"]`
- User reports WebUI has ~10 models available
- Dropdown should populate from WebUI like samplers/models/VAEs

### Root Cause

**Infrastructure EXISTS but incomplete:**

✅ Resource service tries to fetch:
```python
# src/api/webui_resource_service.py:23
adetailer_models = self.list_adetailer_models()
```

✅ Dropdown loader expects it:
```python
# src/gui/dropdown_loader_v2.py:22
_RESOURCE_KEYS = (
    "models",
    "vaes",
    "samplers",
    "schedulers",
    "upscalers",
    "adetailer_models",  # ✅ Listed
    "adetailer_detectors",
)
```

✅ GUI card consumes it:
```python
# src/gui/stage_cards_v2/adetailer_stage_card_v2.py:342
models = [str(v) for v in (resources.get("adetailer_models") or []) if str(v).strip()]
self._configure_combo(self._model_combo, models, self.model_var)
```

❌ **Client method DOESN'T EXIST:**
```python
# src/api/webui_resource_service.py:60
def list_adetailer_models(self) -> list[str]:
    getter = getattr(self.client, "get_adetailer_models", None)
    # client.get_adetailer_models() doesn't exist!
```

### Fix Required

**Add method to SDWebUIClient:**

```python
# src/api/sd_webui_client.py

def get_adetailer_models(self) -> list[str]:
    """
    Fetch list of available ADetailer models from WebUI.
    
    ADetailer extension exposes models via /adetailer/models endpoint
    or via /sdapi/v1/scripts (inspect ADetailer args).
    """
    try:
        # Try dedicated endpoint first (if ADetailer extension provides)
        response = self.session.get(
            f"{self.base_url}/adetailer/models",
            timeout=10.0
        )
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    
    # Fallback: Parse from /sdapi/v1/scripts
    try:
        scripts = self._get("/sdapi/v1/scripts")
        if scripts and "alwayson_scripts" in scripts:
            adetailer = scripts["alwayson_scripts"].get("ADetailer", {})
            # Extract model list from args schema
            # Structure varies by ADetailer version
            # May need adjustment based on actual API
            args = adetailer.get("args", [])
            # ... parse args to find model list
    except Exception as e:
        logger.warning("Failed to get ADetailer models: %s", e)
    
    return []
```

**Research needed:**
1. What endpoint does ADetailer extension expose?
2. Test `GET /adetailer/models` on running WebUI
3. Inspect `GET /sdapi/v1/scripts` response structure
4. Verify model list format

**Alternative approach:**
- Scan filesystem for `.pt` files in WebUI's models/adetailer/ directory
- Less elegant but guaranteed to work

---

## Implementation Plan

### Priority 1: Batch Size (CRITICAL - Blocks workflow)
**Effort:** 2-3 hours  
**Risk:** Low  
**Files:** 2-3  

1. Add `batch_size` to stage payloads in pipeline_runner.py
2. Extract and use in executor.py stage methods
3. Test with 10-prompt pack, batch_size=2, verify 20 images

### Priority 2: ADetailer Models (HIGH - UX issue)
**Effort:** 3-4 hours  
**Risk:** Medium (depends on WebUI API)  

1. Research ADetailer extension API endpoints
2. Implement `client.get_adetailer_models()`
3. Test resource loading on startup
4. Verify dropdown populates

### Priority 3: Output Organization (HIGH - UX/usability)
**Effort:** 4-6 hours  
**Risk:** Medium (affects many files, tests)  

1. Change run_dir generation to datetime/pack_name
2. Add manifests/ subfolder
3. Simplify image naming
4. Update all stage executors
5. Update tests

### Priority 4: Process Cleanup (MEDIUM - Needs diagnostics first)
**Effort:** 2 hours diagnostic + 3-4 hours fix  
**Risk:** High (platform-specific, hard to test)  

1. Add comprehensive logging
2. User captures shutdown logs
3. Analyze surviving processes
4. Implement targeted fix based on findings
5. Add taskkill fallback for Windows

---

## Questions for User

1. **Batch Size:** Do you want batch_size to also affect img2img/adetailer stages, or only txt2img?

2. **Output Folders:** If two jobs from same pack run in same minute, should they:
   - Share folder (20251217-2132/pack_name/)
   - Add sequence suffix (20251217-2132/pack_name_01/, pack_name_02/)

3. **Process Cleanup:** Can you run app with extra logging and capture console output during shutdown?

4. **ADetailer Models:** Do you know which ADetailer extension version you're using? (Helps find correct API)

---

## Next Steps

**Recommend starting with:**
1. **Batch Size** - Highest impact, lowest risk
2. **ADetailer Models** - Research API, then implement
3. **Output Organization** - Significant UX improvement
4. **Process Cleanup** - Needs diagnostic run first

Would you like me to proceed with implementing batch size fix first?
