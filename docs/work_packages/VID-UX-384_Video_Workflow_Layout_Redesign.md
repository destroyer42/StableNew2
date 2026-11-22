# VID-UX-384 — Video Workflow tab layout redesign (Create / Evaluate, two-pane, media on demand)

Hand-off prompt for a fresh Claude Code or Codex session. Discovery is done; read only the files named here.

## Objective

- **Owner complaint (2026-11-22):** sections are scattered; **Settings is buried** partway down; **Compare and evaluate** is a thin
  collapsed bar you must expand to find *Queue eval suite* / *Build eval report*; the **Motion source readiness image** sits at the
  top and is always visible, even for a prompt-only workflow, with no way to hide it (not even a *Show media* checkbox). "Please
  redesign using current UI/UX best practices."
- **Outcome:** a re-laid-out Video Workflow tab that follows the operator's real flow, keeps the primary action always visible, shows
  settings without hunting, gives evaluation a first-class place, and shows media only when it is relevant and the operator wants it.
- **In scope:** layout, visibility rules, a Show media control, moving existing panels, small new layout modules, test updates, the
  VID-UX-360 design doc and VIDEO_PIPELINE §4 text. **Behavior of every action stays identical** (same controller calls, same NJRs).
- **Explicit exclusions:** no controller/service behavior change; no new video features; no change to the eval panel's internal
  controls (owned by `EVAL-HOME-383`, which replaces its file pickers with dropdowns); no Qt port.

## Execution class and model recommendation

- Execution class: **Standard-high** (large GUI refactor of a 2,325-line view; known architecture; many layout tests).
- Model recommendation: Claude Code **Opus 5.5 High** (design-heavy) or Sonnet 5.5 XHigh; Codex **GPT-6.1 Sol XHigh**.
- Expected usage: about 25M cache-read, 200k output.

## Exact start state and sequencing

- `origin/main` at hand-off `d8ea1c86`; isolated worktree; main's `.venv` interpreter. Branch `gui/vid-ux-384-layout`.
  Record task-start timestamp and session ID.
- **Sequencing:** land after (or rebase onto) `EVAL-HOME-383` — it edits `src/gui/views/video_eval_panel_v2.py` internals; this
  package only re-parents that panel. Never two writers on one checkout.

## Research already done

### Files
- Tab: `src/gui/views/video_workflow_tab_frame_v2.py` (2,325 lines, `VideoWorkflowTabFrameV2(ttk.Frame)`), created by
  `src/gui/main_window_v2.py:407-418`, state restored at :1880. `__init__` → `_build_header()` (L386) + `_build_body()` (L457);
  header = fixed frame at grid row 1; body = `ScrollableFrame` at row 2 (L459) with `body = ttk.Frame(_body_scroll.inner)`.
  `_build_body` (L493-525) calls `_build_task_inputs`, `SuggestedSettingsLine`, `_build_settings_section`, `_build_sequence_panel`,
  runtime strip, `_build_keyframes_section`, `_build_compare_section`, `_build_details_section`, Recent outputs.
- Child panels (`src/gui/views/`): `video_workflow_task_panel_v2.py` (162; `WorkflowTaskSelector`, `SuggestedSettingsLine`,
  `PinTracker`), `video_workflow_motion_readiness_panel_v2.py` (319; `WorkflowMotionReadinessPanel`, LabelFrame),
  `video_workflow_motion_prep_panel_v2.py` (311), `video_workflow_motion_library_panel_v2.py` (833),
  `video_workflow_sequence_panel_v2.py` (397; via `storyboard_panel_actions.py` 363 → `DisclosureSection` "Multi-shot sequence"),
  `video_workflow_batch_panel_v2.py` (444), `video_workflow_runtime_strip_v2.py` (197), `video_workflow_experiment_panel_v2.py` (356),
  `video_eval_panel_v2.py` (209, LabelFrame "Eval suite"), `video_workflow_recent_outputs_panel_v2.py` (247),
  `video_workflow_controls_panel_v2.py` (158).
