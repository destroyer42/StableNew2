"""Storyboard submission service: create roots, preview, submit and reconcile takes (PR-VID-STORY-380, spec 7.5).

Every Continue ends in exactly one ``JobService.submit_njrs`` call on the canonical path. Each take is a sequence job
under plan policy v2, admitted through ``build_sequence_njr`` (the same core as the Video Workflow sequence path). The
storyboard file records takes and their job ids (attempts); job state is always read back from the repository.

Crash-safe recording: the pending takes (no attempts) are written with revision compare-and-swap before admission, the
NJRs cross ``submit_njrs`` once, and the attempts are written after. When admission or submission raises, the takes whose
jobs the repository holds keep them as attempts, the rest are removed, and the error is re-raised. When the second write fails, the takes stay pending and
:meth:`StoryboardSubmissionService.reconcile` adopts the queued jobs by the storyboard link stamped in each plan.

All methods are synchronous and worker-safe: they read and write files and the storyboard store, never Tk.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any, Final, Literal

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.video.sequence_admission import LEAD_IN_OVERLAP
from src.video.sequence_job_build import build_sequence_njr
from src.video.sequence_plan import (
    ANCHOR_CARRY,
    ROOT_PARENT,
    SequencePlanError,
    StoryboardLeadIn,
    StoryboardPlanLink,
    default_overlap,
)
from src.video.storyboard import timestamp
from src.video.storyboard_cut import CutManifest
from src.video.storyboard_cuts import read_job, root_cut, take_cut, write_lead_in
from src.video.storyboard_import import ClipImporter, ClipImportPlan
from src.video.storyboard_projection import TakeView, first_missing_frame, project_storyboard
from src.video.storyboard_reconcile import adopt_job
from src.video.storyboard_root import (
    PreparedRoot,
    prepare_clip_root,
    prepare_image_root,
)
from src.video.storyboard_tree import (
    MAX_ROWS,
    StoryboardTree,
    StoryboardTreeError,
    Take,
    TreeRoot,
    check_storyboard_id,
)
from src.video.storyboard_tree_store import StoryboardTreeStore
from src.video.video_workflow_intent import EXPERIMENTAL_OPT_IN_FIELD, parse_seed_input
from src.video.video_workflow_njr_builder import (
    FrozenVideoInputs,
    VideoWorkflowBuild,
    VideoWorkflowNjrBuilder,
)
from src.video.workflow_contracts import WORKFLOW_GOVERNANCE_EXPERIMENTAL
from src.video.workflow_frame_count import parse_frame_count

#: How many of the newest repository jobs reconciliation reads (a bounded read; no new table or index).
RECONCILE_WINDOW: Final = 200

logger = logging.getLogger(__name__)

Mode = Literal["parallel", "sequential"]


@dataclass(frozen=True, slots=True)
class ContinueRow:
    prompt: str
    negative_prompt: str
    #: Blank or ``random`` is drawn at admission; a whole number is used as given.
    seed: str


@dataclass(frozen=True, slots=True)
class ContinueRequest:
    storyboard_id: str
    expected_revision: int
    #: A take id, or ``ROOT_PARENT``.
    parent_id: str
    #: 0-based index of the handoff frame in the parent's cut; ``None`` only for an image root.
    handoff_index: int | None
    mode: Mode
    rows: tuple[ContinueRow, ...]
    experimental_opt_in: bool = False


@dataclass(frozen=True, slots=True)
class ContinuePreview:
    jobs: int
    segments: int
    lead_in_frames: int
    #: The length of each take's cut (parallel) or of the chain's whole cut (sequential), lead-in included.
    total_cut_frames: int
    fps: int
    workflow_id: str
    workflow_version: str
    #: Each row's seed intent (``random`` where the row left it blank); nothing is drawn by a preview.
    seeds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContinueResult:
    job_ids: tuple[str, ...]
    take_ids: tuple[str, ...]
    tree: StoryboardTree


class StoryboardSubmissionService:
    """Create storyboards, preview and submit Continue requests, and reconcile takes with the repository."""

    def __init__(
        self,
        *,
        njr_builder: VideoWorkflowNjrBuilder,
        workflow_registry: Any,
        job_service: Callable[[], Any],
        repository: Callable[[], Any],
        store: StoryboardTreeStore | None = None,
        output_root: Callable[[], str],
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        draw_seed: Callable[[], int] = lambda: secrets.randbelow(2**31),
        clip_importer: ClipImporter | None = None,
    ) -> None:
        self._njr_builder = njr_builder
        self._registry = workflow_registry
        self._job_service = job_service
        self._repository = repository
        self.store = store if store is not None else StoryboardTreeStore()
        self._output_root = output_root
        self._new_id = new_id
        self._draw_seed = draw_seed
        self.clip_importer = clip_importer or ClipImporter(
            repository=repository, registry=workflow_registry, output_root=output_root
        )

    # ------------------------------------------------------------------------------------------ roots

    def inspect_clip(self, path: str, settings: Mapping[str, Any]) -> ClipImportPlan:
        """What a picked MP4 is and what using it needs (read only; nothing is created or queued)."""

        return self.clip_importer.inspect(path, settings)

    def create_from_clip_file(
        self, path: str, title: str, settings: Mapping[str, Any], **choices: Any
    ) -> StoryboardTree:
        """A storyboard from an MP4: its StableNew job when known, else its decoded frames (``storyboard_import``)."""

        _check_title(title)
        storyboard_id = check_storyboard_id(self._new_id())
        prepared = self.clip_importer.prepare(path, settings, storyboard_id, **choices)
        return self._create(storyboard_id, title, prepared)

    def create_from_clip(self, job_id: str, title: str) -> StoryboardTree:
        _check_title(title)
        storyboard_id = check_storyboard_id(self._new_id())
        prepared = prepare_clip_root(
            repository=self._repo(),
            job_id=job_id,
            storyboard_id=storyboard_id,
            output_root=self._output_root(),
            registry=self._registry,
        )
        return self._create(storyboard_id, title, prepared)

    def create_from_image(
        self, image_path: str, settings: Mapping[str, Any], title: str
    ) -> StoryboardTree:
        _check_title(title)
        prepared = prepare_image_root(
            image_path=image_path, settings=settings, registry=self._registry
        )
        return self._create(check_storyboard_id(self._new_id()), title, prepared)

    def _create(self, storyboard_id: str, title: str, prepared: PreparedRoot) -> StoryboardTree:
        root = TreeRoot.from_dict(
            {
                "kind": prepared.kind,
                "job_id": prepared.job_id or "",
                "image_path": prepared.image_path or "",
                "image_sha256": prepared.image_sha256 or "",
                "manifest_path": "" if prepared.manifest is None else prepared.manifest.path,
                "manifest_sha256": "" if prepared.manifest is None else prepared.manifest.sha256,
                "settings": dict(prepared.settings),
                "fps": prepared.fps,
                "width": prepared.width,
                "height": prepared.height,
                "smoothing_text": "" if prepared.smoothing is None else prepared.smoothing.text(),
                **(prepared.external or {}),
            }
        )
        tree = replace(StoryboardTree.new(title, root), storyboard_id=storyboard_id)
        return self.store.save(tree)

    # ------------------------------------------------------------------------------------------ cuts

    def parent_cut(self, tree: StoryboardTree, take_id: str) -> CutManifest | None:
        """The node's cut: the root manifest, or an attempt manifest's prefix through that take's range.

        A take's cut comes from its newest completed attempt whose manifest covers the take, or else its newest
        attempt whose manifest does; unreadable attempts fall back to older ones (``src/video/storyboard_cuts.py``).
        ``None`` for an image root or a take with no frames yet.
        """

        if take_id == ROOT_PARENT:
            return root_cut(tree.root)
        return take_cut(self._repo(), _find(tree, take_id), [self._output_root()])

    def _lead_in_cut(self, tree: StoryboardTree, request: ContinueRequest) -> CutManifest | None:
        """The parent cut's first K frames (K = handoff_index + 1), or ``None`` for the first takes of an image root."""

        if request.parent_id != ROOT_PARENT:
            _find(tree, request.parent_id)
        cut = self.parent_cut(tree, request.parent_id)
        if request.handoff_index is None:
            if cut is None and request.parent_id == ROOT_PARENT and tree.root.kind == "image":
                return None
            raise StoryboardTreeError("Choose the frame to continue from.")
        if cut is None:
            what = (
                "The storyboard's still image" if request.parent_id == ROOT_PARENT else "This take"
            )
            raise StoryboardTreeError(f"{what} has no frames to continue from yet.")
        index = request.handoff_index
        if isinstance(index, bool) or not 0 <= index < len(cut.frames):
            raise StoryboardTreeError(
                f"Frame {index + 1 if isinstance(index, int) else index} is outside this "
                f"{len(cut.frames)}-frame cut."
            )
        return cut.prefix(index + 1)

    def project(self, tree: StoryboardTree) -> dict[str, TakeView]:
        """Each take's state, progress, files and frame health, read back from the repository (read-only)."""

        return project_storyboard(
            tree,
            self._repo(),
            output_roots=[self._output_root()],
            check_frames=first_missing_frame,
        )

    def needs_experimental_opt_in(self, tree: StoryboardTree) -> bool:
        """True when the inherited workflow is experimental, so a Continue needs the job's own opt-in."""

        try:
            spec = self._njr_builder.spec_for(dict(tree.root.to_dict()["settings"]))
        except (KeyError, ValueError):
            return False
        return getattr(spec, "governance_state", None) == WORKFLOW_GOVERNANCE_EXPERIMENTAL

    def output_root(self) -> str:
        return self._output_root()

    # ------------------------------------------------------------------------------------------ preview

    def preview(self, request: ContinueRequest) -> ContinuePreview:
        """The frozen summary of a Continue; nothing is drawn, written or submitted."""

        rows = _check_rows(request)
        tree = self.store.load(request.storyboard_id)
        cut = self._lead_in_cut(tree, request)
        form = self._form(tree, request)
        spec = self._njr_builder.spec_for(form)
        frames = parse_frame_count(spec, form.get("frame_count"))
        lead_in = 0 if cut is None else len(cut.frames)
        first = frames - (LEAD_IN_OVERLAP if cut is not None else 0)
        if request.mode == "parallel":
            jobs, total = len(rows), lead_in + first
        else:
            later = sum(frames - default_overlap(ANCHOR_CARRY, i) for i in range(1, len(rows)))
            jobs, total = 1, lead_in + first + later
        return ContinuePreview(
            jobs=jobs,
            segments=len(rows),
            lead_in_frames=lead_in,
            total_cut_frames=total,
            fps=int(tree.root.fps),
            workflow_id=str(spec.workflow_id),
            workflow_version=str(spec.workflow_version),
            seeds=tuple(row.seed.strip() or "random" for row in rows),
        )

    # ------------------------------------------------------------------------------------------ submit

    def submit(self, request: ContinueRequest) -> ContinueResult:
        """Admit a Continue through ONE ``submit_njrs`` call; all or none (see the module docstring)."""

        rows = _check_rows(request)
        tree = self.store.load(request.storyboard_id)
        if tree.revision != request.expected_revision:
            raise StoryboardTreeError(
                "Revision conflict: the storyboard changed since it was shown; reopen it. Nothing queued."
            )
        cut = self._lead_in_cut(tree, request)
        batch_id = self._new_id()
        lead_in = (
            None
            if cut is None
            else write_lead_in(self._output_root(), tree.storyboard_id, batch_id, cut)
        )
        seeds = self._draw_seeds(rows)
        takes = self._pending_takes(request, rows, batch_id)
        pending = tree
        for take in takes:
            pending = pending.with_take(take)
        pending = self.store.save(pending)  # CAS and the 2 MB cap, before anything is admitted
        take_ids = tuple(take.take_id for take in takes)
        groups = self._groups(request.mode, rows, seeds, takes)
        njrs: list[Any] = []
        submitted = False
        try:
            for position, (group_rows, group_seeds, group_ids) in enumerate(groups):
                built = self._admit(
                    position,
                    tree=tree,
                    request=request,
                    rows=group_rows,
                    seeds=group_seeds,
                    take_ids=group_ids,
                    lead_in=lead_in,
                )
                njrs.append(built.njr)
            self._job_service().submit_njrs(njrs, SubmissionPolicy())
            submitted = True
        finally:
            if not submitted:
                self._settle_failed(request.storyboard_id, groups, njrs)
        # JobService admits each NJR under its own job id, so the attempts are the NJRs' ids.
        job_ids = tuple(str(njr.job_id) for njr in njrs)
        recorded = pending
        for (_rows, _seeds, group_ids), job_id in zip(groups, job_ids, strict=True):
            for take_id in group_ids:
                recorded = recorded.with_attempt(take_id, job_id)
        # If this write fails the takes stay pending; reconcile() adopts the queued jobs.
        saved = self.store.save(recorded)
        return ContinueResult(job_ids=job_ids, take_ids=take_ids, tree=saved)

    def _admit(
        self,
        position: int,
        *,
        tree: StoryboardTree,
        request: ContinueRequest,
        rows: tuple[ContinueRow, ...],
        seeds: tuple[str, ...],
        take_ids: tuple[str, ...],
        lead_in: StoryboardLeadIn | None,
    ) -> VideoWorkflowBuild:
        """Build job ``position``'s NJR (one per row in parallel, one for a chain); nothing is queued."""

        form = self._form(tree, request)
        frames = parse_frame_count(self._njr_builder.spec_for(form), form.get("frame_count"))
        segments: list[dict[str, Any]] = []
        for row, seed in zip(rows, seeds, strict=True):
            segment: dict[str, Any] = {"frame_count": frames, "prompt": row.prompt, "seed": seed}
            if row.negative_prompt.strip():
                segment["negative_prompt"] = row.negative_prompt
            segments.append(segment)
        form.update({"prompt": rows[0].prompt, "seed": seeds[0]})
        link = StoryboardPlanLink(
            storyboard_id=tree.storyboard_id,
            parent_id=request.parent_id,
            take_ids=take_ids,
            handoff_index=request.handoff_index,
            lead_in=lead_in,
        )
        check_frozen = None
        if lead_in is None:
            source = tree.root.image_path
            check_frozen = _still_unchanged(tree.root)
        else:
            source = lead_in.handoff_path
        return build_sequence_njr(
            njr_builder=self._njr_builder,
            registry=self._registry,
            source_image_path=source,
            form_data=form,
            sequence_intent={"segments": segments},
            storyboard=link,
            exact_source=lead_in is not None,
            check_frozen=check_frozen,
        )

    def _form(self, tree: StoryboardTree, request: ContinueRequest) -> dict[str, Any]:
        """The root's inherited settings; the experimental opt-in only from this request, never from the file."""

        form: dict[str, Any] = dict(tree.root.to_dict()["settings"])
        if request.experimental_opt_in:
            form[EXPERIMENTAL_OPT_IN_FIELD] = True
        return form

    def _draw_seeds(self, rows: tuple[ContinueRow, ...]) -> tuple[str, ...]:
        """Blank or ``random`` rows draw a seed, redrawn until it differs from every other seed in the batch."""

        used = {row.seed.strip() for row in rows if row.seed.strip().lower() not in ("", "random")}
        seeds: list[str] = []
        for row in rows:
            text = row.seed.strip()
            if text.lower() in ("", "random"):
                text = str(self._draw_seed())
                while text in used:
                    text = str(self._draw_seed())
                used.add(text)
            seeds.append(text)
        return tuple(seeds)

    def _pending_takes(
        self, request: ContinueRequest, rows: tuple[ContinueRow, ...], batch_id: str
    ) -> tuple[Take, ...]:
        now = timestamp()
        takes: list[Take] = []
        for position, row in enumerate(rows):
            chained = request.mode == "sequential" and position > 0
            takes.append(
                Take.from_dict(
                    {
                        "take_id": self._new_id(),
                        "parent_id": takes[-1].take_id if chained else request.parent_id,
                        "handoff_index": None if chained else request.handoff_index,
                        "mode": request.mode,
                        "batch_id": batch_id,
                        "chain_position": position if request.mode == "sequential" else 0,
                        "segment_index": position if request.mode == "sequential" else 0,
                        "prompt": row.prompt,
                        "negative_prompt": row.negative_prompt,
                        "seed_intent": row.seed.strip(),
                        "attempts": [],
                        "replay_of": None,
                        "mark": "none",
                        "created_at": now,
                    }
                )
            )
        return tuple(takes)

    @staticmethod
    def _groups(
        mode: Mode,
        rows: tuple[ContinueRow, ...],
        seeds: tuple[str, ...],
        takes: tuple[Take, ...],
    ) -> list[tuple[tuple[ContinueRow, ...], tuple[str, ...], tuple[str, ...]]]:
        """One job per row (parallel) or one job for the whole chain (sequential)."""

        ids = tuple(take.take_id for take in takes)
        if mode == "sequential":
            return [(rows, seeds, ids)]
        return [
            ((row,), (seed,), (take_id,))
            for row, seed, take_id in zip(rows, seeds, ids, strict=True)
        ]

    def _settle_failed(
        self,
        storyboard_id: str,
        groups: list[tuple[tuple[ContinueRow, ...], tuple[str, ...], tuple[str, ...]]],
        njrs: list[Any],
    ) -> None:
        """After admission or submission raised: keep the takes whose jobs the repository holds (recording their
        attempts) and remove the rest with their descendants. Best effort; the caller re-raises the original error.

        ``submit_njrs`` persists the batch before its announcements, so an error raised after persisting still leaves
        queued jobs that will run; their takes must survive.
        """

        repository = self._repository()
        accepted = {
            position: str(njr.job_id)
            for position, njr in enumerate(njrs)
            if read_job(repository, str(njr.job_id)) is not None
        }
        with suppress(StoryboardTreeError, OSError):
            current = self.store.load(storyboard_id)
            present = {take.take_id for take in current.takes}
            gone: set[str] = set()
            for position, (_rows, _seeds, group_ids) in enumerate(groups):
                for take_id in (i for i in group_ids if i in present):
                    if position in accepted:
                        current = current.with_attempt(take_id, accepted[position])
                    else:
                        gone.add(take_id)
            for take in current.takes:  # creation order: a parent is seen before its children
                if take.parent_id in gone:
                    gone.add(take.take_id)
            if gone or accepted:
                self.store.save(current.without_takes(gone))

    # ------------------------------------------------------------------------------------------ reconcile

    def reconcile(self, storyboard_id: str) -> StoryboardTree:
        """Adopt repository jobs that name this storyboard but are in no take's attempts; save once if any changed.

        Reads the newest ``RECONCILE_WINDOW`` jobs. A job of pending takes becomes their first attempt; a resume joins
        the takes it resumed; a replay becomes new sibling takes (``src/video/storyboard_reconcile.py``).
        """

        tree = self.store.load(storyboard_id)
        known = {job_id for take in tree.takes for job_id in take.attempts}
        repository = self._repo()
        entries = list(repository.list_recent_jobs(limit=RECONCILE_WINDOW) or ())
        changed = False
        for entry in reversed(entries):  # oldest first, so a resume of a replay finds its take
            job_id = str(getattr(entry, "job_id", "") or "")
            if not job_id or job_id in known:
                continue
            njr = getattr(read_job(repository, job_id), "_normalized_record", None)
            if njr is None:
                continue
            try:
                adopted = adopt_job(tree, job_id, njr, new_id=self._new_id)
            except ValueError as exc:  # a malformed plan or link: skip this job, keep reconciling
                logger.warning("storyboard: job %s cannot be adopted: %s", job_id, exc)
                continue
            if adopted is not tree:
                tree, changed = adopted, True
                known.add(job_id)
        return self.store.save(tree) if changed else tree

    # ------------------------------------------------------------------------------------------ helpers

    def _repo(self) -> Any:
        repository = self._repository()
        if repository is None or not callable(getattr(repository, "get_job_model", None)):
            raise RuntimeError(
                "The job repository is not available; the storyboard cannot read its jobs."
            )
        return repository


