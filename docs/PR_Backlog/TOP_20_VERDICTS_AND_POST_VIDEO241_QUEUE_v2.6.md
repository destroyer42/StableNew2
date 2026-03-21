TOP_20_VERDICTS_AND_POST_VIDEO241_QUEUE_v2.6.md

Status: Active planning document  
Updated: 2026-03-21

## Purpose

Convert the 2026-03-21 deep-research "golden top 20" report into one cleaned
verdict surface that:

- confirms or refutes each recommendation against current repo truth
- separates already-addressed items from still-actionable work
- maps confirmed items onto a concrete post-`PR-VIDEO-236` through
  `PR-VIDEO-241` execution queue

This document is a planning surface, not architecture. The architecture remains
defined by `docs/ARCHITECTURE_v2.6.md`.

## Current Repo Context

The deep-research report correctly identified several structural issues, but it
predated or only partially reflected later v2.6 execution work.

Important current truths:

- queue-only fresh execution is already complete
- NJR and canonical config layering are already complete
- workflow registry/compiler and managed Comfy runtime already exist
- adaptive refinement `PR-HARDEN-224` through `PR-HARDEN-229` are complete
- the `Core Config` -> `Base Generation` and `Pipeline Presets` -> `Saved
  Recipes` migration is complete
- output-root normalization is complete
- docs active-vs-archive cleanup is substantially complete
- Tk remains the active GUI toolkit; PySide6 is not the current execution path

The remaining value in the report is mostly in the structural cleanup and
enforcement recommendations, not in its older assumptions about missing queue,
config, or sidebar work.

## Cleaned Verdicts

### A. Break controller -> GUI dependency inversion

Verdict: Confirm

Why:

- `src/controller/pipeline_controller.py` still imports `src.gui.controller`
  and subclasses the GUI controller
- this is the clearest remaining active inversion against the v2.6 ownership
  map
- it directly raises the cost of backend isolation, controller simplification,
  and future bootstrap cleanup

Mapped queue item:

- `PR-ARCH-242-Controller-GUI-Boundary-Core-Controller-Reset`

### B. Remove or hard-fence archive code under `src/`

Verdict: Confirm

Why:

- archive/reference code under importable runtime package paths still creates
  accidental reuse risk
- even if currently dormant, it weakens the architecture boundary and confuses
  future migrations

Mapped queue item:

- `PR-ARCH-243-Archive-Import-Fencing-and-Reference-Relocation`

### C. Purge tracked mutable runtime state and artifacts

Verdict: Confirm

Why:

- `.gitignore` now blocks the correct categories, but previously tracked
  mutable outputs can still linger in history and day-to-day workflows
- this remains a repo hygiene and reproducibility issue

Mapped queue item:

- `PR-HYGIENE-244-Tracked-Runtime-State-Purge-and-Hygiene-Enforcement`

### D. Make CI and docs consistent and trustworthy

Verdict: Confirm

Why:

- this repo uses docs as a machine-facing planning surface
- CI drift is not cosmetic here; it causes bad PR planning and wrong execution
  assumptions

Mapped queue item:

- `PR-CI-245-CI-Truth-Sync-and-Smoke-Suite-Contract`

### E. Strengthen architecture enforcement tests

Verdict: Confirm

Why:

- the current enforcement suite is real but incomplete
- it does not yet forbid the controller -> GUI inversion the repo still has
- it should also be the mechanical guard for backend-isolation rules

Mapped queue item:

- `PR-ARCH-246-Architecture-Enforcement-Expansion-and-Import-Guards`

### F. Decide the GUI framework direction with explicit Tk/Qt entrypoints

Verdict: Refute for now

Why:

- Tk is still the real active path
- a dual-runtime entrypoint split adds complexity before the remaining product
  and structural cleanup is finished
- this is not the highest-value use of risk budget right now

Deferred status:

- revisit only after the post-`PR-241` structural queue is materially complete

### G. Remove canonical `_v2` suffixes

Verdict: Refute for now

Why:

- this is low-value rename churn compared with the still-open structural work
- it would create large noisy diffs with limited runtime or UX value

Deferred status:

- only revisit as a dedicated rename-only cleanup after higher-leverage debt is
  closed

### H. Eliminate remaining PipelineConfig-era affordances

Verdict: Confirm, but narrowly

Why:

- most of the broad migration is already done
- the remaining work is now about the last active affordances, terminology, and
  archive-adjacent seams, not a second large migration

Mapped queue item:

- absorbed into `PR-ARCH-243` and `PR-ARCH-242`

### I. Make `PipelineController` smaller via cohesive services

Verdict: Confirm

Why:

- service extraction has started, but the controller remains oversized
- this should follow the core boundary reset rather than happen first

Mapped queue item:

- `PR-CTRL-247-PipelineController-Service-Extraction-and-Facade-Reduction`

### J. Promote the deterministic smoke suite to a formal contract

Verdict: Confirm

Why:

- the required CI job already approximates this idea
- formalizing it will make future enforcement and CI expansion clearer

