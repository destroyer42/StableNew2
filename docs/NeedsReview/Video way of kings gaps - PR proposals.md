# Executive Summary

We propose **20 prioritized PRs** to complete StableNew2’s workflows. Each PR focuses on one high-value feature or fix identified above. For each, we provide Motivation, an Implementation Plan (files/functions to change), Tests to add, CI changes, and effort/risk. We preserve the repo’s PR template style (title with `PR-CORE-XXX`, sections, etc.) and cite relevant repo docs or code where helpful. A summary table maps each PR to code evidence. Mermaid diagrams at end illustrate workflow dependencies. 

## PR Plans

### PR-CORE-001: Add Native Stable Video Diffusion (SVD) Backend Tab

**Motivation:** StableNew can animate images via AnimateDiff/WebUI but lacks a built-in SVD pipeline. We need a **self‑hosted SVD tab** for one-click image-to-video (per spec【148†L79-L88】). This enables short-clip generation without external UI.

**Implementation Plan:**  
- **Files to Create:** Under `src/video/svd_*` (see docs【148†L79-L88】) – e.g. `svd_service.py` (wraps Diffusers `StableVideoPipeline`), `svd_runner.py` (orchestrates preprocess/generation/export), `svd_export.py` (ffmpeg export).  
- **Files to Modify:** `src/gui/main_window_v2.py` (register new SVD tab), `src/controller/app_controller.py` (hook up SVD controller), `src/pipeline/job_models_v2.py` (support `svd_native` stage type)【148†L107-L115】.  
- **Controller & UI:** Create `SVDTabFrameV2` UI for selecting an image, parameters (fps, prompt), and a “Generate” button. Add `SVDController` to validate inputs.  
- **Pipeline:** In the NJR executor, detect `svd_native` stages and call `svd_service`. Use `video_export.py` to produce an MP4 (per doc【148†L81-L90】).  
- **Error Handling:** Validate aspect ratio (landscape vs portrait), throw user error for invalid images.  
- **Tests to Add:** `tests/video/test_svd_service.py`, `test_svd_runner.py` to mock Diffusers pipeline (use a dummy image). GUI test for SVD tab loading (`test_svd_tab_frame_v2.py`).  
- **CI Changes:** Add new tests in `tests/video/`; ensure Diffusers SVD is in `requirements-svd.txt`.  
- **Effort:** **M** – substantial code but guided by spec【148†L79-L88】.  
- **Risk:** Medium – new UI and pipeline integration.  
- **Reviewers:** @destroyer42, @pipeline-team.  
- **Milestone/Labels:** `Video-Phase1`, `feature`.

### PR-CORE-002: Implement Character Embedding (LoRA/Textual Inversion)

**Motivation:** We need consistent character appearance. A **LoRA/Textual-Inversion pipeline** will train embeddings for each main character (e.g. Kaladin). This aligns with best practices【134†L282-L289】.

**Implementation Plan:**  
- **Files to Create:** `src/training/character_embedder.py` – handles dataset collection/training (wraps Automatic1111 or diffusers). `src/training/lora_manager.py` – load/apply LoRAs.  
- **Files to Modify:** Add options in GUI for “Train Character Embedding” (maybe in artist tools panel). Extend `JobBuilder` to include a “train-LoRA” job.  
- **Data:** Expect user to supply ~100 images per character (could integrate webUI exporting). Use naming convention `<CharacterName>_<version>.pt` saved in `data/embeddings/`.  
- **Tests to Add:** Unit tests for embedding loader; integration test mocking the training function (no actual GPU call).  
- **CI Changes:** None immediate (training may be offline).  
- **Effort:** **L** – complex ML integration.  
- **Risk:** High – many edge cases in ML training.  
- **Reviewers:** @ml-team, @sdexpert.  
- **Milestone/Labels:** `Feature`, `loRA`.

### PR-CORE-003: Add Scene/Shot Planning Module

