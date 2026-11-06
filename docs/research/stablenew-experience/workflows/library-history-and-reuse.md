# Workflow W7 — Library, history and reuse

**Discovery status: OPEN.** Last updated 2026-11-05.

## Observed current state [V/D]
- There is **no Library destination**. Job History lives inside the Pipeline tab (action row, searchable paged *Browse All…* window; text search covers only the first 64 prompt characters and the model; no full-text search).
- History actions (wrapping `FlowRow`): Open Output Folder, Iterate…, Animate with SVD, Make Video, Movie Clips, Explain Job, Review Experiment, Browse All…, Refresh. Iterate from History: Edit Image in Review or Regenerate with Changes (completed single-still txt2img only).
- **Compare with Parent**: typed frozen-settings diff, SHA-256 parent verification, direct pairs only; unavailable for masked edits on `main` because `parent_job_id` is not recorded (EV-07).
- Other asset stores: Motion Library (rendered motion videos), Discovered Outputs (Learning), PromptPack lists, Storyboard drafts, saved experiments, Review/Photo Optimize baselines.
- Shared MediaInspector adopted across Pipeline Preview, History, Review, Photo Optimize, Learning, Video Recent Outputs (Show/Detach/zoom); History and Pipeline start hidden under content-visibility policy.
- History selection → video: playback implemented (UX-510) [D]; History Open-in-viewer "verified as enabled, not clicked" in journeys.

## Owner direction (brief)
Task intent "Library / History"; reuse of prior assets, prompts and results; reusable media/gallery/list components; large-list behavior is a comparison criterion.

## Confirmed decisions (repository)
Repository-projection model: queue and history are projections of `JobRepository`; no second history authority.

## Hypotheses [H]
H1: A Library view (assets first, jobs second) is a more natural place than a sub-panel of Pipeline. H2: "Reuse" (apply prompt/settings, make variant, animate, edit) should be one verb menu on any asset. H3: Large-history performance on Tk Treeview is a risk worth measuring before choosing a toolkit.

## Alternatives
(a) Keep History in Pipeline; add Browse All as primary. (b) Promote *Library* to a top-level destination with Images, Videos, Motion, Packs, Experiments facets. (c) Asset-centric side drawer available from all tabs.

## Flows
Current: Pipeline → Job History → select → action (Open/Iterate/Make Video/Compare). Ideal: PENDING.

## Discovery contract — status
1–5 PENDING · 6 Expert: Explain Job, Debug · 7 Duplicates: Discovered Outputs; Motion Library; History inside Pipeline · 8 Reuse: replay, iterate · 9 AI: search/summarize is a possible future item (needs full-text index first) · 10 Boundaries: replay creates new NJR with lineage · 11 Failure: missing artifacts show explicit missing state [D] · 12 Artifact: any asset with provenance · 13 Acceptance: none.

## Open questions
Q1 Is it important to browse assets independent of the job that produced them? Q2 What searches does the operator actually run (prompt text, model, rating, date, lineage)? Q3 How large are real histories (rows/artifacts)? (unmeasured)