def _check_title(title: str) -> None:
    if not isinstance(title, str) or not title.strip():
        raise StoryboardTreeError("A storyboard needs a title.")


def _check_rows(request: ContinueRequest) -> tuple[ContinueRow, ...]:
    rows = tuple(request.rows)
    if not 1 <= len(rows) <= MAX_ROWS:
        raise StoryboardTreeError(f"A Continue has 1 to {MAX_ROWS} rows, not {len(rows)}.")
    if request.mode not in ("parallel", "sequential"):
        raise StoryboardTreeError("A Continue is parallel or sequential.")
    for number, row in enumerate(rows, start=1):
        if not row.prompt.strip():
            raise StoryboardTreeError(f"Row {number} needs a positive prompt.")
        try:
            parse_seed_input(row.seed)
        except ValueError as exc:
            raise StoryboardTreeError(f"Row {number}: {exc}") from exc
    return rows


def _find(tree: StoryboardTree, take_id: str) -> Take:
    for take in tree.takes:
        if take.take_id == take_id:
            return take
    raise StoryboardTreeError(f"Unknown take {take_id!r}.")


def _still_unchanged(root: TreeRoot) -> Callable[[FrozenVideoInputs], None]:
    def check(frozen: FrozenVideoInputs) -> None:
        if root.image_sha256 and frozen.source_sha256 != root.image_sha256:
            raise SequencePlanError(
                f"the storyboard's still image changed since the storyboard was made: {root.image_path}"
            )

    return check


__all__ = [
    "RECONCILE_WINDOW",
    "ContinuePreview",
    "ContinueRequest",
    "ContinueResult",
    "ContinueRow",
    "StoryboardSubmissionService",
]


def build_storyboard_service(controller: Any) -> StoryboardSubmissionService:
    """Wire the service from a ``VideoWorkflowController`` (kept out of that file, which has a size ceiling)."""

    return StoryboardSubmissionService(
        njr_builder=controller._njr_builder,
        workflow_registry=controller._workflow_registry,
        job_service=controller._job_service,
        repository=lambda: getattr(controller._job_service(), "history_store", None),
        output_root=lambda: getattr(controller._app_controller, "output_dir", None) or "output",
    )
