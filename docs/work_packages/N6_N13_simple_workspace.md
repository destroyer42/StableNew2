# N6 + N13: simple Generate workspace and video picker hygiene

Status: implemented on branch `claude/n6-n13-simple-workspace` (2026-11-26), not pushed. Way Forward items N6 and
N13. The owner's top unaddressed desktop pain is "too many settings and tabs".

## Objective

- **N6 outcome.** The window opens on a simple **Generate** workspace:
  - the Packs × Models batch builder (N5, PR #451), embedded instead of behind a dialog;
  - the Queue;
  - Recent outputs.

  An **Advanced** switch on the navigation bar shows every other tab and option exactly as today. The switch
  persists. Nothing is deleted, disabled or refused (warn, don't block, `AGENTS.md` section 2).
- **N13 outcome.** The Video Workflow engine picker:
  - no longer offers Wan-Animate-2 prompt mode;
  - shows unrated speed arms and superseded workflow arms only behind a **Show experimental** switch.
- **Why.** Owner interview 2026-11-25: queue packs × models, walk away, review on the phone. The desktop's pains are
  too many settings and tabs, and mixing packs × models. Usage shows 0 experiments of four Learning study types and an
  unused Discovered inbox (see Evidence). Wan-Animate-2 prompt mode failed 31 of 31 runs.
- **In scope:**
  - a Tk-free workspace-mode contract;
  - the Generate tab;
  - an embeddable batch builder panel, with the N5 dialog kept and hosting the same panel;
  - the Advanced switch on the navigation bar;
  - the Learning tab's simple presentation;
  - the picker tiers and a Show experimental switch;
  - tests.
- **Explicit exclusions:**
  - No tab, panel, study, workflow or stored record is deleted or retired from the catalog. Wan-Animate-2 prompt
    mode stays registered, so stored jobs replay and a restored or handed-off form that names it still works.
  - No change to the queue, submission, NJR, admission, replay or history paths.
  - No new controller code. `app_controller.py`, `pipeline_controller.py` and `job_service.py` are untouched.
  - The phone gateway's video list, the eval editor's version list and Learning's What Should I Test Next? summary
    are unchanged.
  - V1 (motion controls) builds on the Show experimental switch; it does not change here.

## Execution class and model recommendation

- Execution class: **Standard**. It is presentation-only work over the existing notebook, navigation contract, N5
  service and picker. No runtime ownership, data or admission change.
- Model recommendation: Claude Code Opus-class at moderate effort; Codex GPT-5-class at medium.
- Execution location: local worktree; GUI tests run hidden under `tools/ci/quiet_run.py`.

## Exact start state and authorities

- Task start: 2026-11-26T23:56:36Z. Subagent of orchestrator session 3d36ca46.
- Branch `claude/n6-n13-simple-workspace` on `main` dbbd1e87 (N5 merged as #451).
- Authorities:
  - `AGENTS.md` sections 2, 4 and 6;
  - `STATUS.md`;
  - `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md` (task navigation, rules 8 and 9 on hot surfaces);
  - `docs/work_packages/N5_batch_builder.md`;
  - `docs/work_packages/V1_motion_controls.md` section 5.10, which says what moves behind Show experimental.

## Evidence (read-only, the owner's live data, 2026-11-26)

These counts come from read-only `grep` over `StableNew-main/data/learning`. Nothing there was opened for writing.

- **Learning experiments** (67 saved):
  - Controlled Variable: 23;
  - LoRA Composition: 29;
  - Model Comparison: 11;
  - Compatibility Probe: 3;
  - one with no study type;
  - **Prompt Slot, Embedding, Two-Axis Grid and Prompt x Model Matrix: 0 each.**
- **Discovered inbox:** 834 groups, almost all created by the output scan. 831 are waiting for review,
  2 are in review and 1 is closed. (Corrected 2026-11-27: the scan is not automatic. See owner question 5.)
- **Wan-Animate-2 prompt mode:** 31 of 31 runs failed (the owner's figure, relayed by the orchestrator; not
  re-counted, because the job database belongs to the live app).

## Survey

### Tabs today (`src/gui/main_window_v2.py`)

- Ten tabs live in one `ttk.Notebook`. Their creation order is `LEGACY_TAB_ORDER`.
- `TaskNavigationBar` (PR-GUI-410) shows them in five groups and hides the native tab strip:
  - Create: Prompt, Pipeline;
  - Edit: Review, Photo Optimize;
  - Motion: Video Workflow, Storyboard, SVD Img2Vid, Movie Clips;
  - Learn: Learning;
  - Advanced: Character Training (HOLD).
- The Learning tab has its own notebook: Designed Experiments, Discovered Outputs and Staged Curation.
- Designed Experiments lists eight studies under five objectives (LEARN-NAV-871).

### Video picker today

- `VideoWorkflowController.list_workflow_specs` returns one version per workflow id, the newest approved one when
  there is one (`latest_spec_per_workflow`). That is ten entries.
- `workflow_tasks.eligible_workflows` narrows them to the selected task.
- Every experimental entry is offered: HunyuanVideo 1.5 8-step and 12-step, A14B CK attention, A14B SVI, Fun Control
  5B Canny 1.1.0, Wan-Animate-2 Driving Video 1.2.0 and Wan-Animate-2 prompt mode 1.2.0.

## Design

### Default layout (Simple)

| Group | Simple (default) | Advanced adds |
|---|---|---|
| Create | **Generate** | Prompt, Pipeline |
| Edit | Review | Photo Optimize |
| Motion | Video Workflow, Storyboard | SVD Img2Vid, Movie Clips |
| Learn | Learning (simple presentation) | the hidden studies and Discovered Outputs |
| Advanced | not shown | Character Training (HOLD) |

- **Startup.** The window opens on the stored tab when it is visible in the current mode. Otherwise it opens on
  Generate in Simple mode and on Pipeline in Advanced mode. That is today's rule with a mode-specific fallback.
- **Advanced.** It shows exactly today's groups, destinations, labels and order. The one addition is Generate, listed
  first under Create, so switching modes never moves the operator off the tab they are on.
- **The switch.** It is a checkbutton, **Advanced**, right after the group buttons on the navigation bar, so a narrow window never clips it. It is persisted as
  `workspace.mode` (`simple` or `advanced`) in the UI state file. It is written when toggled and again on close. A
  missing or unknown value means Simple.
- **Nothing blocked.** Hidden tabs are still built, registered and selectable. A handoff (Make Video, Send to Movie
  Clips, View in queue, Edit in Review) or Ctrl+Tab that selects a hidden tab shows it, and the navigation bar shows
  it in its group until the operator leaves it. Hiding only removes navigation buttons.
- **SVD.** The SVD tab is folded under Video, not merged into it. In Simple mode it is no longer a separate
  destination; Advanced shows it as today. Native SVD XT stays a production backend and every handoff to it works.
  A link inside the Video Workflow tab is an owner question (below).

### Generate tab (`src/gui/views/generate_tab_frame_v2.py`)

- **Left column: "Packs × Models batch".** This is the N5 builder as an embedded `BatchBuilderPanel`:
  - pack list, model list, ADetailer, Upscale and Use each model's saved recipe;
  - batch name, Plan, the exact summary and Queue batch.

  The packs, models and stage toggles are re-read from the Pipeline tab's PromptPack card, which is the same source
  the dialog reads. This happens each time the tab is shown, when WebUI resources change while it is shown, and on
  **Refresh lists**. It is an in-memory read. A selection the operator already made is kept where the names still
  exist, and an unchanged list keeps the current plan.
- **Right column.** Queue (`QueuePanelV2`, with its pause and auto-run controls) on top; **Recent outputs**
  (`JobHistoryPanelV2`) below.
- **Hot surfaces.** The tab owns these, like the Pipeline shell (ownership map rules 8 and 9). The panels are mounted
  with `manage_app_state_subscriptions=False`. The tab subscribes to the queue and history keys, marks a surface
  dirty, and refreshes it only while it is mapped; hidden surfaces refresh when they map.
- **Background work.** Planning and Queue run through `pack_model_batch_service` background tasks, unchanged. Nothing
  compiles, reads packs or touches files on the Tk thread.

### Batch builder refactor (`src/gui/batch_builder_dialog.py`)

- `BatchBuilderPanel(ttk.Frame)` holds the widgets and the plan and queue logic.
- `BatchBuilderDialog(tk.Toplevel)` hosts one panel. The Pipeline tab's **Packs × Models…** button keeps opening it.
- The pure helpers `batch_sources(sidebar)` and `batch_callbacks(controller_provider)` are shared by the dialog and
  the Generate tab.

### Learning simple presentation

- `LearningTabFrame.set_simple_workspace(simple)` hides the **Discovered Outputs** view with the notebook's own
  `hidden` tab state, and restores it unchanged.
- It also hides four study entries from the objective chooser: Prompt Slot, Embedding, Two-Axis Grid and Prompt x
  Model Matrix. It hides the "More comparisons" heading, which then has nothing left under it.
- A hidden study that is currently selected, for example a restored draft, stays shown.
- Saved experiments of every type still open, run and rate.

### N13 picker tiers (`src/video/workflow_picker.py`)

Each tier is data with a reason, keyed by workflow id. The picker is a presentation choice; the catalog, its
governance and the specs are unchanged.

| Tier | Workflows | Picker |
|---|---|---|
| default | approved engines; Wan-Animate-2 Driving Video 1.2.0 and Fun Control 5B Canny 1.1.0, the only engines for Follow a driving clip | always offered |
| experimental only | A14B CK attention (unrated speed arm), A14B SVI (unrated arm), HunyuanVideo 1.5 8-step and 12-step (unrated candidate arms) | only with **Show experimental** |
| retired from the picker | Wan-Animate-2 prompt mode (`wan_animate2_prompt_i2v_v1`; failed 31 of 31 runs) | never offered |

- Superseded versions of a workflow id are already never offered: one version per id. That stays true, and the
  tiers cover the superseded alternative arms that have their own ids.
- The selected engine is always offered, even when its tier is hidden, so a restored form, a handoff or a stored
  job's replay never loses its engine. Task availability counts only offered engines.
- **Show experimental** sits beside **Why these settings?**. It is off by default and saved with the Video Workflow
  form state, like **Show media**.

## Controller Surface Assessment

- No file under `src/controller/` changes.
- The Generate tab reaches the N5 service the way the dialog does, through the sidebar's controller.
- The ratchet ceilings are unchanged.

## Acceptance and evidence reuse

- Required behaviour:
  1. A fresh UI state opens on Generate. The bar shows Create, Edit, Motion and Learn with the Simple destinations.
  2. Turning Advanced on shows today's destinations, plus Generate. The choice survives a restart.
  3. Hidden tabs stay registered, and a handoff to one selects it and shows it on the bar.
  4. The Generate tab plans and queues through the N5 service callbacks and shows the Queue and Recent outputs.
     Hidden surfaces defer their refresh.
  5. Simple Learning hides Discovered Outputs and the four zero-use studies; Advanced restores them.
  6. The picker never offers Animate-2 prompt mode, and offers the arms only with Show experimental. The selected
     engine stays offered.
- Evidence mode: deterministic tests. The contract and picker tests are pure; the Tk tests use the shared hidden
  root and the GUI harness. Physical runtime: NOT RUN (the owner's live app runs from `StableNew-main`).
- Qualification claim: N/A.

## Token-Efficient Validation Plan

1. Run the focused contract and picker tests, then the GUI tests for navigation, the Generate tab, Learning and the
   video tab, alone.
2. Run `tests/gui_v2` and `tests/video` alone.
3. Run `python tools/ci/run_pr_gate.py`, `tests/system`, `tests/tools/test_code_map.py`, the ruff ratchets and the
   mypy ratchet.
4. Run `git diff --check`.

## Stop conditions

- A change would need a controller ceiling raised.
- A change would need a change to a catalog spec, which is pinned byte for byte.
- A change would hide something that cannot be reached any other way.

## Owner questions (defaults chosen; each is one line to reverse)

1. **Simple tab set.** Simple shows Generate, Review, Video Workflow, Storyboard and Learning. Prompt (pack
   authoring), Pipeline (settings for models without a recipe), Photo Optimize, Movie Clips and SVD are Advanced
   only. Should any of them be in Simple?
2. **Generate in Advanced.** Generate is listed in Advanced too, so switching modes never moves you off your tab.
   Should Advanced be exactly today's tabs, without Generate?
3. **SVD.** Is a link from Video Workflow to the native SVD tab wanted, or is Advanced enough?
4. **Prompt mode.** V1 section 5.10 put Animate-2 prompt mode behind Show experimental. This package retires it from
   the picker entirely, as N13 asked. Should it come back behind Show experimental instead?
5. **Discovered inbox.** Answered 2026-11-27: "Stop scan, keep groups". The groups are kept. This package wrongly
   said an automatic scan still ran: only the Rescan and Rebuild buttons call it, so no code had to change. The
   scan-created groups in the owner's workspace date from two runs (102 on 2026-10-27, 689 on 2026-11-08).

## Documentation impact

- `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md`: Generate tab, workspace mode and the tab set.
- `docs/Subsystems/Video/VIDEO_PIPELINE.md`: picker tiers.
- `docs/CODE_MAP.md`: regenerated.
- `STATUS.md`: one line once merged.
