"""Bounded, source-bound observations and advisory choices for guided Review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.review.assist.contracts import SourceIdentity

MAX_FINDINGS = 24
MAX_OBSERVATION = 500
CORRECTION_KEY = "guided_correction"


class Category(StrEnum):
    FACE = "Face"
    HANDS = "Hands"
    ANATOMY = "Anatomy"
    COMPOSITION = "Composition"
    ARTIFACT = "Rendering artifact"
    PROMPT = "Prompt adherence"
    GENERAL = "General / local issue"


class Origin(StrEnum):
    OPERATOR = "Operator observation"
    DETECTOR = "Detector suggestion"
    MODEL = "External model suggestion"


class Certainty(StrEnum):
    UNKNOWN = "Unknown"
    TENTATIVE = "Tentative"
    CLEAR = "Clear to the operator"


class Confirmation(StrEnum):
    UNREVIEWED = "Unreviewed"
    CONFIRMED = "Confirmed"
    REJECTED = "Rejected"
    UNCERTAIN = "Uncertain"


class Action(StrEnum):
    MASK = "Edit mask"
    FACE = "ADetailer face pass"
    HANDS = "ADetailer hand pass"
    REPROCESS = "Reprocess with img2img"
    INSPECT = "Inspect manually"


@dataclass(frozen=True, slots=True)
class Region:
    """Half-open rectangle in stored pixel coordinates, as used by the mask editor."""

    left: int
    top: int
    right: int
    bottom: int

    def validate(self, size: tuple[int, int]) -> None:
        width, height = size
        if any(type(edge) is not int for edge in self.box):
            raise ValueError("Region edges must be whole pixels.")
        if not (0 <= self.left < self.right <= width and 0 <= self.top < self.bottom <= height):
            raise ValueError("The region is empty or outside the image.")

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom


@dataclass(frozen=True, slots=True)
class FindingSource:
    path: Path
    identity: SourceIdentity
    revision: tuple[int, int]


@dataclass(frozen=True, slots=True)
class Advisory:
    action: Action
    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class Finding:
    source: FindingSource
    region: Region | None
    category: Category
    origin: Origin
    observation: str
    certainty: Certainty = Certainty.UNKNOWN
    confirmation: Confirmation = Confirmation.UNREVIEWED
    advice: tuple[Advisory, ...] = ()
    suggestion_label: str = ""
    effectiveness_job_id: str | None = None

    def __post_init__(self) -> None:
        for value, kind in (
            (self.category, Category),
            (self.origin, Origin),
            (self.certainty, Certainty),
            (self.confirmation, Confirmation),
        ):
            if not isinstance(value, kind):
                raise ValueError(
                    "Choose a supported finding category, origin, certainty and confirmation."
                )
        if self.region is not None:
            self.region.validate(self.source.identity.size)
        object.__setattr__(self, "observation", bounded_text(self.observation, MAX_OBSERVATION))
        object.__setattr__(self, "suggestion_label", bounded_text(self.suggestion_label, 220))
        if self.confirmation is Confirmation.CONFIRMED and not self.observation:
            raise ValueError("Describe the visible issue before confirming it.")


def correction_context(
    source: FindingSource, category: Category, region: Region | None, action: Action
) -> dict[str, Any]:
    """Job provenance may carry authored action and geometry. Observation text stays in Review."""

    if region is not None:
        region.validate(source.identity.size)
    return {
        "schema": "stablenew.guided-correction.v1",
        "action": action.value,
        "category": category.value,
        "region": list(region.box) if region else None,
        "source_size": list(source.identity.size),
    }


def bounded_text(text: str, limit: int) -> str:
    """Keep prose and remove display controls from imported evidence."""

    return re.sub(
        r"[^\S ]+|[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", " ", text[:limit]
    ).strip()
