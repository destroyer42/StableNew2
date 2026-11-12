# Asset Library workflow (QT-DS-05)

An isolated, in-memory Qt Widgets prototype of the unified **Asset Library**: find → inspect → organize or
select → choose a compatible action → place into another workspace → return to the same library context.
Every record is a **fixture**. Nothing here scans a folder, imports a file, indexes, renames, moves, deletes
or rewrites a user asset, reads History/Learning/Photo stores, calls a model or touches a network. The
header says so: **FIXTURES ONLY · NO SCAN**.

Authority: `AGENTS.md` and `STATUS.md` win over this directory. The catalog below mirrors the *shape* of
production sources at contract preparation; it is not read from the application. Research is linked, not
copied: [UX-850 research](../../../docs/research/stablenew-experience/README.md) and
[owner decisions UX-DEC-035…041](../../../docs/research/stablenew-experience/ux-850-r1/OWNER_DECISIONS.md).

## The task, end to end

| Step | What the operator does | Where it lives |
|---|---|---|
| Find | Pick a source scope, search, filter, sort, page | `SourceScopePicker`, `AssetFilterBar`, results header |
| Inspect | Read source identity, availability, lineage, relations; open the inspector; compare with the direct parent | `AssetDetailsPanel`, `InspectDialog`, `CompareDialog` |
| Organize / select | Single, Ctrl, Shift or keyboard multi-select (ordered); collections, tags, favorites, undo/redo | `AssetView`, `MultiSelectionStrip`, `OrganizePanel` |
| Choose an action | Every action is listed with its eligibility; disabled actions say why | `AssetActionMenu`, context menu |
| Place | Whole-selection review, optionally narrow, then Place / Replace / Cancel | `CompatibilityReview` |
| Return | **← Return to Library** restores scope, filters, sort, page, selection, view mode, tab and scroll | `LibrarySession.restore_context`, `LibraryView.return_to_library` |

Entry: the **Asset Library** navigation item (Ctrl+6). Existing destinations keep their positions.
The Library never owns the destination's draft: it proposes, the destination session commits.

## Architecture

```
library_domain.py        pure (no Qt): identities, fixture catalog, groups, query, eligibility rules
library_session.py       pure: LibrarySession (selection, organizing, proposals, commits, return context)
library_walkthroughs.py  pure: LIB-01..08 executable scripts
library_components.py    Qt: reusable Library widgets (also in the Component Library)
library_view.py          Qt: LibraryView, layouts A and B, review loop, return trip
app.py                   navigation, destination adoption after a placement, theme rebuild preserving state
```

- **State lives in `LibrarySession`** plus a small `LibraryUi` (layout, view mode, inspector tab, page,
  drawer flags). A theme or layout switch rebuilds widgets from those two objects; nothing is lost.
- **Fixtures are immutable.** Collections, tags, favorites and the simulated Photo archive are mutable,
  in-memory `OrgState` (a frozen value with an undo/redo stack, 50 steps). Selection, search, sort,
  page and view mode are presentation state and are never undoable organizing actions.
- **One media gate.** `LibrarySession.media_source(key)` is the only path to pixels. Thumbnails
  (`MediaProvider`) are deferred, batched (4 per timer tick) and LRU-bounded (192); paint never decodes.
  Hidden, missing, unsupported and metadata-only records never reach the decoder; a missing record is
  never replaced by a substitute image. Native tests inject a recording decoder to prove it.
- **No second authority.** There is no History/catalog/store reimplementation. The Library holds a
  fixture `Catalog` and references destination sessions it was handed (`Destinations`).

## Source and identity model

Five different things are kept apart on purpose; none is a substitute for another.

| Concept | Example | Rule |
|---|---|---|
| **Logical source record ID** | `history:ridge-17` | `namespace:id`, unique, the only handle a collection, selection or handoff uses |
| **Namespace** | `history`, `create`, `edit`, `photo`, `import`, `video`, `motion`, `learning`, `anchor` | Where the record claims to come from; shown on every card and in the badge |
| **Content hash** | `fixture-hash-twin` | A *fact about bytes*. Equal hashes never merge records |
| **Lineage** | `parent history:ridge-16` | Direct parent only. Comparison needs a direct, available parent |
| **Collection membership / labels** | Ridge project, `keeper` | Mutable organizing metadata, kept as references to record IDs |
| **Research observation ID** | `learning:obs-0101` | A *separate record type* that references an image; an image may have several |

