# GUI Views Archive

This directory contains legacy GUI view modules archived during PR-CORE1-12.

## PR-CORE1-12: PipelineConfig Runtime Removal

**Date:** 2025
**Reason:** Enforcement of NJR-only execution path (v2.6 architecture)

### Archived Files:

#### `pipeline_config_panel.py`
- **Purpose:** GUI V1 panel for pipeline configuration
- **Deprecated:** GUI V2 migration (replaced by panels_v2/)
- **Reason:** Legacy GUI V1 component, superseded by V2 architecture
- **Status:** ARCHIVED - GUI V1 is fully deprecated

**Replacement:** `src/gui/panels_v2/` components (which are themselves evolving)

---

## Status: ARCHIVED

GUI V1 is fully deprecated. All new GUI work should use `src/gui/panels_v2/` and follow v2.6 architecture.

This archive exists for historical reference only.
