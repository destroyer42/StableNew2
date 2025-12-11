# Controller Archive

This directory contains legacy controller modules archived during PR-CORE1-12.

## PR-CORE1-12: PipelineConfig Runtime Removal

**Date:** 2025
**Reason:** Enforcement of NJR-only execution path (v2.6 architecture)

### Archived Files:

#### `pipeline_config_assembler.py`
- **Purpose:** Built `PipelineConfig` objects from GUI state and config manager
- **Deprecated:** PR-CORE1-B2 (NJR-only execution)
- **Reason:** All pipeline execution now uses `NormalizedJobRecord` (NJR) + PromptPack
- **Replacement:** `JobBuilderV2` + `ConfigMergerV2` build NJR directly from state
- **Classes:**
  - `GuiOverrides` - GUI state overrides for config building
  - `PlannedJob` - Single job in multi-job plan
  - `RunPlan` - Plan for pipeline run with multiple jobs
  - `PipelineConfigAssembler` - Main assembler class

**Status:** ARCHIVED - Do not use for new code. Reference only for understanding legacy logic.

---

## Architecture Context

StableNew v2.6 enforces a single canonical job model:

```
GUI → Controller → JobBuilderV2 → NJR → Queue → Runner → History → Learning
```

`PipelineConfig` existed as an intermediate execution payload but was replaced by `NormalizedJobRecord` (NJR) which includes:
- Full PromptPack reference
- Complete configuration snapshot
- Execution metadata
- Learning system integration

All runtime execution MUST use NJR. `PipelineConfig` may appear only in:
1. Internal conversion methods (transitional, to be refactored)
2. Compatibility fixtures in archived tests
3. This archive directory

Do not reintroduce `PipelineConfig` as an execution payload.
