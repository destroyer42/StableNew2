PHASE1-1-ConceptualPlanV2_5_P2(11-28-25).md
1. Define What “V1 vs V2 vs Unused” Actually Means

First, I’d explicitly classify every relevant file into three buckets:

V2 (canonical) – must survive, will be actively wired:

Suffixes: _v2, V2 in class names

Directly referenced by main.py, app_factory.py, executor.py, current tests

Lives in obviously “new” modules (e.g. main_window_v2.py, pipeline_panel_v2.py, advanced_txt2img_stage_card_v2.py, theme_v2.py, app_state_v2.py, webui_resources.py, last_run_store_v2_5.py)

V1 (legacy) – to archive immediately:

Original GUI (e.g. main_window.py, pipeline_panel.py, older *_card.py without _v2)

Old helpers: legacy healthcheck / webui discovery / old controller variants

Anything used only by old tests like test_gui_v1_*, test_main_window.py targeting the first GUI

V2-Experimental (not wired yet, but not legacy):

Newer V2 files that aren’t yet referenced from main.py or controllers

Things like advanced prompt editor v2, randomization v2, learning hooks, etc.

How I’d actually do the classification

I’d run a small script over the snapshot (you’ve already dropped a StableNew-cleanHouse-YYYY.zip):

Walk src/ and build an inventory:

file path

top-level classes

# comments that say “V2”, “legacy”, “deprecated”

whether they’re referenced by:

main.py, app_factory.py, executor.py

any test_*.py in tests/

Apply rules:

If a file:

has _v2 in name or only V2 classes,

and is referenced from main.py/app_factory/executor/tests,
→ mark as V2 canonical.

If a file:

is duplicated by a _v2 sibling or

only referenced by V1-style tests,
→ mark as V1.

If a file:

has _v2, but isn’t referenced anywhere yet,
→ mark as V2-Experimental.

Generate a single JSON + markdown report:

repo_inventory_classified.json

docs/StableNew_V2_Inventory.md with three lists:

“V2 Canonical”

“Legacy (V1 – to archive)”

“V2 Experimental (not wired yet)”

This becomes the source of truth for Phase 1.

2. Archiving V1 Cleanly (Without Losing It)

Once we know what’s V1, I’d physically move it out of the way so it cannot accidentally be imported.

Step 2.1 – Create archive structure

archive/gui_v1/

archive/api_v1/

archive/misc_v1/

Step 2.2 – For each V1 file:

Move from src/... to archive/...

Rename: main_window.py → main_window_v1 (OLD).py
(so if it ever gets referenced, it’s visibly wrong)

Step 2.3 – Fix imports / tests

Run a search for from src.gui.main_window import etc.

If any V1 imports remain:

Either point to V2 equivalents

Or remove the tests that are explicitly for V1 (they’re no longer relevant)

Mark removed V1 tests in a doc: docs/TESTS_RETIRED_V1.md

Now your tree literally cannot compile with V1 unless someone goes spelunking in archive/.

3. Fix the V2 GUI Scaffold “Clearly and Deterministically”

The goal: one predictable layout contract and one path from GUI → Controller → Pipeline.

3.1 Define the “Zone Map” for MainWindowV2

I’d create a tiny spec doc:

docs/gui/MAINWINDOW_V2_ZONE_MAP.md:

header_zone – top, toolbar/status buttons, global controls

left_zone – pipeline / core config panel

center_zone – scrollable main pipeline stages

right_zone – optional/advanced info (future)

bottom_zone – status bar, progress, ETA, WebUI health

And then enforce:

MainWindowV2 owns these zones:

self.header_zone

self.left_zone

self.center_zone

self.bottom_zone

Each zone is one container widget (usually a ttk.Frame).

3.2 Make MainWindowV2 construct zones before controller

Right now, you’re hitting errors like:

'MainWindowV2' object has no attribute 'header_zone'

So the fix is structural:

In main_window_v2.py:

Ensure the __init__:

Creates all zone frames immediately

Exposes them as attributes

class MainWindowV2(ttk.Frame):
    def __init__(self, root: tk.Tk, *args, **kwargs):
        super().__init__(root, *args, **kwargs)
        self.root = root

        self.header_zone = ttk.Frame(self)
        self.left_zone = ttk.Frame(self)
        self.center_zone = ttk.Frame(self)
        self.bottom_zone = ttk.Frame(self)

        # grid/pack layout here
        self._build_header()
        self._build_left_panel()
        self._build_center_panel()
        self._build_bottom_status()


In app_factory.build_v2_app():

Instantiate MainWindowV2

Only then create AppController:

window = MainWindowV2(root)
app_controller = AppController(window, pipeline_runner=pipeline_runner, threaded=threaded)

3.3 Make AppController assume zones exist

Now AppController can be simplified:

Remove the “guessing” / deferring / zone detection.

Assume main_window.header_zone, left_zone, bottom_zone exist.

_attach_to_gui() becomes a simple, deterministic wiring:

def _attach_to_gui(self) -> None:
    # header buttons
    header = self.main_window.header_zone
    header.launch_webui_button.configure(command=self.on_launch_webui_clicked)
    header.retry_connect_button.configure(command=self.on_retry_webui_clicked)

    # left panel controls
    pipeline_panel = self.main_window.pipeline_panel  # or left_zone child
    pipeline_panel.bind_on_run(self.on_run_pipeline_clicked)
    # etc...

    # status label
    self.status_label = self.main_window.bottom_zone.status_label


This eliminates phase-order bugs. The window builds its structure; the controller wires the behavior.

3.4 Kill config_manager as a Tk option

Co-Pilot already flagged:

_tkinter.TclError: unknown option "-config_manager"

So:

In base_stage_card_v2.py and all subclasses (advanced_txt2img_stage_card_v2.py, etc.) remove config_manager from super().__init__ calls:

