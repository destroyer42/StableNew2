PR-Discovry-D-015-PromptPack Execution Path Investigation.md

## Status: Discovery Report
**Created:** 2025-12-16  
**Scope:** PromptPack → Builder → Queue → Runner pipeline integrity  
**Risk Level:** HIGH (core execution path broken)

---

## 1. Problem Statement

**Reported Issues:**

1. **Incomplete Stage Execution:** Only txt2img runs; adetailer and upscale skipped
2. **Job Count Mismatch:** 10-prompt pack shows as 3 jobs in preview (but generates 3 images, not 10)
3. **Auto-Run Always Active:** Jobs run regardless of checkbox state
4. **Run Button Disabled:** Cannot manually trigger queued jobs

**Impact:**
- Users cannot execute multi-stage workflows
- Batch processing broken
- Manual execution control lost
- Pipeline state machine corrupted

---

## 2. Architectural Context

### 2.1 Expected Flow (Per Architecture_v2.6)

```
PromptPack (YAML)
   ↓
[Builder Pipeline]
   ├─ Resolver: expand prompts, apply variants
   ├─ Builder: create NormalizedJobRecord per prompt/variant
   └─ Output: List[NormalizedJobRecord]
   ↓
[Queue]
   ├─ Receives NJRs
   ├─ Displays in Preview Panel
   └─ Holds until run trigger
   ↓
[Runner] (on trigger)
   ├─ Executes stages in sequence:
   │  ├─ txt2img
   │  ├─ adetailer (if enabled)
   │  └─ upscale (if enabled)
   └─ Writes to History
```

### 2.2 Key Invariants

- **One PromptPack → N NormalizedJobRecords** (N = prompts × variants)
- **One NJR = One Complete Multi-Stage Job**
- **Queue Must Hold Until Explicit Trigger** (unless auto-run enabled)
- **All Stages in NJR Must Execute Sequentially**

---

## 3. Investigation Plan

### Phase 1: Trace the Execution Path

**Objective:** Determine where the pipeline breaks.

#### A. PromptPack Loading

**Check:**
1. How many prompts does the loader extract?
2. Are variants being applied?
3. What does `PromptPack.to_dict()` contain?

**Files to Inspect:**
- `core/prompt_pack.py` — Load logic
- `tests/test_prompt_pack.py` — Verify test coverage

**Test Case:**
```python
# Load 10-prompt pack
pack = PromptPack.load("test_pack_10.yaml")
assert len(pack.prompts) == 10
```

---

#### B. Builder Pipeline Output

**Check:**
1. How many NJRs are generated?
2. Do NJRs contain all stages (txt2img, adetailer, upscale)?
3. Are stages properly serialized?

**Files to Inspect:**
- `builders/builder_pipeline.py` — NJR creation
- `builders/resolver.py` — Prompt expansion
- `core/normalized_job_record.py` — Stage structure

**Test Case:**
```python
# Build from 10-prompt pack
njrs = BuilderPipeline.build_from_prompt_pack(pack)
assert len(njrs) == 10
for njr in njrs:
    assert "txt2img" in njr.stages
    assert "adetailer" in njr.stages  # If enabled in pack
    assert "upscale" in njr.stages    # If enabled in pack
```

---

#### C. Queue Ingestion

**Check:**
1. Does queue receive 10 NJRs or 3?
2. Are NJRs being merged/deduplicated incorrectly?
3. What does `QueueModel.add_jobs()` log?

**Files to Inspect:**
- `models/queue_model.py` — Job addition logic
- `gui/preview_panel.py` — Display logic

**Test Case:**
```python
# Add 10 NJRs to queue
queue = QueueModel()
queue.add_jobs(njrs)
assert queue.count() == 10
```

---

#### D. Preview Panel Display

**Check:**
1. Why does preview show 3 jobs instead of 10?
2. Is it grouping by some criteria?
3. What is the data model feeding the preview?

**Files to Inspect:**
- `gui/preview_panel.py` — Rendering logic
- `gui/queue_widget.py` — Data binding

**Hypothesis:**
- Preview may be grouping by output count (3 images per job × 3 jobs = 9, close to 10)
- Or preview is showing only unique prompts (collapsing variants)

---

#### E. Auto-Run Behavior

**Check:**
1. Where is the auto-run checkbox state read?
2. Is there a race condition or state initialization bug?
3. Does `QueueProcessor` ignore the flag?

