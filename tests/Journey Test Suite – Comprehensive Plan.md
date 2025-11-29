2. Journey Test Suite – Comprehensive Plan

Below is the high-level Journey Test inventory, then I’ll walk through each journey with what exists, what’s missing, and what should be revised.

2.1 Journey Test Inventory (Short List)

Prompt & Authoring

JT-01 – Prompt Pack Authoring & Randomization

JT-02 – LoRA / Embedding Prompt Integration

Core Pipeline Execution

JT-03 – txt2img Pipeline Run (Single Stage)

JT-04 – img2img / ADetailer Run

JT-05 – Upscale Stage Run

JT-06 – Video Pipeline Run (Future)

App Startup & WebUI Integration

JT-07 – StableNew Startup + Async WebUI Bootstrap

Learning System

JT-08 – Single-Variable Learning Plan (Baseline v1)

JT-09 – X/Y (Two-Variable) Learning Experiment (Future, depends on PR-3S)

JT-10 – Ratings, Learning Records & Experiment Review

Presets, Styles, and Reuse

JT-11 – Creating and Using Styles/Presets Across Tabs

Diagnostics and Stability

JT-12 – Run / Stop / Run Again Lifecycle

JT-13 – Logging, Error Surfacing, and Log Retrieval

2.2 What We Already Have (Partial Coverage)

From the Pipeline Tab PR we already have a set of manual testing bullets around stages, randomizer behavior, LoRA runtime controls, and preview updates. These are essentially proto-journey tests focused on the Pipeline workspace:

Stage toggles expand/collapse cards and affect execution.

Randomizer behavior drives job counts.

LoRA strength sliders change behavior at runtime.

Queue vs direct mode.

Preview updated on completion.

From the Learning Tab PR, we likewise have manual testing bullets for experiment design, plan execution, rating, and img2img/upscale learning:

Design a CFG sweep and confirm plan table correctness.

Execute plan and see statuses and images flow.

Rate images and confirm records persisted.

Confirm img2img/upscale learning keeps the same base image while varying only the selected parameter.

From the controller lifecycle example PR we have a very clear Run / Stop / Run again behavioral focus, with tests around controller states (IDLE, RUNNING, STOPPING, ERROR) and UI control states. That’s essentially a basis for JT-12:

What’s missing is:

A named, documented Journey Test suite tying all these flows together.

Explicit preconditions, steps, and artifacts for prompt authoring, LoRA/embedding authoring, presets/styles, and logging flows.

A test mapping that says, “This journey test is covered by these manual checks + these pytest files.”

So the plan below is about formalizing and filling those gaps.

3. Journey Tests – Detailed Plan

For each journey:

Goal – what the user is trying to accomplish.

Preconditions – what needs to exist.

Scenario & Steps – the rough flow.

Expected Artifacts – what you should see / what files or records should exist.

Status – Existing / Partial / New and what needs revision.

JT-01 – Prompt Pack Authoring & Randomization

Goal
Author a prompt pack (10 prompts × 5 lines style), attach global negative, add randomization tokens, and end with a “ready to run” prompt pack that displays correctly in the Prompt tab and drives the pipeline randomizer.

Preconditions

Prompt tab exists (PR-001 baseline).

PromptWorkspaceState and metadata (matrix tags, LoRA references) wired up.

Scenario (High-Level)

Start StableNew, open Prompt tab.

Create a new prompt pack; populate 10 prompts with 5-line structure.

Add:

Global negative prompt.

At least one randomized token column (e.g., {day|night|sunset}).

Add LoRA references inline in prompt text as per your conventions.

Save prompt pack.

Switch to Pipeline tab and confirm the same pack is selectable and matrix metadata is visible.

Expected Artifacts

Saved prompt pack file on disk.

PromptWorkspaceState reflects:

Prompt text.

Matrix metadata.

LoRA/embedding references.

Status

New journey.

Prompt / metadata pieces are defined conceptually in the Prompt PR, but we don’t yet have a formal, named JT-01 spec or tests derived from it.

JT-02 – LoRA / Embedding Prompt Integration

Goal
Verify that LoRAs/embeddings configured in prompts are:

Correctly parsed into metadata (Prompt tab).

