"""Describe stack frames as short ``file:line in function`` strings without reading any source file."""

from __future__ import annotations

from types import FrameType


def describe_frame(frame: FrameType) -> str:
    """``src/pkg/mod.py:42 in func`` for a frame (file name only when the frame is outside ``src``)."""

    code = frame.f_code
    filename = code.co_filename.replace("\\", "/")
    cut = filename.rfind("/src/")
    short = filename[cut + 1 :] if cut >= 0 else filename.rsplit("/", 1)[-1]
    return f"{short}:{frame.f_lineno} in {code.co_name}"


def describe_stack(frame: FrameType | None, *, depth: int = 16) -> tuple[str, ...]:
    """``frame`` and its callers, innermost first, at most ``depth`` entries."""

    lines: list[str] = []
    while frame is not None and len(lines) < depth:
        lines.append(describe_frame(frame))
        frame = frame.f_back
    return tuple(lines)
