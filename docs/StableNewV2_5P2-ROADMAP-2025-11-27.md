StableNewV2P2-ROADMAP-2025-11-27.md

StableNew V2 · Part 2 Roadmap
Focus: 1) Real pipeline runs, 2) full V2 transition & cleanup, 3) learning, 4) randomization & advanced prompts, 5) video, 6) cluster/controller.

Objective 1 – Reliable V2 pipeline image generation (correct models/configs)

Goal: From a fresh launch of StableNew V2, you can select a model / VAE / sampler / scheduler in the GUI and successfully run txt2img → img2img → upscale with correct payloads to WebUI.

PR-1A · WebUI resource discovery + last-run load (Backend only – mostly done)

Purpose: Ensure the backend has a single, reliable source for available models/VAEs/etc. and last-run config.

Finalize src/api/webui_resources.py (filesystem + API discovery).

Finalize src/api/last_run_store_v2_5.py (or equivalent) for read/write of last-run config.

Make AppController the single consumer:

list_models() / list_vaes() / list_upscalers() / list_embeddings() / list_hypernetworks()

get_last_run_config() / save_last_run_config(...).

Ensure tests for resource service + last-run store are green (fix filesystem fallback test).

V2 files brought in: webui_resources.py, last_run_store_v2_5.py as final, canonical services.

PR-1B · Pipeline dropdown wiring (models, VAEs, samplers, schedulers)

Purpose: GUI dropdowns show real WebUI resources and flow into pipeline configs.

In AppController:

Ensure _resource_service and _last_run_store are initialized in __init__.

Provide controller methods for GUI:

get_available_models(), get_available_vaes(), get_available_samplers(), get_available_schedulers(), get_available_upscalers(), etc.

In AdvancedTxt2ImgStageCardV2 and other stage cards:

Populate dropdowns from controller methods.

On selection changes, write into the appropriate config dict for the stage (e.g., config["model"], config["vae"], config["sampler_name"], config["scheduler"], config["upscaler"]).

Ensure executor.py reads those config keys and sends them verbatim into:

/sdapi/v1/options (for model/vae/upscale settings).

/sdapi/v1/txt2img, /sdapi/v1/img2img, /sdapi/v1/extra-batch (for sampler, scheduler, etc.).

V2 files brought in:

advanced_txt2img_stage_card_v2.py, advanced_img2img_stage_card_v2.py, advanced_upscale_stage_card_v2.py (where present).

Align with V2-only patterns; do not resurrect old V1 stage card code.

PR-1C · Last-run prefill into V2 GUI

Purpose: On launch, StableNew V2 looks “warm”: last run’s key settings are pre-populated.

On app startup (in AppController and/or the pipeline panel):

If get_last_run_config() returns a value:

Preselect model/vae/sampler/scheduler/upscaler dropdowns.

Pre-set steps, CFG scale, resolution, seed, clip skip, etc.

After a successful txt2img (and possibly a full pipeline run), call save_last_run_config(...) with:

The effective per-stage config (including user selections).

Ensure this only uses V2 config structures (no AppState V1 reintroduction).

V2 files brought in:

pipeline_panel_v2.py (ensure it knows how to apply last-run config to sub-cards).

app_state_v2.py only if needed for V2-only persistence; avoid re-adding old AppState.

PR-1D · V2-only GUI stability fixes (zones, status panel, wiring)

Purpose: Make MainWindowV2 + AppController robust enough that python -m src.main always launches cleanly.

Finish AppController → MainWindowV2 wiring:

Use deferred wiring pattern for header_zone, left_zone, bottom_zone.

Make _update_status and _attach_to_gui fully safe if zones are delayed.

Ensure api_status_panel and status bar correctly track WebUI connection state (DISCONNECTED → READY).

Don’t reintroduce legacy main window; use MainWindowV2 as single entrypoint.

V2 files brought in:

