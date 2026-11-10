# Theme contract (`stablenew.qt-design-theme`, schema version 1)

Source of truth: `stablenew_qt_proto/theme.py` (pure Python). Presets: `stablenew_qt_proto/themes/`.
This theme system belongs to the **design workspace only**. It is not a second production theme and
touches no Tk design value (`src/gui_v2/design_values.py`, `src/gui/ui_tokens.py`) or setting.

## Document shape

A UTF-8 JSON object, at most 128 KiB, with exactly these keys (unknown or missing keys, duplicate
keys, `NaN`/`Infinity` and non-object roots are rejected):

| Key | Content |
|---|---|
| `schema`, `schema_version` | `stablenew.qt-design-theme`, `1` (a future version is refused, never guessed) |
| `id`, `name`, `description` | slug id; name 1–60 chars; description ≤ 600 chars (shown as plain text) |
| `kind`, `base_id` | `reference` (shipped, immutable) or `user`; `base_id` names the reference a user theme derives from |
| `colors` | 15 semantic roles, each `#RRGGBB`: `background surface field selected border strong_border text muted disabled accent on_accent danger success danger_fill on_danger` |
| `typography` | `family` (letters, digits, space, `. _ -`, ≤ 64 chars; blocks stylesheet injection), `body_pt 8–16`, `small_pt 7–14`, `section_pt 8–20`, `heading_pt 9–28`, `emphasis_weight normal|bold` |
| `spacing`, `density` | `xs sm md gutter xl` px ranges 0–16/24/32/48/64 and `control_min_height 24–64`; `density comfortable|compact` |
| `borders`, `radius` | `control_width 1–4`, `card_width 0–4`; `control button card chip` radii 0–24/24/32/32 |
| `states` | 8 component-state appearances (`button_hover_border`, `input_hover_border`, `focus_border`, `pressed_background`, `primary_hover_border`, `primary_focus_border`, `selected_item_border`, `hover_fill`), each **a colour role name**, never a literal |
| `provenance` | optional ≤ 64 short notes saying where values come from |

Integers must be real integers (booleans are rejected). Validation returns every error at once; an
invalid file never half-loads.

## Density

`compact` scales layout gaps (`xs sm md gutter xl`) by 0.75. It **never** reduces the control minimum
height, so hit targets do not shrink (UX-850-C: do not reduce body font or hit target to solve a
compact window). Spacing is read when widgets are built, so applying a spacing change rebuilds the
Create view (the draft session, undo history and layout choice are preserved).

## Contrast diagnostics

20 WCAG 2.x relative-luminance checks (text on each surface 4.5:1, primary action label 7:1,
danger label 4.5:1, accent/outline/focus/hover edges 3:1, disabled text 3:1, danger/success text on
fields 4.5:1). **Apply, Save As and Export are refused while any check fails or an edit is invalid.**
These validate colour pairs only; they are not a WCAG conformance or screen-reader result.

## Presets

| Preset | Origin | Honesty note |
|---|---|---|
| `blue-modern` | Exact values of the imported v0.3.0 prototype, plus the new `danger_fill`/`on_danger` roles | JSON pinned by SHA-256 `bae781b2…7217` (line-ending independent) so the migration cannot drift silently |
| `concept-a` | Reconstructed from `docs/research/stablenew-experience/ux850-c/TOKENS.md` role values | **Not verified against the Figma Concept A file** (no Figma access in this task). `provenance` marks each role as *verified* (documented value), *mapped* (documented colour, mapped role) or *invented* (`danger`, `success`, `field`; the production red fill is only 4.0:1 on the dark page so a lighter text red was invented). SHA-256 `ea290b8d…6ce9` |

Both pass all 20 checks. No pixel parity with any Figma file is claimed.

## Library behaviour (`theme_store.py`)

- Shipped presets cannot be overwritten, deleted or saved under their names; editing one yields an
  unsaved user copy.
- **Save As** writes canonical JSON atomically to the user directory (default
  `design/qt_widgets/user_themes/`, git-ignored; `STABLENEW_QT_PROTO_THEME_DIR` overrides). Overwriting
  an existing saved theme needs a second deliberate Save As press. Names are slugged (no path
  separators, Windows reserved device names guarded).
- **Export** writes a validated copy to a chosen `.json` path (never into the shipped theme folder).
  **Import** validates the file, downgrades any `kind: reference` claim to `user`, renames id
  collisions, and loads it as an *unsaved draft* — import never saves or applies by itself.
- **Apply** restyles the whole prototype and remembers the theme (saved or reference) for next
  launch in `active-theme.json`; an unsaved or modified theme is applied for the session only.
- Imported names/descriptions are untrusted text: shown with plain-text labels, never rich text.

## Enforcement

`tests/test_theme_contract.py` (validation, contrast, editor, density, preset pins),
`tests/test_theme_store.py` (save/restore/overwrite/import/export/isolation),
`tests/test_theme_consistency.py` (no hex/RGB/QColor/font literals outside `theme.py` and the preset
JSON; every component role and state is styled), `tests/test_qt_theme_studio.py` (live preview,
forced-state pixels, blocking, persistence through the UI).