- Contracts (`src/gui/view_contracts/`): `video_motion_readiness_contract.py` (578), `video_batch_contract.py` (571),
  `video_experiment_contract.py` (404), `video_motion_prep_contract.py` (386), `video_runtime_readiness_contract.py` (214),
  `video_recent_outputs_contract.py` (183), `video_sequence_contract.py` (100), `video_workspace_contract.py` (137).
- Widgets to reuse: `src/gui/widgets/disclosure_section_v2.py` (`DisclosureSection`: `toggle`, `set_expanded`, `is_expanded`,
  `set_status`), `scrollable_frame_v2.py` (`ScrollableFrame`), `media_inspector.py` (743; `MediaInspector` with "Show media"
  `Dark.TCheckbutton` L136-142, `default_shown`, `show_control`, `shown_var`, `image_decoder`, `set_visibility`/`set_eligibility`
  L301-311, `_apply_policy` L663 → `ContentVisibilityResolver`), state `src/gui/view_contracts/media_inspector_contract.py`
  (`MediaInspectorState`), `flow_row_v2.py`, `responsive_wrap_v2.bind_wraplength`, `submission_notice_v2.py`,
  `task_navigation_bar_v2.py`, `expander_v2.py`.

### Current order (as built) — the problem
Fixed header: (1) Source Image entry/Browse/Use Latest Output → (2) Task selector "Make: Animate from a prompt | Follow a driving
clip | Multi-shot sequence | Many images" → (3) action bar (Queue Video Workflow = Primary, Preview Frozen Plan, Preview/Queue Batch,
queue-block reason, status) → (4) submission notice → (5) batch source strip → (6) source summary.
Scroll body: (7) batch table → (8) Prompt → (9) inputs stack: driving video [follow], **Motion source readiness (always shown)**,
Prepare Motion Source + Motion Library [follow] → (10) Multi-shot sequence [sequence] → (11) Settings line (Change / Reset to
suggested) → (12) **Settings editor disclosure, collapsed** (Engine, Motion, Length, Seed, Smooth with RIFE, Negative, workflow
controls, Use native SVD) → (13) runtime readiness strip → (14) Keyframes and conditioning (collapsed) → (15) **Compare and evaluate
(collapsed)**: hidden experiment panel + Eval suite buttons → (16) Details (collapsed): Effective settings, Output Route, help,
tab overview → (17) Recent outputs (MediaInspector).

### Why the readiness image is always shown
- Built in `_build_task_inputs` L589-595, deliberately outside `follow_clip_frame` (comment L547-549; design doc
  `docs/Subsystems/Video/PR-VID-UX-360_Task_First_Video_Workflow_Design.md:117-118` "shows for any engine that declares it, in
  every task"; pinned by `tests/gui_v2/test_pr_vid_ux_360_task_first.py:398`
  `test_source_preview_and_guidance_are_not_tied_to_the_driving_clip_task`). **The owner's request supersedes that decision** —
  update the design doc and that test with the new rule and cite this package.
