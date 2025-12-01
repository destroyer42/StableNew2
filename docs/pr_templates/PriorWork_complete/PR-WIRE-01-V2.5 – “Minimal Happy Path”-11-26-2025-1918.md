PR-WIRE-01-V2.5 – “Minimal Happy Path”-11-26-2025-1918.md

Here’s a Codex / Copilot MAX execution prompt for the first wiring PR, focused on one simple but real path:

GUI run → controller → pipeline → WebUI client (stub or real) → GUI feedback

You can paste this directly into Copilot MAX with the repo set to your current StableNew-cleanHouse repo.

You are acting as an implementation agent for the StableNew project.

## Context

Repository root: `StableNew-cleanHouse/`

StableNew is a Python 3.11+ Tk/Ttk GUI app that should orchestrate Stable Diffusion (txt2img/img2img/upscale) using:

- GUI under `src/gui/`
- Controllers under `src/controller/`
- Pipeline logic under `src/pipeline/`
- WebUI / process management under `src/api/`
- Utility helpers under `src/utils/`

We have a repo inventory file:

- `repo_inventory.json`

which tells us `reachable_from_main == true` for these key modules (non-exhaustive list):

- Entry / root:
  - `src/main.py`
  - `src/app_factory.py`
- GUI:
  - `src/gui/main_window_v2.py`
  - `src/gui/layout_v2.py`
  - `src/gui/gui_invoker.py`
  - Various V2 panels (e.g., `core_config_panel_v2.py`, `model_manager_panel_v2.py`, `pipeline_config_panel_v2.py`, `prompt_editor_panel_v2.py`, `status_bar_v2.py`, etc.)
- Controller:
  - `src/controller/app_controller.py`
  - `src/controller/webui_connection_controller.py`
- Pipeline:
  - `src/pipeline/executor.py`
  - `src/pipeline/pipeline_runner.py`
  - `src/pipeline/stage_sequencer.py`
- API / WebUI:
  - `src/api/client.py`
  - `src/api/webui_process_manager.py`
  - `src/api/healthcheck.py`
- Utils:
  - `src/utils/config.py`
  - `src/utils/file_io.py`
  - `src/utils/prompt_packs.py`

The file-access logger shows that right now, **only packs/presets and cache files are touched at runtime**. The GUI looks like V2, but almost no spine code is actually “hot”.

We are **not** doing any archiving in this PR.  
The goal is to make **one minimal, end-to-end happy path actually do work**.

Your task is to implement **PR-WIRE-01-V2.5 – Minimal Happy Path Wiring**.

---

## High-level goals for this PR

Implement a thin, clean path from the GUI to the pipeline and back:

1. From the V2 GUI (e.g., a “Run” / “Generate” button) → a controller method.
2. From the controller → a pipeline execution function.
3. From the pipeline → a WebUI call (real or stubbed).
4. From that WebUI/pipeline result → some visible feedback in the GUI.

It is OK if this only covers **one mode** (e.g., txt2img) and is only partially functional.  
We just want a real “button → code → response” chain that we can iterate on.

---

## Hard constraints

Do NOT:

- Introduce any new V1-style GUI entrypoints or files.
- Touch `archive/` or rename/move files as legacy.
- Modify the file access logger or summarizer tools.
- Change CI or GitHub workflow files.
- Implement a large feature set; keep this focused and incremental.

You SHOULD:

- Keep changes minimal and localized to:
  - `src/main.py`
  - `src/app_factory.py`
  - `src/gui/main_window_v2.py` (and possibly `src/gui/layout_v2.py` / `gui_invoker.py` as needed)
  - `src/controller/app_controller.py`
  - `src/controller/webui_connection_controller.py`
  - `src/pipeline/pipeline_runner.py` and/or `src/pipeline/executor.py`
  - `src/api/client.py` and/or `src/api/webui_process_manager.py` (for the call boundary)
- Add or update tests where it’s straightforward (e.g., for pipeline runner or controller behavior).

---

## Step 1 – Confirm and simplify the V2 GUI entry path

1. Inspect `src/main.py` and `src/app_factory.py` and determine the **current** path used to launch the GUI V2:
   - Find the main function / entrypoint.
   - Identify how `main_window_v2` / `layout_v2` / `gui_invoker` are used.

2. Ensure there is a **single, clear V2 entry path**:
   - `main()` in `src/main.py` should:
     - Set up logging and state as it does now.
     - Call into `app_factory` or a clearly named GUI bootstrap function for V2 (e.g., `create_app()` or similar).
   - If you see any remaining V1/legacy GUI entrypoints hanging off main, do NOT delete them yet, but:
     - Prefer to clearly use the V2 bootstrap for this PR.
     - You may add a code comment noting that the V2 path is canonical.

3. Do not change behaviour unrelated to GUI startup (e.g., CLI flags, logging, single-instance lock, etc.), unless absolutely required for correctness.

---

## Step 2 – Identify the “Run pipeline” UI action

1. Open `src/gui/main_window_v2.py` (and, if necessary, `src/gui/layout_v2.py` / `gui_invoker.py`).
2. Locate the **primary user action** that should trigger a pipeline run. This might be:
   - A “Run” / “Generate” / “Start pipeline” button; or
   - A menu item or toolbar action.

3. If such an action exists but currently:
   - Has an empty callback,
   - Only logs something,
   - Or calls a placeholder,

   then we will replace or extend that callback to route to the controller.