**Motivation:** To map book content to shots, we need a **scene planner**. Preliminary classes exist (`story_plan_models.py`), but no end-to-end mechanism.

**Implementation Plan:**  
- **Files to Create/Modify:** Extend `src/video/story_plan_store.py` to load a sequence of scene descriptions. Develop a CLI or GUI to import a text (e.g. chapter) and break it into scenes using an LLM (or manual editor UI).  
- **Integration:** Tie the plan to PromptPack creation: each scene yields a PromptPack.  
- **Tests to Add:** Simulate short story text and assert correct number of scenes.  
- **Effort:** **M** (logic heavy, depends on NLP or manual input).  
- **Risk:** Medium (LLM results may vary).  
- **Reviewers:** @nlp-team.  
- **Milestone/Labels:** `Feature`, `StoryPlanner`.

### PR-CORE-004: Cinematic Prompt Template Library

**Motivation:** Provide **predefined prompt templates** (action, environment, camera angles) for consistency. Users should not craft every phrase from scratch.

**Implementation Plan:**  
- **Files to Create:** `data/prompt_templates.json` or similar. In code, load these templates in PromptPack builder.  
- **Integration:** Modify PromptPack builder (maybe `src/services/prompt_pack.py`) to allow selecting a template category.  
- **Examples:** Include templates like “Wide shot of {scene} at sunrise, epic lighting” or “Close-up on {character}, dynamic pose”.  
- **Tests to Add:** Ensure the PromptPack system correctly interpolates placeholders.  
- **Effort:** **S**.  
- **Risk:** Low.  
- **Reviewers:** @ui-team.  
- **Milestone/Labels:** `Enhancement`, `Templates`.

### PR-CORE-005: Integrate Camera Control/ControlNet

**Motivation:** Allow specifying camera moves or poses (e.g. animate camera through a scene). Use **ControlNet** for depth/pose guidance.