# BAD
super().__init__(parent, config_manager=config_manager, **kwargs)

# GOOD
super().__init__(parent, **kwargs)
self.config_manager = config_manager


No non-Tk options should be passed into Tk constructors.

4. Make WebUI Discovery & Healthcheck Final and Boring

You’re already most of the way there. Phase 1 goal: never touch this again.

4.1 Canonical healthcheck

Ensure exactly one canonical wait_for_webui_ready(base_url, timeout, poll_interval) in src/api/healthcheck.py

All other modules import from here:

main.py

webui_discovery.py

webui_process_manager.py

app_controller / GUI click handlers

Legacy helpers in webui_discovery.py stay renamed to _wait_for_webui_ready_legacy and unreferenced.

4.2 Single source of WebUI base URL

Centralize base URL computation: probably in webui_process_manager or healthcheck.

GUI/Controller do not compute http://127.0.0.1:7860 themselves — they ask the WebUI layer.

4.3 Tests

Keep test_webui_healthcheck.py and test_bootstrap_webui_autostart.py as your contract tests.

When those pass reliably, freeze the API and mark this Phase 1 complete for WebUI.

5. Stable Dropdown Population & Payload Correctness

Here the plan leans on the work you already did: webui_resources.py, last_run_store_v2_5.py, controller pass-throughs, and advanced_txt2img_stage_card_v2.py.

5.1 Resource discovery flow

Target flow:

WebUIResourceService knows how to ask the API or walk the filesystem for:

models

VAEs

upscalers

hypernetworks

embeddings

AppController wraps this with:

def list_models(self) -> list[WebUIResource]: ...
def list_vaes(self) -> list[WebUIResource]: ...
def list_upscalers(self) -> list[WebUIResource]: ...
def list_hypernetworks(self) -> list[WebUIResource]: ...
def list_embeddings(self) -> list[WebUIResource]: ...


AdvancedTxt2ImgStageCardV2 calls:

models = self.controller.list_models()
self.model_var.set(default_model_name)
self.model_dropdown["values"] = [m.display_name for m in models]


When user selects a model, the card updates the config:

def on_model_changed(self, event=None):
    selected = self.model_var.get()
    resource = self._model_lookup[selected]
    self.controller.set_model_for_stage(self.stage_id, resource.name)


So the true model name (what WebUI expects) is used in config/payload, while display name is just for UI.

5.2 Last-run config restore

Use LastRunStoreV2_5 like this:

On app startup:

Controller loads: config = last_run_store.load()

If present:

Apply to internal pipeline config

Tell GUI to preload dropdowns/sliders (MainWindowV2/StageCards pulled from controller)

After a successful pipeline run:

Controller compiles a minimal LastRunConfigV2_5 object

Calls last_run_store.save(config)

This gives you the “load stable config from last session” behavior from old StableNew, but in a controlled V2 way.

5.3 Payload correctness

executor.py already:

Pulls from a config dict

Shapes payloads for /sdapi/v1/options, /sdapi/v1/txt2img, etc.

Phase 1 target is not to redesign the executor — just:

Ensure the config keys it expects are actually filled from the GUI/controller.

Add one golden-path integration test:

Build a fake pipeline config

Pass it into executor

Assert generated JSON payload matches expected fields (model, vae, sampler, scheduler, etc.)

6. Zero Tkinter Errors

Concrete plan:

Add a very small GUI smoke test:

def test_main_window_v2_smoke():
    root = tk.Tk()
    try:
        window = MainWindowV2(root)
        controller = AppController(window, pipeline_runner=FakeRunner(), threaded=False)
    finally:
        root.destroy()


Run this (and a few similar ones) in headless-friendly mode (you may already use os.environ["DISPLAY"] tricks or pytest markers).

Fix every Tkinter TclError by:

Removing custom options from widget constructors

Ensuring ttk.Style styles exist before reference

Ensuring all frames exist before they’re used in controller wiring

Once this test is green, you’ve got a baseline guarantee that “V2 GUI can be constructed without exploding.”

7. Inputs I’d Need From You

If I were actually implementing Phase 1 for real (soup to nuts) I’d want:

Latest snapshot zip (which you’ve already provided)

Your short list of “must-keep V2 experimental files”, e.g.:

advanced prompt editor v2

randomization engine v2

learning hooks / JSONL record writer v2

Confirmation that:

main.py should always launch V2-only

Old main_v1 entrypoints (if any) can be safely archived

Any non-negotiable UX expectations for Phase 1:

e.g., “Pipeline tab must show: global negative, prompt pack picker, model/sampler/CFG/steps/size”

That’s it. Everything else I can infer from the repo and tests.

8. How I’d Avoid Losing Unused, Non-Legacy Work

This is the “don’t throw away good ideas” piece.

For everything classified as V2-Experimental:

Move them into a clearly labeled “staging” folder, not archive:

src/experimental_v2/ or src/labs_v2/

Document them in:

docs/StableNew_V2_Experimental_Features.md

For each:

File / class

Intended use (randomization, advanced prompt editing, etc.)

Dependencies it likely needs (controller hooks, UI zone, pipeline events)

Proposed Phase in the roadmap where it will be pulled back in

Do not import them in Phase 1.
They are explicitly out-of-scope until:

Pipeline is stable

Dropdowns are correct

WebUI integration is boring

Then in later phases (learning, randomization, etc.) we pick them up intentionally, one PR at a time.

If you want, next step I can:

Turn this into a StableNewV2P2-Phase1-ExecutionPlan-YYYY-MM-DD.md you can drop into docs/, or

Write a Codex-ready PR bundle for the exact Phase 1 steps (classification script + archive + GUI zone map + Tk fixes + dropdown/payload sanity).