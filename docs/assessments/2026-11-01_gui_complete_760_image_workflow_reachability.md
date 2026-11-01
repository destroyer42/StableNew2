# GUI-COMPLETE-760 — primary image workflow reachability

Evidence collected **2026-11-01** on one Windows 11 host (2560×1440 monitor at 100%, CPython 3.14, Tk 9.0.4). Builds on GUI-100, GUI-110 and GUI-420.
This is a presentation-only repair: no controller, queue, repository, runner, compiler, dispatcher, runtime or persistence change.

| Verdict | Result |
|---|---|
| **Outcome** | **PASS** for the exit criterion: zero unreachable mandatory controls in Prompt, Pipeline, Review and Photo Optimize at every qualified window size, by wheel-reveal and by keyboard focus |
| Before | 62 unique controls unreachable at the qualified sizes (Prompt 7, Pipeline 54, Review 1) |
| After | 0 |

## What was measured

`tests/helpers/reachability_760.py` walks the live widget tree of a tab (every page of every nested notebook, collapsed and with every
disclosure expanded) and, for each actionable control that is logically shown, checks that it can be brought fully inside every clipping
ancestor. Two independent reachability paths are used, the same ones an operator has:

- **Scroll**: `ScrollableFrame.reveal` for each scroll frame above the control (what the shared wheel router and focus handler use).
- **Keyboard**: `focus_force`, relying on the router's `<FocusIn>` reveal; a control that cannot take focus is `focus_failed`.

Severity: *blocking* = unmapped, focus-unreachable, or less than half visible; *degraded* = operable but partly clipped, or taller than its
whole scroll viewport with its top reachable. Geometry does not depend on enabled state (Job History actions enable on selection). The probe
never activates a control (no clicks or commands); keyboard mode moves focus, which can run the control's own focus-out handler. Window size is applied after application start (the app's saved-geometry restore otherwise overrides it) and the
realized client size is recorded.

| Window | Realized client | Tk scaling | Label |
|---|---|---|---|
| 1366×768 default | 1342×680 | 1.334 | actual 100%; the host clamps the minimum height to 680, so the requested 672 was not realized |
| 1366×768 minimum | 1280×680 | 1.334 | actual 100% |
| 1366×768 at 150% | 1342×680 | 2.002 | **simulated**: Tk scaling raised 1.5×, not a Windows DPI change |
| 1920×1080 default / minimum | 1896×984 / 1280×680 | 1.334 | actual 100% |
| 1920×1080 at 150% | 1896×984 | 2.002 | **simulated** |
| 2560×1440 default / maximized | 1900×1000 / 2560×1369 | 1.334 | actual 100% |

The 8-window matrix runner was a scratch harness and is **not committed**; the committed journey tests cover the minimum window and the simulated 150% window on Prompt, Pipeline and Review (blocking findings only; Photo Optimize is covered by its GUI-420 tests). Compact evidence for all 8 windows × 4 tabs × (collapsed, expanded) × (scroll, keyboard):
[`reachability_matrix.json`](evidence/gui_complete_760/reachability_matrix.json). Real 125%/150%/175% Windows DPI was **not** run
(it needs a display-setting change, which is out of scope); the simulated rows are labelled as such everywhere.

## Reproduction matrix and root causes

| # | Finding (before) | Classification | Root cause | Fix |
|---|---|---|---|---|
| P1 | Job History actions (Open Output Folder, Iterate, Animate with SVD, Make Video, Movie Clips, Explain Job, Review Experiment, Browse All…) unmapped on the Pipeline right column at 1280–1896 px and on every window except maximized; 8 `focus_failed` | **Confirmed blocking** | Single `pack(side="left")` action bar. Tk leaves the children that do not fit the column unmapped, so they are neither visible nor focusable | `FlowRow` (new, `src/gui/widgets/flow_row_v2.py`): same children, `place`d on as many rows as the width needs, own height; coalesced reflow; reversible |
| P2 | Output Settings Seed Mode / Route comboboxes hidden or clipped (Pipeline sidebar) | **Confirmed blocking** | Same single-row `pack` | Format/Batch/Seed/Route pairs in a `FlowRow` |
| P3 | Pipeline controls partly clipped at 1280–2560 px (batch-operations filters and actions, other grids) while the fit-driven layout reported "fits" | **Confirmed degraded** | `measure_horizontal_extent` used each control's own right edge and ignored an intermediate container narrower than the control, so a clipped control counted as fitting | Overrun of the tightest ancestor is added to the control's right edge (`layout_v2.py`); the fit-driven compact decision now sees the clip. Observed in an intermediate run (not committed): with this change reverted and the rest kept, 9 degraded Pipeline clips at 1896×984 and 1900×1000 returned; with it, none. The unit test guards the rule |
| P4 | Batch Operations filter/failure combos and Open Output Folder clipped | **Confirmed degraded/blocking at 150%** | Fixed grid row | Filters and actions in `FlowRow`s |
| P5 | Prompt: Add Slot / Copy / Delete, Adapt for Target…, Suggest…, Matrix Add example unreachable at 1342 px at 150% (simulated); ControlNet OpenPose strength/guidance/mode controls clipped | **Confirmed blocking (simulated 150%)** | Slot buttons were vertically squeezed out by a fixed-height pack list (8 rows) above the expanding slot list; the editor header and the matrix and OpenPose option rows were single packed/grid rows | Pack and slot lists ask for few rows and expand with the column, slot actions in a `FlowRow`; header, matrix and OpenPose option rows in `FlowRow`s |
| P6 | Review: "?" (batch help) unreachable at 150% (simulated) | **Confirmed blocking (simulated 150%)** | Single-row pack | Batch row in a `FlowRow` |
| — | Review image list taller than the whole scroll viewport (its top is reachable; the list is a self-scrolling widget); Photo Optimize list the same at 150% | **Confirmed degraded, not repaired** | Preview column fixes a 620 px pane; GUI-100 documented this density | Left as a design decision (see below) |
| — | Prompt editor Text partly clipped and matrix Text taller than the viewport at 150% on 1342×680 | **Confirmed degraded, not repaired** | Fixed-height text panes at an extreme size | Scrollable; left as density debt |
| — | Pipeline combobox clipped by a few px at 150% on 1342×680 | **Degraded, residual** | Operable | Not repaired |
| — | Prompt, Photo Optimize at 100% | **No defect** | GUI-420 holds | none |

