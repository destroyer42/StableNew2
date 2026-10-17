# Controller Archive

This directory no longer contains importable Python modules.

## PR-CORE1-12: PipelineConfig Runtime Removal

**Date:** 2025
**Reason:** Enforcement of NJR-only execution path (v2.6 architecture)

The old archive Python modules were relocated by `PR-ARCH-243` to `tools/archive_reference/` and later retired (audit P2-6). The source remains in Git history at `bfdeb493`:

- `tools.archive_reference.controller.legacy_pipeline_config_types`
- `tools.archive_reference.controller.legacy_pipeline_config_assembler`

Those modules no longer exist in the tree. `PipelineConfig` code must not return to `src/`.

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
2. Git history (the retired `tools/archive_reference/` package, last present at `bfdeb493`)

Do not reintroduce `PipelineConfig` as an execution payload.
