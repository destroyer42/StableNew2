# PR-VID-UX-360 Task-first Video Workflow Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Video Workflow tab starts from "what do you want to make?", picks the engine, fills the settings with reasons, and shows only what that task needs.

**Architecture:** A pure rules module (`src/video/workflow_tasks.py`) turns the existing workflow records into task eligibility, an engine choice and suggested settings. A new Tk panel renders the task selector and the Suggested settings line and owns pin state. The tab frame is re-laid out around them; it still writes the same Tk variables, so `get_video_workflow_state()` and everything below it are unchanged.

**Tech Stack:** Python 3.14, Tkinter/ttk, pytest (`pytestmark = pytest.mark.gui` for Tk tests, `tk_root` fixture, helpers in `tests/helpers/make_video_313.py`).

**Spec:** `docs/Subsystems/Video/PR-VID-UX-360_Task_First_Video_Workflow_Design.md`

## Global Constraints

- Worktree `C:\Users\rob\qual\StableNew-vid-task-first`, branch `feature/pr-vid-ux-360-task-first-video-workflow`. Never push to `main`; no push or PR without the owner's say.
- Canonical path unchanged: no edits to `video_workflow_njr_builder.py`, `workflow_compiler.py`, admission, queue, catalog specs or governance.
- `workflow_tasks.py` has no Tk, no I/O, and contains no workflow id or model name.
- The task id never appears in a submitted form (`get_video_workflow_state(for_submission=True)`).
- The experimental opt-in is never ticked by code and is cleared on every engine change.
- No new tuning numbers: suggestions come only from record fields (`frame_count.default`, `operator_controls` defaults, `form_visibility`, `operator_projection`) and `rife_runtime.find_rife_executable()`.
- Smoothing default is **on**, except: RIFE not found, or task `sequence`.
- Existing tab attributes keep their names: `workflow_combo`, `queue_workflow_button`, `experimental_opt_in_check`, `advanced_section`, `conditioning_section`, `batch_panel`, `sequence_panel`, `experiment_panel`, `eval_panel`, `motion_library_panel`, `motion_readiness_panel`, `motion_prep_panel`, `recent_outputs_panel`, `runtime_readiness_strip`, `use_svd_button`, `effective_settings_section`, `overview_panel`, `frozen_plan_button`, `workflow_controls_panel`.
- Controller surface ceilings are not raised (`AGENTS.md` section 3). Finish with `python tools/ci/run_pr_gate.py` and `git diff --check`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.

## Review Focus

1. A task whose only eligible engines are experimental: the opt-in is shown, Queue stays disabled, nothing ticks it. (Task 1, Task 5)
2. RIFE not found while a restored state has smoothing pinned on: the pin is kept, and the Suggested settings line says smoothing cannot run and why, before Queue. (Task 2, Task 5)
3. Task switch while a batch step is running: refused with the existing message and the selector returns to `batch`. (Task 5)
4. Saved state with an unknown `task` value or a workflow id no longer in the catalog: falls back to `animate` and the recommended engine without raising. (Task 1, Task 6)
5. Leaving `follow_clip` with a Motion Library binding or a prepared motion source: the driving field, the binding and the prepared record are dropped, so none is submitted with an engine that does not accept them. (Task 5)

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/video/workflow_tasks.py` | create | Tasks, eligibility, engine choice, suggestions, pin reconciliation, task inference |
| `src/controller/video_workflow_controller.py` | modify | `rife_available()` |
| `src/gui/views/video_workflow_task_panel_v2.py` | create | Task selector, Suggested settings line, pin state |
| `src/gui/views/video_workflow_tab_frame_v2.py` | modify | Layout, per-task visibility, disclosure grouping, state `task` key, handoff task selection |
| `tests/video/test_workflow_tasks.py` | create | Rules tests |
| `tests/gui_v2/test_pr_vid_ux_360_task_first.py` | create | Panel and tab behaviour |
| existing `tests/gui_v2/test_*video*`, `test_pr_vid_*`, `test_focused_operator_workspace_110.py`, `test_tab_overview_panels_v2.py`, `tools/operator_journey/golden/vid0*.py` | modify | Only assertions about the old layout |
| `docs/Subsystems/Video/VIDEO_PIPELINE.md`, `STATUS.md`, `docs/research/stablenew-experience/workflows/video-and-motion.md` | modify | Operator surface description |

---

### Task 1: Tasks, eligibility, engine choice, task inference

**Files:**
- Create: `src/video/workflow_tasks.py`
- Test: `tests/video/test_workflow_tasks.py`

**Interfaces:**
- Consumes: workflow record dicts as returned by `VideoWorkflowController.list_workflow_specs()` (keys used: `workflow_id`, `display_name`, `governance_state`, `experimental`, `form_visibility`, `operator_projection.admission_block_reason`).
- Produces:

```python
TASK_ANIMATE = "animate"; TASK_FOLLOW_CLIP = "follow_clip"
TASK_SEQUENCE = "sequence"; TASK_BATCH = "batch"

