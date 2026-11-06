# Workflow W2 — Prompt and models

**Discovery status: OPEN.** Last updated 2026-11-05.

## Observed current state [V/D]
- Prompt tab: slots, Cinematic Template, LoRA browser/keywords, Matrix, ControlNet units (OpenPose/Canny/Depth, pre-rendered or on-request maps), optimizer, "Adapt for Target…", "Suggest…" (disabled, EV-35).
- Pipeline: Model combobox + Generation profile strip (No profile / Research / Learning / Custom; favorite starred). Picking a checkpoint applies that model's preferred profile; restores never re-apply.
- Exact profiles: FLUX.2 Klein 4B FP8; Z-Image-Turbo FP8 (physical qualification inconclusive); Klein Base 9B refused (`NO_GO_RESOURCE_RISK`). Model-family differences handled by `ModelPolicy`/adaptation, not by the operator picking an engine.
- IMG-02 full desktop journey: PromptPack edit/reload, model switch, effective settings, queue (EV-31). Klein/Z-Image only *selected and read*, never generated in a journey.
- Audit open items (2026-10-22, [C,O,T], **not re-verified**; some superseded by UX-530/540/550): Matrix semantics (sequential fanout, unseeded random), optimizer effective ordering, ineffective anchor-boost option, style-LoRA examples requiring uninstalled weights, low-level ControlNet fields.

## Owner direction (brief)
Operators should not need Forge/A1111/Comfy/SVD/family distinctions. Backend choice may be automated only by a deterministic, verified capability-policy decision the operator can inspect and override where legal. No silent routing to an unsupported backend; no change to a frozen NJR.

## Confirmed decisions (repository)
Backend neutrality via adapters; profiles are advisory; publication of Learning profiles is explicit and never auto-applied (`STATUS.md`, `MODEL_PROFILES.md`). Prompt text never becomes a setting recommendation (Learning §3.11).

## Hypotheses [H]
H1: Model + profile choice can be one control with a *plain-language capability line* ("Good for portraits; 1024 px; needs 8 GB") instead of exposing backend names. H2: Effective-settings summary should sit beside the primary action, not in a separate preview. H3: ControlNet/LoRA/Matrix belong in a second disclosure level.

## Alternatives
(a) Keep Model row; improve wording only. (b) Intent-based "what are you making?" selecting model+profile through policy, with an Advanced override. (c) Presets-as-recipes (note: legacy recipes/presets were retired deliberately, UX-520 — reintroducing "preset" language needs an owner decision).

## Flows
Current: author prompt → pick pack → pick model → profile auto-applies → read Effective Settings in Preview. Ideal: PENDING. Differences: unknown.

## Discovery contract — status
1–5 PENDING · 6 Expert controls: LoRA weights, embeddings, Matrix, ControlNet, optimizer · 7 Duplicates: model/profile also in Learning baselines · 8 Reuse: PromptPacks, History · 9 AI: Suggest/Adapt (deterministic adapter exists; AI disabled) · 10 Safety: `ModelPolicy` authoritative, strict validator on AI text · 11 Failure: model/backend mismatch reasons exist at preflight; operator-facing wording unmeasured · 12 Artifact: pack + effective config · 13 Acceptance examples: none.

## Open questions
Q1 Which backend/model facts may ever be hidden vs must always be shown? Q2 Is a profile a user concept or an internal one? Q3 Is Matrix (variation) a prompt feature or a Learning feature for the operator? Q4 Which audit findings are still true in the live app? (needs live walk)
