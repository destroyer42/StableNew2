"""Motion Library support on the Video Workflow controller (PR-VID-MOTION-LIB-353).

A mixin so ``VideoWorkflowController`` keeps one surface for the Video Workflow tab.  Every call here is a
local catalog operation: nothing queues work, builds a job, starts a runtime or reaches the network.  The
heavy ones (hashing, FFprobe, FFmpeg frame decode) are meant to be called from a worker the view owns.

The library is a catalog of reference media, not a second job store: the canonical History repository is
only *read* (``add_job_to_motion_library``) and the Video Workflow job is still built, previewed and
submitted through the existing controller methods.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.video.driving_video_inspection import DrivingVideoInspection, inspect_driving_video
from src.video.motion_library.config import (
    load_library_root,
    save_library_root,
    suggested_library_root,
)
from src.video.motion_library.handoff import HandoffPlan, plan_driving_handoff
from src.video.motion_library.importer import (
    FolderImportReport,
    ImportOutcome,
    import_folder,
    import_history_video,
    import_video,
)
from src.video.motion_library.models import LOCATOR_LINKED, MotionAsset
from src.video.motion_library.relink import RelinkOutcome, relink_asset
from src.video.motion_library.snapshot import LibrarySnapshot, build_snapshot
from src.video.motion_library.store import LibraryError, MotionLibraryStore
from src.video.motion_library.verification import FileCheck, quick_check


class VideoMotionLibraryControllerMixin:
    """Requires ``list_workflow_specs`` and ``_job_service`` on the host controller."""

    # ------------------------------------------------------------------ opening

    def _motion_library_slot(self) -> dict[str, Any]:
        slot = self.__dict__.get("_motion_library_state")
        if slot is None:
            slot = {"lock": threading.Lock(), "store": None, "root": ""}
            self.__dict__["_motion_library_state"] = slot
        return slot

    def motion_library_configured_root(self) -> str:
        return load_library_root()

    def motion_library_suggested_root(self) -> str:
        return str(suggested_library_root())

    def configure_motion_library(self, root: str | Path) -> MotionLibraryStore:
        """Remember an explicit library folder (outside Git) and open it."""

        resolved = save_library_root(root)
        return self._open_motion_library(str(resolved))

    def motion_library(self) -> MotionLibraryStore:
        """The open store for the configured folder; raises ``LibraryError`` when none is configured."""

        root = load_library_root()
        if not root:
            raise LibraryError("No Motion Library folder is configured. Choose one first.")
        return self._open_motion_library(root)

    def _open_motion_library(self, root: str) -> MotionLibraryStore:
        slot = self._motion_library_slot()
        with slot["lock"]:
            if slot["store"] is not None and slot["root"] == root:
                return slot["store"]  # type: ignore[no-any-return]
            store = MotionLibraryStore(root)
            slot["store"], slot["root"] = store, root
            return store

    def motion_library_snapshot(self) -> LibrarySnapshot:
        """What the browser shows (one ``stat`` per asset).  A missing folder or an unopenable library is
        reported inside the snapshot, never raised, so the panel can explain it."""

        root = load_library_root()
        suggested = str(suggested_library_root())
        if not root:
            return LibrarySnapshot(configured=False, suggested_root=suggested)
        try:
            store = self._open_motion_library(root)
            store.reload()
        except (LibraryError, OSError) as exc:
            return LibrarySnapshot(
                configured=True, root=root, suggested_root=suggested, error=str(exc)
            )
        return replace(build_snapshot(store), suggested_root=suggested)

    # ------------------------------------------------------------------ import

    def import_motion_video(
        self,
        path: str | Path,
        *,
        mode: str = LOCATOR_LINKED,
        annotations: Mapping[str, Any] | None = None,
        cancel: threading.Event | None = None,
    ) -> ImportOutcome:
        return import_video(
            self.motion_library(),
            path,
            mode=mode,
            annotations=annotations,
            inspect=lambda p, c: inspect_driving_video(p, cancel=c),
            cancel=cancel,
        )

    def import_motion_folder(
        self,
        folder: str | Path,
        *,
        mode: str = LOCATOR_LINKED,
        annotations: Mapping[str, Any] | None = None,
        cancel: threading.Event | None = None,
    ) -> FolderImportReport:
        return import_folder(
            self.motion_library(),
            folder,
            mode=mode,
            annotations=annotations,
            inspect=lambda p, c: inspect_driving_video(p, cancel=c),
            cancel=cancel,
        )

    def add_job_to_motion_library(
        self,
        job_id: str,
        *,
        mode: str = LOCATOR_LINKED,
        motion_label: str = "",
        motion_achieved: bool | None = None,
        good_for_motion: bool | None = None,
        known_artifacts: str = "",
        reuse_conditions: str = "",
        annotations: Mapping[str, Any] | None = None,
        cancel: threading.Event | None = None,
    ) -> ImportOutcome:
        """Keep one completed job's recorded video as a motion reference.  The job is re-read from the
        canonical repository; nothing is replayed, copied into History or queued."""

        store = self.motion_library()
        repository: Any = getattr(self._job_service(), "history_store", None)  # type: ignore[attr-defined]
        reader = getattr(repository, "get_job", None)
        entry = reader(str(job_id)) if callable(reader) else None
        return import_history_video(
            store,
            entry,
            mode=mode,
            annotations=annotations,
            motion_label=motion_label,
            motion_achieved=motion_achieved,
            good_for_motion=good_for_motion,
            known_artifacts=known_artifacts,
            reuse_conditions=reuse_conditions,
            inspect=lambda p, c: inspect_driving_video(p, cancel=c),
            cancel=cancel,
        )

    # ------------------------------------------------------------------ catalog edits

    def annotate_motion_asset(self, asset_id: str, changes: Mapping[str, Any]) -> MotionAsset:
        return self.motion_library().annotate(asset_id, changes)

    def annotate_motion_origin(self, asset_id: str, changes: Mapping[str, Any]) -> MotionAsset:
        return self.motion_library().update_origin(asset_id, changes)

    def relink_motion_asset(
        self, asset_id: str, new_path: str | Path, cancel: threading.Event | None = None
    ) -> RelinkOutcome:
        return relink_asset(self.motion_library(), asset_id, new_path, cancel=cancel)

    # ------------------------------------------------------------------ read-only inspection

    def motion_asset_quick_check(self, asset_id: str) -> FileCheck:
        """One ``stat``: present / size changed / timestamp moved.  Never hashes."""

        store = self.motion_library()
        asset = store.require(asset_id)
        try:
            return quick_check(asset, store.asset_path(asset))
        except LibraryError as exc:
            return FileCheck("unreadable", str(exc))

    def inspect_motion_asset(
        self, asset_id: str, cancel: threading.Event | None = None
    ) -> DrivingVideoInspection:
        """Bounded facts plus start/middle/end preview frames of the cataloged file (read-only)."""

        store = self.motion_library()
        asset = store.require(asset_id)
        return inspect_driving_video(store.asset_path(asset), cancel=cancel)

    # ------------------------------------------------------------------ handoff

    def plan_motion_library_handoff(
        self,
        asset_id: str,
        workflow_id: str,
        workflow_version: str = "",
        cancel: threading.Event | None = None,
    ) -> HandoffPlan:
        """Verify the clip and check the selected workflow's declared driving-video contract.

        Only describes; the tab fills its own form and the operator still previews and submits."""

        meta: Mapping[str, Any] | None = None
        for spec in self.list_workflow_specs():  # type: ignore[attr-defined]
            if spec.get("workflow_id") == workflow_id and (
                not workflow_version or spec.get("workflow_version") == workflow_version
            ):
                meta = spec
                break
        return plan_driving_handoff(self.motion_library(), asset_id, meta, cancel=cancel)


__all__ = ["VideoMotionLibraryControllerMixin"]