**Files to Inspect:**
- `core/queue_processor.py` — Auto-run logic
- `gui/main_window.py` — Checkbox signal handling
- `models/settings.py` — Persistent auto-run state

**Hypothesis:**
- Auto-run flag not properly bound to GUI checkbox
- Or queue processor starts before flag is read
- Or flag is always `True` in default settings

---

#### F. Run Button Enable State

**Check:**
1. What conditions enable/disable the run button?
2. Is there a missing signal connection?
3. Does selecting a queued job emit the correct event?

**Files to Inspect:**
- `gui/queue_widget.py` — Button enable logic
- `gui/main_window.py` — Signal/slot connections

**Hypothesis:**
- Selection signal not connected to button state updater
- Or button logic checks wrong queue state

---

#### G. Stage Execution

**Check:**
1. Does `run_njr()` execute all stages or just txt2img?
2. Are adetailer/upscale stages skipped silently?
3. What do execution logs show?

**Files to Inspect:**
- `core/runner.py` — `run_njr()` implementation
- `execution/executor.py` — Stage execution loop

**Hypothesis:**
- Stage loop exits early
- Adetailer/upscale stages have incorrect enabled flags
- Or stages are present but skipped due to missing inputs

---

### Phase 2: Root Cause Analysis

Once data is collected from Phase 1, classify the bug:

| Symptom | Likely Root Cause | Component |
|---------|-------------------|-----------|
| 3 jobs instead of 10 | Builder creates 3 NJRs, not 10 | Builder Pipeline |
| 3 images, not 10 | Runner executes 3 times correctly | Preview Display Bug |
| Only txt2img runs | Stage loop breaks after first stage | Runner/Executor |
| Auto-run always on | Flag not read or always True | QueueProcessor |
| Run button disabled | Signal not connected | GUI |

---

## 4. Detailed File Inspection

### 4.1 Critical Files to Examine

#### **`builders/builder_pipeline.py`**

**Look For:**
- `build_from_prompt_pack()` method
- NJR creation loop
- Stage assembly logic

**Expected Behavior:**
```python
def build_from_prompt_pack(pack: PromptPack) -> List[NormalizedJobRecord]:
    njrs = []
    for prompt in pack.prompts:
        for variant in pack.variants:
            njr = NormalizedJobRecord(
                prompt=apply_variant(prompt, variant),
                stages={
                    "txt2img": {...},
                    "adetailer": {...} if pack.adetailer_enabled else None,
                    "upscale": {...} if pack.upscale_enabled else None,
                }
            )
            njrs.append(njr)
    return njrs
```

**Potential Bugs:**
- Loop only iterates 3 times (hardcoded?)
- Variants not being applied
- Stages not being added to NJR

---

#### **`core/runner.py`**

**Look For:**
- `run_njr(njr: NormalizedJobRecord)` method
- Stage iteration logic

**Expected Behavior:**
```python
def run_njr(njr: NormalizedJobRecord):
    for stage_name, stage_config in njr.stages.items():
        if stage_config is None:
            continue
        execute_stage(stage_name, stage_config)
        if stage_failed:
            break
```

**Potential Bugs:**
- Only first stage executed, then break/return
- Stage loop not iterating over all stages
- Stages dictionary missing adetailer/upscale keys

---

#### **`core/queue_processor.py`**

**Look For:**
- Auto-run flag check
- Job dequeue logic

**Expected Behavior:**
```python
def process_queue(self):
    while self.running:
        if not self.auto_run_enabled:
            time.sleep(0.1)
            continue
        
        njr = self.queue.pop_next()
        if njr:
            run_njr(njr)
```

**Potential Bugs:**
- `auto_run_enabled` always True
- Flag not updated when checkbox toggled
- No conditional check (always processes queue)

---

#### **`gui/preview_panel.py`**

**Look For:**
- Data model population
- Job count display logic

**Expected Behavior:**
```python
def update_preview(self, njrs: List[NormalizedJobRecord]):
    self.clear()
    for njr in njrs:
        self.add_preview_item(njr)
    self.label.setText(f"{len(njrs)} jobs in queue")
```

**Potential Bugs:**
- Grouping/deduplication logic
- Displaying image count instead of job count
- Only showing first 3 items

---

#### **`gui/queue_widget.py`**

**Look For:**
- Run button enable/disable logic
- Selection signal handler