@dataclass(frozen=True)
class VideoTask:
    task_id: str
    label: str        # "Animate from a prompt", "Follow a driving clip", "Multi-shot sequence", "Many images"
    description: str  # one sentence for the tooltip

TASKS: tuple[VideoTask, ...]   # in the order above

@dataclass(frozen=True)
class EngineChoice:
    workflow_id: str
    reason: str         # e.g. "Recommended: approved for production."
    needs_opt_in: bool
    block_reason: str   # "" when not blocked

def eligible_workflows(task_id: str, records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]
def choose_workflow(task_id: str, records: Iterable[Mapping[str, Any]], pinned_workflow_id: str = "") -> EngineChoice | None
def infer_task(record: Mapping[str, Any] | None, saved_task: Any = None) -> str
NO_ENGINE_MESSAGE = "No installed workflow supports this."
```

- [ ] **Step 1: Write the failing tests** in `tests/video/test_workflow_tasks.py`. Build records with a local helper `_rec(wid, *, approved=False, experimental=False, pose=False, frame_count=True, block="")`.

```python
def test_eligibility_splits_on_driving_clip():
    recs = [_rec("a", approved=True), _rec("b", experimental=True, pose=True)]
    assert [r["workflow_id"] for r in eligible_workflows(TASK_ANIMATE, recs)] == ["a"]
    assert [r["workflow_id"] for r in eligible_workflows(TASK_FOLLOW_CLIP, recs)] == ["b"]
    assert [r["workflow_id"] for r in eligible_workflows(TASK_BATCH, recs)] == ["a"]

def test_sequence_needs_a_frame_count_policy():
    recs = [_rec("a", approved=True, frame_count=False), _rec("c", approved=True)]
    assert [r["workflow_id"] for r in eligible_workflows(TASK_SEQUENCE, recs)] == ["c"]

def test_choice_order_pinned_then_approved_then_unblocked_then_blocked():
    recs = [_rec("x", experimental=True), _rec("a", approved=True), _rec("a2", approved=True)]
    assert choose_workflow(TASK_ANIMATE, recs).workflow_id == "a"
    assert choose_workflow(TASK_ANIMATE, recs, "a2").workflow_id == "a2"
    assert choose_workflow(TASK_ANIMATE, recs, "not-eligible").workflow_id == "a"

def test_experimental_only_task_needs_opt_in_and_is_not_blocked():
    choice = choose_workflow(TASK_FOLLOW_CLIP, [_rec("b", experimental=True, pose=True)])
    assert (choice.workflow_id, choice.needs_opt_in, choice.block_reason) == ("b", True, "")

def test_unblocked_experimental_beats_blocked_one():
    recs = [_rec("f", experimental=True, pose=True, block="hardware unqualified"),
            _rec("b", experimental=True, pose=True)]
    assert choose_workflow(TASK_FOLLOW_CLIP, recs).workflow_id == "b"
    only = choose_workflow(TASK_FOLLOW_CLIP, recs[:1])
    assert only.block_reason == "hardware unqualified"

def test_no_eligible_engine_returns_none():
    assert choose_workflow(TASK_FOLLOW_CLIP, [_rec("a", approved=True)]) is None

