# Design system candidate (research tokens and specifications)

**Status: PROPOSED, research only.** No production styling, token or component changes. Today's authority is [GUI_STYLE_GUIDE](../../Subsystems/GUI/GUI_STYLE_GUIDE.md) (`design_values.py` → `ui_tokens.py` → `theme_v2.py`; metrics frozen: Segoe UI 10/11/12 pt, spacing 4/8/12). This document adds candidate rules for a possible redesign and marks where they differ.

## 1. Component taxonomy (candidate)

| Layer | Component | Exists today | Notes |
|---|---|---|---|
| Shell | Global bar, intent nav, workspace, anchored action bar, status drawer, asset tray | Header, `TaskNavigationBar`; bar/drawer/tray **do not exist** | See EXPERIENCE_ARCHITECTURE §2 |
| Page | Scrollable page (single scroll owner), fixed strip | `ScrollableFrame(fill_height=True)` + fixed Save strip (831) | Keep "a page scrolls; it never squeezes" |
| Disclosure | `DisclosureSection`, `TabOverviewPanel` | yes | Candidate cap: two levels |
| Input | Entry, combobox, slider, checkbox, source selector | yes (ttk) | Source selector inconsistent across tabs (hypothesis) |
| Action | Primary / Secondary / Ghost / Danger | yes | One Primary per surface already a rule |
| Feedback | `SubmissionNotice` (neutral, info, success, warning, error, queued) | yes | Role/accessible text contract exists |
| Media | `MediaInspector`, `VideoPreviewWidget`, gallery/list | inspector yes; **reusable gallery/list: no** (Review list, History table, Photo list, Learning grid are separate) | Candidate shared component with virtualization question (Qt/Tk) |
| Summary | Effective-settings / changes summary | read-only in Preview panel | Candidate: always beside primary action |
| Wrap | `FlowRow` | yes | Keep |

## 2. Layout and density

- **Minimum viewport target:** 1280×680 (the application's declared minimum; Windows clamps height to 680). Secondary targets: 1366×768, 1920×1080, 2560×1440; each at 100% and a *real* 125–150% display scale (not yet tested; EV-29).
- **Chrome budget (hypothesis):** fixed non-workspace height ≤ 20% at 680 px. **Measured today (EV-14, pixel script):** of the 719 px captured window (which includes ≈ 39 px of OS title bar/frame) global chrome is ≈ 36%; against the 680 px *client* height it is ≈ 33% (≈ 222 px), and on Learning the working pane starts ≈ 60% down and is ≈ 25% tall. The ≤ 20% budget is a client-height budget. Reaching 20% implies merging guidance/title rows and collapsing the Operator Log to a drawer (layout recommendation P2, P3). Re-measure with the same script before and after any change.
- **Declared minimum.** Determined by **measurement** (DR-A27): 680 px stays the compatibility baseline, 760 px is an additional comparison viewport (not adopted), each at 100%, 125% and 150% scaling. The goal is reachable controls and usable workflows through responsive layout, scrolling and progressive disclosure rather than requiring a larger monitor; P6 (raise the minimum) stays conditional on that measurement. Rule of thumb to test: working pane ≥ 300 px at the minimum (layout recommendation P2 target), versus ≈ 170 px on Learning today.
- **Modern appearance, defined by outcomes (owner, DR-A29):** task-first navigation and hierarchy; consistent typography, spacing, alignment and control styling; no clipped or unreachable controls; progressive disclosure; consistent status/validation/error feedback; keyboard accessibility, visible focus, appropriate contrast; responsive preview/review workspaces with minimal wasted space. Preserve the owner-stated Hybrid Create Image approach, automatic model-profile application with valid overrides preserved, and customizable basic controls with pinnable advanced settings (source not located in the repository, DR-O16).
- **Single scroll owner per workspace.** Nested scrollers (list inside canvas inside page) are allowed only if the wheel hands off at the limit (the shared router does this since 831) *and* the nested widget never fills the viewport (EV-16).
- **Secondary panes reserve no space when empty** (brief §5); an empty pane shows a one-line state, not a frame. The Learning null-grid fix (PR-831) is the precedent.
- Density tiers (hypothesis): Comfortable (default ≥ 1080 px height), Compact (≤ 768 px: single-column forms, summary strips). Selection by available height, not a user preference, to avoid a new settings scope.

## 3. Disclosure rules

1. At most two ordinary levels: always visible → one "More options" disclosure. 2. A control **required for admission** is never inside a collapsed disclosure; if a required value is hidden, the disclosure header names it and its state (the existing "img2img ON" header pattern). 3. Expert-only controls may nest one more level only inside an explicitly named *Expert* section. 4. Header text shows non-default hidden content (existing gold hint rule).

## 4. Typography and hierarchy

Keep Segoe UI 10/11/12 pt and gold-reserved-for-primary/selection/focus. Candidate addition: a *summary* style (11 pt, Body) for effective-settings strips, and a *status chip* style. No change to global metrics without before/after geometry on every tab (`test_design_foundation_400.py`).

## 5. Interaction states

Every interactive component defines: default, hover, pressed, focus (visible edge ≥ 3:1), disabled (**with a visible reason on demand**), selected, busy, error. Candidate rule new to this repo: a disabled primary action always exposes *why* (tooltip + inline line) — measured against the signal "disabled primary without understandable reason" (AI_GUIDED §6).

## 6. Validation and errors

Inline, next to the field and mirrored in the action bar summary; message = cause + next action; no modal for action results (existing rule). Admission errors name the field that is empty (the GP832-F4 lesson) and, for backend/model failures, the recorded cause (GP832-F1 lesson). Error text is bounded and path-free.

## 7. Media inspection

Keep `MediaInspector` behavior (Show, Detach, Fit, 100%, zoom/pan, hide on content-policy). Candidate: always show source-pixel vs preview-pixel label; same compare gestures for parent/child, A/B, before/after, and experiment cells.

## 8. Keyboard and accessibility

- Tab order matches visual order; a visible focus indicator on every control (Treeview gap documented). Keyboard reach of every mandatory control (GUI-COMPLETE-760 method).
- Assistive technology: Tk exposes **no per-widget accessibility tree** (0 of 31 UIA elements named in 742); Qt exposed 104 of 110. The owner has stated **no assistive-technology requirement today** (DR-A8); accessibility is therefore a measured secondary criterion, not a gate, and also not evidence *against* Qt.
- `SubmissionNotice.role`/`accessible_text()` is a programmatic contract only; no screen-reader claim.

## 9. Scope guard

Candidate tokens belong in a separate research folder until a prototype is authorized. A design system covering *every* widget family would repeat the audit's "do not rebuild the entire GUI" warning; recommended first scope is the shell, the action bar, the summary strip, the asset list/gallery and the notice/error pattern.