`FlowRow` owns no value, command or state and holds no controller reference; children keep their identity, variables, bindings and commands.
A width change re-flows synchronously (the fit-driven Pipeline layout resizes columns and measures straight after `update_idletasks`); child size
changes re-flow after the 60 ms coalescing delay.

**Visible layout changes (intentional, presentation only):** Job History *Refresh History* is now the last item of the wrapping action row instead
of right-aligned; the Prompt header banner follows Adapt/Suggest in the flow instead of sitting at the right edge; Add Slot / Copy / Delete keep
their natural width instead of equal expanding widths; the Prompt pack list and slot list request 3 and 4 rows (was 8 and 10) and both expand,
so in a tall column the spare height is shared instead of all going to the slot list. The *Browse All…* window subclasses the Job History panel and
inherits the wrapping action row.

## Behaviors verified

| Behavior | Evidence |
|---|---|
| Reachable actions, wheel/scroll | matrix (scroll mode, 8 windows × 4 tabs × 2 disclosure states), `test_primary_image_journey_has_no_unreachable_control` (min window and 150% simulated) |
| Keyboard | matrix (keyboard mode, same cells); `test_pipeline_keyboard_focus_reaches_every_control_at_the_minimum_window` |
| Narrow → wide → narrow | `test_flow_row_reflow_is_reversible_and_does_not_oscillate`; `test_resizing_narrow_wide_narrow_keeps_state_and_layout_stable` (rows return to the same count, no oscillation once settled, selected tab never moves). The existing fit-driven Pipeline layout tests still pass |
| Order and visibility of conditional actions | `test_flow_row_set_shown_keeps_order_and_unplaces_hidden_children`; sequence Resume/Replay stay ordered and Refresh stays last (`test_pr_vid_seq_331a_sequence_ui`) |
| Synchronous wrap, no stale job after destroy, child-size self-scheduling | `test_flow_row_wraps_synchronously_when_its_width_changes`, `test_flow_row_manual_reflow_leaves_no_stale_job_after_destroy`, `test_flow_row_self_schedules_after_a_child_changes_size` |
| Fit decision sees a clipped control | `test_extent_counts_a_control_clipped_by_a_narrower_container` |
| State and execution | Output Settings values and overrides round-trip across wrapping; `FlowRow` only moves widgets; no job admission, queue, runner or backend call is involved |
| Single wheel router | untouched; no `bind_all` added |
| Thread discipline | reflow is a Tk `after` callback on the GUI thread only |

## Test results and a pre-existing order dependency

The focused GUI set (52 test files that construct a converted panel, plus `test_pipeline_layout_scroll_v2`, `test_photo_optimize_layout_420`,
`test_task_navigation_shell_410`, `test_workspace_layout_resilience_v2`, `test_pipeline_view_contracts`, `test_gui_reachability_250` and the new
file) gives 919 passed, 3 failed in one pytest process. The same three Photo Optimize tests
(`test_selection_summary_names_single_photo_and_batch`, `test_resize_round_trip_keeps_selection_text_and_widgets`,
`test_archive_restore_and_toggles_survive_layout_changes`) fail identically on the unmodified base `11cebada` in the same file order (906 passed,
3 failed there) and pass when `test_photo_optimize_layout_420.py` runs alone (26 passed) or with the new file (39 passed). They are a pre-existing
cross-test ordering dependency in that file's state, not caused by this change; Photo Optimize source is untouched.

## Remaining independent GUI issues (not started)

0. `test_photo_optimize_layout_420.py` is order-dependent (above); worth its own small package.


1. Review image list / preview density: the 620 px preview pane makes the image list taller than a 680 px client (degraded at every size). Needs a layout decision, not a defect fix.
2. Prompt editor and matrix text panes at 150% on a 1342×680 client (degraded).
3. Real Windows 125/150/175% DPI has not been run; only simulated Tk scaling.
4. Motion/Learning/Character Training were not inspected for repair, per scope.

## Recommended next package

GUI-DENSITY-761: decide the Review preview/list split and the fixed-height text panes (a design decision), then run the same probe on real 125%/150% DPI with the owner's display settings.
