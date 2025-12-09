# PR-CORE-D Implementation Analysis & Gap Assessment
## StableNew v2.6 GUI V2 Recovery & PromptPack-Only Alignment

**Date**: 2025-12-08  
**Author**: GitHub Copilot (Analysis Agent)  
**Status**: Implementation Planning  
**Depends on**: PR-CORE-A, PR-CORE-B, PR-CORE-C

---

## Executive Summary

This document provides a comprehensive analysis of the current StableNew GUI V2 implementation against PR-CORE-D requirements. The analysis reveals that **the GUI V2 architecture is largely aligned with PromptPack-Only principles**, but requires targeted enhancements to fully comply with PR-CORE-D specifications.

**Key Findings**:
- ✅ **No free-text prompt entry fields** exist in Pipeline Panel (already compliant)
- ✅ **UnifiedJobSummary** and **NormalizedJobRecord** models are already defined and partially integrated
- ✅ Preview Panel already uses job summary structures
- ⚠️ **AppState V2 requires PromptPack-specific tracking fields** (current_pack exists but insufficient)
- ⚠️ Queue and Running Job panels need **lifecycle event subscription** integration
- ⚠️ History Panel needs **NormalizedJobRecord metadata** display enhancements
- ⚠️ Controllers need **PromptPack-only validation** at job submission boundaries

---

## 1. Current Architecture State

### 1.1 Existing Files Analyzed

| Component | File Path | Status |
|-----------|-----------|--------|
| App State | `src/gui/app_state_v2.py` | ✅ Exists, needs enhancement |
| Pipeline Panel | `src/gui/pipeline_panel_v2.py` | ✅ Compliant (no free-text prompts) |
| Preview Panel | `src/gui/preview_panel_v2.py` | ✅ Uses UnifiedJobSummary |
| Queue Panel | `src/gui/panels_v2/queue_panel_v2.py` | ⚠️ Needs lifecycle event integration |
| Running Job Panel | `src/gui/panels_v2/running_job_panel_v2.py` | ⚠️ Needs UnifiedJobSummary integration |
| History Panel | `src/gui/panels_v2/history_panel_v2.py` | ⚠️ Needs NormalizedJobRecord metadata |
| Pipeline Controller | `src/controller/pipeline_controller.py` | ⚠️ Needs PromptPack-only enforcement |
| Job Service | `src/controller/job_service.py` | ❓ Not yet analyzed |

### 1.2 Data Models Status

**Already Defined** (in `src/pipeline/job_models_v2.py`):
- ✅ `NormalizedJobRecord` - Full job specification with PromptPack provenance
- ✅ `UnifiedJobSummary` - GUI-facing summary DTO
- ✅ `QueueJobV2` - Queue item wrapper
- ✅ `JobHistoryItemDTO` - History entry structure
- ✅ `JobLifecycleLogEvent` - Lifecycle event structure

**These models match PR-CORE-A requirements.**

---

## 2. Gap Analysis by Subsystem

### 2.1 AppState V2 (`src/gui/app_state_v2.py`)

#### Current State
```python
@dataclass
class AppStateV2:
    prompt: str = ""  # ⚠️ LEGACY - should be removed
    negative_prompt: str = ""  # ⚠️ LEGACY - should be removed
    current_pack: Optional[str] = None  # ✅ Exists but insufficient
    preview_jobs: list[NormalizedJobRecord] = field(default_factory=list)  # ✅ Good
    log_events: list[JobLifecycleLogEvent] = field(default_factory=list)  # ✅ Good
```

#### Required Changes (PR-CORE-D §5.6)
1. **Add PromptPack tracking fields**:
   ```python
   selected_prompt_pack_id: Optional[str] = None
   selected_prompt_pack_name: Optional[str] = None
   selected_config_snapshot_id: Optional[str] = None
   last_unified_job_summary: Optional[UnifiedJobSummary] = None
   ```

2. **Deprecate legacy prompt fields**:
   - Mark `prompt` and `negative_prompt` as deprecated
   - Add migration warnings if these are accessed
   - Eventually remove after confirming no usage

3. **Add setters with notifications**:
   ```python
   def set_selected_prompt_pack(self, pack_id: str, pack_name: str) -> None
   def set_selected_config_snapshot(self, snapshot_id: str) -> None
   def set_last_unified_job_summary(self, summary: UnifiedJobSummary) -> None
   ```

#### Priority: **HIGH** (foundational for all other changes)

---

### 2.2 Pipeline Panel (`src/gui/pipeline_panel_v2.py`)

#### Current State
✅ **Already compliant** - No free-text prompt entry fields exist.

The panel displays:
- Read-only prompt pack name label
- Read-only row index label
- Read-only positive/negative preview labels
- Stage cards (which handle config, not prompts)

