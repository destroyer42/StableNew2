# Operator walkthrough

Start the app (see the README for the interpreter): `python -m stablenew_qt_proto.app`.
Everything is a simulation; nothing is submitted, generated or stored except theme files you
explicitly save. Screenshots referenced below are in `screenshots/qt-ds-01/`.

## 1. Orientation

The header shows **ISOLATED DEMO · NO GPU · NO BACKEND · NO JOBS**. Left navigation has **Create Image**,
**Component Library** and **Edit & Improve**. The **Output Display** button (or Ctrl+3) collapses
the right dock outside Edit.
Shortcuts: Ctrl+1 Create, Ctrl+2 Library, Ctrl+3 Output Display, Alt+Z / Alt+Y undo / redo,
Ctrl+Enter build mock preview, Ctrl+Shift+Enter simulate admission.

## 2. Component Library

**Component Library → Components** is the executable catalog: buttons (secondary / primary / danger /
disabled), inputs, setting fields with lock and reset, notices and chips in four levels, disclosures,
tiles and the result gallery, with the active theme and its fingerprint at the top.

## 3. Theme Studio (Component Library → Theme Studio)

1. **Pick a preset.** *Blue Modern* and *Concept A (reconstructed)* are marked *reference (read-only)*.
   Concept A is a reconstruction from research tokens, **not** verified against Figma.
2. **Edit.** Change a colour (`#RRGGBB`, or *Pick…*), font family/size/weight, spacing and density,
   borders/radius, or *Component state appearance* (which colour role hover/focus/etc. use). The
   first edit of a preset makes an *unsaved user copy*; the preset itself never changes.
3. **Watch the live preview** (right column; on a narrow window use the *Edit values / Live preview
   and diagnostics* toggle). The *Component states* matrix shows Default, Hover, Focus, Pressed and
   Disabled side by side (forced, so you need not hover). An invalid value turns its field red and the
   preview keeps the last valid draft.
4. **Read the contrast diagnostics** — 20 pairs with PASS/FAIL and the ratio needed. The chip
   (also in the toggle bar when narrow) says `CONTRAST · ALL 20 PASS` or `· N FAIL`. While any fail,
   **Apply, Save As and Export are disabled and refused** (`screenshots/qt-ds-01/studio_*_contrast_blocked.png`).
5. **Revert edits** drops edits; **Reset to preset** returns to the shipped values.
6. **Save As…** stores a user theme (confirm an overwrite by pressing Save As again). **Apply to
   prototype** restyles everything and remembers the theme for next launch. **Export…** / **Import…**
   write/read a validated JSON file; import loads an *unsaved draft* and never auto-saves or applies.
7. Close and restart: the applied (saved or reference) theme returns.

Layout of a saved user theme: `design/qt_widgets/user_themes/<slug>.theme.json` (git-ignored).

## 4. Create Image — the mock journey

1. In **Create Image**, start with the **Main prompt** or choose a fixture from **Prompt source**.
   Choosing a pack replaces the working text in one undoable step. The review pane shows whether
   it is modified and unsaved.
2. Open **Prompt details and slots** to name the working draft, edit negative text and slot rows,
   or read the resolved prompt. Write a reference such as **{subject}** in the main prompt.
   Tab leaves the multi-line editor.
3. Choose a **Model fixture** and **Profile fixture** alongside the prompt. Model default and
   Learning-informed both use invented recommendations. Untouched settings follow the new
   recommendation. Locked and manual values are retained where they differ from it. Open
   **Change log** to see what was proposed and what was retained.
4. Review the **Size preset**, steps, CFG, seed and batch count. A field labels its origin.
   **Lock** protects a value across fixture changes, **↺** resets a field, and **Reset unlocked
   settings** returns unlocked values to the recommendation. Expand **Advanced settings** for
   sampler, scheduler and exact dimensions. To resolve an unsupported locked value, choose a
   supported option or reset that field explicitly. A custom size can be unverified without
   being unsupported.
5. Read the effective configuration and fixture issues in **Review & results**. **Build Preview**
   (Ctrl+Enter) checks the draft and shows the display-only snapshot. The chip above the panes
   indicates **NOT BUILT**, **CURRENT · READY**, **BLOCKED** or **STALE**. A change to the draft
   calls for reviewing the current settings and rebuilding a stale preview.
6. Choose **Simulate admission** (Ctrl+Shift+Enter) after reviewing a ready, current Preview.
   The chip changes to **SIMULATED · RECEIPT**, the review pane shows its revision and fixture
   provenance, and the result card shows placeholder tiles. The same preview produces one
   receipt. Editing clears that receipt and keeps the draft editable.
7. Continue editing, or choose **Reset draft** to start from the default fixture. **Undo** and
   **Redo** (Alt+Z and Alt+Y) apply to the in-memory draft.

The Output Display starts collapsed. In a wide Create workspace, drag the handles between the
authoring, settings and review panes to resize them. At compact widths the settings follow the
prompt in the left pane, with review on the right. Preview status and actions stay outside the
scroll areas.

## 5. Comparing layouts

Launch with **--layout scroll** for the vertical comparison. The responsive split is the default.
[Responsive Create design and evidence](RESPONSIVE_CREATE.md) describes the comparison and
links the captures. Use **tools/layout_audit.py** to reproduce the geometry measurements.

## 6. What this walkthrough cannot show

No real model, profile, backend, job, History or Artifacts; no screen-reader behaviour; no real
125/150% display. See [ASSESSMENT](ASSESSMENT.md).
## Edit & Improve

See [the Edit walkthroughs](EDIT_WORKFLOW.md#operator-walkthroughs) for Quick Edit, Masked Edit,
Extend Canvas, Compare and Iterate, and negative/recovery cases. Use **Ctrl+4** to open the workspace.
