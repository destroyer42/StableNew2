# PR-PERF-206B - PromptPack Builder Caching

Status: Completed 2026-03-18

## Summary

This PR adds short-lived, file-aware caching to the prompt-pack NJR builder so
repeated preview and queue builds stop re-reading and re-resolving the same
pack inputs on every pass.

## Runtime Changes

### 1. Parsed pack-row cache

[prompt_pack_job_builder.py](/c:/Users/rob/projects/StableNew/src/pipeline/prompt_pack_job_builder.py)
now caches parsed text rows keyed by pack file fingerprint.

That avoids repeated parse work for unchanged `.txt` pack sources during:

- repeated preview refreshes
- preview-to-queue submission
- small draft edits that do not change the pack file itself

### 2. Pack metadata/config cache

The same builder now caches:

- pack JSON metadata
- pack config payloads

with invalidation based on path fingerprinting.

This removes repeated metadata/config disk loads for unchanged packs.

### 3. Resolved config cache

The builder now also caches the merged config produced from:

- pack source fingerprint
- pack id
- runtime params

That means unchanged preview records stop paying the full config-resolution cost
on every rebuild.

### 4. Builder reuse in PipelineController

[pipeline_controller.py](/c:/Users/rob/projects/StableNew/src/controller/pipeline_controller.py)
now memoizes the prompt-pack builder instance instead of constructing a fresh
builder for each preview build.

This is what makes the per-builder caches actually useful across repeated UI
operations.

## Verification

Passed:

- `pytest tests/pipeline/test_prompt_pack_job_builder.py -q`
- `python -m compileall src/pipeline/prompt_pack_job_builder.py tests/pipeline/test_prompt_pack_job_builder.py`

## Follow-On

This PR speeds up repeated pack-driven builds for unchanged sources. It does
not yet reduce how often preview rebuilds are triggered. That is handled in
`PR-PERF-206C`.
