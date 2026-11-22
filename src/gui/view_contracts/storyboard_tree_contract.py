"""Tk-free state of the Storyboard tab (PR-VID-STORY-380, spec 7.2).

Columns, selection, the slider's owner arithmetic, the Continue panel's row rules and the button states. The tab and its
widgets render this; nothing here imports ``tkinter`` or touches a file. Ownership of a frame comes from the tree's
parent and handoff links, never from the owner labels inside a manifest (a replay's job carries its original take ids,
so those labels are provenance only).

Display is 1-based; every stored index is 0-based.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_projection import TakeView
from src.video.storyboard_tree import MAX_ROWS, StoryboardTree, Take

MAX_SEED: Final = 2147483647
EXCERPT_LIMIT: Final = 40
AI_NOT_SET_UP: Final = "AI Assist is not set up"
#: Frames a take drops at its start because they repeat the frame before them (spec 7.6).
DEFAULT_TRIMMED: Final = 1


class RowLike(Protocol):
    @property
    def prompt(self) -> str: ...

    @property
    def seed(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Card:
    take_id: str
    label: str
    excerpt: str
    status_text: str
    mark: str
    on_path: bool
    selected: bool


@dataclass(frozen=True, slots=True)
class Column:
    title: str
    cards: tuple[Card, ...]


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= EXCERPT_LIMIT else flat[: EXCERPT_LIMIT - 1] + "…"


class StoryboardTreeContract:
    def __init__(
        self,
        tree: StoryboardTree,
        views: Mapping[str, TakeView],
        *,
        ai_reason: Callable[[], str] | None = None,
    ) -> None:
        self.tree = tree
        self.views = views
        self._ai_reason = ai_reason
        self._takes: dict[str, Take] = {take.take_id: take for take in tree.takes}
        self.selected_id = ROOT_PARENT
        self._owners: tuple[str, ...] = ()
        self._trimmed: Mapping[str, int] = {}
        self._lengths: Mapping[str, int] = {}

    # ------------------------------------------------------------------ tree

    def label(self, node_id: str) -> str:
        return self.tree.label(node_id)

    def path_to(self, node_id: str) -> tuple[str, ...]:
        """Node ids from the root down to ``node_id`` (the root is ``ROOT_PARENT``)."""

        chain = [node_id]
        while chain[-1] != ROOT_PARENT:
            chain.append(self._takes[chain[-1]].parent_id)
        return tuple(reversed(chain))

    def select(self, node_id: str) -> None:
        if node_id != ROOT_PARENT and node_id not in self._takes:
            raise KeyError(f"Unknown take {node_id!r}")
        self.selected_id = node_id
        self._owners = ()

    def dropped_count(self) -> int:
        return sum(1 for take in self.tree.takes if take.mark == "dropped")

    def _header(self, take_ids: Sequence[str]) -> str:
        seen: list[str] = []
        for take_id in take_ids:
            take = self._takes[take_id]
            where = "end" if take.handoff_index is None else f"f{take.handoff_index + 1}"
            text = f"{self.label(take.parent_id)} @ {where}"
            if text not in seen:
                seen.append(text)
        return "from " + ", ".join(seen)

    def columns(self, show_dropped: bool) -> tuple[Column, ...]:
        path = set(self.path_to(self.selected_id))
        by_depth: dict[int, list[Take]] = {}
        for take in self.tree.takes:
            if take.mark == "dropped" and not show_dropped:
                continue
            by_depth.setdefault(self.tree.depth(take.take_id), []).append(take)
        root_card = Card(
            ROOT_PARENT,
            self.label(ROOT_PARENT),
            "still image" if self.tree.root.kind == "image" else "root clip",
            "root",
            "none",
            ROOT_PARENT in path,
            self.selected_id == ROOT_PARENT,
        )
        columns = [Column("Shot 1", (root_card,))]
        for depth in sorted(by_depth):
            takes = by_depth[depth]
            cards = tuple(self._card(take, path) for take in takes)
            title = f"Shot {depth + 1} · {self._header([t.take_id for t in takes])}"
            columns.append(Column(title, cards))
        return tuple(columns)

    def _card(self, take: Take, path: set[str]) -> Card:
        view = self.views.get(take.take_id)
        return Card(
            take.take_id,
            self.label(take.take_id),
            _excerpt(take.prompt),
            "pending" if view is None else view.status_text,
            take.mark,
            take.take_id in path,
            take.take_id == self.selected_id,
        )

    # ------------------------------------------------------------------ the slider

    def selected_cut_owners(
        self,
        cut_length: int,
        segment_lengths: Mapping[str, int],
        trimmed: Mapping[str, int] | None = None,
    ) -> tuple[str, ...]:
        """The owner node of every frame of the selected node's cut.

        ``segment_lengths`` is each node's kept frame count; ``trimmed`` the leading frames a node dropped as repeats
        (default 0 for the root, 1 for a take). The result is remembered for the slider methods below.
        """

        owners = self._owners_of(self.selected_id, segment_lengths)
        if len(owners) != cut_length:
            raise ValueError(
                f"The cut has {cut_length} frames but the tree accounts for {len(owners)}."
            )
        self._owners = owners
        self._lengths = dict(segment_lengths)
        self._trimmed = dict(trimmed or {})
        return owners

    def _owners_of(self, node_id: str, lengths: Mapping[str, int]) -> tuple[str, ...]:
        if node_id == ROOT_PARENT:
            return (ROOT_PARENT,) * int(lengths.get(ROOT_PARENT, 0))
        take = self._takes[node_id]
        parent = self._owners_of(take.parent_id, lengths)
        keep = len(parent) if take.handoff_index is None else take.handoff_index + 1
        return parent[:keep] + (node_id,) * int(lengths.get(node_id, 0))

    def joins(self) -> tuple[int, ...]:
        """Slider tick positions: the first frame of every owner after the first."""

        return tuple(
            index for index in range(1, len(self._owners)) if self._owners[index] != self._owners[index - 1]
        )

    def _own_position(self, index: int) -> tuple[str, int, int]:
        owner = self._owners[index]
        start = self._owners.index(owner)
        trimmed = self._trimmed.get(owner, 0 if owner == ROOT_PARENT else DEFAULT_TRIMMED)
        return owner, index - start + 1 + trimmed, int(self._lengths.get(owner, 0)) + trimmed

    def readout(self, index: int) -> str:
        """``frame 226 / 234 · A1b frame 78 of 81``; the owner's number counts its trimmed overlap frame."""

        owner, number, total = self._own_position(index)
        return (
            f"frame {index + 1} / {len(self._owners)} · {self.label(owner)} frame {number} of {total}"
        )

    def continue_target(self, index: int) -> tuple[str, int]:
        """The node that owns frame ``index`` and the handoff index (the same index in that node's cut)."""

        if not 0 <= index < len(self._owners):
            raise IndexError(f"Frame {index + 1} is outside the cut.")
        return self._owners[index], index

    def continue_title(self, index: int) -> str:
        owner, _number, _total = self._own_position(index)
        return f"Continue {self.label(owner)} from its frame {index + 1}"

    # ------------------------------------------------------------------ the Continue panel

    @staticmethod
    def validate_rows(rows: Sequence[RowLike]) -> list[str]:
        if not 1 <= len(rows) <= MAX_ROWS:
            return [f"A Continue has 1 to {MAX_ROWS} rows."]
        errors: list[str] = []
        for number, row in enumerate(rows, start=1):
            if not row.prompt.strip():
                errors.append(f"Row {number} needs a positive prompt.")
            seed = row.seed.strip()
            if seed and seed.lower() != "random":
                valid = seed.isascii() and seed.isdigit() and int(seed) <= MAX_SEED
                if not valid:
                    errors.append(
                        f"Row {number} seed must be blank, random or a whole number 0-{MAX_SEED}."
                    )
        return errors

    @staticmethod
    def queue_label(mode: str, count: int) -> str:
        return f"Queue chain of {count}" if mode == "sequential" else f"Queue {count} takes"

    def ai_button(self) -> tuple[bool, str]:
        """Always disabled in this package; the reason is the readiness record's when one is reachable."""

        reason = self._ai_reason() if self._ai_reason is not None else ""
        return False, reason.strip() or AI_NOT_SET_UP

    def continue_allowed(self, node_id: str) -> tuple[bool, str]:
        if node_id == ROOT_PARENT:
            return True, ""  # a clip root has its manifest; an image root starts without a lead-in
        view = self.views.get(node_id)
        if view is None or view.state == "pending":
            return False, "This take has not been queued yet."
        if not view.frames_ok:
            return False, view.problem or "frames missing or changed"
        if view.manifest is None:
            return False, "This take has no frames yet."
        return True, ""

    def engine_line(self) -> str:
        settings: dict[str, Any] = dict(self.tree.root.settings)
        root = self.tree.root
        workflow = str(settings.get("workflow_id") or "workflow")
        version = str(settings.get("workflow_version") or "")
        name = f"{workflow} {version}".strip()
        frames = settings.get("frame_count")
        fps = int(root.fps) if float(root.fps).is_integer() else root.fps
        frame_text = f" · {frames} f" if frames else ""
        return f"Engine: {name} · {root.width}×{root.height}{frame_text} · {fps} fps (inherited)"


__all__ = [
    "AI_NOT_SET_UP",
    "Card",
    "Column",
    "StoryboardTreeContract",
]
