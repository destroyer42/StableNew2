from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class LoraReference:
    name: str
    weight: float | None = None
    start: int | None = None
    end: int | None = None


@dataclass
class EmbeddingReference:
    name: str
    weight: float | None = None
    start: int | None = None
    end: int | None = None


def parse_loras(text: str) -> list[LoraReference]:
    """Parse LoRA references from prompt text."""
    refs: list[LoraReference] = []

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


def parse_embeddings(text: str) -> list[EmbeddingReference]:
    """Parse embedding references from prompt text."""
    refs: list[EmbeddingReference] = []

    weighted_pattern = re.compile(r"\(\s*<embedding:([^>]+)>\s*:\s*([0-9.]+)\s*\)")
    angle_pattern = re.compile(r"<embedding:([^>]+)>")
    working_text = text or ""

    for match in weighted_pattern.finditer(working_text):
        name = match.group(1).strip()
        try:
            weight = float(match.group(2))
        except (TypeError, ValueError):
            weight = None
        refs.append(
            EmbeddingReference(
                name=name,
                weight=weight,
                start=match.start(),
                end=match.end(),
            )
        )

    # Support both <embedding:name> and embedding:name formats
    # Process angle bracket format after stripping weighted matches to avoid duplicates
    stripped_for_angle = weighted_pattern.sub(" ", working_text)
    for match in angle_pattern.finditer(stripped_for_angle):
        name = match.group(1).strip()
        refs.append(
            EmbeddingReference(
                name=name,
                weight=None,
                start=match.start(),
                end=match.end(),
            )
        )

    # Then process colon format, but only when not inside angle brackets
    colon_pattern = re.compile(r"(?<!<)embedding:([^>\s]+)")
    stripped_for_colon = angle_pattern.sub(" ", stripped_for_angle)
    for match in colon_pattern.finditer(stripped_for_colon):
        name = match.group(1).strip()
        refs.append(
            EmbeddingReference(
                name=name,
                weight=None,
                start=match.start(),
                end=match.end(),
            )
        )
    return refs


def parse_prompt_metadata(text: str) -> dict[str, Any]:
    """Return a simple metadata dict for convenience."""
    return {
        "loras": parse_loras(text),
        "embeddings": parse_embeddings(text),
    }
