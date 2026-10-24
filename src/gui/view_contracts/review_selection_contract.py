"""Toolkit-neutral revision bookkeeping for Review's asynchronous selection (PR-GUI-UX-580).

Every operation that can replace or refresh Review's active image (Select Images, Select Folder, Learning and History
handoffs, Queue/History image handoffs, Clear) is an *accepted selection* and bumps one selection revision. Every
asynchronous result carries the revision it was requested under, so a late folder scan, metadata decode or comparison
from a superseded selection context is dropped instead of overwriting the newer selection, its lineage claim, its stage
choices, its prompt edits or its status. The class holds counters only; it owns no thread, widget or file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionToken:
    """What an asynchronous request was started for."""

    selection: int
    image: int = 0
    path: str = ""


class ReviewSelectionRevisions:
    def __init__(self) -> None:
        self._selection = 0
        self._image = 0
        self._folder = 0
        self._compare = 0

    @property
    def selection(self) -> int:
        return self._selection

    def accept_selection(self) -> int:
        """A new selection or handoff was accepted: every outstanding request of the old context is stale."""

        self._selection += 1
        self._image += 1
        self._folder += 1
        self._compare += 1
        return self._selection

    def begin_image(self, path: str) -> SelectionToken:
        """The operator moved to ``path`` inside the current selection (a newer image request supersedes older)."""

        self._image += 1
        self._compare += 1
        return SelectionToken(selection=self._selection, image=self._image, path=str(path))

    def begin_folder_scan(self) -> SelectionToken:
        self._folder += 1
        return SelectionToken(selection=self._selection, image=self._folder)

    def begin_compare(self, path: str) -> SelectionToken:
        self._compare += 1
        return SelectionToken(selection=self._selection, image=self._compare, path=str(path))

    def close_compare(self) -> None:
        """The comparison viewer closed: a decode still running must not publish into a later one."""

        self._compare += 1

    def is_current_image(self, token: SelectionToken) -> bool:
        return token.selection == self._selection and token.image == self._image

    def is_current_folder_scan(self, token: SelectionToken) -> bool:
        return token.selection == self._selection and token.image == self._folder

    def is_current_compare(self, token: SelectionToken) -> bool:
        return token.selection == self._selection and token.image == self._compare


__all__ = ["ReviewSelectionRevisions", "SelectionToken"]
