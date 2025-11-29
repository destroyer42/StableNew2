from __future__ import annotations

from typing import List

from src.gui.models.prompt_metadata import PromptMetadata


def build_prompt_variants(prompt_text: str, metadata: PromptMetadata | None, mode: str, max_variants: int) -> List[str]:
    """
    Very lightweight variant builder.

    - When mode == "off": returns the base prompt only.
    - Otherwise, generates up to max_variants prompts by simple suffixing,
      using matrix_count as a hint when available.
    """
    base = prompt_text or ""
    if mode == "off":
        return [base]

    count_hint = metadata.matrix_count if metadata else 0
    variant_count = min(max(max_variants, 1), 20)
    if count_hint > 0:
        variant_count = min(variant_count, count_hint)

    variants: list[str] = []
    for i in range(variant_count):
        suffix = f" [variant {i+1}]" if variant_count > 1 else ""
        variants.append(f"{base}{suffix}")
    return variants or [base]

