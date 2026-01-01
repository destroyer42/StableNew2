# Learning System Roadmap v2.6

**Status:** CANONICAL  
**Last Updated:** 2025-01-XX  
**Author:** StableNew Planning Team

---

## Executive Summary

The Learning System in StableNew provides a controlled experimentation framework for discovering optimal Stable Diffusion settings through systematic parameter sweeping, user feedback collection, and intelligent recommendations.

This document provides:
1. Current state assessment (what exists, what's functional)
2. Gap analysis (what's broken, missing, or stubbed)
3. Architecture alignment requirements (matching Prompt/Pipeline tab patterns)
4. Phased implementation roadmap with prioritized PRs

---

## 1. Current State Assessment

### 1.1 GUI Layer — PARTIALLY IMPLEMENTED ✅

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| LearningTabFrame | `src/gui/views/learning_tab_frame_v2.py` | ✅ Complete | 3-column layout, header with toggle, wired to LearningController, **NOW WIRED TO EXECUTION CONTROLLER** |
| ExperimentDesignPanel | `src/gui/views/experiment_design_panel.py` | ✅ Complete | Full UI: name, stage, variable, range, prompt source, buttons |
| LearningPlanTable | `src/gui/views/learning_plan_table.py` | ✅ Complete | Treeview with status, selection, highlight support |
| LearningReviewPanel | `src/gui/views/learning_review_panel.py` | ✅ Complete | Status, metadata, image list, rating controls |
| LearningReviewDialogV2 | `src/gui/learning_review_dialog_v2.py` | ✅ Complete | Modal dialog for reviewing historical records |

**GUI Assessment:** The UI layer is substantially complete. All panels render correctly and have proper event handlers. **PR-LEARN-001 & PR-LEARN-002 COMPLETE: Controllers now properly wired.**

### 1.2 State Layer — COMPLETE ✅

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| LearningState | `src/gui/learning_state.py` | ✅ Complete | Holds current_experiment, plan, selected_variant |
| LearningExperiment | `src/gui/learning_state.py` | ✅ Complete | Dataclass with name, stage, variable, values |
| LearningVariant | `src/gui/learning_state.py` | ✅ Complete | Tracks param_value, status, image_refs |
| LearningImageRef | `src/gui/learning_state.py` | ✅ Complete | Links images to ratings |

**State Assessment:** The state layer is complete and well-designed.

### 1.3 Controller Layer — ✅ **PHASE 1 COMPLETE (PR-LEARN-001 & PR-LEARN-002)**

| Component | File | Status | Critical Issues |
|-----------|------|--------|-----------------|
| LearningController | `src/gui/controllers/learning_controller.py` | ✅ **COMPLETE** | ✅ **PR-LEARN-001**: Fixed to use proper queue submission API; ✅ **PR-LEARN-002**: Now accepts execution_controller |
| LearningExecutionController | `src/controller/learning_execution_controller.py` | ✅ **COMPLETE** | ✅ **PR-LEARN-002**: Now initialized by AppController and wired through GUI |

**Controller Assessment:**
- ✅ **PR-LEARN-001 COMPLETE**: `LearningController._submit_variant_job()` now uses correct PackJobEntry queue submission
- ✅ **PR-LEARN-001 COMPLETE**: MainWindow passes `pipeline_controller` to `LearningTabFrame`
- ✅ **PR-LEARN-001 COMPLETE**: `PackJobEntry.learning_metadata` field added for provenance tracking
- ✅ **PR-LEARN-002 COMPLETE**: `AppController` creates `LearningExecutionController` with `_learning_run_callable`
- ✅ **PR-LEARN-002 COMPLETE**: `LearningTabFrame` extracts and passes `execution_controller` to `LearningController`
- ✅ **PR-LEARN-002 COMPLETE**: Full wiring: AppController → MainWindow → LearningTabFrame → LearningController

### 1.4 Backend Layer — COMPLETE AND **NOW CONNECTED** ✅

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| LearningPlan | `src/learning/learning_plan.py` | ✅ Complete | Mode, stage, variable, sweep_values |
| LearningRunner | `src/learning/learning_runner.py` | ⚠️ Stub | Prepares batches but `run_learning_batches()` returns stub artifacts |
| LearningExecution | `src/learning/learning_execution.py` | ✅ Complete | Orchestrates steps via callable |
| LearningRecord | `src/learning/learning_record.py` | ✅ Complete | Schema + JSONL writer |
| RecommendationEngine | `src/learning/recommendation_engine.py` | ✅ Complete | Statistical analysis of ratings |
| LearningAdapter | `src/learning/learning_adapter.py` | ✅ Complete | Builds plans from config |
| FeedbackManager | `src/learning/feedback_manager.py` | ✅ Complete | Per-run feedback.json |

**Backend Assessment:** Core data structures and algorithms are complete. ✅ **PR-LEARN-002: Now integrated with GUI via LearningExecutionController.**

### 1.5 AppController Integration — ✅ **PHASE 1 COMPLETE**

| Integration Point | Status | Issue |
|-------------------|--------|-------|
| learning_execution_controller attribute | ✅ **COMPLETE** | ✅ **PR-LEARN-002**: AppController creates LearningExecutionController in `__init__` |
| _learning_run_callable method | ✅ **COMPLETE** | ✅ **PR-LEARN-002**: Provides pipeline execution callable for learning experiments |
| Pipeline completion hooks | ❌ Missing | **PR-LEARN-003**: No mechanism to route job completion to learning subsystem (NEXT PHASE) |
| WebUI resource discovery | ⚠️ Partial | No learning-specific resource integration |

---

## 2. Architecture Comparison with Prompt/Pipeline Tabs

### 2.1 Prompt Tab Pattern (Reference)

```
MainWindow
├── PromptTabFrame (creates workspace_state internally)
│   ├── Left: Pack Manager + Slot List
│   ├── Center: Editor Notebook (Prompts + Matrix)
│   └── Right: Metadata + Preview
└── PromptWorkspaceState (passed to AppController)
```

**Key Pattern:** PromptTabFrame is self-contained. It creates its own state and exposes it to AppController.

### 2.2 Pipeline Tab Pattern (Reference)

```
MainWindow
├── PipelineTabFrame (receives app_controller, pipeline_controller)
│   ├── Left: SidebarPanelV2 (pack selector, settings)
│   ├── Center: StageCardsPanel (txt2img, img2img, upscale, adetailer)
│   └── Right: PreviewPanel, QueuePanel, HistoryPanel, DiagnosticsPanel
├── PipelineController (owned by AppController)
│   ├── Builds NormalizedJobRecords
│   ├── Submits to JobQueue
│   └── Routes results to history/preview
└── AppStateV2 (shared state)
```

**Key Pattern:** PipelineTabFrame receives controllers from MainWindow. Controllers handle all logic; views are purely display.

### 2.3 Learning Tab Current State

```
MainWindow
├── LearningTabFrame (creates LearningController internally)
│   ├── Left: ExperimentDesignPanel
│   ├── Center: LearningPlanTable
│   └── Right: LearningReviewPanel
├── LearningController (local, not connected to AppController)
│   ├── build_plan() ✅ Works
│   ├── run_plan() ❌ BROKEN (wrong API call)
│   └── record_rating() ✅ Works (local)
└── LearningExecutionController (exists but unused)
```

**Problem:** Learning Tab doesn't follow Pipeline Tab's controller injection pattern. It creates its own controller locally, which has no access to the real pipeline execution system.

---

## 3. Gap Analysis & Critical Issues

### 3.1 CRITICAL: Run Experiment is Broken

**File:** `src/gui/controllers/learning_controller.py:134-156`

```python
def _submit_variant_job(self, variant: LearningVariant) -> None:
    # ...
    success = self.pipeline_controller.start_pipeline(
        pipeline_func=None,
        on_complete=lambda result: self._on_variant_job_completed(variant, result),
        on_error=lambda error: self._on_variant_job_failed(variant, error),
    )
```

**Issues:**
1. `start_pipeline()` doesn't accept `on_complete`/`on_error` parameters
2. `pipeline_func=None` is meaningless
3. No variant-specific config override is actually applied
4. No seed control for reproducibility

### 3.2 CRITICAL: Controller Not Injected

**File:** `src/gui/main_window_v2.py:189-195`

```python
def _make_learning(parent):
    try:
        tab = LearningTabFrame(parent)  # No pipeline_controller!
    except Exception:
        # ...
```

The Learning tab never receives `pipeline_controller`, so even if the internal code was correct, it has no way to actually run jobs.

### 3.3 MEDIUM: No Integration with Job Completion Events

When a pipeline job completes (via `SingleNodeJobRunner` or `JobService`), there's no hook to notify the Learning system that a learning-related job finished.

### 3.4 MEDIUM: LearningExecutionController is Orphaned

`src/controller/learning_execution_controller.py` exists and works correctly in tests, but:
- AppController doesn't instantiate it
- LearningController (GUI) doesn't use it
- No bridge between the two

### 3.5 LOW: Image Display Not Implemented

`LearningReviewPanel._on_image_selected()` has a TODO:
```python
# TODO: In a real implementation, this would display the actual image
```

### 3.6 LOW: Recommendation Display Not Wired

`LearningReviewPanel.update_recommendations()` exists but the controller's `update_recommendations()` calls it with no guarantee of UI update.

---

## 4. Phased Implementation Roadmap

### Phase 1: Fix Critical Wiring (Short-Term, 1-2 PRs)

| PR | Title | Priority | Scope |
|----|-------|----------|-------|
| PR-LEARN-001 | Wire LearningController to PipelineController | P0 | Fix MainWindow to pass pipeline_controller; Fix _submit_variant_job() API |
| PR-LEARN-002 | Integrate LearningExecutionController | P0 | Connect GUI LearningController to backend LearningExecutionController |

**Goal:** Make "Run Experiment" button actually execute variants.

### Phase 2: Job Completion Integration (Medium-Term, 2-3 PRs) ✅ **COMPLETE**

| PR | Title | Priority | Scope | Status |
|----|-------|----------|-------|--------|
| PR-LEARN-003 | Add Learning Job Completion Hooks | P1 | Route job completion events to learning subsystem | ✅ **COMPLETE** |
| PR-LEARN-004 | Live Variant Status Updates | P1 | Real-time table updates as jobs complete | ✅ **COMPLETE** |
| PR-LEARN-005 | Image Result Integration | P1 | Connect output images to variant records | ✅ **COMPLETE** |

**Goal:** Full closed-loop from experiment → job → result → variant update.

**Implementation Summary:**

**PR-LEARN-003 (Complete)**:
- Added `LearningJobContext` dataclass to `job_models_v2.py` with experiment metadata
- Added `learning_context` field to `NormalizedJobRecord`
- Implemented completion handler registration in `JobService` (`register_completion_handler`, `unregister_completion_handler`, `_notify_completion`)
- Added `on_job_completed_callback` to `LearningController` to route completions
- Wired completion handler in `AppController` via `_create_learning_completion_handler`
- Completion handlers called after job finishes (COMPLETED, CANCELLED, FAILED)

**PR-LEARN-004 (Complete)**:
- Variant status updates automatically on job completion
- `_on_variant_job_completed` updates variant status to "completed"
- `_on_variant_job_failed` updates variant status to "failed"
- Live table updates via `_update_variant_status`, `_update_variant_images`, `_highlight_variant`
- Error states properly handled and displayed

**PR-LEARN-005 (Complete)**:
- Enhanced `_on_variant_job_completed` to extract images from multiple result formats
- Supports "images", "output_paths", and "image_paths" keys
- Image paths added to `variant.image_refs` list
- Automatic deduplication prevents duplicate image references
- Images linked to variants for review and rating

**Tests:** `tests/learning_v2/test_phase2_job_completion_integration.py` (12/12 passing)

### Phase 3: Review & Rating Polish (Medium-Term, 2 PRs) ✅ **COMPLETE**

| PR | Title | Priority | Scope | Status |
|----|-------|----------|-------|--------|
| PR-LEARN-006 | Image Preview in Review Panel | P2 | Display actual images, not just paths | ✅ **COMPLETE** |
| PR-LEARN-007 | Rating Persistence & Retrieval | P2 | Save ratings, reload on session start | ✅ **COMPLETE** |

**Goal:** Complete rating workflow with visual feedback.

**Implementation Summary:**

**PR-LEARN-006 (Complete)**:
- Created `ImageThumbnail` widget in `src/gui/widgets/image_thumbnail.py`
- Supports PIL image loading with automatic resizing and aspect ratio preservation
- Graceful degradation without PIL (shows installation message)
- Error handling for missing/corrupt images
- Integrated into `LearningReviewPanel` with thumbnail display
- Images load automatically when selected from list
- Debounced resize handling for smooth UX

**PR-LEARN-007 (Complete)**:
- Added rating query methods to `LearningRecordWriter`:
  - `get_ratings_for_experiment()` - returns {image_path: rating} dict
  - `get_average_rating_for_variant()` - calculates average for variant
  - `is_image_rated()` - checks if image already rated
- Added rating cache to `LearningController` (`_rating_cache` dict)
- `load_existing_ratings()` called when building plan
- `get_rating_for_image()` and `is_image_rated()` helper methods
- Rating indicators (⭐) shown in image list for rated images
- Duplicate rating prevention with confirmation dialog
- Refresh display after rating to show new indicators
- Added "Avg Rating" column to `LearningPlanTable` with star display
- `update_row_rating()` method updates table with average ratings

**Tests:** `tests/gui/test_image_thumbnail.py` (3/3 passing), `tests/learning_v2/test_rating_persistence.py` (7/7 passing)

### Phase 4: Recommendations & Analytics (Long-Term, 3 PRs)

| PR | Title | Priority | Scope |
|----|-------|----------|-------|
| PR-LEARN-008 | Live Recommendation Display | P2 | Show recommendations in review panel |
| PR-LEARN-009 | Apply Recommendations to Pipeline | P3 | Button to apply best settings to stage cards |
| PR-LEARN-010 | Analytics Dashboard | P3 | Charts, trends, statistical summaries |

**Goal:** Intelligent parameter tuning based on feedback.

### Phase 5: Advanced Experiments (Long-Term, 2+ PRs)

| PR | Title | Priority | Scope |
|----|-------|----------|-------|
| PR-LEARN-011 | Multi-Variable (X/Y) Experiments | P3 | Two-variable grid sweeping |
| PR-LEARN-012 | Adaptive Learning Loop | P4 | Automatic refinement based on ratings |

**Goal:** Advanced experimentation capabilities.

---

## 5. Architectural Decisions

### 5.1 Controller Ownership

**Decision:** LearningController should be owned by AppController, not created inside LearningTabFrame.

**Rationale:** This matches the Pipeline tab pattern where PipelineController is owned by AppController and passed to views.

### 5.2 Job Identification

**Decision:** Learning jobs should include metadata that identifies them as learning variants.

**Implementation:**
```python
@dataclass
class NormalizedJobRecord:
    # ... existing fields ...
    learning_context: LearningJobContext | None = None

@dataclass  
class LearningJobContext:
    experiment_id: str
    variant_index: int
    variable: str
    value: Any
```

### 5.3 Completion Routing

**Decision:** Use an event bus or callback registration pattern for job completion.

**Implementation:** `PipelineController.register_completion_handler(handler)` where handlers can filter by job metadata.

---

## 6. Dependencies & Prerequisites

| Dependency | Status | Required For |
|------------|--------|--------------|
| NormalizedJobRecord stable | ✅ Complete | All learning PRs |
| JobQueue functional | ✅ Complete | PR-LEARN-001+ |
| SingleNodeJobRunner | ✅ Complete | PR-LEARN-001+ |
| Output path tracking | ✅ Complete | PR-LEARN-005 |
| Image preview infrastructure | ⚠️ Partial | PR-LEARN-006 |

---

## 7. Test Coverage Requirements

Each PR must include:

1. **Unit tests** for all new/modified controller methods
2. **Integration tests** verifying wiring between components
3. **Smoke tests** exercising the GUI workflow (headless where possible)

Existing test files to extend:
- `tests/learning_v2/test_learning_execution_controller_integration.py`
- `tests/learning_v2/test_recommendation_engine.py`
- `tests/controller/test_learning_execution_controller_gui_contract.py`

---

## 8. Conclusion

The Learning System has a solid foundation in UI and data structures, but **critical wiring issues** prevent it from actually running experiments. The roadmap prioritizes fixing these blockers first (Phase 1), then building out the full closed-loop workflow (Phases 2-3), and finally adding advanced features (Phases 4-5).

The immediate priority is **PR-LEARN-001** and **PR-LEARN-002**, which will make the core experiment workflow functional.

---

## Appendix A: File Reference

| Category | Files |
|----------|-------|
| **GUI Views** | learning_tab_frame_v2.py, experiment_design_panel.py, learning_plan_table.py, learning_review_panel.py |
| **GUI State** | learning_state.py |
| **GUI Controllers** | src/gui/controllers/learning_controller.py |
| **Backend Controllers** | src/controller/learning_execution_controller.py |
| **Backend Logic** | src/learning/learning_plan.py, learning_runner.py, learning_execution.py, learning_record.py, recommendation_engine.py |
| **Adapters** | src/gui_v2/adapters/learning_adapter_v2.py |
| **Tests** | tests/learning_v2/*.py, tests/controller/test_learning_execution_controller_gui_contract.py |

## Appendix B: Related Documents

- [Learning_System_Spec_v2.5.md](Learning_System_Spec_v2.5.md) — Schema and writer API
- [LearningSystem_MasterIndex_2025-11-26_0512.md](older/LearningSystem_MasterIndex_2025-11-26_0512.md) — Original PR roadmap (3A-3R series)
- [ARCHITECTURE_v2.6.md](ARCHITECTURE_v2.6.md) — System architecture
- [PR Template — StableNew v2.6.md](PR%20Template%20—%20StableNew%20v2.6.md) — PR specification format
