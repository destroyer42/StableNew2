"""Form section contract independent of widget framework."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FormSectionState:
    mode: str
    editable_text: str
    readonly_text: str


def update_form_section(
    *,
    previous_mode: str,
    next_mode: str,
    edits_by_mode: dict[str, str],
    readonly_text: str,
) -> tuple[FormSectionState, dict[str, str]]:
    mode_from = str(previous_mode or "append")
    mode_to = str(next_mode or "append")
    values = dict(edits_by_mode or {})
    if mode_to == "modify":
        values["modify"] = values.get("modify") or str(readonly_text or "")
    editable = values.get(mode_to, "")
    state = FormSectionState(
        mode=mode_to,
        editable_text=str(editable or ""),
        readonly_text=str(readonly_text or ""),
    )
    return state, values
