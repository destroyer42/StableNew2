# StableNew Debugging Action Plan
## Issues Identified & Testing Strategy

### Issue 1: Orphaned Processes (23GB RAM leak)
**Root Cause:** Orphan monitor only watches active session, doesn't clean up from previous crashes

**Fix Implemented:**
- Created `scripts/kill_orphan_pythons.ps1` for manual cleanup

**Next Steps:**
1. Run `.\scripts\kill_orphan_pythons.ps1` before starting StableNew
2. Monitor for new orphans after crashes

**Improvement Needed:**
- Add startup scan for orphaned processes in `webui_process_manager.py`
- Expand orphan detection beyond port-blocking processes

---

### Issue 2: NaN Errors (WebUI Generation Failures)
**Symptoms:**
- NansException during generation
- Once it occurs, persists across ALL models until WebUI restart
- Error message: "tensor with NaNs was produced in Unet"

**Possible Causes:**
1. **Model/VAE precision incompatibility** with GPU
2. **Memory corruption** from previous failed generation
3. **Upcast attention setting** may not be working
4. **Model switching** leaves corrupted state

**Testing Strategy:**

#### Test 1: Isolate Precision Issue
```powershell
# Fresh WebUI start, disable float32 upcast
1. Stop StableNew/WebUI
2. Kill orphans: .\scripts\kill_orphan_pythons.ps1
3. Open WebUI settings, UNCHECK "Upcast cross attention to float32"
4. Apply & Reload UI
5. Run ONE generation with SAME model
6. Check if NaN occurs
```
**Expected:** If NaN still occurs → model/VAE precision issue
**Next:** Try different model or add `--no-half` to WebUI launch

#### Test 2: Model Switching Memory Corruption
```powershell
# Test if model switching causes state corruption
1. Fresh start (as above)
2. Run generation with Model A → SUCCESS
3. Switch to Model B → Run generation
4. Switch BACK to Model A → Run generation
5. Check if NaN occurs on return to Model A
```
**Expected:** If NaN occurs after switching → WebUI state corruption
**Next:** Add VRAM clear after model changes

#### Test 3: Memory Leak Correlation
```powershell
# Track memory during multiple generations
1. Fresh start
2. Run `python scripts/capture_nan_diagnostics.py` BEFORE generation
3. Run 3 generations with SAME model
4. Run diagnostics AFTER each generation
5. Compare memory growth
```
**Expected:** If RAM keeps growing → memory leak in WebUI
**Next:** Force GC between generations

---

### Issue 3: High RAM Usage at Startup (22GB)
**Likely Cause:** WebUI loading SDXL model in float32 mode to system RAM

**Check WebUI Settings (scroll down):**
- [ ] "Move model to CPU when not needed" should be UNCHECKED
- [ ] "Move VAE to CPU" should be UNCHECKED
- [ ] No "Low VRAM" or "Medvram" options enabled

**Alternative:** Check WebUI launch args for:
- `--medvram` (loads to RAM)
- `--lowvram` (loads to RAM)
- `--no-half` (doubles memory usage)

---

### Memory Management: Should We Re-enable?

**Changes Reverted:**
1. `gc.collect()` in `free_vram()`
2. Pre-generation memory checks
3. Post-generation cleanup
4. `psutil` memory logging

**Analysis:**
- Orphan process was from PREVIOUS crash, not caused by these changes
- `psutil` is already used throughout the codebase
- Memory checks were HELPING identify pressure

**Recommendation:** **YES, re-enable with better diagnostics**

**Re-enable Plan:**
1. Add memory logging ONLY at WARNING level (not DEBUG)
2. Skip aggressive GC if memory < 80%
3. Add flag to disable via config: `enable_memory_management: false`
4. Log to separate `memory.log` file

---

### Testing Tools Created

1. **`scripts/kill_orphan_pythons.ps1`**
   - Run before starting StableNew
   - Kills processes >10GB or >1 hour old

2. **`scripts/capture_nan_diagnostics.py`**
   - Run after NaN error
   - Captures memory state, WebUI state, processes
   - Saves JSON report to `reports/diagnostics/`

Usage:
```powershell
# After NaN error occurs
python scripts/capture_nan_diagnostics.py
```

---

### Immediate Actions (Priority Order)

1. **Kill orphans:** `.\scripts\kill_orphan_pythons.ps1`
2. **Test NaN isolation:** Run Test 1 above
3. **Capture diagnostics:** Run after next NaN error
4. **Review WebUI settings:** Check for CPU offload options
5. **Consider re-enabling memory management** with config flag

---

### Success Criteria

**Problem Solved When:**
- ✅ No orphaned processes after crashes
- ✅ NaN errors identified and prevented
- ✅ RAM usage stays < 10GB during generation
- ✅ Model switching doesn't cause failures
- ✅ Diagnostics capture root cause when issues occur

---

### Open Questions

1. **Which models trigger NaN?** Need to test multiple models
2. **Does hires fix increase NaN risk?** Test with/without
3. **Is VRAM fragmentation a factor?** Monitor VRAM usage
4. **Does batch size affect NaN?** Test batch_size=1 vs 2+

**Track answers in:** `reports/diagnostics/testing_results.md`