#### Observations
```python
# Lines 51-72: Read-only summary display
self.pack_label = ttk.Label(summary_frame, text="Prompt Pack: –", ...)
self.row_label = ttk.Label(summary_frame, text="Row: –", ...)
self.positive_preview_label = ttk.Label(...)
self.negative_preview_label = ttk.Label(...)
```

#### Required Changes
**None** - Panel is already PromptPack-only compliant.

#### Enhancement Opportunity (Optional)
- Add visual indicator when PromptPack is **not** selected (disable run buttons)
- Display variant/batch count when randomization is enabled

#### Priority: **LOW** (already compliant)

---

### 2.3 Preview Panel (`src/gui/preview_panel_v2.py`)

#### Current State
✅ **Partially compliant** - Uses `UnifiedJobSummary` and `NormalizedJobRecord`.

```python
# Lines 34-36: Good integration
def set_jobs(self, jobs: list[Any]) -> None:
    """Update preview from a list of NormalizedJobRecord objects."""
    self.set_preview_jobs(jobs)
```

#### Required Changes (PR-CORE-D §5.1.3)
1. **Ensure UnifiedJobSummary-only rendering**:
   - Verify `_update_from_job_summaries` method uses only summary fields
   - No reconstruction of prompts from config dicts

2. **Add PromptPack provenance display**:
   - Show `prompt_pack_name` explicitly
   - Show `prompt_pack_row_index` explicitly
   - Show matrix slot values (if randomization enabled)

3. **Add stage chain visualization**:
   ```python
   def _format_stage_chain(self, summary: UnifiedJobSummary) -> str:
       """Format stage chain as human-friendly labels."""
       # e.g., "txt2img → img2img → adetailer → upscale"
   ```

#### Priority: **MEDIUM** (functional but needs metadata display enhancements)

---

### 2.4 Queue Panel (`src/gui/panels_v2/queue_panel_v2.py`)

#### Current State
⚠️ **Needs lifecycle event integration**.

Currently displays `QueueJobV2` objects but does not subscribe to lifecycle events.

```python
# Lines 52-53: Has summaries field but not fully utilized
self._summaries: list[UnifiedJobSummary] = []
```

#### Required Changes (PR-CORE-D §5.2)
1. **Subscribe to job lifecycle events**:
   ```python
   def _bind_app_state(self) -> None:
       if self.app_state:
           self.app_state.subscribe("log_events", self._on_lifecycle_event)
   ```

2. **Update display on lifecycle events**:
   - `SUBMITTED` → Add to queue list
   - `QUEUED` → Update status indicator
   - `RUNNING` → Highlight running job
   - `CANCELLED` → Remove from queue

3. **Render UnifiedJobSummary fields**:
   ```python
   def _format_queue_item(self, summary: UnifiedJobSummary) -> str:
       """Format queue item with PromptPack metadata."""
       return (f"{summary.prompt_pack_name} "
               f"[Row {summary.prompt_pack_row_index + 1}] "
               f"Variant {summary.variant_index} "
               f"Seed: {summary.seed}")
   ```

4. **Show PromptPack provenance in queue items**:
   - Pack name
   - Row index
   - Variant/batch indices
   - Stage chain summary

#### Priority: **HIGH** (core workflow integration)

---

### 2.5 Running Job Panel (`src/gui/panels_v2/running_job_panel_v2.py`)

#### Current State
⚠️ **Uses QueueJobV2 but needs UnifiedJobSummary integration**.

```python
# Line 39: Uses QueueJobV2 directly
self._current_job: QueueJobV2 | None = None
```

#### Required Changes (PR-CORE-D §5.3)
1. **Use UnifiedJobSummary for display**:
   ```python
   self._current_job_summary: UnifiedJobSummary | None = None
   ```

2. **Display PromptPack metadata**:
   - PromptPack name & row
   - Stage chain with current stage highlighting
   - Seeds and matrix slot values
   - Execution timestamps

3. **Stage progress visualization**:
   ```python
   def _update_stage_progress(self, current_stage: str) -> None:
       """Highlight current stage in stage chain display."""
       # txt2img [RUNNING] → img2img → adetailer → upscale
   ```

4. **Subscribe to lifecycle events**:
   - Update on `RUNNING` → show job
   - Update on `COMPLETED` / `FAILED` → clear display

#### Priority: **HIGH** (critical for user feedback)

---

### 2.6 History Panel (`src/gui/panels_v2/history_panel_v2.py`)

#### Current State
⚠️ **Uses JobHistoryItemDTO but lacks NormalizedJobRecord metadata display**.

```python
# Lines 98-102: Basic display
display_text = f"[{timestamp}] {dto.label} ({dto.total_images} images)"
```

