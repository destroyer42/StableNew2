# Controller Archive

This directory no longer contains importable Python modules.

## PR-CORE1-12: PipelineConfig Runtime Removal

**Date:** 2025
**Reason:** Enforcement of NJR-only execution path (v2.6 architecture)

The old archive Python modules were relocated by `PR-ARCH-243` to:

- `tools.archive_reference.controller.legacy_pipeline_config_types`
- `tools.archive_reference.controller.legacy_pipeline_config_assembler`

Those modules are reference-only and may be imported only by compat/archive test
surfaces. Active runtime code under `src/` must not import them.

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
1. compatibility fixtures in compat/archive tests
2. `tools.archive_reference/` as reference-only code

Do not reintroduce `PipelineConfig` as an execution payload.