Mapped queue item:

- absorbed into `PR-CI-245`

### K. Add explicit backend boundary ports

Verdict: Confirm, but narrowly

Why:

- useful where it prevents backend/client leakage
- not worth introducing as blanket abstraction everywhere
- should target the specific runtime seams that still leak or are likely to
  leak

Mapped queue item:

- `PR-PORTS-248-Backend-Port-Boundaries-for-Image-and-Video-Runtimes`

### L. Consolidate logging into a job/stage context contract

Verdict: Confirm

Why:

- high operational value for replay, diagnostics, queue debugging, and backend
  comparison
- especially important once secondary motion adds more policy/provenance to
  video execution

Mapped queue item:

- `PR-OBS-249A-Structured-Event-Logging-Contract-and-Ascii-Normalization`
- `PR-OBS-249B-Log-Trace-Panel-Severity-Coloring-and-Event-Filters`
- `PR-OBS-249C-Repeated-Event-Collapse-and-WebUI-Outage-Dedup`
- `PR-OBS-249D-Operator-vs-Trace-Log-Surface-Split`

### M. Add a hard replay fidelity contract

Verdict: Confirm

Why:

- replay fidelity is central to the v2.6 architecture
- StableNew now has more artifact/manifests/video metadata than before, making
  explicit replay validation more important, not less

Mapped queue item:

- `PR-REPLAY-250-Replay-Fidelity-Contract-and-Versioned-Validation`

### N. Align GUI and CLI through a shared bootstrap/kernel

Verdict: Confirm, medium priority

Why:

- this will reduce startup divergence and simplify future runtime capabilities
  reporting
- it is worthwhile, but should follow controller-boundary cleanup

Mapped queue item:

- `PR-APP-251-Shared-Application-Bootstrap-and-Kernel-Composition`

### O. Make optional dependencies explicit and capability-aware

Verdict: Confirm

Why:

- StableNew now has several optional dependency surfaces
- standardized optional-deps handling will reduce brittle imports and improve
  capability reporting

Mapped queue item:

- `PR-HARDEN-252-Optional-Dependency-Capabilities-and-Startup-Probes`

### P. Add a staged mypy gate

Verdict: Confirm, low priority

Why:

- useful if staged and whitelisted
- not urgent compared with controller, replay, or hygiene work

Mapped queue item:

- `PR-CI-253-Mypy-Smoke-Gate-and-Whitelist-Expansion`

### Q. Make PromptPack intent a first-class artifact

Verdict: Refute as written; confirm the underlying goal

Why:

- the repo is no longer PromptPack-only
- the correct target is StableNew-owned intent artifact hardening across all
  intent surfaces, not PromptPack-specific semantics

Mapped queue item:

- `PR-CONTRACT-254-Intent-Artifact-Versioning-and-Hash-Closure`

### R. Add a single source of truth for workflow/preset registries

Verdict: Confirm

Why:

- this is the right pattern, and video already moved in this direction
- the remaining work is governance and extension of registry truth, not
  inventing a new concept

Mapped queue item:

- `PR-VIDEO-255-Workflow-Registry-Governance-and-Pinning-Closure`

### S. Reduce docs bloat by separating active and historical surfaces

Verdict: Confirm, but mostly already done

Why:

- this was the right recommendation
- most of the heavy cleanup is already complete, so only incremental tightening
  remains

Mapped queue item:

- absorb as maintenance work inside future planning/docs PRs, not a standalone
  queue item right now

### T. Create an explicit repo hygiene checklist and CI enforcement

Verdict: Confirm

Why:

- this is the mechanical counterpart to governance
- it is the cleanest way to prevent regression into tracked state, accidental
  archive imports, or other drift

Mapped queue item:

- absorbed into `PR-HYGIENE-244`

## Confirmed Recommendation Summary

The confirmed work falls into nine practical groups:

1. controller/core boundary cleanup
2. archive fencing and remaining PipelineConfig-era closure
3. tracked-state and repo hygiene enforcement
4. CI/doc truth alignment and formal smoke contract
5. stronger architecture/import guard tests
6. further controller/service decomposition
7. backend port boundaries
8. structured diagnostics/logging and replay fidelity
9. startup/bootstrap, optional dependencies, typing, and intent/registry
   governance follow-through

## Concrete Post-`PR-VIDEO-241` Queue

This is the recommended execution queue after the secondary motion tranche is
complete.

### 1. `PR-ARCH-242-Controller-GUI-Boundary-Core-Controller-Reset`

Primary outcome:

- remove the active controller -> GUI inheritance/import inversion
- introduce a true core controller boundary with GUI adapter-only ownership at
  the GUI edge

Incorporates:

- Recommendation A
- Recommendation H (remaining active affordance closure)

### 2. `PR-ARCH-243-Archive-Import-Fencing-and-Reference-Relocation`

Primary outcome:

- move or fence archive/reference code so runtime paths cannot accidentally
  import it
- close the last remaining archive-adjacent PipelineConfig-era affordances

