"""Operator before/after review of an ADetailer output (PR-REFINE-160), carried by the existing Review feedback record.

No new store: the judgments travel in ``feedback["context"]`` of the existing ``LearningController.save_review_feedback`` call
(``metadata.review_context`` in the Learning record and in the stamped portable review metadata). The overall 1-5 rating the
operator already gives stays separate and is never derived from these judgments.

Only an operator can state that a face or a hand improved. The judgments are post-ADetailer visual assessments *by region*:
face and hand ran in one combined request, so nothing here attributes an effect to an individual pass or scores it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.pipeline.adetailer_effectiveness import VISUAL_OUTCOMES
from src.utils.image_metadata import extract_embedded_metadata

SCHEMA = "stablenew.adetailer-review.v1"
ATTRIBUTION = (
    "post-ADetailer visual assessment by region; face and hand ran in one combined request, "
    "so this is not a causal attribution to an individual pass"
)
OUTCOME_LABELS: dict[str, str] = {name: name.capitalize() for name in VISUAL_OUTCOMES}


@dataclass(frozen=True)
class AdetailerPair:
    """An ADetailer output and the verified image that was sent to ADetailer."""

    output: Path
    source: Path


def resolve_adetailer_pair(image_path: Path | str | None) -> AdetailerPair | None:
    """The ``(source, output)`` pair for an ADetailer output, or ``None`` unless the source is verifiably the stage input.

    Verified means: the embedded metadata names the stage ``adetailer``, its artifact record names an input image, and that
    input is an existing file different from the output itself. Nothing is guessed from file names or neighbors.
    """

    if not image_path:
        return None
    output = Path(image_path)
    result = extract_embedded_metadata(output)
    payload = result.payload if result.status == "ok" and isinstance(result.payload, dict) else None
    if payload is None:
        return None
    manifest = payload.get("stage_manifest")
    stage = (manifest.get("stage") if isinstance(manifest, dict) else None) or payload.get("stage")
    if str(stage or "").strip().lower() != "adetailer":
        return None
    artifact = payload.get("artifact")
    raw = artifact.get("input_image_path") if isinstance(artifact, dict) else None
    if not raw:
        return None
    source = Path(str(raw))
    try:
        if not source.is_file() or not output.is_file() or source.resolve() == output.resolve():
            return None
    except OSError:
        return None
    return AdetailerPair(output=output, source=source)


def load_effectiveness(image_path: Path | str) -> dict[str, Any] | None:
    """The stage's ``adetailer_effectiveness`` record from its manifest, when one sits beside the output (optional context)."""

    image = Path(image_path)
    for folder in (image.parent / "manifests", image.parent.parent / "manifests"):
        candidate = folder / f"{image.stem}.json"
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        record = data.get("adetailer_effectiveness") if isinstance(data, dict) else None
        if isinstance(record, dict):
            return record
    return None


def normalize_outcome(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in VISUAL_OUTCOMES else "unreviewed"


def build_review_context(
    pair: AdetailerPair | None,
    *,
    face: object,
    hands: object,
    note: str = "",
) -> dict[str, Any] | None:
    """The ``feedback["context"]`` fragment for an explicit judgment, or ``None`` when nothing was judged.

    Without a verified pair nothing is recorded: a judgment is never attached to an image whose source is unknown.
    """

    face_outcome, hands_outcome = normalize_outcome(face), normalize_outcome(hands)
    if pair is None or (face_outcome == "unreviewed" and hands_outcome == "unreviewed"):
        return None
    return {
        "adetailer_outcome_review": {
            "schema": SCHEMA,
            "source": "operator_review",
            "face": face_outcome,
            "hands": hands_outcome,
            "note": str(note or "").strip()[:500],
            "attribution": ATTRIBUTION,
            "reviewed_pair": {"input_image": str(pair.source), "output_image": str(pair.output)},
        }
    }


__all__ = [
    "ATTRIBUTION",
    "OUTCOME_LABELS",
    "SCHEMA",
    "AdetailerPair",
    "build_review_context",
    "load_effectiveness",
    "normalize_outcome",
    "resolve_adetailer_pair",
]
