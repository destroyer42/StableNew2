# High Level ComfyUI Integration Approach Rationale

Status: archived reference  
Updated: 2026-03-18

This note is retained because the core strategic idea was correct: StableNew
should not become "Comfy as the platform." StableNew remains the orchestrator,
and Comfy is only one backend option inside the StableNew video architecture.

What was incomplete in the original version:

- it predated the current `src/video/` backend registry seam
- it speculated about a second outer video job shape that the current
  architecture does not need
- it treated earlier video PRs as prospective when the repo has already landed
  substantial SVD and AnimateDiff contract work

Current canonical replacements:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`
- `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`

Current architecture rule:

- NJR remains the only outer execution contract
- `VideoExecutionRequest` is an internal runner-to-backend seam only
- workflow JSON stays backend-internal
- StableNew owns queueing, orchestration, artifacts, replay, diagnostics, and
  history

The approved sequence now starts from the existing video backend seam and builds
Comfy/LTX on top of it through the backlog above. Do not use this archived note
as a source of architecture truth.