def test_infer_task():
    assert infer_task(_rec("b", pose=True)) == TASK_FOLLOW_CLIP
    assert infer_task(_rec("a")) == TASK_ANIMATE
    assert infer_task(_rec("a"), "sequence") == TASK_SEQUENCE      # a saved valid task wins
    assert infer_task(_rec("a"), "nonsense") == TASK_ANIMATE
    assert infer_task(None, None) == TASK_ANIMATE

def test_module_names_no_workflow_or_model():
    text = Path(workflow_tasks.__file__).read_text(encoding="utf-8").lower()
    assert not any(word in text for word in ("wan", "ti2v", "animate2", "svd", "comfy"))
```

- [ ] **Step 2: Run** `python -m pytest tests/video/test_workflow_tasks.py -q` — expected: collection error, module missing.
- [ ] **Step 3: Implement** the Produces block. `approved` means `governance_state == WORKFLOW_GOVERNANCE_APPROVED and not experimental` (the rule in `workflow_picker._is_approved` plus `recommended_workflow_id`). A saved task is honoured only if it is one of the four ids **and** `record` is eligible for it; otherwise infer from `form_visibility.pose_video`.
- [ ] **Step 4: Run** the same command — expected: all pass.
- [ ] **Step 5: Commit** `feat(video): task eligibility and engine choice rules (PR-VID-UX-360)`.

### Task 2: Suggested settings and pin reconciliation

**Files:**
- Modify: `src/video/workflow_tasks.py`
- Test: `tests/video/test_workflow_tasks.py`

**Interfaces:**
- Consumes: Task 1; record keys `frame_count` (`{"default": int, "choices": [{"frames": int, ...}]}`), `form_visibility`, `operator_controls`, `operator_projection.fixed_settings`.
- Produces:

```python
FIELD_LENGTH = "frame_count"; FIELD_MOTION = "motion_profile"; FIELD_SMOOTH = "smooth"
FIELD_SEED = "seed"; FIELD_NEGATIVE = "negative_prompt"; FIELD_ENGINE = "workflow_id"

@dataclass(frozen=True)
class Suggestion:
    field: str
    value: Any
    reason: str

def suggest_settings(task_id: str, record: Mapping[str, Any], *, rife_available: bool) -> dict[str, Suggestion]
def reconcile(current: Mapping[str, Any], pinned: Collection[str],
              suggestions: Mapping[str, Suggestion], record: Mapping[str, Any]
              ) -> tuple[dict[str, Any], list[str]]
    # -> (values to write into the form, human notes for pins that had to be replaced)
def smoothing_warning(task_id: str, smooth_on: bool, *, rife_available: bool) -> str
```

Fixed reason strings (exact copy):
- smooth on: `"Smoother playback; RIFE was found."`
- RIFE missing: `"Off: RIFE was not found. Put a RIFE release in tools/rife to enable smoothing."`
- sequence: `"Off: smoothing is not applied inside a sequence."`
- seed: `"Random; the seed is recorded with the job."`
- negative: `"Left empty; the engine's own default applies."`
- length: `"The engine's default length."`
- motion: `"A safe starting point."`

- [ ] **Step 1: Write the failing tests**

```python
def test_suggestions_come_from_the_record():
    rec = _rec("a", approved=True) | {"frame_count": {"default": 81, "choices": [{"frames": 49}, {"frames": 81}]}}
    s = suggest_settings(TASK_ANIMATE, rec, rife_available=True)
    assert s[FIELD_LENGTH].value == 81 and s[FIELD_SMOOTH].value is True
    assert s[FIELD_SEED].value == "" and s[FIELD_NEGATIVE].value == ""

def test_motion_only_when_declared():
    rec = _rec("a") ; rec["form_visibility"]["motion_profile"] = False
    assert FIELD_MOTION not in suggest_settings(TASK_ANIMATE, rec, rife_available=True)

