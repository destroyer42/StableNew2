PR-074-Upscale-Pipeline-Logic-V2-P1-20251202.md

Title: Controller Upscale Pipeline Logic (run_pipeline() uses pipeline-tab state + WebUI API)
Snapshot: StableNew-snapshot-20251201-230021.zip (authoritative baseline)

0. Purpose & Context

We now have:

PR-071: Journey infra fixed (Tk/TCL, ApiClient alias).

PR-072: AppController.run_pipeline() facade exists and the pipeline runner is invoked by on_run_clicked() in non-threaded mode.

PR-073: PipelineTabFrameV2 exposes JT05-compatible attributes:

txt2img_enabled, img2img_enabled, adetailer_enabled, upscale_enabled

upscale_factor, upscale_model, upscale_tile_size

prompt_text (Entry-like)

input_image_path (str)

This PR wires actual upscale pipeline behavior into run_pipeline() so that:

A standalone upscale run (upscale-only pipeline) calls the WebUI API upscale_image with the correct parameters.

A multi-stage txt2img → upscale run:

Generates a base image via txt2img, then

Upscales that image using upscale_image, preserving metadata.

JT05’s tests (test_jt05_upscale_stage_run.py) observe the expected WebUI API calls through their patches, and no longer fail for logic reasons.

1. Scope
1.1 Files Allowed to Change

Only these files may be modified in this PR:

src/controller/app_controller.py
src/api/webui_api.py