main_window_v2.py, api_status_panel.py, status_bar_v2.py as the canonical V2 GUI scaffold.

Objective 2 – Full V2 transition & legacy cleanup

Goal: The repo uses only V2 app paths; all V1 GUI + controller files are archived and no longer imported.

PR-2A · V2 entrypoint and factory consolidation

Ensure src/main.py only builds the V2 app (via build_v2_app).

Confirm tests like test_entrypoint_uses_v2_gui.py pass:

Entrypoint returns/uses StableNewGUIV2 (or MainWindowV2 equivalent) as expected.

Mark any remaining V1 entrypoints (main_window.py, main_v1.py, etc.) as legacy:

Add (OLD) suffix to filename and move into archive/ folder.

PR-2B · Controller & state consolidation

Remove any duplicate / half-migrated controller logic:

Single AppController class in src/controller/app_controller.py, V2-only.

Remove or archive:

app_controller_v1.py (if present).

AppState V1 definitions if they conflict with AppStateV2.

Update imports so:

All GUI V2 code uses AppController + AppStateV2.

No references remain to V1 controller/state.

PR-2C · Archive legacy GUI & theme

Identify V1 GUI components:

Legacy main_window/main_window_v1, old pipeline_panel, old stage cards, legacy theme.py pieces, etc.

For each:

Suffix filename with (OLD) and move under archive/gui_v1/.

Keep them import-free (no longer referenced by runtime code).

Make theme_v2.py + theme.py delegator the only styling pathway used by tests and V2 GUI.

Objective 3 – Learning features wired into pipeline

Goal: Each pipeline run optionally writes a “learning record” that can support rating, analysis, and future auto-tuning.

PR-3A · Learning record writer V2 integration (backend)

Finalize LearningRecordWriterV2 (or learning_record_writer_v2.py equivalent):

Append JSONL records per stage or per pipeline:

Inputs (prompt, negative, model/vae/sampler/scheduler, seed, config).

Outputs (paths to saved images, any WebUI metadata).

Run metadata (duration, NSFW filters applied, etc.).

Plug into executor.py:

After each successful stage (txt2img, img2img, upscale) write a record.

Include global pipeline ID / run ID so later multi-stage analysis is possible.

V2 files brought in:

learn/learning_record_writer_v2.py or similar; if present but unused, this PR makes it canonical.

PR-3B · Rating hooks (UI + controller)

Purpose: Let the user rate outputs in the GUI and write that into the learning records.

In the gallery/result panel (V2):

Add rating controls (simple 1–5 or thumbs up/down).

Wire rating actions to AppController.rate_image(image_id, rating).

In AppController:

Implement rate_image to:

Update the appropriate learning record (by manifest or image ID).

Optionally write a separate “ratings” JSONL.

No heavy dashboards yet—just consistent, structured data.

V2 files brought in:

results_panel_v2.py, image_gallery_v2.py (if present) for rating UI.

PR-3C · Learning-aware suggestions (optional, later in Objective 3)

Simple MVP:

On prompt config load, compute “favorite” models/samplers from last N runs (e.g., by rating or frequency).

Highlight those in dropdowns (e.g., top of list or “⭐ Favorites” section).

No complex ML yet; just basic heuristics to leverage the learning data.

Objective 4 – Randomization & advanced prompt editing

Goal: Restore the powerful “randomization” and “advanced prompt editor” behavior in a clean V2 way.

PR-4A · Prompt pack + advanced editor V2 wiring

Identify V2 prompt editor modules:

advanced_prompt_editor_v2.py, prompt_pack_panel_v2.py, etc. (whatever you have in V2 namespace).

Ensure:

Prompt pack list comes from the same file_io / packs loader used at startup.

The advanced editor:

Can view/edit the current prompt.

Can push edited prompt back into PipelinePanelV2 / AdvancedTxt2ImgStageCardV2.

PR-4B · Randomization engine V2

