"""Eight scripted, executable Library walkthroughs (LIB-01 … LIB-08) over the pure mock domain.

Each script drives a fresh :class:`LibrarySession` with real destination mock sessions exactly as an
operator would through the UI and ends in a named success, refusal or recoverable state. The native Qt
tests replay the key journeys through widgets; these scripts prove the rules without Qt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .domain import CreateSession
from .edit_domain import EditSession, Mode, Replacement
from .library_domain import (
    ActionId,
    Availability,
    EmptyState,
    LibraryRefused,
    Scope,
    SearchMode,
    exact_groups,
)
from .library_session import Destinations, LibrarySession, Outcome
from .motion_domain import KIND_MOVIE, KIND_QUICK, MotionSession, Status

CLIP_1, CLIP_3 = "video:hist-run-1-clip-1", "video:hist-run-1-clip-3"
TWIN_A, TWIN_B = "history:twin-a", "history:twin-b"


class WalkthroughError(AssertionError):
    """A scripted step did not behave as the operator contract requires."""


def expect(condition: object, message: str) -> None:
    if not condition:
        raise WalkthroughError(message)


def refused(action: Callable[[], object], needle: str) -> str:
    try:
        action()
    except LibraryRefused as exc:
        expect(needle.lower() in str(exc).lower(), f"expected '{needle}' in refusal, got: {exc}")
        return str(exc)
    raise WalkthroughError(f"expected a refusal mentioning '{needle}'")


@dataclass(frozen=True)
class WalkthroughResult:
    key: str
    title: str
    outcome: str  # success | refusal | recoverable
    terminal: str
    steps: tuple[str, ...]


@dataclass
class Script:
    key: str
    title: str
    session: LibrarySession
    log: list[str]

    def step(self, text: str) -> None:
        self.log.append(text)

    def done(self, outcome: str, terminal: str) -> WalkthroughResult:
        return WalkthroughResult(self.key, self.title, outcome, terminal, tuple(self.log))


def new_session() -> LibrarySession:
    return LibrarySession(
        destinations=Destinations(EditSession(), MotionSession(), CreateSession())
    )


def _script(key: str, title: str, session: LibrarySession | None = None) -> Script:
    return Script(key, title, session or new_session(), [])


def lib_01_find_image(session: LibrarySession | None = None) -> WalkthroughResult:
    s = _script("LIB-01", "Find an image", session)
    lib = s.session
    s.step("Open the Library: all supported mock assets, most recent first")
    expect(
        lib.query.scope == Scope.ALL and lib.result().total == len(lib.catalog), "starts unfiltered"
    )
    s.step("Choose the Generated Images (History fixtures) scope")
    lib.set_scope(Scope.HISTORY)
    s.step(
        "Filter by model fixture-sdxl and a date from 2026-10-03; search the metadata for 'ridge'"
    )
    lib.set_query(models=frozenset({"fixture-sdxl"}), date_from="2026-10-03", text="ridge")
    result = lib.result()
    expect("history:ridge-17" in result.matched, "ridge-17 matches")
    expect("history:ridge-16" not in result.matched, "ridge-16 is older than the date filter")
    expect(result.scope_total == 130, "the scope total is shown, not widened")
    s.step("Inspect the result without changing the selection")
    lib.select_only("history:ridge-17")
    before = (lib.query, lib.selection)
    eligibility = lib.evaluate(ActionId.INSPECT)
    expect(eligibility.placeable, "inspect is always available for one asset")
    expect((lib.query, lib.selection) == before, "inspecting changes no context")
    s.step("Move to the next page and back: scope, filters and selection are kept")
    lib.go_page(0)
    expect(
        lib.query.models == frozenset({"fixture-sdxl"}) and lib.selection == ("history:ridge-17",),
        "context kept",
    )
    return s.done(
        "success", "history:ridge-17 found and inspected; scope, filters and selection preserved"
    )


def lib_02_organize(session: LibrarySession | None = None) -> WalkthroughResult:
    s = _script("LIB-02", "Organize a project", session)
    lib = s.session
    s.step("Select three harbor studies in order")
    for key in (TWIN_A, "history:near-a", "history:near-b"):
        lib.toggle(key)
    expect(lib.selection == (TWIN_A, "history:near-a", "history:near-b"), "ordered selection")
    s.step("Create the collection 'Harbor set' from the selection")
    harbor = lib.create_collection("Harbor set", lib.selection)
    expect(harbor.members == lib.selection, "members reference the original IDs, in order")
    s.step("Tag and favorite one item")
    lib.add_tag((TWIN_A,), "Keeper")
    lib.set_favorite((TWIN_A,), True)
    expect(
        lib.org.tags_of(TWIN_A) == ("keeper",) and TWIN_A in lib.org.favorites,
        "tag and favorite set",
    )
    s.step("Remove one collection reference; the source artifact is preserved")
    before = lib.catalog.get("history:near-b")
    message = lib.remove_from_collection(harbor.collection_id, ("history:near-b",))
    expect("not deleted" in message, "feedback says nothing was deleted")
    expect(
        lib.catalog.get("history:near-b") is before and "history:near-b" in lib.catalog,
        "source untouched",
    )
    expect(
        lib.org.collection(harbor.collection_id).members == (TWIN_A, "history:near-a"),
        "reference removed",
    )
    s.step("Undo restores the removed reference")
    lib.undo()
    expect(
        "history:near-b" in lib.org.collection(harbor.collection_id).members,
        "undo restores membership",
    )
    return s.done(
        "success", "Collection, tag and favorite applied; removal kept the source artifact"
    )


def lib_03_exact_duplicates(session: LibrarySession | None = None) -> WalkthroughResult:
    s = _script("LIB-03", "Exact duplicate identities", session)
    lib = s.session
    s.step("Open the exact-content group")
    groups = [g for g in exact_groups(lib.catalog) if TWIN_A in g.members]
    expect(len(groups) == 1 and set(groups[0].members) == {TWIN_A, TWIN_B}, "one exact group")
    a, b = lib.catalog.get(TWIN_A), lib.catalog.get(TWIN_B)
    s.step("Inspect both records: equal hash, distinct logical IDs, provenance and observations")
    expect(a.content_hash == b.content_hash and a.content_hash, "identical hashes")
    expect(a.ref != b.ref and a.job_id != b.job_id, "distinct IDs and jobs")
    expect(
        lib.catalog.observations_of(TWIN_A) != lib.catalog.observations_of(TWIN_B),
        "separate observations",
    )
    s.step("Organize one without touching the other")
    lib.create_collection("Twin A only", (TWIN_A,))
    expect(not lib.org.collections_of(TWIN_B), "membership is per record")
    s.step("Propose both as Learning sources: the proposal says the hash is shared")
    lib.selection = ()
    lib.toggle("learning:obs-0103")
    lib.toggle("learning:obs-0104")
    proposal = lib.build_learning_proposal(lib.selection)
    expect(
        any("not independent observations" in x for x in proposal.limitations),
        "limitation disclosed",
    )
    expect(len(proposal.sources) == 2, "both records stay separate sources")
    return s.done(
        "success", "Two records with one hash stayed two records, not one canonical asset"
    )


def lib_04_edit_handoff(session: LibrarySession | None = None) -> WalkthroughResult:
    s = _script("LIB-04", "Edit handoff", session)
    lib = s.session
    edit = lib.destinations.edit
    s.step("Select history:ridge-17 and review the Edit placement")
    lib.select_only("history:ridge-17")
    proposal = lib.propose(ActionId.EDIT)
    expect(
        proposal.can_place and not proposal.needs_replace, "eligible; no unsaved work to replace"
    )
    expect(("Known lineage", "parent history:ridge-16") in proposal.copied, "lineage is carried")
    s.step("Place into Edit: a new draft, no Preview approval")
    result = lib.commit(proposal)
    expect(result.outcome == Outcome.PLACED, result.message)
    expect(edit.draft.source_key == "history:ridge-17" and edit.preview is None, "fresh draft")
    s.step("Return to the Library: the same context")
    notes = lib.restore_context()
    expect(not notes and lib.selection == ("history:ridge-17",), "context restored")
    return s.done(
        "success", "Edit has a new draft on history:ridge-17; the Library kept its context"
    )


def lib_05_motion_and_movie(session: LibrarySession | None = None) -> WalkthroughResult:
    s = _script("LIB-05", "Motion and Movie Clips", session)
    lib = s.session
    motion = lib.destinations.motion
    s.step("Select create:ridge-study and place it as the Quick Clip source")
    lib.select_only("create:ridge-study")
    expect(lib.commit(lib.propose(ActionId.ANIMATE)).ok, "motion handoff")
    expect(motion.quick.draft.source_key == "create:ridge-study", "source selected")
    expect(motion.status(KIND_QUICK) == Status.NOT_REVIEWED, "no inherited approval")
    expect(
        not motion.consent_required(KIND_QUICK) or KIND_QUICK not in motion._consent,
        "no inherited consent",
    )
    s.step("Select clip 3 then clip 1 and place them as Movie Clips in that order")
    lib.selection = ()
    lib.toggle(CLIP_3)
    lib.toggle(CLIP_1)
    expect(lib.commit(lib.propose(ActionId.MOVIE)).ok, "movie handoff")
    ids = [i.clip_id for i in motion.assembly.draft.items]
    expect(
        ids == ["hist-run-1-clip-3", "hist-run-1-clip-1"], f"selected order kept, not sorted: {ids}"
    )
    expect(
        motion.status(KIND_MOVIE) != Status.READY and not motion.movies,
        "nothing assembled or approved",
    )
    return s.done(
        "success",
        "Quick Clip source and an ordered two-clip assembly were drafted; nothing was approved",
    )


def lib_06_learning_proposal(session: LibrarySession | None = None) -> WalkthroughResult:
    s = _script("LIB-06", "Learning source proposal", session)
    lib = s.session
    revisions = (
        lib.destinations.edit.revision,
        lib.destinations.motion.quick.revision,
        lib.destinations.create.revision,
    )
    s.step("Select the observation of history:ridge-17 recorded in experiment A")
    lib.select_only("learning:obs-0101")
    s.step("Propose it as a Learning source")
    result = lib.commit(lib.propose(ActionId.LEARNING))
    expect(result.ok, result.message)
    proposal = lib.learning_proposals[-1]
    expect(proposal.executable is False and proposal.is_study is False, "proposal is not a study")
    s.step("Inspect the evidence limitations")
    expect(
        any("not independent samples" in x for x in proposal.limitations),
        "two observations share the image",
    )
    expect(any("not a verdict" in x for x in proposal.limitations), "rating is not a verdict")
    expect(
        revisions
        == (
            lib.destinations.edit.revision,
            lib.destinations.motion.quick.revision,
            lib.destinations.create.revision,
        ),
        "no destination changed",
    )
    return s.done(
        "success",
        f"{proposal.proposal_id}: inspectable, non-executable, {len(proposal.limitations)} limitation(s)",
    )


def lib_07_mixed_selection(session: LibrarySession | None = None) -> WalkthroughResult:
    s = _script("LIB-07", "Mixed selection and refusal", session)
    lib = s.session
    edit = lib.destinations.edit
    s.step("Select a placeable image, an image Edit has no fixture for, and a missing image")
    for key in ("history:ridge-17", "history:coast-04", "history:missing"):
        lib.toggle(key)
    proposal = lib.propose(ActionId.EDIT)
    expect(not proposal.can_place and proposal.needs_narrowing, "whole-set preflight refuses")
    expect(proposal.eligibility.eligible == ("history:ridge-17",), "eligible shown separately")
    expect(
        {v.key for v in proposal.eligibility.blocked} == {"history:coast-04", "history:missing"},
        "blocked shown",
    )
    s.step("Placing the unnarrowed set is refused and mutates nothing")
    before = (edit.revision, edit.draft)
    result = lib.commit(proposal)
    expect(
        result.outcome == Outcome.REFUSED and (edit.revision, edit.draft) == before, "zero mutation"
    )
    expect(
        lib.selection == ("history:ridge-17", "history:coast-04", "history:missing"),
        "nothing silently dropped",
    )
    s.step("Explicitly narrow to the eligible image and place it")
    lib.narrow(["history:ridge-17"])
    expect(lib.commit(lib.propose(ActionId.EDIT)).ok, "narrowed set places")
    s.step("A video clip mixed with a still is refused for Movie Clips")
    lib.selection = ()
    lib.toggle(CLIP_1)
    lib.toggle("history:ridge-17")
    expect(not lib.propose(ActionId.MOVIE).can_place, "still image cannot join a movie")
    return s.done(
        "refusal", "Mixed sets were refused as a whole; narrowing made the placement valid"
    )


def lib_08_recovery(session: LibrarySession | None = None) -> WalkthroughResult:
    s = _script("LIB-08", "Recovery and negative states", session)
    lib = s.session
    edit = lib.destinations.edit
    s.step("Empty source: Favorites has nothing yet")
    lib.set_scope(Scope.FAVORITES)
    expect(lib.result().empty == EmptyState.EMPTY_SOURCE, "empty source")
    s.step("Zero matches: a search that finds nothing does not widen the scope")
    lib.set_scope(Scope.LEARNING)
    lib.set_query(text="zzzz", mode=SearchMode.METADATA)
    result = lib.result()
    expect(
        result.empty == EmptyState.NO_MATCHES and result.scope_total == 4,
        "no matches, scope unchanged",
    )
    lib.clear_filters()
    s.step("Hidden and missing media keep their records and give readable reasons")
    expect(lib.effective("history:hidden") == Availability.HIDDEN, "hidden state")
    reason = lib.evaluate(ActionId.EDIT, ("history:hidden",)).reason
    expect("hidden" in reason.lower(), reason)
    expect(
        "missing" in lib.evaluate(ActionId.EDIT, ("history:missing",)).reason.lower(),
        "missing reason",
    )
    s.step("A source vanishing between review and placement fails the handoff cleanly")
    lib.set_scope(Scope.ALL)
    lib.select_only("history:ridge-16")
    proposal = lib.propose(ActionId.EDIT)
    lib.simulate_vanish("history:ridge-16")
    failed = lib.commit(proposal)
    expect(
        failed.outcome == Outcome.REFUSED and edit.draft is None, "no partial destination update"
    )
    lib.simulate_restore("history:ridge-16")
    s.step("Unsaved Edit work: Cancel keeps both sides, Replace proceeds")
    expect(edit.select("history:ridge-16"), "open a draft")
    edit.update(mode=Mode.MASKED)
    lib.select_only("history:ridge-17")
    review = lib.propose(ActionId.EDIT)
    expect(review.needs_replace, "unsaved work needs a decision")
    snapshot = (edit.draft, edit.revision, lib.query, lib.selection)
    cancelled = lib.commit(review, Replacement.CANCEL)
    expect(cancelled.outcome == Outcome.CANCELLED, cancelled.message)
    expect(
        (edit.draft, edit.revision, lib.query, lib.selection) == snapshot, "zero mutation on Cancel"
    )
    expect(lib.commit(review, Replacement.REPLACE).ok, "Replace places the new draft")
    return s.done(
        "recoverable",
        "Every negative state kept identity, explained itself and left both workspaces intact",
    )


ALL = (
    lib_01_find_image,
    lib_02_organize,
    lib_03_exact_duplicates,
    lib_04_edit_handoff,
    lib_05_motion_and_movie,
    lib_06_learning_proposal,
    lib_07_mixed_selection,
    lib_08_recovery,
)


def run_all() -> list[WalkthroughResult]:
    return [script() for script in ALL]
