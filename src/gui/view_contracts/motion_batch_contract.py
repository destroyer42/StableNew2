"""Toolkit-neutral state of the "Batch Convert Motion" dialog (PR-VID-MOTION-356).

Walks the operator through: choose a folder -> read the dry-run inventory -> confirm the file count, destination and disk
budget -> convert a representative sample -> review -> convert the rest.  It imports no Tk and starts no process: scanning and
converting are injected ports run on the injected ``BackgroundWorkRunner``.  Progress is published by the worker into plain
fields and *read* by the dialog's timer, so no widget is touched from a worker thread.  Nothing here builds a job, queues, uses a
GPU or edits the Video Workflow form; converted clips land in the existing Motion Library.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.video.motion_conversion import batch as bt
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.blender import BlenderInstall
from src.video.motion_conversion.ports import BatchPorts

IDLE_STATUS = "Choose Blender (in Convert Motion) and a folder of FBX or BVH files."
_MIB = 1024 * 1024


@dataclass
class BatchOptions:
    profile_policy: str = bt.POLICY_AUTO
    camera: str = cp.CAMERA_FRONT
    camera_mode: str = cp.CAMERA_STATIC
    root_motion: str = cp.ROOT_PRESERVE
    start_seconds: str = "0"
    frames: str = ""
    orientation: str = "portrait"

    def size(self) -> tuple[int, int]:
        return (
            (cp.DEFAULT_HEIGHT, cp.DEFAULT_WIDTH)
            if self.orientation == "landscape"
            else (cp.DEFAULT_WIDTH, cp.DEFAULT_HEIGHT)
        )


@dataclass(frozen=True)
class BatchView:
    busy: bool
    status: str
    folder: str
    blender_text: str
    inventory_lines: tuple[str, ...]
    estimate_lines: tuple[str, ...]
    confirm_text: str
    confirmed: bool
    stale: bool
    progress_text: str
    result_lines: tuple[str, ...]
    legal_frames: tuple[int, ...]
    can_choose_folder: bool
    can_confirm: bool
    can_sample: bool
    can_remaining: bool
    remaining_label: str = "Convert remaining"
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _mib(count: int) -> str:
    return f"{count / _MIB:.1f} MiB" if count < 1024 * _MIB else f"{count / (1024 * _MIB):.2f} GiB"


class MotionBatchSession:
    def __init__(
        self,
        *,
        ports: BatchPorts,
        runner: BackgroundWorkRunner,
        on_change: Callable[[], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self._ports = ports
        self._runner = runner
        self._on_change = on_change
        self._on_finished = on_finished
        self._closed = False
        self._token = 0
        self._cancel = threading.Event()
        self.options = BatchOptions()
        self.install: BlenderInstall | None = None
        self.folder = ""
        self.inventory: bt.BatchInventory | None = None
        self._scanned_with: bt.BatchSettings | None = None
        self.confirmed = False
        self.summary: bt.BatchSummary | None = None
        self._attempted_ok: set[str] = set()
        self.busy = False
        self.status = IDLE_STATUS
        #: Written by the worker, read by the dialog's timer (plain attribute stores).
        self._progress: bt.BatchProgress | None = None

    # ------------------------------------------------------------------ plumbing

    def _notify(self) -> None:
        if self._on_change is not None and not self._closed:
            self._on_change()

    def _start(
        self, work: Callable[[threading.Event], Any], finish: Callable[[Any], None], text: str
    ) -> None:
        self._token += 1
        token = self._token
        self._cancel.set()  # supersede whatever ran before (a stale scan must never land on a newer folder)
        cancel = self._cancel = threading.Event()
        self.busy, self.status, self._progress = True, text, None
        self._notify()

        def done(outcome: WorkOutcome) -> None:
            if self._closed or token != self._token:
                return
            self.busy = False
            if outcome.error:
                self.status = f"{text.rstrip('.')} failed: {outcome.error}"
                self._notify()
                return
            finish(outcome.value)

        self._runner.start("motion-batch", lambda: WorkOutcome(value=work(cancel)), done)

    def cancel_work(self) -> None:
        self._cancel.set()

    def close(self) -> None:
        self._closed = True
        self._cancel.set()
        self._on_change = None
        self._on_finished = None

    def progress(self, progress: bt.BatchProgress) -> None:
        """Called from the worker thread: only stores; the dialog reads it on its own timer."""

        self._progress = progress

    # ------------------------------------------------------------------ steps

    def load_remembered_blender(self) -> None:
        def finished(install: BlenderInstall | None) -> None:
            self.install = install
            self.status = (
                "Blender is ready. Choose a folder of FBX or BVH files."
                if install
                else "No Blender is registered. Use Convert Motion... to choose one first."
            )
            self._notify()

        self._start(lambda c: self._ports.remembered_blender(c), finished, "Checking Blender...")

    def settings(self) -> bt.BatchSettings:
        workflow = self._ports.workflow()
        options = self.options
        try:
            frames = int(options.frames) if options.frames.strip() else workflow.default_frames
        except ValueError:
            frames = workflow.default_frames
        width, height = options.size()
        return bt.BatchSettings(
            profile_policy=options.profile_policy,
            camera=options.camera,
            camera_mode=options.camera_mode,
            root_motion=options.root_motion,
            start_seconds=options.start_seconds.strip() or "0",
            frames=frames,
            width=width,
            height=height,
            legal_frames=workflow.legal_frames,
            workflow_spec=workflow.spec,
        )

    def choose_folder(self, folder: str) -> None:
        self.folder = folder
        self.scan()

    def scan(self) -> None:
        if not self.folder:
            self.status = "Choose a folder first."
            self._notify()
            return
        settings, folder = self.settings(), self.folder

        def finished(inventory: bt.BatchInventory) -> None:
            self.inventory, self._scanned_with = inventory, settings
            self.confirmed, self.summary = False, None
            self._attempted_ok = set()
            counts = inventory.counts
            self.status = (
                f"Scanned: {counts[bt.DISP_CONVERT]} file(s) to convert. Nothing has been converted yet."
                if not inventory.cancelled
                else "The scan was cancelled."
            )
            self._notify()

        self._start(
            lambda c: self._ports.scan(folder, settings, c),
            finished,
            "Scanning the folder (read-only)...",
        )

    def set_options(self, **changes: Any) -> None:
        for key, value in changes.items():
            if hasattr(self.options, key):
                setattr(self.options, key, value)
        self.confirmed = False  # a confirmation belongs to one scan under one set of settings
        self._notify()

    def set_confirmed(self, value: bool) -> None:
        self.confirmed = bool(value) and self.inventory is not None and not self.stale()

    def stale(self) -> bool:
        return self.inventory is not None and self._scanned_with != self.settings()

    def run_sample(self) -> None:
        inventory = self.inventory
        if inventory is not None:
            self._run(
                inventory, inventory.sample(), "Converting the sample...", include_existing=False
            )

    def run_remaining(self) -> None:
        inventory = self.inventory
        if inventory is not None:
            rest = tuple(
                e for e in inventory.to_convert if e.relative_path not in self._attempted_ok
            )
            self._run(inventory, rest, "Converting the remaining files...", include_existing=True)

    def _run(
        self,
        inventory: bt.BatchInventory,
        entries: tuple[bt.BatchEntry, ...],
        text: str,
        *,
        include_existing: bool,
    ) -> None:
        if not self.confirmed or self.stale() or self.install is None or not entries:
            self.status = (
                "Confirm the file count, destination and disk budget first."
                if self.install is not None and entries
                else "Nothing to convert, or Blender is not ready."
            )
            self._notify()
            return
        confirmation = inventory.confirmation()

        def work(cancel: threading.Event) -> bt.BatchSummary:
            summary: bt.BatchSummary = self._ports.run(
                inventory, entries, confirmation, cancel, self.progress, include_existing
            )
            return summary

        def finished(summary: bt.BatchSummary) -> None:
            self.summary = summary
            self._attempted_ok |= {r.relative_path for r in summary.results if r.ok}
            self.status = (
                "Finished." if not summary.stopped_reason else f"Stopped: {summary.stopped_reason}"
            )
            self._notify()
            if self._on_finished is not None:
                self._on_finished()

        self._start(work, finished, text)

    def summary_text(self) -> str:
        return self.summary.text() if self.summary is not None else ""

    def diagnostic_text(self, path: str) -> str:
        return self._ports.diagnostic_text(path)

    # ------------------------------------------------------------------ view

    def inventory_lines(self) -> tuple[str, ...]:
        inventory = self.inventory
        if inventory is None:
            return ()
        counts = inventory.counts
        lines = [
            f"Scanned {len(inventory.entries)} file(s) under {inventory.root}",
            f"Will convert: {counts[bt.DISP_CONVERT]}",
            f"Already converted, identical (skipped): {counts[bt.DISP_EXISTING]}",
            f"Duplicates of another file (converted once): {counts[bt.DISP_DUPLICATE]}",
            f"Not eligible (no rig, no animation, unsupported or unreadable): {counts[bt.DISP_INELIGIBLE]}",
            f"Inside archives, not extracted: {counts[bt.DISP_ARCHIVE]}",
            f"Already videos (import them directly): {counts[bt.DISP_VIDEO]}",
        ]
        reasons = Counter(
            e.reason for e in inventory.of(bt.DISP_INELIGIBLE) if e.kind in ("fbx", "bvh")
        )
        for reason, count in reasons.most_common(4):
            lines.append(f"  not eligible x{count}: {reason}")
        profiles = Counter(e.profile for e in inventory.to_convert)
        if profiles:
            lines.append(
                "Rendering profiles: "
                + ", ".join(
                    f"{cp.PROFILE_LABELS[p].split(' (')[0]} x{n}"
                    for p, n in sorted(profiles.items())
                )
            )
        return tuple(lines)

    def view(self) -> BatchView:
        workflow = self._ports.workflow()
        inventory = self.inventory
        stale = self.stale()
        estimate: tuple[str, ...] = ()
        confirm = ""
        warnings: list[str] = []
        if inventory is not None:
            e = inventory.estimate
            estimate = (
                f"Destination: {inventory.destination}",
                f"Published clips: about {_mib(e.expected_bytes)} (could be {_mib(e.low_bytes)} to "
                f"{_mib(e.high_bytes)}; based on {e.basis}). Up to {_mib(e.temporary_bytes)} of temporary "
                "frames while each clip renders, deleted afterwards.",
                f"Free space on that drive: {_mib(inventory.free_bytes)}.",
            )
            budget = inventory.confirmation()
            confirm = (
                f"I confirm: convert {budget.file_count} file(s) into {budget.destination}, "
                f"within a disk budget of {_mib(budget.budget_bytes)}."
            )
            if inventory.truncated:
                warnings.append(
                    "The scan stopped at its size limit; choose a smaller folder to see everything."
                )
            if inventory.settings.start_seconds in ("", "0", "0.0"):
                warnings.append(bt.CALIBRATION_WARNING)
        if stale:
            warnings.append("The settings changed since the scan. Scan again before converting.")
        progress = self._progress
        progress_text = (
            f"File {progress.index + 1} of {progress.total}: {progress.relative_path}"
            if self.busy and progress is not None
            else ""
        )
        result_lines = tuple(self.summary.text().splitlines()) if self.summary is not None else ()
        if self.summary is not None and self.summary.report_path:
            result_lines += (f"Report: {self.summary.report_path}",)
        ready = (
            inventory is not None
            and self.confirmed
            and not stale
            and not self.busy
            and self.install is not None
        )
        remaining = (
            tuple(e for e in inventory.to_convert if e.relative_path not in self._attempted_ok)
            if inventory is not None
            else ()
        )
        return BatchView(
            busy=self.busy,
            status=self.status,
            folder=self.folder,
            blender_text=f"Blender {'.'.join(map(str, self.install.version))}"
            if self.install
            else "Blender: not registered",
            inventory_lines=self.inventory_lines(),
            estimate_lines=estimate,
            confirm_text=confirm,
            confirmed=self.confirmed,
            stale=stale,
            progress_text=progress_text,
            result_lines=result_lines,
            legal_frames=workflow.legal_frames,
            can_choose_folder=not self.busy,
            can_confirm=inventory is not None
            and not stale
            and not self.busy
            and bool(inventory.to_convert),
            can_sample=bool(
                ready and inventory is not None and inventory.to_convert and not self._attempted_ok
            ),
            can_remaining=bool(ready and remaining),
            remaining_label="Convert remaining"
            if self._attempted_ok
            else "Convert all (skip sample)",
            warnings=tuple(warnings),
        )


__all__ = ["BatchOptions", "BatchView", "MotionBatchSession"]
