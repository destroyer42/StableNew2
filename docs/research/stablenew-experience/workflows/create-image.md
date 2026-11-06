# Workflow W1 — Create image

**Discovery status: OPEN** (owner has not reviewed). Last updated 2026-11-05. Evidence IDs refer to [EVIDENCE_REGISTER](../EVIDENCE_REGISTER.md).

## Observed current state [V/D]
- Entry: Prompt tab (authoring) and Pipeline tab (sidebar composer, Working Settings, Preview, Queue, Job History); header Run/Preview/Stop. Group "Create" holds Prompt and Pipeline (EV-30).
- Pipeline composer: **Generate** (txt2img), **Improve Result (optional)** (ADetailer, upscale), collapsed **Advanced and legacy stages** (img2img); Refiner/Hires inside one disclosure (ownership map, PR-GUI-UX-530).
- Path: PromptPack → Preview (frozen jobs) → Add to Queue (queue-first; Run Now only enqueues) → Job History → image. Preview thumbnail only shows a *saved* image, never generates one.
- IMG-01 full desktop journey passes at normal/minimum/maximized with direct reachability after PR-831 (EV-01..03). Stages ADetailer/upscale are off in that journey.
- Settings scopes visible in this area: PromptPack Settings, Saved Pack List, Working Settings + Current Job Overrides, Startup Defaults, Application Defaults, generation profile (EV-21).

## Owner direction (from the brief; not yet confirmed per workflow)
Operators should reach a useful outcome without knowing backend/model-family distinctions; one obvious primary action per task state; required parameters visible before admission; concise effective-settings summary.

## Confirmed product decisions (repository)
Queue-first; frozen NJR; GUI does not build backend payloads or call the runner (`AGENTS.md` §2). Forge default, A1111 rollback (`STATUS.md`). Retained persisted tab IDs (audit 2026-10-22 "do not renumber").

## Owner product intent (2026-11-05, DR-A34)

**Status:** accepted **product intent** from the owner. These are product directions, **not** necessarily existing repository authority and **not** previously approved engineering scope; each needs its own package before it changes behavior. This section separates *intent*, *what exists*, and *conflicts or gaps with existing authority*. Nothing in the repository was changed or overwritten.

