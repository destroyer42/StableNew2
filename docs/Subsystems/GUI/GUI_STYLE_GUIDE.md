# GUI style guide (living)

Status: Active, edited in place by the PR that changes a token, style or shared component
Updated: 2026-10-22 (PR-GUI-400)

How the Tk GUI looks and which names to use. It supplements `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md`; the code and
`tests/gui_v2/test_design_foundation_400.py` win on any disagreement.

## 1. Where things live

| Layer | File | Owns |
|---|---|---|
| Raw palette, spacing, type sizes, radii (immutable values, no toolkit import) | `src/gui_v2/design_values.py` | `Colors`, `Spacing`, `Typography`, `Radii`, `NOTICE_KINDS` |
| ttk style *names* and Tk registration | `src/gui/design_system_v2.py` | style-name constants, card/label/action-button styles; re-exports the values above unchanged |
| Semantic tokens (what new code reads) | `src/gui/ui_tokens.py` | `TOKENS.colors / spacing / typography / notices`; built from `design_values`, imports no toolkit |
| Registration of every other ttk style | `src/gui/theme_v2.py` | `init_theme` / `apply_theme`; entries, checkbuttons, radiobuttons, notebook tabs, disclosure, notices; style-name constants (`*_STYLE`) |

New code takes values from `TOKENS` and style names from the constants; it does not write hex literals or a second theme.
Style names are public: add one, do not rename one. A value is changed once, in `design_values.py`; a renderer (Tk today) reads it and
never keeps its own copy. `design_values` and `ui_tokens` must stay importable without `tkinter`
(`tests/gui_v2/test_design_values_741.py` imports them in a process that forbids it). `TOKENS.spacing` is canonical (its `xs` is 4; the older
`design_system_v2.Spacing.XS` is 2 and is kept only for existing callers).

Metrics are frozen for Wave 1: Segoe UI 10 / 11 / 12 pt, spacing 4 / 8 / 12. A change to a global metric needs
before/after geometry for every tab (`tests/gui_v2/test_design_foundation_400.py` pins them).

## 2. Surfaces and which label style to use

`#121212` is the page; `#1E1E1E` is every card, section, panel and label frame; `#2B2B2B` is a selected header or tab;
`#262626` is hover on a quiet button.

| Where the label sits | Use |
|---|---|
| Card / Section / Panel / LabelFrame (almost everything) | `Heading.TLabel`, `Subheading.TLabel`, `Body.TLabel`, `Muted.TLabel` (all card surface), or `Dark.TLabel` |
| Directly on the page-dark background (a plain `TFrame`, a dialog root, `ScrollableFrame` content) | `Page.Body.TLabel`, `Page.Muted.TLabel`, plain `TLabel`, `Page.TRadiobutton` |

A ttk label cannot be transparent: a style whose background differs from its parent draws a visible rectangle.
Known gap: ~90 widgets (plain `TLabel`/`TCheckbutton` without a style, mostly inside label frames) still use the
class default and mismatch their surface; give them `Dark.TLabel` / `Dark.TCheckbutton` when you touch them.

## 3. Hierarchy

- **Heading** (gold, 12 pt bold): one title per card. **Subheading** (white, 11 pt bold): a group inside a card, and
  the tab overview title (help text is not a page heading). **Body** (white 10 pt): field labels and content.
  **Muted** (`#CCC`): explanatory text.
- **Gold is reserved** for the Primary action, selection and "non-default hidden content" hints, and keyboard focus.
  Do not use it for decoration or ordinary headings of lower priority.
- Card boundary: `Card.TFrame` (1 px border) for a standalone card, `Section.TFrame` / `Panel.TFrame` inside one.

## 4. Actions and states

| Role | Style | Use |
|---|---|---|
| Primary | `Primary.TButton` (gold fill, black text) | The one action that advances the task; one per surface |
| Secondary | `Secondary.TButton` | Other actions |
| Ghost | `Ghost.TButton` | Low-emphasis, outlined |
| Danger | `Danger.TButton` (red fill, white text, 4.6:1) | Destructive actions only |
| Generic | `Dark.TButton`, `TButton` | Quiet buttons inside forms and panels |

Every interactive style defines the same states, and tests assert them:

- **Disabled**: foreground `TOKENS.colors.text_disabled` (`#777`) and `embossed` off. Tk draws a doubled "embossed" shadow
  for disabled text unless a style turns it off, and the old disabled foreground (`#CCC`) looked enabled. A disabled
  Primary keeps a dim gold edge so it still reads as the primary action.
