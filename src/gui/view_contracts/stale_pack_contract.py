"""Toolkit-neutral rules for adding a PromptPack that has unsaved Prompt-tab edits (GUI-TRUTH-912).

"Add to Job" builds its entries from the pack file on disk. The Prompt tab edits a pack in memory and only writes it on
an explicit save, so adding a pack that is open and modified there would silently queue the *older saved* text. The
sidebar asks this module whether that is the case, and shows the notice below instead of adding. Nothing here touches
Tk, storage or the controller.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from src.utils.prompt_pack_utils import same_pack_file

SAVE_AND_ADD_LABEL = "Save and add"
ADD_SAVED_LABEL = "Add saved version"


def notice_text(pack_name: str) -> str:
    return (
        f"'{pack_name}' has unsaved edits in the Prompt tab. Adding it uses the saved file, "
        "which does not include them."
    )


def save_failed_text(pack_name: str, error: object) -> str:
    return f"Could not save '{pack_name}': {error}. Nothing was added."


def unsaved_prompt_tab_pack(
    workspace: Any, summaries: Iterable[Any], pack_ids: Sequence[str]
) -> str | None:
    """The name of the selected pack that the Prompt tab holds with unsaved edits, or ``None``.

    Only the very same file counts (``same_pack_file``), so another pack that merely shares a name does not. A workspace
    with no open pack, no saved path or no pending edits is never a match.
    """
    if workspace is None or not getattr(workspace, "dirty", False):
        return None
    pack = getattr(workspace, "current_pack", None)
    open_path = getattr(pack, "path", None) if pack is not None else None
    if not open_path:
        return None
    wanted = {str(item) for item in pack_ids}
    for summary in summaries:
        name = getattr(summary, "name", None)
        path = getattr(summary, "path", None)
        if name in wanted and path is not None and same_pack_file(Path(path), Path(str(open_path))):
            return str(name)
    return None


__all__ = [
    "ADD_SAVED_LABEL",
    "SAVE_AND_ADD_LABEL",
    "notice_text",
    "save_failed_text",
    "unsaved_prompt_tab_pack",
]
