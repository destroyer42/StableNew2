"""Pure, in-memory mock domain for the Asset Library (QT-DS-05).

Everything here is a deterministic fixture simulation with no Qt, filesystem, network or production
import. The Library is a *presentation* over source-identified fixture records: it is not a History,
catalog, repository or storage authority, and nothing in this module indexes, scans, imports, renames,
moves, deletes or rewrites a user file.

Identity is deliberately separated (UX-850-B J4, UX-DEC-035..041):

1. logical source record ID      ``AssetRecord.ref.record_id``
2. source namespace              ``AssetRecord.ref.namespace``
3. content hash (if known)       ``AssetRecord.content_hash`` (equal bytes are NOT the same record)
4. parent/child lineage          ``AssetRecord.parent`` / ``job_id``
5. collection membership         ``OrgState`` (mutable, references original keys)
6. user-visible label            ``AssetRecord.label``
7. mock research observation ID  ``AssetRecord.observation_id``
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from .edit_domain import SOURCES as STILL_SOURCES
from .edit_domain import Availability
from .motion_domain import ANCHORS, REFERENCES, MotionSession

FIXTURE_NOTICE = "Fixture catalog · not production records · nothing is indexed, scanned or changed"
SIMILARITY_LABEL = "Illustrative Similarity — No AI Analysis"
EXACT_LABEL = "Exact content match — records stay distinct"
PROMPT_INDEX_LEN = 48
DEFAULT_PAGE_SIZE = 24
MAX_COLLECTION_NAME = 60
MAX_TAG = 32
MAX_LEARNING_SOURCES = 8
MAX_MOVIE_CLIPS = 12
UNDO_LIMIT = 50
UNKNOWN = "unknown"
SEMANTIC_UNAVAILABLE = (
    "Semantic / AI search is not available: it needs separate qualification (UX-DEC-038). "
    "Only the indexed fixture fields are searched."
)
FILTER_SEMANTICS = (
    "Filters combine with AND. Within one filter, the selected values combine with OR. "
    "Tags require ALL selected tags. A search box with several words requires every word. "
    "Nothing widens beyond the chosen source scope."
)


class LibraryRefused(ValueError):
    """A mock Library action needs a different or more current input. Never a production refusal."""


class AssetKind(StrEnum):
    STILL = "Still image"
    EDITED = "Edited candidate"
    VIDEO = "Video clip"
    SEQUENCE = "Storyboard sequence"
    MOTION_REF = "Motion reference"
    OBSERVATION = "Learning observation"
    UNSUPPORTED = "Unsupported type"


IMAGE_KINDS = frozenset({AssetKind.STILL, AssetKind.EDITED})
# Kinds that may show a packaged fixture picture (a video poster frame is still a still picture).
MEDIA_KINDS = frozenset({AssetKind.STILL, AssetKind.EDITED, AssetKind.VIDEO, AssetKind.SEQUENCE})

CATEGORY_HISTORY = "History"
CATEGORY_EDIT = "Edit & Photo"
CATEGORY_VIDEO = "Video"
CATEGORY_MOTION = "Motion Library"
CATEGORY_LEARNING = "Learning"
CATEGORY_IMPORTED = "Imported"
CATEGORIES = (
    CATEGORY_HISTORY,
    CATEGORY_EDIT,
    CATEGORY_VIDEO,
    CATEGORY_MOTION,
    CATEGORY_LEARNING,
    CATEGORY_IMPORTED,
)


class Scope(StrEnum):
    ALL = "all"
    HISTORY = "history"
    EDIT_PHOTO = "edit-photo"
    VIDEO = "video"
    MOTION = "motion"
    LEARNING = "learning"
    IMPORTED = "imported"
    COLLECTIONS = "collections"
    FAVORITES = "favorites"


SCOPE_LABELS = {
    Scope.ALL: "All supported mock assets",
    Scope.HISTORY: "Generated Images (History fixtures)",
    Scope.EDIT_PHOTO: "Edit & Photo candidates",
    Scope.VIDEO: "Video Clips and Storyboards",
    Scope.MOTION: "Motion References",
    Scope.LEARNING: "Learning Observations",
    Scope.IMPORTED: "Explicitly Imported Fixtures",
    Scope.COLLECTIONS: "Collections",
    Scope.FAVORITES: "Favorites",
}
SCOPE_SHORT = {
    Scope.ALL: "All assets",
    Scope.HISTORY: "Generated images",
    Scope.EDIT_PHOTO: "Edit & Photo",
    Scope.VIDEO: "Video & Storyboards",
    Scope.MOTION: "Motion references",
    Scope.LEARNING: "Learning observations",
    Scope.IMPORTED: "Imported fixtures",
    Scope.COLLECTIONS: "Collections",
    Scope.FAVORITES: "Favorites",
}
SCOPE_CATEGORY = {
    Scope.HISTORY: CATEGORY_HISTORY,
    Scope.EDIT_PHOTO: CATEGORY_EDIT,
    Scope.VIDEO: CATEGORY_VIDEO,
    Scope.MOTION: CATEGORY_MOTION,
    Scope.LEARNING: CATEGORY_LEARNING,
    Scope.IMPORTED: CATEGORY_IMPORTED,
}


class SearchMode(StrEnum):
    METADATA = "Metadata"
    PROMPT_PREFIX = "Prompt prefix"


class Sort(StrEnum):
    RECENT = "Newest first"
    OLDEST = "Oldest first"
    LABEL = "Label A–Z"
    SOURCE = "Source, label"


class EmptyState(StrEnum):
    EMPTY_SOURCE = "Empty source"
    NO_MATCHES = "No filter matches"


class ViewState(StrEnum):
    READY = "Ready"
    LOADING = "Loading"
    ERROR = "Read error"


# --------------------------------------------------------------------------------------- identity
@dataclass(frozen=True, order=True)
class AssetRef:
    namespace: str
    record_id: str

    @property
    def key(self) -> str:
        return f"{self.namespace}:{self.record_id}"

    @classmethod
    def parse(cls, key: str) -> AssetRef:
        namespace, _, record_id = key.partition(":")
        if not namespace or not record_id:
            raise LibraryRefused(f"Not a source-qualified identity: {key!r}.")
        return cls(namespace, record_id)


@dataclass(frozen=True)
class AssetRecord:
    """An immutable source fixture. Optional fields are ``None`` when unknown, never invented."""

    ref: AssetRef
    label: str
    kind: AssetKind
    category: str
    availability: Availability = Availability.AVAILABLE
    size: tuple[int, int] | None = None
    duration: float | None = None
    model: str | None = None
    workflow: str | None = None
    created: str | None = None  # ISO date of the fixture
    prompt: str | None = None
    content_hash: str | None = None
    parent: AssetRef | None = None
    job_id: str | None = None
    observation_id: str | None = None
    references: AssetRef | None = None
    rating: int | None = None
    experiment: str | None = None
    motif: int | None = None  # packaged illustration index; None means "no media of its own"
    native_key: str | None = None  # destination-owned identity (Edit/Motion fixture key or clip id)
    recipe_pack: str | None = None  # known Create recipe route, if any
    retired: bool = False

    @property
    def key(self) -> str:
        return self.ref.key

    @property
    def namespace(self) -> str:
        return self.ref.namespace


class Catalog:
    """Immutable set of source fixtures. Looks records up; never mutates or scans anything."""

    def __init__(self, records: list[AssetRecord] | tuple[AssetRecord, ...]):
        self._records: dict[str, AssetRecord] = {}
        for record in records:
            if record.key in self._records:
                raise LibraryRefused(f"Duplicate source identity: {record.key}.")
            self._records[record.key] = record
        self._by_hash: dict[str, list[str]] = {}
        for record in self._records.values():
            if record.content_hash:
                self._by_hash.setdefault(record.content_hash, []).append(record.key)

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self):
        return iter(self._records.values())

    def __contains__(self, key: object) -> bool:
        return key in self._records

    def get(self, key: str) -> AssetRecord:
        try:
            return self._records[key]
        except KeyError:
            raise LibraryRefused(f"Unknown source identity: {key}. Nothing was substituted.") from None

    def keys(self) -> tuple[str, ...]:
        return tuple(self._records)

    def with_hash(self, content_hash: str) -> tuple[str, ...]:
        return tuple(self._by_hash.get(content_hash, ()))

    def children_of(self, key: str) -> tuple[str, ...]:
        return tuple(r.key for r in self if r.parent is not None and r.parent.key == key)

    def observations_of(self, key: str) -> tuple[str, ...]:
        return tuple(r.key for r in self if r.references is not None and r.references.key == key)


# -------------------------------------------------------------------------------- fixture catalog
def _hash(token: str) -> str:
    return "sha256:" + hashlib.sha256(f"fixture-bytes:{token}".encode()).hexdigest()[:16]


def _rec(namespace: str, record_id: str, label: str, kind: AssetKind, category: str, **kw):
    return AssetRecord(AssetRef(namespace, record_id), label, kind, category, **kw)


def _still(namespace: str, record_id: str, label: str, motif: int, **kw) -> AssetRecord:
    kw.setdefault("size", (640, 400))
    kw.setdefault("content_hash", _hash(f"{namespace}:{record_id}"))
    kw.setdefault("category", CATEGORY_HISTORY)
    kind = kw.pop("kind", AssetKind.STILL)
    category = kw.pop("category")
    return _rec(namespace, record_id, label, kind, category, motif=motif, **kw)


def _curated() -> list[AssetRecord]:
    refs = {s.key: s for s in STILL_SOURCES}
    ridge16, ridge17 = AssetRef("history", "ridge-16"), AssetRef("history", "ridge-17")
    twin_hash = _hash("harbor-twin-bytes")
    records: list[AssetRecord] = [
        _still("history", "ridge-16", "Ridge revision 16", 0, model="fixture-sdxl", workflow="txt2img",
               created="2026-10-02", job_id="fixture-job-16", native_key="history:ridge-16",
               prompt="Ridge at dusk, long shadows, painterly", recipe_pack="pack-landscapes"),
        _still("history", "ridge-17", "Ridge revision 17", 1, model="fixture-sdxl", workflow="img2img",
               created="2026-10-03", job_id="fixture-job-17", native_key="history:ridge-17",
               parent=ridge16, prompt="Ridge at dusk, long shadows, warmer sky",
               recipe_pack="pack-landscapes"),
        _still("create", "ridge-study", "Ridge study (Create result)", 0, model="fixture-sdxl",
               workflow="txt2img", created="2026-10-05", native_key="create:ridge-study",
               prompt="Ridge study, overcast morning"),
        _still("history", "coast-04", "Coast study 4", 2, size=(800, 400), model="fixture-flux",
               workflow="txt2img", created="2026-10-08", job_id="fixture-job-44",
               prompt="Wide coast, low tide, soft haze", recipe_pack="pack-landscapes"),
        _still("history", "twin-a", "Harbor study (copy A)", 3, content_hash=twin_hash,
               model="fixture-sdxl", workflow="txt2img", created="2026-10-09", job_id="fixture-job-61",
               prompt="Harbor at first light, gulls"),
        _still("history", "twin-b", "Harbor study (copy B)", 3, content_hash=twin_hash,
               model="fixture-sdxl", workflow="txt2img", created="2026-10-10", job_id="fixture-job-62",
               prompt="Harbor at first light, gulls"),
        _still("history", "near-a", "Harbor study (similar A)", 3, model="fixture-sdxl",
               workflow="txt2img", created="2026-10-10", job_id="fixture-job-63",
               prompt="Harbor at dawn, boats"),
        _still("history", "near-b", "Harbor study (similar B)", 2, model="fixture-flux",
               workflow="txt2img", created="2026-10-11", job_id="fixture-job-64",
               prompt="Harbor at dawn, mist"),
        _still("history", "missing", "Missing still", 0, availability=Availability.MISSING,
               model="fixture-sdxl", created="2026-09-28", job_id="fixture-job-9",
               native_key="history:missing", prompt="Ridge, file since removed"),
        _still("history", "hidden", "Restricted still", 1, availability=Availability.HIDDEN,
               model="fixture-sdxl", created="2026-09-29", job_id="fixture-job-10",
               native_key="history:hidden", prompt="Restricted fixture content"),
        _still("photo", "evening", "Evening candidate", 3, size=(600, 400), category=CATEGORY_EDIT,
               created="2026-10-11", native_key="photo:evening", model="fixture-sdxl",
               workflow="photo-optimize"),
        _still("edit", "fixture-candidate-1", "Edited candidate (ridge, warmer sky)", 1,
               kind=AssetKind.EDITED, category=CATEGORY_EDIT, parent=ridge17, model="fixture-sdxl",
               workflow="masked-edit", created="2026-10-12", job_id="fixture-job-edit-1"),
        _still("import", "coast", "Imported coast study", 2, category=CATEGORY_IMPORTED,
               created="2026-10-06", native_key="import:coast"),
        _still("anchor", "ridge-dusk", "Ridge at dusk (authored anchor)", 3,
               category=CATEGORY_IMPORTED, created="2026-10-07", native_key="anchor:ridge-dusk"),
        _rec("import", "clip", "Imported clip (unsupported type)", AssetKind.UNSUPPORTED,
             CATEGORY_IMPORTED, availability=Availability.UNSUPPORTED, created="2026-10-06",
             native_key="import:clip"),
    ]
    assert refs["import:clip"].availability == Availability.UNSUPPORTED  # keep fixtures aligned
    # Video fixtures mirror the Motion mock history so eligibility parity can be tested.
    motion = MotionSession()
    for clip_id in (
        "hist-run-1-clip-1",
        "hist-run-1-clip-2",
        "hist-run-1-clip-3",
        "hist-clip-lost",
        "hist-clip-retired",
    ):
        clip = motion.clip(clip_id)
        available = clip.output_available
        records.append(
            _rec("video", clip_id, f"Clip · {clip.label}", AssetKind.VIDEO, CATEGORY_VIDEO,
                 availability=Availability.AVAILABLE if available else Availability.MISSING,
                 duration=round(clip.seconds, 2), model=clip.workflow[0], workflow=clip.workflow[0],
                 created="2026-10-14", parent=AssetRef.parse(clip.source_key), job_id=clip.run_id,
                 motif=0, native_key=clip.clip_id, retired=clip.clip_id == "hist-clip-retired",
                 content_hash=_hash(f"video:{clip.clip_id}"))
        )
    run = motion.run("hist-run-1")
    records.append(
        _rec("video", "hist-board-1", "Storyboard run · Fixture Ridge walk", AssetKind.SEQUENCE,
             CATEGORY_VIDEO, duration=round(sum(c.seconds for c in run.clips), 2),
             model="svd_native", created="2026-10-14", job_id=run.run_id, motif=0)
    )
    for key, title, availability in REFERENCES:
        namespace, _, record_id = key.partition(":")
        records.append(
            _rec(namespace, record_id, title, AssetKind.MOTION_REF, CATEGORY_MOTION,
                 availability=availability, created="2026-10-01", native_key=key,
                 content_hash=_hash(key))
        )
    for obs_id, ref, experiment, rating, created in (
        ("0101", ridge17, "fixture-exp-A", 4, "2026-10-15"),
        ("0102", ridge17, "fixture-exp-B", 2, "2026-10-16"),
        ("0103", AssetRef("history", "twin-a"), "fixture-exp-A", 3, "2026-10-15"),
        ("0104", AssetRef("history", "twin-b"), "fixture-exp-C", 5, "2026-10-17"),
    ):
        target = next(r for r in records if r.ref == ref)
        records.append(
            _rec("learning", f"obs-{obs_id}", f"Observation · {target.label} ({experiment})",
                 AssetKind.OBSERVATION, CATEGORY_LEARNING, model=target.model, created=created,
                 observation_id=f"mock-obs-{obs_id}", references=ref, rating=rating,
                 experiment=experiment, job_id=target.job_id)
        )
    return records


def bulk_records(count: int) -> list[AssetRecord]:
    """Deterministic lightweight records: no files, no decoding until a tile is shown."""
    records = []
    for i in range(1, count + 1):
        availability = (
            Availability.MISSING if i % 37 == 0 else Availability.HIDDEN if i % 53 == 0 else Availability.AVAILABLE
        )  # fmt: skip
        day = 1 + (i % 27)
        records.append(
            _still("history", f"gen-{i:05d}", f"Generated study {i:05d}", i % 4,
                   availability=availability, model="fixture-flux" if i % 3 == 0 else "fixture-sdxl",
                   workflow="txt2img", created=f"2026-09-{day:02d}", job_id=f"fixture-job-b{i}",
                   prompt=f"Generated study {i}, {('mist', 'dusk', 'noon', 'night')[i % 4]}")
        )
    return records


def fixture_catalog(bulk: int = 120) -> Catalog:
    return Catalog([*_curated(), *bulk_records(bulk)])


# ------------------------------------------------------------------------------- similarity/groups
@dataclass(frozen=True)
class AssetGroup:
    group_id: str
    label: str
    members: tuple[str, ...]
    caveat: str
    exact: bool


ILLUSTRATIVE_GROUPS = (
    AssetGroup(
        "sim-harbor",
        SIMILARITY_LABEL,
        ("history:twin-a", "history:twin-b", "history:near-a", "history:near-b"),
        "Predetermined fixture relationship. No embedding, perceptual match or model ran. Grouping "
        "does not establish a common parent, provenance or statistical independence.",
        False,
    ),
    AssetGroup(
        "sim-ridge",
        SIMILARITY_LABEL,
        ("history:ridge-16", "history:ridge-17", "create:ridge-study"),
        "Predetermined fixture relationship. No embedding, perceptual match or model ran. Grouping "
        "does not establish a common parent, provenance or statistical independence.",
        False,
    ),
)


def exact_groups(catalog: Catalog) -> tuple[AssetGroup, ...]:
    """Records whose fixture content hashes are equal. Each member keeps its own identity."""
    groups = []
    seen: set[str] = set()
    for record in catalog:
        h = record.content_hash
        if not h or h in seen:
            continue
        members = catalog.with_hash(h)
        if len(members) > 1:
            seen.add(h)
            groups.append(
                AssetGroup(
                    f"exact-{h[7:15]}",
                    EXACT_LABEL,
                    members,
                    "Equal bytes are not one logical asset: each record keeps its own job, "
                    "provenance, collections and research observations. Nothing is merged or deleted.",
                    True,
                )
            )
    return tuple(groups)


def groups_of(catalog: Catalog, key: str) -> tuple[AssetGroup, ...]:
    return tuple(g for g in (*exact_groups(catalog), *ILLUSTRATIVE_GROUPS) if key in g.members)


# ------------------------------------------------------------------------------ organization state
@dataclass(frozen=True)
class Collection:
    collection_id: str
    name: str
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrgState:
    """Mutable-by-replacement presentation metadata. It references source keys and never copies them."""

    collections: tuple[Collection, ...] = ()
    tags: tuple[tuple[str, tuple[str, ...]], ...] = ()
    favorites: frozenset[str] = frozenset()
    archived: frozenset[str] = frozenset()  # simulated Photo-style archive only
    next_collection: int = 1

    def collection(self, collection_id: str) -> Collection:
        for c in self.collections:
            if c.collection_id == collection_id:
                return c
        raise LibraryRefused(f"Unknown collection: {collection_id}.")

    def tags_of(self, key: str) -> tuple[str, ...]:
        for k, tags in self.tags:
            if k == key:
                return tags
        return ()

    def collections_of(self, key: str) -> tuple[Collection, ...]:
        return tuple(c for c in self.collections if key in c.members)

    def all_tags(self) -> tuple[str, ...]:
        return tuple(sorted({t for _, tags in self.tags for t in tags}))


def initial_org() -> OrgState:
    return OrgState(
        collections=(
            Collection(
                "col-1", "Ridge project",
                ("history:ridge-16", "history:ridge-17", "create:ridge-study"),
            ),
            Collection("col-2", "Client review", ("history:ridge-17", "history:coast-04")),
        ),
        tags=(("history:coast-04", ("coast",)), ("history:ridge-17", ("keeper", "ridge"))),
        next_collection=3,
    )


# ------------------------------------------------------------------------------------------ query
@dataclass(frozen=True)
class LibraryQuery:
    scope: Scope = Scope.ALL
    text: str = ""
    mode: SearchMode = SearchMode.METADATA
    kinds: frozenset[AssetKind] = frozenset()
    categories: frozenset[str] = frozenset()
    models: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()
    favorites_only: bool = False
    availability: frozenset[Availability] = frozenset()
    collection: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sort: Sort = Sort.RECENT
    page: int = 0
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def filters_active(self) -> bool:
        return self != replace(
            LibraryQuery(), scope=self.scope, sort=self.sort, page=self.page,
            page_size=self.page_size, mode=self.mode,
        )  # fmt: skip

    def cleared(self) -> LibraryQuery:
        """Clear filters and search. The source scope, sort, mode and page size stay."""
        return LibraryQuery(
            scope=self.scope, sort=self.sort, mode=self.mode, page_size=self.page_size
        )


@dataclass(frozen=True)
class QueryResult:
    query: LibraryQuery
    items: tuple[str, ...]  # keys on the current page, in sort order
    matched: tuple[str, ...]  # every key that passed all filters, in sort order
    scope_total: int
    page: int
    page_count: int
    empty: EmptyState | None
    notices: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.matched)

    @property
    def first_number(self) -> int:
        return self.page * self.query.page_size + 1 if self.items else 0

    @property
    def last_number(self) -> int:
        return self.page * self.query.page_size + len(self.items)

    def summary(self) -> str:
        if not self.items:
            return f"0 results · {self.scope_total} in this source scope"
        return (
            f"{self.first_number}–{self.last_number} of {self.total} results · page "
            f"{self.page + 1} of {self.page_count} · {self.scope_total} in this source scope"
        )


def _in_scope(record: AssetRecord, query: LibraryQuery, org: OrgState) -> bool:
    scope = query.scope
    if scope == Scope.ALL:
        return True
    if scope == Scope.FAVORITES:
        return record.key in org.favorites
    if scope == Scope.COLLECTIONS:
        return bool(org.collections_of(record.key))
    return record.category == SCOPE_CATEGORY[scope]


def scope_count(catalog: Catalog, org: OrgState, scope: Scope) -> int:
    probe = LibraryQuery(scope=scope)
    return sum(1 for r in catalog if _in_scope(r, probe, org))


def _metadata_haystack(record: AssetRecord, org: OrgState) -> str:
    parts = [
        record.label, record.key, record.kind.value, record.category,
        record.model or "", record.workflow or "", *org.tags_of(record.key),
    ]  # fmt: skip
    return " ".join(parts).casefold()


def run_query(
    catalog: Catalog,
    org: OrgState,
    query: LibraryQuery,
    availability_of: Callable[[AssetRecord], Availability] | None = None,
) -> QueryResult:
    """Pure, deterministic filter -> sort -> page. Unknown fields are excluded by their own filter and
    that exclusion is reported, never silently widened."""
    effective = availability_of or (lambda r: r.availability)
    if query.page_size < 1:
        raise LibraryRefused("Page size must be at least 1.")
    in_scope = [r for r in catalog if _in_scope(r, query, org)]
    notices: list[str] = []
    rows = in_scope
    if query.collection is not None:
        members = set(org.collection(query.collection).members)
        rows = [r for r in rows if r.key in members]
    if query.kinds:
        rows = [r for r in rows if r.kind in query.kinds]
    if query.categories:
        rows = [r for r in rows if r.category in query.categories]
    if query.availability:
        rows = [r for r in rows if effective(r) in query.availability]
    if query.favorites_only:
        rows = [r for r in rows if r.key in org.favorites]
    if query.tags:
        rows = [r for r in rows if query.tags <= set(org.tags_of(r.key))]
    if query.models:
        unknown = sum(1 for r in rows if r.model is None)
        rows = [r for r in rows if r.model in query.models]
        if unknown:
            notices.append(f"{unknown} record(s) have no model metadata and are excluded by the model filter.")
    if query.date_from or query.date_to:
        unknown = sum(1 for r in rows if r.created is None)
        rows = [
            r
            for r in rows
            if r.created is not None
            and (not query.date_from or r.created >= query.date_from)
            and (not query.date_to or r.created <= query.date_to)
        ]
        if unknown:
            notices.append(f"{unknown} record(s) have an unknown date and are excluded by the date filter.")
    text = " ".join(query.text.split())
    if text:
        if query.mode == SearchMode.PROMPT_PREFIX:
            needle = text.casefold()
            if len(needle) > PROMPT_INDEX_LEN:
                needle = needle[:PROMPT_INDEX_LEN]
                notices.append(f"Only the first {PROMPT_INDEX_LEN} characters of a prompt are indexed; the query was cut to match.")
            unindexed = sum(1 for r in rows if not r.prompt)
            rows = [r for r in rows if r.prompt and r.prompt[:PROMPT_INDEX_LEN].casefold().startswith(needle)]
            if unindexed:
                notices.append(f"{unindexed} record(s) have no indexed prompt prefix and cannot match a prompt search.")
        else:
            words = text.casefold().split(" ")
            rows = [r for r in rows if all(w in _metadata_haystack(r, org) for w in words)]
    rows = _sorted(rows, query.sort)
    matched = tuple(r.key for r in rows)
    page_count = max(1, math.ceil(len(matched) / query.page_size))
    page = min(max(0, query.page), page_count - 1)
    start = page * query.page_size
    empty = None
    if not matched:
        empty = EmptyState.EMPTY_SOURCE if not in_scope else EmptyState.NO_MATCHES
        if query.collection is not None and not org.collection(query.collection).members:
            empty = EmptyState.EMPTY_SOURCE
    return QueryResult(
        query, matched[start : start + query.page_size], matched, len(in_scope), page, page_count,
        empty, tuple(notices),
    )  # fmt: skip


def _sorted(rows: list[AssetRecord], sort: Sort) -> list[AssetRecord]:
    rows = sorted(rows, key=lambda r: r.key)
    if sort == Sort.RECENT:
        return sorted(rows, key=lambda r: r.created or "", reverse=True)
    if sort == Sort.OLDEST:
        return sorted(rows, key=lambda r: (r.created is None, r.created or ""))
    if sort == Sort.LABEL:
        return sorted(rows, key=lambda r: r.label.casefold())
    order = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(rows, key=lambda r: (order.get(r.category, 99), r.label.casefold()))


class SelectionStatus(StrEnum):
    ON_PAGE = "On this page"
    OTHER_PAGE = "On another page of these results"
    FILTERED_OUT = "Outside the current scope or filters"


def selection_status(result: QueryResult, selection: tuple[str, ...]) -> dict[str, SelectionStatus]:
    page, matched = set(result.items), set(result.matched)
    return {
        key: SelectionStatus.ON_PAGE if key in page
        else SelectionStatus.OTHER_PAGE if key in matched
        else SelectionStatus.FILTERED_OUT
        for key in selection
    }  # fmt: skip


# ------------------------------------------------------------------------------------- availability
def availability_reason(availability: Availability) -> str:
    return {
        Availability.AVAILABLE: "",
        Availability.MISSING: "Missing file: the source entry is kept, but no media is available. "
        "Nothing was substituted (relinking would be a future source-owned capability).",
        Availability.HIDDEN: "Hidden by fixture policy: identity is shown, but the media is never "
        "decoded, previewed, compared, copied or dragged.",
        Availability.UNSUPPORTED: "Unsupported type: shown as metadata only.",
    }[availability]


# --------------------------------------------------------------------------------- action vocabulary
class ActionId(StrEnum):
    INSPECT = "inspect"
    EDIT = "edit"
    ANIMATE = "animate"
    STORYBOARD = "storyboard"
    MOVIE = "movie"
    COMPARE = "compare"
    REGENERATE = "regenerate"
    LEARNING = "learning"
    ADD_COLLECTION = "add-collection"
    REMOVE_COLLECTION = "remove-collection"
    FAVORITE = "favorite"
    ARCHIVE_PHOTO = "archive-photo"
    RESTORE_PHOTO = "restore-photo"
    ARCHIVE_GENERAL = "archive-general"
    DELETE = "delete"


ACTION_LABELS = {
    ActionId.INSPECT: "Inspect",
    ActionId.EDIT: "Edit Image",
    ActionId.ANIMATE: "Animate in Motion",
    ActionId.STORYBOARD: "Add to Storyboard",
    ActionId.MOVIE: "Add to Movie Clips",
    ActionId.COMPARE: "Compare with Parent",
    ActionId.REGENERATE: "Regenerate with Changes",
    ActionId.LEARNING: "Propose Learning Source",
    ActionId.ADD_COLLECTION: "Add to Collection",
    ActionId.REMOVE_COLLECTION: "Remove from Collection",
    ActionId.FAVORITE: "Favorite",
    ActionId.ARCHIVE_PHOTO: "Archive (simulated Photo policy)",
    ActionId.RESTORE_PHOTO: "Restore (simulated Photo policy)",
    ActionId.ARCHIVE_GENERAL: "Archive",
    ActionId.DELETE: "Delete source artifact",
}
# Actions that hand work to another workspace (and therefore get the placement review).
HANDOFF_ACTIONS = (
    ActionId.EDIT, ActionId.ANIMATE, ActionId.STORYBOARD, ActionId.MOVIE, ActionId.REGENERATE,
    ActionId.LEARNING,
)  # fmt: skip
ACTION_ORDER = (
    ActionId.INSPECT, ActionId.EDIT, ActionId.ANIMATE, ActionId.STORYBOARD, ActionId.MOVIE,
    ActionId.COMPARE, ActionId.REGENERATE, ActionId.LEARNING, ActionId.ADD_COLLECTION,
    ActionId.REMOVE_COLLECTION, ActionId.FAVORITE, ActionId.ARCHIVE_PHOTO, ActionId.RESTORE_PHOTO,
    ActionId.ARCHIVE_GENERAL, ActionId.DELETE,
)  # fmt: skip
DESTINATIONS = {
    ActionId.INSPECT: "Library inspector",
    ActionId.EDIT: "Edit & Improve",
    ActionId.ANIMATE: "Motion · Quick Clip",
    ActionId.STORYBOARD: "Motion · Storyboard",
    ActionId.MOVIE: "Motion · Movie Clips",
    ActionId.COMPARE: "Library comparison",
    ActionId.REGENERATE: "Create Image",
    ActionId.LEARNING: "Learning (mock proposal only)",
    ActionId.ADD_COLLECTION: "Library collection",
    ActionId.REMOVE_COLLECTION: "Library collection",
    ActionId.FAVORITE: "Library favorites",
    ActionId.ARCHIVE_PHOTO: "Photo (simulated)",
    ActionId.RESTORE_PHOTO: "Photo (simulated)",
    ActionId.ARCHIVE_GENERAL: "General archive",
    ActionId.DELETE: "Source artifact",
}
# How many items one placement takes. ``None`` means an ordered set.
CAPACITY: dict[ActionId, int | None] = {
    ActionId.INSPECT: 1, ActionId.EDIT: 1, ActionId.ANIMATE: 1, ActionId.STORYBOARD: 1,
    ActionId.COMPARE: 1, ActionId.REGENERATE: 1, ActionId.MOVIE: MAX_MOVIE_CLIPS,
    ActionId.LEARNING: MAX_LEARNING_SOURCES,
}  # fmt: skip
GATED = {
    ActionId.ARCHIVE_GENERAL: "Future-gated (UX-DEC-041): general archive needs an approved ownership "
    "and dependency policy. Only a source-specific Photo archive is simulated here.",
    ActionId.DELETE: "Future-gated (UX-DEC-041): deleting a source artifact needs approved ownership, "
    "dependency and recovery semantics. The Library never deletes anything. Removing a collection "
    "reference is the only organizing removal.",
}
EDIT_KEYS = frozenset(s.key for s in STILL_SOURCES)
MOTION_IMAGE_KEYS = EDIT_KEYS | frozenset(a[0] for a in ANCHORS)
MOTION_REFERENCE_KEYS = frozenset(r[0] for r in REFERENCES)


@dataclass(frozen=True)
class Verdict:
    key: str
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class ActionEligibility:
    action: ActionId
    destination: str
    verdicts: tuple[Verdict, ...]
    set_reason: str = ""
    gated: bool = False

    @property
    def label(self) -> str:
        return ACTION_LABELS[self.action]

    @property
    def eligible(self) -> tuple[str, ...]:
        return tuple(v.key for v in self.verdicts if v.ok)

    @property
    def blocked(self) -> tuple[Verdict, ...]:
        return tuple(v for v in self.verdicts if not v.ok)

    @property
    def placeable(self) -> bool:
        return bool(self.verdicts) and not self.gated and not self.set_reason and not self.blocked

    @property
    def needs_narrowing(self) -> bool:
        """Some, but not all, of the selection can be placed (or the destination takes fewer)."""
        return not self.gated and bool(self.eligible) and not self.placeable

    @property
    def reason(self) -> str:
        """One readable sentence for a disabled control."""
        if self.gated:
            return self.set_reason
        if not self.verdicts:
            return "Select at least one asset."
        if self.set_reason:
            return self.set_reason
        if self.blocked:
            first = self.blocked[0]
            more = f" (+{len(self.blocked) - 1} more)" if len(self.blocked) > 1 else ""
            return f"{first.key}: {first.reason}{more}"
        return ""


@dataclass(frozen=True)
class RuleContext:
    """What the explicit eligibility rules may read. Built by the session; has no side effects."""

    catalog: Catalog
    org: OrgState
    availability_of: Callable[[AssetRecord], Availability]
    collection: str | None = None
    already_in_assembly: frozenset[str] = frozenset()


def _unavailable(record: AssetRecord, ctx: RuleContext) -> str:
    availability = ctx.availability_of(record)
    if availability != Availability.AVAILABLE:
        return availability_reason(availability)
    if record.key in ctx.org.archived:
        return "Archived under the simulated Photo policy: restore it before using it elsewhere."
    return ""


def _edit_rule(record: AssetRecord, ctx: RuleContext) -> str:
    if record.kind not in IMAGE_KINDS:
        return f"Edit works on still images; this is a {record.kind.value.lower()}."
    if problem := _unavailable(record, ctx):
        return problem
    if record.native_key not in EDIT_KEYS:
        return f"Edit has no fixture for {record.key}. The Library will not substitute another image."
    return ""


def _animate_rule(record: AssetRecord, ctx: RuleContext) -> str:
    if record.kind == AssetKind.MOTION_REF:
        if problem := _unavailable(record, ctx):
            return problem
        if record.native_key not in MOTION_REFERENCE_KEYS:
            return "Motion has no fixture for this motion reference."
        return ""
    if record.kind == AssetKind.VIDEO or record.kind == AssetKind.SEQUENCE:
        return "Motion animates still images or takes a motion reference; use Movie Clips for clips."
    if record.kind not in IMAGE_KINDS:
        return f"Motion cannot use a {record.kind.value.lower()} as a source."
    if problem := _unavailable(record, ctx):
        return problem
    if record.native_key not in MOTION_IMAGE_KEYS:
        return f"Motion has no fixture for {record.key}. The Library will not substitute another image."
    return ""


def _storyboard_rule(record: AssetRecord, ctx: RuleContext) -> str:
    if record.kind not in IMAGE_KINDS:
        return f"A Storyboard anchors on a still image; this is a {record.kind.value.lower()}."
    if problem := _unavailable(record, ctx):
        return problem
    if record.native_key not in MOTION_IMAGE_KEYS:
        return f"Motion has no fixture for {record.key}. The Library will not substitute another image."
    return ""


def _movie_rule(record: AssetRecord, ctx: RuleContext) -> str:
    if record.kind == AssetKind.SEQUENCE:
        return "A storyboard run is a summary, not a clip. Add its individual clips instead."
    if record.kind != AssetKind.VIDEO:
        return f"Movie Clips assembles video clips; this is a {record.kind.value.lower()}."
    if problem := _unavailable(record, ctx):
        return problem
    if record.retired:
        return "Produced by a retired workflow."
    if record.native_key in ctx.already_in_assembly:
        return "Already in the Movie Clips assembly."
    return ""


def _compare_rule(record: AssetRecord, ctx: RuleContext) -> str:
    if record.kind in (AssetKind.VIDEO, AssetKind.SEQUENCE):
        return "Video comparison is not supported. Only direct-parent still-image comparison is shown."
    if record.kind not in IMAGE_KINDS:
        return f"Comparison needs two still images; this is a {record.kind.value.lower()}."
    if record.parent is None:
        return "No known parent is recorded for this asset, so no comparison is offered."
    if problem := _unavailable(record, ctx):
        return problem
    if record.parent.key not in ctx.catalog:
        return f"Recorded parent {record.parent.key} is not in the catalog."
    parent = ctx.catalog.get(record.parent.key)
    if parent.kind not in IMAGE_KINDS:
        return "The recorded parent is not a still image."
    if problem := _unavailable(parent, ctx):
        return f"Parent {parent.key}: {problem}"
    return ""


def _regenerate_rule(record: AssetRecord, ctx: RuleContext) -> str:
    if record.kind not in IMAGE_KINDS:
        return f"Regeneration starts from a still image recipe; this is a {record.kind.value.lower()}."
    if problem := _unavailable(record, ctx):
        return problem
    if not record.recipe_pack:
        return "No known recipe is recorded for this asset. The Library will not guess one."
    return ""


def _learning_rule(record: AssetRecord, ctx: RuleContext) -> str:
    if record.kind == AssetKind.OBSERVATION:
        target = ctx.catalog.get(record.references.key) if record.references else None
        if target is None:
            return "The observation references no known asset."
        if problem := _unavailable(target, ctx):
            return f"Observed asset {target.key}: {problem}"
        return ""
    if record.kind not in IMAGE_KINDS:
        return f"Learning sources are observed stills; this is a {record.kind.value.lower()}."
    if problem := _unavailable(record, ctx):
        return problem
    if not record.job_id:
        return "No job or record lineage is recorded, so it cannot be proposed as a Learning source."
    return ""


_RULES: dict[ActionId, Callable[[AssetRecord, RuleContext], str]] = {
    ActionId.EDIT: _edit_rule,
    ActionId.ANIMATE: _animate_rule,
    ActionId.STORYBOARD: _storyboard_rule,
    ActionId.MOVIE: _movie_rule,
    ActionId.COMPARE: _compare_rule,
    ActionId.REGENERATE: _regenerate_rule,
    ActionId.LEARNING: _learning_rule,
}


def _organize_rule(action: ActionId, record: AssetRecord, ctx: RuleContext) -> str:
    """References never need available media: an unavailable asset can still be organized."""
    if action == ActionId.REMOVE_COLLECTION:
        if ctx.collection is None:
            return "Choose a collection first."
        if record.key not in ctx.org.collection(ctx.collection).members:
            return "Not a member of the chosen collection."
    if action == ActionId.ARCHIVE_PHOTO:
        if record.namespace != "photo":
            return f"Archive is source-specific: {record.namespace} has no approved archive policy."
        if record.key in ctx.org.archived:
            return "Already archived under the simulated Photo policy."
    if action == ActionId.RESTORE_PHOTO:
        if record.namespace != "photo" or record.key not in ctx.org.archived:
            return "Only an archived Photo fixture can be restored."
    return ""


def evaluate_action(action: ActionId, keys: tuple[str, ...], ctx: RuleContext) -> ActionEligibility:
    """Explicit per-action eligibility for the *whole* ordered selection. Never silently drops an item."""
    destination = DESTINATIONS[action]
    if action in GATED:
        verdicts = tuple(Verdict(k, False, "Future-gated.") for k in keys)
        return ActionEligibility(action, destination, verdicts, GATED[action], gated=True)
    records = [ctx.catalog.get(k) for k in keys]
    verdicts = []
    for record in records:
        if action == ActionId.INSPECT:
            reason = ""
        elif action in _RULES and record.kind == AssetKind.UNSUPPORTED:
            reason = availability_reason(Availability.UNSUPPORTED)
        elif action in _RULES:
            reason = _RULES[action](record, ctx)
        else:
            reason = _organize_rule(action, record, ctx)
        verdicts.append(Verdict(record.key, not reason, reason))
    set_reason = ""
    capacity = CAPACITY.get(action)
    if keys and capacity is not None and len(keys) > capacity:
        noun = "one asset" if capacity == 1 else f"at most {capacity} assets"
        set_reason = (
            f"{ACTION_LABELS[action]} takes {noun} at a time; "
            f"{len(keys)} are selected. Narrow the selection."
        )
    if keys and action == ActionId.ANIMATE and len({r.kind == AssetKind.MOTION_REF for r in records}) > 1:
        set_reason = "A motion reference and a source image are different placements. Narrow the selection."
    return ActionEligibility(action, destination, tuple(verdicts), set_reason)


# ---------------------------------------------------------------------------------------- relations
@dataclass(frozen=True)
class Relation:
    kind: str
    key: str
    caveat: str = ""


def relations(catalog: Catalog, key: str) -> tuple[Relation, ...]:
    record = catalog.get(key)
    out: list[Relation] = []
    if record.parent is not None:
        out.append(Relation("Parent", record.parent.key, "Recorded lineage."))
    out += [Relation("Child", k, "Recorded lineage.") for k in catalog.children_of(key)]
    if record.references is not None:
        out.append(Relation("Observed asset", record.references.key, "This record is an observation."))
    out += [
        Relation("Observation", k, "A separate research record about this asset.")
        for k in catalog.observations_of(key)
    ]
    for group in groups_of(catalog, key):
        for member in group.members:
            if member != key:
                caveat = (
                    "Same content hash, distinct record." if group.exact else SIMILARITY_LABEL
                )
                out.append(Relation("Same content" if group.exact else "Similar", member, caveat))
    return tuple(out)


@dataclass(frozen=True)
class FieldRow:
    name: str
    value: str


def describe(record: AssetRecord) -> tuple[FieldRow, ...]:
    """Every identity field, with unknown shown as unknown rather than invented."""

    def show(value: object) -> str:
        return UNKNOWN if value is None or value == "" else str(value)

    return (
        FieldRow("Source record ID", record.ref.record_id),
        FieldRow("Source namespace", record.ref.namespace),
        FieldRow("Qualified identity", record.key),
        FieldRow("Type", record.kind.value),
        FieldRow("Source category", record.category),
        FieldRow("Content hash", show(record.content_hash)),
        FieldRow("Parent", show(record.parent.key if record.parent else None)),
        FieldRow("Job / record lineage", show(record.job_id)),
        FieldRow("Observation ID", show(record.observation_id)),
        FieldRow("Dimensions", f"{record.size[0]}×{record.size[1]}" if record.size else UNKNOWN),
        FieldRow("Duration", f"{record.duration:g} s" if record.duration is not None else UNKNOWN),
        FieldRow("Model", show(record.model)),
        FieldRow("Workflow", show(record.workflow)),
        FieldRow("Created (fixture)", show(record.created)),
    )
