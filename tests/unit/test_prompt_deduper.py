from __future__ import annotations

from src.prompting.prompt_deduper import dedupe_prompt_chunks


def test_deduper_drops_obvious_duplicates_deterministically() -> None:
    kept, dropped = dedupe_prompt_chunks(
        ["beautiful woman", "(beautiful woman:1.2)", "japanese garden", "beautiful woman"]
    )
    assert kept == ["beautiful woman", "japanese garden"]
    assert dropped == ["(beautiful woman:1.2)", "beautiful woman"]
