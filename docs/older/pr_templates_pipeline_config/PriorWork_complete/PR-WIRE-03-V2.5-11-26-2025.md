You are acting as an implementation agent for the StableNew project.

## Context

Repository root: `StableNew-cleanHouse/`

StableNew is a Python Tk/Ttk GUI app for Stable Diffusion. We are in the middle of a V2.5 wiring effort:

- PR-WIRE-01-V2.5: Minimal happy-path wiring (GUI → controller → pipeline → WebUI).
- PR-WIRE-02-V2.5: Theme + entrypoint + bootstrap contracts (Theme.apply_root, ENTRYPOINT_GUI_CLASS, wait_for_webui_ready, bootstrap_webui).

After those, we ran pytest and saw a cluster of remaining failures in:

1. **Journeys / Upscale:**  
   - `tests/journeys/test_jt05_upscale_stage_run.py::*`
   - All failing with:
     - `ModuleNotFoundError: No module named 'src.api.webui_api'`

2. **Pipeline / Learning contracts:**
   - `tests/learning/test_learning_hooks_pipeline_runner.py::*`
   - `tests/pipeline/test_pipeline_io_contracts.py::*`
   - `tests/pipeline/test_pipeline_runner_variants.py::*`
   - `tests/pipeline/test_stage_sequencer_runner_integration.py::*`
   - Typical errors:
     - `TypeError: FakePipeline.run_img2img_stage() got an unexpected keyword argument 'image_name'`
     - `TypeError: FakePipeline.run_img2img_stage() got an unexpected keyword argument 'image_name'`
     - `TypeError: FakePipeline.run_upscale_stage() got multiple values for argument 'image_name'`

3. **GUI V2 pipeline panel contracts:**
   - `tests/gui_v2/test_pipeline_prompt_integration_v2.py::*` fails with:
     - `AttributeError: 'PipelinePanelV2' object has no attribute 'prompt_text'`
     - `AttributeError: 'PipelinePanelV2' object has no attribute 'get_prompt'`
   - `tests/gui_v2/test_scrollable_pipeline_panel_v2.py::test_pipeline_panel_uses_scrollable_center` fails with:
     - `AttributeError: 'PipelinePanelV2' object has no attribute '_scroll'`

Your task is to implement **PR-WIRE-03-V2.5 – Pipeline/Learning Contracts + webui_api Stub**, focusing ONLY on:

- Providing a minimal `src.api.webui_api` module matching what journey tests expect.
- Fixing the pipeline runner/learning contracts so they match the signatures/tests (no more `image_name` TypeErrors).
- Restoring the GUI V2 pipeline panel API (prompt accessors and scroll handle) to what tests expect.

Do NOT:

- Move or archive any files.
- Attempt to fully “pass” all journey tests; we just want to remove the structural breakages.
- Change learning or journey tests; treat them as specification.
- Modify Theme / entrypoints / bootstrap behavior in this PR.
- Modify the file access logger or summarizer.

---

## Files you MUST inspect before making changes

1. `tests/journeys/test_jt05_upscale_stage_run.py`
   - See how it imports and uses `src.api.webui_api`:
     - Which functions/classes are imported?
     - What signatures are expected?

2. `tests/learning/test_learning_hooks_pipeline_runner.py`
   - Look at `FakePipeline` definition.
   - See how `pipeline_runner` is constructed and used.

3. `tests/pipeline/test_pipeline_io_contracts.py`
   - Look for the expected shape of `PipelineRunner` and its interactions with stages.

4. `tests/pipeline/test_pipeline_runner_variants.py`
   - Understand how variants and img2img stages are expected to be called.

5. `tests/pipeline/test_stage_sequencer_runner_integration.py`
   - See how `StageSequencer` and runner are expected to call:
     - `run_txt2img_stage`
     - `run_img2img_stage`
     - `run_upscale_stage`

6. `tests/gui_v2/test_pipeline_prompt_integration_v2.py`
   - See how `PipelinePanelV2` is expected to expose:
     - `prompt_text`
     - `get_prompt`
   - Note any other methods/attributes referenced.

7. `tests/gui_v2/test_scrollable_pipeline_panel_v2.py`
   - See how `PipelinePanelV2` is expected to expose `_scroll`.

8. Production code:
   - `src/api/client.py`
   - `src/api/webui_process_manager.py`
   - `src/pipeline/pipeline_runner.py`
   - `src/pipeline/stage_sequencer.py`
   - `src/gui/pipeline_config_panel_v2.py` or equivalent PipelinePanelV2 implementation.

---

## Step 1 – Implement a minimal src.api.webui_api module

1. Create a new file:

   - `src/api/webui_api.py`

2. From `tests/journeys/test_jt05_upscale_stage_run.py`, determine:

   - Which symbols are imported from `src.api.webui_api`.
   - How they are used (functions/classes, parameters, return types).

3. Implement a minimal, test-focused API that either:

   - Delegates to existing client/process manager code where appropriate, or
   - Provides a stub implementation that:
     - Accepts the expected arguments.
     - Returns simple, well-formed objects consistent with tests (e.g., a `PipelineResult`-like object, or a simple dataclass/dict with fields that tests check).

4. The goal is not to fully implement the real WebUI HTTP API in this PR. It’s OK if this module is a **thin facade or stub** so long as:

   - Imports from `src.api.webui_api` succeed.
   - Upscale journey tests reach their next assertion instead of crashing with `ModuleNotFoundError`.

