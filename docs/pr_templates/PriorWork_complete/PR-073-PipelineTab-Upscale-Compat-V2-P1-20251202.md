PR-073-PipelineTab-Upscale-Compat-V2-P1-20251202.md

Title: PipelineTabFrameV2 Test-Compat Attributes for Upscale Journeys (JT05)
Snapshot: StableNew-snapshot-20251201-230021.zip (authoritative baseline)

0. Intent

Goal:
Make app.pipeline_tab expose the JT05-expected attributes so the Upscale Journey tests can drive the V2 GUI in a predictable way:

txt2img_enabled (BooleanVar)

img2img_enabled (BooleanVar)

adetailer_enabled (BooleanVar)

upscale_enabled (BooleanVar)

upscale_factor (DoubleVar)

upscale_model (StringVar)

upscale_tile_size (IntVar)

prompt_text (Entry-like widget with .insert() / .get())

input_image_path (string attribute)

This PR is GUI/attribute wiring only. It does not implement full upscale pipeline behavior; that’s the next PR (controller/WebUI wiring). Here we just:

Create the right attributes,

Hook them into the actual Upscale stage card where appropriate,

Ensure Stage enable/disable toggles reflect into StageCardsPanel.

JT05 will then stop failing with AttributeError and have real controls to work with.

1. Scope
1.1 Files Allowed to Change

Only these:

src/gui/views/pipeline_tab_frame_v2.py


No other files should be touched in this PR.

