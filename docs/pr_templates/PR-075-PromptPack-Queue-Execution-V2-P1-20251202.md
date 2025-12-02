PR-075-PromptPack-Queue-Execution-V2-P1-20251202.md

Title: JobService _execute_job() uses upscale-aware run_pipeline() for queued prompt-pack jobs
Snapshot: StableNew-snapshot-20251201-230021.zip (authoritative baseline)

0. Intent

Now that:

AppController.run_pipeline() exists and understands:

standalone upscale,

txt2img→upscale (PR-074), and

PipelineTabFrameV2 exposes JT05 attributes (PR-073), and

the “Run” button path calls run_pipeline() (PR-072),

this PR makes the queue path do the same thing:

When the user builds a job from prompt packs and hits “Run Now”, JobService / _execute_job() should iterate through the pack entries and actually run a pipeline per entry using the same controller-level logic, not just stub out a fake result.

This is the bridge from “prompt packs visible in Preview & queue” → “real batches of images on disk, with history entries.”

1. Scope
1.1 Files Allowed to Change

Only these:

src/controller/app_controller.py
src/controller/job_service.py        # or equivalent job service/controller file
src/queue/job_model.py               # only if needed to store richer results
src/queue/jsonl_job_history_store.py # only if needed to persist per-entry results


If your actual filenames differ slightly (e.g. job_service_v2.py, job_history_store.py), adapt paths accordingly — but keep the scope identical: controller AppController, job service, and (optionally) history model.