---

## Step 2 – Fix pipeline/learning contracts (image_name & stage signatures)

1. Inspect how tests define `FakePipeline` in:

   - `tests/learning/test_learning_hooks_pipeline_runner.py`
   - `tests/pipeline/test_pipeline_runner_variants.py`
   - `tests/pipeline/test_pipeline_io_contracts.py`
   - `tests/pipeline/test_stage_sequencer_runner_integration.py`

   Focus on:

   - `run_txt2img_stage(...)`
   - `run_img2img_stage(...)`
   - `run_upscale_stage(...)`

   See what parameters they expect (names and position).

2. Inspect `src/pipeline/pipeline_runner.py` (and `stage_sequencer.py` as needed):

   - Find where it calls these stage methods on a pipeline instance.
   - Note any kwargs (e.g. `image_name=...`) that are causing errors.

3. Adjust **only the production pipeline code**, not the test fakes, so that:

   - Calls to `run_img2img_stage` and `run_upscale_stage` use the parameter names and calling convention that the tests expect.
   - Remove or rename `image_name` keyword arguments if the tests define functions that don’t take `image_name` (or expect it by position).

   For example (this is conceptual, you must align with tests exactly):

   ```python
   # Before (example)
   pipeline.run_img2img_stage(config=config, image_name=image_name)

   # After (example)
   pipeline.run_img2img_stage(config=config, source_image_name=image_name)
Or drop image_name entirely if tests don’t use/expect it.

Ensure that PipelineRunner returns whatever the tests in test_pipeline_io_contracts expect:

Some tests expect both a result and a learning_record.

Make sure your return type matches what those tests assert on.

Step 3 – Restore GUI V2 PipelinePanelV2 prompt/scroll API
Inspect tests/gui_v2/test_pipeline_prompt_integration_v2.py:

How do they use PipelinePanelV2?

Specifically, note how they access:

panel.prompt_text

panel.get_prompt()

Inspect src/gui/pipeline_config_panel_v2.py (or wherever PipelinePanelV2 is implemented):

Identify the current internal representation of the prompt (e.g., a ttk.Entry, tk.Text, or some internal field).

Implement:

python
Copy code
class PipelinePanelV2(...):
    @property
    def prompt_text(self) -> str:
        """Return the current main prompt as text."""
        ...

    def get_prompt(self) -> str:
        """Backward-compatible accessor; delegate to prompt_text."""
        return self.prompt_text
These should simply reflect the same underlying prompt state that the GUI uses.

Inspect tests/gui_v2/test_scrollable_pipeline_panel_v2.py:

See how _scroll is referenced.

It likely expects _scroll to exist as a child widget or scroll helper.

In PipelinePanelV2, ensure _scroll exists:

If the panel already creates a scrollable center widget (e.g., ScrollableFrameV2), assign it to self._scroll.

If not, create a minimal self._scroll attribute pointing to whatever scrollable frame or canvas you already have.

The point is to make this attribute exist and align with the test’s expectations for type/behavior, without a major layout rewrite.

Step 4 – Run focused tests and confirm
After making changes:

Run targeted tests:

bash
Copy code
pytest tests/journeys/test_jt05_upscale_stage_run.py -q
pytest tests/learning/test_learning_hooks_pipeline_runner.py tests/pipeline/test_pipeline_io_contracts.py tests/pipeline/test_pipeline_runner_variants.py tests/pipeline/test_stage_sequencer_runner_integration.py -q
pytest tests/gui_v2/test_pipeline_prompt_integration_v2.py tests/gui_v2/test_scrollable_pipeline_panel_v2.py -q
It is OK if some journey tests still fail on deeper assertions (assert False placeholders, etc.).

The goal is to eliminate:

ModuleNotFoundError for src.api.webui_api

The TypeError about unexpected/multiple image_name args

The AttributeError on prompt_text, get_prompt, and _scroll.

Then run the full test suite to confirm no new regressions:

bash
Copy code
pytest -q
There will still be other failures from parts we haven’t wired yet (other journeys, learning behaviors, etc.). That’s expected.

Acceptance criteria
src/api/webui_api.py exists, and imports from it in journey tests succeed.

tests/journeys/test_jt05_upscale_stage_run.py no longer fails with ModuleNotFoundError: src.api.webui_api.

It may still fail on deeper assertions; that’s OK for this PR.

The pipeline/learning tests listed above no longer raise:

TypeError: FakePipeline.run_img2img_stage() got an unexpected keyword argument 'image_name'

TypeError: FakePipeline.run_upscale_stage() got multiple values for argument 'image_name'

GUI V2 tests:

tests/gui_v2/test_pipeline_prompt_integration_v2.py

tests/gui_v2/test_scrollable_pipeline_panel_v2.py
no longer fail due to:

Missing prompt_text

Missing get_prompt

Missing _scroll

No changes to:

Theme or entrypoints (beyond what’s already done in previous PRs).

Test files themselves (except where absolutely necessary to fix obvious typos; generally prefer adjusting production code to match tests).

Final response format
When you are finished, reply with:

A short summary of what you changed:

New webui_api module API.

Pipeline runner / stage call signature fixes.

PipelinePanelV2 prompt/scroll API additions.

The list of files you created or modified.

The key public functions/methods you added or changed (signatures and what they do).

The results of running the targeted pytest commands above (pass/fail per file).

Any follow-up wiring opportunities you saw (e.g., specific journey tests that are now “reachable” but failing logically).