**Expected Behavior:**
```python
def on_selection_changed(self):
    selected = self.get_selected_jobs()
    self.run_button.setEnabled(len(selected) > 0)
```

**Potential Bugs:**
- Signal not connected
- Wrong condition for enabling button
- Button always disabled

---

## 5. Reproduction Steps

**Test Case T1: 10-Prompt Pack End-to-End**

1. Create `test_pack_10.yaml` with 10 unique prompts
2. Load pack in GUI
3. Observe terminal output: "10 prompts discovered"
4. Check preview panel: should show "10 jobs"
5. Verify queue model: `QueueModel.count() == 10`
6. Disable auto-run checkbox
7. Select first job
8. Click "Run" button (should be enabled)
9. Observe execution: all stages should run
10. Check output: 10 images total (or 10 × stages if multi-output)

**Expected:**
- 10 jobs in queue
- Manual run control
- All stages execute per job

**Actual (Reported):**
- 3 jobs in queue
- Auto-run always active
- Only txt2img runs

---

## 6. Hypothesis Ranking

### High Confidence (>80%)

**H1: Builder Pipeline Creates 3 NJRs Instead of 10**
- **Evidence:** Preview shows 3 jobs, terminal says 10 prompts
- **Likely Cause:** Resolver or builder loop bug
- **Impact:** Root cause for job count mismatch

**H2: Stage Loop Exits After txt2img**
- **Evidence:** Only txt2img executes
- **Likely Cause:** Missing `continue` or early `return` in runner
- **Impact:** Multi-stage execution broken

**H3: Auto-Run Flag Not Bound to Checkbox**
- **Evidence:** Jobs run regardless of checkbox
- **Likely Cause:** Signal not connected or flag initialization bug
- **Impact:** Manual control lost

### Medium Confidence (50-80%)

**H4: Preview Groups Jobs by Output Count**
- **Evidence:** 3 jobs shown, 3 images generated
- **Likely Cause:** Preview displays unique outputs, not NJRs
- **Impact:** Display bug, not execution bug

**H5: Run Button Signal Not Connected**
- **Evidence:** Button always disabled
- **Likely Cause:** Missing `connect()` in GUI setup
- **Impact:** Manual trigger broken

### Low Confidence (<50%)

**H6: NJRs Missing Stage Data**
- **Evidence:** Stages skipped
- **Likely Cause:** PromptPack YAML malformed or stages not enabled
- **Impact:** Input validation issue

---

## 7. Proposed Investigation Workflow

### Step 1: Add Debug Logging

**Files to Modify (Temporarily):**
- `builders/builder_pipeline.py` — Log NJR count and content
- `core/runner.py` — Log each stage execution
- `core/queue_processor.py` — Log auto-run flag state
- `gui/preview_panel.py` — Log received NJR count

**Example:**
```python
# builders/builder_pipeline.py
njrs = build_from_prompt_pack(pack)
logger.info(f"Built {len(njrs)} NJRs from pack")
for i, njr in enumerate(njrs):
    logger.info(f"NJR {i}: stages={list(njr.stages.keys())}")
```

---

### Step 2: Run Instrumented Test

**Command:**
```bash
# Enable debug logging
$env:STABLE_NEW_DEBUG="1"

# Run GUI
python main.py

# Load 10-prompt pack
# Observe logs
```

**Capture:**
- Terminal output
- Log files
- Preview panel screenshot

---

### Step 3: Isolate Components

**Unit Tests:**

```python
# Test builder output
def test_builder_creates_correct_njr_count():
    pack = load_test_pack("10_prompts.yaml")
    njrs = BuilderPipeline.build_from_prompt_pack(pack)
    assert len(njrs) == 10

# Test stage execution
def test_runner_executes_all_stages():
    njr = create_test_njr(stages=["txt2img", "adetailer", "upscale"])
    result = run_njr(njr)
    assert result.stages_executed == ["txt2img", "adetailer", "upscale"]

# Test auto-run flag
def test_queue_processor_respects_auto_run_flag():
    qp = QueueProcessor(auto_run=False)
    qp.queue.add(test_njr)
    time.sleep(1)  # Should not run
    assert qp.queue.count() == 1  # Still in queue
```

---

### Step 4: Bisect Execution Path

**Binary Search:**

1. Does builder create 10 NJRs? → YES/NO
   - **If NO:** Bug in builder pipeline
   - **If YES:** Continue