Exposed as runtime controls (sliders/toggles) in Pipeline tab.

Actually affect runs.

Scenario

Open a prompt pack with LoRA markers and embeddings.

In Prompt tab, confirm metadata detection (LoRA names visible in some sidebar/metadata area).

Switch to Pipeline tab and see LoRA/embeddings listed with sliders/toggles in the left panel.

Run a small txt2img job with LoRA strength low vs high and visually confirm that images differ in the expected direction.

Expected Artifacts

LoRA metadata structure populated in PipelineState.

LoRA strength / enabled flags persisted for run config.

Status

Partial via Pipeline PR manual tests (LoRA runtime behavior), but not explicitly framed as a journey from Prompt → Pipeline. Needs a combined, documented JT-02.

JT-03 – txt2img Pipeline Run (Single Stage)

Goal
“Standard” first-use journey: user selects a prompt, configures txt2img, and successfully generates images that match expectations.

Scenario

Start StableNew; ensure WebUI status is “Ready”.

Open Pipeline tab:

Enable txt2img card only.

Configure sampler, scheduler, steps, CFG, batch size.

Select prompt from Prompt tab via shared state (or via Pipeline’s prompt selector referencing PromptWorkspaceState).

Run:

“Run Now” with direct mode.

Confirm:

Stage card indicates running → complete.

Preview shows generated images with metadata.

Expected Artifacts

Job run record (whatever logging structure you currently have).

Images in the expected output location.

Status

Partial via Pipeline manual tests (stage toggles, preview behavior), but JT-03 should unify that into a single scenario.

JT-04 – img2img / ADetailer Run

Goal
Take an existing image, run img2img with ADetailer or equivalent, ensure the same asset flows through.

Scenario

Produce or load a base image (from JT-03 or a test fixture).

Enable img2img / adetailer stage in the Pipeline tab; ensure txt2img feeding it is configured properly or that a source image is selected.

Configure denoise, inpainting mask (if applicable), and ADetailer settings.

Run “Run current stage only” or “Run from selected stage”.

Confirm:

The base image is used.

Only the selected stage transforms it.

Preview shows the transformed image and correct stage.

Expected Artifacts

Logs showing original image path + derived image path.

Any stage-specific metadata captured.

Status

New as a named journey. PR docs reference multi-stage pipeline behavior but don’t define an img2img-specific journey explicitly.

JT-05 – Upscale Stage Run

Goal
Take an image and run it through the upscale stage in isolation and as the last stage of a pipeline.

Scenario

Choose an existing image (either from disk or from a previous stage).

Pipeline tab: enable only Upscale stage; configure factor, model, tile size.

Run just Upscale; confirm output resolution and naming.

Then configure a multi-stage pipeline (txt2img → upscale) and confirm:

The same intermediate image is fed into the upscale stage.

Final output is as expected.

Expected Artifacts

Upscaled image with correct resolution.

Stage metadata confirming upscale parameters.

Status

New as a full journey; current docs only broadly mention stages, not a structured upscale test.

JT-06 – Video Pipeline Run (Future)

Goal
Once video features exist, verify a simple txt2img → frames → video pipeline.

Status

Future; tie this to future Video PRs and defer for now.

JT-07 – StableNew Startup + Async WebUI Bootstrap

Goal
Ensure the user experience from “double-click StableNew” to “ready to run a pipeline”, with async WebUI detection/bootstrap and status monitoring, works cleanly in both paths:

WebUI not running yet.

WebUI already running.

Scenario

Case A – WebUI not running:

Start StableNew.

Confirm GUI appears quickly (no 30s block).

Watch the WebUI status panel move from “Connecting” → “Ready”.

Confirm WebUI cache file created/updated (workdir/command).

Case B – WebUI already running:

Start StableNew; confirm it quickly shows “Ready” without repeated detection.

In both cases, run a simple JT-03 txt2img job to prove everything is wired correctly.

Expected Artifacts

webui_cache.json present and valid.

Status bar reflecting correct status transitions.

Status

New as a named journey, but implementation is already done (per Codex summary you pasted). This test just needs to be codified.

JT-08 – Single-Variable Learning Plan (Baseline)

