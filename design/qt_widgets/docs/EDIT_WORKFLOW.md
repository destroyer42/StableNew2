# Edit & Improve prototype

Edit & Improve explores the J2 journey from an explicit image source to a reviewed, illustrated
candidate. Open it with **Ctrl+4** or the workspace navigation. Drafts, masks, previews, candidates
and Working Baselines live for the open window. The Component Library demonstrates the picker,
canvas, zoom and side-by-side comparison independently of the workflow.

## Operator walkthroughs

| Journey | Actions and expected observation |
|---|---|
| **EDIT-01 · Quick Edit** | In Create, build a Preview, simulate admission and choose **Edit linked fixture** under Mock result. Edit opens `create:ridge-study` with **Not built** status and no admission permission. Keep **Quick Edit**, choose Foreground, enter “Warm the valley”, build Preview and confirm its source, region and settings. **Simulate Admission** opens a labeled source/result pair for `edit:candidate-1`. |
| **EDIT-02 · Masked Edit** | Choose the History fixture `history:ridge-17` and **Masked Edit**. Select **Brush** and drag over the foreground, then erase part of the mask. Check the coverage count and pixel readout. Undo and redo a stroke. Enter an edit prompt. Under **Advanced settings**, adjust Feather and inspect the softened overlay. Build Preview, simulate admission and compare with the recorded direct source. **Inspect recorded source parent** compares the separate `history:ridge-16` → `history:ridge-17` fixture pair. |
| **EDIT-03 · Extend Canvas** | Select Photo Optimize's evening candidate. Choose **Extend Canvas**, set Left to 72 px and Top to 48 px, leave Right at 32 px, and enter “Continue the evening sky”. The source frame remains 600×400, placed at (72, 48) inside a 704×448 illustration. Preview the settings and simulate admission. The result uses striped extension bands to distinguish the placement illustration from generated content. |
| **EDIT-04 · Compare and iterate** | After an admission, choose **Back to Draft**, open Advanced settings and change strength. The previous Preview is **Stale** and the previous candidate remains inspectable. Rebuild Preview and simulate again. In Candidates, choose the earlier candidate in **Compare with** to inspect the sibling pair and changed settings. Select either record and explicitly **Set Working Baseline**. The baseline label changes for that source. Preferred / Final remains empty. |
| **EDIT-05 · Refuse and recover** | Try Missing still, Restricted still and Imported clip. Read each refusal and verify the current draft or empty canvas is retained. Open the imported coast, choose Extend Canvas and set all margins to zero. Build Preview and observe **Blocked**. Attempt to switch sources and click **Cancel** to preserve the draft. Switch to Masked Edit and try the simulated suggestion in Advanced settings. The imported fixture refuses the suggestion and leaves Brush and Erase available. Repair the geometry or paint a mask, enter a prompt and rebuild Preview. Change a setting after building to see the stale refusal. |

## Gesture and identity semantics

- **Fit to Window**, **100%**, **Zoom in** and **Zoom out** use the same vocabulary in Edit and Compare.
  At 100%, one source pixel spans one logical display pixel. Drag in Pan mode or middle-drag in
  any tool. Ctrl+wheel zooms the Edit canvas. Plain wheel is
  reserved for scroll behavior. Comparison uses its shared zoom buttons, with independent panning.
- The canvas inverts the current fit/zoom, placement and pan transform in widget logical pixels.
  Source coordinates are zero-based and right/bottom exclusive. Brush radius is in source pixels.
  A stroke sweeps between pointer samples and clips to source bounds. Release commits a single
  revision. Escape, focus loss or resizing cancels an unfinished stroke. Coverage counts binary
  source pixels before the optional visual feather approximation. The source image is read-only.
- **Alt+Z** and **Alt+Y** step through draft changes, including committed strokes. **Ctrl+Enter**
  builds Preview. Tab and Shift+Tab traverse the visible, enabled controls. Source or mode changes
  retain the relevant draft only as specified by the replacement choice. **Keep draft** opens the
  existing draft, **Cancel** leaves navigation as it was and **Replace draft** opens the new source.
  Switching workspaces retains edits. Comparison has an explicit return to the editable draft.
- The two named regions hold separate prompts, settings and masks. A Preview uses one region.
  When available, **Try simulated suggestion** shows a deterministic overlay you can inspect,
  revise with Brush/Erase, accept as a mask, or reject. An unresolved suggestion blocks Preview and
  simulated admission. Region or draft changes discard a suggestion tied to an older revision.
- Preview reports **Not built**, **Stale**, **Blocked**, **Current / ready**, or **Simulated admission
  recorded**. Undo and Redo advance the revision. Returning to old settings still requires a
  new Preview. A late mask or Preview cannot replace a newer revision. Repeated activation on the
  same revision yields one candidate. The receipt freezes source, selected region, mode and
  settings. Candidate comparisons use explicit identity. Two sibling candidates must share a
  recorded source. An imported image has unknown earlier ancestry.
- Reference theme changes restyle Edit in place. They preserve the draft, zoom/pan context, selected
  region and undo stack. Edit hides the Create-only Output Display while its own viewer is active.

## Layout choice and Windows evidence

**Default A · Editor-centered.** Source and mode share the heading above a large canvas. A
hideable, resizable inspector separates Settings, Preview and Candidates. The action strip
stays outside the inspector scroll area. Comparison replaces the canvas in the same stage.

