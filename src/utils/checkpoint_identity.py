"""N12: the one canonical checkpoint key, derived at read time from any stored or displayed spelling.

A checkpoint reaches StableNew spelled many ways: a Forge/A1111 ``/sd-models`` title
(``sdxl\\name.safetensors [a1b2c3d4e5]``), an A1111 ``model_name`` (``name``), a full ``filename``, a registry relative
path, a Learning or curation record written from a display name, or a picker label that disambiguates a display-name
collision as ``"{display} [{internal}]"``. Every one of them maps to the same key: the file's base name without any
directory, trailing ``[hash]`` suffix, picker collision wrapper or checkpoint extension, lower-cased.

The key is *name identity*. Two different files with one base name in different folders share a key; a recorded
SHA-256 (Model Comparison, Prompt x Model Matrix, the asset registry) remains the byte identity where one exists.

Stored records are never rewritten: NJR snapshots, history rows and Learning records keep the spelling they were
written with, and readers join them through this key. The key for every name the pre-N12 probe key handled is
unchanged (``tests/utils/test_checkpoint_identity_n12.py`` pins this), so persisted ``model_key`` values still match.
"""

from __future__ import annotations

from typing import Any

#: Checkpoint file extensions removed from the key (compared case-insensitively).
CHECKPOINT_EXTENSIONS: tuple[str, ...] = (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".gguf")


def _split_trailing_group(text: str) -> tuple[str, str] | None:
    """``(before, inner)`` for a final balanced ``[...]`` group, or ``None`` when ``text`` does not end with one."""

    if not text.endswith("]"):
        return None
    depth = 0
    for index in range(len(text) - 1, -1, -1):
        char = text[index]
        if char == "]":
            depth += 1
        elif char == "[":
            depth -= 1
            if depth == 0:
                return text[:index].rstrip(), text[index + 1 : -1].strip()
    return None


def _names_a_file(inner: str) -> bool:
    """Whether a bracketed group is a picker's internal checkpoint name rather than a hash suffix."""

    if "/" in inner or "\\" in inner:
        return True
    head = inner
    while (split := _split_trailing_group(head)) is not None and split[0]:
        head = split[0]
    return head.lower().endswith(CHECKPOINT_EXTENSIONS)


def checkpoint_stem(name: Any) -> str:
    """The case-preserving base name behind :func:`checkpoint_key` (for substring search of stored JSON text)."""

    text = str(name or "").strip()
    while (split := _split_trailing_group(text)) is not None:
        before, inner = split
        if _names_a_file(inner):
            text = inner  # picker collision label: the bracketed internal name is the checkpoint
        elif before:
            text = before  # ``[hash]`` suffix
        else:
            break
    base = text.replace("\\", "/").rsplit("/", 1)[-1].strip()
    lowered = base.lower()
    for ext in CHECKPOINT_EXTENSIONS:
        if lowered.endswith(ext):
            return base[: -len(ext)]
    return base


def checkpoint_key(name: Any) -> str:
    """Canonical checkpoint identity of any title, model name, filename, path, record value or picker label."""

    return checkpoint_stem(name).lower()


def same_checkpoint(left: Any, right: Any) -> bool:
    """Whether two non-empty spellings name the same checkpoint by name."""

    key = checkpoint_key(left)
    return bool(key) and key == checkpoint_key(right)


__all__ = ["CHECKPOINT_EXTENSIONS", "checkpoint_key", "checkpoint_stem", "same_checkpoint"]
