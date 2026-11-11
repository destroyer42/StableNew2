# PR-VID-UX-360: Task-first Video Workflow tab (design)

Date: 2026-11-09. Status: **design reviewed by the owner on 2026-11-09** (smoothing on by default; Motion Library
only in the driving-clip task; restored state pinned). Base: `main` at `5348745f`.
Scope: the Video Workflow tab only. SVD Img2Vid and Movie Clips are unchanged.

## 1. Problem

The Video Workflow tab has a Basic/Advanced split (PR-VID-UX-313) but is still hard to use:

- The first choice is a workflow name, which asks the operator to know model families.
- Fifteen-plus controls and panels are always visible, including Motion Library, the batch strip, the overview panel,
  Effective settings and "Use native SVD instead".
- One "Advanced options" disclosure holds fourteen unrelated things: anchors, driving video, seed, RIFE, output route,
  negative prompt, motion readiness, motion preparation, conditioning, workflow controls, help, Compare one control,
  the eval kit and the multi-shot sequence.
- Choosing a workflow configures nothing beyond the declared default length.

## 2. Goal and success criteria

The operator says what they want to make; the tab picks the engine, fills the settings and shows only what that task
needs.

- Default task, image already loaded: **3 actions or fewer** to a queued clip (task is preselected, type a prompt, Queue).
- At the main window's minimum size, 1280x680 (`window_layout_contract.PREFERRED_MIN_WIDTH/HEIGHT`), the default
  task shows source, task selector, Queue, prompt and the Suggested settings line without scrolling. Disclosures and
  Recent outputs may scroll.
- Every automatic choice is visible, carries a one-line reason and can be overridden.
- No change to what is submitted for the same operator choices: the form state, NJR, admission and replay are unchanged.

## 3. Non-goals

