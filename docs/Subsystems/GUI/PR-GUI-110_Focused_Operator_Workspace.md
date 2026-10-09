# PR-GUI-110 — Focused Operator Workspace

Status: COMPLETE / ACCEPTED / INTEGRATED (PR #75; hosted `required` and GUI `affected` lanes passed; independent review found no
blocking finding). Follow-up corrections: `PR-GUI-111_Thumbnail_Recovery_and_Tooltip_Correctness.md`.

Builds on PR-GUI-100. Presentation only: no generation, queue, NJR, compiler, JobService, `PipelineRunner.run_njr`, runtime
manager, PromptPack, Learning, reprocess, model, backend or dependency behavior changed. GUI remains intent and projection.

## Execution profile and validation

Standard, bounded GUI presentation package. Recommended: Codex GPT-6.1 Sol Medium / Claude Code Sonnet 5.5 Medium, existing
Windows Local/Desktop session (real Tk and a real display are needed for the measurements). Controller Surface Assessment:
no controller or coordinator file was touched and no ratchet ceiling changed. Token-efficient validation: one baseline
measurement on the starting SHA, one coherent implementation, focused real-Tk tests, one after-measurement under identical
conditions, then the repository PR gate once.

## Root cause (GUI-100 "visual-density debt")

At the simulated 1366 x 768 window (1342 x 680) the usable scroll viewport was only 158 px (Review), 239 px (SVD) and 223 px
(Video Workflow) because fixed chrome sat outside the scroll regions: an expanded 177 px Operator Log + status bar, a wrapped
tab-overview paragraph, a wrapped action-explainer paragraph, and long header text blocks. The SVD and Video Workflow primary
submit buttons were at the bottom of the scrolling form. The Review preview was a fixed 620 px canvas with fixed 620/520 px
label wraps; the Pipeline preview panel gave a fixed 300 px column to a thumbnail that is off by default, so its field labels
were cut off in the compact Pipeline.

## What changed

**A. Shell and diagnostics** (`log_trace_panel_v2.py`). The Operator Log is compact by default: one header row with the
title, `Details`, a warning/error summary and `Crash Bundle`; level filter, auto-scroll and the text area appear on demand
(the Trace Log still starts expanded). Expanding or collapsing never resizes the root window (the old
`_adjust_window_height` is gone). The summary is counted from the same `InMemoryLogHandler` (repeats included, one entry scan
per log version, none when unchanged), is coloured by severity, never hides or auto-dismisses entries, and clicking it opens
the details. The panel now cancels its refresh timers on destroy. The status bar is unchanged and always visible.

**B. Progressive guidance** (`tab_overview_panel_v2.py`, `action_explainer_panel_v2.py`). Collapsed guidance is a single header
row; the summary and details are the disclosed content and are unchanged. `ActionExplainerPanel(summary_when_collapsed=True)`
keeps a safety-critical summary visible (no current guidance needs it). Help Mode still forces everything open. Return
activates the toggle like Space. The manual choice lives on the panel instance, so it survives tab switches and resizes for the
session (no persistence authority). Wraps follow the real width with the old value as a cap.

**C. Responsive Review** (`thumbnail_widget_v2.py`, `review_tab_frame_v2.py`, `responsive_wrap_v2.py`). `ThumbnailWidget(
responsive=True)` treats 620 as a maximum square edge, fits the parent's real width (200..620), preserves aspect ratio,
re-fits once per settled resize (one coalesced job), rescales the already-decoded image instead of decoding again, discards
results from superseded requests, never starts a duplicate decode for a path already in flight, and ignores callbacks after
destroy. Metadata, prior-review, diff, effective-settings and hint labels follow their allotted width
(`bind_wraplength`). The Review feedback sub-scores wrap to two rows so the pane fits at increased Tk scaling.

**D. SVD / Video Workflow primary actions.** `animate_btn` (SVD) and `queue_workflow_button` (Video Workflow) are the same
widgets with the same callbacks and legal enabled states, now in the fixed header above the scrolling form. SVD: next to
`Select Folder...`; the status and admission rows are mapped only when they have something to say (the admission line shows
whenever it blocks or warns and is never scrolled away). Video Workflow: one action row holds the button, the experimental
opt-in checkbox (packed beside the button whenever the selected workflow is experimental) and the status text; the source
summary (source, operation/backend and experimental requirement) stays visible and wraps; the long effective-settings string is a
`DisclosureSection` (collapsed, with a short hint). Advanced Conditioning is a `DisclosureSection`; every control and value
stays alive while collapsed, and the collapsed header says `active: camera=..., depth=...` or `N edited (inactive)` (accented)
when hidden content is non-default, or `not used by this workflow`.

