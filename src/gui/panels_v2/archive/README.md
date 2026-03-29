# GUI Panels V2 Archive

This directory no longer contains importable Python modules.

## PR-CORE1-12: PipelineConfig Runtime Removal

**Date:** 2025
**Reason:** Enforcement of NJR-only execution path (v2.6 architecture)

The old reference-only GUI module was relocated by `PR-ARCH-243` to:

- `tools.archive_reference.gui.pipeline_config_panel_v2`

It remains available only for explicit archival/reference use outside runtime
package paths.

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