#### Required Changes (PR-CORE-D §5.4)
1. **Display canonical NormalizedJobRecord-derived summaries**:
   - Pack name
   - Prompt preview
   - Negative preview
   - Model & sampler
   - `variant_index` and `batch_index`
   - Stage chain summary
   - Execution timestamps
   - Failure message (if applicable)

2. **Add drilldown/details view**:
   ```python
   def _on_item_double_click(self, event) -> None:
       """Open detailed view of selected history entry."""
       # Display full UnifiedJobSummary
       # Display full NormalizedJobRecord details (read-only)
       # Show output image list
   ```

3. **Integrate with Debug Hub** (optional):
   - "Explain Job" button on history items
   - Opens Debug Hub with selected job context

#### Priority: **MEDIUM** (important for debugging/learning but not blocking)

---

### 2.7 Pipeline Controller (`src/controller/pipeline_controller.py`)

#### Current State
⚠️ **Exists but needs PromptPack-only validation**.

The controller already has job building logic but does not enforce PromptPack-only constraint at submission boundaries.

```python
# Lines 73-113: Legacy job building without PromptPack enforcement
def _build_job(
    self,
    config: PipelineConfig,
    *,
    prompt_pack_id: str | None = None,  # ⚠️ Optional - should be REQUIRED
    ...
) -> Job:
```

#### Required Changes (PR-CORE-D §5.1.2 + §8)
1. **Enforce PromptPack-only at job submission**:
   ```python
   def build_and_run_jobs(
       self,
       prompt_pack_id: str,  # REQUIRED, not Optional
       config_snapshot_id: str,
       runtime_overrides: dict[str, Any] | None = None
   ) -> None:
       """Build jobs from PromptPack (PromptPack-only enforcement)."""
       if not prompt_pack_id:
           self._emit_error("PromptPack not selected. Cannot build jobs.")
           return
       
       # Call PR-CORE-B builder pipeline
       jobs = self._builder.build_jobs_from_pack(
           prompt_pack_id=prompt_pack_id,
           config_snapshot_id=config_snapshot_id,
           runtime_overrides=runtime_overrides
       )
       
       # Submit to JobService
       self._job_service.submit_jobs(jobs)
   ```

2. **Disable run controls until PromptPack selected**:
   ```python
   def _update_run_button_state(self) -> None:
       """Disable run button if no PromptPack selected."""
       has_pack = bool(self.app_state.selected_prompt_pack_id)
       has_config = bool(self.app_state.selected_config_snapshot_id)
       self.run_button.config(state="normal" if (has_pack and has_config) else "disabled")
   ```

3. **Add validation callbacks**:
   - Check PromptPack selection before enabling "Run Now"
   - Check config snapshot selection
   - Display clear error messages in GUI

#### Priority: **CRITICAL** (enforcement point for architecture)

---

### 2.8 Job Service (`src/controller/job_service.py`)

#### Current State
❓ **Not yet analyzed** - Needs inspection for PR-CORE-C compliance.

#### Required Changes (PR-CORE-C §A)
1. **Validate NormalizedJobRecord at submission**:
   - Reject jobs without `prompt_pack_id`
   - Reject jobs with missing required fields
   - Return structured errors

2. **Emit lifecycle events**:
   - `SUBMITTED` when jobs are accepted
   - `QUEUED` when jobs enter queue
   - Forward `RUNNING` / `COMPLETED` / `FAILED` events from runner

#### Priority: **CRITICAL** (enforcement layer for PR-CORE-C)

---

## 3. Implementation Roadmap

### Phase 1: AppState & Data Flow (Week 1)
**Goal**: Establish PromptPack tracking in AppState V2.

1. **Update `app_state_v2.py`**:
   - Add `selected_prompt_pack_id` / `selected_prompt_pack_name`
   - Add `selected_config_snapshot_id`
   - Add `last_unified_job_summary`
   - Add setters with notifications
   - Deprecate `prompt` and `negative_prompt`

2. **Tests**:
   - Unit test AppState setters
   - Verify listener notifications

**Deliverable**: `src/gui/app_state_v2.py` updated with PromptPack tracking.

---

### Phase 2: Controller Enforcement (Week 1-2)
**Goal**: Enforce PromptPack-only at controller boundary.

1. **Update `pipeline_controller.py`**:
   - Make `prompt_pack_id` required in job building
   - Add validation method
   - Add error emission for missing PromptPack
   - Integrate with PR-CORE-B builder (when available)

2. **Update run button logic**:
   - Disable until PromptPack selected
   - Display tooltip explaining requirement

3. **Tests**:
   - Test PromptPack validation
   - Test run button state changes
   - Test error messages

