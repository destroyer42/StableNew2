# QT-DS-04 test and acceptance report

Branch `design/qt-ds-04-motion-workflow`, based on `origin/main` `802cfdac`. Windows 11, Python 3.14.9,
PySide6 6.12.0, native `windows` Qt platform, screen DPR 1.0.

## Test counts

| Suite | Result |
|---|---|
| Whole `design/qt_widgets/tests`, pure (Qt tests skip) | 421 collected · 276 run · 145 skipped · **OK** |
| Whole suite with `STABLENEW_QT_PROTOTYPE_TEST=1` (native) | 421 run · **OK** |
| `tests/test_motion_domain.py` (pure Motion domain + walkthroughs + playback math) | 90 tests |
| `tests/test_qt_motion.py` (native Motion interaction + geometry) | 36 tests |
| `tests/test_independence.py` | Motion flow added: all seven walkthroughs + the assembly-failure drill run with production modules, numpy, PIL, sqlite3, sockets and subprocess blocked, and assert that no `PySide6` module was loaded |
| Repo guard `tests/system/test_qt_design_workspace.py` (StableNew `.venv`) | 4 passed |
| `ruff check` / `ruff format --check` on `design/qt_widgets` | clean |

The domain tests are deterministic (no clocks, randomness or I/O) and cover the work package's list:
workflow identity and governance, capability-declared controls, source provenance and immutability,
frame and seed rules, shot count boundaries, shot identity across reorder/duplicate/remove, blank-vs-empty
prompts, explicit-vs-inherited marks, provided-vs-carried anchors, changed-media acceptance, draft
revisions with undo/redo, in-memory Save / Save As / Duplicate and stale-save conflicts, per-job consent,
summary-vs-admission and staleness, result identity and variant independence, handoffs (including H8
reopen as a new draft), Movie Clips ordering/trim/transition/audio/profile rules, assembly results with
their own identity, and isolation. Two real defects were found by these tests and fixed: consent could be
revived by returning to equal values, and a Storyboard media fingerprint omitted anchors on shot 1.

## Walkthroughs (executable, `motion_walkthroughs.run_all()`)

| Key | Outcome | Terminal state |
|---|---|---|
| MOTION-01 Quick Clip | success | mock-run-1 completed with 2 simulated clips |
| MOTION-02 Create/Edit handoff | success | source identity kept; unsaved draft protected; fresh preview ready |
| MOTION-03 Storyboard | success | four segments in authored order |
| MOTION-04 Consent and compatibility | refusal | unsupported SVD prompt refused; consent never inherited |
| MOTION-05 Sequence review and iteration | success | candidates mock-run-1 and mock-run-2 coexist |
| MOTION-06 Movie Clips | success | mock-movie-1 illustrated, not encoded |
| MOTION-07 Failure and recovery | recoverable | every failure explained with a way forward; no state lost |

The same paths are driven through real widgets (clicks, key presses, modal choices) in `test_qt_motion`.

## Acceptance against the work package

| Requirement | Result | Evidence |
|---|---|---|
| Quick Clip, Storyboard, Movie Clips navigable | Met | `test_qt_motion`, screenshots |
| Shared components; new generic components in the Component Library | Met | `gallery.py` "Motion · …" sections |
| Both themes work; theme switch keeps drafts | Met | `test_theme_switch_keeps_session_and_view_state`, `test_every_mode_works_in_the_second_theme` |
| ≥ 2 layouts at five sizes; primary chosen | Met (A primary) | [MOTION_LAYOUTS](MOTION_LAYOUTS.md) |
| No inaccessible horizontal overflow; no shrunk text/controls | Met at all measured sizes | `horizontal_overflow_px` empty, `shrunk_controls` 0 |
| Walkthroughs ≥ 7 | Met | above |
| Experimental consent per job, never inherited or saved | Met | `ConsentTests`, MOTION-04, native consent test |
| Summaries never claim a frozen NJR or seeds | Met | readiness panel text asserted in `test_storyboard_review_simulate_and_h8_reopen` |
| No production imports / jobs / NJRs / History / persistence / FFmpeg / network | Met | `test_architecture`, `test_independence`; see isolation below |

## Isolation verification

- `test_architecture` scans every package source for forbidden imports and persistence names; the Motion
  modules pass it. `motion_domain.py` imports only the standard library and `edit_domain`.
- The independence child interpreter blocks production runtimes and I/O, runs all walkthroughs, and fails if
  Qt is loaded by the pure Motion path.
- No file is written by Motion: Save / Save As / Duplicate use an in-memory store. The evidence tools write
  only to `--out`.
- `presets/settings.json` (an unrelated local modification in the user's main checkout) is untouched; this
  work lives in a separate worktree cut from `origin/main`.

## Simulated, unverified and held capabilities

- **Simulated:** all clips, sequences, movies and ratings; playback is a camera move over a still fixture;
  fixture history runs; failure drills; the `QT_SCALE_FACTOR=1.5` audit.
- **Unverified:** real Windows 125 % / 150 % display scaling; screen-reader behaviour (only accessible
  names are checked for presence); real Wan/SVD motion quality; production catalog drift since the
  fixtures were written.
- **Held / not built:** continuity profiles, titles/dialogue/captions/effects, audio generation, lip sync,
  autosave and portable packaging, precision timeline editing, AI assistance and critique
  (see the UX-DEC table in [MOTION_WORKFLOW](MOTION_WORKFLOW.md)).

## Owner decisions still open

1. Whether Layout B should remain selectable or be removed once a timeline editor is designed.
2. Whether *Animate in Motion* should also exist on a future Gallery / History surface.
3. The fixtures' production facts must be re-verified against the live catalog before any real integration.
4. How much of UX-DEC-023/025/027 (continuity, audiovisual composition, dialogue) belongs in QT-DS-05.
