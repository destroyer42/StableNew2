from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class LoraReference:
    name: str
    weight: float | None = None
    start: int | None = None
    end: int | None = None


@dataclass
class EmbeddingReference:
    name: str
    start: int | None = None
    end: int | None = None


def parse_loras(text: str) -> List[LoraReference]:
    """Parse LoRA references from prompt text."""
    refs: List[LoraReference] = []

    # Support both {lora:name:weight} and <lora:name:weight> formats
    brace_pattern = re.compile(r"\{lora:([^:}]+)(?::([0-9.]+))?\}")
    angle_pattern = re.compile(r"<lora:([^:>]+)(?::([0-9.]+))?>")

    for pattern in [brace_pattern, angle_pattern]:
        for match in pattern.finditer(text or ""):
            name = match.group(1).strip()
            weight_raw = match.group(2)
            try:
                weight = float(weight_raw) if weight_raw is not None else None
            except (TypeError, ValueError):
                weight = None
            refs.append(
                LoraReference(
                    name=name,
                    weight=weight,
                    start=match.start(),
                    end=match.end(),
                )
            )
    return refs


def parse_embeddings(text: str) -> List[EmbeddingReference]:
    """Parse embedding references from prompt text."""
    refs: List[EmbeddingReference] = []

    # Support both <embedding:name> and embedding:name formats
    # Process angle bracket format first (more specific)
    angle_pattern = re.compile(r"<embedding:([^>]+)>")
    for match in angle_pattern.finditer(text or ""):
        name = match.group(1).strip()
        refs.append(
            EmbeddingReference(
                name=name,
                start=match.start(),
                end=match.end(),
            )
        )

    # Then process colon format, but only when not inside angle brackets
    colon_pattern = re.compile(r"(?<!<)embedding:([^>\s]+)")
    for match in colon_pattern.finditer(text or ""):
        name = match.group(1).strip()
        refs.append(
            EmbeddingReference(
                name=name,
                start=match.start(),
                end=match.end(),
            )
        )
    return refs


def parse_prompt_metadata(text: str) -> Dict[str, Any]:
    """Return a simple metadata dict for convenience."""
    return {
        "loras": parse_loras(text),
        "embeddings": parse_embeddings(text),
    }