def test_smoothing_off_without_rife_and_in_a_sequence():
    rec = _rec("a", approved=True)
    assert suggest_settings(TASK_ANIMATE, rec, rife_available=False)[FIELD_SMOOTH].value is False
    seq = suggest_settings(TASK_SEQUENCE, rec, rife_available=True)[FIELD_SMOOTH]
    assert seq.value is False and "sequence" in seq.reason

def test_reconcile_keeps_legal_pins_and_replaces_illegal_ones():
    rec = _rec("a") | {"frame_count": {"default": 81, "choices": [{"frames": 49}, {"frames": 81}]}}
    s = suggest_settings(TASK_ANIMATE, rec, rife_available=True)
    values, notes = reconcile({FIELD_LENGTH: 49, FIELD_SMOOTH: False}, {FIELD_LENGTH, FIELD_SMOOTH}, s, rec)
    assert FIELD_LENGTH not in values and FIELD_SMOOTH not in values and notes == []
    values, notes = reconcile({FIELD_LENGTH: 33}, {FIELD_LENGTH}, s, rec)
    assert values[FIELD_LENGTH] == 81 and len(notes) == 1

def test_reconcile_applies_every_unpinned_suggestion():
    rec = _rec("a") ; s = suggest_settings(TASK_ANIMATE, rec, rife_available=True)
    values, _ = reconcile({}, set(), s, rec)
    assert set(values) == set(s)

def test_pinned_smoothing_without_rife_is_kept_and_warned():   # Review Focus 2
    assert smoothing_warning(TASK_ANIMATE, True, rife_available=False).startswith("Smoothing cannot run")
    assert smoothing_warning(TASK_ANIMATE, True, rife_available=True) == ""
    assert "sequence" in smoothing_warning(TASK_SEQUENCE, True, rife_available=True)
```

- [ ] **Step 2: Run** — expected: import errors for the new names.
- [ ] **Step 3: Implement.** A pinned value is illegal only for `FIELD_LENGTH` (not among `frame_count.choices`) and `FIELD_MOTION` (engine does not declare it); every other pin is always kept. Operator-control defaults are not part of `suggest_settings` — `WorkflowControlsPanel.apply` already loads them.
- [ ] **Step 4: Run** `python -m pytest tests/video/test_workflow_tasks.py -q` — expected: all pass.
- [ ] **Step 5: Commit** `feat(video): suggested settings and pin reconciliation (PR-VID-UX-360)`.

### Task 3: RIFE availability on the controller

**Files:**
- Modify: `src/controller/video_workflow_controller.py`
- Test: `tests/controller/test_video_workflow_controller.py`

**Interfaces:**
- Produces: `VideoWorkflowController.rife_available(self) -> bool` — `find_rife_executable() is not None`, never raises (returns `False` on any exception).

- [ ] **Step 1: Failing test:** patch `src.controller.video_workflow_controller.find_rife_executable` to return `Path("x")`, then `None`, then raise `OSError`; assert `True`, `False`, `False`.
- [ ] **Step 2: Run** `python -m pytest tests/controller/test_video_workflow_controller.py -q -k rife` — expected: AttributeError.
- [ ] **Step 3: Implement** as a `@staticmethod`-free instance method importing `find_rife_executable` from `src.video.rife_runtime`.
- [ ] **Step 4: Run** — pass. Also run `python tools/ci/run_pr_gate.py --help` to find the controller-ceiling stage name and run that stage; expected: no ceiling raised.
- [ ] **Step 5: Commit** `feat(video): expose RIFE availability to the workflow form (PR-VID-UX-360)`.

### Task 4: Task panel widget

**Files:**
- Create: `src/gui/views/video_workflow_task_panel_v2.py`
- Test: `tests/gui_v2/test_pr_vid_ux_360_task_first.py`

**Interfaces:**
- Consumes: `TASKS`, `VideoTask` (Task 1).
- Produces:

```python
class WorkflowTaskSelector(ttk.Frame):
    def __init__(self, master, *, on_select: Callable[[str], bool]) -> None
        # on_select returns False to refuse; the selector then stays on the previous task
    task_var: tk.StringVar
    buttons: dict[str, ttk.Radiobutton]            # keyed by task id
    def set_task(self, task_id: str) -> None       # no callback
    def set_availability(self, reasons: Mapping[str, str]) -> None
        # task id -> "" (enabled) or the reason it is disabled (also its tooltip)

