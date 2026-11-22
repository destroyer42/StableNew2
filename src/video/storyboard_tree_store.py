"""Atomic storyboard-tree JSON storage with revision compare-and-swap (PR-VID-STORY-380).

Same rules as ``storyboard_store.py``: an exclusive ``.lock``, a root-escape check, duplicate-key refusal, a 2 MB cap,
``atomic_publish_json`` for a new file and ``atomic_write_json`` for an existing one. A malformed or future-schema file
is refused and never rewritten.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.utils import atomic_io
from src.video.storyboard import timestamp
from src.video.storyboard_tree import StoryboardTree, StoryboardTreeError, check_storyboard_id

MAX_BYTES = 2 * 1024 * 1024
UNREADABLE_TITLE = "(unreadable)"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StoryboardTreeError(f"Duplicate JSON field {key!r}; no data rewritten.")
        result[key] = value
    return result


def _check_size(tree: StoryboardTree) -> None:
    if len(json.dumps(tree.to_dict(), indent=2).encode("utf-8")) > MAX_BYTES:
        raise StoryboardTreeError("Storyboard JSON exceeds the 2 MB limit; nothing written.")


def default_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "StableNew" / "storyboard_trees"


def read_tree(path: str | Path) -> StoryboardTree:
    try:
        with Path(path).open("rb") as handle:
            content = handle.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise StoryboardTreeError("Storyboard JSON exceeds the 2 MB limit.")
        return StoryboardTree.from_dict(json.loads(content, object_pairs_hook=_unique_object))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StoryboardTreeError(
            f"Malformed storyboard JSON; original file preserved: {exc}"
        ) from exc
    except OSError as exc:
        raise StoryboardTreeError(f"Storyboard file cannot be read: {exc}") from exc


class StoryboardTreeStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()

    def _path(self, storyboard_id: str) -> Path:
        path = self.root / f"{check_storyboard_id(storyboard_id)}.json"
        if path.is_symlink() or path.resolve().parent != self.root.resolve():
            raise StoryboardTreeError("Storyboard storage path escapes its root.")
        return path

    @contextmanager
    def _locked(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix(".lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise StoryboardTreeError(
                "Storyboard is being saved elsewhere (or a stale lock needs operator inspection); "
                "retry after it closes."
            ) from exc
        try:
            os.close(descriptor)
            yield
        finally:
            lock.unlink()

    def load(self, storyboard_id: str) -> StoryboardTree:
        tree = read_tree(self._path(storyboard_id))
        if tree.storyboard_id != storyboard_id:
            raise StoryboardTreeError("Storyboard filename and recorded identity disagree.")
        return tree

    def save(self, tree: StoryboardTree) -> StoryboardTree:
        tree = StoryboardTree.from_dict(tree.to_dict())
        path = self._path(tree.storyboard_id)
        with self._locked(path):
            # Recheck after the exclusive lock; readers see only complete old/new JSON.
            path = self._path(tree.storyboard_id)
            if path.exists():
                current = self.load(tree.storyboard_id)
                if current.revision != tree.revision:
                    raise StoryboardTreeError(
                        "Revision conflict: a newer storyboard exists; reopen or Save As. "
                        "Nothing overwritten."
                    )
            elif tree.revision:
                raise StoryboardTreeError(
                    "The saved storyboard is missing; use Save As to create a new identity."
                )
            saved = replace(tree, revision=tree.revision + 1, updated_at=timestamp())
            _check_size(saved)
            if path.exists():
                atomic_io.atomic_write_json(path, saved.to_dict(), indent=2)
            else:
                atomic_io.atomic_publish_json(path, saved.to_dict(), indent=2)
        return saved

    def list_trees(self) -> list[tuple[str, str, str]]:
        """``(id, title, updated_at)``, newest first. Unreadable files are listed as ``(unreadable)`` and never touched."""

        if not self.root.is_dir():
            return []
        readable: list[tuple[str, str, str]] = []
        unreadable: list[tuple[str, str, str]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                storyboard_id = check_storyboard_id(path.stem)
            except StoryboardTreeError:
                continue
            try:
                tree = self.load(storyboard_id)
            except StoryboardTreeError:
                unreadable.append((storyboard_id, UNREADABLE_TITLE, ""))
            else:
                readable.append((tree.storyboard_id, tree.title, tree.updated_at))
        readable.sort(key=lambda row: row[2], reverse=True)
        return readable + unreadable
