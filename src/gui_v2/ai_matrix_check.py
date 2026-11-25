"""Deterministic matrix and prompt checks for the AI Assist Check tab (AI-230e). No model, no I/O, no Tk.

Reads the matrix as :class:`~src.gui_v2.ai_slot_variety.SlotState` snapshots and the pack's prompt texts, and reports what a
careful operator would look for by hand: a slot no prompt uses, a marker with no slot, duplicate and near-duplicate values, a
slot with nothing to vary, a very unbalanced matrix. Most findings are notes with a pointer to the Matrix tab. Exact
duplicate values have a fix (remove the later copies, keep the first) that the owner applies only on an explicit press through
the Matrix tab's own edit path, with the same journal and Undo as every other change.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from src.gui_v2.ai_changes import KIND_NOTE, KIND_REMOVE_DUPLICATE, ProposedChange
from src.gui_v2.ai_slot_variety import (
    HIDDEN_TEXT,
    SlotState,
    VarietyContext,
    matrix_state,
    near_key,
)
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

_TOKEN = re.compile(r"\[\[([^\[\]]+)\]\]")
UNBALANCED_RATIO = 8
UNBALANCED_MIN_LARGEST = 16
SHOWN_VALUES = 6

SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    """One check result. ``fix`` is empty for a note; ``"dedupe"`` for exact duplicates that Apply can remove."""

    key: str
    code: str
    severity: str
    title: str
    detail: str = field(repr=False)
    slot_index: int = -1
    fix: str = ""
    before: tuple[str, ...] = field(default=(), repr=False)
    after: tuple[str, ...] = field(default=(), repr=False)


def _shown(text: str, is_visible: Callable[[str], bool]) -> str:
    return text if is_visible(text) else HIDDEN_TEXT


def dedupe_values(values: Sequence[Any]) -> tuple[str, ...]:
    """The values with every later exact copy removed (first occurrence kept, order kept)."""

    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        kept.append(text)
    return tuple(kept)


def run_checks(
    slots: Sequence[SlotState],
    prompts: Sequence[tuple[str, str]],
    *,
    is_visible: Callable[[str], bool] = lambda _text: True,
) -> tuple[Finding, ...]:
    """Every finding for this matrix and these ``(positive, negative)`` prompt texts, most important first."""

    findings: list[Finding] = []

    def add(
        code: str,
        severity: str,
        title: str,
        detail: str,
        *,
        index: int = -1,
        fix: str = "",
        before: Sequence[str] = (),
        after: Sequence[str] = (),
    ) -> None:
        findings.append(
            Finding(
                f"check:{len(findings)}",
                code,
                severity,
                title,
                detail,
                index,
                fix,
                tuple(before),
                tuple(after),
            )
        )

    used: Counter[str] = Counter()
    undefined: dict[str, set[int]] = {}
    known = {normalize_matrix_slot_name(slot.name) for slot in slots if slot.name.strip()}
    for number, (positive, negative) in enumerate(prompts, start=1):
        for text in (positive, negative):
            for match in _TOKEN.finditer(text or ""):
                key = normalize_matrix_slot_name(match.group(1))
                used[key] += 1
                if key not in known:
                    undefined.setdefault(match.group(1), set()).add(number)

    name_counts = Counter(
        normalize_matrix_slot_name(slot.name) for slot in slots if slot.name.strip()
    )
    for index, slot in enumerate(slots):
        shown = _shown(slot.name, is_visible)
        key = normalize_matrix_slot_name(slot.name)
        row = f"Matrix tab row {index + 1}"
        if not slot.name.strip() and slot.values:
            add(
                "unnamed_slot",
                SEVERITY_WARNING,
                f"Row {index + 1} has values but no name",
                f"{row}: the matrix skips a row without a name. Give it a name or delete it.",
                index=index,
            )
            continue
        if not slot.name.strip():
            continue
        if not slot.values:
            add(
                "empty_slot",
                SEVERITY_WARNING,
                f"Slot {shown} has no values",
                f"{row}: the matrix skips a slot without values. Add values or delete the row.",
                index=index,
            )
            continue
        if name_counts[key] > 1:
            add(
                "duplicate_slot_name",
                SEVERITY_WARNING,
                f"Slot name {shown} is used more than once",
                f"{row}: names that match ignoring case, spaces and punctuation are one slot to the compiler; the last "
                "definition wins. Rename or delete one.",
                index=index,
            )
        if key and not used.get(key):
            add(
                "unused_slot",
                SEVERITY_WARNING,
                f"Slot {shown} is not used by any prompt",
                f"{row}: no prompt in this pack contains [[{shown}]]. Put the marker in a prompt, or delete the row.",
                index=index,
            )
        values = [str(value) for value in slot.values]
        deduped = dedupe_values(values)
        if len(deduped) < len(values):
            extra = len(values) - len(deduped)
            add(
                "exact_duplicate",
                SEVERITY_WARNING,
                f"Slot {shown} repeats {extra} value(s)",
                f"{row}: identical values only make the matrix repeat itself. Apply removes the later copies and keeps "
                "the first.",
                index=index,
                fix="dedupe" if slot.editable else "",
                before=values,
                after=deduped,
            )
        seen: dict[str, str] = {}
        near: list[str] = []
        for value in deduped:
            folded = near_key(value)
            if folded in seen and seen[folded] != value:
                near.append(f"{seen[folded]} / {value}")
            seen.setdefault(folded, value)
        if near:
            shown_pairs = ", ".join(_shown(pair, is_visible) for pair in near[:3])
            add(
                "near_duplicate",
                SEVERITY_INFO,
                f"Slot {shown} has near-duplicate values",
                f"{row}: {shown_pairs}. They differ only in case, spacing or a plural; keep both only if you mean it.",
                index=index,
            )
        if len(deduped) == 1:
            add(
                "single_value",
                SEVERITY_INFO,
                f"Slot {shown} has only one value",
                f"{row}: a slot with one value adds no variety. Add values or put the text straight in the prompt.",
                index=index,
            )
        if not slot.editable and name_counts[key] <= 1:
            add(
                "not_editable",
                SEVERITY_INFO,
                f"AI Assist cannot add values to slot {shown}",
                f"{row}: a slot needs a unique name and text values without commas before AI Assist can edit it.",
                index=index,
            )

    for token, numbers in sorted(undefined.items()):
        where = ", ".join(str(n) for n in sorted(numbers)[:5])
        add(
            "undefined_marker",
            SEVERITY_WARNING,
            f"[[{_shown(token, is_visible)}]] has no slot",
            f"Prompt {where} uses [[{_shown(token, is_visible)}]] but the Matrix tab has no slot with that name.",
        )

    sizes = [len(dedupe_values(s.values)) for s in slots if s.name.strip() and s.values]
    if len(sizes) >= 2 and max(sizes) >= UNBALANCED_MIN_LARGEST and max(sizes) >= UNBALANCED_RATIO * min(sizes):
        add(
            "unbalanced",
            SEVERITY_INFO,
            "The slots are very unevenly sized",
            f"The largest slot has {max(sizes)} values and the smallest {min(sizes)}. A large slot dominates the "
            "combinations; trim it or grow the others if that is not intended.",
        )

    order = {SEVERITY_WARNING: 0, SEVERITY_INFO: 1}
    ranked = sorted(findings, key=lambda f: (order.get(f.severity, 2), f.key))
    return tuple(
        replace(finding, key=f"check:{position}") for position, finding in enumerate(ranked)
    )


def check_summary(findings: Sequence[Finding]) -> str:
    if not findings:
        return "No problems found."
    warnings = sum(f.severity == SEVERITY_WARNING for f in findings)
    fixable = sum(bool(f.fix) for f in findings)
    text = f"{warnings} warning(s), {len(findings) - warnings} note(s)"
    return f"{text}; {fixable} can be fixed with Apply." if fixable else f"{text}."


def _values_line(values: Sequence[str]) -> str:
    shown = list(values)
    if len(shown) > SHOWN_VALUES:
        shown = ["…", *shown[-SHOWN_VALUES:]]
    return ", ".join(shown)


def finding_cards(
    findings: Sequence[Finding],
    *,
    applied: frozenset[str] = frozenset(),
    is_visible: Callable[[str], bool] = lambda _text: True,
) -> tuple[ProposedChange, ...]:
    """One card per finding. A fixable finding is an offered card; every other finding is a note."""

    cards: list[ProposedChange] = []
    for finding in findings:
        prefix = "Warning" if finding.severity == SEVERITY_WARNING else "Note"
        if finding.fix == "dedupe":
            visible = all(is_visible(v) for v in finding.before)
            cards.append(
                ProposedChange(
                    finding.key,
                    KIND_REMOVE_DUPLICATE,
                    finding.title,
                    before=_values_line(finding.before) if visible else HIDDEN_TEXT,
                    after=_values_line(finding.after) if visible else HIDDEN_TEXT,
                    effect=finding.detail,
                    applied=finding.key in applied,
                )
            )
        else:
            cards.append(
                ProposedChange(
                    finding.key, KIND_NOTE, f"{prefix}: {finding.title}", detail=finding.detail
                )
            )
    return tuple(cards)


def with_slot_values(context: VarietyContext, index: int, values: Sequence[str]) -> VarietyContext:
    """The matrix state expected after slot ``index`` has its values replaced through the Matrix editor."""

    raw = [
        _Raw(slot.name, list(values) if i == index else list(slot.values))
        for i, slot in enumerate(context.slots)
    ]
    return replace(context, slots=matrix_state(raw))


@dataclass(frozen=True, slots=True)
class _Raw:
    name: str
    values: list[Any]


__all__ = [
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "UNBALANCED_MIN_LARGEST",
    "UNBALANCED_RATIO",
    "Finding",
    "check_summary",
    "dedupe_values",
    "finding_cards",
    "run_checks",
    "with_slot_values",
]
