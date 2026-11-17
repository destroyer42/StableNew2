"""Toolkit-neutral session for the task-first Review workspace (PR-REVIEW-LIFECYCLE-621).

Review is one lifecycle: *Review -> Retain / Discard / Re-work -> individual or batch Re-work -> Review again*. The
workspace is **logical**: only the operator's decisions and ratings are stored (as Learning evidence rows through the
existing ``LearningRecordWriter``); everything about jobs is derived from the job repository each time, the way the
Batches view derives its batches. Nothing here queues, runs or compiles. The one file this session
moves is an image the operator discards or restores (PR-REVIEW-ARCHIVE-623): Discard moves it into
``<output root>/_archive`` through ``src.review.archive`` (reversibly, never overwriting, refusing with a visible reason),
and Undo / Restore / Retain / Re-work move it back first. Where a file is is always read from the file system, never
remembered, so a refresh after a restart agrees with what is on disk.

All state, derivation and action gating live here so they are testable without Tk. Blocking work (hashing, reading the
evidence file, reading the repository, writing a decision) runs through the existing ``EditWorkRunner`` off the UI thread;
every completion is dropped when the session was superseded or closed, so a late result can never overwrite newer state.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.gui.view_contracts.edit_work_runner import EditWorkRunner
from src.queue.job_model import JobStatus
from src.review.archive import (
    ALREADY_ARCHIVED,
    OCCUPIED,
    ArchiveOutcome,
    archived_location,
)
from src.review.review_evidence import (
    DISPOSITION_CLEARED,
    IDENTITY_CHANGED,
    EvidenceIndex,
    file_sha256,
)
from src.review.review_lineage import (
    LineageResult,
    LineageSource,
    ReviewChild,
    find_review_children,
)
from src.utils.image_metadata import ImageMetadataContractV26, read_image_metadata


class ItemState(str, Enum):
    TO_REVIEW = "to_review"
    RETAINED = "retained"
    ARCHIVED = "archived"
    REWORK_MARKED = "rework_marked"
    REWORK_QUEUED = "rework_queued"
    REWORK_FAILED = "rework_failed"
    RETURNED = "returned"
    CHANGED = "changed"


STATE_LABELS: dict[ItemState, str] = {
    ItemState.TO_REVIEW: "To review",
    ItemState.RETAINED: "Retained",
    ItemState.ARCHIVED: "Archived",
    ItemState.REWORK_MARKED: "Re-work marked",
    ItemState.REWORK_QUEUED: "Re-work queued",
    ItemState.REWORK_FAILED: "Re-work failed",
    ItemState.RETURNED: "Returned",
    ItemState.CHANGED: "Changed since reviewed",
}
#: States that still need an operator decision (what "advance to the next undecided image" looks for).
UNDECIDED = frozenset({ItemState.TO_REVIEW, ItemState.RETURNED, ItemState.CHANGED})
REWORK_STATES = frozenset(
    {ItemState.REWORK_MARKED, ItemState.REWORK_QUEUED, ItemState.REWORK_FAILED}
)


class ViewFilter(str, Enum):
    #: The default: everything except what the operator archived.
    ACTIVE = "active"
    TO_REVIEW = "to_review"
    RETAINED = "retained"
    REWORK = "rework"
    ARCHIVED = "archived"
    ALL = "all"


FILTER_LABELS: dict[ViewFilter, str] = {
    ViewFilter.ACTIVE: "Active",
    ViewFilter.TO_REVIEW: "To review",
    ViewFilter.RETAINED: "Retained",
    ViewFilter.REWORK: "Re-work",
    ViewFilter.ARCHIVED: "Archived",
    ViewFilter.ALL: "All",
}

_DISPOSITION_STATE = {
    "retain": ItemState.RETAINED,
    "discard": ItemState.ARCHIVED,
    "rework": ItemState.REWORK_MARKED,
}


@dataclass(frozen=True)
class ActionState:
    enabled: bool
    #: Why the action is unavailable, or what it will do when enabled (used as the control's tooltip).
    reason: str


@dataclass(frozen=True)
class ReviewItem:
    """One image under review. ``key`` is its identity inside the set; the digest lives in :class:`ItemFacts`."""

    path: Path
    key: str

    @property
    def name(self) -> str:
        return self.path.name


def item_key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


@dataclass(frozen=True)
class ItemFacts:
    """What was read about one image (digest, decision, rating, children); states are derived from it."""

    digest: str = ""
    job_id: str = ""
    disposition: str = ""
    #: ``digest``, ``path`` or ``changed`` (see ``review_evidence``); empty when no decision was recorded.
    identity: str = ""
    rating: int | None = None
    children: tuple[ReviewChild, ...] = ()
    loaded: bool = False
    #: When the decision was recorded (UTC, naive), so a re-work finished *before* a newer mark is not counted for it.
    decided_at: datetime | None = None
    #: Where the file is now: ``in_place`` (at its original path), ``archived`` (only at its archive location) or
    #: ``missing`` (neither); empty until it was read.
    location: str = ""


LOC_IN_PLACE = "in_place"
LOC_ARCHIVED = "archived"
LOC_MISSING = "missing"


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _parse_stamp(*values: str) -> datetime | None:
    """The first parsable UTC stamp (sub-second ``decided_at`` first, the record's whole-second timestamp after)."""

    for value in values:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            continue
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
    return None


@dataclass(frozen=True)
class WorkspaceFacts:
    items: dict[str, ItemFacts] = field(default_factory=dict)
    #: Facts of the finished children's outputs (keyed by output path), for their own decision state.
    outputs: dict[str, ItemFacts] = field(default_factory=dict)
    lineage_truncated: bool = False
    cancelled: bool = False
    #: Images discarded and archived from the opened folder that the folder scan can no longer list (from records).
    archived_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ReturnedRow:
    """A finished re-work output shown beside its source."""

    source_key: str
    source_name: str
    path: Path
    job_id: str
    #: ``verified`` or ``unverified`` (the job named this image's digest, or only its job id).
    relation: str
    state: ItemState
    in_set: bool


@dataclass(frozen=True)
class UndoEntry:
    key: str
    path: Path
    digest: str
    job_id: str
    previous: str
    previous_identity: str


def derive_state(facts: ItemFacts, *, returned: bool = False) -> ItemState:
    """The state of an image from its recorded decision and the jobs that name it as their source."""

    if not facts.loaded:
        return ItemState.TO_REVIEW
    if facts.identity == IDENTITY_CHANGED:
        return ItemState.CHANGED
    disposition = facts.disposition
    if disposition == "discard":
        return ItemState.ARCHIVED
    if disposition == "retain":
        return ItemState.RETAINED
    if disposition in ("", "rework") and any(child.active for child in facts.children):
        return ItemState.REWORK_QUEUED
    if disposition == "rework":
        since = [
            child
            for child in facts.children
            if facts.decided_at is None or child.created_at > facts.decided_at
        ]
        latest = max(since, key=lambda child: child.created_at, default=None)
        if latest is not None and latest.status is JobStatus.FAILED:
            return ItemState.REWORK_FAILED
        if latest is not None and latest.status is JobStatus.COMPLETED:
            # Its re-work is back: the source awaits a decision (and is no longer in the re-work scope).
            return ItemState.RETURNED
        return ItemState.REWORK_MARKED
    return ItemState.RETURNED if returned else ItemState.TO_REVIEW


def _embedded_job_id(path: Path) -> str:
    try:
        return str(read_image_metadata(path).get(ImageMetadataContractV26.KEY_JOB_ID) or "")
    except Exception:  # noqa: BLE001 - an unreadable container only means the lineage is by digest alone
        return ""


@dataclass(frozen=True)
class FileRead:
    digest: str = ""
    job_id: str = ""
    location: str = LOC_MISSING


class FileFactsCache:
    """Digest, embedded job id and location per file, valid while the file's size and mtime are unchanged.

    A refresh (and the 5 s poll while a re-work is queued) would otherwise hash and parse every image again. A file
    whose ``(size, mtime_ns)`` or place changed is read again, so "Changed since reviewed" still works; a file that
    cannot be stat'ed is never cached. An image Review archived is read from its archive location (the bytes are the
    same), so its decision still resolves by digest while the item keeps its original path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[tuple[str, int, int], FileRead]] = {}

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def read_full(self, path: Path, output_root: Path | None = None) -> FileRead:
        effective, location = path, LOC_IN_PLACE
        if not os.path.lexists(path):
            archived = archived_location(path, output_root=output_root)
            effective, location = (archived, LOC_ARCHIVED) if archived else (path, LOC_MISSING)
        try:
            stat = effective.stat()
            stamp: tuple[str, int, int] | None = (
                os.path.normcase(str(effective)),
                stat.st_size,
                stat.st_mtime_ns,
            )
        except OSError:
            stamp = None
        key = item_key(path)
        if stamp is not None:
            with self._lock:
                hit = self._entries.get(key)
            if hit is not None and hit[0] == stamp:
                return hit[1]
        digest = file_sha256(effective) or ""
        read = FileRead(digest, _embedded_job_id(effective) if digest else "", location)
        if stamp is not None and digest:
            with self._lock:
                self._entries[key] = (stamp, read)
        return read

    def read(self, path: Path) -> tuple[str, str]:
        """``(digest, embedded job id)``; both empty when the file is unreadable."""

        found = self.read_full(path)
        return found.digest, found.job_id


def _facts_for(
    path: Path,
    index: EvidenceIndex,
    cache: FileFactsCache | None = None,
    *,
    loaded: bool = True,
    output_root: Path | None = None,
) -> tuple[ItemFacts, str]:
    read = (cache or FileFactsCache()).read_full(path, output_root)
    digest, job_id = read.digest, read.job_id
    decision = index.disposition(path, digest or None)
    rating = index.rating(path, digest or None)
    value: int | None = None
    if rating.row is not None and rating.identity != IDENTITY_CHANGED:
        raw = rating.row["metadata"].get("user_rating_raw")
        try:
            value = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            value = None
    return (
        ItemFacts(
            digest=digest,
            job_id=job_id,
            disposition=decision.disposition,
            identity=decision.identity,
            rating=value,
            loaded=loaded,
            decided_at=_parse_stamp(decision.decided_at, decision.timestamp),
            location=read.location,
        ),
        digest,
    )


def _archived_from_records(
    index: EvidenceIndex,
    folder: Path | None,
    present: Sequence[Path],
    output_root: Path | None,
) -> list[Path]:
    """Originals under ``folder`` whose latest decision is Discard and whose file now lives only in the archive."""

    if folder is None:
        return []
    have = {item_key(path) for path in present}
    base = item_key(folder)
    found: list[Path] = []
    for recorded, digest in index.discarded():
        key = item_key(recorded)
        if key in have or not (key == base or key.startswith(base.rstrip(os.sep) + os.sep)):
            continue
        original = Path(recorded)
        if os.path.lexists(original):
            continue  # back in place (or never moved): the folder scan lists it when it is there
        if archived_location(original, output_root=output_root, digest=digest or None) is not None:
            have.add(key)
            found.append(original)
    return sorted(found)


def collect_facts(
    paths: Sequence[Path],
    *,
    records_path: Path | None,
    repository: Any,
    is_current: Callable[[], bool] = lambda: True,
    cache: FileFactsCache | None = None,
    output_root: Path | None = None,
    folder: Path | None = None,
) -> WorkspaceFacts:
    """Blocking: read each image's digest and decision, then the repository's children of those images.

    Run it on a worker. ``is_current`` is polled between images so a superseded request stops early. ``cache``
    (the session's) spares re-hashing a file whose size and mtime did not change. ``output_root`` locates archived
    files; with ``folder`` (an opened folder) the images archived from it are listed from their records too.
    """

    index = EvidenceIndex.read(records_path)
    extra = _archived_from_records(index, folder, paths, output_root)
    paths = [*paths, *extra]
    facts: dict[str, ItemFacts] = {}
    sources: list[LineageSource] = []
    for path in paths:
        if not is_current():
            return WorkspaceFacts(cancelled=True)
        item_facts, digest = _facts_for(path, index, cache, output_root=output_root)
        key = item_key(path)
        facts[key] = item_facts
        sources.append(LineageSource(key, digest, item_facts.job_id))
    lineage: LineageResult = find_review_children(repository, sources)
    outputs: dict[str, ItemFacts] = {}
    for key, children in lineage.by_source.items():
        facts[key] = replace(facts[key], children=children)
        for child in children:
            for output in child.outputs:
                if not is_current():
                    return WorkspaceFacts(cancelled=True)
                outputs[item_key(output)] = _facts_for(
                    Path(output), index, cache, output_root=output_root
                )[0]
    return WorkspaceFacts(facts, outputs, lineage.truncated, archived_paths=tuple(extra))


@dataclass(frozen=True)
class _WriteResult:
    disposition: str
    outcome: ArchiveOutcome | None = None
    #: The file could not be put back, so nothing was recorded (the item stays discarded).
    blocked: bool = False


@dataclass(frozen=True)
class RestoreOffer:
    """The original location holds a different file; ``alternative`` is a free name the operator may accept."""

    key: str
    alternative: Path


class ReviewWorkspaceSession:
    """The set of images under review, their derived states and the gated actions over them."""

    def __init__(
        self,
        *,
        runner: EditWorkRunner,
        records_path: Callable[[], Path | None] = lambda: None,
        repository: Callable[[], Any] = lambda: None,
        write_disposition: Callable[[Path, str, str, str], Any] | None = None,
        on_change: Callable[[], None] | None = None,
        output_root: Callable[[], Path | None] = lambda: None,
        archive: Callable[[Path, str], ArchiveOutcome] | None = None,
        restore: Callable[[Path, str, bool], ArchiveOutcome] | None = None,
    ) -> None:
        self._runner = runner
        self._records_path = records_path
        self._repository = repository
        self._write = write_disposition
        self._on_change = on_change or (lambda: None)
        self._output_root = output_root
        #: Worker-side file moves (``None``: decisions stay logical and no file is ever moved).
        self._archive = archive
        self._restore = restore
        self._folder: Path | None = None
        #: Why a discarded image was left where it was (this session only; the file system is the record).
        self.archive_notes: dict[str, str] = {}
        self.restore_offer: RestoreOffer | None = None
        self.items: list[ReviewItem] = []
        self.facts: dict[str, ItemFacts] = {}
        self.output_facts: dict[str, ItemFacts] = {}
        self.filter: ViewFilter = ViewFilter.ACTIVE
        self.loading = False
        self.lineage_truncated = False
        self.message = ""
        self._generation = 0
        self._writes = 0
        self._cache = FileFactsCache()
        #: Ordinal of the last local decision / rating per image; a refresh that began earlier never overwrites it.
        self._ordinal = 0
        self._decided: dict[str, int] = {}
        self._rated: dict[str, int] = {}
        self._pending: dict[str, str] = {}
        self._undo: list[UndoEntry] = []
        self._closed = False

    # -- lifecycle --------------------------------------------------------------------------------------

    def close(self) -> None:
        self._closed = True

    def _changed(self) -> None:
        if not self._closed:
            self._on_change()

    def _say(self, text: str) -> None:
        self.message = text
        self._changed()

    # -- the set -----------------------------------------------------------------------------------------

    def set_items(
        self,
        paths: Sequence[str | os.PathLike[str]],
        *,
        folder: str | os.PathLike[str] | None = None,
    ) -> None:
        """A new set (a folder, files, a job or a batch): every earlier request becomes stale.

        ``folder`` is the opened folder, when the set is one: images discarded from it are listed from their
        records even though the folder scan no longer finds their files.
        """

        self._generation += 1
        self.items, self.facts, self.output_facts = [], {}, {}
        self._folder = Path(folder) if folder is not None else None
        self.archive_notes, self.restore_offer = {}, None
        self._pending, self._undo, self.message = {}, [], ""
        self._decided, self._rated = {}, {}
        self._cache.clear()
        self.lineage_truncated = False
        self._add(paths)
        self.refresh()

    def add_items(
        self, paths: Sequence[str | os.PathLike[str]], *, after: str | None = None
    ) -> list[str]:
        """Add images (a finished re-work output) to the set; those already present keep their place."""

        keys = self._add(paths, after=after)
        self._changed()
        self.refresh()
        return keys

    def _add(
        self, paths: Sequence[str | os.PathLike[str]], *, after: str | None = None
    ) -> list[str]:
        present = {item.key for item in self.items}
        position = len(self.items)
        if after is not None:
            position = next(
                (index + 1 for index, item in enumerate(self.items) if item.key == after), position
            )
        added: list[str] = []
        for path in paths:
            key = item_key(path)
            if key not in present:
                present.add(key)
                self.items.insert(position, ReviewItem(Path(path), key))
                position += 1
            added.append(key)
        return added

    def clear(self) -> None:
        self.set_items(())

    def item(self, key: str | None) -> ReviewItem | None:
        return next((item for item in self.items if item.key == key), None)

    def paths(self) -> list[Path]:
        return [item.path for item in self.items]

    # -- derivation -------------------------------------------------------------------------------------

    def _returned_keys(self) -> set[str]:
        return {
            item_key(output)
            for facts in self.facts.values()
            for child in facts.children
            for output in child.outputs
        }

    def facts_of(self, key: str) -> ItemFacts:
        facts = self.facts.get(key, ItemFacts())
        pending = self._pending.get(key)
        if pending is not None:
            facts = replace(
                facts,
                disposition="" if pending == DISPOSITION_CLEARED else pending,
                identity="digest",
                loaded=True,
                decided_at=_utc_now(),
            )
        return facts

    def state_of(self, key: str) -> ItemState:
        return derive_state(self.facts_of(key), returned=key in self._returned_keys())

    def label_of(self, key: str) -> str:
        return STATE_LABELS[self.state_of(key)]

    def counts(self) -> dict[ItemState, int]:
        returned = self._returned_keys()
        found: dict[ItemState, int] = dict.fromkeys(ItemState, 0)
        for item in self.items:
            found[derive_state(self.facts_of(item.key), returned=item.key in returned)] += 1
        return found

    def filter_counts(self) -> dict[ViewFilter, int]:
        counts = self.counts()
        return {
            ViewFilter.ACTIVE: len(self.items) - counts[ItemState.ARCHIVED],
            ViewFilter.TO_REVIEW: sum(counts[state] for state in UNDECIDED),
            ViewFilter.RETAINED: counts[ItemState.RETAINED],
            ViewFilter.REWORK: sum(counts[state] for state in REWORK_STATES),
            ViewFilter.ARCHIVED: counts[ItemState.ARCHIVED],
            ViewFilter.ALL: len(self.items),
        }

    def counts_text(self) -> str:
        counts = self.filter_counts()
        return "  ".join(
            f"{FILTER_LABELS[view]} {counts[view]}"
            for view in (
                ViewFilter.TO_REVIEW,
                ViewFilter.RETAINED,
                ViewFilter.REWORK,
                ViewFilter.ARCHIVED,
            )
        )

    def set_filter(self, value: ViewFilter) -> None:
        self.filter = value
        self._changed()

    def _matches(self, state: ItemState) -> bool:
        view = self.filter
        if view is ViewFilter.ALL:
            return True
        if view is ViewFilter.ACTIVE:
            return state is not ItemState.ARCHIVED
        if view is ViewFilter.TO_REVIEW:
            return state in UNDECIDED
        if view is ViewFilter.RETAINED:
            return state is ItemState.RETAINED
        if view is ViewFilter.REWORK:
            return state in REWORK_STATES
        return state is ItemState.ARCHIVED

    def visible_items(self) -> list[ReviewItem]:
        returned = self._returned_keys()
        return [
            item
            for item in self.items
            if self._matches(derive_state(self.facts_of(item.key), returned=item.key in returned))
        ]

    def row_text(self, item: ReviewItem) -> str:
        facts = self.facts_of(item.key)
        rating = f"  {'*' * facts.rating}" if facts.rating else ""
        state = self.state_of(item.key)
        label = STATE_LABELS[state] if facts.loaded else "..."
        place = ""
        if state is ItemState.ARCHIVED and self._archive is not None and facts.loaded:
            place = {LOC_ARCHIVED: " (in archive)", LOC_IN_PLACE: " (not moved)"}.get(
                facts.location, " (file missing)"
            )
        return f"[{label}] {item.name}{place}{rating}"

    def archive_line(self, key: str | None) -> str:
        """What to tell the operator about one archived image: where the file is and, if not moved, why."""

        if key is None or self.state_of(key) is not ItemState.ARCHIVED or self._archive is None:
            return ""
        facts = self.facts_of(key)
        if facts.location == LOC_ARCHIVED:
            return "Archived: the file is in the archive folder. Restore (or Undo) puts it back."
        note = self.archive_notes.get(key, "")
        if facts.location == LOC_IN_PLACE:
            return f"Discarded but not moved{': ' + note if note else '.'} Discard again to retry."
        return "Discarded, but the file is neither at its original path nor in the archive."

    def next_undecided(self, after: str | None) -> str | None:
        """The next visible image after ``after`` that still needs a decision (``None`` when there is none)."""

        visible = self.visible_items()
        start = next((index + 1 for index, item in enumerate(visible) if item.key == after), 0)
        for item in visible[start:]:
            if self.state_of(item.key) in UNDECIDED:
                return item.key
        return None

    def returned_rows(self) -> list[ReturnedRow]:
        in_set = {item.key for item in self.items}
        rows: list[ReturnedRow] = []
        for item in self.items:
            for child in self.facts_of(item.key).children:
                for output in child.outputs:
                    out_key = item_key(output)
                    # An output already in the set is decided there; otherwise by what was read for it.
                    own = (
                        self.facts_of(out_key)
                        if out_key in in_set
                        else self.output_facts.get(out_key, ItemFacts())
                    )
                    state = derive_state(own, returned=True) if own.loaded else ItemState.RETURNED
                    rows.append(
                        ReturnedRow(
                            item.key,
                            item.name,
                            Path(output),
                            child.job_id,
                            child.relation,
                            state,
                            out_key in in_set,
                        )
                    )
        return rows

    def compare_partner(self, key: str | None) -> tuple[Path, str] | None:
        """The image to compare ``key`` with: its latest returned result, else the source it came from.

        Returns ``(path, relation)`` where ``relation`` is ``"returned"`` (the partner is this image's re-work
        result) or ``"source"`` (the partner is the image this one was re-worked from); ``None`` when neither exists.
        """

        if key is None:
            return None
        children = [
            c for c in self.facts_of(key).children if c.status is JobStatus.COMPLETED and c.outputs
        ]
        if children:
            latest = max(children, key=lambda child: child.created_at)
            return Path(latest.outputs[-1]), "returned"
        for item in self.items:
            for child in self.facts_of(item.key).children:
                if any(item_key(output) == key for output in child.outputs):
                    return item.path, "source"
        return None

    # -- refresh -----------------------------------------------------------------------------------------

    def refresh(self) -> bool:
        """Re-read decisions and the repository's children for the current set (latest request wins)."""

        if self._closed:
            return False
        if not self.items and self._folder is None:
            self.loading = False
            self._changed()
            return False
        self._generation += 1
        generation = self._generation
        paths = self.paths()
        records, repository = self._records_path(), self._repository()
        root, folder = self._output_root(), self._folder
        began = self._ordinal
        self.loading = True
        self._changed()

        def work() -> WorkspaceFacts:
            return collect_facts(
                paths,
                records_path=records,
                repository=repository,
                is_current=lambda: generation == self._generation and not self._closed,
                cache=self._cache,
                output_root=root,
                folder=folder,
            )

        def done(result: WorkspaceFacts) -> None:
            if self._closed or generation != self._generation or result.cancelled:
                return
            self.loading = False
            for path in result.archived_paths:
                if self.item(item_key(path)) is None:
                    self.items.append(ReviewItem(path, item_key(path)))
            known = {item.key for item in self.items}
            self.facts = self._merge_local(result.items, known, began)
            self.output_facts = dict(result.outputs)
            self.lineage_truncated = result.lineage_truncated
            if result.lineage_truncated:
                self.message = (
                    "The lineage read limit was reached; some re-work results may be missing."
                )
            self._changed()

        def failed(error: Exception) -> None:
            if self._closed or generation != self._generation:
                return
            self.loading = False
            self._say(f"Could not read review state: {type(error).__name__}: {error}")

        self._runner.submit(
            f"review:workspace-facts:{generation}",
            work,
            on_result=done,
            on_error=failed,
            name="review-workspace-facts",
            purpose="Read review decisions and re-work lineage for the Review set",
        )
        return True

    def _merge_local(
        self, read: dict[str, ItemFacts], known: set[str], began: int
    ) -> dict[str, ItemFacts]:
        """A refresh's facts, except a decision or rating recorded here after that refresh began (the newer wins).

        The refresh read the evidence file when it started, so a decision (or Undo/Restore) whose write finished
        while it was hashing is not in its result; lineage and digests from the refresh are still applied.
        """

        merged: dict[str, ItemFacts] = {}
        for key, value in read.items():
            if key not in known:
                continue
            local = self.facts.get(key)
            if local is not None:
                if self._decided.get(key, 0) > began:
                    value = replace(
                        value,
                        disposition=local.disposition,
                        identity=local.identity,
                        decided_at=local.decided_at,
                        location=local.location or value.location,
                    )
                if self._rated.get(key, 0) > began:
                    value = replace(value, rating=local.rating)
            merged[key] = value
        return merged

    # -- decisions ----------------------------------------------------------------------------------------

    def decide_state(self, key: str | None, disposition: str) -> ActionState:
        if self._write is None:
            return ActionState(
                False, "Review decisions are unavailable: Learning evidence is not connected."
            )
        item = self.item(key)
        if item is None:
            return ActionState(False, "Select an image first.")
        if key in self._pending:
            return ActionState(False, "The previous decision for this image is still being saved.")
        if disposition == "discard" and self._archive is not None:
            return ActionState(
                True,
                f"Discard {item.name}: moves it to the archive folder; Undo or Restore puts it back. "
                "Nothing is deleted.",
            )
        return ActionState(
            True,
            f"Record {disposition} for {item.name}."
            + (
                " An archived file is put back first."
                if self._archive is not None and self.facts_of(item.key).disposition == "discard"
                else " The file is never changed."
            ),
        )

    def decide(self, key: str | None, disposition: str) -> bool:
        gate = self.decide_state(key, disposition)
        if not gate.enabled or key is None:
            self._say(gate.reason)
            return False
        item = self.item(key)
        assert item is not None
        before = self.facts_of(key)
        self._submit_write(item, before, disposition, push_undo=True)
        return True

    def decide_many(self, keys: Sequence[str], disposition: str) -> int:
        """Record ``disposition`` for each image (one write and, for Discard, one move each); returns how many began."""

        return sum(1 for key in dict.fromkeys(keys) if self.decide(key, disposition))

    def restore(self, key: str | None, *, use_alternative: bool = False) -> bool:
        """Bring an archived image back: move the file home, then a clearing row so it is to be reviewed again."""

        if self.state_of(key or "") is not ItemState.ARCHIVED:
            self._say("Only an archived image can be restored.")
            return False
        gate = self.decide_state(key, DISPOSITION_CLEARED)
        item = self.item(key)
        if not gate.enabled or item is None:
            self._say(gate.reason)
            return False
        self.restore_offer = None
        self._submit_write(
            item,
            self.facts_of(item.key),
            DISPOSITION_CLEARED,
            push_undo=True,
            use_alternative=use_alternative,
        )
        return True

    def take_restore_offer(self) -> RestoreOffer | None:
        offer, self.restore_offer = self.restore_offer, None
        return offer

    def _submit_write(
        self,
        item: ReviewItem,
        before: ItemFacts,
        disposition: str,
        *,
        push_undo: bool,
        use_alternative: bool = False,
        retry: UndoEntry | None = None,
    ) -> None:
        self._writes += 1
        write = self._write
        assert write is not None
        self._pending[item.key] = disposition
        self._changed()
        digest, job_id = before.digest, before.job_id
        archive, restore = self._archive, self._restore
        was_discarded = before.disposition == "discard"

        def work() -> _WriteResult:
            if disposition == "discard":
                write(item.path, digest, job_id, disposition)
                outcome = archive(item.path, digest) if archive is not None else None
                return _WriteResult(disposition, outcome)
            outcome = None
            if was_discarded and restore is not None:
                # Put the file back before recording anything: a refused restore leaves the image archived.
                outcome = restore(item.path, digest, use_alternative)
                if outcome.status in ("refused", "failed"):
                    return _WriteResult(disposition, outcome, blocked=True)
            write(item.path, digest, job_id, disposition)
            return _WriteResult(disposition, outcome)

        def done(result: _WriteResult) -> None:
            self._pending.pop(item.key, None)
            if self._closed:
                return
            outcome = result.outcome
            if result.blocked:
                if retry is not None:
                    self._undo.append(retry)
                self._restore_blocked(item, outcome)
                return
            current = self.facts.get(item.key, before)
            location = self._location_after(item, current, disposition, outcome)
            self.facts[item.key] = replace(
                current,
                disposition="" if disposition == DISPOSITION_CLEARED else disposition,
                identity="digest",
                loaded=True,
                decided_at=_utc_now(),
                location=location,
            )
            self._ordinal += 1
            self._decided[item.key] = self._ordinal
            if push_undo:
                self._undo.append(
                    UndoEntry(
                        item.key, item.path, digest, job_id, before.disposition, before.identity
                    )
                )
            if (
                outcome is not None
                and outcome.moved
                and outcome.target is not None
                and item_key(outcome.target) != item.key
                and disposition != "discard"
            ):
                self.add_items([outcome.target], after=item.key)
            self._changed()

        def failed(error: Exception) -> None:
            self._pending.pop(item.key, None)
            if retry is not None:
                self._undo.append(retry)
            self._say(f"The decision for {item.name} was not saved: {error}")

        self._runner.submit(
            f"review:decide:{self._writes}",
            work,
            on_result=done,
            on_error=failed,
            name="review-decision",
            purpose="Record a Review decision as Learning evidence and move the file",
        )

    def _location_after(
        self,
        item: ReviewItem,
        current: ItemFacts,
        disposition: str,
        outcome: ArchiveOutcome | None,
    ) -> str:
        """Where the file is after a decision, from what the move reported (a refresh re-reads the disk anyway)."""

        if self._archive is None:
            return current.location
        if disposition == "discard":
            if outcome is not None and (outcome.moved or outcome.code == ALREADY_ARCHIVED):
                self.archive_notes.pop(item.key, None)
                if outcome.moved:
                    self.message = (
                        f"{item.name} was moved to the archive. Undo or Restore puts it back."
                    )
                return LOC_ARCHIVED
            reason = (outcome.message if outcome is not None else "") or "the file was not moved."
            self.archive_notes[item.key] = reason
            self.message = f"{item.name} is discarded but was not moved: {reason}"
            return LOC_IN_PLACE
        self.archive_notes.pop(item.key, None)
        if outcome is not None and outcome.status == "duplicate":
            self.message = f"{item.name}: {outcome.message}"
        return LOC_IN_PLACE

    def _restore_blocked(self, item: ReviewItem, outcome: ArchiveOutcome | None) -> None:
        reason = (
            outcome.message if outcome is not None else ""
        ) or "the file could not be restored."
        if outcome is not None and outcome.code == OCCUPIED and outcome.alternative is not None:
            self.restore_offer = RestoreOffer(item.key, outcome.alternative)
            reason += " It can be restored under a new name."
        self._say(f"{item.name} was not restored: {reason}")

    @property
    def can_undo(self) -> bool:
        return bool(self._undo) and self._write is not None

    def undo(self) -> bool:
        """Undo the last decision by recording the earlier one (or a clearing row); nothing is deleted."""

        if not self.can_undo:
            self._say("No decision to undo.")
            return False
        entry = self._undo.pop()
        item = self.item(entry.key)
        if item is None or entry.key in self._pending:
            self._say("The decision cannot be undone right now.")
            return False
        restored = entry.previous or DISPOSITION_CLEARED
        before = self.facts_of(entry.key)
        self._submit_write(item, before, restored, push_undo=False, retry=entry)
        return True

    def note_rating(self, key: str, rating: int | None) -> None:
        if self.item(key) is not None:
            self.facts[key] = replace(self.facts.get(key, ItemFacts()), rating=rating)
            self._ordinal += 1
            self._rated[key] = self._ordinal
            self._changed()

    # -- re-work scope and tool gating -------------------------------------------------------------------

    def rework_scope(self) -> list[ReviewItem]:
        """The images a re-work would process: marked (or failed) and not already queued or running."""

        return [
            item
            for item in self.items
            if self.state_of(item.key) in (ItemState.REWORK_MARKED, ItemState.REWORK_FAILED)
        ]

    def marked_items(self) -> list[ReviewItem]:
        return [item for item in self.items if self.state_of(item.key) in REWORK_STATES]

    def scope_line(self) -> str:
        scope, marked = self.rework_scope(), self.marked_items()
        queued = len(marked) - len(scope)
        text = f"Re-work: {len(scope)} image(s) will be processed"
        if queued:
            text += f"; {queued} already queued"
        return text

    def rework_state(self) -> ActionState:
        scope = self.rework_scope()
        if not scope:
            return ActionState(False, "Mark one or more images for Re-work first.")
        return ActionState(
            True, f"Preview, then queue {len(scope)} image(s) through the existing Review path."
        )

    def single_tool_state(self, current: str | None) -> ActionState:
        """Mask, canvas, Smart Review, Inspect & Improve and Klein work on exactly one image."""

        scope = self.rework_scope()
        if len(scope) > 1:
            return ActionState(
                False,
                f"{len(scope)} images are marked for Re-work and this tool edits one image. "
                "Unmark all but one, or use the batch settings below.",
            )
        if scope:
            return ActionState(True, f"Edits {scope[0].name}.")
        if current is not None and self.item(current) is not None:
            return ActionState(True, "Edits the image shown.")
        return ActionState(False, "Select an image first.")

    def single_target(self, current: str | None) -> ReviewItem | None:
        scope = self.rework_scope()
        if len(scope) == 1:
            return scope[0]
        return self.item(current) if not scope else None


__all__ = [
    "ActionState",
    "FILTER_LABELS",
    "FileRead",
    "ItemFacts",
    "ItemState",
    "LOC_ARCHIVED",
    "LOC_IN_PLACE",
    "LOC_MISSING",
    "RestoreOffer",
    "ReturnedRow",
    "ReviewItem",
    "ReviewWorkspaceSession",
    "STATE_LABELS",
    "UNDECIDED",
    "UndoEntry",
    "ViewFilter",
    "WorkspaceFacts",
    "collect_facts",
    "derive_state",
    "item_key",
]