**Alternative B · Adjustable inspector.** Run with `--edit-layout inspector` to put source
and mode in a dedicated left rail. It keeps those controls grouped and saves 2 px of height
at each size. The extra rail costs 204 px of canvas width at every measured size. At 960×600
it reduces the canvas from 482×263 to 278×265, which leaves a much smaller fitted image.
At 1280×680, A provides 770×343 compared with 566×345 in B. Both layouts needed no scrolling
to reach Advanced at 1280×680. A therefore keeps the source controls in the heading and
allocates the width to the image.

| Native Windows client | A canvas | B canvas |
|---|---:|---:|
| 960×600 | 482×263 | 278×265 |
| 1280×680 | 770×343 | 566×345 |
| 1366×768 | 856×431 | 652×433 |
| 1440×900 | 925×563 | 721×565 |
| 1920×1080 | 1354×743 | 1150×745 |

Both reference themes produced the dimensions above. In 20 native masked-edit layout cases,
all client sizes matched their request. The probe found no clipped persistent controls,
horizontal inspector overflow or missing enabled Tab stops. Advanced was reachable with up to
70 px of vertical scrolling at 960×600. The native interaction tests cover keyboard selection,
Tab and Shift+Tab, focus, pointer gestures, wheel behavior, replacement, mask cancellation,
resize, theme switching and window destruction. These are scripted walkthroughs and reachability
measurements. Operator preference and task-time comparisons still need human sessions.

Windows Python 3.14.9 and PySide6 6.12.0 used the native `windows` platform on a 2560×1440
display with DPR 1.0. A separate 1280×680 run used `QT_SCALE_FACTOR=1.5` with DPR 1.5 and
reported no clipping or missing enabled Tab stops. Actual scaled monitors and screen-reader
navigation remain unverified.

- Native measurements for [Blue Modern](evidence/edit_native_blue-modern.md) and
  [Concept A](evidence/edit_native_concept-a.md)
- [Simulated 1.5× measurements](evidence/edit_SIMULATED-scale-1.5_blue-modern.md)
- [Masked Edit at 1280×680](screenshots/qt-ds-03/edit_blue-modern_editor_1280x680_masked.png) and
  [Concept A at 960×600](screenshots/qt-ds-03/edit_concept-a_editor_960x600_masked.png)
- [Alternative B at 1280×680](screenshots/qt-ds-03/edit_blue-modern_inspector_1280x680_masked.png)
- [Extend Canvas](screenshots/qt-ds-03/edit_blue-modern_editor_1280x680_extend.png),
  [comparison](screenshots/qt-ds-03/edit_blue-modern_editor_1280x680_compare.png) and
  [blocked geometry](screenshots/qt-ds-03/edit_blue-modern_editor_1280x680_blocked.png)

## Decision traceability and boundary

| Decision | Demonstration and remaining boundary |
|---|---|
| UX-DEC-007/007A, 011 | A Create result explicitly opens its linked still fixture. The picker covers Recent Create, History, imported and Photo Optimize identities. Each destination starts with its own Preview. Full gallery actions and durable staging are separate product work. |
| UX-DEC-012 | Brush and Erase are available without assistance. The editable suggestion is synthetic. Actual Smart Review model behavior and quality require their own evidence. |
| UX-DEC-013 | Mask coverage and illustrative feather are visible. Canvas extension exposes exact target and placement. Production Review outpainting has a scoped restoration contract. The mock illustrations establish no generated-output preservation. |
| UX-DEC-014 | Foreground and Background store independent intent. Combining regions in executable work needs a compiler and preservation contract. |
| UX-DEC-015 | Inspect a frozen candidate beside its recorded source or compare two siblings. Production History supports verified direct pairs for applicable still-image jobs. A durable edit tree and arbitrary comparisons remain proposed. |
| UX-DEC-016 | An explicit, source-scoped Working Baseline changes only the mock selection. Production Photo Optimize owns managed baseline promotion. Cross-source Preferred / Final needs its own metadata decision. |
| UX-DEC-017 | Preview and candidate review are explicit checkpoints between iterations. Multistep plans and downstream approvals remain future design. |
| UX-DEC-018 | Branch candidates keep independent frozen settings and identities. Refused or stale attempts leave prior candidates intact. There is no execution lifecycle in the prototype. |
| UX-DEC-019 | Refusals name the fixture or invalid input and retain recoverable draft intent. Runtime diagnostics and restart recovery require the existing service owners. |
| UX-DEC-035–040 | Scoped fixture namespaces, availability-aware selection and explicit handoffs inform later asset discovery. Global indexing, grouping, search, ingest and disposition are outside this workspace. |

Research anchors are [J2 and H3/H9](../../../docs/research/stablenew-experience/ux850-b/README.md),
[component roles C03–C11](../../../docs/research/stablenew-experience/ux850-c/COMPONENTS.md),
[draft and approval contracts](../../../docs/research/stablenew-experience/ux850-d/DRAFT_SUBMISSION_CONTRACTS.md)
and the [delivery map](../../../docs/research/stablenew-experience/ux850-f/DECISION_DELIVERY_MAP.md).
The production reference is [Photo Review and Reprocess](../../../docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md)
sections 3.3–3.3.2, 3.5–3.6 and 6.4–6.6. Real Review compiles and validates a frozen supported edit
before queue admission. Photo Optimize owns real baseline writes. Compare with Parent validates
recorded lineage and image identity. Any production integration requires those owners, an approved
Qt integration decision and evidence for the relevant model/backend and hardware.
