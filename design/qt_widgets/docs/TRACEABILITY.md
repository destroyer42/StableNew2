# Focused traceability — prototype scope only

Research sources are linked from [`docs/research/stablenew-experience/`](../../../docs/research/stablenew-experience/README.md)
(not duplicated). "Demonstrated" means a test or measurement in this workspace; every limit still applies.

## Owner decisions and UX research → prototype

| Owner decision / merged UX research | Current prototype | Test / evidence | Limit |
|---|---|---|---|
| 001 Hybrid Create | Default Create form with mock recommended profile and manual edits | `test_create_workflow`, `test_domain*` | No real model recommendation |
| 002 Model-aware settings | Switching fixtures applies defaults, preserves locked/manual values, explains changes | `OverridePrecedenceTests` | Fictional metadata, not backend compatibility |
| 003 Basic + pinnable advanced | Basic settings always shown; *Advanced settings* disclosure with a header summary of hidden differences; separate advanced prompt channels | `test_advanced_settings_are_hidden_by_default…`, `BASIC/ADVANCED` partition test | Pinned persisted controls not implemented |
| 004 Adaptive confirmation | Readiness/errors, explicit preview, then simulation | `PreviewFreshnessAndRefusalTests` | Does not enable production one-click submission |
| 005 PromptPack-centered creation | Prompt source (fixture packs), prompt/negative, structured slots, resolved prompt, optional global/ADetailer/LoRA/embedding notes | `PromptSourceTests`, `WorkflowThroughTheUiTests` | No native pack parser, template or Matrix compile |
| 005A Settings association | Source labelled as draft; "modified, unsaved" when a pack is edited; no save scope | `test_editing_after_loading_a_pack…` | No shared/self-contained persisted config |
| 008 Unsaved draft recovery | Explicit unsaved state; in-memory undo/redo; undoable reset | domain + UI reset tests | No restart recovery/autosave |
| 009 Consolidated review | Stable current/stale preview status, stale reasons by field, effective-settings summary | `stale_reasons` tests, split-pane evidence | Not production NJR preview |
| 049/050 Default vs Learning settings | Source selector applies illustrative fixture deltas under the same protection rules | `test_domain_features` | No qualified Learning-informed profile |
| 051/052 Locks and conflict review | Draft-only locks, origin labels (recommended/manual/locked), per-setting reset, persistent change log | `test_origin_labels`, precedence test | No persistent per-model lock scope |
| UX-850-B J1 C1–C7 | C1–C4 mock inputs and preview; C5 simulated admission; C6 text acknowledgement + placeholder tiles | `SimulatedResultTests`, independence tests | No canonical admission, queue, history or result |
| UX-850-C C02/C03/C04/C05/C09/C10 | Component primitives, contextual hierarchy, fixed action strip, notices, model/profile, PromptPack | component gallery, `test_theme_consistency` | Native Windows density/accessibility unverified |
| UX-850-C TOKENS (roles, 4/8/12 spacing, 32 px control, gold primary, 3:1 outlines, no new density preference) | `concept-a` preset (provenance: verified/mapped/invented); density never reduces the hit target; 20 contrast checks | `test_theme_contract`, THEME_CONTRACT | Not Figma-verified; contrast ≠ WCAG conformance |
| UX-850-D draft/submission | Fingerprinted preview invalidation, no dispatch | refusal + independence tests | Demo hashes have no NJR meaning |
| UX-850-F P1/G1/G2 | Not implemented; no claim to replace the roadmap | – | PromptPack Load guard remains a separate candidate |
| Output Display (owner request, v0.3, no merged research row) | Dockable/collapsible/lockable/fillable/zoomable placeholder viewer | `test_qt_output_display` (27), `test_output_model` | Shows no real image; no Artifacts/History; no persistence |

## QT-DS-01 scope → evidence

| Scope item | Where |
|---|---|
| Preserve v0.3 (blue theme, assets, mock domain, undo/redo, overrides, recommendations, slots/preview, native layout fixes, gallery, tests, capture) | `IMPORT_RECORD.md`, manifest, unchanged tests, hash-pinned `blue-modern` |
| Versioned, validated, editable theme library; ≥2 presets | `THEME_CONTRACT.md`, `test_theme_contract/store` |
| Theme Studio inside the gallery | `theme_studio.py`, `test_qt_theme_studio`, `screenshots/qt-ds-01/studio_*` |
| Mock Create workflow, clearly labelled, never dispatching | `create_view.py`, `test_create_workflow`, `test_qt_create_layouts`, `test_independence` |
| ≥2 layouts compared at 1280×680 (+960×600 stress) | `LAYOUT_EVALUATION.md`, `evidence/` |
| Real vs simulated scaling | Audit meta records the real 100% display; `SIMULATED-scale` files are labelled |
| Independence from production runtimes | `test_independence`, `SimulatedOnlyTests`, repo guard test |

Component design authority is checked-in source, **not** a Figma plugin session or chat memory. Figma Concept A
may inform visual review only and was not read in this task.
