# Workflow W4 — Video and motion

**Discovery status: OPEN.** Last updated 2026-11-05.

## Observed current state [V/D]
- Group "Motion": **Video Workflow** (Comfy; task-first form: a Make selector, suggested settings, three collapsed disclosures; PR-VID-UX-360), **SVD Img2Vid** (native SVD XT), **Movie Clips** (assembly).
- **Make Video** appears on Review, Job History and the Pipeline preview; loads the image into Video Workflow with the recommended approved workflow preselected; Queue feedback inline and non-modal; finished clips play in-app under Recent outputs (Open, Reveal, Send to Movie Clips).
- Production video backends: native SVD XT and Comfy workflows marked `approved` (Wan2.2 TI2V-5B 1.2.0 and 1.3.0). Others experimental with per-job opt-in; Fun Control 5B Canny: Queue refused (hardware unqualified).
- Motion Library (local import/tag/search/preview of rendered motion videos; "Use as Driving Video" fills only the driving field after SHA-256/workflow check).
- VID-01 full desktop journey passes (EV-01..03 layouts); VID-02 partial: conversion lane HOLD because Blender is absent (EV-11, infrastructure); Prepare Motion Source not driven.
- RIFE smoothing default on new SVD configs; ping-pong/loop export; secondary motion retired.

## Owner direction (brief)
Operator should not need to understand SVD vs Comfy workflow families. Automated choice only through verified capability policy; inspectable; overridable where legal; never silent routing to an unsupported backend.

## Confirmed decisions (repository)
D2 (2026-10-20): approved Comfy workflows are production; experimental needs the job's own opt-in, never a global switch. Frozen NJR; no re-routing at admission (`AGENTS.md` §2).

## Hypotheses [H]
H1: One *Animate* entry with outcome-oriented controls (length, motion style, driving clip) maps to a workflow via the catalog's governance state and readiness. H2: SVD becomes a policy-selected engine, not a tab, if SVD retains a distinct value (open). H3: Motion Library belongs under Library with a "use for motion" action.

## Alternatives
(a) Keep three tabs. (b) One Animate workspace with SVD and Comfy as an *Advanced → Engine* choice. (c) Animate as a task launched from any image (side sheet) with Video Workflow as the expert surface.

## Flows
Current: select image anywhere → Make Video → Video Workflow (choose what to make: animate an image, follow a driving clip, multi-shot sequence, many images; the engine, length, motion and smoothing are suggested; write the prompt) → queue → Recent outputs player → optional Movie Clips. Ideal: PENDING. Differences: unknown.

## Discovery contract — status
1 Goal PENDING · 2 Inputs: image, optional driving clip, prompt · 3–5 PENDING (task-first form: task, prompt, suggested settings [D]) · 6 Expert: motion guidance, pose strength, sources, experiment opt-in · 7 Duplicates: three Make Video doors; two engines · 8 Reuse: Motion Library, Recent outputs · 9 AI: none yet; "workflow choice" advice is explicitly unavailable until an eligibility-checked closed list exists (AI_ASSIST §10) · 10 Boundaries: experimental opt-in per job; RAM/VRAM readiness · 11 Failure: readiness messaging exists; actionable cause display unmeasured · 12 Artifact: MP4 + manifest · 13 Acceptance: none.

## Open questions
Q1 Does SVD retain a user-visible value beyond Wan? Q2 How should "this will not run here" (RAM, VRAM, missing weights) be shown before Queue? Q3 Is video experiment review a Learning or a Video feature to the operator? Q4 Physical qualification status gates which options can be simplified (conversion, Fun Control).
