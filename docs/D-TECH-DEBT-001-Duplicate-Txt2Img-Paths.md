# D-TECH-DEBT-001: Duplicate txt2img Execution Paths

**Status:** DOCUMENTED | Model/VAE Fix Applied  
**Date:** 2026-01-01  
**Priority:** HIGH (consolidation needed)  
**Impact:** Manifest inconsistency, code duplication, maintenance burden

---

## Executive Summary

StableNew has **TWO separate txt2img execution paths** with duplicated logic, different manifest formats, and inconsistent metadata. This caused **critical model/VAE fields to be missing** from production manifests (Path 2) while being present in legacy manifests (Path 1).

**Immediate Fix Applied:** ✅ Added model/VAE fields to Path 2 manifests  
**Remaining Issue:** ⚠️ Duplicate code paths still exist and need consolidation

---

## The Two Paths

### **Path 1: `run_txt2img()` → `_run_txt2img_impl()`**

**Location:** [executor.py:1338-1615](c:\Users\rob\projects\StableNew\src\pipeline\executor.py#L1338-L1615)

**Used By:**
- ❌ **DEPRECATED:** `run_full_pipeline()` (line 2457)
- ❌ **ONLY CALLER:** CLI script (`src/cli.py:116`)
- ❌ **NOT USED BY GUI** or modern queue system

**Characteristics:**
- Takes single prompt string
- Handles batch_size as parameter
- Returns `list[dict[str, Any]]` (multiple metadata records)
- **OLD manifest format:**
  - `"prompt"`: string
  - `"name"`: string
  - `"path"`: string
  - ✅ `"model"`: string (PRESENT)
  - ✅ `"vae"`: string (PRESENT)
  - Simpler structure, fewer tracking fields

**Execution Flow:**
```
CLI → run_full_pipeline() → run_txt2img() → _run_txt2img_impl()
```

---

### **Path 2: `run_txt2img_stage()`**

**Location:** [executor.py:3079-3500+](c:\Users\rob\projects\StableNew\src\pipeline\executor.py#L3079)

**Used By:**
- ✅ **PRODUCTION:** `pipeline_runner.run_njr()` (line 291) ← **ALL GUI JOBS USE THIS**
- ✅ **PRODUCTION:** `run_pack_pipeline()` (line 2767)
- ✅ **PRODUCTION:** Learning module via NormalizedJobRecord
- ✅ **PRODUCTION:** All queued jobs from GUI

**Characteristics:**
- Takes separate `prompt` and `negative_prompt` strings
- Handles global prompt term enrichment
- Returns single `dict[str, Any]` (one metadata record)
- **NEW manifest format:**
  - `"original_prompt"`: string
  - `"final_prompt"`: string (with global terms)
  - `"global_positive_applied"`: bool
  - `"global_positive_terms"`: string
  - `"original_negative_prompt"`: string
  - `"final_negative_prompt"`: string
  - `"global_negative_applied"`: bool
  - `"global_negative_terms"`: string
  - ✅ `"model"`: string (FIXED - was missing)
  - ✅ `"vae"`: string (FIXED - was missing)
  - Richer metadata for PromptPack tracking

**Execution Flow:**
```
GUI → PipelineController → JobService → Queue → SingleNodeJobRunner 
    → PipelineRunner.run_njr() → run_txt2img_stage()
```

---

## Why Two Paths Exist

### Historical Evolution

1. **Path 1** was the **original simple pipeline** (pre-v2.0)
   - Single-prompt workflow
   - Basic txt2img → img2img → upscale chain
   - Used by early CLI tools

2. **Path 2** was added for **PromptPack feature** (v2.0+)
   - Multi-prompt batch processing
   - Global positive/negative term injection
   - Variant tracking and matrix randomization
   - Richer metadata for learning system

3. **Nobody consolidated them** when v2.6 NJR architecture was introduced
   - Path 2 became production path (all GUI jobs)
   - Path 1 remained for backward compatibility (CLI only)
   - Duplicate logic diverged over time

---

## The Problem Discovered

### Missing Model/VAE in Production Manifests

**User Report (2026-01-01):**
> "STILL NO MODEL AND VAE!!!!!!!!!!!!!!!!!!!!!!! Even though I've requested you fix this over 5 times now."

**Root Cause:**
- Path 1 (`_run_txt2img_impl`) **HAD** model/VAE query and manifest fields (lines 1423-1426, 1565-1566) ✅
- Path 2 (`run_txt2img_stage`) **FORGOT** to query current model/VAE from WebUI ❌
- Path 2 only extracted from config (lines 3221-3223) but **NEVER added to manifest** ❌
- Production uses Path 2 → all production manifests missing critical fields

**Example Broken Manifest:**
```json
{
  "stage": "txt2img",
  "prompt": "...",
  "config": { "model": "...", "vae": "..." },
  // ❌ NO top-level "model" field
  // ❌ NO top-level "vae" field
  "actual_seed": 3442621591
}
```

**Fix Applied (2026-01-01):**
- Lines 3222-3234: Added WebUI query for actual current model/VAE
- Lines 3378-3379: Added `"model"` and `"vae"` fields to manifest
- Now matches Path 1 behavior ✅

---

## Current Production Usage

### What Actually Uses Each Path?

**Path 1 (`run_txt2img`):**
- ❌ **ONLY:** `src/cli.py` command-line script
- ❌ **NOT USED** by GUI, queue, learning, or any modern feature
- ⚠️ **DEPRECATED** (safe to remove after migration)

**Path 2 (`run_txt2img_stage`):**
- ✅ **ALL GUI JOBS** via `PipelineRunner.run_njr()`
- ✅ **ALL QUEUED JOBS** via `SingleNodeJobRunner`
- ✅ **LEARNING MODULE** via `NormalizedJobRecord` submission
- ✅ **PROMPTPACK EXECUTION** via `run_pack_pipeline()`
- ✅ **100% of production traffic**

**Verification Evidence:**
```python
# GUI job submission path (pipeline_controller.py:1543)
submitted = self._submit_normalized_jobs(...)

# Queue execution path (pipeline_runner.py:49)
def run_njr(self, njr: NormalizedJobRecord, ...) -> PipelineRunResult:
    ...
    result = self._pipeline.run_txt2img_stage(...)  # ← Path 2

# Learning module (job_service.py:356)
def _job_from_njr(self, record: NormalizedJobRecord, ...) -> Job:
    job._normalized_record = record
    # Eventually executes via run_njr() → Path 2
```

**Conclusion:** Path 1 is **effectively dead code** except for CLI.

---

## Consolidation Analysis

### What It Would Take

**Option A: Deprecate Path 1 Entirely** ⭐ RECOMMENDED
1. Remove `run_full_pipeline()` and `run_txt2img()` / `_run_txt2img_impl()`
2. Update `src/cli.py` to build `NormalizedJobRecord` and use `run_njr()`
3. Remove ~300 lines of duplicate code
4. All paths use consistent manifest format

**Benefits:**
- ✅ Single source of truth for txt2img execution
- ✅ Consistent manifests across all execution paths
- ✅ Easier maintenance (one code path to fix/enhance)
- ✅ Reduced test surface

**Risks:**
- ⚠️ CLI script needs minor rewrite (low risk, <50 lines)
- ⚠️ Any external scripts calling `run_full_pipeline()` directly will break

**Option B: Extract Common Logic**
1. Create `_execute_txt2img_api_call()` shared method
2. Both paths call shared method
3. Each path handles its own manifest formatting

**Benefits:**
- ✅ Preserves backward compatibility
- ✅ Reduces code duplication

**Risks:**
- ⚠️ Still maintains two execution paths
- ⚠️ Manifest format divergence continues
- ⚠️ Higher maintenance burden

---

## Recommendations

### Immediate (DONE ✅)
- [x] Fix model/VAE missing from Path 2 manifests
- [x] Document the two paths (this document)

### Short-Term (Next PR)
1. **Deprecate Path 1 entirely** (Option A)
2. Update CLI to use `run_njr()` path
3. Remove `run_full_pipeline()`, `run_txt2img()`, `_run_txt2img_impl()`
4. Add deprecation warnings if any external callers exist

### Long-Term (Architecture)
1. Ensure all execution flows through `PipelineRunner.run_njr()`
2. Standardize on NJR-based execution contract (v2.6+)
3. Document single canonical pipeline path in ARCHITECTURE_v2.6.md

---

## Testing Requirements

Before consolidation:
- ✅ Verify CLI script builds valid NormalizedJobRecord
- ✅ Ensure manifest format matches expectations
- ✅ Test all stage chain combinations (txt2img, img2img, adetailer, upscale)
- ✅ Verify learning module job submission still works
- ✅ Check backward compatibility for any external scripts

---

## Related Documents

- [ARCHITECTURE_v2.6.md](ARCHITECTURE_v2.6.md) - Pipeline execution contract
- [Builder Pipeline Deep-Dive (v2.6).md](Builder%20Pipeline%20Deep-Dive%20%28v2.6%29.md) - NJR lifecycle
- [PR-CORE1-D Roadmap](CORE1-D%20Roadmap%20—%20History%20Integrity,%20Persistence%20Cleanup%28v2.6%29.md) - Queue/history integrity

---

## Appendix: Code Locations

### Path 1 (Legacy)
- **Definition:** `executor.py:1338-1615`
- **Caller:** `executor.py:2457` (`run_full_pipeline`)
- **External:** `cli.py:116`

### Path 2 (Production)
- **Definition:** `executor.py:3079-3500+`
- **Caller (Primary):** `pipeline_runner.py:291` (`run_njr`)
- **Caller (Secondary):** `executor.py:2767` (`run_pack_pipeline`)

### Model/VAE Fix Applied
- **Query WebUI:** `executor.py:3222-3234`
- **Add to Manifest:** `executor.py:3378-3379`

---

**END OF DISCOVERY DOCUMENT**
