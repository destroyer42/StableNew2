"""Toolkit-neutral state of the Video Workflow "Motion Library" browser (PR-VID-MOTION-LIB-353).

The session lists, filters, previews and annotates cataloged motion-reference clips and hands a verified
one to the Video Workflow form.  It imports no Tk and starts no process of its own:

* every disk, hash and FFmpeg call is an injected port the injected ``BackgroundWorkRunner`` runs on a
  worker; results return on the UI thread and are dropped when a newer request superseded them or the
  panel closed (a per-kind token), and a superseded preview is cancelled through its own event;
* filtering is local and pure (``search_assets``): typing never reads a file;
* nothing here builds a job, submits, queues or edits the Video Workflow form -- ``use_as_driving``
  verifies on a worker and then calls ``on_handoff`` with a plan the tab applies to its own fields.

Content visibility: rows the active mode hides are not listed (their count is shown) and prompt text is
redacted through the shared ``ContentVisibilityResolver``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.view_contracts.video_motion_readiness_contract import FrameThumb
from src.video.driving_video_inspection import DrivingVideoInspection
from src.video.motion_library.derivation import derivation_lines
from src.video.motion_library.handoff import HandoffPlan
from src.video.motion_library.importer import FolderImportReport, ImportOutcome
from src.video.motion_library.models import (
    SOURCE_CATEGORY_LABELS,
    MotionAsset,
)
from src.video.motion_library.relink import RelinkOutcome
from src.video.motion_library.search import SearchQuery, known_tags, search_assets
from src.video.motion_library.snapshot import LibrarySnapshot
from src.video.motion_library.verification import (
    FILE_CHANGED,
    FILE_MISSING,
    FILE_OK,
    FILE_UNREADABLE,
    FILE_UNVERIFIED,
)

NOT_CONFIGURED_TEXT = (
    "No Motion Library yet. Choose a folder outside the repository to keep your motion references."
)
EMPTY_TEXT = "The library is empty. Import a video or a folder of videos to begin."
_FILE_LABELS = {
    FILE_OK: "verified",
    FILE_UNVERIFIED: "",
    FILE_MISSING: "MISSING",
    FILE_CHANGED: "CHANGED",
    FILE_UNREADABLE: "UNREADABLE",
}
_MAX_LISTED_FAILURES = 5


@dataclass(frozen=True)
class MotionLibraryPorts:
    """The controller calls the session needs (all worker-safe)."""

    snapshot: Callable[[], LibrarySnapshot]
    inspect: Callable[[str, threading.Event], DrivingVideoInspection]
    import_file: Callable[[str, str, Mapping[str, Any], threading.Event], ImportOutcome]
    import_folder: Callable[[str, str, Mapping[str, Any], threading.Event], FolderImportReport]
    annotate: Callable[[str, Mapping[str, Any]], MotionAsset]
    relink: Callable[[str, str, threading.Event], RelinkOutcome]
    configure: Callable[[str], Any]
    plan_handoff: Callable[[str, str, str, threading.Event], HandoffPlan]


@dataclass(frozen=True)
class LibraryRow:
    asset_id: str
    name: str
    tags_text: str
    source_label: str
    length_text: str
    review_label: str
    file_label: str
    thumbnail_path: str


@dataclass(frozen=True)
class LibraryDetail:
    asset: MotionAsset
    title: str
    fact_lines: tuple[str, ...]
    provenance_lines: tuple[str, ...]
    origin_lines: tuple[str, ...]
    file_state: str
    file_message: str
    frames: tuple[FrameThumb, ...]
    preview_issues: tuple[str, ...]
    preview_loading: bool
    media_path: str
    can_use: bool
    can_relink: bool


@dataclass(frozen=True)
class LibraryView:
    configured: bool
    root: str
    suggested_root: str
    status: str
    busy: bool
    rows: tuple[LibraryRow, ...]
    total: int
    hidden_by_visibility: int
    detail: LibraryDetail | None
    known_tags: tuple[str, ...]
    issues: tuple[str, ...]
    selected_id: str
    can_import: bool


def _length_text(asset: MotionAsset) -> str:
    seconds = f"{asset.duration_seconds:.1f} s" if asset.duration_seconds else "? s"
    frames = f"{asset.frame_count} f" if asset.frame_count else "? f"
    return f"{seconds} / {frames}"


def visibility_subject(asset: MotionAsset) -> dict[str, Any]:
    """What the visibility policy classifies: the clip's name, tags, notes and (protected) prompts."""

    origin = asset.origin
    return {
        "name": asset.display_name,
        "description": " ".join(
            filter(None, (asset.quality_notes, asset.provenance_notes, asset.source_reference))
        ),
        "tags": list(asset.tags),
        "prompt": origin.prompt if origin is not None else "",
        "negative_prompt": origin.negative_prompt if origin is not None else "",
    }


