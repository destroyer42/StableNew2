# Workflow W5 — Storyboards and movies

**Discovery status: OPEN.** Last updated 2026-11-05.

## Observed current state [V/D]
- A multi-shot sequence is **one job with N internal segments** (exact-frame carry-forward, one warm-runtime release, durable ledger, strict resume as a new job, in-job assembly). Queued from Video Workflow's "Multi-shot sequence" section; Job History shows segment progress with Resume and Replay.
- Persistent editable **Storyboard** JSON drafts, source identities, safe History reconstruction (`docs/Subsystems/Video/STORYBOARDS.md` [D]).
- **Movie Clips**: file-list and assembly workspace; assembly is a queued CPU `movie_assembly` job; no inline viewer (ownership map).
- VID-03 full desktop journey: author, save, reopen, reorder, preview, queue a three-shot Storyboard (EV-31). Strict resume/replay not driven (INT only).
- Admission defect GP832-F4: blank form-level motion prompt refused although every shot has its own; message did not name the field (EV-10). Local 833 repair changes policy (form check skipped for sequences).
- GP833-O1 (WONTFIX): "Discard unsaved draft changes?" after form-only prep (EV-32).

## Owner direction (brief)
Guided multi-step workflows (storyboard-like) are an AI Tier 3 candidate, bounded and independently admissible. No other owner statement on storyboards in the brief.

## Confirmed decisions (repository)
Movie assembly queued on the canonical path (decision 10); selective suffix regeneration needs its own later contract (`STATUS.md` Active).

## Hypotheses [H]
H1: A timeline/ordered-source view is the natural mental model for both Storyboard and Movie Clips (the audit asked for one; it is not confirmed built). H2: "Shot" prompt vs "form" prompt is a duplicate-field problem to resolve in design, not only in copy. H3: Movie Clips could be a final step of a project rather than a tab.

## Alternatives
(a) Keep Storyboard inside Video Workflow. (b) A dedicated *Sequence* workspace (timeline). (c) Merge Storyboard and Movie Clips into one *Movie* workspace.

## Flows
Current: Video Workflow → sequence section → author shots → Queue Sequence → progress in History → Resume/Replay → Send to Movie Clips → assemble. Ideal: PENDING.

## Discovery contract — status
1–5 PENDING · 6 Expert: per-shot controls, anchors, strict resume · 7 Duplicates: form vs shot prompt · 8 Reuse: Storyboard drafts, clips · 9 AI: plan-from-goal is a Tier-3 research topic, nothing built · 10 Boundaries: one job, ledger, strict resume · 11 Failure: refusal copy (EV-10) · 12 Artifact: assembled movie, playable · 13 Acceptance: none.

## Open questions
Q1 Is Storyboard authoring a primary use case or an expert one? Q2 Should shots be reorderable on a visual timeline? Q3 What should Resume vs Replay look like to a non-technical operator? Q4 Is continuity quality (physical) required before simplifying this surface?