`SourceIdentityBadge` always shows namespace and ID; the card shows the label as a second line. A favorite
is a mark, not a rating, and is never read as Learning evidence.

### Fixture catalog (28 curated records + 120 deterministic lightweight bulk records = 148; a 1,528-record variant adds 1,500 for scale tests)

| Kind | Count | Notes |
|---|---|---|
| Still image | 13 | generated History stills (ridge-16/17, coast-04, twin-a/b, near-a/b), a Create result, a Photo still, an imported still, anchors, a missing and a hidden still |
| Edited candidate | 1 | has a recorded direct parent; stills without a parent are also present |
| Video clip | 5 | mirrors the Motion fixtures, including a missing clip and a retired-workflow clip |
| Storyboard sequence | 1 | a simulated sequence record |
| Motion reference | 3 | one is missing |
| Learning observation | 4 | two observations of one image, in different experiments |
| Unsupported type | 1 | `import:clip` |

Required cases are all present: two records with **identical hashes** (`twin-a/b`), **similar but
non-identical** records (`near-a/b`), one asset in **several collections** (`ridge-17`), one asset with
**several observations**, **missing**, **hidden-by-policy**, **unsupported** items,
and the lightweight bulk records. Bulk records are generated rows with a small packaged motif; **no
private images are in Git** and no fixture file is read from outside the package.

## Source scopes

All assets · Generated images (History) · Edit & Photo · Video & Storyboards · Motion references ·
Learning observations · Imported fixtures · Collections (any, or one named collection) · Favorites.
A scope is a *presentation filter over the one catalog*, not a repository. Choosing a scope never clears
the other filters, and a filter never silently widens the scope. An empty collection says so and offers a
way out; it does not show other items.

## Search, filter, sort and pagination specification

| Rule | Behaviour |
|---|---|
| Combination | Filters combine with **AND**. Within one filter the chosen values combine with **OR** |
| Tags | The tag filter requires **ALL** selected tags |
| Words | A search with several words requires **every** word |
| Metadata search | Indexed fields only: label, ID, model, workflow, kind, tags |
| Prompt-prefix search | Matches the start of the **first 48 characters** of a fixture prompt. Not full-text, not semantic |
| Semantic / AI search | Listed as **"Semantic — unavailable"** and refused with a reason. No AI or embedding exists in this prototype |
| Unknown fields | A record with an unknown field is excluded by a filter on that field and the exclusion is reported in a notice; it is never guessed |
| Sort | Newest first · Oldest first · Label A–Z · Source, label. Ties break by record ID, so order is deterministic |
| Pagination | Default **24 per page**; the model holds only the current page (`AssetPageModel`). Changing a filter returns to page 1; paging keeps filters, scope and selection |
| Result states | *empty source*, *no matches* (names the scope; offers *Clear filters*), *loading*, *read error*, *no selection* are different panels with different words |
| Clear filters | Clears filters only. Scope, sort and selection are unchanged |
| Debounce | Typing is debounced (120 ms); changing any combo box or the Favorites checkbox applies immediately |

## Collections, tags and favorites

| Operation | Rule |
|---|---|
| Create | Name 1–60 characters after whitespace collapse; case-insensitive duplicates refused. May start from the selection |
| Rename | Same naming rules; the references and the assets are untouched |
| Add selected | Appends **references** in selected order; duplicates are skipped and counted; works for any available *or unavailable* record (a missing item can still be organized) |
| Remove references | Removes the *reference* from the one collection. The source artifact, its tags and its other collections are untouched. This is the only organizing removal |
| Tags | Up to 32 characters, no commas, stored sorted; add/remove on the whole selection |
| Favorite / Unfavorite | A mark. Not a rating, not a selection, not Learning evidence |
| Undo / Redo | 50 steps over collections, tags, favorites and the simulated Photo archive. Undo re-validates a collection filter that no longer exists |
| Persistence | **None.** All of this is in-memory; closing the prototype forgets it. A durable collection policy is an open owner decision |