Goal
Validate the core Learning flow: pick a baseline config, define a variable under test, build a plan, run it, and rate results. This is essentially the “happy path” described in PR-GUI-V2-LEARNING-TAB-003.

Scenario

Configure a baseline pipeline in the Pipeline tab (e.g., txt2img with a specific model/prompt).

Open Learning tab:

Use “Use current Pipeline config as baseline”.

Choose a prompt from PromptWorkspaceState.

Select stage = txt2img.

Variable under test = CFG.

Values = 3, 7, 11, 15; images per value = 2.

Click “Build Plan”; confirm the plan table shows 4 variants × 2 images.

Click “Run Plan”; pipeline jobs are submitted with learning context.

As images complete, verify:

Plan table status and counts update.

Rating panel receives images.

Rate all images (e.g., 1–5 stars) and add a note to at least one.

Expected Artifacts

LearningState populated with experiment, variants, and image refs.

LearningRecordWriter JSONL entries containing:

Experiment ID.

Variant value (CFG).

Config snapshot.

Rating & note.

Status

Partial – the PR defines this flow and its manual tests in prose, but we need to formalize this as JT-08 and potentially add automated tests for plan building and record writing.

JT-09 – X/Y (Two-Variable) Learning Experiment (Future)

Goal
Once PR-3S is implemented, validate a two-variable sweep (e.g., CFG × steps) with table or grid view and rating.

Status

Future – depends on PR-3S; this sits in the Future Roadmap section.

JT-10 – Ratings, Learning Records & Experiment Review

Goal
Focus specifically on the rating and review experience: navigation between variants/images, updating ratings, and ensuring the history is coherent.

Scenario

Using results from JT-08, open Learning tab and select a completed experiment.

Navigate:

Variant by variant.

Image by image inside a variant.

Change ratings for some images, mark a “best in group” if supported.

Re-open the same experiment (or reload app, if supported) and confirm ratings persist.

Expected Artifacts

Updated LearningRecord entries for changed ratings (not duplicated incorrectly).

Status

Partial – the PR defines persistence behavior; we need explicit JT-10 to test mutations over time (not just initial writes).

JT-11 – Creating and Using Styles/Presets Across Tabs

Goal
Allow users to create a persistent “style” (preset) that encapsulates prompt + model config + LoRAs, then reuse it later.

Scenario

Configure a prompt + pipeline config that you like.

Save it as a “Style” or “Preset” (once that feature is implemented).

Restart the app (or at least clear the current view), then:

Load the style.

Confirm Prompt, Pipeline, and LoRA settings all repopulate.

Run a pipeline and confirm results match expectations.

Status

Future/new – depends on a Styles/Presets feature; this one should be tied to the future PR(s) for presets.

JT-12 – Run / Stop / Run Again Lifecycle

Goal
Prove that the controller lifecycle and GUI controls behave as expected through multiple runs and cancellations.

Scenario

From IDLE, start a pipeline run (txt2img).

While running, click Stop/Cancel:

Confirm state transitions (RUNNING → STOPPING → IDLE/ERROR).

Confirm buttons and menus reflect the state.

Start another run and ensure it launches cleanly.

Simulate a failure (e.g., bad config) and ensure:

Error surfaces to the user.

App returns to a stable state where new runs can be started.

Expected Artifacts

Controller logs showing clean state transitions.

No fatal exceptions or stuck “RUNNING” flags.

Status

Partial – Example lifecycle PR already defines goals and tests for these transitions; JT-12 should align with that as the high-level behavior spec.

JT-13 – Logging, Error Surfacing, and Log Retrieval

Goal
Validate that when a user notices a problem, they can find and export meaningful logs without needing to know internals.

Scenario

Trigger a controlled error (e.g., deliberately misconfigure WebUI path or sampler).

Observe:

Status bar message.

Any dialogs or inline error messages.

Open the logging view or log file location via the GUI (if present):

Ensure logs are readable and timestamped.

Export or copy logs to a file intended for troubleshooting.

Expected Artifacts

Clear, user-visible error indication.

Log file with sufficient context (time, stage, error stack/message).

Status

New – logging is mentioned in multiple docs, but we don’t yet have a Journey framed around “user notices a problem and pulls logs.”