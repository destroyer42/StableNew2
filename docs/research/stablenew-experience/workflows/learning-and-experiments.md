# Workflow W6 — Learning and experiments

**Discovery status: OPEN.** Last updated 2026-11-05.

## Observed current state [V/D]
- One tab (group "Learn") with sub-tabs **Designed Experiments / Discovered Outputs / Staged Curation**; Designed Experiments presented as **Design → Preview → Run → Compare → Rate** with one primary action (PR-LEARN-UX-590).
- Studies: Model Comparison, Two-Axis Grid, Prompt Slot, LoRA Composition, Embedding, Prompt×Model Matrix, qualification proposals, *What Should I Test Next?* (deterministic, read-only, no AI) (LEARNING §3.x).
- Ratings are evidence; descriptive studies never auto-recommend; publication of Learning profiles is explicit.
- Layout history: at 1280×680 the Rating box collapsed (EV-01) and the Images list sat behind the Operator Log (EV-02); both repaired in PR-831 and accepted by sealed archives. A retained screenshot of the repaired minimum window still shows the Learning header/step bar/plan summary occupying most of the visible height (EV-14; not pixel-measured).
- LRN-01 and LRN-02 are full desktop journeys; Model Comparison and Prompt×Model Matrix are integration-only.
- Learning shares a 4,000-line controller that compiles prompts and NJRs (`PHOTO_REVIEW_REPROCESS.md` §7.1) — a structural constraint on any UI rewrite (EV-34).

## Owner direction (brief)
Controlled Learning experiments appear as an AI Tier-3 candidate; improvement monitoring should reuse deterministic evidence checks.

## Confirmed decisions (repository)
Observational and experimental evidence stay distinct; ratings from grids never feed recommendations; nothing auto-applies (LEARNING invariants).

## Hypotheses [H]
H1: Operators want "find out which setting is better for me", of which Designed Experiments is one expert path. H2: Discovered Outputs is an *inbox of unrated outputs*, closer to Library than to experimentation. H3: Staged Curation and Review overlap in purpose.

## Alternatives
(a) Keep Learn as one workspace; reduce header height and add a step-aware layout. (b) Split into *Experiment* (design/run/compare) and *Rate / Curate* (inbox) with Library. (c) Hide special studies behind "Advanced" (audit direction).

## Flows
Current: Design → Preview (frozen) → Run (confirmed Queue) → Compare → Rate → recommendations/publication. Ideal: PENDING.

## Discovery contract — status
1–5 PENDING · 6 Expert: special studies · 7 Duplicates: Discovered Outputs/History, Staged Curation/Review · 8 Reuse: ratings, profiles · 9 AI: Tier-3 candidate only · 10 Boundaries: frozen Preview, whole-selection preflight, no auto publication · 11 Failure: admission/resume uncertainty remains visible [D] · 12 Artifact: findings, profile · 13 Acceptance: none.

## Open questions
Q1 How often does the operator run designed experiments vs rate loose outputs? Q2 Should Learning be a destination or a layer over Library? Q3 What is the smallest experiment a non-expert would run? Q4 Is the Learning controller extraction a precondition for any UI change?
