# PR-GUI-V2-LEARNING-GROUNDWORK-001
## Title
V2 Learning System Groundwork — Feedback Capture, Run Metadata, and Future LLM Integration Hooks

## Scope
Establish the structural foundations for a long-term adaptive learning system that improves StableNew’s default/auto configurations over time through user feedback, run metadata capture, and optional future LLM-based guidance.

This PR **does not** implement learning heuristics or LLM calls. It only lays the scaffolding needed to support future PRs.

## Included Changes
### 1. Run Metadata Capture
Add a lightweight metadata object recorded for every pipeline run:
- selected pack(s)
- selected one-click action (if any)
- full unified config (pre-run)
- timestamp
- per-stage outputs (paths only)
- stochastic IDs for correlation

Write metadata to:
```
runs/<run_id>/run_metadata.json
```

### 2. Feedback Prompt Hooks
Implement a callback entry point for user feedback:
```
feedback_manager.record_feedback(run_id, image_id, rating, notes=None)
```
Store under:
```
runs/<run_id>/feedback.json
```

### 3. Learning Dataset Aggregator
Create:
```
src/learning/dataset_builder.py
```
which exposes:
- `collect_runs()`
- `collect_feedback()`
- `build_learning_dataset()`

This dataset becomes the input to future learning algorithms or LLM agents.

### 4. Learning API Contract (Stable)
Create:
```
src/learning/learning_contract.py
```
Defines a *stable*, minimal interface for future consumers:
```
get_available_modifiers()
get_modifier_ranges()
get_current_best_defaults()
propose_new_defaults(dataset)
```
Implement stubs returning placeholders.

### 5. GUI Integration Hooks
GUI V2 should:
- attach run_id to pipeline start
- attach feedback linkage to preview and gallery panels (stub only)
- expose a “Learning Mode” toggle in the future (stub only)

### 6. Tests
Add new test suite:
```
tests/learning_v2/
```
Tests:
- metadata file creation
- feedback recording
- dataset builder aggregation
- API contract importability

## Non-Goals
- no machine learning
- no LLM integration
- no UI/UX elements beyond hooks
- no config auto-updating

## Success Criteria
- All new modules import cleanly
- GUI run pipeline produces metadata directory
- Feedback manager persists JSON
- Dataset builder can ingest multiple run folders