You may read other files (like src/api/client.py, src/pipeline/*, the JT05 test file) to understand existing interfaces, but do not change them in this PR.

1.2 Forbidden Files (do NOT modify)
src/gui/*
src/queue/*
src/main.py
tests/*
src/api/client.py
src/pipeline/*
src/webui/*


We want this PR to be purely about controller → WebUI API logic, not GUI layout, tests, or queue/executor behavior.

2. Done Criteria

This PR is complete when all of the following are true:

Standalone Upscale Path Works

When the pipeline tab is configured as:

app.pipeline_tab.upscale_enabled.set(True)
app.pipeline_tab.txt2img_enabled.set(False)
app.pipeline_tab.img2img_enabled.set(False)
app.pipeline_tab.adetailer_enabled.set(False)
app.pipeline_tab.input_image_path = "<valid image path>"
app.pipeline_tab.upscale_factor.set(2.0)
app.pipeline_tab.upscale_model.set("UltraSharp")
app.pipeline_tab.upscale_tile_size.set(512)


A call to:

result = app.controller.run_pipeline()


must produce exactly one WebUIAPI.upscale_image(...) call with:

The configured input image path

The configured scale/factor

The configured upscaler/model

The configured tile size (if supported by the API)

JT05’s “standalone upscale” test (in test_jt05_upscale_stage_run.py) passes.

Txt2img → Upscale Multi-Stage Path Works (Basic)

When the pipeline tab is configured with both:

app.pipeline_tab.txt2img_enabled.set(True)
app.pipeline_tab.upscale_enabled.set(True)
app.pipeline_tab.prompt_text.insert(0, "a beautiful landscape")
# model, sampler, etc. taken from existing app state / sidebar


A run_pipeline() call must:

Perform a txt2img generation via WebUI API (or via your existing pipeline_runner if that is already the abstraction).

Use the output image path(s) from txt2img as input(s) to upscale_image using the same upscale parameters as in (1).

JT05’s “multi-stage txt2img → upscale pipeline” test passes and sees:

At least one txt2img call.

At least one upscale_image call, chained from the txt2img outputs.

Error Handling Path Works

When WebUIAPI.upscale_image raises (e.g., patched to throw in JT05), run_pipeline() must:

Catch the exception.

Log a message.

Set lifecycle to an appropriate error state (LifecycleState.ERROR).

Return either None or an error result object (JT05 already allows either).

No Regression to Other Journeys

test_v2_full_pipeline_journey_runs_once and ...handles_runner_error continue to pass (PR-072 behavior intact).

No existing tests break due to changed signatures or imports.

3. Functional Design
3.1 Examine WebUIAPI’s Upscale Interface

File: src/api/webui_api.py

Before implementing anything in the controller, Codex must:

Open src/api/webui_api.py.

Identify the existing method (or desired method) for upscaling:

Something like:

class WebUIAPI:
    def upscale_image(self, image_path: str, scale: float, upscaler: str, tile_size: int | None = None, **kwargs) -> dict:
        ...


Use the exact signature and parameter names defined there, so JT05’s patches and assertions match.

If upscale_image does not exist yet, implement it in this PR as a thin wrapper around whatever underlying WebUI client call is already used for upscaling (check src/api/client.py or similar), using a signature that is simple and explicit:

def upscale_image(self, image_path: str, scale: float, upscaler: str, tile_size: int | None = None, **kwargs) -> dict:
    """
    High-level wrapper for WebUI's image upscaling.
    Returns a dict with 'images' and 'info' JSON, mirroring txt2img responses.
    """


JT05 will patch this method, so the object path must be stable:

"src.api.webui_api.WebUIAPI.upscale_image"

3.2 Extend AppController.run_pipeline() for Stage-Aware Behavior

File: src/controller/app_controller.py

We already have:

run_pipeline() as a public entrypoint (from PR-072).

Pipeline lifecycle and validation logic.

A PipelineTabFrameV2 with JT05 attributes (from PR-073).

We now make run_pipeline() stage-aware:

3.2.1 Gather Stage Flags and Parameters

Inside run_pipeline() (after validation passes and before calling any runner / WebUI):

Get a handle to the pipeline tab (whatever the current app uses):

pipeline_tab = getattr(self, "pipeline_tab", None)


If pipeline_tab is None, fall back to the existing runner-based behavior and return early.

Read the stage toggles and upscale params:

txt2img_enabled = bool(getattr(pipeline_tab, "txt2img_enabled", False).get())
img2img_enabled = bool(getattr(pipeline_tab, "img2img_enabled", False).get())
adetailer_enabled = bool(getattr(pipeline_tab, "adetailer_enabled", False).get())
upscale_enabled = bool(getattr(pipeline_tab, "upscale_enabled", False).get())

upscale_factor = getattr(pipeline_tab, "upscale_factor", None)
upscale_model = getattr(pipeline_tab, "upscale_model", None)
upscale_tile_size = getattr(pipeline_tab, "upscale_tile_size", None)

factor = float(upscale_factor.get()) if upscale_factor is not None else 2.0
model = upscale_model.get().strip() if upscale_model is not None else ""
tile_size = int(upscale_tile_size.get()) if upscale_tile_size is not None else 0

input_image_path = getattr(pipeline_tab, "input_image_path", "") or ""


Read the prompt text (for txt2img or metadata):

prompt = ""
try:
    if hasattr(pipeline_tab, "prompt_text"):
        prompt = pipeline_tab.prompt_text.get().strip()
except Exception:
    prompt = ""

3.2.2 Choose Execution Path

Implement the following high-level dispatch logic:

# Pseudo-logic inside run_pipeline(), after lifecycle set to RUNNING

if upscale_enabled and not (txt2img_enabled or img2img_enabled or adetailer_enabled):
    # Standalone upscale (JT05 path 1)
    result = self._run_standalone_upscale(
        input_image_path=input_image_path,
        factor=factor,
        model=model,
        tile_size=tile_size,
        prompt=prompt,
    )
elif txt2img_enabled and upscale_enabled:
    # Multi-stage txt2img -> upscale (JT05 path 2)
    result = self._run_txt2img_then_upscale(
        prompt=prompt,
        factor=factor,
        model=model,
        tile_size=tile_size,
    )
else:
    # Fallback to the existing runner-based implementation (PR-072)
    result = self._run_pipeline_via_runner_only()


At the end of run_pipeline():

On success: set lifecycle to IDLE and return result.

On failure: handled in the exception block (see 3.2.4).

3.3 Implement _run_standalone_upscale Helper

Add a private helper in AppController:

def _run_standalone_upscale(
    self,
    input_image_path: str,
    factor: float,
    model: str,
    tile_size: int,
    prompt: str,
):
    """
    Perform a single standalone upscale operation using WebUIAPI.upscale_image.
    This is the core for JT05 standalone upscale tests.
    """

Behavior:

Validate input_image_path:

If empty or not a file:

Log a warning.

Raise a ValueError or return an error result (JT05’s error test will cover this path).

Acquire WebUI API client:

Check if the app already has a shared WebUI client instance (e.g., self.webui_api or self.api_client).

If not, create a new WebUIAPI instance from src.api.webui_api (constructor should be cheap).

from src.api.webui_api import WebUIAPI
api = getattr(self, "webui_api", None)
if api is None:
    api = WebUIAPI()


Call upscale_image:

Inspect WebUIAPI.upscale_image signature and call with matching parameters; for example:

response = api.upscale_image(
    image_path=input_image_path,
    scale=factor,
    upscaler=model or None,
    tile_size=tile_size or None,
)


JT05 will patch WebUIAPI.upscale_image, so the call itself is what matters.

Wrap and return a stable result object:

return {
    "mode": "upscale_only",
    "input_image": input_image_path,
    "factor": factor,
    "model": model,
    "tile_size": tile_size,
    "prompt": prompt,
    "raw": response,
}

3.4 Implement _run_txt2img_then_upscale Helper

Add another helper:

def _run_txt2img_then_upscale(
    self,
    prompt: str,
    factor: float,
    model: str,
    tile_size: int,
):
    """
    Multi-stage pipeline: txt2img -> upscale.
    Uses WebUIAPI (or the injected pipeline runner) for txt2img,
    then WebUIAPI.upscale_image for each resulting image.
    """

Behavior:

Get WebUI API client in the same way as _run_standalone_upscale.

Build txt2img payload:

Use existing app state methods for model, sampler, resolution, etc. (e.g., from self.app_state or sidebar).

At minimum, provide prompt.

Example:

txt2img_args = {
    "prompt": prompt,
    # TODO: fill in model, sampler, steps, width, height from app_state/sidebar
}
txt2img_response = api.txt2img(**txt2img_args)


Extract generated image paths:

If the WebUI API returns base64 images only, JT05 may not inspect paths; it may only check that upscale_image was called.

For safety, treat the txt2img outputs as a list:

images = txt2img_response.get("images", []) or []


If the framework writes images to disk and returns paths, adapt accordingly.

For each image (or at least one representative image):

upscaled_results = []
for img in images[:1]:  # JT05 likely only asserts one call
    up = api.upscale_image(
        image_path=img if isinstance(img, str) else "",  # or write to temp file
        scale=factor,
        upscaler=model or None,
        tile_size=tile_size or None,
    )
    upscaled_results.append(up)


Return a structured result:

return {
    "mode": "txt2img_then_upscale",
    "prompt": prompt,
    "factor": factor,
    "model": model,
    "tile_size": tile_size,
    "txt2img": txt2img_response,
    "upscaled": upscaled_results,
}

3.5 Preserve Runner-Based Fallback

For any configuration not explicitly handled (e.g., txt2img-only, img2img-only, adetailer pipelines), keep the existing runner-only path from PR-072:

def _run_pipeline_via_runner_only(self):
    pipeline_config = self.build_pipeline_config_v2()
    runner = getattr(self, "pipeline_runner", None)
    if runner is None:
        raise RuntimeError("No pipeline runner configured")
    return runner.run(pipeline_config, None, self._append_log_threadsafe)


This function can already exist or be added as a small refactor of current run_pipeline()’s core.

3.6 Error Handling & Lifecycle

The top-level run_pipeline() should already have a try/except around the execution block (from PR-072). Ensure it:

Catches all exceptions from _run_standalone_upscale and _run_txt2img_then_upscale.

Logs a message like:

self._append_log(f"[controller] Pipeline error in run_pipeline: {exc!r}")


Calls:

self._set_lifecycle(LifecycleState.ERROR, error=str(exc))


Returns None (JT05 error test allows either None or a value).

This satisfies JT05’s error-handling scenario.

4. Test Plan

After implementing PR-074:

Run JT05 tests:

pytest tests/journeys/test_jt05_upscale_stage_run.py -q


All 5 JT05 tests should pass:

test_jt05_standalone_upscale_stage

test_jt05_multi_stage_txt2img_upscale_pipeline

test_jt05_upscale_parameter_variations

test_jt05_upscale_metadata_preservation

test_jt05_upscale_error_handling

Re-run the full V2 journey tests to confirm no regression:

pytest tests/journeys/test_v2_full_pipeline_journey.py::test_v2_full_pipeline_journey_runs_once -q
pytest tests/journeys/test_v2_full_pipeline_journey.py::test_v2_full_pipeline_journey_handles_runner_error -q


Optionally:

pytest tests/journeys -q


to validate all journeys together under this new behavior.

5. Non-Goals

Out of scope for PR-074:

No changes to GUI layout, stage cards, or prompt workspace UX.

No queue/job-runner integration (that’s the “Run Now” / JobService path in another PR).

No learning/JSONL history behavior; we only pass through prompt, factor, etc., in the return object for future use.

No changes to the test files themselves; they must pass as-is.

If you’d like next, I can draft a follow-on PR (PR-075) for JobService _execu