## Grouping (UX-DEC-037)

| Group | Behaviour |
|---|---|
| **Exact hash** | Records that share a content hash are listed together in the inspector. They stay *separate records* with their own IDs, lineage, collections and observations. Nothing is merged, hidden or deleted |
| **Illustrative similarity** | Hand-authored fixture groups, always labelled **"Illustrative Similarity — No AI Analysis"**. It says nothing about how similar real images are |

Learning proposals call out shared hashes and several observations of one image as *not independent
evidence*.

## Action eligibility matrix

Eligibility is **explicit per action** (one rule function each) and evaluated on the **whole ordered
selection**. A handoff button is enabled when at least one selected record can be placed; the review dialog
then lists eligible and blocked records separately and never silently drops one. Capacity limits open a
"narrow the selection" review instead of truncating.

Single-record eligibility (Y = can be placed; `-` = refused with a stated reason). `remove-collection` needs
a collection scope and is therefore `-` here; archive/delete are future-gated.

| Source | Kind | inspect | edit | animate | storyboard | movie | compare | regenerate | learning | add-coll. | favorite | archive-photo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| history:ridge-17 | Still, parent known | Y | Y | Y | Y | - | Y | Y | Y | Y | Y | - |
| history:ridge-16 | Still, no parent | Y | Y | Y | Y | - | - | Y | Y | Y | Y | - |
| create:ridge-study | Still | Y | Y | Y | Y | - | - | - | - | Y | Y | - |
| edit:fixture-candidate-1 | Edited candidate | Y | - | - | - | - | Y | - | Y | Y | Y | - |
| import:coast | Imported still | Y | Y | Y | Y | - | - | - | - | Y | Y | - |
| photo:evening | Photo still | Y | Y | Y | Y | - | - | - | - | Y | Y | Y |
| anchor:ridge-dusk | Anchor still | Y | - | Y | Y | - | - | - | - | Y | Y | - |
| video:hist-run-1-clip-1 | Video clip | Y | - | - | - | Y | - | - | - | Y | Y | - |
| video:hist-board-1 | Storyboard sequence | Y | - | - | - | - | - | - | - | Y | Y | - |
| motion:orbit-slow | Motion reference | Y | - | Y* | - | - | - | - | - | Y | Y | - |
| learning:obs-0101 | Learning observation | Y | - | - | - | - | - | - | Y | Y | Y | - |
| history:missing | Missing media | Y | - | - | - | - | - | - | - | Y | Y | - |
| history:hidden | Hidden by policy | Y | - | - | - | - | - | - | - | Y | Y | - |
| import:clip | Unsupported type | Y | - | - | - | - | - | - | - | Y | Y | - |

\* A motion reference only *adds to* an existing Quick Clip draft; with no source image chosen it is refused.

Capacity: Edit, Animate, Storyboard, Compare and Regenerate take **1** record; Movie Clips takes up to
**12** (selected order, never sorted); a Learning proposal takes up to **8**. Inspect works for every
record, including missing and hidden ones (identity and metadata only, never pixels).
**Archive (general)** and **Delete source artifact** are **future-gated** (UX-DEC-041): the buttons are
disabled with the reason, and the Library has no code path that removes or moves an artifact.

## Handoff and replacement semantics

| Action | Destination | Copied | Reset / not inherited | Replace needed when |
|---|---|---|---|---|
| Edit Image | Edit & Improve | source identity, namespace, lineage, availability | new editable draft; **no Preview or approval inherited** | the open Edit draft has unsaved changes and a different source |
| Animate in Motion | Motion · Quick Clip | source identity as the clip source (or a motion reference added to an existing draft) | prompt, seed, frames start fresh; **preview approval and experimental consent are never inherited** | a Quick Clip draft exists on a different source |
| Add to Storyboard | Motion · Storyboard | source image | approval and consent reset (revision changes); existing shots kept | – (undo available) |
| Add to Movie Clips | Motion · Movie Clips | the eligible clips in **selected order** | assembly approval reset; existing items kept | – |
| Regenerate with changes | Create Image | recipe route, a lineage note | prompt/negative/slots replaced by the recipe; **nothing queued, no admission** | the Create draft has unsaved changes |
| Propose Learning source | Learning (proposal only) | source records, hashes, job lineage, observation IDs, limitations | **no study, experiment or rating created; not executable** | – |