class SuggestedSettingsLine(ttk.Frame):
    def __init__(self, master, *, on_change: Callable[[], None], on_reset: Callable[[], None]) -> None
    summary_var: tk.StringVar
    change_button: ttk.Button                      # text "Change" / "Hide"
    reset_button: ttk.Button                       # text "Reset to suggested"
    notes_var: tk.StringVar                        # replaced-pin notes and smoothing warning
    def set_summary(self, parts: Sequence[str]) -> None    # joined with " · ", empty parts dropped
    def set_notes(self, notes: Sequence[str]) -> None

class PinTracker:
    def __init__(self) -> None
    pinned: set[str]
    def watch(self, field: str, variable: tk.Variable) -> None   # a write pins the field
    def applying(self) -> ContextManager[None]                   # writes inside do not pin
    def pin_all(self, fields: Iterable[str]) -> None
    def clear(self) -> None
```

- [ ] **Step 1: Failing tests** (`pytestmark = pytest.mark.gui`, `tk_root` fixture):

```python
def test_selector_lists_four_tasks_and_reverts_on_refusal(tk_root):
    calls = []
    sel = WorkflowTaskSelector(tk_root, on_select=lambda t: calls.append(t) or t != "batch")
    assert list(sel.buttons) == ["animate", "follow_clip", "sequence", "batch"]
    sel.set_task("animate"); sel.buttons["batch"].invoke()
    assert calls == ["batch"] and sel.task_var.get() == "animate"

def test_unavailable_task_is_disabled_with_its_reason(tk_root):
    sel = WorkflowTaskSelector(tk_root, on_select=lambda t: True)
    sel.set_availability({"follow_clip": "No installed workflow supports this."})
    assert str(sel.buttons["follow_clip"].cget("state")) == "disabled"

def test_summary_line_joins_and_drops_empty_parts(tk_root):
    line = SuggestedSettingsLine(tk_root, on_change=lambda: None, on_reset=lambda: None)
    line.set_summary(["Engine X", "", "3.4 s", "smoothed"])
    assert line.summary_var.get() == "Engine X · 3.4 s · smoothed"

def test_pin_tracker_pins_operator_writes_only(tk_root):
    var = tk.StringVar(master=tk_root); pins = PinTracker(); pins.watch("seed", var)
    with pins.applying(): var.set("1")
    assert pins.pinned == set()
    var.set("2"); assert pins.pinned == {"seed"}
    pins.clear(); assert pins.pinned == set()