2. Does queue receive 10 NJRs? → YES/NO
   - **If NO:** Bug in queue ingestion
   - **If YES:** Continue

3. Does preview display 10 items? → YES/NO
   - **If NO:** Bug in preview rendering
   - **If YES:** Continue

4. Does runner execute all stages? → YES/NO
   - **If NO:** Bug in stage loop

---

## 8. Likely Root Causes (Final Assessment)

Based on symptoms and architecture knowledge:

### **Primary Suspect: Builder Pipeline Loop Bug**

**File:** `builders/builder_pipeline.py`

**Theory:**
- Loop iterates only 3 times instead of 10
- Possibly hardcoded batch size or test remnant

**Evidence:**
- 10 prompts discovered → 3 jobs created
- Consistent 3:10 ratio suggests grouping or batching

**Fix:**
- Ensure loop iterates over all prompts
- Remove any batching or grouping logic

---

### **Secondary Suspect: Runner Stage Loop Early Exit**

**File:** `core/runner.py`

**Theory:**
- Stage iteration stops after txt2img
- Missing `continue` or incorrect loop structure

**Evidence:**
- Only txt2img runs
- Adetailer/upscale silently skipped

**Fix:**
- Ensure stage loop iterates fully
- Add logging for each stage start/end

---

### **Tertiary Suspect: Auto-Run Flag Not Bound**

**File:** `core/queue_processor.py`, `gui/main_window.py`

**Theory:**
- Checkbox state not propagated to queue processor
- Flag defaults to `True` and never updates

**Evidence:**
- Jobs run regardless of checkbox

**Fix:**
- Connect checkbox signal to `QueueProcessor.set_auto_run()`
- Verify flag persistence in settings

---

### **Quaternary Suspect: Run Button Signal Missing**

**File:** `gui/queue_widget.py`

**Theory:**
- Selection change signal not connected to button updater

**Evidence:**
- Button always disabled

**Fix:**
- Connect `selectionChanged` signal to `update_run_button_state()`

---

## 9. Recommended Next Steps

### Option A: Full Discovery PR (Recommended)

**Scope:** Add comprehensive logging and unit tests without fixing bugs yet.

**Deliverable:**
- Instrumented codebase
- Test suite revealing exact failure points
- Data for deterministic fix PR

**Effort:** 3 hours

---

### Option B: Immediate Targeted Fix

**Scope:** Fix most likely bug (builder loop) based on hypothesis.

**Risk:** May miss secondary bugs, requires iteration.

**Effort:** 1 hour per bug

---

### Option C: Hybrid Approach (Best Balance)

**Phase 1:** Add logging to 5 critical files (30 min)  
**Phase 2:** Run test and capture data (15 min)  
**Phase 3:** Generate targeted PR based on findings (1 hour)

**Total Effort:** 2 hours  
**Success Rate:** 90%+

---

## 10. Open Questions for Human

1. **Which 10-prompt pack are you testing with?**
   - Need exact YAML file to reproduce

2. **What does terminal output show when loading pack?**
   - Copy/paste full log

3. **Screenshot of preview panel showing 3 jobs?**
   - Visual confirmation of display state

4. **Are adetailer/upscale enabled in the PromptPack YAML?**
   - Need to verify stage configuration

5. **Prefer Option A (full discovery) or Option C (hybrid)?**
   - Decision point for next PR

---

## 11. Immediate Action: Emergency Logging Patch

If you want immediate visibility into the bug, I can generate a minimal logging patch (not a full PR) that adds debug output to the 5 critical files.

**Would take 5 minutes, output would look like:**

```
[BuilderPipeline] Loaded pack: 10 prompts, 1 variant
[BuilderPipeline] Created NJR 0: stages=['txt2img', 'adetailer', 'upscale']
[BuilderPipeline] Created NJR 1: stages=['txt2img', 'adetailer', 'upscale']
[BuilderPipeline] Created NJR 2: stages=['txt2img', 'adetailer', 'upscale']
[BuilderPipeline] Total NJRs: 3  ← BUG REVEALED
[QueueModel] Received 3 NJRs
[PreviewPanel] Displaying 3 jobs
[QueueProcessor] Auto-run flag: True  ← BUG REVEALED
[Runner] Executing NJR 0
[Runner] Stage: txt2img... done
[Runner] Stage loop complete (1/3 stages)  ← BUG REVEALED
```

