# Adaptive Refinement Executable Roadmap v2.6

Status: Active planning document
Updated: 2026-03-20

## Purpose

Turn the adaptive refinement research memo into an executable PR series that can
be handed to an implementation agent without architecture guessing, silent scope
growth, or dependency drift.

This roadmap is the guiding document for the adaptive image-hardening tranche.
The individual PR specs under `docs/PR_Backlog/` are the executable handoff
artifacts.

## Current Repo Truth

StableNew already has the backbone this work needs:

- `PipelineRunner.run_njr(...)` is the only production runner entrypoint.
- NJR remains the only outer execution contract.
- The canonical image stage order already exists: `txt2img -> img2img -> adetailer -> upscale`.
- Prompt bucketing, prompt splitting, embedding extraction, and prompt
  optimization already exist under `src/prompting/` and `src/utils/`.
- Learning record building and recommendation analysis already exist under
  `src/learning/`.

StableNew now has the first foundation slices of the adaptive refinement layer:

- `src/refinement/` exists as a StableNew-owned subsystem boundary
- the canonical nested `intent_config["adaptive_refinement"]` contract exists
- observation-only decision bundles can be emitted from the runner
- the detector boundary exists with optional OpenCV fallback support
- ADetailer-safe per-image adaptive actuation now exists with manifest and
  embedded-image provenance reuse

StableNew still does not yet have the remaining behavior-changing and feedback
parts of the tranche:

- no prompt-patch or upscale policy application
- no learning feedback loop or recommendation-aware evaluation for refinement outcomes

## Critical Appraisal of the Research Memo

The research summary identified the right subsystem seams, but its first-pass PR
plan was still too risky to execute directly.

### Weakness 1: It front-loaded too much risky runner behavior

The memo combined new contracts, analyzer logic, per-image policy selection,
stage override application, prompt rewriting, manifest changes, and learning
integration too early in the series.

Incorporated correction:

- the improved plan separates contracts, observation-only capture, detector
  rollout, ADetailer actuation, prompt/upscale actuation, and learning
  integration into distinct PRs

### Weakness 2: It coupled independent risk surfaces

Detector enablement, prompt patching, and ADetailer/upscale mutation were
presented as one broad feature band even though they fail in different ways and
need different rollback strategies.

Incorporated correction:

- detector rollout now lands before real actuation
- ADetailer knob changes land before prompt patches and upscale changes
- prompt patching explicitly excludes LoRA and embedding weight mutation in v1

### Weakness 3: It underspecified rollout gates and opt-in behavior

The memo assumed the runner would "just know" when to analyze and apply policy
changes, but it did not define a stable user-facing intent contract, an
observation-only mode, or go/no-go criteria between phases.

Incorporated correction:

- a single nested `adaptive_refinement` intent contract lands first
- rollout modes are explicit: `disabled`, `observe`, `adetailer`, `full`
- each phase has an exit gate before the next PR may begin

## Improved Execution Strategy

The series follows five execution rules.

1. Add one canonical nested intent contract before any behavior change.
2. Observe before act: record decision bundles before mutating stage configs.
3. Land detector capability before enabling real per-image actuation.
4. Roll out ADetailer actuation before prompt-patch and upscale behavior.
5. Extend learning only after refinement metadata and manifest provenance are
   stable.

Additional tranche-wide execution constraints:

6. All refinement provenance must use one canonical `adaptive_refinement`
   carrier shape across runner metadata, manifests, embedded image metadata,
   diagnostics, and later learning context.
7. Subject assessment must happen at most once per source image per run path,
   with runner-owned caching and deterministic reuse by downstream stages.
8. Detector execution must have an explicit timeout/fallback rule and may never
   fail a job merely because adaptive assessment degraded.
9. The feature remains dark-launched through this series: default disabled, no
   GUI exposure, and no hidden auto-enable path outside explicit config/test
   inputs.

## PR Sequence Overview