- `WorkflowMotionReadinessPanel.render()` (L222-229) shows when `source_state != idle or video_state != idle or view.guidance_title`;
  the guidance title is never empty (`src/video/workflow_motion_guidance.py` `_unsupported()` ~L114 → "No motion guidance for this
  workflow"), so it shows for every workflow; the crop image appears once a source is chosen because every Wan spec declares
  `source_preparation`. It renders PNG bytes (`tk.PhotoImage`), and **ignores content visibility** (no `ContentVisibilityResolver`) —
  a policy gap to fix (`docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md:160-173`: application content visibility overrides local Show).
- There is **no T2V workflow**: every workflow is image-to-video (`KNOWN_VIDEO_TASKS = {image_to_video}`,
  `src/video/video_backend_types.py:17`; `source_image` always in `_WORKFLOW_BASE_CONTROLS`, `workflow_contracts.py:35`). The owner's
  "prompt-only workflow" = task **Animate from a prompt** (`TASK_ANIMATE`), which still needs a source image. Hide signals available:
  GUI task (`self._task`; `_adopt_task` L1660 already toggles `follow_clip_frame`/`follow_clip_tools`), `form_visibility["pose_video"]`
  (`src/video/video_workflow_intent.py:139-163`), `motion_readiness["accepts_driving_video"]` and `["source_preparation"] is None`
  (`workflow_motion_guidance.py:449-466`), added per record in `src/controller/video_workflow_controller.py:87,90`. Task rules:
  `src/video/workflow_tasks.py:65-110`.

### Settings and eval specifics
- `SuggestedSettingsLine` (`video_workflow_task_panel_v2.py:76-126`; Change/Hide L99, Reset to suggested L103) at body row 3;
  `on_change=_toggle_settings` (L1800), `on_reset=_reset_to_suggested` (L1809). Editor `advanced_section =
  DisclosureSection(body, title="Settings")` row 4 (L645-765); auto-opens only for a required control or experimental engine (L1373).
- `_build_compare_section` (L878-907): `experiment_panel` hidden (`grid_remove()` L896) until the engine declares operator
  controls; so the section usually holds only `VideoEvalPanel` (wired L898-906). RIFE = `smooth_check` (L724), availability
  `rife_available()`. Movie Clips: Recent outputs "Send to Movie Clips" → `_send_output_to_movie` (L2014) →
  `src/gui/controllers/video_workspace_handoff.py::route_bundle_to_movie_clips`. Batch strip `_sync_batch_strip` (L1684).
- Attribute names that must keep existing (VID-UX-360 plan `docs/work_packages/VID-UX-360_Task_First_Video_Workflow.md` line 22):
  `advanced_section`, `compare_section`, `eval_panel`, `motion_readiness_panel`, … — keep them as attributes even if they become
  views/tabs; add aliases rather than renaming.

### Conventions and constraints
- `docs/Subsystems/GUI/GUI_STYLE_GUIDE.md`: `TOKENS` (`src/gui/ui_tokens.py`, spacing 4/8/12), styles from `design_system_v2`/`theme_v2`,
  **one `Primary.TButton` per surface**, `DisclosureSection` as-is with no fixed heights (§6), always-visible actions in a fixed strip
  outside the scroll body (§4), "Selected" state on expanded disclosures, manual check at **1366x768 and 1920x1080**.
- VID-UX-360 acceptance to keep: at **1280x680** the default task shows source, task selector, Queue, prompt and the Settings line
  without scrolling (now: the settings themselves).
- Audit `docs/audits/2026-10-22_gui_ux_audit_and_tranche.md:20,50` (progressive disclosure; keep simplifications, improve discoverability).
- Controller: the tab reaches `AppController` only via `getattr` (`app_controller.py:4568-4626`); everything else via
  `VideoWorkflowController` (257 lines). `AppController` is exactly at its 4,775-line ceiling — a layout change must add nothing there.
- GUI work stays non-blocking; marshal widget updates to the Tk thread (AGENTS.md §4).

## Design (apply these UX principles; justify deviations in the PR)

Principles: task-first ordering that mirrors the flow (what → from what → how → check → go); primary action always visible;
progressive disclosure for rare controls, **not** for the controls most people change; show status, not machinery (collapse
readiness into a status chip with details on demand); media on demand with a persistent Show media preference; separate *making*
from *evaluating*; consistent section headers; no empty or irrelevant panels; responsive two-pane at desktop widths.

Wireframe (≥ 1280 px wide; below ~1100 px the right pane stacks under the left):

```
┌ Fixed header ───────────────────────────────────────────────────────────────────────────────┐
│ [ Create | Evaluate ]   Make: (Animate from a prompt) (Follow a driving clip) (Multi-shot) (Many images) │
│ Source: [path……………] [Browse] [Use latest]     ● Ready  (status chip: runtime + source readiness)   │
│ [Preview plan]  [ Queue video ]  ← Primary        inline SubmissionNotice / queue-block reason     │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
┌ Create view: left (scroll) ──────────────────────────┐ ┌ right pane (scroll) ─────────────────┐
│ Prompt                                                │ │ ☑ Show media                          │
│ [ multi-line prompt …………………………………… ]                │ │ ┌ Source preview (MediaInspector) ┐  │
│ Settings   Engine ▾  Length ▾  Motion ▾  Seed [ ]     │ │ │  image / crop preview            │  │
│            ☑ Smooth (RIFE)   why these? ⓘ             │ │ └──────────────────────────────────┘  │
│            [Reset to suggested]   ▸ More settings     │ │ Motion source readiness  (only when   │
│               (negative, workflow controls, SVD)       │ │   relevant — see rules)               │
│ ── task-specific (only the active task's section) ── │ │ Recent outputs  (MediaInspector,      │
│   Follow clip: driving video, Prepare, Motion Library │ │   Open / Reveal / Send to Movie Clips)│
│   Multi-shot: Storyboard                              │ └───────────────────────────────────────┘
│   Many images: batch table                            │
│ ▸ Keyframes and conditioning   (only if engine has)   │
│ ▸ Details (effective settings, output route, help)    │
└───────────────────────────────────────────────────────┘
┌ Evaluate view (same tab, header stays) ────────────────────────────────────────────────────────┐
│ Eval plans & runs  (VideoEvalPanel as delivered by EVAL-HOME-383: plan ▾ Queue…, run ▾ Build/Open report) │
│ Compare one control  (experiment panel; empty state explains when it is available)              │
│ Rate & review  (links: open report, ratings status n/m, Operator Site review)                    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Rules:
1. **Create | Evaluate** segmented control in the fixed header (reuse `task_navigation_bar_v2.py` or a `FlowRow` of toggle buttons
   styled per the guide). Evaluate shows `eval_panel` and `experiment_panel` full-width with clear headings and empty states;
   `compare_section` attribute points at the Evaluate container. The Primary button in Evaluate is the eval action; Create's Primary
   is Queue video (one Primary per visible surface). Remember the last view in the tab state restored at `main_window_v2.py:1880`.
2. **Settings visible by default:** replace the line+collapsed editor with an always-visible compact Settings block (Engine, Length,
   Motion, Seed, Smooth) right under the prompt; reasons behind an ⓘ/"why these?" disclosure; rarely changed controls (negative prompt,
   workflow-specific controls, Use native SVD) under **More settings** (`DisclosureSection`, auto-opens for a required control or an
   experimental engine as today, L1373). Keep `advanced_section` (now More settings) and `SuggestedSettingsLine` semantics (Reset to
   suggested, pinned-value tracking via `PinTracker`).
3. **Motion source readiness visibility:** full panel only when the active task is *Follow a driving clip* **or** the selected spec
   `accepts_driving_video` **or** readiness reports a problem/warning; otherwise it collapses into the header status chip ("Source ready
   · 480x832 crop", click → opens the panel in the right pane). The crop image renders only when **Show media** is on **and**
   `ContentVisibilityResolver` allows it (fix the policy gap; reuse `MediaInspectorState` or feed `MediaInspector` through `image_decoder`
   since the panel holds PNG bytes).
4. **Show media:** one tab-level checkbox at the top of the right pane controlling the source preview, readiness crop and Recent outputs
   media (share one `shown_var` across the `MediaInspector`s); default shown; persisted with tab state; application content visibility
   always wins (GUI ownership map L160-173).
5. **Only relevant sections exist on screen:** task-specific sections show only for their task; Keyframes only if the engine declares
   them; runtime strip folds into the status chip (details on click); no empty LabelFrames.
6. **Responsive:** two panes with `grid` weights (left weight 3, right weight 2, right min ~360 px); a `<Configure>` handler switches to
   one column below ~1100 px; text wraps via `bind_wraplength`; the fixed header never scrolls.
7. **Code structure:** do not grow the 2,325-line tab. Extract `video_workflow_layout_v2.py` (pane/view scaffolding + breakpoints),
   `video_workflow_settings_block_v2.py` (settings block), `video_workflow_evaluate_view_v2.py` (Evaluate container), and move the media
   preview wiring into the right-pane module; the tab file should shrink. No new controller code.

## Acceptance criteria

1. At 1280x680 (default task, source chosen): task selector, source, Queue, prompt **and** the Settings block (Engine/Length/Motion/Seed/
   Smooth) are visible without scrolling. Verified at 1366x768 and 1920x1080 by screenshot (attach to PR).
2. Animate-from-a-prompt with a valid source: no motion-readiness panel or crop image is shown; the header chip says ready; clicking it
   reveals details. Follow-a-driving-clip: panel visible in the right pane.
3. Show media off hides every media render in the tab (source preview, crop, Recent outputs) and survives restart; content-visibility
   "hidden" mode hides them regardless of the checkbox (test with the resolver).
4. Evaluate view shows Queue eval / Build report controls immediately (no expand), plus Compare one control with an explanatory empty
   state; switching views never loses form state.
5. Every existing action produces identical controller calls/NJRs (characterization tests stay green or are updated only for parentage).
6. One Primary per visible surface (`tests/gui_v2/test_design_foundation_400.py` green); `AppController` unchanged; tab file line count
   lower than 2,325.
7. Docs updated: `docs/Subsystems/Video/PR-VID-UX-360_Task_First_Video_Workflow_Design.md` (new layout + superseded rule L117-118),
   `docs/Subsystems/Video/VIDEO_PIPELINE.md` §4 layout paragraph (~L189), `docs/CODEX_MAP.md` Comfy row (new modules), `STATUS.md`
   video sentence about the form (edit the line).

## Tests to update / add (all `tests/gui_v2/`)

- `test_pr_vid_ux_360_task_first.py` (disclosures collapsed L128-139, Change/Hide L149-151, readiness placement L398-408 → new rule),
  `test_pr_vid_ux_313_make_video.py:295-322` (`_under` ancestry: eval/experiment under the Evaluate container; prompt/settings
  placement), `test_video_workflow_motion_readiness_ui.py` (hidden-state L501, L515; add Show media + content-visibility cases),
  `test_focused_operator_workspace_110.py:522-600` (status/source summary outside the scroll body; Effective settings in Details),
  `test_workspace_layout_resilience_v2.py:86,195`, `test_video_workflow_tab_frame_v2.py`, `test_video_workflow_batch_ui.py:310-318`
  (batch buttons in `_action_bar`), `test_pr_vid_seq_331a_sequence_ui.py`, `test_storyboard350_ui.py`,
  `test_pr_vid_motion_lib_353_panel.py`, `test_pr_vid_ux_311_runtime_strip.py`, `test_pr_vid_ux_314_recent_outputs_panel.py`,
  `test_video_eval_panel_320.py`, `test_design_foundation_400.py`.
- New: breakpoint switch (one/two column), Create/Evaluate persistence, readiness visibility matrix (task × accepts_driving_video ×
  problem), shared Show media var.
- Placement is asserted by ancestry/`winfo_manager()`/`grid_info()`, not row numbers — keep it that way. `tk_root` fixtures skip on
  `TclError` locally; CI runs the census under Xvfb (`.github/workflows/ci.yml:210-221`).

## Token-efficient validation plan

1. `python -m pytest tests/gui_v2 -q -k "video or vid_ux or storyboard or motion or eval or design_foundation or workspace"`.
2. `python tools/ci/run_pr_gate.py` from the isolated worktree (memory: a running app in the main checkout trips collection).
3. Launch the app from the worktree (not the owner's main checkout) for the screenshots; `git diff --check`.

## Stop conditions

- A layout goal needs a controller/service change or a new controller method → stop and report.
- Owner-visible behavior beyond layout (e.g. removing a feature, changing defaults) → stop for owner.
- If EVAL-HOME-383 is not merged, place the existing `VideoEvalPanel` in the Evaluate view unchanged and note the follow-up.

## Completion report

`AGENTS.md` §8 (implementation, demonstration = tests + screenshots, qualification N/A, held = owner live-app acceptance).
`Model / usage` line. Feature-branch commits; publish only with owner authorization.