**Deliverable**: Controller enforces PromptPack-only invariant.

---

### Phase 3: Queue & Running Job Panels (Week 2)
**Goal**: Integrate lifecycle events and UnifiedJobSummary rendering.

1. **Update `queue_panel_v2.py`**:
   - Subscribe to lifecycle events
   - Render UnifiedJobSummary fields
   - Update display on `SUBMITTED` / `QUEUED` / `RUNNING` / `CANCELLED`

2. **Update `running_job_panel_v2.py`**:
   - Use UnifiedJobSummary for display
   - Show PromptPack metadata
   - Add stage chain visualization
   - Subscribe to lifecycle events

3. **Tests**:
   - Test lifecycle event handling
   - Test UnifiedJobSummary rendering
   - Test stage progress updates

**Deliverable**: Queue and Running Job panels reflect real-time job state.

---

### Phase 4: Preview & History Enhancements (Week 2-3)
**Goal**: Enhance metadata display and drilldown capabilities.

1. **Update `preview_panel_v2.py`**:
   - Add PromptPack provenance display
   - Add matrix slot values display
   - Add stage chain visualization

2. **Update `history_panel_v2.py`**:
   - Display NormalizedJobRecord metadata
   - Add drilldown/details view
   - Integrate with Debug Hub (optional)

3. **Tests**:
   - Test metadata display
   - Test drilldown view
   - Test history item formatting

**Deliverable**: Preview and History panels show complete job metadata.

---

### Phase 5: Integration & E2E Testing (Week 3)
**Goal**: Verify end-to-end PromptPack-only workflow.

1. **Golden Path E2E Tests** (PR-CORE-D §7.2):
   - Test: Angelic Warriors E2E
   - Test: Mythical Beasts Randomization

2. **Integration Tests**:
   - Test full workflow: Select Pack → Preview → Run → Queue → Running → History
   - Test lifecycle event propagation
   - Test UnifiedJobSummary consistency across panels

3. **Documentation**:
   - Update ARCHITECTURE_v2.6.md
   - Update CHANGELOG.md
   - Create migration guide for legacy prompt fields

**Deliverable**: Full E2E compliance with PR-CORE-D.

---

## 4. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Legacy code still uses `prompt` / `negative_prompt` fields | HIGH | Add deprecation warnings; audit all references |
| Controller cannot enforce PromptPack-only without PR-CORE-B | CRITICAL | Coordinate with PR-CORE-B implementation timeline |
| Lifecycle events not emitted by JobService | HIGH | Implement PR-CORE-C first or in parallel |
| GUI performance degradation with large queue | MEDIUM | Optimize listbox rendering; implement pagination |
| Breaking changes for existing users | MEDIUM | Provide migration script; document changes clearly |

---

## 5. Acceptance Criteria Checklist

Per PR-CORE-D §8:

- [ ] UI contains no free-text prompt fields ✅ (already compliant)
- [ ] Pipeline Tab run controls disabled until PromptPack selected
- [ ] All panels use UnifiedJobSummary exclusively
- [ ] Queue Panel correctly reflects lifecycle transitions
- [ ] Running Job Panel displays accurate active job metadata
- [ ] History shows complete PromptPack provenance
- [ ] Debug Hub "Explain Job" works identically across all job sources
- [ ] GUI never reconstructs any prompt or config
- [ ] All tests pass

---

## 6. Open Questions

1. **Does PR-CORE-B builder exist yet?**
   - If not, Phase 2 will need to mock builder interface
   - Coordinate implementation timeline

2. **Does JobService emit lifecycle events?**
   - If not, Phase 3 will be blocked
   - PR-CORE-C must be implemented first or in parallel

3. **How should legacy `prompt` / `negative_prompt` fields be migrated?**
   - Gradual deprecation vs. immediate removal?
   - Need migration guide for users

4. **Should Debug Hub integration be in scope?**
   - PR-CORE-D mentions it but doesn't detail implementation
   - Defer to separate PR?

---

## 7. Recommended Next Steps

1. ✅ **Immediate**: Review this analysis with Rob and ChatGPT planner
2. ⏭️ **Week 1**: Implement Phase 1 (AppState updates)
3. ⏭️ **Week 1-2**: Implement Phase 2 (Controller enforcement) **pending PR-CORE-B**
4. ⏭️ **Week 2**: Implement Phase 3 (Queue/Running Job panels) **pending PR-CORE-C**
5. ⏭️ **Week 2-3**: Implement Phase 4 (Preview/History enhancements)
6. ⏭️ **Week 3**: Integration testing & documentation

---

## End of Analysis

**This document is a living analysis and will be updated as implementation progresses.**

**Next Action**: Review with stakeholders and approve implementation roadmap.