```

- [ ] **Step 2: Run** `python -m pytest tests/gui_v2/test_pr_vid_ux_360_task_first.py -q` — expected: import error.
- [ ] **Step 3: Implement** with the styles the tab already uses (`Panel.TFrame`, `Dark.TRadiobutton` if defined in the theme, else `Dark.TCheckbutton`'s sibling; `Muted.TLabel` for notes) and `attach_tooltip` for task descriptions and disabled reasons.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `feat(gui): task selector, suggested-settings line and pin tracker (PR-VID-UX-360)`.

### Task 5: Re-lay out the tab around the task

**Files:**
- Modify: `src/gui/views/video_workflow_tab_frame_v2.py` (`__init__`, `_build_header`, `_build_body`, `_apply_workflow_capabilities`, `_refresh_workspace_summary`, `_refresh_advanced_status`)
- Test: `tests/gui_v2/test_pr_vid_ux_360_task_first.py`

**Interfaces:**
- Consumes: Tasks 1-4; `controller.rife_available()`.
- Produces on `VideoWorkflowTabFrameV2`:

```python
task_selector: WorkflowTaskSelector
suggested_line: SuggestedSettingsLine
keyframes_section: DisclosureSection   # title "Keyframes and conditioning"; conditioning_section lives inside it
compare_section: DisclosureSection     # title "Compare and evaluate"
details_section: DisclosureSection     # title "Details"
def current_task(self) -> str
def select_task(self, task_id: str, *, pinned_workflow_id: str = "") -> bool
```

Layout decisions (spec section 6):
- Header rows: source row; `task_selector`; action bar (Queue, opt-in, block reason, status); `submission_notice`. `batch_panel`'s strip stays in the header but is gridded only in `batch`.
- Body order: batch table (`batch` only) → prompt → driving-clip row + `motion_library_panel` + `motion_readiness_panel` + `motion_prep_panel` (`follow_clip` only) → `sequence_panel` (`sequence` only) → `suggested_line` → `advanced_section` (now titled "Settings"; it is the editor `suggested_line.change_button` toggles) → `runtime_readiness_strip` → `keyframes_section` → `compare_section` → `details_section` → `recent_outputs_panel`.
- `advanced_section` body holds: Workflow picker (label "Engine") with `workflow_detail_var`, `use_svd_button` row, Length, Motion, Smooth with RIFE, Seed, Negative, `workflow_controls_panel`. Each has a `Muted.TLabel` reason fed from `Suggestion.reason`.
- `keyframes_section` body: end anchor, mid anchors, `conditioning_section`. The section is `grid_remove()`d when `form_visibility` has none of `end_anchor`, `mid_anchors`, `camera_intent`, `depth_conditioning`.
- `compare_section` body: `experiment_panel`, `eval_panel`.
- `details_section` body: `source_summary_label`, `effective_settings_section`, `frozen_plan_button` (moved out of the action bar; still shown only when `form_visibility.frozen_preview`), Output Route, `workflow_help_panel`, `overview_panel`.
- `smooth_var` initial value is `False`; the first `select_task` applies the suggestion.
- `select_task` flow: refuse if `_leave_batch_mode()` refuses when leaving `batch` → `choose_workflow` → set `workflow_var` inside `pins.applying()` → `suggest_settings` → `reconcile` → write values inside `pins.applying()` → show/hide per-task widgets → `suggested_line.set_summary([engine label, length label, motion, "smoothed" if smooth else "", "random seed" if not seed else f"seed {seed}"])` → `set_notes(notes + [smoothing_warning(...)])`.
- Leaving `follow_clip`: clear `pose_video_var`, `_library_binding`, `_library_bound_path`, and call the motion prep session's existing reset.
- Pinned fields watched: `workflow_var` (`FIELD_ENGINE`), `frame_count_var`, `motion_profile_var`, `smooth_var`, `seed_var`; the negative prompt pins on `<KeyRelease>`/`<<Paste>>`/`<<Cut>>`.
- An operator change of `workflow_var` re-runs suggestion and reconcile for the current task and clears the opt-in (existing behaviour in `_refresh_workspace_summary`).
- Auto-open: `keyframes_section` and `advanced_section` open only when they hold a required empty input (replace line 1172's unconditional expand: the driving clip is now outside the disclosure, so only required `operator_controls` text controls trigger it). `set_status("modified", active=True)` on a collapsed section holding non-default values, reusing `_refresh_conditioning_status`'s comparison pattern.

- [ ] **Step 1: Failing tests** (fixture as in `tests/gui_v2/test_pr_vid_ux_313_make_video.py::env`, using `make_app`, `TI2V_ID`, `ANIMATE2_ID`; add `monkeypatch` of `controller.rife_available`):

```python
def test_default_task_is_animate_with_the_recommended_engine(env):
    assert env.tab.current_task() == "animate" and env.tab.workflow_var.get() == TI2V_ID
    assert env.tab.smooth_var.get() is True            # rife_available patched True

def test_default_task_hides_everything_it_does_not_need(env):
    for w in (env.tab.motion_library_panel, env.tab.sequence_panel, env.tab.pose_video_frame):
        assert not w.winfo_manager()
    assert not env.tab.advanced_section.is_expanded()

def test_follow_clip_selects_a_driving_engine_and_shows_its_inputs(env):
    assert env.tab.select_task("follow_clip")
    assert env.tab.workflow_var.get() == ANIMATE2_ID
    assert env.tab.pose_video_frame.winfo_manager() and env.tab.motion_library_panel.winfo_manager()
    assert env.tab.experimental_opt_in_var.get() is False          # Review Focus 1
    assert str(env.tab.queue_workflow_button.cget("state")) == "disabled"