| PR | Title | Core outcome | Depends on |
| ---- | ----- | ------------ | ---------- |
| `PR-HARDEN-224` | Adaptive Refinement Contracts and Dark-Launch Foundation | Canonical config contract, schema, builder persistence, import guards | none |
| `PR-HARDEN-225` | Prompt Intent Analysis and Observation-Only Decision Capture | Analyzer, no-op registry path, runner metadata capture with no stage mutation | `PR-HARDEN-224` |
| `PR-HARDEN-226` | Detector Boundary and Optional OpenCV Subject Assessment | Real subject assessment path with optional OpenCV, null fallback, threshold versioning | `PR-HARDEN-225` |
| `PR-HARDEN-227` | Safe ADetailer Adaptive Policy Application | First behavior-changing rollout, limited to ADetailer overrides and manifest provenance | `PR-HARDEN-226` |
| `PR-HARDEN-228` | Prompt Patch and Upscale Policy Integration | Stage-scoped prompt patching and bounded upscale policy application | `PR-HARDEN-227` |
| `PR-HARDEN-229` | Learning Loop and Recommendation-Aware Refinement Feedback | Learning metadata, quality metrics, recommendation stratification | `PR-HARDEN-228` |

## Current Execution Status

Completed:

- `PR-HARDEN-224`
- `PR-HARDEN-225`
- `PR-HARDEN-226`
- `PR-HARDEN-227`

Remaining:

- `PR-HARDEN-228`
- `PR-HARDEN-229`

## Phase Gates

### Gate A: Contract Freeze

Applies after `PR-HARDEN-224`.

Status: Passed on 2026-03-20

Required before continuing:

- `adaptive_refinement` survives canonicalization, builder paths, and NJR
  snapshots without adding a second job model
- the refinement package has AST guard coverage blocking GUI imports and
  backend/video leakage
- the canonical `adaptive_refinement` carrier shape is frozen for later reuse
- no runner behavior changes have landed yet

### Gate B: Observation Stability

Applies after `PR-HARDEN-225` and `PR-HARDEN-226`.

Status: Passed on 2026-03-20

Required before continuing:

- observation-mode bundles are stable in runner metadata
- observation bundles are shaped so they can later flow into manifests,
  embedded image metadata, diagnostics, and learning without schema forks
- prompt intent analysis reuses existing prompt infrastructure instead of
  duplicating it
- detector preference resolution degrades cleanly to a null detector when
  OpenCV is unavailable
- detector work is cached per image and bounded by explicit timeout/fallback
  rules

### Gate C: Controlled Actuation Stability

Applies after `PR-HARDEN-227`.

Status: Passed on 2026-03-20

Required before continuing:

- ADetailer overrides are the only applied behavior mutation
- applied overrides are recorded once in a canonical manifest-facing structure
- the same applied-override structure is consumable by embedded image metadata
  and replay/diagnostics surfaces without translation loss
- disable and observe modes still remain lossless rollback paths

### Gate D: Metadata and Learning Stability

Applies after `PR-HARDEN-228` and before `PR-HARDEN-229` is considered done.

Required before closing the tranche:

- prompt patch merge order is deterministic and covered by executor tests
- prompt patching does not mutate LoRA tags, embedding tokens, or weighted
  prompt syntax in v1
- original prompt, patch payload, and final prompt provenance survive replay
- learning records store scalar metrics and policy ids only; no image crops or
  large binary payloads are persisted

## Roadmap Outcome Definition

This tranche is complete when:

- adaptive refinement can be enabled through canonical intent metadata without
  creating a new job model
- the runner can assess images and record refinement decisions per image
- StableNew can safely apply bounded ADetailer and later prompt/upscale policy
  adjustments under explicit rollout modes
- manifests, metadata, and learning records preserve enough provenance to replay
  and evaluate refinement decisions
- optional OpenCV support improves assessment quality without becoming a hard
  install dependency

## Follow-On Work Outside This Series

These items are intentionally deferred so the runtime series stays bounded:

- minimal GUI exposure for `adaptive_refinement.enabled`, `mode`, and detector
  preference
- richer diagnostics surfacing of refinement bundles in Debug Hub or History
- policy auto-tuning beyond the existing recommendation-engine evidence tiers

Those follow-ons should be planned only after `PR-HARDEN-229` is complete and
the metadata contract is stable.
