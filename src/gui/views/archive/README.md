# GUI Views Archive

This directory no longer contains importable Python modules.

## PR-CORE1-12: PipelineConfig Runtime Removal

**Date:** 2025
**Reason:** Enforcement of NJR-only execution path (v2.6 architecture)

The old reference-only GUI module was relocated by `PR-ARCH-243` to:

- `tools.archive_reference.gui.pipeline_config_panel`

It remains available only for explicit archival/reference use outside runtime
package paths.

---

## Status: ARCHIVED

GUI V1 is fully deprecated. All new GUI work should use `src/gui/panels_v2/` and follow v2.6 architecture.

This archive exists for historical reference only.