class MotionLibrarySession:
    def __init__(
        self,
        *,
        ports: MotionLibraryPorts,
        runner: BackgroundWorkRunner,
        mode_provider: Callable[[], str] = lambda: "nsfw",
        selected_workflow: Callable[[], tuple[str, str]] = lambda: ("", ""),
        on_change: Callable[[], None] | None = None,
        on_handoff: Callable[[HandoffPlan], None] | None = None,
    ) -> None:
        self._ports = ports
        self._runner = runner
        self._mode = mode_provider
        self._workflow = selected_workflow
        self._on_change = on_change
        self._on_handoff = on_handoff
        self._closed = False
        self._tokens: dict[str, int] = {}
        self._cancels: dict[str, threading.Event] = {}
        self.snapshot: LibrarySnapshot | None = None
        self.query = SearchQuery()
        self.selected_id = ""
        self.status = NOT_CONFIGURED_TEXT
        # The last operator-command result; an automatic refresh after the command keeps showing it.
        self._notice = ""
        self.busy = False
        self._inspection: DrivingVideoInspection | None = None
        self._inspection_for = ""
        self._inspecting = False
        self.last_plan: HandoffPlan | None = None
        self._select_after_refresh = ""

    # ------------------------------------------------------------------ plumbing

    def _next(self, kind: str) -> int:
        self._tokens[kind] = self._tokens.get(kind, 0) + 1
        previous = self._cancels.pop(kind, None)
        if previous is not None:
            previous.set()  # a superseded worker stops at its next bounded step
        self._cancels[kind] = threading.Event()
        return self._tokens[kind]

    def _live(self, kind: str, token: int) -> bool:
        return not self._closed and self._tokens.get(kind) == token

    def _say(self, text: str) -> None:
        self._notice = text
        self.status = text

    def _notify(self) -> None:
        callback = self._on_change
        if callback is not None and not self._closed:
            callback()

    def _run(
        self,
        kind: str,
        work: Callable[[threading.Event], Any],
        finish: Callable[[Any], None],
        *,
        busy_text: str = "",
    ) -> None:
        token = self._next(kind)
        cancel = self._cancels[kind]
        if busy_text:
            self.busy = True
            self.status = busy_text
            self._notify()

        def done(outcome: WorkOutcome) -> None:
            if not self._live(kind, token):
                return
            if busy_text:
                self.busy = False
            if outcome.error:
                self._say(f"{kind.replace('-', ' ').capitalize()} failed: {outcome.error}")
                self._notify()
                return
            finish(outcome.value)

        self._runner.start(f"motion-library-{kind}", lambda: WorkOutcome(value=work(cancel)), done)

    # ------------------------------------------------------------------ commands (UI thread)

    def refresh(self, *, keep_notice: bool = False) -> None:
        if not keep_notice:
            self._notice = ""
        self._run("refresh", lambda _c: self._ports.snapshot(), self._finish_refresh)

    def refresh_and_select(self, asset_id: str) -> None:
        """Refresh the catalog, then select ``asset_id`` once it is listed (a clip added by another dialog)."""

        self._select_after_refresh = str(asset_id or "")
        self.refresh(keep_notice=True)

    def _finish_refresh(self, snapshot: LibrarySnapshot) -> None:
        self.snapshot = snapshot
        if snapshot.error:
            summary = snapshot.error
        elif not snapshot.configured:
            summary = NOT_CONFIGURED_TEXT
        elif not snapshot.assets:
            summary = EMPTY_TEXT
        else:
            summary = f"{len(snapshot.assets)} clip(s) in the library."
        self.status = summary if snapshot.error else (self._notice or summary)
        if self.selected_id and not any(a.asset_id == self.selected_id for a in snapshot.assets):
            self.selected_id = ""
            self._inspection = None
        pending, self._select_after_refresh = self._select_after_refresh, ""
        if pending and any(a.asset_id == pending for a in snapshot.assets):
            self.select(pending)
        self._notify()

    def set_query(self, query: SearchQuery) -> None:
        self.query = query
        self._notify()

    def select(self, asset_id: str) -> None:
        asset_id = str(asset_id or "")
        if asset_id == self.selected_id:
            return
        self.selected_id = asset_id
        self._inspection = None
        self._inspection_for = ""
        self.last_plan = None
        self._tokens["inspect"] = self._tokens.get("inspect", 0) + 1  # drop an in-flight preview
        previous = self._cancels.pop("inspect", None)
        if previous is not None:
            previous.set()
        if asset_id and self._asset(asset_id) is not None:
            self._inspecting = True
            self._run(
                "inspect",
                lambda cancel: (asset_id, self._ports.inspect(asset_id, cancel)),
                self._finish_inspect,
            )
        else:
            self._inspecting = False
        self._notify()

    def _finish_inspect(self, value: tuple[str, DrivingVideoInspection]) -> None:
        asset_id, inspection = value
        self._inspecting = False
        if asset_id == self.selected_id:
            self._inspection, self._inspection_for = inspection, asset_id
        self._notify()

    def configure_root(self, root: str) -> None:
        def finished(_value: Any) -> None:
            self._say("Motion Library folder set.")
            self.refresh(keep_notice=True)

        self._run(
            "configure",
            lambda _c: self._ports.configure(root),
            finished,
            busy_text="Opening library...",
        )

    def import_file(self, path: str, mode: str, annotations: Mapping[str, Any]) -> None:
        def finished(outcome: ImportOutcome) -> None:
            if outcome.status == "imported":
                self._say(f"Imported {outcome.path}.")
            elif outcome.status == "duplicate":
                self._say(outcome.reason or "Already in the library.")
            else:
                self._say(f"Not imported: {outcome.reason}")
            if outcome.asset_id:
                self.selected_id = ""
                self.select(outcome.asset_id)
            self.refresh(keep_notice=True)

        self._run(
            "import",
            lambda cancel: self._ports.import_file(path, mode, annotations, cancel),
            finished,
            busy_text="Importing video...",
        )

    def import_folder(self, folder: str, mode: str, annotations: Mapping[str, Any]) -> None:
        def finished(report: FolderImportReport) -> None:
            failures = [o for o in report.outcomes if o.status == "failed"]
            lines = [report.summary()]
            lines.extend(f"{o.path}: {o.reason}" for o in failures[:_MAX_LISTED_FAILURES])
            if len(failures) > _MAX_LISTED_FAILURES:
                lines.append(f"...and {len(failures) - _MAX_LISTED_FAILURES} more failure(s).")
            self._say("\n".join(lines))
            self.refresh(keep_notice=True)

        self._run(
            "import",
            lambda cancel: self._ports.import_folder(folder, mode, annotations, cancel),
            finished,
            busy_text="Importing folder...",
        )

    def annotate(self, asset_id: str, changes: Mapping[str, Any]) -> None:
        def finished(asset: MotionAsset) -> None:
            self._say(f"Saved '{asset.display_name}'.")
            self.refresh(keep_notice=True)

        self._run("annotate", lambda _c: self._ports.annotate(asset_id, dict(changes)), finished)

    def relink(self, asset_id: str, path: str) -> None:
        def finished(outcome: RelinkOutcome) -> None:
            self._say("File relinked." if outcome.ok else f"Not relinked: {outcome.reason}")
            self.refresh(keep_notice=True)

        self._run(
            "relink",
            lambda cancel: self._ports.relink(asset_id, path, cancel),
            finished,
            busy_text="Verifying file...",
        )

    def use_as_driving(self) -> None:
        """Verify the selected clip against the selected workflow, then offer the plan to the tab."""

        asset = self._asset(self.selected_id)
        if asset is None:
            self._say("Select a clip first.")
            self._notify()
            return
        workflow_id, workflow_version = self._workflow()
        asset_id = asset.asset_id

        def finished(plan: HandoffPlan) -> None:
            self.last_plan = plan
            if not plan.ok:
                action = f" {plan.corrective_action}" if plan.corrective_action else ""
                self._say(f"{plan.refusal}{action}")
            elif asset_id != self.selected_id or self._workflow() != (
                workflow_id,
                workflow_version,
            ):
                self._say(
                    "The selection or workflow changed while the clip was being verified; "
                    "nothing was applied. Choose Use as Driving Video again."
                )
            else:
                handler = self._on_handoff
                if handler is not None:
                    handler(plan)
                self._say(f"'{asset.display_name}' is now the driving video.")
            self._notify()

        self._run(
            "handoff",
            lambda cancel: self._ports.plan_handoff(
                asset_id, workflow_id, workflow_version, cancel
            ),
            finished,
            busy_text="Verifying clip...",
        )

    def cancel_work(self) -> None:
        for event in self._cancels.values():
            event.set()

    def close(self) -> None:
        self._closed = True
        self.cancel_work()
        self._on_change = None
        self._on_handoff = None

    # ------------------------------------------------------------------ view

    def _asset(self, asset_id: str) -> MotionAsset | None:
        if self.snapshot is None:
            return None
        return next((a for a in self.snapshot.assets if a.asset_id == asset_id), None)

    def view(self) -> LibraryView:
        snapshot = self.snapshot
        if snapshot is None:
            return LibraryView(
                configured=False, root="", suggested_root="", status=self.status, busy=self.busy,
                rows=(), total=0, hidden_by_visibility=0, detail=None, known_tags=(), issues=(),
                selected_id="", can_import=False,
            )  # fmt: skip
        resolver = ContentVisibilityResolver(self._mode())
        matching = search_assets(snapshot.assets, self.query)
        visible = [a for a in matching if resolver.is_visible(visibility_subject(a))]
        rows = tuple(
            LibraryRow(
                asset_id=a.asset_id,
                name=a.display_name,
                tags_text=", ".join(a.tags[:6]),
                source_label=SOURCE_CATEGORY_LABELS.get(a.source_category, a.source_category),
                length_text=_length_text(a),
                review_label=a.review_status.capitalize(),
                file_label=_FILE_LABELS.get(
                    snapshot.checks[a.asset_id].state
                    if a.asset_id in snapshot.checks
                    else FILE_UNREADABLE,
                    "",
                ),
                thumbnail_path=snapshot.thumbnails.get(a.asset_id, ""),
            )
            for a in visible
        )
        selected = self._asset(self.selected_id)
        if selected is not None and not resolver.is_visible(visibility_subject(selected)):
            selected = None
        return LibraryView(
            configured=snapshot.configured and not snapshot.error,
            root=snapshot.root,
            suggested_root=snapshot.suggested_root,
            status=self.status,
            busy=self.busy,
            rows=rows,
            total=len(snapshot.assets),
            hidden_by_visibility=len(matching) - len(visible),
            detail=self._detail(selected, resolver) if selected is not None else None,
            known_tags=known_tags(snapshot.assets),
            issues=snapshot.issues,
            selected_id=selected.asset_id if selected is not None else "",
            can_import=snapshot.configured and not snapshot.error and not self.busy,
        )

    def _detail(self, asset: MotionAsset, resolver: ContentVisibilityResolver) -> LibraryDetail:
        snapshot = self.snapshot
        assert snapshot is not None
        check = snapshot.checks.get(asset.asset_id)
        state = check.state if check is not None else FILE_UNREADABLE
        facts = [
            f"Dimensions: {asset.width or '?'} x {asset.height or '?'}",
            f"Frame rate: {asset.fps:g} fps" if asset.fps else "Frame rate: not reported",
            f"Frames: {asset.frame_count if asset.frame_count else 'not reported'}",
            f"Duration: {asset.duration_seconds:.2f} s"
            if asset.duration_seconds
            else "Duration: not reported",
            f"SHA-256: {asset.sha256}",
            f"Review: {asset.review_status}"
            + (", marked good for motion driving" if asset.good_for_motion else ""),
            f"Loop: {asset.loop_suitability.replace('_', ' ')}",
        ]
        provenance = [
            f"Source: {SOURCE_CATEGORY_LABELS.get(asset.source_category, asset.source_category)}",
            f"Source reference: {asset.source_reference or '-'}",
            f"Location: {asset.locator.mode} -> {asset.locator.path}",
            f"Imported: {asset.imported_at or '-'}",
        ]
        if asset.source_url:
            provenance.append(f"Source URL: {asset.source_url}")
        if asset.usage_terms:
            provenance.append(f"Usage terms: {asset.usage_terms}")
        if asset.provenance_notes:
            provenance.append(f"Provenance notes: {asset.provenance_notes}")
        if asset.quality_notes:
            provenance.append(f"Quality notes: {asset.quality_notes}")
        provenance.extend(f"Also seen at: {alias.path}" for alias in asset.aliases)
        origin_lines: list[str] = []
        if asset.derivation is not None:
            origin_lines.extend(
                derivation_lines(
                    asset.derivation, source_present=snapshot.derivation_sources.get(asset.asset_id)
                )
            )
        if asset.origin is not None:
            o = asset.origin
            subject = visibility_subject(asset)
            origin_lines = [
                f"Generated by job {o.job_id} ({o.workflow_id or 'workflow unknown'} {o.workflow_version}".rstrip()
                + ")",
                f"Seed: {o.seed if o.seed is not None else 'not recorded'}",
                f"Requested motion achieved: "
                f"{'yes' if o.motion_achieved else 'no' if o.motion_achieved is False else 'not judged'}",
            ]
            if o.motion_label:
                origin_lines.append(f"Motion label: {o.motion_label}")
            if o.prompt:
                origin_lines.append(f"Prompt: {resolver.redact_text(o.prompt, item=subject)}")
            if o.known_artifacts:
                origin_lines.append(f"Known artifacts: {o.known_artifacts}")
            if o.reuse_conditions:
                origin_lines.append(f"Reuse conditions: {o.reuse_conditions}")
        frames: tuple[FrameThumb, ...] = ()
        issues: tuple[str, ...] = ()
        if self._inspection is not None and self._inspection_for == asset.asset_id:
            labels = ("Start", "Middle", "End")
            frames = tuple(
                FrameThumb(
                    frame.png_bytes,
                    f"{labels[i] if i < len(labels) else 'Frame'} ({frame.position_seconds:g} s)",
                )
                for i, frame in enumerate(self._inspection.frames)
            )
            issues = tuple(issue.message for issue in self._inspection.issues)
        usable_path = state in {FILE_OK, FILE_UNVERIFIED}
        return LibraryDetail(
            asset=asset,
            title=asset.display_name,
            fact_lines=tuple(facts),
            provenance_lines=tuple(provenance),
            origin_lines=tuple(origin_lines),
            file_state=state,
            file_message=check.message if check is not None else "",
            frames=frames,
            preview_issues=issues,
            preview_loading=self._inspecting,
            media_path=snapshot.media_paths.get(asset.asset_id, "") if usable_path else "",
            can_use=usable_path and not self.busy,
            can_relink=state in {FILE_MISSING, FILE_CHANGED, FILE_UNREADABLE},
        )


__all__ = [
    "visibility_subject",
    "EMPTY_TEXT",
    "NOT_CONFIGURED_TEXT",
    "LibraryDetail",
    "LibraryRow",
    "LibraryView",
    "MotionLibraryPorts",
    "MotionLibrarySession",
]
