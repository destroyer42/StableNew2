#CANONICAL
# Unified Debug Hub (V2.5)

The Unified Debug Hub (`DebugHubPanelV2`) collocates:

- **Pipeline tab** (diagnostics snapshot, queue/jobs flow, Explain This Job).
- **Prompts tab** (show normalized job prompts and pack usage).
- **API tab** (`LogTracePanelV2` with structured filters + Crash Bundle button).
- **Processes tab** (StableNew-like processes via `process_inspector_v2`).
- **Crash tab** (list of `reports/diagnostics/` bundles and open actions).
- **System tab** (system snapshot via `system_info_v2`).
- **API tab** also now includes the API Failure Visualizer, which lists recent WebUI failures and shows structured details (endpoint, stage, status, response preview, and any decoded image payload) so operators can quickly diagnose invalid encoded image/validation errors without manual base64 decoding.
- **Processes tab** embeds the background auto-scanner status and toggle so operators can see how often the system scans, how many python strays were killed, and how to disable or adjust the interval when needed.

Access the hub via the Debug button in `MainWindowV2` or through `AppController.open_debug_hub()`. When a job is selected (history list or combo), “Explain This Job” opens `JobExplanationPanelV2`, which reads the run metadata + stage manifests from `runs/<job_id>` to explain:

- Prompt pack, preset, or manual source.
- Final prompts/negatives per stage and which global-negative terms were applied.
- Stage flow (txt2img → img2img → upscale) and manifest availability.


### Job Lifecycle Console

The Pipeline tab includes `DebugLogPanelV2` below the preview and queue cards. This console displays `AppStateV2.log_events`, which are emitted by `JobLifecycleLogger` whenever the GUI adds a job to the draft, submits it to the queue, or JobService reports runner pickups/completions. Each line shows the source, event type, job ID (if any), and a concise message so operators can follow the job lifecycle without reading raw log files.

PR-CORE-C adds a `job_submitted` lifecycle entry emitted whenever JobService doors a normalized, PromptPack-backed job into the queue. These entries make it easy to see the SUBMITTED → QUEUED → RUNNING → COMPLETED/FAILED path alongside the existing `job_started` and `job_finished` events without hitting the runner logs directly.

Use the hub for faster diagnostics without touching the pipeline runner or queue internals.
