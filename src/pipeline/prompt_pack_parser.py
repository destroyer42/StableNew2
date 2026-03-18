from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from src.utils.embedding_prompt_utils import extract_embedding_entries, strip_embedding_entries

LORA_TAG_RE = re.compile(r"<lora:([^:>]+):([^>]+)>")
MATRIX_TOKEN_RE = re.compile(r"\[\[([a-zA-Z0-9_]+)\]\]")


@dataclass(frozen=True)
class PackRow:
    embeddings: tuple[tuple[str, float], ...]
    quality_line: str
    subject_template: str
    lora_tags: tuple[tuple[str, float], ...]
    negative_embeddings: tuple[tuple[str, float], ...]
    negative_phrases: tuple[str, ...]


def _parse_line_embeddings(line: str) -> list[tuple[str, float]]:
    return extract_embedding_entries(line)


def _parse_lora_tags(line: str) -> list[tuple[str, float]]:
    tags: list[tuple[str, float]] = []
    for match in LORA_TAG_RE.finditer(line):
        name = match.group(1)
        weight_text = match.group(2)
        try:
            weight = float(weight_text)
        except ValueError:
            weight = 1.0
        tags.append((name, weight))
    return tags


def _split_negative_line(line: str) -> tuple[list[tuple[str, float]], list[str]]:
    embeddings = extract_embedding_entries(line)
    removed = strip_embedding_entries(line)
    phrases = [
        phrase.strip() for phrase in removed.replace("neg:", "").split(",") if phrase.strip()
    ]
    return embeddings, phrases


def _extract_blocks(content: str) -> Iterable[list[str]]:
    for block in re.split(r"\n\s*\n", content):
        lines = [
            line.strip()
            for line in block.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if lines:
            yield lines


def parse_prompt_pack_text(content: str) -> list[PackRow]:
    rows: list[PackRow] = []
    for lines in _extract_blocks(content):
        embeddings: list[tuple[str, float]] = []
        quality_line = ""
        subject_template = ""
        lora_tags: list[tuple[str, float]] = []
        negative_embeddings: list[tuple[str, float]] = []
        negative_phrases: list[str] = []
        positive_text_lines: list[str] = []
        for line in lines:
            if line.startswith("neg:"):
                emb, phrases = _split_negative_line(line)
                negative_embeddings.extend(emb)
                negative_phrases.extend(phrases)
                continue

            parsed_embeddings = _parse_line_embeddings(line)
            line_without_embeddings = strip_embedding_entries(line).strip()
            if parsed_embeddings and not line_without_embeddings:
                embeddings.extend(parsed_embeddings)
                continue

            parsed_loras = _parse_lora_tags(line)
            line_without_loras = LORA_TAG_RE.sub("", line).strip()
            if parsed_loras and not line_without_loras:
                lora_tags.extend(parsed_loras)
                continue

            positive_text_lines.append(line)

        if positive_text_lines:
            quality_line = positive_text_lines[0]
            subject_template = " ".join(positive_text_lines[1:]).strip()

        if quality_line or subject_template or lora_tags or embeddings:
            rows.append(
                PackRow(
                    embeddings=tuple(embeddings),
                    quality_line=quality_line,
                    subject_template=subject_template,
                    lora_tags=tuple(lora_tags),
                    negative_embeddings=tuple(negative_embeddings),
                    negative_phrases=tuple(negative_phrases),
                )
            )
    return rows
