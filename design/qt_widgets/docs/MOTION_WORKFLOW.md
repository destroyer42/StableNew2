# Motion & Video workflow (QT-DS-04)

An isolated, simulated Qt Widgets prototype of the artifact-centered **Motion & Video** destination.
Nothing here runs inference, encodes video, queues a job, builds an NJR, writes History or Storyboard
JSON, calls FFmpeg/Blender/WebUI or touches a network. Every result is an in-memory fixture
illustration of a still image, labelled **Simulated Clip — No Video Generated**.

Authority: `AGENTS.md` and `STATUS.md` win over this directory. Production capability claims below are
**fixtures that mirror the catalog at contract preparation**; they are not read from the application.
Research is linked, not copied:
[UX-850 research](../../../docs/research/stablenew-experience/README.md) and
[owner decisions UX-DEC-020…034](../../../docs/research/stablenew-experience/ux-850-r1/OWNER_DECISIONS.md).

## Three connected tasks

| Task | What you do | Terminal states |
|---|---|---|
| **Quick Clip** | Pick a source image fixture, write motion intent, choose a workflow version, review readiness, simulate, inspect variants, rate | success, refusal (illegal frames, missing media, unsupported control), recoverable |
| **Storyboard** | Author 2–12 shots with stable identities, explicit vs inherited fields, provided vs carried anchors; Save / Save As / Duplicate (in memory); simulate a sequence; reopen it as a **new** draft | success, refusal, stale-save conflict → Save As |
| **Movie Clips** | Select simulated clips, add, remove, reorder (never sorted), trim, pick a transition / imported audio fixture / export profile, simulate assembly | success, refusal (crossfade too long), recoverable (assembly failure keeps the list) |

Entry points: the **Motion & Video** navigation item (Ctrl+5), **Animate in Motion** on a Create result,
and **Animate in Motion** in Edit. A handoff carries *identity only* (source key + origin), never a
prompt, approval or consent.

## Architecture

```
motion_domain.py        pure (no Qt): fixtures, evaluation, MotionSession, playback math
motion_walkthroughs.py  pure: MOTION-01..07 as executable scripts
motion_components.py    Qt: reusable Motion widgets (also in the Component Library)
motion_view.py          Qt: MotionView, QuickPanel, StoryPanel (layouts A/B), MoviePanel
app.py                  navigation, handoffs, theme rebuild preserving state
```

- **State lives in `MotionSession`** (three `Authoring[T]` slots with undo/redo and revision numbers) plus a
  tiny `MotionUi` (mode, layout, selected shot). A theme switch or a Storyboard-layout switch rebuilds
  widgets from those two objects, so no draft state is lost.
- **Staleness** is `(revision, media fingerprint)`. A readiness summary is valid only for the exact draft
  and media it reviewed; any edit, a workflow change or changed media makes it *Stale*.
- **Consent** is bound to `(revision, media fingerprint)`, per submission, per kind. It is never
  inherited, never saved with a draft, never revived by returning to equal values (a regression test
  found and pinned this).
- **Summaries never claim a frozen NJR or frozen seeds.** The readiness panel says so in words.
- **Hidden media protection:** hidden, missing or unsupported media yields no pixels and no title in a
  refusal message; no substitute is ever chosen.

### Production facts mirrored as fixtures (not live)

Native SVD is a separate route (no motion prompt). Wan2.2 TI2V-5B **1.3.0** (picker default, frames-out)
and **1.2.0** are approved; **1.1.0**, Wan-Animate-2 and Fun Control are experimental (Fun Control is also
held for admission). LTX is retired and refused. Wan frame policy is 4n+1 in 17–81 at 24 fps. A Storyboard
has 2–12 shots; shot 1 uses the main source; a later shot with an authored keyframe uses a *provided*
anchor, otherwise it *carries* the previous last frame. A blank shot prompt inherits, an explicitly empty
one is refused. Later seeds resolve at admission. Movie Clips assembly is a separate CPU operation; list
order is movie order; a crossfade longer than half the shortest clip is refused. Strict resume applies only
to an unchanged plan and is explained, never offered here.

## Component catalog (Motion additions)

All appear in **Component Library → Components → "Motion · …"** over fixtures, in both themes.

| Component | Role | Reuses |
|---|---|---|
| `MotionSourceSelector` | Explicit media identities with availability shown before selection; no pixels; restricted titles masked | `QComboBox` pattern of `SourcePicker` |
| `WorkflowCapabilityBadge` | Governance chip + route + declared controls + frame policy + note | `StatusChip` |
| `StoryboardShotCard` / `ShotStrip` | Ordered, keyboard-navigable cards (arrows, Home/End, Enter/Space); wrap instead of scrolling; selection, validity and basis words not colour alone | theme `role=shot` |
| `ShotTimeline` | Order / approximate-duration / dependency illustration, not a precision editor | – |
| `SequenceReadinessPanel` | Status chip, revision, facts, per-shot lines, issue banners | `IssueList`, `NoticeBanner` |
| `SimulatedClipViewer` | Play/pause/restart/scrub over fixture frames; timer runs only while playing and visible | – |
| `ClipAssemblyList` | Ordered clips, move/remove, trim intent; never re-sorts | `ResponsiveGrid` |
| `QualityRatingPanel` | Action outcome (a fact) separate from optional operator impression; never sent to Learning | – |
| `MotionActionStrip` | Review / Inspect / Send / Simulate with a mode-dependent primary label | `ActionStrip` |
| `ElidedLabel` | Single-line middle-elided label; full text in tooltip and accessible description | – |

