"""Storyboard tree-of-takes authoring file (PR-VID-STORY-380).

A named tree: one root (a clip or an image) and the takes continued from it. The file is authoring state only. It never
holds job status, output paths or an executable plan; job ids are recorded and their state is read back from the
repository by the callers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final, Literal, cast
from uuid import uuid4

from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard import StoryboardError, check_id, timestamp

TREE_SCHEMA: Final = "stablenew.storyboard-tree.v1"
#: Rows (takes) one Continue may add.
MAX_ROWS: Final = 6

_TAKE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = 65536
_MAX_TITLE = 200
_MAX_JSON_DEPTH = 8
_ROOT_KINDS = frozenset({"clip", "image"})
_MODES = frozenset({"parallel", "sequential"})
_MARKS = frozenset({"none", "kept", "dropped"})


class StoryboardTreeError(ValueError):
    """A storyboard tree cannot be safely read, edited or saved."""


def check_storyboard_id(value: Any) -> str:
    try:
        return check_id(value)
    except StoryboardError as exc:
        raise StoryboardTreeError(str(exc)) from exc


def _text(value: Any, label: str, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise StoryboardTreeError(f"{label} must be a string of at most {limit} characters.")
    return value


def _hash(value: Any, label: str) -> str:
    text = _text(value, label)
    if text and not _SHA.fullmatch(text):
        raise StoryboardTreeError(f"{label} must be empty or a SHA-256.")
    return text


def _int(value: Any, label: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise StoryboardTreeError(f"{label} must be an integer of at least {minimum}.")
    return value


def _stamp(value: Any, label: str) -> str:
    try:
        if datetime.fromisoformat(_text(value, label, 64)).tzinfo is None:
            raise ValueError("missing timezone")
    except ValueError as exc:
        raise StoryboardTreeError(f"Invalid {label} timestamp: {exc}") from exc
    return str(value)


def _fields(data: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != allowed:
        raise StoryboardTreeError(
            f"Malformed {label}: missing or unknown fields; file left untouched."
        )
    return data


def _freeze(value: Any, depth: int = 0) -> Any:
    """Validate a JSON value and turn lists into tuples so a root compares equal after a round trip."""

    if depth > _MAX_JSON_DEPTH:
        raise StoryboardTreeError("Root settings are nested too deeply.")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, depth + 1) for item in value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise StoryboardTreeError("Root setting objects need text keys.")
        return {key: _freeze(item, depth + 1) for key, item in value.items()}
    raise StoryboardTreeError("Root settings must be plain JSON values.")


def _thaw(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    if isinstance(value, dict):
        return {key: _thaw(item) for key, item in value.items()}
    return value


def _number(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise StoryboardTreeError(f"{label} must be a positive number.")
    return value


@dataclass(frozen=True, slots=True)
class TreeRoot:
    kind: Literal["clip", "image"]
    job_id: str
    image_path: str
    image_sha256: str
    manifest_path: str
    manifest_sha256: str
    settings: tuple[tuple[str, Any], ...]
    fps: int | float
    width: int
    height: int
    smoothing_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "job_id": self.job_id,
            "image_path": self.image_path,
            "image_sha256": self.image_sha256,
            "manifest_path": self.manifest_path,
            "manifest_sha256": self.manifest_sha256,
            "settings": {key: _thaw(value) for key, value in self.settings},
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "smoothing_text": self.smoothing_text,
        }

    @classmethod
    def from_dict(cls, data: Any) -> TreeRoot:
        raw = _fields(data, set(cls.__dataclass_fields__), "storyboard root")
        if raw["kind"] not in _ROOT_KINDS:
            raise StoryboardTreeError("A storyboard root is a clip or an image.")
        settings = raw["settings"]
        if not isinstance(settings, dict) or not all(
            isinstance(key, str) and key for key in settings
        ):
            raise StoryboardTreeError("Root settings must be an object with text keys.")
        return cls(
            kind=raw["kind"],
            job_id=_text(raw["job_id"], "Root job id", 128),
            image_path=_text(raw["image_path"], "Root image path", 4096),
            image_sha256=_hash(raw["image_sha256"], "Root image identity"),
            manifest_path=_text(raw["manifest_path"], "Root manifest path", 4096),
            manifest_sha256=_hash(raw["manifest_sha256"], "Root manifest identity"),
            settings=tuple(sorted((key, _freeze(value)) for key, value in settings.items())),
            fps=_number(raw["fps"], "Root fps"),
            width=_int(raw["width"], "Root width", 1),
            height=_int(raw["height"], "Root height", 1),
            smoothing_text=_text(raw["smoothing_text"], "Root smoothing text", 1024),
        )


@dataclass(frozen=True, slots=True)
class Take:
    take_id: str
    parent_id: str
    #: 0-based index of the handoff frame in the parent cut; ``None`` is the parent's last frame (chain positions above 0).
    handoff_index: int | None
    mode: Literal["parallel", "sequential"]
    batch_id: str
    chain_position: int
    segment_index: int
    prompt: str
    negative_prompt: str
    seed_intent: str
    attempts: tuple[str, ...]
    replay_of: str | None
    mark: Literal["none", "kept", "dropped"]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "take_id": self.take_id,
            "parent_id": self.parent_id,
            "handoff_index": self.handoff_index,
            "mode": self.mode,
            "batch_id": self.batch_id,
            "chain_position": self.chain_position,
            "segment_index": self.segment_index,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "seed_intent": self.seed_intent,
            "attempts": list(self.attempts),
            "replay_of": self.replay_of,
            "mark": self.mark,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Take:
        raw = _fields(data, set(cls.__dataclass_fields__), "take")
        take_id = _text(raw["take_id"], "Take id", 64)
        if not _TAKE_ID.fullmatch(take_id) or take_id == ROOT_PARENT:
            raise StoryboardTreeError(f"Invalid take id {take_id!r}.")
        parent_id = _text(raw["parent_id"], "Take parent", 64)
        handoff = raw["handoff_index"]
        if handoff is not None:
            handoff = _int(handoff, "Take handoff index", 0)
        if raw["mode"] not in _MODES:
            raise StoryboardTreeError("A take is parallel or sequential.")
        if raw["mark"] not in _MARKS:
            raise StoryboardTreeError("A take mark is none, kept or dropped.")
        attempts = raw["attempts"]
        if not isinstance(attempts, list) or len(attempts) > 1000:
            raise StoryboardTreeError("Take attempts must be a list of job ids.")
        replay_of = raw["replay_of"]
        if replay_of is not None:
            replay_of = _text(replay_of, "Take replay_of", 64)
        return cls(
            take_id=take_id,
            parent_id=parent_id,
            handoff_index=handoff,
            mode=raw["mode"],
            batch_id=_text(raw["batch_id"], "Take batch id", 128),
            chain_position=_int(raw["chain_position"], "Take chain position", 0),
            segment_index=_int(raw["segment_index"], "Take segment index", 0),
            prompt=_text(raw["prompt"], "Take prompt"),
            negative_prompt=_text(raw["negative_prompt"], "Take negative prompt"),
            seed_intent=_text(raw["seed_intent"], "Take seed intent", 256),
            attempts=tuple(_job_id(item) for item in attempts),
            replay_of=replay_of,
            mark=raw["mark"],
            created_at=_stamp(raw["created_at"], "take created_at"),
        )


def _job_id(value: Any) -> str:
    text = _text(value, "Job id", 128)
    if not text:
        raise StoryboardTreeError("A job id cannot be empty.")
    return text


def _letters(number: int) -> str:
    """1 -> a, 26 -> z, 27 -> aa, 28 -> ab ..."""

    out = ""
    while number > 0:
        number, rest = divmod(number - 1, 26)
        out = chr(ord("a") + rest) + out
    return out


def _check_takes(takes: Iterable[Take]) -> None:
    """Unique ids; every parent and replay source is the root or an earlier take (so the tree has no cycles)."""

    seen: set[str] = set()
    for take in takes:
        if take.take_id in seen:
            raise StoryboardTreeError(f"Take id {take.take_id!r} is used twice.")
        if take.parent_id != ROOT_PARENT and take.parent_id not in seen:
            raise StoryboardTreeError(
                f"Take {take.take_id!r} names a parent that is not an earlier take."
            )
        if take.replay_of is not None and take.replay_of not in seen:
            raise StoryboardTreeError(
                f"Take {take.take_id!r} replays a take that is not an earlier take."
            )
        seen.add(take.take_id)


@dataclass(frozen=True, slots=True)
class StoryboardTree:
    storyboard_id: str
    title: str
    revision: int
    created_at: str
    updated_at: str
    root: TreeRoot
    takes: tuple[Take, ...]

    @classmethod
    def new(cls, title: str, root: TreeRoot) -> StoryboardTree:
        now = timestamp()
        return cls(uuid4().hex, _title(title), 0, now, now, root, ())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TREE_SCHEMA,
            "storyboard_id": self.storyboard_id,
            "title": self.title,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "root": self.root.to_dict(),
            "takes": [take.to_dict() for take in self.takes],
        }

    @classmethod
    def from_dict(cls, data: Any) -> StoryboardTree:
        if not isinstance(data, dict) or data.get("schema") != TREE_SCHEMA:
            found = data.get("schema") if isinstance(data, dict) else None
            raise StoryboardTreeError(
                f"Unsupported storyboard schema {found!r}; no data rewritten."
            )
        raw = _fields(data, set(cls.__dataclass_fields__) | {"schema"}, "storyboard")
        if type(raw["revision"]) is not int or raw["revision"] < 0:
            raise StoryboardTreeError("Storyboard revision must be a non-negative integer.")
        raw_takes = raw["takes"]
        if not isinstance(raw_takes, list):
            raise StoryboardTreeError("Storyboard takes must be a list.")
        takes = tuple(Take.from_dict(item) for item in raw_takes)
        _check_takes(takes)
        return cls(
            storyboard_id=check_storyboard_id(raw["storyboard_id"]),
            title=_title(raw["title"]),
            revision=raw["revision"],
            created_at=_stamp(raw["created_at"], "created_at"),
            updated_at=_stamp(raw["updated_at"], "updated_at"),
            root=TreeRoot.from_dict(raw["root"]),
            takes=takes,
        )

    def _take(self, take_id: str) -> Take:
        for take in self.takes:
            if take.take_id == take_id:
                return take
        raise StoryboardTreeError(f"Unknown take {take_id!r}.")

    def children(self, parent_id: str) -> tuple[Take, ...]:
        """Children of one parent in creation order (the order of ``takes``)."""

        return tuple(take for take in self.takes if take.parent_id == parent_id)

    def depth(self, take_id: str) -> int:
        """0 for the root, 1 for a child of the root, and so on."""

        depth = 0
        current = take_id
        while current != ROOT_PARENT:
            current = self._take(current).parent_id
            depth += 1
        return depth

    def label(self, take_id: str) -> str:
        """``A`` for the root; children alternate digits and letters by depth (``A1``, ``A1a``, ``A1a1``)."""

        if take_id == ROOT_PARENT:
            return "A"
        take = self._take(take_id)
        number = [c.take_id for c in self.children(take.parent_id)].index(take_id) + 1
        suffix = str(number) if self.depth(take_id) % 2 else _letters(number)
        return self.label(take.parent_id) + suffix

    def with_take(self, take: Take) -> StoryboardTree:
        takes = (*self.takes, take)
        _check_takes(takes)
        return replace(self, takes=takes)

    def with_mark(self, take_id: str, mark: str) -> StoryboardTree:
        if mark not in _MARKS:
            raise StoryboardTreeError("A take mark is none, kept or dropped.")
        target = self._take(take_id)
        return self._replacing(
            target, replace(target, mark=cast(Literal["none", "kept", "dropped"], mark))
        )

    def with_attempt(self, take_id: str, job_id: str) -> StoryboardTree:
        target = self._take(take_id)
        job = _job_id(job_id)
        if job in target.attempts:
            return self
        return self._replacing(target, replace(target, attempts=(*target.attempts, job)))

    def _replacing(self, old: Take, new: Take) -> StoryboardTree:
        return replace(self, takes=tuple(new if t is old else t for t in self.takes))

    def without_takes(self, take_ids: Iterable[str]) -> StoryboardTree:
        """Remove takes; refuses to orphan a child or a replay link that would be left behind."""

        gone = set(take_ids)
        for take_id in gone:
            self._take(take_id)
        kept = tuple(take for take in self.takes if take.take_id not in gone)
        for take in kept:
            if take.parent_id in gone or take.replay_of in gone:
                raise StoryboardTreeError(
                    f"Take {take.take_id!r} still depends on a take being removed; remove it too."
                )
        return replace(self, takes=kept)

    def renamed(self, title: str) -> StoryboardTree:
        return replace(self, title=_title(title))

    def duplicate(self, title: str) -> StoryboardTree:
        now = timestamp()
        return replace(
            self,
            storyboard_id=uuid4().hex,
            title=_title(title),
            revision=0,
            created_at=now,
            updated_at=now,
        )


def _title(value: Any) -> str:
    text = _text(value, "Storyboard title", _MAX_TITLE)
    if not text.strip():
        raise StoryboardTreeError("A storyboard needs a title.")
    return text


__all__ = [
    "check_storyboard_id",
    "MAX_ROWS",
    "ROOT_PARENT",
    "TREE_SCHEMA",
    "StoryboardTree",
    "StoryboardTreeError",
    "Take",
    "TreeRoot",
]
