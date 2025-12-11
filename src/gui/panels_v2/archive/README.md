# GUI Panels V2 Archive

This directory contains legacy GUI panel modules archived during PR-CORE1-12.

## PR-CORE1-12: PipelineConfig Runtime Removal

**Date:** 2025
**Reason:** Enforcement of NJR-only execution path (v2.6 architecture)

### Archived Files:

#### `pipeline_config_panel_v2.py`
- **Purpose:** GUI V2 panel for configuring pipeline execution settings
- **Deprecated:** PR-CORE1-B2 (NJR-only execution)
- **Reason:** Panel was wired to `PipelineConfig`-based execution, which is removed
- **Features:**
  - Run mode selection (direct vs queue)
  - Batch size configuration
  - Randomizer controls (enabled/disabled, max variants)
  - Stage configuration UI
  - LoRA controls
- **Status:** No longer wired in main GUI as of PR-CORE1-12

**Replacement:**
- Configuration now managed via:
  - `CoreConfigPanel` - Core generation settings (model, sampler, steps, etc.)
  - `RandomizerPanelV2` - Randomization settings
  - `PipelinePanelV2` - Stage enable/disable
  - `PreviewPanel` - Job preview before queue submission

**Architecture Change:**
GUI V2 no longer assembles `PipelineConfig` objects. Instead:

```
GUI widgets → AppStateV2 → PipelineController → JobBuilderV2 → NJR → Queue
```

All execution uses `NormalizedJobRecord` (NJR) built from:
1. GUI state (AppStateV2)
2. PromptPack (from dropdown or manual selection)
3. ConfigMergerV2 (merges pack + GUI overrides)

---

## Status: ARCHIVED

Do not use for new code. Reference only for understanding legacy GUI structure.

If you need pipeline configuration UI, use the modern V2 panels listed above.