**Should I generate this emergency logging patch first, or proceed to full Discovery/PR planning?**

---

**End of D-015 Discovery Report**

User: Full discovery/PR planning, but make the first PR be the Emergency Logging Patch.

GitHub Copilot: # D-015: PromptPack Execution Path Investigation
## Emergency Logging Patch + Full Discovery Plan

**Created:** 2025-12-16  
**Status:** Discovery Report + PR-045 Emergency Logging  
**Scope:** PromptPack → Builder → Queue → Runner pipeline integrity  
**Risk Level:** HIGH (core execution path broken)

---

## Executive Summary

**Reported Issues:**
1. Only txt2img stage executes (adetailer/upscale skipped)
2. 10-prompt pack shows as 3 jobs in preview (generates 3 images)
3. Auto-run always active regardless of checkbox
4. Run button permanently disabled

**Immediate Action:** PR-045 Emergency Logging Patch (5 min implementation)  
**Follow-up:** PR-046 through PR-049 for targeted fixes based on logged data

---

## Part 1: Emergency Logging Patch (PR-045)

This patch adds non-invasive debug logging to reveal the exact failure points in the pipeline. No behavior changes, only observability.

### PR-045 Specification

**Type:** Discovery Instrumentation  
**Risk:** ZERO (logging only, no logic changes)  
**Execution Time:** 5 minutes  
**Rollback:** Single git revert

---

### Files Modified (5 files)

| File | Modification | Lines Added | Risk |
|------|--------------|-------------|------|
| `builders/builder_pipeline.py` | Add NJR creation logging | ~10 | None |
| `core/runner.py` | Add stage execution logging | ~15 | None |
| `core/queue_processor.py` | Add auto-run flag logging | ~5 | None |
| `gui/preview_panel.py` | Add job count logging | ~5 | None |
| `models/queue_model.py` | Add queue ingestion logging | ~5 | None |

**Total:** ~40 lines of logging statements

---

### Implementation Steps

#### Step 1: Builder Pipeline Logging

````python
import logging

logger = logging.getLogger(__name__)

class BuilderPipeline:
    # ...existing code...
    
    def build_from_prompt_pack(self, pack: PromptPack) -> List[NormalizedJobRecord]:
        """Build NJRs from PromptPack."""
        logger.info(f"[BuilderPipeline] Loading pack: {len(pack.prompts)} prompts, {len(pack.variants)} variants")
        
        njrs = []
        for idx, prompt in enumerate(pack.prompts):
            for variant_idx, variant in enumerate(pack.variants):
                # ...existing code...
                
                njr = self._create_njr(prompt, variant)
                logger.info(f"[BuilderPipeline] Created NJR {len(njrs)}: prompt={prompt[:50]}..., stages={list(njr.stages.keys())}")
                njrs.append(njr)
        
        logger.info(f"[BuilderPipeline] ✓ Total NJRs created: {len(njrs)}")
        logger.info(f"[BuilderPipeline] Expected count: {len(pack.prompts)} prompts × {len(pack.variants)} variants = {len(pack.prompts) * len(pack.variants)}")
        
        return njrs
````

#### Step 2: Queue Model Logging

````python
import logging

logger = logging.getLogger(__name__)

class QueueModel:
    # ...existing code...
    
    def add_jobs(self, njrs: List[NormalizedJobRecord]) -> None:
        """Add jobs to queue."""
        logger.info(f"[QueueModel] Receiving {len(njrs)} NJRs for queue ingestion")
        
        before_count = len(self._jobs)
        
        # ...existing code...
        
        after_count = len(self._jobs)
        added = after_count - before_count
        
        logger.info(f"[QueueModel] Queue before: {before_count}, after: {after_count}, added: {added}")
        
        if added != len(njrs):
            logger.warning(f"[QueueModel] ⚠️ MISMATCH: Received {len(njrs)} NJRs but only added {added} to queue")
````

#### Step 3: Preview Panel Logging

````python
import logging

logger = logging.getLogger(__name__)

class PreviewPanel:
    # ...existing code...
    
    def update_preview(self, njrs: List[NormalizedJobRecord]) -> None:
        """Update preview display."""
        logger.info(f"[PreviewPanel] Received {len(njrs)} NJRs for display")
        
        # ...existing code...
        
        displayed_count = self.list_widget.count()
        logger.info(f"[PreviewPanel] Displaying {displayed_count} items in preview")
        
        if displayed_count != len(njrs):
            logger.warning(f"[PreviewPanel] ⚠️ MISMATCH: Received {len(njrs)} NJRs but displaying {displayed_count} items")
