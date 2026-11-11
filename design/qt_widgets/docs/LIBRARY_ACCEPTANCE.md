# Asset Library acceptance, test evidence and limits (QT-DS-05)

Companion to [LIBRARY_WORKFLOW](LIBRARY_WORKFLOW.md) and [LIBRARY_LAYOUTS](LIBRARY_LAYOUTS.md).
Production Qt ancestry: this is a standalone design prototype under `design/qt_widgets/`. It is not a
production Qt migration, not a toolkit decision, and not a second Library, History or catalog authority.

## Test evidence

| Suite | What it proves | Result |
|---|---|---|
| `tests/test_library_domain.py` (pure, Qt-free) | identities kept separate; immutable fixtures; AND/OR filter semantics; pagination bounds; selection order; collections, tags, favorites and undo/redo; exact and illustrative groups; per-action eligibility and whole-selection preflight; propose/commit (PLACED, CANCELLED, REFUSED, STALE); learning proposal is non-executable; return context; LIB-01..08 | 58 tests pass |
| `tests/test_independence.py` | the Library walkthroughs run in an isolated interpreter with `src`, Tk, SQLite, `requests`, sockets, subprocesses, NumPy and PIL blocked, and **no PySide6 module is loaded** | passes |
| `tests/test_architecture.py` | no import of `src`, controller, pipeline, queue, history, Tk, network, subprocess, SQLite, torch, diffusers, ctypes or `webbrowser` in the package | passes |
| `tests/test_qt_library.py` (native Windows, opt-in) | grid and list share one model and one ordered selection; bulk catalog stays one bounded page; keyboard navigation, selection, inspect, clear; Ctrl+A; Shift range; search shortcut and typing; semantic search shown unavailable; no-matches names the scope and does not widen; clear filters keeps scope, sort and selection; collection create/add/remove, tag, favorite, undo/redo; blank and duplicate names refused; context menu selects an unselected item; disabled actions show a reason; hidden/missing block handoff; general archive and delete are gated and change nothing; Library → Edit with place, cancel and replace; Library → Motion; learning proposal stays in the Library; stale destination refused; **blocked media never reaches an injected recording decoder**; loading / error / ready states; simulated vanish and restore; theme switch keeps session, selection and view mode; five window sizes × two layouts keep every action reachable; narrow inspector page; Tab order; accessible names; dispose and reopen; a 1,528-record catalog keeps the widget count constant; similarity label; direct-parent comparison only; the Component Library keeps working | 43 tests pass natively (42 Library + 1 Component Library) |
| Existing prototype suites | Create, Edit, Motion, Output Display, Theme Studio and smoke tests unchanged | 526 tests (native, 15 min): 525 pass; `test_keyboard_focus_is_always_scrolled_into_view` (Create, split) failed in 2 of 2 full-suite runs but passes alone and in its own file in 8 of 9 runs and 4 of 4 on the baseline. Cause not isolated; unresolved timing sensitivity |
| Repository PR gate | `python tools/ci/run_pr_gate.py` | `PR gate OK` (completeness, controller ratchets, Ruff, mypy, architecture ratchets, 16,301 collected, 397 smoke passed) |

Defects the tests found while they were written (kept as regression tests):

- A filter combo handed its `StrEnum` data back as a plain `str`, so the first filter change crashed the
  results header. `query_changes` now restores `SearchMode`, `Sort`, `AssetKind` and `Availability`.
- The unsupported-type reason was being shadowed by the "Edit works on still images" reason.
- A stale details-panel label overlapped the next asset's facts; widgets are now hidden and unparented
  before deletion.
- Persistent combo text was clipped ("Any collectio", "Any availabil"); texts were shortened, the filter
  grid column minimum raised, and the layout probe now measures text clipping for every visible control.

## Isolation evidence

- The package imports nothing from `src/`; `src/` does not reference the workspace (repo guard test).
- No file is read or written by the Library. The only pixel source is four packaged fixture illustrations
  (`default_decoder`); there is no `open()`, no directory walk and no dialog that picks a path.
- PySide6 was **not** installed into the StableNew production virtualenv; the existing
  `gui-port740-env` was reused.
- `presets/settings.json` and `STATUS.md` were not touched by this work.
- No production controller, coordinator, queue, History or Learning code was changed. The three
  `adopt_*` methods added to the Create, Edit and Motion *prototype* views only mirror a draft the Library
  already placed into that prototype's own session.

## What is demonstrated, simulated and unverified

| Demonstrated (tests + measurement on this machine) | Simulated (fixtures) | Unverified |
|---|---|---|
| Ordered selection, grid/list, paging, filters, collections and undo on one in-memory model | Every record, hash, observation, collection and group | Operator benefit, task time or error rate |
| Whole-selection preflight; cancel/refuse/stale mutate nothing; no inherited approval or consent | Photo-style archive (a visibility flag) | Real 125/150% and mixed-DPI scaling; screen readers; High Contrast |
| Hidden, missing and unsupported media never decoded | Learning proposal (a value, not a study) | Behaviour on a real catalog (tens of thousands of records), real thumbnails, real I/O latency |
| Return to the same scope, filters, sort, page, selection, view mode, tab and scroll | Loading and read-error states | Drag-and-drop placement (UX-DEC-040), approved-folder scanning, import, semantic search |
| Both layouts reachable and unclipped at five sizes in two themes | Illustrative similarity groups | Persistence of collections, tags and favorites |