1.2 Forbidden Files (do NOT modify)
src/controller/app_controller.py
src/gui/views/stage_cards_panel_v2.py
src/gui/views/run_control_bar_v2.py
src/gui/panels_v2/*
src/gui/main_window_v2.py
src/pipeline/*
src/queue/*
src/main.py
tests/*


(We’re wiring test-compat attributes on the GUI frame only; controller logic and tests are handled in other PRs.)

2. Done Criteria

PR-073 is complete when all of the following are true:

build_v2_app(root) exposes app.pipeline_tab with the following attributes present and usable:

app.pipeline_tab.txt2img_enabled – tk.BooleanVar

app.pipeline_tab.img2img_enabled – tk.BooleanVar

app.pipeline_tab.adetailer_enabled – tk.BooleanVar

app.pipeline_tab.upscale_enabled – tk.BooleanVar

app.pipeline_tab.upscale_factor – tk.DoubleVar

app.pipeline_tab.upscale_model – tk.StringVar

app.pipeline_tab.upscale_tile_size – tk.IntVar

app.pipeline_tab.prompt_text – a widget instance supporting .insert(pos, text) and .get()

app.pipeline_tab.input_image_path – plain str attribute (default "")

JT05 can do the exact patterns from the test file without raising:

app.pipeline_tab.upscale_enabled.set(True)
app.pipeline_tab.txt2img_enabled.set(False)
app.pipeline_tab.img2img_enabled.set(False)
app.pipeline_tab.adetailer_enabled.set(False)

app.pipeline_tab.upscale_factor.set(2.0)
app.pipeline_tab.upscale_model.set("UltraSharp")
app.pipeline_tab.upscale_tile_size.set(512)

app.pipeline_tab.input_image_path = str(test_image_path)

app.pipeline_tab.prompt_text.insert(0, "a beautiful landscape")


Toggling the BooleanVars for stages propagates to StageCardsPanel via set_stage_enabled(...) (at least for "txt2img", "img2img", "upscale"). We do not need perfect UX in this PR, just that:

app.pipeline_tab.txt2img_enabled.set(False)


eventually calls:

stage_cards_panel.set_stage_enabled("txt2img", False)


_sync_state_overrides() on PipelineTabFrameV2 uses either:

prompt_workspace_state.get_current_prompt_text() when available, OR

The new self.prompt_text.get() as a fallback if the workspace state is missing or returns an empty string.

No other V2 GUI behavior regresses (existing GUI_v2 tests remain green).

3. Functional Design

All changes live inside PipelineTabFrameV2 in src/gui/views/pipeline_tab_frame_v2.py.

3.1 Add Stage Toggle Vars (txt2img/img2img/adetailer/upscale)

Where: In PipelineTabFrame.__init__, after we’ve assigned self.stage_cards_panel.

Add:

# Stage toggle variables used by JT05 and controller logic.
self.txt2img_enabled = tk.BooleanVar(value=True)
self.img2img_enabled = tk.BooleanVar(value=False)
self.adetailer_enabled = tk.BooleanVar(value=False)
self.upscale_enabled = tk.BooleanVar(value=False)


Behavior:

These vars are primary stage toggles for JT05 and later controller logic.

When they change, they should update the visibility of the corresponding stage card via StageCardsPanel.set_stage_enabled.

Add a helper in PipelineTabFrame:

def _on_stage_toggle_var(self, stage_name: str, var: tk.BooleanVar) -> None:
    """Bridge stage toggle BooleanVars to StageCardsPanel.set_stage_enabled."""
    if not hasattr(self, "stage_cards_panel") or self.stage_cards_panel is None:
        return
    try:
        enabled = bool(var.get())
        self.stage_cards_panel.set_stage_enabled(stage_name, enabled)
    except Exception:
        # Fail silently to avoid taking down the GUI in edge cases.
        pass


And attach watchers in __init__:

try:
    self.txt2img_enabled.trace_add("write", lambda *_: self._on_stage_toggle_var("txt2img", self.txt2img_enabled))
    self.img2img_enabled.trace_add("write", lambda *_: self._on_stage_toggle_var("img2img", self.img2img_enabled))
    self.upscale_enabled.trace_add("write", lambda *_: self._on_stage_toggle_var("upscale", self.upscale_enabled))
except Exception:
    pass

# For adetailer, we may simply track the flag for controller logic later;
# no StageCardsPanel visibility requirement in this PR.


This is enough for JT05 to toggle flags and for the underlying stage cards to respond structurally.

3.2 Expose Upscale Control Vars (factor/model/tile size) via Upscale Stage Card

We already have AdvancedUpscaleStageCardV2 with:

self.factor_var (DoubleVar)

self.upscaler_var (StringVar)

self.tile_size_var (IntVar)

We want PipelineTabFrame to expose proxies to those, rather than duplicating state.

In __init__, after self.stage_cards_panel exists:

# Upscale control proxies used by JT05.
self.upscale_factor = tk.DoubleVar(value=2.0)
self.upscale_model = tk.StringVar()
self.upscale_tile_size = tk.IntVar(value=0)

up_card = getattr(self.stage_cards_panel, "upscale_card", None)
if up_card is not None:
    try:
        # Initialize from card's internal vars
        self.upscale_factor = up_card.factor_var
    except Exception:
        pass
    try:
        self.upscale_model = up_card.upscaler_var
    except Exception:
        pass
    try:
        self.upscale_tile_size = up_card.tile_size_var
    except Exception:
        pass


Notes:

JT05 only needs .set() and .get() on these; aliasing to the stage-card vars is ideal because it keeps state unified.

If for some reason upscale_card doesn’t exist (e.g., misconfigured layout), we still have standalone DoubleVar/StringVar/IntVar created earlier, so JT05 won’t crash with AttributeError.

3.3 Add prompt_text Entry (Test-Compat Prompt Editor)

JT05 expects:

app.pipeline_tab.prompt_text.insert(0, "some prompt")


So we need a simple tk.Entry that:

Is accessible at pipeline_tab.prompt_text.

Feeds into _sync_state_overrides() as a fallback when no workspace prompt is available.

Placement suggestion:

PipelineTabFrame already has a left column (self.left_column) with:

self.sidebar

self.restore_last_run_button

We can add a minimal prompt field below the “Restore Last Run” button, but keep styling simple.

In __init__, after restore_last_run_button:

# Primary prompt entry (JT05 + fallback when prompt workspace is absent)
self.prompt_text = tk.Entry(self.left_column)
self.prompt_text.grid(row=2, column=0, sticky="ew", pady=(0, 4))
attach_tooltip(self.prompt_text, "Primary text prompt for the active pipeline.")


(We don’t need fancy styling here yet; future PRs can refine the UX. For the tests, it just needs to be a working Entry.)

3.4 Wire prompt_text into _sync_state_overrides()

Current code (simplified):

def _sync_state_overrides(self) -> None:
    if not self.state_manager:
        return
    prompt_text = ""
    try:
        if self.prompt_workspace_state is not None:
            prompt_text = self.prompt_workspace_state.get_current_prompt_text()
    except Exception:
        prompt_text = ""

    overrides = self.stage_cards_panel.to_overrides(prompt_text=prompt_text)
    ...


Update to:

def _sync_state_overrides(self) -> None:
    if not self.state_manager:
        return

    prompt_text = ""
    try:
        if self.prompt_workspace_state is not None:
            prompt_text = self.prompt_workspace_state.get_current_prompt_text() or ""
    except Exception:
        prompt_text = ""

    # Fallback to prompt_text Entry if workspace prompt is empty
    if not prompt_text and hasattr(self, "prompt_text"):
        try:
            prompt_text = self.prompt_text.get() or ""
        except Exception:
            pass

    overrides = self.stage_cards_panel.to_overrides(prompt_text=prompt_text)
    ...


This guarantees:

Existing prompt-workspace flow remains first-class.

JT05, which only uses the prompt_text entry, still produces a prompt that goes into stage overrides.

3.5 Add input_image_path Attribute

JT05 sets:

app.pipeline_tab.input_image_path = str(test_image_path)


and later the controller will need this for the upscale-only path.

In __init__:

# Path to the input image used for img2img/upscale journeys (JT05).
self.input_image_path: str = ""


No additional wiring is needed in this PR; we just ensure the attribute exists and is a string.

4. Test Expectations

After applying this PR (alone), the following should no longer raise AttributeError:

test_jt05_standalone_upscale_stage

test_jt05_multi_stage_txt2img_upscale_pipeline

test_jt05_upscale_parameter_variations

test_jt05_upscale_metadata_preservation

test_jt05_upscale_error_handling

They may still fail on logic (e.g., whether run_pipeline() calls WebUIAPI.upscale_image correctly) – that’s PR-074 territory – but the “missing attributes on PipelineTabFrame” category of failure is resolved.

5. Non-Goals

Out of scope for PR-073:

Any changes to AppController.run_pipeline() logic (txt2img vs upscale decisions, WebUI calls).

Any WebUI or API wiring (WebUIAPI.txt2img, .upscale_image, etc.).

Any queue/job system wiring.

Tk/TCL root creation tweaks (handled in PR-071).

Modifying JT05 itself.

Those will be handled in subsequent PRs once JT05 can at least drive the GUI via these attributes.