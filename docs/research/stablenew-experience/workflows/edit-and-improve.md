# Workflow W3 — Edit and improve

**Discovery status: OPEN.** Last updated 2026-11-05.

## Observed current state [V/D]
- Group "Edit": **Review** (inspection, metadata, ratings, prompt edits, mask, outpaint, queued reprocess) and **Photo Optimize** (Quick Edit vs Managed Photo Set, per-photo baselines).
- Other doors into editing: History "Edit Image in Review", History "Regenerate with Changes" (Pipeline draft), Learning Staged Curation → Review, Pipeline sidebar "Edit or Reprocess Existing Image" (only selects Review) (EV-15).
- Masked inpaint and canvas extension: registry-resolved SDXL base on Forge; original pixels restored at artifact finalization; frozen input previews. Smart Review (SAM 2.1 Small / Florence-2) is opt-in, off by default, **unqualified**.
- IMG-03 partial journey: History → Iterate → Edit Image in Review → Edit Mask → frozen Preview → queue. On `origin/main` it **fails by design** on `parent_job_recorded` and `compare_offered_for_the_edit` (EV-07, product lineage defect). Local 833 branch claims repair and a 37/37 PASS archive.
- Retained screenshot of Review at the minimum window shows a 460 px working area, the Images list and Preview side by side, two "Show Guidance" buttons, and the edit actions below the fold (EV-14, EV-15, EV-17).

## Owner direction (brief)
Non-destructive edit/compare/reprocess; reuse prior results; consistent source selection and asset previews; masked-edit lineage must not be conflated with cosmetic issues.

## Confirmed decisions (repository)
Replay/edit creates a new NJR with parent lineage; edits go through Preview → Add to Queue (`AGENTS.md`). Smart Review suggestions only. Photo Optimize persistence stays independent of Review.

## Hypotheses [H]
H1: Operators think "improve this image" (fix a region / enlarge / fix faces / change style), not "Review vs Photo Optimize". H2: A single *selected asset* context (with the shared MediaInspector) removes re-selection when moving between inspect, mask, compare and reprocess. H3: Compare-with-parent should be a default view of any derived result, which requires EV-07 resolved first.

## Alternatives
(a) Keep two tabs; unify navigation and the selected-asset strip. (b) One *Edit / Improve* workspace with task chips (Fix region, Extend, Upscale, Restyle, Batch). (c) Edit as a mode of Library/History (asset-centric).

## Flows
Current: pick image (several doors) → Review → mask/outpaint/reprocess → Preview frozen job → Add to Queue → result in History → Compare with Parent (if lineage). Ideal: PENDING. Differences: unknown; lineage gap is known (EV-07).

## Discovery contract — status
1 Goal PENDING · 2 Inputs: image(s), optional mask, prompt · 3–5 PENDING · 6 Expert: stage selection, ADetailer, denoise, outpaint padding · 7 Duplicates: Review/Photo Optimize/History iterate · 8 Reuse: parent lineage, baselines · 9 AI: Smart Review caption/mask suggestions (unqualified) · 10 Boundaries: frozen Preview before queue; original preserved · 11 Failure: refusals with reason on unsupported jobs [D] · 12 Artifact: derived image with parent link · 13 Acceptance: none.

## Open questions
Q1 Which edit tasks are common enough to be first-class? Q2 Is Photo Optimize's managed-photo-set model still valued as a separate concept? Q3 Should every derived image show its parent automatically? Q4 Is Smart Review ever to move from opt-in to suggested-by-default (needs qualification first)?
