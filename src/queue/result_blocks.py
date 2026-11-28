"""Store each prompt-optimizer record of a job result once, by hash (KEEP-SPACE, forward only).

A job result carries the same ``prompt_optimizer_v3`` record several times (the variant, the replay descriptor, the
diagnostics descriptor and its replay copy). When ``JobRepository`` writes a result, every copy becomes a reference and
the body is stored once in its ``result_blocks`` table, in the same transaction; reading puts the body back, so callers
see the result they stored. Rows written before this keep their embedded records and read as they are.

The pattern is LEARN-SNAPSHOT-914's: content-addressed by the SHA-256 of the canonical JSON, insert-or-ignore, verified
on every read. Only ``JobRepository`` uses this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Final

BLOCK_KEY: Final = "prompt_optimizer_v3"
REFERENCE_KEY: Final = "$stored_block_sha256"
#: A stored result without this text refers to nothing, so reading it costs nothing extra.
REFERENCE_MARKER: Final = f'"{REFERENCE_KEY}"'
#: Records shorter than this are not worth a reference and a row.
MIN_BLOCK_CHARS: Final = 256


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def externalize(result: Any) -> tuple[Any, dict[str, str]]:
    """A copy of ``result`` with each record replaced by its reference, and the bodies to store, by hash."""

    bodies: dict[str, str] = {}

    def visit(value: Any, key: Any) -> Any:
        if isinstance(value, dict):
            copied: Any = {name: visit(item, name) for name, item in value.items()}
        elif isinstance(value, (list, tuple)):
            return [visit(item, None) for item in value]
        else:
            return value
        if key != BLOCK_KEY:
            return copied
        body = _dumps(copied)
        if len(body) < MIN_BLOCK_CHARS:
            return copied
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        bodies[digest] = body
        return {REFERENCE_KEY: digest}

    return visit(result, None), bodies


def restore(
    result: Any,
    lookup: Callable[[str], str | None],
    on_problem: Callable[[str, str], None],
) -> Any:
    """``result`` with every reference replaced by its stored body.

    A body that is missing or does not hash to its reference is reported to ``on_problem(digest, reason)`` and its
    reference is left in place, so one bad block neither hides the job nor passes for the record.
    """

    cache: dict[str, str | None] = {}

    def body_of(digest: str) -> str | None:
        if digest not in cache:
            body = lookup(digest)
            if body is None:
                on_problem(digest, "is not stored")
            elif hashlib.sha256(body.encode("utf-8")).hexdigest() != digest:
                on_problem(digest, "does not match its SHA-256")
                body = None
            cache[digest] = body
        return cache[digest]

    def visit(value: Any, key: Any) -> Any:
        if isinstance(value, list):
            return [visit(item, None) for item in value]
        if not isinstance(value, dict):
            return value
        if key == BLOCK_KEY and set(value) == {REFERENCE_KEY}:
            body = body_of(str(value[REFERENCE_KEY]))
            return value if body is None else json.loads(body)  # a fresh object for every copy
        return {name: visit(item, name) for name, item in value.items()}

    return visit(result, None)


__all__ = [
    "BLOCK_KEY",
    "MIN_BLOCK_CHARS",
    "REFERENCE_KEY",
    "REFERENCE_MARKER",
    "externalize",
    "restore",
]