def test_sequence_turns_smoothing_off_and_shows_the_shot_list(env):
    env.tab.select_task("sequence")
    assert env.tab.smooth_var.get() is False and env.tab.sequence_panel.winfo_manager()

def test_operator_edits_survive_a_task_switch(env):
    env.tab.seed_var.set("42"); env.tab.select_task("batch"); env.tab.select_task("animate")
    assert env.tab.seed_var.get() == "42"

def test_reset_to_suggested_clears_pins(env):
    env.tab.smooth_var.set(False); env.tab.suggested_line.reset_button.invoke()
    assert env.tab.smooth_var.get() is True

def test_task_switch_refused_while_a_batch_step_runs(env):           # Review Focus 3
    env.tab.select_task("batch"); env.tab._batch_session.active = True; env.tab._batch_session.busy = True
    assert env.tab.select_task("animate") is False and env.tab.current_task() == "batch"

def test_leaving_follow_clip_drops_driving_state(env, tmp_path):     # Review Focus 5
    env.tab.select_task("follow_clip"); env.tab.pose_video_var.set(str(tmp_path / "m.mp4"))
    env.tab._library_binding = {"sha256": "x"}; env.tab.select_task("animate")
    assert env.tab.pose_video_var.get() == "" and env.tab._library_binding is None
    assert "pose_video_path" not in env.tab.get_video_workflow_state(for_submission=True)

def test_pinned_smoothing_without_rife_is_warned_not_flipped(env_no_rife):   # Review Focus 2
    env_no_rife.tab.smooth_var.set(True); env_no_rife.tab.select_task("animate")
    assert env_no_rife.tab.smooth_var.get() is True
    assert "Smoothing cannot run" in env_no_rife.tab.suggested_line.notes_var.get()

def test_submitted_form_is_unchanged_and_carries_no_task(env):
    form = env.tab.get_video_workflow_state(for_submission=True)
    assert "task" not in form and form["workflow_id"] == TI2V_ID and form["interpolation"] == {"enabled": True}

def test_default_task_fits_the_minimum_window(env):
    env.root.geometry("1280x680"); env.tab.pack(fill="both", expand=True); env.root.update()
    line = env.tab.suggested_line
    assert line.winfo_rooty() + line.winfo_height() <= env.root.winfo_rooty() + 680
```

  If `_batch_session.active`/`busy` are read-only properties, set the underlying session state the way `tests/gui_v2/test_video_workflow_batch_ui.py` does.
- [ ] **Step 2: Run** `python -m pytest tests/gui_v2/test_pr_vid_ux_360_task_first.py -q` — expected: the new tests fail on missing attributes.
- [ ] **Step 3: Implement** per the layout decisions. Move layout-only code for the three new disclosures into small `_build_*` methods so `_build_body` shrinks; do not move logic out of the file beyond that.
- [ ] **Step 4: Run** the new file — pass. Then run `python -m pytest tests/gui_v2 -q -k "video or vid or focused_operator or tab_overview or storyboard"` and record which existing tests fail; they are fixed in Task 7, not here.
- [ ] **Step 5: Commit** `feat(gui): task-first Video Workflow layout with per-task disclosure (PR-VID-UX-360)`.

### Task 6: Saved state and handoffs

**Files:**
- Modify: `src/gui/views/video_workflow_tab_frame_v2.py` (`get_video_workflow_state`, `restore_video_workflow_state`, `apply_make_video_defaults`, `_apply_library_handoff`, `set_source_batch`, `set_source_image_path`)
- Test: `tests/gui_v2/test_pr_vid_ux_360_task_first.py`

**Interfaces:**
- Consumes: `infer_task`, `select_task`, `PinTracker.pin_all`.
- Produces: saved state key `"task"`, present only when `for_submission` is false.

- [ ] **Step 1: Failing tests**

```python
def test_state_round_trip_keeps_task_and_pins_everything(env):
    env.tab.select_task("follow_clip"); env.tab.smooth_var.set(False)
    saved = env.tab.get_video_workflow_state(); assert saved["task"] == "follow_clip"
    env.tab.select_task("animate"); env.tab.restore_video_workflow_state(saved)
    assert env.tab.current_task() == "follow_clip" and env.tab.smooth_var.get() is False
    env.tab.select_task("follow_clip"); assert env.tab.smooth_var.get() is False     # still pinned

