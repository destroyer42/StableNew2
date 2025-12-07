# Journey Test Plan (2025-11-26_1115)


# StableNewV2 — Journey Test Plan

This document defines the **Journey Test Suite** for StableNewV2.  
Journey tests validate **complete end‑to‑end workflows** across the Prompt, Pipeline, Learning, WebUI, Logging, and Presets systems.
Pipeline configuration lives entirely in the **Pipeline** tab (Run tab removed); journeys reference that tab as the single staging area for txt2img/img2img/upscale.

---

# 1. Journey Test Inventory

| ID | Name | Purpose | Status |
|----|------|---------|--------|
| JT‑01 | Prompt Pack Creation & Randomization | Authoring workflow | New |
| JT‑02 | LoRA/Embedding Integration | Prompt → Pipeline continuity | Partial |
| JT‑03 | txt2img Pipeline Run | Baseline generation | Partial |
| JT‑04 | img2img / ADetailer Run | Image transformation | New |
| JT‑05 | Upscale Stage Run | High-res refinement | New |
| JT‑06 | Video Pipeline Run | Future | Future |
| JT‑07 | Startup + Async WebUI Bootstrap | App readiness | New |
| JT‑08 | Single-Variable Learning Plan | Baseline learning | Partial |
| JT‑09 | X/Y Learning Plan | Two-variable experiments | Future |
| JT‑10 | Ratings & Review | Rating lifecycle | Partial |
| JT‑11 | Presets/Styles | Reusable configs | Future |
| JT‑12 | Run/Stop/Run Lifecycle | Controller stability | Partial |
| JT‑13 | Logging & Error Surfacing | End-user diagnostics | New |

---

# 2. Journey Test Descriptions

## JT‑01 — Prompt Pack Creation & Randomization
Design and save a new prompt pack with:
- 10×5-line structure  
- negative prompts  
- randomized tokens  
- LoRA/embedding tokens  

Artifact: prompt pack file.

---

## JT‑02 — LoRA / Embedding Integration
Confirm:
- LoRA tokens parsed in Prompt tab  
- Appearing as runtime modifiable controls in Pipeline  
- Affecting output  

Artifact: LoRA/embedding metadata + run result.

---

## JT‑03 — txt2img Pipeline Run
Validate:
- Correct prompt load  
- Correct stage activation  
- Image produced via configured sampler/scheduler  

Artifact: txt2img image + metadata.

---

## JT‑04 — img2img / ADetailer Run
Validate:
- Base image flows correctly  
- Refinement pipeline operates as expected  

Artifact: refined image.

---

## JT‑05 — Upscale Stage Run
Validate:
- solo upscale workflow  
- multi-stage (txt2img → upscale) chain  

Artifact: upscaled image.

---

## JT‑06 — Video Pipeline Run (Future)
Reserved for future video PRs.

---

## JT‑07 — Startup + Async WebUI Bootstrap
Validate:
- Fast GUI load  
- Async detection  
- Correct transition to READY  

Artifact: valid WebUI cache + successful job.

---

## JT‑08 — Single-Variable Learning Plan
Validate:
- Experiment definition  
- Plan building  
- Execution  
- Rating entries  

Artifact: LearningRecord JSONL entries.

---

## JT‑09 — X/Y Learning Plan (Future)
Reserved for PR‑3Q.

---

## JT‑10 — Ratings, Review & Learning Records
Validate:
- Variant navigation  
- Re-rating  
- Persistence  

Artifact: updated LearningRecord entries.

---

## JT‑11 — Presets/Styles (Future)
Reserved for presets/automation PR.

---

## JT‑12 — Run / Stop / Run Again Lifecycle
Validate:
- Controller state transitions  
- UI responsiveness across runs  

Artifact: clean logs.

---

## JT‑13 — Logging & Error Surfacing
Validate:
- User-facing error messages  
- Log viewing/exporting  

Artifact: accessible logs.

---

# 3. Mapping Journey Tests to PRs

| Journey | PR Dependencies |
|--------|------------------|
| JT‑01 | PR‑1A → 1H |
| JT‑02 | PR‑1G/1H + Pipeline PR |
| JT‑03 | Pipeline PR |
| JT‑04 | Pipeline PR |
| JT‑05 | Pipeline PR |
| JT‑07 | WebUI bootstrap PR |
| JT‑08 | PR‑3A → 3F |
| JT‑10 | PR‑3H |
| JT‑12 | Controller Lifecycle PR |
| JT‑13 | Logging subsystem |

Future journeys (JT‑06, JT‑09, JT‑11) depend on future PRs.

---

# 4. Next Step
After reviewing this document and the Roadmap, we will generate **JourneyTest_JT‑01.md through JT‑13.md** as full step-by-step specifications.