**Implementation Plan:**  
- **Files to Modify/Create:** Add optional `depth_map` or `pose_data` input in `svd_preprocess.py`. Extend workflow compiler to accept a “camera_motion” parameter. Possibly integrate [ControlNet](https://github.com/lllyasviel/ControlNet) in `svd_service.py`.  
- **UI:** In SVD/Gallery, allow uploading a depth map or selecting preset camera path.  
- **Tests:** If integrated with Comfy, mock a depth input and ensure it’s passed to the pipeline node.  
- **Effort:** **M**.  
- **Risk:** High (new dependency).  
- **Reviewers:** @ml-team.  
- **Milestone/Labels:** `Feature`, `ControlNet`.

### PR-CORE-006: Frame Interpolation / Flicker Reduction

**Motivation:** Enhance video smoothness by interpolating extra frames. This reduces flicker.

**Implementation Plan:**  
- **Files to Create:** `src/video/frame_interpolator.py` – use a model like RIFE or simple linear interpolation (OpenCV).  
- **Integration:** After SVD output, call interpolator if “smooth” option is set.  
- **Tests:** Verify that calling the function on two frames yields intermediate frames.  
- **Effort:** **S**.  
- **Risk:** Medium.  
- **Reviewers:** @video-team.  
- **Milestone/Labels:** `Enhancement`, `Interpolation`.

### PR-CORE-007: Video Composition & Stitching

**Motivation:** Stitch multiple clips into longer sequences with transitions. Useful for scene assembly.

**Implementation Plan:**  
- **Files to Create:** `src/video/video_stitcher.py` – wrap ffmpeg via `imageio_ffmpeg` to concat clips or add fades.  
- **Integration:** After all PromptPacks of a chapter run, call stitcher on their outputs.  
- **Tests:** Create dummy mp4s and assert they combine into one file of correct duration.  
- **Effort:** **S**.  
- **Risk:** Low.  
- **Reviewers:** @video-team.  
- **Milestone/Labels:** `Enhancement`, `Stitching`.

### PR-CORE-008: Style Consistency LoRA

**Motivation:** Enforce a uniform artistic style (lighting, color) across scenes via a shared LoRA.

**Implementation Plan:**  
- **Files to Create:** Extend LoRA manager (`lora_manager.py`) to load an optional “style LoRA”.  
- **Usage:** If user selects a style tag (e.g. “cyberpunk”), automatically append it to all prompts.  
- **Tests:** Unit-test loading and applying the LoRA to a prompt.  
- **Effort:** **M**.  
- **Risk:** Medium.  
- **Reviewers:** @ml-team.  
- **Milestone/Labels:** `Enhancement`, `Style`.

### PR-CORE-009: Scheduler/Sampler UI Options

**Motivation:** Allow user to choose sampler (DDIM, Euler) and step count in GUI.

**Implementation Plan:**  
- **Files to Modify:** Add dropdown fields in SVD/WebUI tabs for scheduler and steps (modify `PromptPack` parameters or stage config).  
- **Backend:** Use these values when calling `pipe(num_inference_steps=..., sampler=...)`.  
- **Tests:** Validate that setting a scheduler produces different image pattern.  
- **Effort:** **S**.  
- **Risk:** Low.  
- **Reviewers:** @ui-team.  
- **Milestone/Labels:** `Enhancement`, `UI`.

### PR-CORE-010: Performance / Memory Optimization

**Motivation:** Ensure video can run on limited GPU (e.g. 10-12GB) and faster execution.

**Implementation Plan:**  
- **Files to Modify:** Enable XFormers (`pipe.enable_xformers_memory_efficient_attention()`) in `svd_service.py`.  
- **Config:** Add a config flag to use 16-bit or 32-bit.  
- **Tests:** No direct test; measure memory usage manually.  
- **CI:** Add `torch`/`xformers` to requirements.  
- **Effort:** **M**.  
- **Risk:** Medium (GPU dependency).  
- **Reviewers:** @infra-team.  
- **Milestone/Labels:** `Optimization`, `Performance`.

### PR-CORE-011: End-to-End Pipeline Tests

**Motivation:** Provide regression coverage for text→video path.

**Implementation Plan:**  
- **Files to Create:** `tests/integration/test_full_pipeline.py`. In pytest, simulate a simple prompt through the entire pipeline (mock model for speed).  
- **CI Changes:** Ensure integration tests are run (add to pytest invocation).  
- **Effort:** **M**.  
- **Risk:** Low.  
- **Reviewers:** @qa-team.  
- **Milestone/Labels:** `Testing`.

### PR-CORE-012: Enhanced Logging & Metrics

**Motivation:** Add detailed logging (durations, errors) for each stage to aid debugging.

**Implementation Plan:**  
- **Files to Modify:** In all major steps (`runner`, `service`, `executor`), add logging entries (e.g. `logger.info("PromptPack X started at...")`).  
- **Format:** Include timestamps, stage names.  
- **Tests:** None needed; just manually review logs.  
- **CI Changes:** None.  
- **Effort:** **S**.  
- **Risk:** Low.  
- **Reviewers:** @logging-team.  
- **Milestone/Labels:** `Refactor`.

### PR-CORE-013: Config Consolidation & CLI Options

**Motivation:** Unify WebUI/Comfy settings and add CLI for batch jobs.

**Implementation Plan:**  
- **Files to Modify:** Merge WebUI and Comfy config in `ConfigManager`. Add CLI flags in `main.py` (e.g. `--run-prompt-pack <file>`).  
- **Tests:** Add unit tests for CLI argument parsing.  
- **Effort:** **M**.  
- **Risk:** Low.  
- **Reviewers:** @infra-team.  
- **Milestone/Labels:** `Enhancement`, `CLI`.

### PR-CORE-014: Multi-Character Support

**Motivation:** Allow scenes with multiple named characters, applying separate LoRAs per character.

**Implementation Plan:**  
- **Files to Create:** In `story_plan_models`, allow multiple `{actor: "Kaladin", lora: "Kaladin_LoRA"}` entries. Update generation to insert all relevant LoRA tags.  
- **UI:** Enable specifying multiple character tokens.  
- **Tests:** Ensure prompts correctly contain all tags.  
- **Effort:** **M**.  
- **Risk:** Medium.  
- **Reviewers:** @pipeline-team.  
- **Milestone/Labels:** `Enhancement`.

### PR-CORE-015: Prompt/Output Metadata Logging

**Motivation:** Record prompt text, seeds, and LoRA names for each generated image/frame.

**Implementation Plan:**  
- **Files to Modify:** In `svd_runner`, after generation, write a JSON record alongside each output image (fields: prompt, seed, LoRAs used).  
- **Tests:** Check that metadata file matches expected schema.  
- **Effort:** **S**.  
- **Risk:** Low.  
- **Reviewers:** @qa-team.  
- **Milestone/Labels:** `Enhancement`, `Logging`.

### PR-CORE-016: GUI V2 Polishing

**Motivation:** Fix UI layout issues and ensure all features are exposed (pending from PR-CORE-D)【146†L23-L26】.

**Implementation Plan:**  
- **Files to Modify:** `src/gui/panels_v2` and `src/gui/widgets` to align elements (reference PR backlog). Add missing panels (prompt editor, prompt archive).  
- **Tests:** GUI contract tests (ensure tabs exist).  
- **Effort:** **M**.  
- **Risk:** Low.  
- **Reviewers:** @ui-team.  
- **Milestone/Labels:** `UI`, `Refactor`.

### PR-CORE-017: ControlNet & Depth Map Support

**Motivation:** Allow usage of depth or edge maps as generation hints.

**Implementation Plan:**  
- **Files to Modify:** In Comfy workflow or `svd_service`, add optional ControlNet pipeline nodes. Extend UI to accept a depth image input.  
- **Tests:** Mock depth array and ensure it’s passed into the pipeline.  
- **Effort:** **L**.  
- **Risk:** High (new feature with dependencies).  
- **Reviewers:** @ml-team.  
- **Milestone/Labels:** `Feature`, `ControlNet`.

### PR-CORE-018: Documentation and Usage Example

**Motivation:** Provide a clear “how-to” for book-to-video, including commands.

**Implementation Plan:**  
- **Files to Create:** `docs/WoK_scenes_workflow.md` – step-by-step example using sample prompts. Include exact pytest/CLI commands (e.g. `python main.py --config path`).  
- **Tests:** None.  
- **Effort:** **S**.  
- **Risk:** Low.  
- **Reviewers:** @doc-team.  
- **Milestone/Labels:** `Documentation`.

### PR-CORE-019: Book Ingestion Tool

**Motivation:** Simplify turning *The Way of Kings* text into scene prompts.

**Implementation Plan:**  
- **Files to Create:** `src/tools/book_parser.py` – parse an ebook (text or markdown) and output chapter/scene summaries. Use a basic keyword or LLM extraction.  
- **Integration:** Save output as JSON; allow import into story planner.  
- **Tests:** Run parser on a known text snippet.  
- **Effort:** **M**.  
- **Risk:** Medium.  
- **Reviewers:** @nlp-team.  
- **Milestone/Labels:** `Feature`.

### PR-CORE-020: Research Spike – 3D/NeRF

**Motivation:** Investigate using SV4D or NeRFs for true 3D consistency (future development).

**Implementation Plan:**  
- **Files to Create:** *Spike only* – add experimental scripts under `src/research/`. Possibly wrap [SV4D GitHub code](https://github.com/stabilityai/stable-video-diffusion-img2vid-xt) or [NeRF libraries].  
- **Tests:** None (research).  
- **Effort:** **L**.  
- **Risk:** High.  
- **Reviewers:** @research-team.  
- **Milestone/Labels:** `Spike`, `Research`.

## PR Mapping Table

| PR            | Feature/Fix                     | Repo Evidence                                             |
|---------------|----------------------------------|-----------------------------------------------------------|
| PR-CORE-001   | Native SVD Tab                  | Specified in docs【148†L79-L88】 and missing in code       |
| PR-CORE-002   | Character Embedding Pipeline    | No such pipeline exists; tutorial approach outlined【134†L282-L289】 |
| PR-CORE-003   | Scene/Shot Planner              | Story plan models present, not used (backlog)【109†L63-L65】|
| PR-CORE-004   | Prompt Templates                | PromptPack exists, no template data                       |
| PR-CORE-005   | Camera Control (ControlNet)     | No control input code in `src/video`                      |
| PR-CORE-006   | Frame Interpolation             | `interpolation_contracts.py` present, no impl             |
| PR-CORE-007   | Video Stitching                 | Only `video_export.py` stub; stitching not implemented    |
| PR-CORE-008   | Style LoRA                      | LoRA support exists (via WebUI) but not in pipeline       |
| PR-CORE-009   | Scheduler UI                   | No UI hooks for scheduler (tests mention schedulers)      |
| PR-CORE-010   | Perf/Memory Opt                | XFormers diffusers requirement, not enabled in code        |
| PR-CORE-011   | End-to-End Tests                | No integration tests (units only)                         |
| PR-CORE-012   | Logging & Metrics              | Logging setup exists【117†L49-L58】, no metrics collection |
| PR-CORE-013   | Config Unification & CLI       | Settings in `ConfigManager` (test saves)【136†L78-L86】; no CLI |
| PR-CORE-014   | Multi-Character Support        | Not implemented (story plan not character-aware)          |
| PR-CORE-015   | Output Metadata               | History saved【109†L49-L53】, but no prompt metadata       |
| PR-CORE-016   | GUI V2 Enhancements            | Panels and features pending (backlog PRs exist)【146†L23-L26】 |
| PR-CORE-017   | ControlNet/Depth Support       | Absent in code                                             |
| PR-CORE-018   | Documentation & Example        | Only design docs present, no end-user tutorial            |
| PR-CORE-019   | Book Ingestion Tool            | Not present                                                |
| PR-CORE-020   | 3D/NeRF Research              | Out of current scope, no code                              |

## Workflow Dependencies

```mermaid
graph LR
    PR1[PR-CORE-001 (SVD Tab)]
    PR2[PR-CORE-002 (Char Embedding)]
    PR3[PR-CORE-003 (Scene Planner)]
    PR4[PR-CORE-004 (Templates)]
    PR5[PR-CORE-005 (ControlNet)]
    PR6[PR-CORE-006 (Interpolation)]
    PR7[PR-CORE-007 (Stitching)]
    PR8[PR-CORE-008 (Style LoRA)]
    PR9[PR-CORE-009 (Scheduler)]
    PR10[PR-CORE-010 (Performance)]
    PR11[PR-CORE-011 (E2E Tests)]
    PR12[PR-CORE-012 (Logging)]
    PR13[PR-CORE-013 (Config/CLI)]
    PR14[PR-CORE-014 (Multi-Char)]
    PR15[PR-CORE-015 (Metadata)]
    PR16[PR-CORE-016 (GUI Enhancements)]
    PR17[PR-CORE-017 (Depth/ControlNet)]
    PR18[PR-CORE-018 (Documentation)]
    PR19[PR-CORE-019 (Book Parser)]
    PR20[PR-CORE-020 (3D Research)]

    PR3-->PR11
    PR1-->PR6
    PR1-->PR7
    PR2-->PR14
    PR3-->PR4
    PR5-->PR17
    PR16-->PR11
    PR13-->PR18
    PR19-->PR3
```

This graph shows logical orderings: e.g., PR-001 (SVD) precedes video-stitching PR-007, PR-003 (scene planner) feeds PR-011 (tests), etc.

Each PR above should be created using the StableNew PR template, referencing the specified files and goals, and incorporating the stub evidence cited.