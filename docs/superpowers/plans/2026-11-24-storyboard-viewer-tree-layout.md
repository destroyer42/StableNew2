# Storyboard viewer / tree / Continue-panel layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Storyboard tab stays usable on a short window (Viewer fits, tree scrolls and resizes, Continue panel scrolls), the selected take and Continue target are unmistakable, and prompt fields are roomy and fast.

**Architecture:** Presentation-only changes in `src/gui`. Each widget keeps its public API: the Viewer fits and rescales its own picture, `StoryboardColumnsV2` gains vertical scrolling, selection styling and `see()`, the tab hosts tree and body in a vertical `tk.PanedWindow` and shows a Continue banner, and `ContinueRowsV2` swaps `ttk.Entry` for a `MirroredText` that mirrors the existing `StringVar`s. The Continue panel's middle region sits in the existing `ScrollableFrame`.

**Tech Stack:** Python 3.14, Tkinter/ttk, Pillow, pytest (`pytest.mark.gui`, `tk_root` fixture).

**Spec:** `docs/superpowers/specs/2026-11-24-storyboard-viewer-tree-layout-design.md`

## Global Constraints

- Branch `claude/storyboard-viewer-layout` (already created). **Never stage or revert** the unrelated modified files already in the worktree (`presets/settings.json`, `src/video/workflow_catalog*.py`, `docs/Subsystems/Video/PR-VID-FUN-352_Fun_Control_5B.md`, `tests/video/*`); `git add` only the files each task names. No push, no merge.
- Presentation only: no change to the contract (`storyboard_tree_contract.py`), service, queue, runner or NJR; no new execution path (AGENTS.md section 2).
- GUI stays non-blocking: rescaling uses the cached PIL frame, debounced; no disk or network on the UI thread.
- Line length 100 (ruff). Colours come from `Colors` tokens (`src/gui_v2/design_values.py`, re-exported by `design_system_v2`), never hex literals.
- Existing attribute names stay: `prompt_entry`, `negative_entry`, `prompt_var`, `negative_var`, `seed_*`, `columns.card_frames`, `columns.card_take_ids()`, `viewer.index`, `viewer.frame_count`, `viewer._photo` (None while media hidden).
- Tests use real Tk through the `tk_root` fixture and `tests/gui_v2/storyboard_tab_helpers.py` fakes; existing `tests/gui_v2/test_pr_vid_story_*`, `test_storyboard350_ui.py`, `test_vid_ux_384_layout.py` must keep passing.

## Review Focus

- A live-state auto-refresh rebuilds the whole tree every `REFRESH_MS`; the tree's scroll position must not jump back (Task 3).
- A window shorter than the Viewer's content, or a not-yet-mapped widget (`winfo_width()` is 1): the fit never raises, never returns a size under 1x1, and the controls stay visible (Task 2).
- Pasting multi-line text or pressing Enter in a prompt field must leave a single-line prompt, and Tab must leave the field (Task 5).
- Setting `prompt_var` programmatically (`set_rows`, restore) must show in the field, and clearing the field must clear the variable (Task 5).
- The selected take is hidden (dropped, "Show dropped" off) or missing: `see()` is a no-op and the banner still names the Continue target (Tasks 3, 4).

---

### Task 1: Selected-card style

**Files:**
- Modify: `src/gui/design_system_v2.py` (constant near line 23; `apply_card_styles` near line 60)
- Test: `tests/gui_v2/test_storyboard_layout_fit.py` (new; shared by Tasks 1-5)

**Interfaces:**
- Produces: `design_system_v2.SELECTED_CARD_FRAME = "SelectedCard.TFrame"`.

- [ ] **Step 1: Write the failing test** `test_selected_card_style_has_a_thick_accent_border(tk_root)`: after `theme_v2.apply_theme(...)` (use the same call the other GUI tests use; grep `apply_theme`/`apply_design_system` in `tests/gui_v2`), `ttk.Style().lookup(SELECTED_CARD_FRAME, "bordercolor") == Colors.PRIMARY_ACCENT` and `int(lookup(..., "borderwidth")) >= 3`; `Card.TFrame`'s borderwidth stays 1.
- [ ] **Step 2: Run** `python -m pytest tests/gui_v2/test_storyboard_layout_fit.py -k selected_card_style -v`. Expected: FAIL (name missing).
- [ ] **Step 3: Implement** the constant and register the style in `apply_card_styles` as a copy of the `CARD_FRAME` options with `borderwidth=3`, `bordercolor=Colors.PRIMARY_ACCENT`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `git add src/gui/design_system_v2.py tests/gui_v2/test_storyboard_layout_fit.py` then `git commit -m "feat(storyboard): selected-card frame style"`.

