# Storyboard tab: fit, scroll and make the selection obvious (design)

Date: 2026-11-24. Status: **approved by Rob 2026-11-24** (design, plus the prompt-field and right-panel additions in
section 3.4). Execution class: **Standard** (several `src/gui` presentation files, no contract, queue or runner change).
**Model recommendation:** Claude Code Sonnet 5.5 Medium; presentation-only Tk work in understood architecture.

Decisions are labelled **[Rob]** (said or chosen by Rob) or **[call]** (the designer's, for Rob to correct).

## 1. Intent

The Storyboard tab (PR-VID-STORY-380) stops being usable on a short window, and it does not say clearly which take
Rob is about to continue from. He wants to:

- see the whole clip/frame in the Viewer however tall the window is, with the slider and **Continue from this frame**
  always reachable **[Rob]**;
- reach every take card in the tree, including the 3rd, 4th... of a parallel fan-out, to look at or preview it
  **[Rob]**;
- know at a glance which take and frame the next Continue extends or parallelises from **[Rob]**;
- type long prompts without the field fighting him: more vertical room, or growth on focus, and no slow sideways
  scrolling in the text field **[Rob]**; with all 6 rows in use the right-hand panel must still be fully reachable
  **[Rob]**.

## 2. What exists (evidence: `main` at `25f80feb`)

- `StoryboardColumnsV2` (`src/gui/widgets/storyboard_columns_v2.py`): a `tk.Canvas(height=210)` with only a horizontal
  scrollbar. Each tree depth is a column; parallel takes stack vertically inside it, so cards past ~210 px are
  unreachable. The tab grids it `sticky="ew"` in row 1; the body is row 2 (weight 1).
- `StoryboardViewerV2` (`.../storyboard_viewer_v2.py`): the picture is a `ttk.Label` showing the full-size
  `PhotoImage` (the tab builds `ImageTk.PhotoImage(image)` in `_apply_frame`). It never scales. When the window is short
  the grid squeezes the lower rows, so the slider, controls and Continue button disappear first.
- Selection: `Card.selected` and `Card.on_path` exist in the contract. The widget shows only a `▶ ` label prefix and
  `Card.TFrame` vs `Panel.TFrame` for `on_path`. The Continue target is only said in the Continue panel's title
  (`Continue <take> from its frame N`, `_update_continue_panel`).
- Continue panel (`_build_continue_panel`, `ContinueRowsV2`): prompts are one-line `ttk.Entry` widgets (`prompt_var`,
  `negative_var`); up to 6 rows; the panel is a plain frame with no scrolling.

## 3. Design

### 3.1 Viewer autofit (viewer widget + tab)

- The image area is a grid cell that takes the space left after the title, slider, ticks, controls and note rows. The
  controls rows keep `weight=0` and a minimum size, so they are never squeezed out.
- The picture is **scaled to fit** that cell (aspect ratio kept, never upscaled past 1x **[call]**) and is re-scaled on
  `<Configure>` (debounced). The viewer keeps the source PIL image for the current frame and builds the `PhotoImage`
  itself; the tab passes the PIL image rather than a `PhotoImage` (`_apply_frame`). `show_image` accepts both a PIL image
  (fit) and the existing photo object, so current callers and tests keep working.
- A minimum image height (about 120 px) stops the picture collapsing to nothing on a very short window **[call]**.

### 3.2 Take tree: scroll, resize, follow the selection (columns widget + tab)

- `StoryboardColumnsV2` gets a vertical scrollbar next to the horizontal one, mouse-wheel (vertical) and Shift+wheel
  (horizontal) while the pointer is over the tree. The fixed `height=210` becomes a minimum, not the height.
- The tree and the body (Viewer + Continue) sit in a vertical `ttk.PanedWindow` in the tab, so Rob drags the divider to
  give either more room **[Rob: "resize"]**. The tree keeps `weight` 1 and the body `weight` 3 initially **[call]**.
- Rendering the tree scrolls the selected card into view (`see(take_id)`), so selecting or refreshing never leaves the
  selected card off-screen.

### 3.3 Selection and the Continue target

- **Selected card:** a thick accent-gold border (`PRIMARY_ACCENT` token) through one new ttk style,
  `SelectedCard.TFrame`, registered beside `Card.TFrame` in `design_system_v2.apply_card_styles`; the `▶` text marker
  stays so the selection is not colour alone. No separate tint: the card's labels paint their own background, so a tinted
  frame would show as mismatched patches **[call, changed from the first sketch]**. **On the path:** the existing
  `Card.TFrame`. Other cards: unchanged.
- **Continue banner** spanning the top of the body (above both the Viewer and the Continue panel, so it sits next to
  Queue) **[call]**: `Continuing from: <take label> · frame N` (or `the still image`). It is bound to `tab.target`
  (the value that titles the Continue panel), so it changes when the selection changes and when **Continue from this
  frame** is pressed. It shows `Nothing selected to continue from` when there is no target. The Continue panel title
  keeps its existing text.
- **Scroll offsets survive re-renders:** the tree is rebuilt on every refresh while takes are running, so `render`
  keeps the current scroll position and only an explicit select/open scrolls the selected card into view **[call]**.
- The selected card's Resume/Replay/Keep/Drop buttons and every existing action are unchanged.

### 3.4 Prompt fields and the right-hand panel **[Rob]**

- **Prompt and negative fields** become word-wrapped multi-line `tk.Text` widgets, which removes the sideways-scroll
  slowness (the single-line `ttk.Entry` is the cause). Resting height 3 lines **[call]**; on focus-in the focused field
  grows to about 8 lines and shrinks back on focus-out **[call]**. A prompt stays one logical line, as the service
  expects: Enter is swallowed and pasted newlines become spaces **[call]**; Ctrl+A selects all.
- **`prompt_var` / `negative_var` keep their `StringVar` API** (the tab, contract and tests read and set them). The Text
  widget mirrors the variable both ways with a re-entrancy guard, so no consumer changes.
- **Right panel:** the title and Parallel/Sequential bar stay pinned at the top, **Preview / Queue** stay pinned at the
  bottom, and everything between (rows, Add row, engine line, experimental check, hint) scrolls in the existing
  `src/gui/widgets/scrollable_frame_v2.ScrollableFrame` (vertical scrollbar, wheel routing that leaves `Text` fields
  their own wheel, scroll-to-focus) **[call]**: Queue is always reachable, and 6 enlarged rows scroll instead of being
  clipped. That frame already tracks the canvas width, so the two prompt columns still share the spare width.
- Focus-out shrinks a grown field after a short delay (about 250 ms), not at once, so a click on a control in the next
  row is not moved from under the pointer by the shrink **[call]**.
- Tab and Shift+Tab move focus out of a prompt field instead of inserting a tab character **[call]**.

## 4. Goals, non-goals, anti-goals

- **Goals:** every take, frame, control and prompt reachable at any window height; the selection and Continue target
  unmistakable; a responsive prompt field.
- **Non-goals:** no new storyboard behaviour, no contract/queue/runner/NJR change, no change to what Continue submits, no
  horizontal Viewer/Continue divider (prompt wrapping and the scrolling panel give the room), no zoom/pan inside the
  Viewer, no change to the thumbnail/viewer on-off preferences.
- **Anti-goals:** anything that hides **Queue** or **Continue from this frame** behind a scroll; anything that makes the
  selected card visible by colour alone; an image that blocks the UI while rescaling (resizes use the cached PIL image,
  no disk or network).

## 5. Approaches considered

1. **Per-widget fit and scroll (chosen):** the Viewer fits itself, the tree and the Continue rows scroll, a divider
   separates tree from body. Smallest blast radius; each widget keeps its current API.
2. **One scrollable page for the whole tab:** simple, but scrolling hides Queue and the Viewer controls, which is the
   failure being fixed.
3. **Make the tree strip taller:** only moves the clipping point and takes room from the Viewer.

## 6. Constraints and invariants

GUI stays non-blocking (rescales on the UI thread use the cached image and are debounced); no queue, runner, NJR or
history change; presentation preferences stay in `MediaPrefs`. Existing tests that read `prompt_entry.grid_info()`,
`prompt_var`, `seed_*`, `card_frames`, `card_take_ids`, `action_buttons` and the viewer's `index`/`frame_count` keep
passing; the entry attribute names (`prompt_entry`, `negative_entry`) stay, now naming the Text widgets.

## 7. Left to the builder

Exact scale/debounce numbers, the precise accent/tint tokens, the wheel-binding scoping, and how the PanedWindow
sash positions are remembered (default: not persisted). Tk cannot be exercised visually here: headless tests cover the
fit maths, the mirroring, the see-selected and banner logic, and a manual check on the real window is listed in the plan.