Simulated scale runs use `QT_SCALE_FACTOR` and are labelled `SIMULATED` in `evidence/`.

## UX-DEC-035 … 041 traceability

| Decision | Demonstrated here | Evidence | Not demonstrated |
|---|---|---|---|
| 035 Unified Library and Collections | One catalog over History, Edit & Photo, Video, Motion references, Learning observations and Imported fixtures; scopes, search, filters; collections, tags, favorites as references with undo | LIB-01/02, `test_qt_library` organizing tests | Persistence; a durable collection metadata policy |
| 036 Hybrid Asset Discovery | A fixed fixture catalog standing for "indexed generated assets" and "explicit imports". No scan | `test_architecture`, `test_independence` | Indexing, import flow, optional approved-folder scanning |
| 037 Intelligent Grouping | Exact-hash group keeps distinct records; similarity group labelled "Illustrative Similarity — No AI Analysis" | LIB-03, `test_similarity_is_labelled…` | Real near-duplicate detection |
| 038 Hybrid Search | Metadata search and a bounded prompt-prefix search with stated semantics; semantic search shown unavailable | `test_semantic_search_is_shown_unavailable…` | Any semantic/AI discovery, or its qualification |
| 039 Library and Contextual Pickers | The dedicated Library; contextual placement through the same review. Existing Edit/Motion pickers are unchanged | LIB-04/05 | A workflow-embedded asset picker built on the Library components |
| 040 Context-Aware Placement | Ordered multi-selection, whole-selection compatibility review, narrowing, Replace/Cancel, return to context | LIB-04/05/07, `test_unsaved_edit_work_*` | Drag-and-drop |
| 041 Controlled Asset Disposition | Reference removal; simulated Photo archive/restore; general archive and delete visibly future-gated | LIB-02, `test_general_archive_and_delete_are_future_gated` | Any real archive, deletion or recovery semantics |

Where this table says *not demonstrated*, the prototype makes no claim and the owner decision remains
open design work.

## Known limitations

1. All state is in memory. Collections, tags, favorites, selection and the learning proposals are lost on exit.
2. Thumbnails are four packaged illustrations, so image content says nothing about real thumbnail cost.
3. The 1,528-record "large" catalog (28 curated + 1,500 generated rows); it bounds widget count and refresh time, not disk I/O.
4. Layout A keeps three rows of filters visible; at small heights this leaves a short results area
   (measured in [LIBRARY_LAYOUTS](LIBRARY_LAYOUTS.md)). It is kept as the comparison, not the default.
5. The search shortcut (Ctrl+F) is covered by invoking the shortcut's activation; the offscreen/native key
   synthesis did not trigger a window-scoped shortcut.
6. The Component Library page is verified to build and to survive both themes; its Library cards are not
   individually interaction-tested.
7. Accessible names are set and checked for presence only. Narrator/NVDA announcement is not verified.
8. Aggregate review (one pass) fixed three defects (search text overwritten inside the debounce, Compare using the
   first-selected instead of the focused item, stale focus after narrowing) and left these accepted limits:
   the vanish/restore simulation is bound to one fixture (`history:ridge-16`); `MediaProvider.full_image` is not
   cached; painted tile text uses the theme font at one size, so fixed tile/row heights are not re-tuned for
   very large fonts or real 150 % scaling; a theme switch closes open inspect/compare dialogs and re-decodes
   thumbnails; the Ctrl+F and first-paint decode tests are weaker than the other native tests.

## QT-DS-06 handoff notes

QT-DS-06 should **consume**, not reimplement:

- `LibrarySession.build_learning_proposal(keys)` → `LearningProposal` (`proposal_id`, `sources` with
  namespace, hash, job lineage, observation ID, rating and experiment, `limitations`, `executable=False`,
  `is_study=False`). It is the contract for "what the Library can hand to a Learning study designer".
- `ProposalSource` carries the five identities separately; a study screen must not collapse them
  (an exact-hash group is *not* independent evidence; several observations of one image are *not* independent samples).
- The Library already refuses to rate, favorite-as-evidence, or create a study. A Learning workspace owns
  its own draft, revision and approval, exactly as Edit and Motion do.
- The `commit()` outcome vocabulary (PLACED / CANCELLED / REFUSED / STALE) and the return-to-context
  restore are reusable for the Learning destination.

Open owner decisions that block production work, not QT-DS-06 prototyping: the durable collection and
favorite metadata policy and its owner; general archive/delete ownership and recovery semantics;
whether semantic/AI search is wanted and how it would be qualified; whether approved-folder scanning is wanted.
