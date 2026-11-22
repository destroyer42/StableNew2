"""A fake storyboard service with real (tiny) PNG frames for the Storyboard tab tests (PR-VID-STORY-380).

Tree (same shape as the design's diner example, scaled down): root A has 10 frames; A1 A2(dropped) A3 A4 continue from
A at frame 8 (index 7); A1a and A1b continue from A1 at index 9. Every take keeps 4 frames (a 5-frame clip minus the
overlap frame). A chain C1 -> C2 hangs off A1b so the middle-chain cases exist too.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from src.controller.storyboard_submission_service import (
    ContinuePreview,
    ContinueRequest,
    ContinueResult,
)
from src.video.sequence_ledger import BASIS_NATIVE, FileRecord
from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_cut import CutFrame, CutManifest, CutRange, take_manifest
from src.video.storyboard_projection import TakeView
from src.video.storyboard_tree import StoryboardTree, Take, TreeRoot

NOW = "2026-11-21T10:00:00+00:00"
ROOT_FRAMES = 10
KEPT = 4


def _frames(folder: Path, name: str, count: int) -> list[FileRecord]:
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for index in range(count):
        path = folder / f"{name}_{index:04d}.png"
        Image.new("RGB", (16, 8), (index * 20 % 255, 40, 90)).save(path)
        records.append(FileRecord.of(path))
    return records


def _take(
    take_id: str,
    parent: str,
    handoff: int | None,
    *,
    mark: str = "none",
    mode: str = "parallel",
    position: int = 0,
    prompt: str = "a prompt",
) -> Take:
    return Take(
        take_id=take_id,
        parent_id=parent,
        handoff_index=handoff,
        mode=mode,  # type: ignore[arg-type]
        batch_id="b",
        chain_position=position,
        segment_index=position,
        prompt=prompt,
        negative_prompt="",
        seed_intent="",
        attempts=(f"job-{take_id}",),
        replay_of=None,
        mark=mark,  # type: ignore[arg-type]
        created_at=NOW,
    )


class FakeStore:
    def __init__(self, service: FakeService) -> None:
        self._service = service

    def load(self, storyboard_id: str) -> StoryboardTree:
        return self._service.tree

    def save(self, tree: StoryboardTree) -> StoryboardTree:
        service = self._service
        for old, new in zip(service.tree.takes, tree.takes, strict=False):
            if old.mark != new.mark:
                service.saved_marks.append((new.take_id, new.mark))
        if tree.storyboard_id != service.tree.storyboard_id:
            service.saved_copies.append(tree.title)
        service.tree = replace(tree, revision=tree.revision + 1)
        return service.tree

    def list_trees(self) -> list[tuple[str, str, str]]:
        return [(self._service.tree.storyboard_id, self._service.tree.title, NOW)]


class FakeService:
    def __init__(self, folder: Path) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.saved_marks: list[tuple[str, str]] = []
        self.saved_copies: list[str] = []
        self.files_touched: list[str] = []
        self.last_submit: ContinueRequest | None = None
        self.store = FakeStore(self)
        self.states: dict[str, str] = {}
        self.cuts: dict[str, CutManifest] = {}
        root_records = _frames(folder, "root", ROOT_FRAMES)
        root = take_manifest(
            lead_in=None,
            segments=[(ROOT_PARENT, root_records, 0, BASIS_NATIVE)],
            fps=16,
            width=16,
            height=8,
            job_id="job-root",
        )
        self.cuts[ROOT_PARENT] = root
        tree = StoryboardTree.new(
            "Diner arrest",
            TreeRoot(
                kind="clip",
                job_id="job-root",
                image_path="",
                image_sha256="",
                manifest_path="m.json",
                manifest_sha256="",
                settings=(("frame_count", 5), ("workflow_id", "wan22"), ("workflow_version", "1")),
                fps=16,
                width=16,
                height=8,
                smoothing_text="",
            ),
        )
        takes = [
            _take("t1", ROOT_PARENT, 7, prompt="A1 orders"),
            _take("t2", ROOT_PARENT, 7, mark="dropped"),
            _take("t3", ROOT_PARENT, 7),
            _take("t4", ROOT_PARENT, 7),
            _take("t1a", "t1", 9),
            _take("t1b", "t1", 9),
            _take("c1", "t1b", 11),
            _take("c2", "c1", None, mode="sequential", position=1),
        ]
        for take in takes:
            tree = tree.with_take(take)
        self.tree = replace(tree, storyboard_id="diner")
        self.diner_id = "diner"
        self.chain_mp4 = str(folder / "chain.mp4")
        Path(self.chain_mp4).write_bytes(b"mp4")
        self._folder = folder
        for take in takes:
            self._make_cut(take, folder)

    def _make_cut(self, take: Take, folder: Path) -> None:
        parent_cut = self.cuts[take.parent_id]
        handoff = len(parent_cut.frames) - 1 if take.handoff_index is None else take.handoff_index
        records = _frames(folder, take.take_id, KEPT + 1)
        self.cuts[take.take_id] = take_manifest(
            lead_in=parent_cut.prefix(handoff + 1),
            segments=[(take.take_id, records, 1, BASIS_NATIVE)],
            fps=16,
            width=16,
            height=8,
            job_id=f"job-{take.take_id}",
        )

    def job_of(self, take_id: str) -> str:
        return f"job-{take_id}"

    # --- the surface the tab uses ---------------------------------------------------------------

    def reconcile(self, storyboard_id: str) -> StoryboardTree:
        self.calls.append(("reconcile", storyboard_id))
        return self.tree

    def project(self, tree: StoryboardTree) -> dict[str, TakeView]:
        self.calls.append(("project",))
        views: dict[str, TakeView] = {}
        for take in tree.takes:
            cut = self.cuts[take.take_id]
            owned = [r for r in cut.segment_ranges() if r.owner == take.take_id]
            state = self.states.get(take.take_id, "completed")
            mp4 = self.chain_mp4 if take.take_id in ("c1", "c2") else None
            views[take.take_id] = TakeView(
                take_id=take.take_id,
                state=state,
                status_text=state,  # type: ignore[arg-type]
                shown_job_id=self.job_of(take.take_id),
                manifest=CutFrame("m.json", "0" * 64),
                stitched_path=mp4,
                clip_path=None,
                encoded=mp4 is not None,
                frames_ok=True,
                problem="",
                can_resume=state in ("failed", "cancelled"),
                can_replay=state in ("completed", "failed", "cancelled"),
                thumbnail_path=cut.frames[owned[0].start].path,
            )
        return views

    def parent_cut(self, tree: StoryboardTree, take_id: str) -> CutManifest | None:
        self.calls.append(("parent_cut", take_id))
        return self.cuts.get(take_id)

    def output_root(self) -> str:
        return str(self._folder)

    def create_from_clip(self, job_id: str, title: str) -> StoryboardTree:
        self.calls.append(("create_from_clip", job_id, title))
        return self.tree

    def create_from_image(self, image_path: str, settings: Any, title: str) -> StoryboardTree:
        self.calls.append(("create_from_image", image_path, dict(settings), title))
        return self.tree

    def preview(self, request: ContinueRequest) -> ContinuePreview:
        self.calls.append(("preview", request))
        return ContinuePreview(
            jobs=len(request.rows) if request.mode == "parallel" else 1,
            segments=len(request.rows),
            lead_in_frames=(request.handoff_index or 0) + 1,
            total_cut_frames=234,
            fps=16,
            workflow_id="wan22",
            workflow_version="1",
            seeds=tuple(row.seed.strip() or "random" for row in request.rows),
        )

    def submit(self, request: ContinueRequest) -> ContinueResult:
        self.calls.append(("submit", request))
        self.last_submit = request
        return ContinueResult(job_ids=("job-new",), take_ids=("new",), tree=self.tree)


def fake_controller(service: FakeService) -> SimpleNamespace:
    calls: list[tuple[str, str]] = []
    workflow = SimpleNamespace(storyboards=service)

    def resume_sequence(
        job_id: str, from_segment: int | None = None, *, ledger_path: str | None = None
    ) -> str:
        calls.append(("resume_sequence", job_id))
        return "job-resumed"

    def replay_sequence(job_id: str, *, ledger_path: str | None = None) -> str:
        calls.append(("replay_sequence", job_id))
        return "job-replayed"

    workflow.resume_sequence = resume_sequence
    workflow.replay_sequence = replay_sequence
    service.controller_calls = calls  # type: ignore[attr-defined]
    return SimpleNamespace(get_video_workflow_controller=lambda: workflow)


__all__ = ["CutRange", "FakeService", "fake_controller"]
