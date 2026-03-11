# Subsystem: Learning
# Role: Data models for discovered-review experiments (post-execution historical review).

"""Discovered-review group and item models.

These models are intentionally separate from LearningExperiment — they represent
inferred comparison groups from historical outputs, not user-designed sweeps.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DISCOVERED_REVIEW_SCHEMA_VERSION = "1.0"

# Status lifecycle
STATUS_WAITING_REVIEW = "waiting_review"
STATUS_IN_REVIEW = "in_review"
STATUS_CLOSED = "closed"
STATUS_IGNORED = "ignored"

VALID_STATUSES = frozenset(
    {STATUS_WAITING_REVIEW, STATUS_IN_REVIEW, STATUS_CLOSED, STATUS_IGNORED}
)

# Review item ratings
RATING_UNRATED = 0
RATING_MIN = 1
RATING_MAX = 5


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class DiscoveredReviewItem:
    """One artifact within a discovered comparison group.

    Each item corresponds to a single image in the output tree, scanned
    from a manifest or embedded metadata.
    """

    item_id: str
    artifact_path: str           # Absolute/relative path to the image
    manifest_path: str = ""      # Path to the originating manifest (if any)
    stage: str = ""
    model: str = ""
    sampler: str = ""
    scheduler: str = ""
    steps: int = 0
    cfg_scale: float = 0.0
    seed: int = -1
    positive_prompt: str = ""
    negative_prompt: str = ""
    width: int = 0
    height: int = 0
    extra_fields: dict[str, Any] = field(default_factory=dict)  # Varying fields keyed here
    rating: int = RATING_UNRATED
    rating_notes: str = ""
    rated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "artifact_path": self.artifact_path,
            "manifest_path": self.manifest_path,
            "stage": self.stage,
            "model": self.model,
            "sampler": self.sampler,
            "scheduler": self.scheduler,
            "steps": self.steps,
            "cfg_scale": self.cfg_scale,
            "seed": self.seed,
            "positive_prompt": self.positive_prompt,
            "negative_prompt": self.negative_prompt,
            "width": self.width,
            "height": self.height,
            "extra_fields": dict(self.extra_fields),
            "rating": self.rating,
            "rating_notes": self.rating_notes,
            "rated_at": self.rated_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> DiscoveredReviewItem:
        return DiscoveredReviewItem(
            item_id=str(d.get("item_id") or ""),
            artifact_path=str(d.get("artifact_path") or ""),
            manifest_path=str(d.get("manifest_path") or ""),
            stage=str(d.get("stage") or ""),
            model=str(d.get("model") or ""),
            sampler=str(d.get("sampler") or ""),
            scheduler=str(d.get("scheduler") or ""),
            steps=int(d.get("steps") or 0),
            cfg_scale=float(d.get("cfg_scale") or 0.0),
            seed=int(d.get("seed") or -1),
            positive_prompt=str(d.get("positive_prompt") or ""),
            negative_prompt=str(d.get("negative_prompt") or ""),
            width=int(d.get("width") or 0),
            height=int(d.get("height") or 0),
            extra_fields=dict(d.get("extra_fields") or {}),
            rating=int(d.get("rating") or RATING_UNRATED),
            rating_notes=str(d.get("rating_notes") or ""),
            rated_at=str(d.get("rated_at") or ""),
        )


@dataclass
class DiscoveredReviewExperiment:
    """A group of comparable artifacts identified by the output scanner.

    An experiment becomes eligible when it has >= 3 artifacts with at least
    one meaningfully varying parameter beyond seed.
    """

    group_id: str
    display_name: str
    stage: str
    prompt_hash: str             # Hash of normalized positive prompt
    input_lineage_key: str = ""  # Hash of input-image lineage (empty for txt2img)
    status: str = STATUS_WAITING_REVIEW
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    items: list[DiscoveredReviewItem] = field(default_factory=list)
    varying_fields: list[str] = field(default_factory=list)  # Which params vary
    scan_source_dirs: list[str] = field(default_factory=list)
    schema_version: str = DISCOVERED_REVIEW_SCHEMA_VERSION
    notes: str = ""

    def validate_status(self) -> bool:
        return self.status in VALID_STATUSES

    def transition_status(self, new_status: str) -> None:
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {new_status!r}")
        self.status = new_status
        self.updated_at = _utc_now_iso()

    def is_fully_rated(self) -> bool:
        return bool(self.items) and all(
            i.rating > RATING_UNRATED for i in self.items
        )

    def to_meta_dict(self) -> dict[str, Any]:
        """Serialise non-item fields."""
        return {
            "group_id": self.group_id,
            "display_name": self.display_name,
            "stage": self.stage,
            "prompt_hash": self.prompt_hash,
            "input_lineage_key": self.input_lineage_key,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "varying_fields": list(self.varying_fields),
            "scan_source_dirs": list(self.scan_source_dirs),
            "schema_version": self.schema_version,
            "notes": self.notes,
        }

    def to_items_list(self) -> list[dict[str, Any]]:
        return [i.to_dict() for i in self.items]

    @staticmethod
    def from_meta_and_items(
        meta: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> DiscoveredReviewExperiment:
        exp = DiscoveredReviewExperiment(
            group_id=str(meta.get("group_id") or ""),
            display_name=str(meta.get("display_name") or ""),
            stage=str(meta.get("stage") or ""),
            prompt_hash=str(meta.get("prompt_hash") or ""),
            input_lineage_key=str(meta.get("input_lineage_key") or ""),
            status=str(meta.get("status") or STATUS_WAITING_REVIEW),
            created_at=str(meta.get("created_at") or _utc_now_iso()),
            updated_at=str(meta.get("updated_at") or _utc_now_iso()),
            varying_fields=list(meta.get("varying_fields") or []),
            scan_source_dirs=list(meta.get("scan_source_dirs") or []),
            schema_version=str(meta.get("schema_version") or DISCOVERED_REVIEW_SCHEMA_VERSION),
            notes=str(meta.get("notes") or ""),
        )
        exp.items = [DiscoveredReviewItem.from_dict(i) for i in (items or [])]
        return exp


@dataclass(frozen=True)
class DiscoveredReviewHandle:
    """Lightweight reference suitable for inbox listing."""

    group_id: str
    display_name: str
    stage: str
    status: str
    item_count: int
    varying_fields: tuple[str, ...]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "display_name": self.display_name,
            "stage": self.stage,
            "status": self.status,
            "item_count": self.item_count,
            "varying_fields": list(self.varying_fields),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> DiscoveredReviewHandle:
        return DiscoveredReviewHandle(
            group_id=str(d.get("group_id") or ""),
            display_name=str(d.get("display_name") or ""),
            stage=str(d.get("stage") or ""),
            status=str(d.get("status") or STATUS_WAITING_REVIEW),
            item_count=int(d.get("item_count") or 0),
            varying_fields=tuple(d.get("varying_fields") or []),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
        )


@dataclass
class OutputScanIndexEntry:
    """Tracks a single scanned artifact to enable incremental rescans."""

    artifact_path: str
    scan_key: str          # Stable hash of artifact content or metadata
    scanned_at: str
    group_id: str = ""     # Which group this was assigned to (empty if ineligible)
    eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "scan_key": self.scan_key,
            "scanned_at": self.scanned_at,
            "group_id": self.group_id,
            "eligible": self.eligible,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> OutputScanIndexEntry:
        return OutputScanIndexEntry(
            artifact_path=str(d.get("artifact_path") or ""),
            scan_key=str(d.get("scan_key") or ""),
            scanned_at=str(d.get("scanned_at") or ""),
            group_id=str(d.get("group_id") or ""),
            eligible=bool(d.get("eligible", False)),
        )
