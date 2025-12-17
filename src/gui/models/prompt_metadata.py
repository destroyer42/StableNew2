from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.gui.utils.lora_embedding_parser import (
    EmbeddingReference,
    LoraReference,
    parse_embeddings,
    parse_loras,
)

_MATRIX_PATTERN = re.compile(r"\{[^{}]*\|[^{}]*\}")


@dataclass
class PromptMetadata:
    loras: list[LoraReference] = field(default_factory=list)
    embeddings: list[EmbeddingReference] = field(default_factory=list)
    matrix_count: int = 0
    text_length: int = 0
    line_count: int = 0


def build_prompt_metadata(text: str) -> PromptMetadata:
    clean = text or ""
    loras = parse_loras(clean)
    embeds = parse_embeddings(clean)
    matrix_count = len(_MATRIX_PATTERN.findall(clean))
    line_count = len(clean.splitlines()) if clean else 0
    return PromptMetadata(
        loras=loras,
        embeddings=embeds,
        matrix_count=matrix_count,
        text_length=len(clean),
        line_count=line_count,
    )