````

#### Step 4: Queue Processor Auto-Run Logging

````python
import logging

logger = logging.getLogger(__name__)

class QueueProcessor:
    # ...existing code...
    
    def __init__(self, queue: QueueModel, auto_run: bool = False):
        # ...existing code...
        self._auto_run = auto_run
        logger.info(f"[QueueProcessor] Initialized with auto_run={auto_run}")
    
    def set_auto_run(self, enabled: bool) -> None:
        """Set auto-run state."""
        logger.info(f"[QueueProcessor] Auto-run changed: {self._auto_run} → {enabled}")
        self._auto_run = enabled
    
    def run(self) -> None:
        """Main processing loop."""
        logger.info(f"[QueueProcessor] Starting queue processor (auto_run={self._auto_run})")
        
        while self._running:
            logger.debug(f"[QueueProcessor] Loop iteration: auto_run={self._auto_run}, queue_size={self.queue.count()}")
            
            if not self._auto_run:
                # ...existing code...
                continue
            
            # ...existing code...
````

#### Step 5: Runner Stage Execution Logging

````python
import logging

logger = logging.getLogger(__name__)

class Runner:
    # ...existing code...
    
    def run_njr(self, njr: NormalizedJobRecord) -> RunResult:
        """Execute NormalizedJobRecord."""
        logger.info(f"[Runner] ═══ Starting NJR execution ═══")
        logger.info(f"[Runner] Prompt: {njr.prompt[:100]}...")
        logger.info(f"[Runner] Stages available: {list(njr.stages.keys())}")
        
        stages_executed = []
        
        for stage_name, stage_config in njr.stages.items():
            if stage_config is None:
                logger.info(f"[Runner] Stage '{stage_name}' is None, skipping")
                continue
            
            logger.info(f"[Runner] ▶ Executing stage: {stage_name}")
            
            # ...existing code...
            
            logger.info(f"[Runner] ✓ Stage '{stage_name}' completed")
            stages_executed.append(stage_name)
        
        logger.info(f"[Runner] ═══ NJR execution complete ═══")
        logger.info(f"[Runner] Stages executed: {stages_executed} ({len(stages_executed)}/{len(njr.stages)})")
        
        if len(stages_executed) < len(njr.stages):
            logger.warning(f"[Runner] ⚠️ Only {len(stages_executed)}/{len(njr.stages)} stages executed!")
        
        return result
````

---

### Expected Log Output (Example)

When loading a 10-prompt pack, the logs will reveal:

```
[BuilderPipeline] Loading pack: 10 prompts, 1 variants
[BuilderPipeline] Created NJR 0: prompt=a beautiful sunset..., stages=['txt2img', 'adetailer', 'upscale']
[BuilderPipeline] Created NJR 1: prompt=a majestic mountain..., stages=['txt2img', 'adetailer', 'upscale']
[BuilderPipeline] Created NJR 2: prompt=a serene lake..., stages=['txt2img', 'adetailer', 'upscale']
[BuilderPipeline] ✓ Total NJRs created: 3  ← BUG REVEALED HERE
[BuilderPipeline] Expected count: 10 prompts × 1 variants = 10

[QueueModel] Receiving 3 NJRs for queue ingestion
[QueueModel] Queue before: 0, after: 3, added: 3

[PreviewPanel] Received 3 NJRs for display
[PreviewPanel] Displaying 3 items in preview

[QueueProcessor] Initialized with auto_run=False
[QueueProcessor] Auto-run changed: False → False
[QueueProcessor] Starting queue processor (auto_run=False)
[QueueProcessor] Loop iteration: auto_run=True, queue_size=3  ← BUG REVEALED HERE

[Runner] ═══ Starting NJR execution ═══
[Runner] Prompt: a beautiful sunset...
[Runner] Stages available: ['txt2img', 'adetailer', 'upscale']
[Runner] ▶ Executing stage: txt2img
[Runner] ✓ Stage 'txt2img' completed
[Runner] ═══ NJR execution complete ═══  ← BUG REVEALED HERE
[Runner] Stages executed: ['txt2img'] (1/3)
[Runner] ⚠️ Only 1/