4. If no obvious “Run” action exists yet:
   - Add a single, clearly labeled button (e.g., “Run Pipeline”) in an appropriate panel (e.g., pipeline tab / run panel).
   - Wire its command handler to call a method on `AppController` (see next step).

---

## Step 3 – Wire GUI → AppController

1. Inspect `src/controller/app_controller.py`:
   - Identify any existing methods that look like they should drive a pipeline run (e.g., names containing `run`, `execute`, `start_job`, etc.).
   - If a suitable method exists but is not wired, adapt it.
   - If none exists or they are clearly V1-ish, create a new, minimal V2 method, e.g.:

     ```python
     class AppController:
         def run_txt2img_once(self, config: dict | None = None) -> None:
             ...
     ```

2. That controller method should:
   - Collect or accept the necessary parameters for a simple txt2img run.
     - It’s OK to start with a simplified config (e.g., one text prompt + some defaults).
   - Call into the pipeline layer (next step) in a **non-blocking or minimally-blocking** way that won’t freeze the GUI completely.
     - For now, a simple synchronous call is acceptable if that’s all you can safely do without a big threading refactor.
   - Handle exceptions by logging them and optionally notifying the GUI (e.g., via a status bar message).

3. In `main_window_v2` / `layout_v2`:
   - Ensure the GUI is instantiated with a reference to an `AppController` instance.
   - The “Run” button callback should call the new controller method:
     - Either directly, or via a small wrapper in `gui_invoker`.

---

## Step 4 – Wire AppController → Pipeline

1. Open `src/pipeline/pipeline_runner.py`, `src/pipeline/executor.py`, and `src/pipeline/stage_sequencer.py`.
2. Identify the **most appropriate single entry function** to represent “run one pipeline”:
   - For example, something like `run_pipeline(pipeline_config)` or `execute_txt2img(config)`.
   - If nothing is clearly usable as a single entry, create a focused function that:
     - Accepts a minimal config.
     - Orchestrates exactly one txt2img-style request.
     - Calls down to WebUI client (see Step 5).

3. Expose a stable, minimal API from pipeline layer:

   ```python
   # in src/pipeline/pipeline_runner.py (for example)
   def run_txt2img_once(config: dict) -> "PipelineResult":
       ...


Update AppController.run_txt2img_once(...) to call this pipeline function and handle the result.

Step 5 – Wire Pipeline → WebUI client (real or stub)

Open src/api/client.py and src/api/webui_process_manager.py:

Determine how these are intended to talk to Stable Diffusion WebUI:

HTTP client calls,

Process start/stop,

Healthchecks.

For this PR, you may choose one of two options:

Option A: Real WebUI call (preferred if feasible)

Implement a minimal client call for txt2img:

E.g., client.txt2img(request: dict) -> dict | Image.

Integrate it so that pipeline_runner.run_txt2img_once does:

Build a proper request payload from config.

Call the WebUI client.

Wrap the result in a small PipelineResult object for the controller/GUI.

Option B: Stub WebUI call (if the real integration is too unstable right now)

Implement a stub function in client.py that:

Logs the incoming config.

Returns a dummy PipelineResult object (e.g., with a fake image path or message).

Ensure pipeline runner calls this stub so the rest of the flow is exercised.

Make sure webui_connection_controller.py is consistent with whatever you do:

If it already coordinates WebUI connection / healthcheck, reuse it where appropriate.

Do not introduce a second, parallel WebUI integration path.

Step 6 – Pipeline → GUI feedback

Decide what counts as “visible feedback” for this PR:

Updating a status bar text.

Appending to a log panel.

Optionally, showing a thumbnail or path to the generated image if that’s already easy.

In AppController.run_txt2img_once:

After the pipeline call completes:

Pass a simple summary (success/fail, error message, maybe output path) back to the GUI.

You can either:

Call a method on main_window_v2 / a status bar widget, or

Emit an event/callback that the GUI subscribes to.

Keep this minimal. The goal is to be able to say:

“If I click Run, something real happens:

Controller gets invoked, pipeline gets invoked, WebUI/stub gets invoked,

and I see some indication in the GUI it did something.”

Step 7 – Light tests / sanity checks

Add or update tests where it is straightforward (no need to build a full suite in this PR):

For pipeline runner (e.g., ensure run_txt2img_once calls the WebUI client with expected shape).

For WebUI client/stub (e.g., client.txt2img returns expected structure).

Verify:

pytest -q


If there are pre-existing failing tests unrelated to this PR, note them, but do not try to fix them all here. Ensure your changes don’t introduce new failures (import errors, wrong signatures, etc.).

Manual smoke test:

Run: python -m src.main

Click the Run/Generate button you wired.

Confirm:

No crash.

Code path hits controller and pipeline.

You see some GUI feedback (status/log).

Acceptance criteria

GUI has a clear, discoverable “Run” or “Generate” action in the V2 interface.

Clicking it:

Calls into AppController (or equivalent central controller).

Calls a single pipeline entry function (e.g., run_txt2img_once or similar).

Calls either a real or stub WebUI client function.

Produces visible feedback in the GUI (status/log/etc.).

No new V1-style files or entrypaths are introduced.

No files are moved to archive/ in this PR.

Tests still run (allowing for any pre-existing failures; your changes must not introduce new import/syntax errors).

Final response format

When you are finished implementing this PR, respond with:

A concise summary of the wiring changes (GUI → controller → pipeline → WebUI → GUI).

The list of files you created or modified.

Any new public methods or functions you added (signatures and purpose).

How to exercise the new happy path from the GUI.

Any follow-up wiring opportunities you identified while working (e.g., next obvious things to connect).