Incorporates:

- Recommendation B
- remaining Recommendation H debt

### 3. `PR-HYGIENE-244-Tracked-Runtime-State-Purge-and-Hygiene-Enforcement`

Primary outcome:

- remove tracked mutable runtime artifacts still living in the repo
- add one hygiene checker and one short hygiene contract doc

Incorporates:

- Recommendation C
- Recommendation T

### 4. `PR-CI-245-CI-Truth-Sync-and-Smoke-Suite-Contract`

Primary outcome:

- align active CI docs with actual workflow truth
- formalize the deterministic smoke suite as a named, versioned contract

Incorporates:

- Recommendation D
- Recommendation J

### 5. `PR-ARCH-246-Architecture-Enforcement-Expansion-and-Import-Guards`

Primary outcome:

- extend architecture enforcement tests for:
  - controller -> GUI import bans in core paths
  - backend/client leakage bans
  - archive import bans
  - allowed exception management

Incorporates:

- Recommendation E

### 6. `PR-CTRL-247-PipelineController-Service-Extraction-and-Facade-Reduction`

Primary outcome:

- continue reducing `PipelineController` into cohesive services after the
  controller/core reset
- leave a smaller top-level facade with clearer ownership

Incorporates:

- Recommendation I

### 7. `PR-PORTS-248-Backend-Port-Boundaries-for-Image-and-Video-Runtimes`

Primary outcome:

- formalize the narrow backend port layer where it prevents runtime leakage
- keep GUI/controllers dependent on StableNew-owned ports rather than backend
  client details

Incorporates:

- Recommendation K

### 8. `PR-OBS-249A` through `PR-OBS-249D` Logging and Observability Tranche

Status: Completed 2026-03-21

Primary outcome:

- one structured logging contract across runner, queue, replay, and
  diagnostics surfaces
- a useful trace panel with severity coloring and event/stage filters
- repeated-event collapse and WebUI outage dedup in the GUI log surface
- a clean operator-vs-trace split between the bottom log and Debug Hub

Incorporates:

- Recommendation L, delivered through:
  - `PR-OBS-249A-Structured-Event-Logging-Contract-and-Ascii-Normalization`
  - `PR-OBS-249B-Log-Trace-Panel-Severity-Coloring-and-Event-Filters`
  - `PR-OBS-249C-Repeated-Event-Collapse-and-WebUI-Outage-Dedup`
  - `PR-OBS-249D-Operator-vs-Trace-Log-Surface-Split`

### 9. `PR-REPLAY-250-Replay-Fidelity-Contract-and-Versioned-Validation`

Primary outcome:

- formal replay fidelity validator
- versioned replay-safe manifest/result rules
- deterministic replay validation tests

Incorporates:

- Recommendation M

### 10. `PR-APP-251-Shared-Application-Bootstrap-and-Kernel-Composition`

Primary outcome:

- one shared bootstrap/kernel composition path for GUI and CLI
- reduced startup divergence and clearer runtime capability ownership

Incorporates:

- Recommendation N

### 11. `PR-HARDEN-252-Optional-Dependency-Capabilities-and-Startup-Probes`

Primary outcome:

- standard optional dependency helper pattern
- startup capability probes and clear degraded-mode reporting

Incorporates:

- Recommendation O

### 12. `PR-CI-253-Mypy-Smoke-Gate-and-Whitelist-Expansion`

Primary outcome:

- small mypy gate on selected core modules
- explicit whitelist growth policy

Incorporates:

- Recommendation P

### 13. `PR-CONTRACT-254-Intent-Artifact-Versioning-and-Hash-Closure`

Primary outcome:

- complete the intent artifact contract with version/hash closure across
  NJR-backed intent surfaces
- keep this multi-surface, not PromptPack-only

Incorporates:

- Recommendation Q, reframed correctly

### 14. `PR-VIDEO-255-Workflow-Registry-Governance-and-Pinning-Closure`

Primary outcome:

- finish the governance layer around pinned workflow/registry truth
- keep GUI/controller references ID-only and backend-internal details out of
  public contracts

Incorporates:

- Recommendation R

## Explicitly Deferred Items

These recommendations should not drive immediate standalone PRs:

- Recommendation F: GUI toolkit split or Qt/Tk dual runtime
- Recommendation G: repo-wide `_v2` rename sweep
- Recommendation S: large docs split project beyond normal maintenance

They remain valid future cleanup ideas, but they are lower leverage than the
post-`PR-241` structural queue above.

## Done Definition For This Queue

This queue is successful when:

- no active controller path depends on GUI controller inheritance
- archive/reference code is fenced away from runtime use
- tracked mutable runtime artifacts are no longer part of active repo state
- CI docs and actual CI behavior agree
- architecture guard tests mechanically enforce the repo’s intended boundaries
- replay fidelity is validated as a first-class contract
- GUI and CLI bootstrap through the same application composition story
- optional dependencies degrade cleanly and visibly
- intent and workflow registry governance are explicit and versioned