**E. Pipeline readability** (`preview_panel_v2.py`, `tooltip.py`, `pipeline_tab_frame_v2.py`). The preview checkbox moved to the
panel header; the thumbnail column is mapped only while previews are on and stacks under the job info when the measured label
width (from the real font, not a fixed breakpoint) would be squeezed. `install_full_value_tooltips` gives every Pipeline
combobox that cannot show its whole value (model, checkpoint, VAE ...) a hover/focus tooltip with the full value; it is
idempotent and read-only. Focus visibility: `Dark.TButton` and the new `Disclosure*.TButton` styles accent the border on focus.

New shared helpers: `view_contracts/workspace_density_contract.py` (pure sizing/disclosure rules, no Tk),
`widgets/disclosure_section_v2.py`, `widgets/responsive_wrap_v2.py`. No new state authority, wheel router, logging source or
style system. `ScrollableFrame`'s single wheel dispatcher is untouched and no new widget binds the wheel.

## Measured result (non-generating, Windows 11, Tk 9.0.4, 2560 x 1440 display, simulated windows)

`tools/qualification/gui110/measure_workspace.py` builds the real `MainWindowV2` (with the Operator Log) over the fake runner,
isolated from operator state, and was run on the starting SHA `5e104dd8` and on the changed tree under identical conditions.
Usable scroll viewport height at the 1366 x 768 simulation (1342 x 680, Tk scaling 1.0): baseline reproduces the GUI-100 record
exactly.

| Tab | Baseline | After | Gain | Primary action visible without scrolling |
| --- | --- | --- | --- | --- |
| Review | 158 px | 354 px | +196 px (+124%) | n/a (Reprocess stays in the form) |
| SVD Img2Vid | 239 px | 366 px | +127 px (+53%) | no -> yes |
| Video Workflow | 223 px | 336 px | +113 px (+51%) | no -> yes (with the opt-in) |

The gain is >= 80 px and >= 25% in all three tabs at 1280 x 680 and 1342 x 680 (Tk scaling 1.0 and 1.5). At 1896 x 984 and
1900 x 1000 the same chrome savings are +196/+127/+113 px (+21% to +42%). Increased Tk scaling (1.5, applied before the
widgets are built) improves from a Review viewport of 1 px with 11 clipped controls to 233 px with 0, and SVD/Video from
85/59 px to 247-275/207 px. Clipped actionable controls: 0 in every measured condition (baseline: 11 in Review at scaling
1.5). The bottom zone (log + status) shrinks from 177 px to 85 px. Root geometry is unchanged by any log toggle (asserted).
Baseline/after screenshots and the raw JSON were produced with `--screenshots` and are kept with the completion evidence
(not committed).

## Tests

`tests/gui_v2/test_workspace_density_contract_110.py` (pure rules) and `tests/gui_v2/test_focused_operator_workspace_110.py`
(real Tk, run inside a real main loop so worker callbacks land): compact log, log-toggle geometry invariance, severity summary
and timer cleanup, one-row guidance and its full content, safety-summary opt-out, Help Mode and keyboard activation, disclosure
persistence across tab switch/resize, values kept while collapsed, wrap following/cleanup, thumbnail fit bounds / aspect /
no re-decode / stale and post-destroy results / no duplicate decode, Review preview + metadata inside the viewport at laptop and
increased scaling, Review selection across resize, SVD and Video primary actions visible outside the scroll region with one
click -> one existing controller call, the SVD admission blocker and the experimental opt-in always visible and associated,
status/source identity visible, effective-settings disclosure, Advanced Conditioning values and active/edited flags,
full-value comboboxes, and the Preview panel's labels. Four mutations (log starts expanded, stale-result guard removed,
conditioning flag removed, log toggle resizing the window) are each killed. Existing tests updated for the moved controls:
`test_svd_tab_help_sections_use_distinct_rows`, the long-form reachability test (the lowest scrolled control is now the
Recent SVD output action / the Video negative prompt), and the Operator Log content test (opens the details first).

## Residual constraints

- The measurements simulate a 1366 x 768 laptop on a 2560 x 1440 display; no physical laptop panel was used.
- The Review preview is bounded by width, not by viewport height: at 680 px it still scrolls with the form.
- The Operator Log's warning/error summary counts the in-memory buffer (500 entries), not history.
- SVD help/summary/capability labels in the scrolling body keep their fixed 520 px wraps; they cost no viewport.
- Review's Reprocess buttons stay in the scrolling form (the package scoped only SVD/Video submit actions).
- The supplied GUI-110 research report was not present in the repository checkout; scope followed the work package text.