| Intent (owner's wording, condensed) | What exists today [V = read in docs/source; not run] | Conflict or gap with existing authority |
|---|---|---|
| **Hybrid Create Image:** a straightforward creation form with a recommended model/profile and immediate manual override | *Partly.* Creation spans two tabs: Prompt (authoring) and Pipeline (composer, Model row, Working Settings) (EV-30). A Profile strip sits under the Model row (No profile, Research, Learning, Custom). Working settings are editable immediately; a profile touches only the editable working settings [V: `GUI_Ownership_Map_v2.6.md`, `MODEL_PROFILES.md` section 17]. The name "Hybrid Create Image" appears nowhere in `src/` or `docs/` outside this research (`git grep -i hybrid` finds only unrelated hits) | (1) There is **no single "straightforward form"**; unifying Prompt and Pipeline changes navigation, and the audit direction to preserve top-level groups and stable tab IDs is superseded for *research only* (DR-A15), not for production. (2) A profile is **advisory and never owns execution**; `ModelPolicy` stays final (`MODEL_PROFILES.md` section 17), so "recommended model" must come from a deterministic closed-list source, not a new authority. The existing system recommends a *profile for a chosen model*; it does **not** recommend a *model*. (3) Header Run and Pipeline Queue/Preview both act on creation (H2 below). |
| **Automatic model profiles:** selecting a model applies appropriate model-specific configuration, with visible changes and preservation of valid user overrides | *Largely implemented and merged on `main`:* PR-IMG-PROFILE-630 (#208) and PR-LEARN-PROFILE-660 (#213). Choosing a checkpoint applies the favorite, else the Research, profile to the editable working settings only; prompt text, stage flags and stage intent are untouched; a VAE never crosses model families; a sampler/scheduler the runtime does not offer is reported, not rewritten; `plan_application` returns changes plus per-setting notes (applied, kept, policy-blocked, not offered, reset, unavailable) [V: `src/generation_profiles/application.py`, `MODEL_PROFILES.md` section 17] | (1) **Visible changes:** the strip shows one status line and a Details toggle with per-setting evidence; whether each *changed value* is visible at a glance is **unmeasured**. (2) **Preservation of valid user overrides:** source review shows that a setting the new profile *does* recommend (sampler, scheduler, steps, CFG, size, VAE) is replaced on checkpoint selection; only settings with *no* recommendation are kept (`NOTE_KEPT`) and unsupported values are reported. I found **no mechanism that preserves a manual edit** to a setting the profile also recommends. This is a source reading, **not run**; it is the main behavioral gap against the stated intent and needs owner confirmation of what "valid override" means when a model is re-selected (DR-O23). (3) Profiles are *advisory*; "automatic application" is already bounded by `ModelPolicy` and by "never auto-publish" rules for Learning/Catalog candidates (`MODEL_PROFILES.md` section 17), which any broadened automation must keep. |
| **Customizable basic interface:** operators may promote frequently used advanced settings into the main Create Image workspace | **Not implemented.** No pin or promote mechanism exists in `src/gui` or `src/gui_v2` (`git grep` for pinned/promote settings finds only unrelated hits such as pinned runtimes and a pinned Storyboard workflow) | (1) **Persistence:** pinned choices must persist, which touches saved workspace state and settings semantics; they would need a new key and `atomic_io` persistence, and must not become a second settings authority (pinned controls must bind to the same working-setting variables the stage cards use). (2) **Disclosure rules** proposed in this research (two levels; no admission-required control hidden, DESIGN_SYSTEM_CANDIDATE section 3) interact with user-chosen layouts. (3) **Layout contracts:** the composer structure from PR-GUI-UX-530 and the geometry tests (`test_design_foundation_400.py`) assume a fixed arrangement. (4) **Startup defaults** (`startup.py`) save a fixed set of values; whether pins belong there is undefined. |

Open questions this intent leaves: what counts as a "valid" override across a model change (DR-O23); whether "recommended model" is wanted at all or only "recommended profile for the chosen model"; where pins live and whether they are per model, per profile or global.

## Hypotheses [H]
- H1: The minimum useful path is *prompt → model → count → Queue* and the rest belongs behind one disclosure level.
- H2: Header Run and Pipeline Queue/Preview duplicate each other's role for new users.
- H3: Showing Draft/Preview/Queued/Running/Done as one progression strip beside the primary action reduces navigation to Job History.

## Alternatives
(a) Keep Prompt and Pipeline as two tabs, improve cross-links. (b) Merge into one *Create* workspace with Author / Review-before-queue / Results zones. (c) Wizard for first-time use over (a) or (b).

## Current-state flow → ideal-state flow → differences
Current: Prompt (author) → Pipeline (choose pack/model/profile/stages) → Preview → Add to Queue → Job History to see result. Ideal: **PENDING owner**; candidate in `EXPERIENCE_ARCHITECTURE.md` §3. Differences are unknown until the ideal is stated.

## Discovery contract — status
1 Goal/situation: PENDING · 2 Inputs: PENDING (pack, prompt, model are the known inputs) · 3 Minimum actions: PENDING (current count unmeasured, see VALIDATION T1) · 4 Info at decision points: PENDING · 5 Basic-path settings: PENDING · 6 Expert controls: observed list only (stages, Refiner/Hires, ControlNet) · 7 Duplicated steps: H2 · 8 Reuse of prior assets: Job History "Regenerate with Changes" exists [D] · 9 AI help: Prompt Suggest disabled (EV-35) · 10 Approval/safety: queue admission, frozen NJR [V] · 11 Failure explanation: backend/model reason visibility is an open defect (EV-08) · 12 Finished artifact/follow-on: image in History; follow-ons Edit, Make Video · 13 Owner acceptance examples: **none provided**.

## Open questions
Q1 Is Prompt a separate task or a step of Create? Q2 Which of the six settings scopes must the operator ever see on the basic path? Q3 Should the operator see the chosen backend, or only a capability summary? Q4 What is the acceptance example (e.g., "queue 4 images of a described scene in ≤ N actions")? Q5 Are any *required* parameters currently inside a disclosure (EV-19)?
