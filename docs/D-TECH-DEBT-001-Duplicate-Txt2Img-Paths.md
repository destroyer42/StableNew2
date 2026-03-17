# D-TECH-DEBT-001: Duplicate txt2img Execution Paths

**Status:** RESOLVED IN RUNTIME | Closeout audit complete  
**Date:** 2026-03-16  
**Priority:** CLOSED AS EXECUTION DEBT  
**Impact:** Prevent stale planning and keep retired executor paths from returning

---

## Executive Summary

This debt item is no longer an active runtime problem.

StableNew previously had two txt2img execution paths:
- a legacy CLI-oriented path built around `run_full_pipeline()` / `run_txt2img()`
- the canonical NJR-driven path built around `PipelineRunner.run_njr()` / `run_txt2img_stage()`

That split has now been removed from live code. The CLI has been migrated onto the canonical NJR path, the retired executor entrypoints are gone from `src/`, and this document is retained as a closeout audit rather than an open migration note.

---

## Historical Problem

The original issue was real:
- duplicate txt2img execution logic
- inconsistent manifest behavior across paths
- earlier model/VAE metadata drift between the legacy and canonical flows

This was worth addressing because it multiplied maintenance burden and created misleading debugging signals.

---

## Current State

### Live canonical path

The active txt2img execution chain is:

```text
CLI or GUI -> build NormalizedJobRecord -> PipelineRunner.run_njr() -> Pipeline.run_txt2img_stage()
```

### Evidence in current code

- `src/cli.py` builds an NJR via `build_cli_njr(...)`
- `src/cli.py` executes through `runner.run_njr(...)`
- `src/pipeline/cli_njr_builder.py` exists specifically for the CLI-to-NJR bridge
- `src/pipeline/executor.py` exposes `run_txt2img_stage(...)` as the live txt2img executor

### Retired path status

The following legacy executor surfaces are no longer present in live `src/`:
- `run_full_pipeline()`
- `_run_full_pipeline_impl()`
- `run_txt2img()`
- `_run_txt2img_impl()`

---

## What This Means

### Recommendation #1 status

Recommendation #1 from the revised Top 20 should now be treated as:
- implemented for runtime behavior
- open only for docs harmonization and guard coverage

### Residual work that is not part of this debt item

The repo still has adjacent migration work, but it belongs elsewhere:
- queue/history/controller `pipeline_config` compatibility cleanup
- deprecated controller bridge retirement
- broader docs and README refresh

Those are recommendation #2 and recommendation #13 items, not duplicate txt2img executor debt.

---

## Verification

The closeout audit for this debt item should continue to verify:

1. `src/cli.py` calls `build_cli_njr(...)`
2. `src/cli.py` calls `run_njr(...)`
3. `src/pipeline/executor.py` still defines `run_txt2img_stage(...)`
4. live `src/**/*.py` does not reintroduce:
   - `run_full_pipeline(`
   - `_run_full_pipeline_impl(`
   - `def run_txt2img(`
   - `def _run_txt2img_impl(`

---

## Recommendation

Keep this document as a resolved debt note and enforce it with a small invariant test. Do not spend another migration PR re-solving the same executor-path problem.

---

## Related Documents

- [ARCHITECTURE_v2.6.md](ARCHITECTURE_v2.6.md)
- [Builder Pipeline Deep-Dive (v2.6).md](Builder%20Pipeline%20Deep-Dive%20%28v2.6%29.md)
- [StableNew_Revised_Top20_Recommendations.md](StableNew_Revised_Top20_Recommendations.md)

---

**END OF CLOSEOUT AUDIT**
