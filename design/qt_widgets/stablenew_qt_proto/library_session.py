"""Library session, placement proposals and the non-executable Learning proposal (QT-DS-05).

Pure (no Qt). ``LibrarySession`` owns only *presentation* state: query, selection, in-memory
collections/tags/favorites and a return context. Destination drafts stay owned by their own mock
sessions (``EditSession``, ``MotionSession``, ``CreateSession``); the Library only calls their public
draft interfaces after an explicit review and never reaches into a widget.

Boundaries: no generation, queue, history, filesystem or persistence. A handoff creates or selects a
*draft* in the destination. It never inherits Preview approval, consent or execution approval.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .domain import PACK_BY_KEY, CreateDraft, CreateSession
from .edit_domain import Availability, EditRefused, EditSession, Replacement
from .library_domain import (
    ACTION_LABELS,
    ACTION_ORDER,
    HANDOFF_ACTIONS,
    MAX_COLLECTION_NAME,
    MAX_TAG,
    MEDIA_KINDS,
    UNDO_LIMIT,
    ActionEligibility,
    ActionId,
    AssetRecord,
    Catalog,
    Collection,
    LibraryQuery,
    LibraryRefused,
    OrgState,
    QueryResult,
    RuleContext,
    Scope,
    SelectionStatus,
    ViewState,
    availability_reason,
    evaluate_action,
    exact_groups,
    fixture_catalog,
    initial_org,
    run_query,
    selection_status,
)
from .motion_domain import RECOMMENDED, MotionRefused, MotionSession, workflow_for

LOG_LIMIT = 200


class Outcome(StrEnum):
    PLACED = "Placed"
    CANCELLED = "Cancelled"
    REFUSED = "Refused"
    STALE = "Stale review"


@dataclass
class Destinations:
    """Destination-owned mock sessions. Any of them may be absent (workspace not open)."""

    edit: EditSession | None = None
    motion: MotionSession | None = None
    create: CreateSession | None = None


@dataclass(frozen=True)
class BrowseContext:
    """In-session Library context kept across a handoff. Never restored after a restart."""

    query: LibraryQuery
    selection: tuple[str, ...]
    focus: str | None
    destination: str
    availability: tuple[tuple[str, Availability], ...]
    ui: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class PlacementProposal:
    """What a placement would do, computed without touching the destination."""

    action: ActionId
    destination: str
    items: tuple[str, ...]
    eligibility: ActionEligibility
    copied: tuple[tuple[str, str], ...] = ()
    preserved: tuple[str, ...] = ()
    reset: tuple[str, ...] = ()
    discarded: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    needs_replace: bool = False
    replace_detail: str = ""
    destination_revision: int | None = None

    @property
    def can_place(self) -> bool:
        return self.eligibility.placeable

    @property
    def needs_narrowing(self) -> bool:
        return self.eligibility.needs_narrowing


@dataclass(frozen=True)
class PlacementResult:
    outcome: Outcome
    message: str
    action: ActionId
    destination: str
    placed: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome == Outcome.PLACED


@dataclass(frozen=True)
class ProposalSource:
    key: str
    label: str
    kind: str
    namespace: str
    observation_id: str
    job_id: str
    content_hash: str
    model: str
    rating: str
    experiment: str


@dataclass(frozen=True)
class LearningProposal:
    """An inspectable summary. It is not a study, an experiment, a rating or a submission."""

    proposal_id: str
    sources: tuple[ProposalSource, ...]
    limitations: tuple[str, ...]
    context: str = (
        "Observational source for a future Learning study design (QT-DS-06). "
        "Not a controlled trial."
    )
    executable: bool = False
    is_study: bool = False
    status: str = "Mock proposal · not submitted · no study created"


def _norm_tag(tag: str) -> str:
    tag = " ".join(tag.split()).casefold()
    if not tag:
        raise LibraryRefused("Enter a tag first.")
    if len(tag) > MAX_TAG or "," in tag:
        raise LibraryRefused(f"A tag is at most {MAX_TAG} characters and has no commas.")
    return tag


class LibrarySession:
    """Single owner of mutable Library presentation state. Source records never change."""

    def __init__(
        self,
        catalog: Catalog | None = None,
        destinations: Destinations | None = None,
        org: OrgState | None = None,
    ) -> None:
        self.catalog = catalog or fixture_catalog()
        self.destinations = destinations or Destinations()
        self.org = org if org is not None else initial_org()
        self.query = LibraryQuery()
        self.selection: tuple[str, ...] = ()
        self.focus: str | None = None
        self.overrides: dict[str, Availability] = {}
        self.view_state = ViewState.READY
        self.view_error = ""
        self.log: list[str] = []
        self.learning_proposals: list[LearningProposal] = []
        self.handoffs: list[PlacementResult] = []
        self.pending_return: BrowseContext | None = None
        self.revision = 0
        self._undo: list[OrgState] = []
        self._redo: list[OrgState] = []
        self._cache: tuple[object, QueryResult] | None = None

    # ----------------------------------------------------------------------------- bookkeeping
    def _touch(self) -> None:
        self.revision += 1

    def _say(self, message: str) -> str:
        self.log.append(message)
        del self.log[:-LOG_LIMIT]
        self._touch()
        return message

    @property
    def last_feedback(self) -> str:
        return self.log[-1] if self.log else ""

    # ---------------------------------------------------------------------------- availability
    def availability_of(self, record: AssetRecord) -> Availability:
        return self.overrides.get(record.key, record.availability)

    def effective(self, key: str) -> Availability:
        return self.availability_of(self.catalog.get(key))

    def media_source(self, key: str) -> tuple[AssetRecord | None, str]:
        """The record whose packaged fixture image may be decoded for ``key``, or why none may.

        This is the single gate for every pixel route: thumbnail, preview, inspector, comparison, drag
        and clipboard. A hidden, missing, unsupported or media-less record never yields a decodable
        source, and an observation borrows the media of the asset it references only if that is allowed.
        """
        record = self.catalog.get(key)
        target = self.catalog.get(record.references.key) if record.references else record
        availability = self.availability_of(target)
        if availability != Availability.AVAILABLE:
            return None, availability_reason(availability)
        if target.motif is None or target.kind not in MEDIA_KINDS:
            return None, "This record has no image of its own (metadata only)."
        return target, ""

    def simulate_vanish(self, key: str) -> str:
        """Fixture-only: the source file disappears outside the Library. Identity stays."""
        self.catalog.get(key)
        self.overrides[key] = Availability.MISSING
        return self._say(f"Simulated: the file behind {key} went missing. Its record is kept.")

    def simulate_restore(self, key: str) -> str:
        self.catalog.get(key)
        self.overrides.pop(key, None)
        return self._say(f"Simulated: {key} is available again as originally recorded.")

    def set_view_state(self, state: ViewState, error: str = "") -> None:
        self.view_state = state
        self.view_error = error if state == ViewState.ERROR else ""
        self._touch()

    # -------------------------------------------------------------------------------- queries
    def result(self) -> QueryResult:
        token = (self.query, self.org, tuple(sorted(self.overrides.items())))
        if self._cache is None or self._cache[0] != token:
            self._cache = (
                token,
                run_query(self.catalog, self.org, self.query, self.availability_of),
            )
        return self._cache[1]

    def set_query(self, **changes) -> QueryResult:
        """Change filters. The page returns to the first unless ``page`` itself is being changed."""
        if "page" not in changes:
            changes["page"] = 0
        query = replace(self.query, **changes)
        if query.collection is not None:
            self.org.collection(query.collection)
        self.query = query
        result = self.result()
        if result.page != query.page:
            self.query = replace(query, page=result.page)
        self._touch()
        return self.result()

    def set_scope(self, scope: Scope, collection: str | None = None) -> QueryResult:
        """Choose a source scope. Other filters stay; the scope never widens on its own."""
        return self.set_query(scope=scope, collection=collection)

    def clear_filters(self) -> QueryResult:
        self.query = self.query.cleared()
        self._touch()
        return self.result()

    def go_page(self, page: int) -> QueryResult:
        return self.set_query(page=max(0, page))

    # ----------------------------------------------------------------------------- selection
    def _known(self, key: str) -> str:
        self.catalog.get(key)
        return key

    def select_only(self, key: str) -> None:
        self.selection = (self._known(key),)
        self.focus = key
        self._touch()

    def toggle(self, key: str) -> None:
        self._known(key)
        if key in self.selection:
            self.selection = tuple(k for k in self.selection if k != key)
        else:
            self.selection = (*self.selection, key)
        self.focus = key
        self._touch()

    def select_range(self, anchor: str, key: str) -> None:
        """Append the visible run between two items of the current page, in page order."""
        items = self.result().items
        if anchor not in items or key not in items:
            raise LibraryRefused("A range selection needs both items on the current page.")
        lo, hi = sorted((items.index(anchor), items.index(key)))
        added = [k for k in items[lo : hi + 1] if k not in self.selection]
        self.selection = (*self.selection, *added)
        self.focus = key
        self._touch()

    def clear_selection(self) -> None:
        self.selection = ()
        self._touch()

    def narrow(self, keys: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        """Explicit operator narrowing: keep only ``keys`` and preserve their selected order."""
        unknown = [k for k in keys if k not in self.selection]
        if unknown:
            raise LibraryRefused(f"Not in the current selection: {', '.join(unknown)}.")
        keep = set(keys)
        self.selection = tuple(k for k in self.selection if k in keep)
        if self.focus not in self.selection:
            self.focus = self.selection[-1] if self.selection else None
        self._touch()
        return self.selection

    def selection_report(self) -> dict[str, SelectionStatus]:
        return selection_status(self.result(), self.selection)

    # ---------------------------------------------------------------------------- organization
    def _apply(self, org: OrgState, message: str) -> str:
        if org == self.org:
            return self._say(f"No change: {message}")
        self._undo.append(self.org)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self.org = org
        return self._say(message)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> str:
        if not self._undo:
            raise LibraryRefused("Nothing to undo.")
        self._redo.append(self.org)
        self.org = self._undo.pop()
        self._reconcile_query()
        return self._say("Undo: restored the previous collection, tag and favorite state.")

    def redo(self) -> str:
        if not self._redo:
            raise LibraryRefused("Nothing to redo.")
        self._undo.append(self.org)
        self.org = self._redo.pop()
        self._reconcile_query()
        return self._say("Redo: re-applied the undone organization change.")

    def _reconcile_query(self) -> None:
        ids = {c.collection_id for c in self.org.collections}
        if self.query.collection is not None and self.query.collection not in ids:
            self.query = replace(self.query, collection=None, page=0)

    def create_collection(self, name: str, keys: tuple[str, ...] = ()) -> Collection:
        name = " ".join(name.split())
        if not name:
            raise LibraryRefused("Enter a collection name.")
        if len(name) > MAX_COLLECTION_NAME:
            raise LibraryRefused(f"A collection name is at most {MAX_COLLECTION_NAME} characters.")
        if any(c.name.casefold() == name.casefold() for c in self.org.collections):
            raise LibraryRefused(f"A collection named '{name}' already exists.")
        for key in keys:
            self._known(key)
        collection = Collection(f"col-{self.org.next_collection}", name, tuple(dict.fromkeys(keys)))
        org = replace(
            self.org,
            collections=(*self.org.collections, collection),
            next_collection=self.org.next_collection + 1,
        )
        self._apply(
            org, f"Created collection '{name}' with {len(collection.members)} reference(s)."
        )
        return collection

    def rename_collection(self, collection_id: str, name: str) -> Collection:
        name = " ".join(name.split())
        old = self.org.collection(collection_id)
        if not name or len(name) > MAX_COLLECTION_NAME:
            raise LibraryRefused(f"Enter a collection name of 1–{MAX_COLLECTION_NAME} characters.")
        if any(
            c.name.casefold() == name.casefold() and c.collection_id != collection_id
            for c in self.org.collections
        ):
            raise LibraryRefused(f"A collection named '{name}' already exists.")
        new = replace(old, name=name)
        org = replace(
            self.org,
            collections=tuple(
                new if c.collection_id == collection_id else c for c in self.org.collections
            ),
        )
        self._apply(org, f"Renamed '{old.name}' to '{name}'. No asset was modified.")
        return new

    def add_to_collection(self, collection_id: str, keys: tuple[str, ...]) -> str:
        if not keys:
            raise LibraryRefused("Select at least one asset to add.")
        collection = self.org.collection(collection_id)
        for key in keys:
            self._known(key)
        fresh = tuple(k for k in dict.fromkeys(keys) if k not in collection.members)
        new = replace(collection, members=(*collection.members, *fresh))
        org = replace(
            self.org,
            collections=tuple(
                new if c.collection_id == collection_id else c for c in self.org.collections
            ),
        )
        skipped = len(set(keys)) - len(fresh)
        extra = f" {skipped} already a member." if skipped else ""
        return self._apply(
            org,
            f"Added {len(fresh)} reference(s) to '{collection.name}'.{extra} Source artifacts are unchanged.",
        )

    def remove_from_collection(self, collection_id: str, keys: tuple[str, ...]) -> str:
        """Remove references only. The source artifact, its tags and other collections are untouched."""
        collection = self.org.collection(collection_id)
        drop = set(keys) & set(collection.members)
        if not drop:
            raise LibraryRefused(f"None of the selected assets is in '{collection.name}'.")
        new = replace(collection, members=tuple(k for k in collection.members if k not in drop))
        org = replace(
            self.org,
            collections=tuple(
                new if c.collection_id == collection_id else c for c in self.org.collections
            ),
        )
        return self._apply(
            org,
            f"Removed {len(drop)} reference(s) from '{collection.name}'. "
            "The source artifacts were not deleted, moved or changed.",
        )

    def add_tag(self, keys: tuple[str, ...], tag: str) -> str:
        tag = _norm_tag(tag)
        if not keys:
            raise LibraryRefused("Select at least one asset to tag.")
        tags = dict(self.org.tags)
        for key in keys:
            current = tags.get(self._known(key), ())
            if tag not in current:
                tags[key] = tuple(sorted((*current, tag)))
        return self._apply(
            replace(self.org, tags=tuple(sorted(tags.items()))),
            f"Tag '{tag}' set on {len(keys)} asset(s). Source provenance is unchanged.",
        )

    def remove_tag(self, keys: tuple[str, ...], tag: str) -> str:
        tag = _norm_tag(tag)
        tags = dict(self.org.tags)
        for key in keys:
            current = tags.get(self._known(key), ())
            left = tuple(t for t in current if t != tag)
            if left:
                tags[key] = left
            else:
                tags.pop(key, None)
        return self._apply(
            replace(self.org, tags=tuple(sorted(tags.items()))),
            f"Tag '{tag}' removed from {len(keys)} asset(s). Source provenance is unchanged.",
        )

    def set_favorite(self, keys: tuple[str, ...], value: bool) -> str:
        if not keys:
            raise LibraryRefused("Select at least one asset.")
        for key in keys:
            self._known(key)
        favorites = self.org.favorites | set(keys) if value else self.org.favorites - set(keys)
        word = "Favorited" if value else "Removed from favorites:"
        return self._apply(
            replace(self.org, favorites=frozenset(favorites)),
            f"{word} {len(keys)} asset(s). A favorite is not a rating, a selection or Learning evidence.",
        )

    def archive_photo(self, keys: tuple[str, ...]) -> str:
        """SIMULATED Photo-style archive: a visibility state on a fixture, never a file operation."""
        eligibility = self.evaluate(ActionId.ARCHIVE_PHOTO, keys)
        if not eligibility.placeable:
            raise LibraryRefused(eligibility.reason)
        return self._apply(
            replace(self.org, archived=self.org.archived | set(keys)),
            f"Simulated Photo archive applied to {len(keys)} fixture(s). No file was moved or deleted; restore is available.",
        )

    def restore_photo(self, keys: tuple[str, ...]) -> str:
        eligibility = self.evaluate(ActionId.RESTORE_PHOTO, keys)
        if not eligibility.placeable:
            raise LibraryRefused(eligibility.reason)
        return self._apply(
            replace(self.org, archived=self.org.archived - set(keys)),
            f"Simulated Photo restore applied to {len(keys)} fixture(s).",
        )

    # ----------------------------------------------------------------------------- eligibility
    def _context(self) -> RuleContext:
        in_assembly: frozenset[str] = frozenset()
        motion = self.destinations.motion
        if motion is not None and motion.assembly.draft is not None:
            in_assembly = frozenset(i.clip_id for i in motion.assembly.draft.items)
        return RuleContext(
            self.catalog, self.org, self.availability_of, self.query.collection, in_assembly
        )

    def evaluate(self, action: ActionId, keys: tuple[str, ...] | None = None) -> ActionEligibility:
        return evaluate_action(
            action, self.selection if keys is None else tuple(keys), self._context()
        )

    def available_actions(
        self, keys: tuple[str, ...] | None = None
    ) -> tuple[ActionEligibility, ...]:
        return tuple(self.evaluate(a, keys) for a in ACTION_ORDER)

    # ------------------------------------------------------------------------------ placement
    def propose(self, action: ActionId) -> PlacementProposal:
        """Validate the *whole* ordered selection against ``action``'s destination. No mutation."""
        if action not in HANDOFF_ACTIONS:
            raise LibraryRefused(f"{ACTION_LABELS[action]} is not a workspace handoff.")
        keys = self.selection
        eligibility = self.evaluate(action, keys)
        base = PlacementProposal(action, eligibility.destination, keys, eligibility)
        missing = self._destination_missing(action)
        if missing:
            return replace(base, eligibility=replace(eligibility, set_reason=missing))
        if not keys:
            return base
        builder = {
            ActionId.EDIT: self._propose_edit,
            ActionId.ANIMATE: self._propose_animate,
            ActionId.STORYBOARD: self._propose_storyboard,
            ActionId.MOVIE: self._propose_movie,
            ActionId.REGENERATE: self._propose_create,
            ActionId.LEARNING: self._propose_learning,
        }[action]
        return builder(base)

    def _destination_missing(self, action: ActionId) -> str:
        wanted = {
            ActionId.EDIT: ("edit", "Edit & Improve"),
            ActionId.ANIMATE: ("motion", "Motion & Video"),
            ActionId.STORYBOARD: ("motion", "Motion & Video"),
            ActionId.MOVIE: ("motion", "Motion & Video"),
            ActionId.REGENERATE: ("create", "Create Image"),
        }.get(action)
        if wanted and getattr(self.destinations, wanted[0]) is None:
            return f"{wanted[1]} is not open in this session, so nothing can be placed."
        return ""

    def _rec(self, key: str) -> AssetRecord:
        return self.catalog.get(key)

    def _identity(self, record: AssetRecord) -> tuple[tuple[str, str], ...]:
        return (
            ("Source identity", record.key),
            ("Source namespace", record.namespace),
            (
                "Known lineage",
                f"parent {record.parent.key}" if record.parent else "no parent recorded",
            ),
            ("Media availability", self.availability_of(record).value),
        )

    def _propose_edit(self, base: PlacementProposal) -> PlacementProposal:
        edit = self.destinations.edit
        eligibility = base.eligibility
        if not eligibility.eligible:
            return base
        record = self._rec(eligibility.eligible[0])
        same = edit.draft is not None and edit.draft.source_key == record.native_key
        needs = not same and edit.dirty
        return replace(
            base,
            copied=self._identity(record),
            preserved=("Recorded mock candidates and baselines",)
            + (("The open draft for this source (kept exactly as it is)",) if same else ()),
            reset=()
            if same
            else (
                "New editable draft: mode, prompt, regions, mask and geometry start at defaults",
            ),
            discarded=tuple(
                x
                for x in (
                    "Current Preview and its approval"
                    if edit.preview is not None and not same
                    else "",
                    "Unsaved edit-draft changes" if needs else "",
                )
                if x
            ),
            notes=(
                "Edit derives its own lineage display from its fixture; it inherits no approval.",
            ),
            needs_replace=needs,
            replace_detail=f"Open Edit draft on {edit.draft.source_key} has unsaved changes."
            if needs
            else "",
            destination_revision=edit.revision,
        )

    def _propose_animate(self, base: PlacementProposal) -> PlacementProposal:
        motion = self.destinations.motion
        eligibility = base.eligibility
        if not eligibility.eligible:
            return base
        record = self._rec(eligibility.eligible[0])
        quick = motion.quick
        draft = quick.draft
        workflow = workflow_for(draft.workflow if draft else RECOMMENDED)
        common = (
            f"Selected workflow: {workflow.label} ({workflow.governance}). Experimental consent, "
            "Preview approval, execution approval and frozen settings are never inherited.",
        )
        if record.kind.value == "Motion reference":
            if draft is None or not draft.source_key:
                blocked = tuple(
                    replace(
                        v,
                        ok=False,
                        reason="Choose a Quick Clip source image first; a motion reference only adds to a draft.",
                    )
                    for v in eligibility.verdicts
                )
                return replace(base, eligibility=replace(eligibility, verdicts=blocked))
            supports = "motion_reference" in workflow.controls
            return replace(
                base,
                copied=(("Motion reference", record.key), ("Intended source type", "motion reference"),
                        ("Known lineage", "none recorded"), ("Media availability", self.availability_of(record).value)),
                preserved=("The Quick Clip source image, prompt, seed and workflow choice",),
                reset=(),
                discarded=("Preview approval and experimental consent (the draft revision changes)",),
                notes=(*common, f"{workflow.label} "
                       + ("declares a motion reference." if supports else
                          "does not declare a motion reference: Motion Review will refuse until the workflow changes.")),
                destination_revision=quick.revision,
            )  # fmt: skip
        same = draft is not None and draft.source_key == record.native_key
        needs = draft is not None and not same
        return replace(
            base,
            copied=(*self._identity(record), ("Intended source type", "source image")),
            preserved=("Selected workflow" + (f" ({workflow.label})" if draft else ""),)
            if draft
            else (),
            reset=()
            if same
            else ("Prompt, seed intent, frames and reference start from a fresh draft",),
            discarded=tuple(
                x
                for x in (
                    "Preview approval"
                    if motion.previews.get("quick") is not None and not same
                    else "",
                    "Experimental consent" if not same else "",
                    "Unsaved Motion draft changes" if needs and quick.dirty else "",
                )
                if x
            ),
            notes=common,
            needs_replace=needs,
            replace_detail=f"The Motion Quick Clip draft on {draft.source_key} will be replaced."
            if needs
            else "",
            destination_revision=quick.revision,
        )

    def _propose_storyboard(self, base: PlacementProposal) -> PlacementProposal:
        motion = self.destinations.motion
        if not base.eligibility.eligible:
            return base
        record = self._rec(base.eligibility.eligible[0])
        draft = motion.story.draft
        change = (
            "New Storyboard with this source image"
            if draft is None
            else "Storyboard source image changes on the existing draft (undo available)"
        )
        return replace(
            base,
            copied=(*self._identity(record), ("Intended source type", "storyboard source image")),
            preserved=("Existing shots, prompts and anchors",) if draft else (),
            reset=(),
            discarded=(
                "Storyboard Preview approval and experimental consent (the draft revision changes)",
            ),
            notes=(change,),
            destination_revision=motion.story.revision,
        )

    def _propose_movie(self, base: PlacementProposal) -> PlacementProposal:
        motion = self.destinations.motion
        eligibility = base.eligibility
        verdicts = []
        for v in eligibility.verdicts:
            if v.ok:
                try:
                    clip = motion.clip(self._rec(v.key).native_key or "")
                except MotionRefused as exc:
                    verdicts.append(replace(v, ok=False, reason=str(exc)))
                    continue
                ok, reason = motion.clip_eligibility(clip)
                v = v if ok else replace(v, ok=False, reason=reason)
            verdicts.append(v)
        eligibility = replace(eligibility, verdicts=tuple(verdicts))
        existing = len(motion.assembly.draft.items) if motion.assembly.draft else 0
        copied = tuple(
            (f"Clip {n}", f"{k} (selected order {n})")
            for n, k in enumerate(eligibility.eligible, 1)
        )
        return replace(
            base,
            eligibility=eligibility,
            copied=copied,
            preserved=(
                f"The {existing} item(s) already in the assembly, their order, trims, profile and audio",
            ),
            reset=(),
            discarded=("Assembly Preview approval (the assembly changes)",)
            if motion.assembly_preview is not None
            else (),
            notes=(
                "Clips are appended in the selected order, never sorted by name. Nothing is assembled.",
            ),
            destination_revision=motion.assembly.revision,
        )

    def _propose_create(self, base: PlacementProposal) -> PlacementProposal:
        create = self.destinations.create
        if not base.eligibility.eligible:
            return base
        record = self._rec(base.eligibility.eligible[0])
        pack = PACK_BY_KEY.get(record.recipe_pack or "")
        if pack is None:
            blocked = tuple(
                replace(v, ok=False, reason="Create has no fixture for this recipe route.")
                for v in base.eligibility.verdicts
            )
            return replace(base, eligibility=replace(base.eligibility, verdicts=blocked))
        same = create.draft.source_key == pack.key and not create.pack_modified
        dirty = create.draft.fingerprint() != CreateDraft().fingerprint()
        needs = dirty and not same
        return replace(
            base,
            copied=(("Recipe route", pack.label), ("Starting asset (lineage note)", record.key),
                    ("Prompt / negative / slots", "from the recipe fixture")),
            preserved=("Model, settings, locks and manual overrides already in the draft",),
            reset=() if same else ("Prompt, negative prompt and slots are replaced by the recipe (undo available)",),
            discarded=tuple(x for x in ("Current Preview becomes stale; no executable Preview or admission is inherited"
                                        if create.preview is not None else "",) if x),
            notes=("Saved profiles and startup defaults are not applied. Nothing is queued.",),
            needs_replace=needs,
            replace_detail="The Create draft has unsaved changes that the recipe would replace." if needs else "",
            destination_revision=create.revision,
        )  # fmt: skip

    def _propose_learning(self, base: PlacementProposal) -> PlacementProposal:
        eligibility = base.eligibility
        return replace(
            base,
            copied=tuple((f"Source {n}", k) for n, k in enumerate(eligibility.eligible, 1)),
            preserved=("Every source record, its hash, job lineage and observation IDs, unmerged",),
            reset=(),
            discarded=(),
            notes=(
                "Creates an inspectable, non-executable proposal only. No study, experiment or rating is created.",
            ),
            destination_revision=len(self.learning_proposals),
        )

    def commit(
        self, proposal: PlacementProposal, choice: Replacement | None = None
    ) -> PlacementResult:
        """Place the reviewed selection. Refused, stale and cancelled placements mutate nothing."""
        action, label = proposal.action, proposal.destination
        fresh = self.propose(action) if tuple(proposal.items) == self.selection else None
        if fresh is None:
            return self._finish(
                PlacementResult(
                    Outcome.STALE,
                    "The selection changed since this review. Review again.",
                    action,
                    label,
                )
            )
        if not fresh.can_place:
            return self._finish(
                PlacementResult(
                    Outcome.REFUSED, f"Not placed: {fresh.eligibility.reason}", action, label
                )
            )
        if fresh.destination_revision != proposal.destination_revision:
            return self._finish(
                PlacementResult(
                    Outcome.STALE,
                    f"{label} changed since this review. Nothing was placed; review again.",
                    action,
                    label,
                )
            )
        if fresh.needs_replace and choice != Replacement.REPLACE:
            return self._finish(
                PlacementResult(
                    Outcome.CANCELLED,
                    f"Cancelled: {label} and the Library context are unchanged.",
                    action,
                    label,
                )
            )
        try:
            placed = self._apply_placement(fresh)
        except (EditRefused, MotionRefused, LibraryRefused, ValueError) as exc:
            return self._finish(
                PlacementResult(Outcome.REFUSED, f"Not placed: {exc}", action, label)
            )
        result = PlacementResult(
            Outcome.PLACED, self._receipt(fresh, placed), action, label, placed
        )
        self.pending_return = BrowseContext(
            self.query,
            self.selection,
            self.focus,
            label,
            tuple((k, self.effective(k)) for k in self.selection),
        )
        return self._finish(result)

    def _finish(self, result: PlacementResult) -> PlacementResult:
        self.handoffs.append(result)
        self._say(result.message)
        return result

    def _apply_placement(self, p: PlacementProposal) -> tuple[str, ...]:
        keys = p.eligibility.eligible
        records = [self._rec(k) for k in keys]
        if p.action == ActionId.EDIT:
            edit = self.destinations.edit
            if not edit.select(
                records[0].native_key, Replacement.REPLACE if p.needs_replace else None
            ):
                raise LibraryRefused("Edit still holds unsaved work; nothing was replaced.")
        elif p.action == ActionId.ANIMATE:
            motion = self.destinations.motion
            if records[0].kind.value == "Motion reference":
                motion.update_quick(reference_key=records[0].native_key)
            elif not motion.receive_source(
                records[0].native_key, "library", Replacement.REPLACE if p.needs_replace else None
            ):
                raise LibraryRefused("Motion still holds unsaved work; nothing was replaced.")
        elif p.action == ActionId.STORYBOARD:
            motion = self.destinations.motion
            native = records[0].native_key
            if motion.story.draft is None:
                motion.new_storyboard(native)
            else:
                motion.update_story(
                    source_key=native, source_digest=motion.catalog.get(native).digest
                )
        elif p.action == ActionId.MOVIE:
            self.destinations.motion.add_clips([r.native_key for r in records])
        elif p.action == ActionId.REGENERATE:
            self.destinations.create.select_source(records[0].recipe_pack)
        else:  # LEARNING: an inspectable value, no destination
            self.learning_proposals.append(self.build_learning_proposal(keys))
        return tuple(keys)

    def _receipt(self, p: PlacementProposal, placed: tuple[str, ...]) -> str:
        what = ", ".join(placed)
        if p.action == ActionId.LEARNING:
            return (f"Prepared mock Learning proposal {self.learning_proposals[-1].proposal_id} for {what}. "
                    "It is not a study and cannot be executed.")  # fmt: skip
        return (f"Placed {what} in {p.destination} as a draft. Preview approval, consent and execution "
                "approval were not carried over.")  # fmt: skip

    # --------------------------------------------------------------------------- Learning proposal
    def build_learning_proposal(self, keys: tuple[str, ...]) -> LearningProposal:
        sources, limits = (
            [],
            [
                "Fixture identities only; none is a production History, job or Learning record.",
                "A Library placement does not create a study, an experiment, a rating or a Learning record.",
                "Observational evidence: prompt, seed and baseline were not controlled by this proposal.",
            ],
        )
        groups = exact_groups(self.catalog)
        for key in keys:
            r = self._rec(key)
            target = self._rec(r.references.key) if r.references else r
            sources.append(
                ProposalSource(
                    r.key,
                    r.label,
                    r.kind.value,
                    r.namespace,
                    r.observation_id or "unknown",
                    r.job_id or "unknown",
                    target.content_hash or "unknown",
                    r.model or "unknown",
                    str(r.rating) if r.rating is not None else "none recorded",
                    r.experiment or "none recorded",
                )  # fmt: skip
            )
            if r.rating is not None:
                limits.append(
                    f"{r.key}: rating {r.rating} belongs to fixture experiment {r.experiment}; it is not a verdict of a controlled study."
                )
            for group in groups:
                if target.key in group.members:
                    others = [m for m in group.members if m != target.key]
                    limits.append(
                        f"{r.key}: content hash is shared with {', '.join(others)}. Equal bytes are not independent observations."
                    )
            watching = self.catalog.observations_of(target.key)
            if len(watching) > 1:
                limits.append(
                    f"{target.key}: {len(watching)} observations reference this image ({', '.join(watching)}); they are not independent samples."
                )
            if r.model is None:
                limits.append(f"{r.key}: model is unknown.")
        pid = f"mock-proposal-{len(self.learning_proposals) + 1}"
        return LearningProposal(pid, tuple(sources), tuple(dict.fromkeys(limits)))

    # ----------------------------------------------------------------------------------- compare
    def compare_pair(self, key: str) -> tuple[AssetRecord, AssetRecord]:
        """(parent, child) for a supported direct-parent comparison, else a readable refusal."""
        eligibility = self.evaluate(ActionId.COMPARE, (key,))
        if not eligibility.placeable:
            raise LibraryRefused(eligibility.reason)
        child = self._rec(key)
        return self._rec(child.parent.key), child

    # ------------------------------------------------------------------------------- return trip
    def restore_context(self, context: BrowseContext | None = None) -> tuple[str, ...]:
        """Return to the browse context. Items whose state changed stay selected and are disclosed."""
        context = context or self.pending_return
        if context is None:
            raise LibraryRefused("There is no Library context to return to.")
        self.query = context.query
        self.selection = tuple(k for k in context.selection if k in self.catalog)
        self.focus = context.focus
        notes = []
        for key, before in context.availability:
            now = self.effective(key)
            if now != before:
                notes.append(
                    f"{key} changed from {before.value} to {now.value} while you were away; it stays selected."
                )
        self.pending_return = None
        self._say(
            "Returned to the Library with the same scope, filters, sort, page and selection."
            + (" " + " ".join(notes) if notes else "")
        )
        return tuple(notes)
