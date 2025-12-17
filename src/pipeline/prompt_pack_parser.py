from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

EMBEDDING_TAG_RE = re.compile(r"<embedding:([^>]+)>")
LORA_TAG_RE = re.compile(r"<lora:([^:>]+):([^>]+)>")
MATRIX_TOKEN_RE = re.compile(r"\[\[([a-zA-Z0-9_]+)\]\]")


@dataclass(frozen=True)
class PackRow:
    embeddings: tuple[str, ...]
    quality_line: str
    subject_template: str
    lora_tags: tuple[tuple[str, float], ...]
    negative_embeddings: tuple[str, ...]
    negative_phrases: tuple[str, ...]


def _parse_line_embeddings(line: str) -> list[str]:
    return [match.group(1) for match in EMBEDDING_TAG_RE.finditer(line)]


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


def _split_negative_line(line: str) -> tuple[list[str], list[str]]:
    embeddings = [match.group(1) for match in EMBEDDING_TAG_RE.finditer(line)]
    removed = EMBEDDING_TAG_RE.sub("", line)
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
        embeddings: list[str] = []
        quality_line = ""
        subject_template = ""
        lora_tags: list[tuple[str, float]] = []
        negative_embeddings: list[str] = []
        negative_phrases: list[str] = []
        for index, line in enumerate(lines):
            if index == 0:
                embeddings.extend(_parse_line_embeddings(line))
            elif index == 1:
                quality_line = line
            elif index == 2:
                subject_template = line
            elif index == 3:
                lora_tags.extend(_parse_lora_tags(line))
            elif line.startswith("neg:"):
                emb, phrases = _split_negative_line(line)
                negative_embeddings.extend(emb)
                negative_phrases.extend(phrases)
            else:
                # Extra lines appended to quality if unexpected
                if not quality_line:
                    quality_line = line
                else:
                    subject_template = f"{subject_template} {line}"
        if subject_template and quality_line:
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
