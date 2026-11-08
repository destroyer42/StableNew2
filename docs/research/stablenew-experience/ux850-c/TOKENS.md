# PROPOSED tokens and provenance

These are research role mappings, **not a second runtime theme**. Production values remain owned by `src/gui_v2/design_values.py`, semantic `src/gui/ui_tokens.py`, and registrations in `src/gui/design_system_v2.py` / `theme_v2.py` ([exact anchors](TK_FEASIBILITY.md)). An implementation reads TOKENS and public style constants, never copies this table's literals into a view. Global metrics are frozen by existing tests; any future change needs before/after geometry across every tab.

| Proposed role | Existing value / mapping | C disposition |
|---|---|---|
| Page / panel / selected surface | `#121212` / `#1E1E1E` / `#2B2B2B`; `surface_primary/secondary`, SURFACE_SELECTED | Reuse; label backgrounds must match their containing surface |
| Body / supporting text | `#FFFFFF` / `#CCCCCC`; `text_primary/muted` | Reuse; supporting text still carries full meaning, not unreadable fine print |
| Disabled text | `#777777`; `text_disabled`; embossed off | Reuse with actual disabled state and textual reason nearby. Inactive decorative future note uses readable muted text, not a false disabled control |
| Primary action / text | `#FFC805` / black; `Primary.TButton` | Reuse; one primary per action region. Gold also denotes active hidden values and focus, never decorative status |
| Destructive action | `#D9363E` / white; `Danger.TButton` | Reuse only for actual destructive action, not ordinary failure/retry. C adds no deletion affordance |
| Focus | Gold on dark; white on gold/red fills; existing focus maps | Reuse with a discernible edge. C proposes a 2-logical-pixel outer cue where layout permits; measure against the adjacent outside surface as well as fill. White against gold alone is insufficient for a 3:1 claim |
| Borders / separators | Existing subtle `#2D2D2D` / `#2A2A2A` for grouping | Decorative only; a necessary interactive outline must meet 3:1 or gain a stronger focus/label cue. Prototypes use `#777777` outlines to make wireframe bounds inspectable; this is an existing palette color repurposed for research, not adopted runtime styling |
| Notice | `TOKENS.notices`: word, tint, accent bar and role | Existing neutral/info/success/warning/error/queued. Research SVG uses readable white warning text and gold outline; it is schematic, not a replacement notice palette |
| Space 4 / 8 / 12 | Semantic spacing `xs` / `md` / `lg` | Reuse. Semantic `sm` also equals 4; legacy raw `Spacing.XS` equals 2 and must not be confused with semantic xs |
| Section gutter / page gutter | 12 / proposed composed 16 (two 8 units); semantic xl is 24 | Compose existing units without changing TOKENS.xl. SVG's 16 px outer text inset is an artifact composition choice |
| Type | Segoe UI 10 pt body, 11 pt subhead, 12 pt bold heading | Reuse. SVG at 96 CSS dpi uses 13.333 / 14.667 / 16 px equivalents; actual Tk font metrics/scaling must be measured, not equated with CSS pixels |
| Control size | **PROPOSED** minimum 32 logical-pixel height, at least 32×32 pointer target, 8 gap | Minimum may grow with font request/padding; never fix widget height to 32. Longer labels wrap or move to next row. This is a desktop design target, not a change to supported hardware/platform or current measured metrics |
| Density | One ordinary density; details/disclosures reduce clutter | Do not reduce body font or hit target to solve a compact window. No new saved density preference or pin schema |
| Motion | Existing token durations 120/220/320 ms are available | No animation required for core tasks. Any future animation must not block input, hide a persistent warning or move a pressed target |
| Icon/state wording | Existing disclosure arrows plus plain words: Selected, Loading, Warning, Error, Missing, Unsaved, HOLD | Never icon/color alone. Icons accompany stable labels, have text alternatives where exposed, and do not imply evaluator/qualification status |

Proposed hierarchy: shell/workspace heading → panel heading → field label/value → supporting explanation. Long provenance uses vertical disclosure and copyable full text, never essential ellipsis with hover-only recovery. Tooltips supplement visible instructions; they are not the sole explanation for unavailable actions.

## Contrast verification boundary

Static checks calculate WCAG-style relative luminance/sRGB contrast for actual prototype pairs: white/gray on page/card, black on gold, gray outline on page/card and gold on dark. Targets: body/message text 7:1, ordinary role text at least 4.5:1, necessary outlines/focus 3:1. Disabled text follows the repository's 3:1 floor. The existing white-on-danger pair is checked against 4.5:1. White-on-gold focus is assessed separately; use the outside dark edge/additional cue rather than claim it passes against its fill.

Calculated ratios validate only color pairs. No WCAG conformance, UI Automation bridge, screen-reader announcement, actual focused pixels or operator accessibility verdict follows from this document or SVGs. High Contrast/forced-color behavior remains a Windows validation requirement.
