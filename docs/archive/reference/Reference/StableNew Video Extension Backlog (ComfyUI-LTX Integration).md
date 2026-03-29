# StableNew Video Extension Backlog (ComfyUI-LTX Integration)

Status: archived reference  
Updated: 2026-03-18

This document was an earlier draft of the Comfy/LTX plan. It still contains
useful constraints, but it no longer reflects the current repo accurately
enough to serve as an active backlog.

What remained valuable:

- StableNew must remain the orchestrator
- workflow JSON must not become the public contract
- backend isolation and replayability must remain first-class
- LTX should arrive through an ordered PR sequence, not as a direct UI-to-Comfy
  shortcut

What was superseded:

- the repo now already has a real `src/video/` backend seam
- the canonical plan now keeps NJR as the only outer job contract
- the active migration order is now tied to NJR unification and queue-only
  execution closure

Use these documents instead:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`
- `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`

Current rule set:

- image and video both remain NJR-driven
- `VideoExecutionRequest` is an internal seam, not a second job model
- Comfy runtime, workflow registry, compiler, and pinned LTX workflows belong
  under `src/video/`
- UI surfaces may expose StableNew-native controls only, never raw workflow JSON

Keep this file only as historical rationale. Do not treat it as the active PR
queue or architecture source.