Identify the randomization V2 modules (e.g., prompt_randomizer_v2.py, randomization_matrix_v2.py).

Implement:

A well-defined config for randomization (per tag, weight, probability, etc.).

Buttons in the prompt editor or stage card:

“Randomize prompt”

“Lock/unlock” segments.

Ensure:

Randomized prompts still pass through the same learning + last-run pipeline.

The generated prompt is visible and editable before running.

PR-4C · Randomization + learning bridge

On each run:

If randomization is used, record the randomization config in learning records.

Later we can:

Analyze which randomization settings yield higher-rated images.

Feed that back into default randomization settings (in a future “Objective 3+4 fusion” PR).

Objective 5 – Video clip generation

Goal: Generate short video clips from sequences of frames (or WebUI’s video options) as an optional pipeline tail.

PR-5A · Video stage config + executor scaffold

Introduce a V2 pipeline stage type: video:

Config includes:

Source folder or list of frame paths.

FPS, resolution, codec/container.

Might use external tools:

ffmpeg via a small helper in src/utils/video.py.

Extend executor.py:

Handle a video stage by:

Locating the frame images from prior stages.

Invoking ffmpeg to render MP4/WEBM output.

Persist video path in manifest.

PR-5B · Video stage UI (pipeline panel V2)

In pipeline_panel_v2.py:

Add a “Video” stage card (V2 style) that:

Lets user enable/disable video stage.

Set FPS, length/trim (if needed), basic options.

Basic MVP: “join all frames from this run into a video at X fps.”

Objective 6 – Cluster/controller for large batches

Goal: Offload big batches across multiple nodes (LAN cluster) via a controller that farm jobs to workers.

PR-6A · Job model + controller abstraction

Define a Job / Task abstraction (V2-only) in src/pipeline/job_model_v2.py (or similar):

Contains:

Pipeline config.

Work type (txt2img/img2img/upscale/video).

Priority, status, node assignment.

Create a ClusterController interface:

Local implementation: executes jobs on the current WebUI instance (baseline).

Future remote implementation: dispatches jobs via HTTP/queue to other nodes.

PR-6B · Local “single-node cluster” integration

Wire the existing PipelineRunner/executor to:

Use the ClusterController even on a single machine.

This gives you:

A clean place to plug in a multi-node implementation later, without rewriting GUI/pipeline logic.

PR-6C · Multi-node batch dispatch (later)

Implement a simple worker protocol:

Workers listen on LAN (or via Tailscale) with a simple HTTP/REST or message queue.

Controller assigns jobs and polls status.

This is a larger effort; keep it as a later-phase PR series (6C-1, 6C-2, etc.).

Incorporating “orphaned” V2 files back into the fold

Across the roadmap, here’s where the previously underused V2 files come in:

Core V2 GUI scaffolding (Objective 1 & 2):

main_window_v2.py → single main window implementation.

app_state_v2.py → V2 state container (if needed for layout + preferences).

pipeline_panel_v2.py → canonical pipeline view.

api_status_panel.py, status_bar_v2.py → status and connectivity UI.

Stage cards (Objective 1, 4, 5):

advanced_txt2img_stage_card_v2.py, advanced_img2img_stage_card_v2.py, advanced_upscale_stage_card_v2.py → used for dropdowns and advanced core config.

Future video_stage_card_v2.py → added during Objective 5.

Learning & randomization (Objective 3 & 4):

learning_record_writer_v2.py + any learn_* helpers → integrated in executor and AppController.

advanced_prompt_editor_v2.py, prompt_pack_panel_v2.py, randomization_*_v2.py → restored as the official V2 prompt/edit/randomization system.

Cluster + jobs (Objective 6):

Any early V2 experiments (e.g., pipeline_runner_v2.py, job_queue_v2.py) can be either:

Adopted and cleaned up as canonical implementations.

Or archived if they conflict with the new ClusterController abstraction.