1.2 Forbidden Files (do NOT modify)
src/gui/*
src/api/*
src/pipeline/*
src/webui/*
src/main.py
tests/*
src/queue/single_node_runner.py      # or equivalent runner engine


This PR is queue → controller integration only. No runner engine, GUI, WebUI API, or test file edits here.

2. Done Criteria

PR-075 is complete when:

JobService (or the equivalent class) calls controller-level execution from _execute_job(self, job):

For each prompt-pack entry in job.payload["packs"], it:

Configures the pipeline tab / app state for that entry,

Calls app_controller.run_pipeline(),

Collects the result into a structured per-entry record.

Jobs created from prompt packs via the existing “Add to Queue” flow:

When the user clicks Run Now:

Queue transitions to RUNNING, then back to IDLE/COMPLETED.

A pipeline is actually run per selected pack entry.

Failures are captured per entry and surfaced in job status.

Job history (JSONL) entries are enriched:

Each job completion record contains a results list with per-pack details:

pack_id / pack_name (if available from the snapshot),

prompt text,

pipeline mode used (upscale_only, txt2img_then_upscale, etc.),

basic runtime summary (image count, success/failure).

Existing non-prompt-pack jobs still execute via the prior codepath (no regression).

No new thread spawning or concurrency behavior is introduced in this PR.

3. Functional Design
3.1 Job Payload Structure

From earlier work (and the Preview/queue flow), Job.payload should look roughly like:

{
    "packs": [  # list of prompt pack snapshots or entries
        {
            "pack_id": "...",
            "name": "...",
            "entry": {
                # prompt, negative prompt, cfg, steps, etc.
            },
            "config_snapshot": {
                # optional per-entry config overrides
            },
        },
        # ...
    ],
    "run_config": {   # global run config (resolution, batch size, etc.)
        # ...
    },
}


This PR assumes:

job.payload is a dict,

payload["packs"] is a list of entries,

payload["run_config"] is a dict produced by _run_config_with_lora() or similar.

If the actual shape differs slightly in the snapshot, adapt the field names but keep the concept: list of pack entries + global run_config.

3.2 _execute_job Overview

Location: src/controller/app_controller.py OR src/controller/job_service.py
(whichever currently owns _execute_job that the runner calls).

Target shape:

def _execute_job(self, job: Job) -> dict:
    """
    Execute a queued job built from prompt packs.

    For each pack entry:
    - configure the pipeline state
    - call controller.run_pipeline()
    - collect and return per-entry results
    """


Key behaviors:

Accept a Job instance whose payload was constructed from prompt packs.

For each pack in payload["packs"]:

Restore / apply that pack’s configuration to app state / pipeline tab.

Call self.app_controller.run_pipeline() once per entry.

Aggregate results like:

{
    "job_id": job.job_id,
    "mode": "prompt_pack_batch",
    "total_entries": len(packs),
    "results": [
        {
            "pack_id": "...",
            "pack_name": "...",
            "status": "ok" | "error",
            "error": None | "string message",
            "result": <run_pipeline return value or subset>,
        },
        ...
    ],
}


This returned dict is what the runner will attach to the Job completion record and pass into the JSONL history store.

3.3 Per-Entry Execution Flow

Inside _execute_job:

Basic validation:

payload = job.payload or {}
packs = payload.get("packs") or []
run_config = payload.get("run_config") or {}

if not packs:
    # Nothing to do — treat as no-op job.
    return {
        "job_id": job.job_id,
        "mode": "prompt_pack_batch",
        "total_entries": 0,
        "results": [],
    }


Create a results = [] list.

For each pack in packs:

for pack in packs:
    pack_id = pack.get("pack_id") or pack.get("id") or ""
    pack_name = pack.get("name") or ""
    entry = pack.get("entry") or {}
    cfg_snapshot = pack.get("config_snapshot") or {}


For each entry, call a helper to:

Apply config to widgets/state,

Call run_pipeline(),

Wrap the outcome.

Example:

result = self._execute_pack_entry(
    pack_id=pack_id,
    pack_name=pack_name,
    entry=entry,
    cfg_snapshot=cfg_snapshot,
    run_config=run_config,
)
results.append(result)


Return the aggregated structure as shown in 3.2.

3.4 _execute_pack_entry Helper

Add a private helper method on the same class:

def _execute_pack_entry(
    self,
    pack_id: str,
    pack_name: str,
    entry: dict,
    cfg_snapshot: dict,
    run_config: dict,
) -> dict:
    """
    Configure the app/pipeline for a single pack entry and invoke run_pipeline().
    """


Responsibilities:

Apply prompt and config:

Set the main prompt:

prompt = entry.get("prompt") or cfg_snapshot.get("prompt") or ""
try:
    pipeline_tab = getattr(self, "pipeline_tab", None)
    if pipeline_tab and hasattr(pipeline_tab, "prompt_text"):
        pipeline_tab.prompt_text.delete(0, "end")
        if prompt:
            pipeline_tab.prompt_text.insert(0, prompt)
except Exception:
    pass


Apply upscale-related fields from run_config or cfg_snapshot to:

if pipeline_tab:
    if "upscale_factor" in run_config and hasattr(pipeline_tab, "upscale_factor"):
        pipeline_tab.upscale_factor.set(run_config["upscale_factor"])
    if "upscale_model" in run_config and hasattr(pipeline_tab, "upscale_model"):
        pipeline_tab.upscale_model.set(run_config["upscale_model"])
    if "upscale_tile_size" in run_config and hasattr(pipeline_tab, "upscale_tile_size"):
        pipeline_tab.upscale_tile_size.set(run_config["upscale_tile_size"])


Apply stage toggles from run_config (if present) — e.g.:

if "upscale_enabled" in run_config and hasattr(pipeline_tab, "upscale_enabled"):
    pipeline_tab.upscale_enabled.set(bool(run_config["upscale_enabled"]))
if "txt2img_enabled" in run_config and hasattr(pipeline_tab, "txt2img_enabled"):
    pipeline_tab.txt2img_enabled.set(bool(run_config["txt2img_enabled"]))
# etc.


For txt2img-only vs txt2img→upscale vs upscale-only, we rely on the combination of booleans plus what PR-074 does.

Call run_pipeline() and handle errors:

try:
    run_result = self.app_controller.run_pipeline()
    status = "ok"
    error = None
except Exception as exc:
    self._append_log(f"[queue] Pack {pack_id or pack_name} failed: {exc!r}")
    run_result = None
    status = "error"
    error = str(exc)


Return per-entry summary:

return {
    "pack_id": pack_id,
    "pack_name": pack_name,
    "status": status,
    "error": error,
    "prompt": prompt,
    "run_config": run_config,
    "result": run_result,
}


Note: run_result is whatever run_pipeline() returns per PR-074 (mode, factor, model, tile_size, raw API response, etc.). We don’t need to interpret it further here.

3.5 History Store Integration (Optional but Recommended)

If the JSONL history store currently only receives a flat job.result object, we can optionally enrich it by adding the new results list and some top-level metadata.

File: src/queue/jsonl_job_history_store.py (or equivalent)

On job completion, when writing the history entry, ensure the result property includes your aggregated object (with results list).

Keep all existing fields (job id, timestamps, etc.) intact.

Example entry structure (conceptual):

{
  "job_id": "JOB-123",
  "timestamp": "2025-12-02T23:59:00Z",
  "status": "COMPLETED",
  "result": {
    "mode": "prompt_pack_batch",
    "total_entries": 3,
    "results": [
      {
        "pack_id": "PACK-001",
        "pack_name": "Landscapes",
        "status": "ok",
        "prompt": "a mountain valley at sunrise",
        ...
      }
    ]
  }
}


No new fields are required in Job itself — we can keep this all under result.

4. Test Plan

This PR doesn’t change test files, but you can validate behavior via:

Existing queue/unit tests (should stay green):

pytest tests/queue/test_single_node_runner_loopback.py -q
pytest tests/controller/test_job_service_unit.py -q


Manual queue run (ideal once everything wired):

In the GUI:

Load a prompt pack.

Add 2–3 entries to the job draft.

Add job draft to queue.

Click Run Now.

Confirm:

Queue transitions RUNNING → IDLE.

Images appear in the output directory.

A JSONL history entry is written with mode: "prompt_pack_batch" and results length equal to the number of entries.

Future: dedicated journey test

Later, we can add a Journey test like test_jt06_prompt_pack_queue_batch_run that:

Builds a job with N packs.

Patches run_pipeline() and asserts it’s called N times from _execute_job.

For now, PR-075 focuses on live behavior and reusing the controller logic introduced in PR-074.