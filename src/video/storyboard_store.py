"""Atomic Storyboard JSON storage with revision compare-and-swap; never stores executable jobs."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.utils import atomic_io
from src.video.storyboard import StoryboardDraft, StoryboardError, check_id, timestamp

MAX_BYTES = 2 * 1024 * 1024


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise StoryboardError(f"Duplicate JSON field {key!r}; no data rewritten.")
        result[key] = value
    return result


def _check_size(draft: StoryboardDraft) -> None:
    if len(json.dumps(draft.to_dict(), indent=2).encode("utf-8")) > MAX_BYTES:
        raise StoryboardError("Storyboard JSON exceeds the 2 MB limit; nothing written.")


def default_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return (
        (Path(local) if local else Path.home() / ".local" / "share") / "StableNew" / "storyboards"
    )


def read_draft(path: str | Path) -> StoryboardDraft:
    try:
        with Path(path).open("rb") as handle:
            content = handle.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise StoryboardError("Storyboard JSON exceeds the 2 MB limit.")
        return StoryboardDraft.from_dict(json.loads(content, object_pairs_hook=_unique_object))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StoryboardError(f"Malformed Storyboard JSON; original file preserved: {exc}") from exc


class StoryboardStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()

    def _path(self, storyboard_id: str) -> Path:
        path = self.root / f"{check_id(storyboard_id)}.json"
        if path.is_symlink() or path.resolve().parent != self.root.resolve():
            raise StoryboardError("Storyboard storage path escapes its root.")
        return path

    @contextmanager
    def _locked(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix(".lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise StoryboardError(
                "Storyboard is being saved elsewhere (or a stale lock needs operator inspection); retry after it closes."
            ) from exc
        try:
            os.close(descriptor)
            yield
        finally:
            lock.unlink()

    def load(self, storyboard_id: str) -> StoryboardDraft:
        draft = read_draft(self._path(storyboard_id))
        if draft.storyboard_id != storyboard_id:
            raise StoryboardError("Storyboard filename and recorded identity disagree.")
        return draft

    def save(self, draft: StoryboardDraft) -> StoryboardDraft:
        draft = StoryboardDraft.from_dict(draft.to_dict())
        path = self._path(draft.storyboard_id)
        with self._locked(path):
            # Recheck after the exclusive lock; readers see only complete old/new JSON.
            path = self._path(draft.storyboard_id)
            if path.exists():
                current = self.load(draft.storyboard_id)
                if current.revision != draft.revision:
                    raise StoryboardError(
                        "Revision conflict: a newer Storyboard exists; reopen or Save As. Nothing overwritten."
                    )
            elif draft.revision:
                raise StoryboardError(
                    "The saved Storyboard is missing; use Save As to create a new identity."
                )
            saved = replace(draft, revision=draft.revision + 1, updated_at=timestamp())
            _check_size(saved)
            if path.exists():
                atomic_io.atomic_write_json(path, saved.to_dict(), indent=2)
            else:
                atomic_io.atomic_publish_json(path, saved.to_dict(), indent=2)
        return saved

    def import_json(self, path: str | Path) -> StoryboardDraft:
        return self.save(read_draft(path).duplicate())

    def export_json(self, draft: StoryboardDraft, path: str | Path) -> None:
        target = Path(path)
        if target.suffix.lower() != ".json":
            raise StoryboardError(
                "Export must be a new .json file; linked media is never overwritten."
            )
        validated = StoryboardDraft.from_dict(draft.to_dict())
        _check_size(validated)
        atomic_io.atomic_publish_json(target, validated.to_dict(), indent=2)