- **Hover** (`active`): a lighter surface or fill. **Pressed**: the same.
- **Keyboard focus** (`focus`): a visible edge, gold on dark surfaces and white on gold/red fills, at least 3:1 against the
  surface. Never remove the native focus behavior. Checkbuttons, radiobuttons and sliders set `focuscolor` explicitly: the theme's
  default focus line is black and disappears on these surfaces (found with real Tab key events). The slider thumb also turns gold
  while focused. Known gap: a `Treeview` draws no focus border (one would add 2 px to every tree); its cue is the selected row.
- **Focus is scrolled into view**: `ScrollableFrame` reveals a control that takes focus, in every containing frame, through the
  router's single `<FocusIn>` binding. Do not build a second scrolling container that lacks this (`scrolling.make_scrollable`
  does not have it yet).
- **Selected** (`selected` state flag): expanded `DisclosureSection` and `TabOverviewPanel` headers and the selected
  notebook tab. Set it with `widget.state(["selected"])`; it is also the signal tests read.

Action buttons carry a 1 px edge so focus can show on a filled button; their padding is reduced by 1 px so the outer size
is unchanged.

## 5. Inline notices (never a modal for an action result)

`SubmissionNotice` shows `neutral`, `info`, `success`, `warning` and `error` (plus the existing `queued`). Each kind has a
word (`Note`, `Info`, `Success`, `Warning`, `Error`, `Queued`), a tinted surface, an accent edge bar and a semantic role
(`alert` for warning and error, `status` otherwise), all from `TOKENS.notices`. The **visible word** is what keeps a status from
being color-only, and text contrast is checked (section 7). `notice.role` and `notice.accessible_text()` ("Error: Source image
is missing") are a programmatic contract for tests and a future UI Automation bridge. **They are not announced by a screen
reader today**: Tk exposes no accessibility tree for ttk widgets, so this PR makes no screen-reader claim. Errors and warnings
stay until dismissed or replaced; `queued` and `success` dismiss themselves. State what failed and what to do in the message. An
idle notice paints nothing and keeps the old reserved row height.

## 6. Consuming this from another tab

1. Take colors, spacing and type sizes from `TOKENS`; take style names from `design_system_v2` / `theme_v2`.
2. Pick the label style by surface (section 2). One Primary action per surface; Danger only for destructive actions.
3. Use `TabOverviewPanel`, `DisclosureSection` and `SubmissionNotice` as they are; do not copy their layout. Set no fixed
   heights on them.
4. Do not add a style to fix one screen: add a role here, with a test, if more than one place needs it.

### Shared media controls

Shared media inspection uses `MediaInspector`: a nearby **Show media** checkbox, **Detach** / **Return to dock**, and still-image
**Fit**, **100%**, minus/plus and scroll/pan controls. Controls use existing Dark button/checkbutton styles and muted status text;
compact toolbars wrap vertically. A detached renderer leaves a compact placeholder in its dock. Hide is ephemeral presentation
state, subordinate to content visibility. Resolution labels distinguish source pixels from a downsampled preview. Open original
is offered only on hosts that already support original-file actions. No new global style, font size or modal focus grab is used.

## 7. Checks

Deterministic (CI): `tests/gui_v2/test_design_foundation_400.py` (token shapes and contrast, style registration, disabled /
hover / focus / selected maps, surface matching, notice role and text, metric invariants), plus `test_theme_v2.py`,
`test_dialog_theme_v2.py`, `test_tab_overview_panels_v2.py` and `test_ui_tokens_contract.py`. Contrast floors: message text
7:1, role words and Danger text 4.5:1, focus edges and disabled text 3:1 against their surface.

Manual (Windows, not in CI): look at Pipeline, Review and Video Workflow at 1366x768 and 1920x1080, at 100% and 150%
display scale, and tab through the controls. DPI facts to record with any screenshot:

- The app sets no DPI awareness, and a plain Tk process on the project's Python reports awareness 0 (unaware). At a real
  150% display scale Windows therefore stretches the finished window as a bitmap: the layout equals 100%, only blurrier.
  Changing the Windows display scale is the only way to see that case.
- `root.tk.call("tk", "scaling", 2.0)` (with 1.3333 as 100%) approximates a DPI-aware process at 150%: fonts grow while pixel
  padding does not. It is the stress case for clipped text and min-width, which is what PR-GUI-110 designed for. Say which of
  the two a screenshot used.

Check that nothing is clipped, focus is visible on every control, and a disabled control is distinguishable from an enabled
one without relying on color.

Keyboard focus is best checked with real key events, not by forcing the ttk `focus` flag: send Tab to the foreground window
(`keybd_event`; Windows may refuse `SetForegroundWindow` until the process has had input, and a synthetic Alt tap lets it
succeed), and for each control compare its pixels while focused with the same region after focus moves on. A process that is
not DPI-aware gets virtualized coordinates at 150%, so screen grabs for such a check must come from a DPI-aware process
(`SetProcessDpiAwareness(2)`), which also gives Tk the real 144 DPI scaling.
