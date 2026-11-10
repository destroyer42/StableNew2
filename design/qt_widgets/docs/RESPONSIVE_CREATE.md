# Responsive Create Image

QT-DS-02 refines the standalone Qt Widgets prototype. Follow the [operator walkthrough](WALKTHROUGH.md#4-create-image--the-mock-journey) to exercise the whole simulated flow.

## Comparison and decision

The QT-DS-01 source at **63dbde82e8ce3d119ac0d730a134aa30249ff5ad** merged in
[PR #273](https://github.com/destroyer42/StableNew2/pull/273). The checkout base
**f8f91c13deabeb7c5ecfa22aa93f2914577df4ab** carries the same prototype bytes. Before editing,
the Windows audit measured the baseline and captured its original default with the Output Display expanded.
The table also includes the [matched collapsed-dock baseline measurements](evidence/qt-ds-02-baseline.md).

| Layout, 1280×680 actual client | Authoring viewport | Authoring content height | Initially visible controls | Scroll moves / pixels to primary actions | Readiness / summary / both actions initially visible |
|---|---:|---:|---:|---:|---|
| QT-DS-01 split, dock expanded | 407×402 | 2,434 px | 6 / 15 | 3 / 1,283 | Yes / Yes / Yes |
| QT-DS-01 split, dock collapsed | 647×427 | 2,075 px | 7 / 15 | 2 / 1,155 | Yes / Yes / Yes |
| A. Compact vertical form, dock collapsed | 980×460 | 1,334 px | 9 / 15 | 1 / 167 | Yes / No / Yes |
| B. Responsive split, dock collapsed | 330×460 | 586 px | 15 / 15 | 0 / 0 | Yes / Yes / Yes |

The counts include the 11 named form and action controls and four basic setting editors, including disabled
actions. The scroll probe visits the same six targets in each layout (source, prompt, model, steps, Preview,
admission). It moves each viewport as needed to fully reveal a target. The baseline probe used its 8 px focus
margin. The current probe measures the minimum move with zero margin. Pixels are Qt logical client pixels.
The result inspection was exercised separately by building and admitting a mock preview. Counts describe
a scripted path and geometry. Operator time and error rates remain unmeasured.

**Choose B.** At 1280×680 the authoring column keeps the source, multiline prompt and model/profile in view.
Its settings and review viewports are 315×460 and 295×460, with 479 px and 473 px of content in the initial state.
The primary controls fit without a page scroll. Advanced prompt channels, settings details and the extended
review can scroll independently. Building Preview takes the inspector to its summary. Simulating admission
reveals the receipt in the inspector while leaving authoring in place. A gives text and advanced controls a wider
canvas and uses a single vertical scroll. Its effective review is below the form, so reaching it moves the prompt
and model out of view.

At an actual **960×600** client, B keeps a 241×355 review viewport and stacks settings after prompt and model
in the 399×355 authoring viewport. One scripted move of 272 px reaches the core task controls, down from three
moves and 1,363 px on the matched baseline. A uses one move of 272 px and buries the summary. At 1366×768 and
1920×1080, B also reaches the common tasks with zero scroll moves. These are prototype evaluation sizes.

## Responsive specification

- The split workspace opens by default. At a Create view width of 930 logical pixels, settings get their own
  pane. Below that width the same settings widgets move into the authoring pane, with review on the right.
  The handles let an operator redistribute space within the pane minimums. Opening the optional Output Display
  can trigger compact layout. The collapsed default leaves space for authoring.
- The heading shows Preview state and the top notice shows the first blocking draft issue or stale state.
  The footer keeps Preview and Simulate admission in reach. The inspector lists all draft issues, displays
  the effective settings and snapshot, and reports mock receipt provenance. The footer counts draft warnings.
- Details disclose the working pack name, negative text, slots and resolved text. Advanced generation
  settings disclose sampler, scheduler and exact dimensions. Additional channels keep their own disclosure
  and show which extras are in use.
- A model transition preserves locked and differing manual values. The unsupported setting is kept and
  labelled in the selector and draft issues until the operator changes it. Fixture options come from the
  same pure domain as validation. Uncharacterized sizes and Learning-informed assumptions appear as warnings.
- The mock session owns the draft and undo history. Resizing and disclosure keep the same controls and data.
  Applying a theme rebuilds the view from the same session. Preview and receipt use the existing fingerprint
  and draft revision. Repeating admission for the same current preview reuses its receipt.
- A is available at launch with **--layout scroll** for design comparison. The prototype has one default and
  saves no layout preference.

## Components and theme

| Area | Reused component and change |
|---|---|
| Prompt and selectors | SectionCard, FormTextEdit, ResponsiveGrid, stacked labels and shared wheel guard |
| Settings | Shared SettingField positions lock above the editor and reset next to textual provenance. The component gallery and Theme Studio exercise the same field. |
| Progressive disclosure | Shared Disclosure for prompt details, optional settings, channels and the change log |
| Readiness and issues | Shared StatusChip, NoticeBanner and IssueList, with persistent draft diagnostics |
| Review and actions | FormTextEdit, ResultGallery, ActionStrip and standard Qt splitter/scroll containers |
| Theme | Blue Modern and reconstructed Concept A use the existing semantic stylesheet, SVG assets, contrast checks and Theme Studio library. |

## Decision traceability

| UX-850 authority | Demonstrated in Create |
|---|---|
| J1 C1–C2 · UX-DEC-001/002/005 | Prompt and PromptPack fixtures, editable slots, visible model/profile, recommendation and override provenance |
| J1 C2–C3 · UX-DEC-003/005A/008 | Basic controls, optional detail, draft locks, explicit resets and Undo. Pinning, production save scope and restart recovery remain open. |
| J1 C3–C5 · UX-DEC-004/009 | Effective configuration, material-change log, draft issues, explicit Preview and simulated admission. Production confirmation policy remains gated. |
| J1 C6–C7 · UX-DEC-007/007A | Revision-labelled simulated receipt and tiles, continued draft iteration or reset. Artifact identity and Edit handoff need their own evidence. |

This uses UX-850-A's capability-gap distinctions, UX-850-B's J1 journey, UX-850-C's component roles,
UX-850-D's state boundaries, UX-850-E's distinction between fixtures and Learning evidence, and UX-850-F's
Create provenance direction. The [owner decision register](../../../docs/research/stablenew-experience/ux-850-r1/OWNER_DECISIONS.md)
and [J1 journey](../../../docs/research/stablenew-experience/ux850-b/JOURNEYS.md) remain the research records.

## Evidence

[Baseline capture](screenshots/qt-ds-02/baseline_1280x680.png) ·
[A at 1280×680](screenshots/qt-ds-02/vertical_1280x680.png) ·
[B with keyboard focus](screenshots/qt-ds-02/split_1280x680_focus.png) ·
[B blocked](screenshots/qt-ds-02/split_1280x680_blocked.png) ·
[B simulated receipt](screenshots/qt-ds-02/split_1280x680_result.png) ·
[B at 960×600](screenshots/qt-ds-02/split_960x600.png)

| Evidence | Coverage |
|---|---|
| Pure mock tests · 176 passed | Model/profile transitions, locks, resets, slot expansion, incompatible options, Undo/Redo, stale refusal and idempotent receipt |
| Native Qt regression · 100 passed | Window lifecycle, state retention through resize/layout/theme changes, shortcuts, visible focus, wheel guard, anchored actions, Theme Studio, blocked state and receipt |
| [Blue Modern](evidence/qt-ds-02-native-blue.md) and [Concept A](evidence/qt-ds-02-native-concept.md) | Native Windows at 96 logical DPI and device pixel ratio 1.0. Each covers A and B in fresh and primed states at 960×600, 1280×680, 1366×768 and 1920×1080. No clipped text, horizontal overflow, unreachable required controls or keyboard misses in these cases. |
| [1.5× simulation](evidence/qt-ds-02-simulated-1.5.md) | Eight cases at 960×600 and 1280×680 with **QT_SCALE_FACTOR=1.5**. This is Qt emulation on the same display. |
| Prototype isolation | Tests refuse network/process access and verify import boundaries while running the simulated flow. The repository guard checks both directions of the workspace boundary. |

Reproduce from the prototype root with Python 3.14.9 and PySide6 6.12.0 on Windows. Run
**tools/layout_audit.py --out captures --docks collapsed --sizes 960x600 1280x680 1366x768 1920x1080**.
Use **--theme concept-a** for the second preset and **--scale 1.5** for Qt scale emulation.

Real per-monitor DPI, screen readers, forced colors and operator task performance remain unverified. Concept A
remains reconstructed. Simulation establishes no model, execution, or toolkit qualification. For QT-DS-03,
check the Create-to-Edit handoff against the explicitly labelled fixture receipt and measure focus and geometry
after the Edit workspace takes over.