- No change to `VideoWorkflowNjrBuilder`, the compiler, admission, the queue, governance or the catalog specs.
- No new tuning numbers. Suggestions use only values the catalog already declares and rules already shipped.
- No automatic consent and no silent routing. An experimental engine still needs the operator to choose it in the
  Engine picker for this job (the picker's selection event is the consent; choosing a task is not).
- No merging of SVD or Movie Clips into this tab. "Use native SVD instead" moves into the engine chooser.
- No AI-assisted workflow choice (`AI_ASSIST` section 10 stays as is).

## 4. Tasks

A task is an operator intent. It is not persisted in a job and never reaches the NJR.

| Task id | Label | Eligible engines (from the workflow record) | Inputs shown |
|---|---|---|---|
| `animate` | Animate from a prompt | `form_visibility.pose_video` is false | prompt |
| `follow_clip` | Follow a driving clip | `form_visibility.pose_video` is true | prompt, driving clip, Motion Library, motion readiness, Prepare Motion Source |
| `sequence` | Multi-shot sequence | same as `animate`, and `form_visibility.frame_count` is true | shot list (existing sequence panel) |
| `batch` | Many images | same as `animate` | batch source table (existing batch panel) |

Engine choice within a task, in order:

1. The operator's pinned engine, if it is eligible for the task.
2. The first eligible engine that is `approved` and not experimental (catalog order, the rule
   `workflow_picker.recommended_workflow_id` already uses).
3. Otherwise the first eligible engine without an `admission_block_reason`. It is experimental, so the Settings editor
   opens with the picker and Queue stays disabled until the operator chooses it there.
4. Otherwise the first eligible engine, with its block reason shown. If none is eligible the task is listed disabled
   with "No installed workflow supports this."

Nothing in this logic names a workflow or a model.

## 5. Suggested settings

Computed by a pure function from the selected task and the engine's record. Each suggestion is `(field, value, reason)`.

| Field | Suggested value | Source |
|---|---|---|
| Engine | per section 4 | governance state and capability projection |
| Length | the declared default | `frame_count.default` |
| Motion | `gentle` (current default), only when the engine declares `motion_profile` | `build_default_form_state` |
| Smooth with RIFE | **on by default** (owner decision 2026-11-09). Off with the reason when RIFE is not found, because admission refuses a smoothing request it cannot resolve. Off in `sequence`, because `video_sequence_controller` refuses smoothing inside a sequence. | `rife_runtime.find_rife_executable()` |
| Seed | blank (random, frozen at submit) | existing behaviour |
| Negative prompt | blank, shown as "engine default applies" when the engine declares one | `default_negative_prompt` |
| Workflow controls | each control's declared default | `operator_controls` |
| Fixed settings | listed read-only | `operator_projection.fixed_settings` |

**Pinning.** A field the operator edits is pinned. Changing task or engine re-suggests only unpinned fields. A pinned
value that the new engine cannot accept (for example a length it does not offer) is replaced by the suggestion and the
summary line says so. "Reset to suggested" clears all pins. Pins are session state and are not saved.

**Smoothing default.** Today `smooth_var` defaults to off. With this change it defaults to on wherever the table above
allows it. A restored saved state is pinned (section 8), so a saved "off" stays off until the operator changes it or
uses "Reset to suggested".

## 6. Layout

Fixed header (never scrolls):

1. Source image: path, Browse, Use Latest Output.
2. Task selector: four radio-style buttons in one row.
3. Queue button, Preview Frozen Plan, the block reason with its fix
   action, status, the submission notice, the batch strip (`batch` only) and the source summary (what the job
   will read stays in view, the PR-GUI-110 contract).

Scrolling body:

4. Task inputs (section 4).
5. **Suggested settings** line, for example `Wan2.2 TI2V-5B · 3.4 s · gentle · smoothed · random seed`, with **Change**.
   Expanded it shows Engine (the current workflow picker, plus "Use native SVD instead"), Length, Motion, Smooth, Seed,
   Negative and any workflow controls, the reasons as one list above them, and "Reset to suggested". The Engine
   picker lists the engines that can serve the selected task; choosing an engine the tab is given from elsewhere
   (a handoff, a restore) moves the task to match it.
6. Runtime readiness strip (unchanged; shown only when it has something to say).
7. Named disclosures, collapsed:
   - **Keyframes and conditioning**: end and mid anchors, camera, depth, ControlNet. Hidden entirely when the engine
     declares none of them.
   - **Compare and evaluate**: Compare one control, eval kit.
   - **Details**: effective settings, output route, workflow help, tab overview.
8. Recent outputs.

Disclosure rules:

- A disclosure opens itself only when it contains a required input that is empty.
- A collapsed disclosure that hides non-default values shows "modified" in its header (the existing conditioning
  header behaviour, generalised).
- Motion Library and Prepare Motion Source exist only in `follow_clip`. Motion readiness (the exact source crop
  and motion guidance) shows for any engine that declares it, in every task.
- The batch strip and table show in `batch`, in `follow_clip` (many images can share one driving clip), and for as
  long as a batch is in force; the sequence panel only in `sequence`.

## 7. Components

| Unit | Kind | Responsibility |
|---|---|---|
| `src/video/workflow_tasks.py` | new, pure | Task definitions; `eligible_workflows(task, records)`; `choose_workflow(task, records, pinned)`; `suggest_settings(task, record, rife_available)`; `infer_task(record, state)`. No Tk, no I/O. |
| `src/gui/views/video_workflow_task_panel_v2.py` | new | Task selector and the Suggested settings line and editor. Reads and writes the tab's existing Tk variables; owns pin state. |
| `src/gui/views/video_workflow_tab_frame_v2.py` | changed | Layout only: sections 6 and the per-task show/hide. Existing widget attributes (`workflow_combo`, `queue_workflow_button`, `advanced_section`, the panel attributes) keep their names so handoffs and tests keep working; `advanced_section` becomes the Suggested settings editor. |
| `src/controller/video_preflight_controller.py` | changed, small | The controller's read-only readiness mixin adds `rife_available()`, a thin wrapper over `rife_runtime.find_rife_executable()` (the same call the NJR builder uses at admission). No new admission or build path. Controller surface ceilings are not raised: `video_workflow_controller.py` itself is unchanged in size. |

Data flow: workflow records → `workflow_tasks` → task panel sets the existing Tk variables →
`get_video_workflow_state()` (unchanged shape) → controller → NJR builder. The task never leaves the GUI.

## 8. State and compatibility

- Saved tab state gains an optional `task` key. Absent or unknown: `infer_task` picks `follow_clip` when the saved
  engine accepts a driving clip, otherwise `animate`. `sequence` and `batch` are never inferred. A snapshot
  without a task keeps the current task when the saved engine can serve it.
- A saved workflow that is no longer installed is shown as saved under `animate` and is never swapped for
  another engine; choosing a task again picks an installed one.
- `restore_video_workflow_state` treats every restored value as pinned, so a restore never silently changes settings.
- Make Video handoffs call `apply_make_video_defaults` as today; it additionally leaves `follow_clip` and
  `sequence` for `animate`. Use Latest Output and a single-image choice leave `batch`.
- Motion Library "Use as Driving Video" and the Review batch handoff switch to `follow_clip` and `batch` respectively.
- A Storyboard restore (the sequence panel's own, or Job History's "open as Storyboard") selects `sequence`.
- A Review batch handoff received in `follow_clip` keeps that task, its engine and its clip.
- The operator's engine choice is remembered per task for the session, so leaving a task and returning brings it
  back; "Reset to suggested" forgets it.
- Experimental consent (the picker selection) is reset on any engine change, including a task's own, and never restored.

## 9. Errors and edge cases

- Engine blocked by policy or readiness: Queue disabled, reason inline, "Fix setup" where the readiness strip offers it.
- Switching task while a batch step is running is refused with the existing message (`_leave_batch_mode`).
- Switching away from `follow_clip` clears the driving-clip field, as a workflow change does today.
- Workflow records fail to load: the task selector is disabled and the status line says why.

## 10. Testing

- `tests/video/test_workflow_tasks.py`: eligibility per task; engine choice order including pinned, approved,
  experimental-only and all-blocked; suggestions and reasons; pin replacement when a value is illegal; `infer_task`.
  Uses plain record dicts; asserts no workflow or model name is referenced by the module.
- `tests/gui_v2/test_pr_vid_ux_360_task_first.py`: per-task visibility; default-task action count; pinning survives a
  task switch; "Reset to suggested"; state round-trip with and without `task`; handoffs select the right task; experimental
  consent only from the picker, never from a task choice; submitted state for unchanged choices equals today's.
- Existing video GUI tests updated only where they assert the old layout. Controller and architecture ratchets unchanged.
- Not covered by tests: interactive Tk acceptance on the desktop, which needs an operator run.

## 11. Risks

- `codex/vid-ux-workflow-runtime` (`499ae3c7`, unmerged) edits the same tab file and six of its GUI tests. Whichever
  lands second rebases; this design does not depend on it.
- The tab file is 1,757 lines; moving layout out of it is part of the work, not a separate refactor.
- Hiding Motion Library outside `follow_clip` removes a browse-only use. It stays reachable by choosing that task.

## 12. Docs impact when this lands

`VIDEO_PIPELINE.md` section 4 (operator surface), `STATUS.md` video capability line, and the W4 research note's
"Flows" entry.
