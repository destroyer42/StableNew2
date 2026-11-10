# Operator walkthrough

Start the app (see the README for the interpreter): `python -m stablenew_qt_proto.app`.
Everything is a simulation; nothing is submitted, generated or stored except theme files you
explicitly save. Screenshots referenced below are in `screenshots/qt-ds-01/`.

## 1. Orientation

The header shows **ISOLATED DEMO · NO GPU · NO BACKEND · NO JOBS**. Left navigation has **Create Image**
and **Component Library**. The **Output Display** button (or Ctrl+3) collapses the right dock.
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

1. **Prompt source:** *Free prompt* or a fixture PromptPack. Choosing a pack replaces the working text
   in one undoable step; editing it afterwards shows *modified, unsaved*.
2. Edit the **Main prompt**; `{slot}` placeholders resolve from the **PromptPack slots** table, and
   the **Resolved prompt** (read-only) shows the result. Tab leaves every editor (it does not insert tabs).
3. **Model** and **settings source:** switch fixtures; unlocked, untouched values follow the new
   recommendation, manual and locked values are kept, and the change log says why.
4. **Effective settings:** steps, CFG, seed, batch are always shown; *Advanced settings* (sampler,
   scheduler, size) is collapsed with a one-line summary that says if any differ from the recommendation.
   Each field shows its origin (recommended / manual / locked), **↺** resets one, **Reset unlocked to
   recommended** resets the rest, **Lock** protects a value.
5. **Build mock preview:** the chip becomes READY (or BLOCKED with named reasons). Change anything and
   it becomes **STALE** with *Stale because the draft changed: …* naming the fields; **Simulate
   admission** is then disabled and refuses if forced.
6. **Simulate admission:** a banner states *SIMULATED ONLY — no job submitted and no image generated*;
   the result card shows one placeholder tile per batch image ("MOCK IMAGE n OF N", seed, size) and
   scrolls into view. Editing afterwards clears the receipt.
7. **Undo / Redo / Reset demo draft** (reset is undoable). Nothing is saved.

## 5. Comparing layouts

Use **Layout → Scrolling form / Split workspace** in the Create header. State, undo history and the
preview are preserved on switch. Collapse the Output Display to give either layout more room.
Measured results: [LAYOUT_EVALUATION](LAYOUT_EVALUATION.md). Reproduce them with `tools/layout_audit.py`.

## 6. What this walkthrough cannot show

No real model, profile, backend, job, History or Artifacts; no screen-reader behaviour; no real
125/150% display. See [ASSESSMENT](ASSESSMENT.md).
