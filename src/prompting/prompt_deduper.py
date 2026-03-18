from __future__ import annotations

from typing import List, Tuple

from src.prompting.prompt_normalizer import build_dedupe_key


def dedupe_prompt_chunks(chunks: List[str]) -> Tuple[List[str], List[str]]:
    """
    Returns:
        kept_chunks, dropped_chunks
    """
    kept: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()

    for chunk in chunks:
        text = str(chunk or "").strip()
        if not text:
            continue
        key = build_dedupe_key(text)
        if key and key in seen:
            dropped.append(text)
            continue
        if key:
            seen.add(key)
        kept.append(text)

    if not kept:
        first_non_empty = next((str(chunk or "").strip() for chunk in chunks if str(chunk or "").strip()), "")
        if first_non_empty:
            kept.append(first_non_empty)
            dropped = [item for item in dropped if item != first_non_empty]
    return kept, dropped