Generic pieces (`ElidedLabel`, `ShotStrip`, `SimulatedClipViewer`) are deliberately free of Motion domain
imports beyond the media catalog so they can be reused.

## Theme and component integration

- All colour, spacing and font values come from theme tokens (`tokens.py`/`theme.py`); the package-wide
  guard test forbids hex literals, `QColor` literals and font literals outside `theme.py`.
- One new stylesheet family was added: `QFrame[role='shot']` with hover, focus, `invalid` and `selected`
  states. Hover and focus never change border width, padding or minimum height (checked by the theme
  consistency tests).
- Both reference themes (`blue-modern`, `concept-a`) are exercised by native tests and screenshots, and a
  theme switch is tested to keep the session, selected shot, mode and review status.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Primary Storyboard layout | **A · Shot strip** | Shows thumbnails, basis and validity at a glance, needs less vertical room at the minimum size (42 px page scroll vs 84 px), and keeps the strip next to the selected shot's inspector. See [MOTION_LAYOUTS](MOTION_LAYOUTS.md). |
| Alternative kept | **B · Timeline** (selectable) | Better for judging relative durations; costs ~170 px of height. Kept as a comparison, not the default. |
| Page scrolling | One vertical scroller around the workspace; the action strip stays outside it | A 600 px window cannot hold the chrome plus a usable viewer; vertical scrolling is accessible, horizontal overflow is not. |
| Cards elide, never wrap | Fixed single-line labels | Height-for-width of wrapped labels made the strip height unpredictable. |
| Workflow combo data | String token `id@version`, never a tuple | Qt round-trips tuples as lists and silently lost the selection (found by a screenshot). |
| Handoff conflicts | Cancel is the default | A draft is never silently replaced; Replace starts a fresh, unapproved draft. |

## Honest limits

- Illustrations are camera moves over still fixtures. They say nothing about real Wan/SVD motion quality.
- Real 125 % / 150 % Windows scaling is **unverified**; `QT_SCALE_FACTOR` runs are labelled *simulated*.
- No screen-reader accessibility is claimed. Accessible names are set and tested for presence only.
- Audio is imported-fixture selection only: no generation, mixing, captions, titles, lip-sync or effects
  (UX-DEC-025/027 remain design work).
- No persistence: Save / Save As / Duplicate are in-memory, so autosave, crash recovery, named checkpoints
  and portable packaging (UX-DEC-033/034) are not demonstrated.

## UX-DEC-020 … 034 traceability

| Decision | Demonstrated here | Evidence | Not demonstrated |
|---|---|---|---|
| 020 Hybrid artifact-centered Motion | Dedicated destination + *Animate in Motion* from Create and Edit; identity-only handoff | `test_qt_motion` handoff tests, MOTION-02 | Gallery/History entry points (no such surface in the prototype) |
| 021 Hybrid authoring | Free-text intent + guided settings (workflow, frames, seed, variants); no AI assist | MOTION-01, `QuickPanel` | Optional AI assistance |
| 022 Hybrid clips and storyboards | Quick Clip and a 2–12 shot Storyboard sharing one source/workflow vocabulary | MOTION-01/03 | Production Storyboard JSON |
| 023 Shared continuity profiles | Not implemented; carried vs provided anchors show the continuity *mechanism* only | `StoryboardShotTests` | Reusable character/setting/style references |
| 024 Hybrid storyboard + timeline | Layout A strip + Layout B timeline illustration | MOTION_LAYOUTS | Precision timeline editing |
| 025 Audiovisual composition | Imported audio fixture selection only | MOTION-06 | Titles, dialogue, captions, effects |
| 026 Imported / AI audio | Imported fixtures (incl. a missing one refused); no generation | `test_audio_fixture_selection` | AI audio |
| 027 Dialogue / lip sync | Not implemented | – | Everything |
| 028 Hybrid temporal editing | Non-destructive: results immutable, edits create new candidates; trim is intent only; reopen is a new draft (H8) | MOTION-05, `test_h8_*`, `test_trim_*` | Qualified temporal regeneration |
| 029 Hybrid temporal guidance | Motion prompt, optional motion-reference fixture, authored anchors (keyframes), per-shot frames | `test_required_motion_reference…` | Time ranges |
| 030 Hybrid experiments | 1–N independent variants, run-to-run diff, fixture failure drill | `test_variants_*`, `test_diff_*` | Structured parameter sweeps, AI assistance |
| 031 Evidence-informed evaluation | Separate action outcome vs 1–5 impression; never sent to Learning | `test_ratings_never_change…` | Qualified measurements, AI critique |
| 032 Hybrid deliverable profiles | Recommended + alternative export profiles with compatibility refusal | `test_export_profile_compatibility` | Real encoding |
| 033 Autosave and versions | In-memory Save / Save As / Duplicate with stale-save conflict; undo/redo | `test_stale_save_conflict…` | Autosave, crash recovery, named checkpoints |
| 034 Linked / portable projects | Media are linked by identity + digest; changed media require explicit acceptance | `MediaChangeAndAcceptanceTests` | Verified portable packaging |

Where this table says *not demonstrated*, the prototype makes no claim, and the owner decision remains
open design work for later packages.