The flow is `propose()` → review → `commit()`:

1. `propose()` evaluates the whole selection against the destination **without mutating anything** and
   returns what is copied, preserved, reset and discarded, plus whether unsaved work would be replaced.
2. The review dialog shows eligible and blocked records and the discard list. **Cancel is the default.**
   With unsaved work the only primary action is **Replace draft and place**.
3. `commit()` re-validates. It returns **PLACED**, **CANCELLED** (replacement not chosen), **REFUSED**
   (no longer eligible) or **STALE** (the selection or the destination revision changed since the review).
   Cancelled, refused and stale placements mutate nothing.
4. On success the destination draft is adopted and shown, and **← Return to Library** appears. Returning
   restores the context; items whose availability changed while away stay selected and the change is stated.

## Disposition (UX-DEC-041)

Removing a collection **reference** is safe and undoable. **Archive (simulated Photo policy)** is a
visibility flag on a Photo fixture, reversible with **Restore**, that moves nothing. General archive and
delete are future-gated and explain themselves. The prototype has no file operation of any kind.

## Walkthroughs (executable, `library_walkthroughs.py`)

| ID | Task | Ends in |
|---|---|---|
| LIB-01 | Find an image, inspect it, page away and back; scope, filters and selection preserved | success |
| LIB-02 | Organize: collection, tag, favorite; removal keeps the source artifact | success |
| LIB-03 | Exact-hash twins stay two records; similarity is labelled illustrative | success |
| LIB-04 | Edit handoff creates a fresh draft; the Library returns to the same context | success |
| LIB-05 | Quick Clip source and an ordered two-clip Movie Clips assembly are drafted; nothing approved | success |
| LIB-06 | Learning proposal is inspectable and non-executable; limitations named | success |
| LIB-07 | A mixed selection is refused as a whole; narrowing makes it valid | refusal |
| LIB-08 | Loading, read error, missing, hidden, unsupported, no matches, stale destination: identity kept, both workspaces intact | recoverable |

They run Qt-free, inside the guarded child interpreter of `test_independence` (no PySide6 module may load).

## Component catalog (Library additions)

All appear in **Component Library → Components → "Library · …"** over fixtures, in both themes.

| Component | Role |
|---|---|
| `AssetTile` / delegate card | Thumbnail or availability panel, label, namespace badge; order badge (selection), star (favorite) and collection count are three different signals; state is never colour alone |
| `SourceIdentityBadge` | Namespace + record ID, with availability |
| `SourceScopePicker` | Scope list with counts (compact combo when narrow) |
| `AssetFilterBar` | Debounced search, mode, sort and filter grid (`ResponsiveGrid`) |
| `AssetView` | One grid/list over one ordered selection; arrows, Space, Enter, Ctrl+A, Esc, Menu key |
| `MultiSelectionStrip` | Ordered selection summary with off-page status and Clear / Organize / Details / Actions |
| `AssetActionMenu` | Every action with its reason when disabled |
| `OrganizePanel` | Collections, tags, favorites, undo/redo |
| `SimilarityGroupPanel` | Exact and illustrative groups with the mandatory label |
| `CompatibilityReview` | Whole-selection preflight, narrowing, Place / Replace / Cancel |
| `StatePanel` | Empty source, no matches, loading, read error |

Layout evaluation, measurements and the chosen default: [LIBRARY_LAYOUTS](LIBRARY_LAYOUTS.md).
Test evidence and decision traceability: [LIBRARY_ACCEPTANCE](LIBRARY_ACCEPTANCE.md).