def test_old_state_without_task_infers_it(env):
    env.tab.restore_video_workflow_state({"workflow_id": ANIMATE2_ID})
    assert env.tab.current_task() == "follow_clip"

def test_unknown_task_or_workflow_falls_back(env):                    # Review Focus 4
    env.tab.restore_video_workflow_state({"workflow_id": "gone_v9", "task": "nonsense"})
    assert env.tab.current_task() == "animate" and env.tab.workflow_var.get() == TI2V_ID

def test_make_video_selects_animate(env):
    env.tab.select_task("follow_clip"); env.tab.apply_make_video_defaults()
    assert env.tab.current_task() == "animate" and env.tab.workflow_var.get() == TI2V_ID

def test_batch_handoff_selects_batch_and_library_handoff_selects_follow_clip(env, tmp_path):
    env.tab.set_source_batch([str(make_image(tmp_path, "a.png"))]); assert env.tab.current_task() == "batch"
```

  Add the Motion Library half using a `HandoffPlan` built as in `tests/gui_v2/test_pr_vid_motion_lib_353_panel.py`, asserting `current_task() == "follow_clip"` after `_apply_library_handoff`.
- [ ] **Step 2: Run** — expected: failures on `task` key and task selection.
- [ ] **Step 3: Implement.** `restore_video_workflow_state`: resolve the record for the saved workflow id (fall back to `choose_workflow("animate", ...)` when it is not in `_workflow_map`), `select_task(infer_task(record, state.get("task")), pinned_workflow_id=...)`, apply the saved values inside `pins.applying()`, then `pins.pin_all(...)` for every watched field. A state dict that restores smoothing must keep reading `state["interpolation"]` exactly as today. `set_source_image_path` in `batch` task switches to `animate` after `_leave_batch_mode()` succeeds.
- [ ] **Step 4: Run** `python -m pytest tests/gui_v2/test_pr_vid_ux_360_task_first.py -q` — pass.
- [ ] **Step 5: Commit** `feat(gui): persist the video task and select it from handoffs (PR-VID-UX-360)`.

### Task 7: Existing tests, journeys, docs, gate

**Files:**
- Modify: the existing tests recorded in Task 5 Step 4; `tools/operator_journey/golden/vid02.py`, `vid03.py` if they drive moved controls
- Modify: `docs/Subsystems/Video/VIDEO_PIPELINE.md` (section 4), `STATUS.md` (Video paragraph), `docs/research/stablenew-experience/workflows/video-and-motion.md` ("Flows"), `CHANGELOG.md`

- [ ] **Step 1:** For each failing existing test decide: the assertion is about the old layout (update it to the new location, e.g. select the task first, or look in `details_section`) or about behaviour (then the implementation is wrong — fix the implementation, not the test). List each decision in the commit body.
- [ ] **Step 2: Run** `python -m pytest tests/gui_v2 tests/video tests/controller/test_video_workflow_controller.py tests/integration -q -k "video or vid or workflow or storyboard or focused_operator or tab_overview"` — expected: all pass.
- [ ] **Step 3:** Update the three docs: Basic/Advanced description replaced by task selector, Suggested settings, the three disclosures, the smoothing default and its two exceptions, the saved `task` key.
- [ ] **Step 4: Run** `python tools/ci/run_pr_gate.py` and `git diff --check` — expected: gate green, no whitespace errors. If a ratchet baseline moves, it may only go down.
- [ ] **Step 5: Commit** `test,docs: align video GUI tests and docs with the task-first tab (PR-VID-UX-360)`.

## Not covered by this plan

Interactive desktop acceptance (a real window, real Comfy readiness, a real clip) needs an operator run after the gate is green. No push, PR or merge is part of this plan.
