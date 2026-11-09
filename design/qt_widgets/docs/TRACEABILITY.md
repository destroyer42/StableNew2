# Focused traceability — prototype scope only

| Owner decision / merged UX research | Current prototype | Limit |
|---|---|---|
| 001 Hybrid Create | Default Create form with mock recommended profile and manual edits | No real model recommendation |
| 002 Model-aware settings | Switching fixtures applies defaults, preserves locked/manual values, describes changes | Fictional metadata, not real backend compatibility |
| 003 Basic + pinnable advanced | Main Create form + structured advanced disclosure | Pinned persisted controls not implemented |
| 004 Adaptive confirmation | Readiness/errors, explicit preview then simulation | Deliberately does not enable production one-click submission |
| 005 PromptPack-centered creation | Pack name, prompt/negative, structured slot values, optional global/ADetailer and LoRA/embedding notes | No native pack parser, template or Matrix compile |
| 005A Settings association | Source labeled as draft and no save scope side effect | No shared/self-contained persisted config |
| 008 Unsaved draft recovery | Explicit local unsaved state; in-memory undo/redo; undoable reset (replaces the modal confirmation) | No restart recovery/autosave |
| 009 Consolidated review | Stable current/stale preview status, reasons, settings summary | Not production NJR preview |
| 049/050 Default vs Learning settings | Source selector applies illustrative fixture deltas under the same protection rules; clear fixture warning | No qualified Learning-informed profile or startup-default save |
| 051/052 Locks and conflict review | Draft-only setting locks, visible recommendation and `differs` state, per-setting reset, persistent change log | No persistent per-model or campaign lock scope |
| UX-850-B J1 C1-C7 | C1-C4 mock inputs and preview, C5 simulated admission, C6 text-only acknowledgement | No canonical admission, queue, history or actual result |
| UX-850-C C02/C03/C04/C05/C09/C10 | Component primitives, contextual hierarchy, sticky footer, notices, model/profile, PromptPack | Native Windows/density/accessibility unverified |
| UX-850-D draft/submission | Fingerprinted preview invalidation, no dispatch | Demo hashes have no NJR or authorization meaning |
| UX-850-F P1/G1/G2 | Not implemented, no claim to replace published roadmap | P1 PromptPack Load guard remains separate candidate |

| Output Display (owner request, v0.3 — no merged research row) | Dockable/collapsible/lockable/fillable/zoomable placeholder viewer fed by the draft | Shows no real image; no Artifacts/History/filesystem access; no persistence |

Component design authority is checked-in source, **not** a Figma plugin session or chat memory. Figma Concept A may inform visual review only.