### Task 2: Viewer fits its picture and keeps the controls

**Files:**
- Modify: `src/gui/widgets/storyboard_viewer_v2.py`, `src/gui/views/storyboard_tab_frame_v2.py:553-556` (`_apply_frame`)
- Test: `tests/gui_v2/test_storyboard_layout_fit.py`, `tests/gui_v2/test_pr_vid_story_import_tab.py` (existing hidden-frame test must still pass unchanged)

**Interfaces:**
- Produces: module function `fit_size(source: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]` (aspect kept, never above 1x, each side at least 1, a non-positive box side treated as 1); `StoryboardViewerV2.show_image(image: PIL.Image.Image) -> None` (replaces the photo-taking version; the tab is its only caller); constant `MIN_IMAGE_HEIGHT = 120`; the picture sits in `self.image_area` (a `ttk.Frame`, `grid_propagate(False)`, `height=MIN_IMAGE_HEIGHT`) and `image_label` is placed centred inside it.

- [ ] **Step 1: Write the failing tests:** `test_fit_size_keeps_aspect_and_never_upscales` (`fit_size((800, 400), (400, 400)) == (400, 200)`; `fit_size((16, 8), (400, 400)) == (16, 8)`); `test_fit_size_never_returns_zero` (`fit_size((800, 400), (0, 0))` and `fit_size((0, 0), (10, 10))` each give sides >= 1, no exception); `test_viewer_picture_is_scaled_to_a_short_window` (viewer packed in a 400x300 root, `set_cut(5, (), 16)`, `show_image(Image.new("RGB", (800, 600)))`, `update()`; assert the label's image height <= `image_area.winfo_height()` and `slider`, `continue_button` have `winfo_ismapped()` and `winfo_y() + winfo_height() <= viewer.winfo_height()`); `test_viewer_rescales_when_resized` (resize root, `update()`, wait one debounce via `viewer.update()` after `after`-flush, image height follows); `test_hidden_viewer_drops_a_late_frame` (`set_media_visible(False)`, `show_image(...)`, `viewer._photo is None`).
- [ ] **Step 2: Run** `-k "fit_size or viewer"`. Expected: FAIL.
- [ ] **Step 3: Implement** `fit_size`; in `StoryboardViewerV2` wrap the label in `image_area` (grid row 1, `sticky="nsew"`; `set_media_visible` shows/hides the area, not the label), keep the source PIL image in `self._source`, build the `PhotoImage(master=self)` in a private `_refit()` using `image.resize(..., Image.LANCZOS)` only when the target size changed, call `_refit` from `show_image` and from a debounced (`after(40)`, cancelled in `destroy`/`pause`-style cleanup) `<Configure>` on `image_area`; `clear()` and hiding drop `_source` and `_photo`. Rows 2-5 keep `weight=0`.
- [ ] **Step 4: Update** `_apply_frame` to `self.viewer.show_image(image)` (keep the `if not self.media.viewer: return` guard); drop the now-unused `ImageTk` import only if nothing else in the file uses it (the thumbnail path does).
- [ ] **Step 5: Run** `python -m pytest tests/gui_v2/test_storyboard_layout_fit.py tests/gui_v2/test_pr_vid_story_import_tab.py tests/gui_v2/test_pr_vid_story_380_tab.py -q`. Expected: all pass.
- [ ] **Step 6: Commit** the touched files, `feat(storyboard): viewer fits its picture and keeps controls visible`.

### Task 3: Tree scrolls both ways, styles the selection, follows it

**Files:**
- Modify: `src/gui/widgets/storyboard_columns_v2.py`
- Test: `tests/gui_v2/test_storyboard_layout_fit.py`

**Interfaces:**
- Consumes: `SELECTED_CARD_FRAME` (Task 1).
- Produces: `StoryboardColumnsV2.see(take_id: str) -> None` (scrolls the canvas so that card's frame is fully inside the viewport, both axes; no-op for an unknown id); `StoryboardColumnsV2.render(columns: tuple[Column, ...])` unchanged in signature but now preserves both scroll offsets across the rebuild; `_on_wheel(event) -> str | None` (Shift held or `event.state & 0x1` scrolls sideways, otherwise vertically; returns `"break"` only when the canvas can scroll that way); a vertical scrollbar `self._vscroll`.

- [ ] **Step 1: Write the failing tests** (build a `StoryboardColumnsV2` in a 600x200 root with one column of 6 `Card`s and a second column; `update()`): `test_third_card_is_reachable_by_scrolling` (before: the 6th card's frame bottom is below the viewport; `see("c6")`; after `update()`, its `winfo_rooty()` range is inside the canvas's); `test_see_unknown_take_is_a_noop` (no exception, `yview()` unchanged); `test_selected_card_uses_the_selected_style_and_marker` (`card_frames["c2"].cget("style") == SELECTED_CARD_FRAME` when `selected=True`, on-path card keeps `"Card.TFrame"`, others `"Panel.TFrame"`; the label text still starts `"▶ "`); `test_wheel_scrolls_vertically_and_shift_wheel_sideways` (call `_on_wheel(SimpleNamespace(delta=-120, state=0))` then `state=1`, `yview()[0] > 0`, `xview()[0] > 0` with a wide enough second column); `test_wheel_is_not_consumed_when_everything_fits` (single short column: returns `None`); `test_render_keeps_scroll_offsets` (scroll down, call `render(same columns)` and `update()`, `yview()[0]` within 0.01 of before).
- [ ] **Step 2: Run** `-k "reachable or see_unknown or selected_card_uses or wheel or keeps_scroll"`. Expected: FAIL.
- [ ] **Step 3: Implement.** Grid the canvas at (0,0), `_vscroll` at (0,1) (`orient="vertical"`, wired to `yview`/`yscrollcommand`), the horizontal bar at (1,0) `columnspan=2`; keep `height=210` as the requested size. In `_build_card` choose the frame style `SELECTED_CARD_FRAME if card.selected else ("Card.TFrame" if card.on_path else "Panel.TFrame")`. In `render`, record `xview()[0]`/`yview()[0]` first and restore with `after_idle` once the scroll region is updated. Bind `<MouseWheel>` (and `<Button-4/5>`) with `add="+"` on the canvas and recursively on every widget built in `render`. Implement `see` from `update_idletasks()` plus the frame's position relative to `_inner`, moving the canvas with `xview_moveto`/`yview_moveto` only when the frame is not already fully visible.
- [ ] **Step 4: Run** the new tests plus `tests/gui_v2/test_pr_vid_story_380_tab.py -q`. Expected: pass. If the withdrawn `tk_root` reports 1x1 geometry, call `root.deiconify()` in these tests and `withdraw()` again in teardown.
- [ ] **Step 5: Commit** `feat(storyboard): scrollable take tree with a clear selected card`.

### Task 4: Resizable tree/body split and the Continue banner

**Files:**
- Modify: `src/gui/views/storyboard_tab_frame_v2.py` (`__init__` lines 129-160, `render` 422-426, `select_take` 476-481, `_apply_state` 357-383, `_apply_body_weights` 560-564, `_update_continue_panel` 818-845)
- Test: `tests/gui_v2/test_storyboard_layout_fit.py`

**Interfaces:**
- Consumes: `StoryboardColumnsV2.see` (Task 3).
- Produces: `tab.pane` (`tk.PanedWindow(self, orient="vertical", sashwidth=6, sashrelief="raised", bg=theme_v2.BACKGROUND_DARK)`) holding `tab.columns` (`weight`/stretch first, `minsize=90`) and `tab._body` (`minsize=160`, stretch always); `tab.banner_var: tk.StringVar` and `tab.banner_label` in `_body` row 0 spanning both columns; the viewer and `continue_host` move to `_body` row 1 (`rowconfigure(1, weight=1)`); `render(self, *, reveal_selected: bool = False)`; `_banner_text(self) -> str`.

- [ ] **Step 1: Write the failing tests** using the `storyboard_tab` fixture pattern from `test_pr_vid_story_380_tab.py`: `test_tree_and_body_share_a_draggable_pane` (`tab.pane.panes()` has two members, `columns` first); `test_banner_names_the_continue_target` (open the diner storyboard, `select_take("t1")`; `banner_var.get()` starts `"Continuing from: "`, contains the take's label from `contract.label` and `"frame"`; for the root still image it contains `"the still image"`); `test_banner_follows_continue_from_this_frame` (`tab.viewer.seek(2)`; `tab._continue_from_frame(2)`; the banner's frame number equals `tab.target[1] + 1`); `test_banner_when_nothing_is_selected` (fresh tab: `"Nothing selected to continue from"`); `test_selecting_reveals_the_selected_card` (`select_take` calls `columns.see` with the take id: spy by wrapping `tab.columns.see`); `test_auto_refresh_does_not_scroll_the_tree` (`tab.refresh()` path leaves `columns.see` uncalled); `test_hidden_selected_take_does_not_break_render` (drop the selected take with "Show dropped" off, `render(reveal_selected=True)` raises nothing).
- [ ] **Step 2: Run** `-k "pane or banner or reveals or auto_refresh or hidden_selected"`. Expected: FAIL.
- [ ] **Step 3: Implement.** Build `pane` at grid row 1 (`sticky="nsew"`, `padx=8`), create `columns` and `_body` with `pane` as master, `self.rowconfigure(1, weight=1)` and the status label at row 2 (remove the old row 1/2/3 grid calls and `rowconfigure(2, ...)`). `render(reveal_selected=False)` calls `self.columns.see(self.contract.selected_id)` after rendering when the flag is true; `select_take` and `_apply_state(..., keep_selection=False)` pass `True`; the periodic refresh and mark paths do not. `_update_continue_panel` sets `banner_var` from `_banner_text()` on every call (including the early-return branches) using `self.target` and `contract.label(owner)`: `f"Continuing from: {label} · frame {handoff + 1}"`, `"Continuing from: the still image"` when `handoff is None`, `"Nothing selected to continue from"` when `target is None`. Style the banner with `Dark.TLabel` and bold accent foreground via an existing label style if one exists (grep `theme_v2` for an accent label style), otherwise `Dark.TLabel` is acceptable.
- [ ] **Step 4: Run** `python -m pytest tests/gui_v2/test_storyboard_layout_fit.py tests/gui_v2 -k "story" -q`. Expected: pass; fix any test that assumed the old grid rows (assert on behaviour, do not weaken it).
- [ ] **Step 5: Commit** `feat(storyboard): resizable tree/body split and Continue banner`.

### Task 5: Roomy prompt fields and a scrolling Continue panel

**Files:**
- Create: `src/gui/widgets/mirrored_text_v2.py`
- Modify: `src/gui/widgets/storyboard_continue_rows_v2.py` (`ContinueRowFields.__init__`, `place`), `src/gui/views/storyboard_tab_frame_v2.py` (`_build_continue_panel` 680-743, `_sync_experimental` 847-858)
- Test: `tests/gui_v2/test_storyboard_layout_fit.py`

**Interfaces:**
- Produces: `MirroredText(master: tk.Misc, variable: tk.StringVar, *, rest_lines: int = 3, focus_lines: int = 8, **kwargs)` (a `tk.Text`, `wrap="word"`, `width=20`, `undo=True`): `variable` and the text always agree (variable changes update the text; edits update the variable; guarded against recursion); Enter (`<Return>`, `<KP_Enter>`) is swallowed; newlines arriving by paste become single spaces; `<Tab>`/`<Shift-Tab>` move focus and insert nothing; focus-in sets `height=focus_lines`, focus-out schedules `height=rest_lines` after 250 ms (cancelled on re-focus and on destroy); `FOCUS_SHRINK_MS = 250`.
- `ContinueRowFields.prompt_entry` / `negative_entry` are now `MirroredText` bound to `prompt_var` / `negative_var`; `place` aligns each row's cells to the top (`sticky` becomes `("ne", "new", "new", "nw", "n")`).
- The Continue panel: title, mode bar and AI reason stay at rows 0-2 of `continue_host`; a `ScrollableFrame` (`tab.continue_scroll`) at row 3 (`host.rowconfigure(3, weight=1)`) holds `rows_widget`, the Add-row button, the engine label and the experimental check (its grid rows 0-3 inside `continue_scroll.inner`, `inner.columnconfigure(0, weight=1)`); `actions` (Preview, Queue) move to row 4 of `continue_host`.

- [ ] **Step 1: Write the failing tests:** `test_mirrored_text_follows_the_variable` (set var, text equals it; clear var, text empty); `test_typing_updates_the_variable` (`insert("end", "hello")`, `update()`, var == "hello"; `delete("1.0","end")` -> ""); `test_enter_is_swallowed` (`event_generate("<Return>")` leaves the text unchanged); `test_pasted_newlines_become_spaces` (`insert("1.0", "a\nb")`, `update()`, var == "a b" and the widget shows "a b"); `test_tab_moves_focus_and_inserts_nothing` (two fields; focus the first; `event_generate("<Tab>")`; text unchanged, focus on the second); `test_field_grows_on_focus_and_shrinks_after_blur` (`focus_force()` -> `cget("height") == 8`; focus elsewhere; before `FOCUS_SHRINK_MS` still 8, after `update()` plus waiting past it -> 3; re-focusing inside the delay cancels the shrink); `test_six_rows_scroll_instead_of_clipping` (tab with 6 rows, a small root height; `continue_scroll.has_scroll_overflow()` is true, `queue_button` and `preview_button` stay `winfo_ismapped()` and inside `continue_host`); `test_set_rows_and_row_state_still_work` (existing `set_rows([...])` shows in the `prompt_entry` text; `_continue_rows()` still returns the typed prompts and seed problems).
- [ ] **Step 2: Run** `-k "mirrored or enter_is or pasted or tab_moves or grows_on_focus or six_rows or set_rows"`. Expected: FAIL.
- [ ] **Step 3: Implement** `MirroredText` as specified (variable trace with a re-entrancy flag; `<<Modified>>` to sync text to variable, resetting `edit_modified(False)`; cancel the shrink `after` in `destroy`). In `ContinueRowFields.__init__` replace the two `ttk.Entry` with `MirroredText(parent, self.prompt_var)` / `MirroredText(parent, self.negative_var)`; keep the tooltips. Then `grep -rn "prompt_entry\|negative_entry" src tests` and adapt any `ttk.Entry`-only call (`.get()`, `.insert`, `.configure(state=...)`) to the Text or variable equivalent.
- [ ] **Step 4: Restructure** `_build_continue_panel` as described (create `ScrollableFrame(host)`; build `ContinueRowsV2(self.continue_scroll.inner, ...)`, `add_row_button`, the engine label and `experimental_check` in `inner`; `experimental_check.grid(row=3, ...)` in `_sync_experimental`; `rows_frame`/`rows_widget` names unchanged).
- [ ] **Step 5: Run** `python -m pytest tests/gui_v2/test_storyboard_layout_fit.py tests/gui_v2/test_pr_vid_story_import_tab.py tests/gui_v2/test_pr_vid_story_380_tab.py tests/gui_v2/test_pr_vid_story_380_handoff.py tests/gui_v2/test_storyboard350_ui.py tests/gui_v2/test_vid_ux_384_layout.py -q`. Expected: all pass.
- [ ] **Step 6: Commit** the new and touched files, `feat(storyboard): roomy prompt fields and a scrolling Continue panel`.

### Task 6: Verify the branch

**Files:**
- Modify: `docs/CODE_MAP.md` only if `python tools/generate_code_map.py --check` (or its documented equivalent; read the script's `--help`) reports drift from the new module.

- [ ] **Step 1: Run** `python -m ruff check src/gui tests/gui_v2/test_storyboard_layout_fit.py` and `python -m ruff format --check` on the touched files. Expected: clean (fix only what this change introduced).
- [ ] **Step 2: Run** `python -m pytest tests/gui_v2 -k "story or storyboard or scroll or theme" -q` then the architecture ratchets `python -m tools.ci.run_architecture_ratchets` (controller untouched, so no ceiling should move). Expected: pass.
- [ ] **Step 3: Run** `git diff --check` and `git status -sb`; confirm only this plan's files are changed by the branch (`git diff --stat main...HEAD`).
- [ ] **Step 4: Manual check on the real window** (Tk cannot be seen by the tests): open a storyboard with 3+ parallel takes in one column; shrink the window to about 500 px tall; confirm every card is reachable by wheel and the sash drags, the picture shrinks with the slider and **Continue from this frame** still showing, the selected card has the gold border and the banner names it, all 6 rows can be filled and scrolled with **Queue** always visible, and long prompts type, select and arrow-key without lag. Click a Combobox in the row below right after typing in a prompt: the click must land on it.
- [ ] **Step 5:** Run `python tools/ci/run_pr_gate.py` only if the repository policy for this change class requires it (read `docs/AGENT_OPERATING_MODEL.md` PR-ready criteria); otherwise record that focused validation was used. Do not push.
