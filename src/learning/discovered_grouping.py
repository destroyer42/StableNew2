# Subsystem: Learning
# Role: Groups ScanRecords into eligible discovered-review experiments.

"""Grouping engine for discovered-review candidate selection.

Groups ScanRecords by:
  - stage
  - normalized positive prompt
  - normalized negative prompt
  - input-lineage key (img2img source hash)

Eligibility requires:
  - >= 3 artifacts in the group
  - At least 1 meaningful varying field (seed-only groups are rejected)
"""

from __future__ import annotations

import hashlib
import uuid
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from src.learning.output_scan_models import (
    MEANINGFUL_FIELDS,
    SEED_ONLY_FIELDS,
    ScanRecord,
)
from src.learning.discovered_review_models import (
    DiscoveredReviewExperiment,
    DiscoveredReviewItem,
    STATUS_WAITING_REVIEW,
    _utc_now_iso,
    RATING_UNRATED,
)

MIN_GROUP_SIZE = 3


@dataclass(frozen=True)
class _GroupKey:
    stage: str
    prompt_hash: str
    input_lineage_key: str


def _sha256_short(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _group_key(record: ScanRecord) -> _GroupKey:
    return _GroupKey(
        stage=record.stage or "txt2img",
        prompt_hash=record.prompt_hash,
        input_lineage_key=record.input_lineage_key,
    )


def _find_varying_fields(records: list[ScanRecord]) -> list[str]:
    """Return meaningful field names that vary across *records*.

    Fields in SEED_ONLY_FIELDS are never returned even if they vary.
    """
    if len(records) < 2:
        return []
    varying: list[str] = []
    for field_name in sorted(MEANINGFUL_FIELDS):
        if field_name in SEED_ONLY_FIELDS:
            continue
        values: set[Any] = set()
        for rec in records:
            raw = getattr(rec, field_name, None)
            if raw is None:
                raw = rec.extra_fields.get(field_name)
            values.add(raw)
        if len(values) > 1:
            varying.append(field_name)
    return varying


def _make_group_id(key: _GroupKey) -> str:
    raw = f"{key.stage}|{key.prompt_hash}|{key.input_lineage_key}"
    short = _sha256_short(raw.encode("utf-8"))
    return f"disc-{short}"


def _make_display_name(key: _GroupKey, varying_fields: list[str]) -> str:
    stage = key.stage.upper()
    fields_text = ", ".join(varying_fields) if varying_fields else "unknown"
    return f"{stage} · varying {fields_text}"


def _scan_record_to_item(record: ScanRecord) -> DiscoveredReviewItem:
    return DiscoveredReviewItem(
        item_id=str(uuid.uuid4()),
        artifact_path=record.artifact_path,
        manifest_path=record.manifest_path,
        stage=record.stage,
        model=record.model,
        sampler=record.sampler,
        scheduler=record.scheduler,
        steps=record.steps,
        cfg_scale=record.cfg_scale,
        seed=record.seed,
        positive_prompt=record.positive_prompt,
        negative_prompt=record.negative_prompt,
        width=record.width,
        height=record.height,
        extra_fields=dict(record.extra_fields),
        rating=RATING_UNRATED,
    )


class GroupingEngine:
    """Convert a list of ScanRecords into DiscoveredReviewExperiments.

    This engine is stateless — it processes the supplied records and returns
    new experiment candidates.  The caller is responsible for deduplication
    against the existing store.
    """

    def __init__(self, min_group_size: int = MIN_GROUP_SIZE) -> None:
        self.min_group_size = min_group_size

    def build_candidates(
        self,
        records: list[ScanRecord],
        existing_group_ids: set[str] | None = None,
    ) -> list[DiscoveredReviewExperiment]:
        """Group *records* and return eligible, non-duplicate experiments.

        Parameters
        ----------
        records:
            Normalized ScanRecords from the scanner.
        existing_group_ids:
            IDs already present in the store — these groups will not be re-created.
        """
        if existing_group_ids is None:
            existing_group_ids = set()

        # Deduplicate on dedupe_key within records list
        seen_dedupe: set[str] = set()
        deduped: list[ScanRecord] = []
        for rec in records:
            if rec.dedupe_key and rec.dedupe_key in seen_dedupe:
                continue
            if rec.dedupe_key:
                seen_dedupe.add(rec.dedupe_key)
            deduped.append(rec)

        # Bucket by group key
        buckets: dict[_GroupKey, list[ScanRecord]] = defaultdict(list)
        for rec in deduped:
            key = _group_key(rec)
            buckets[key].append(rec)

        candidates: list[DiscoveredReviewExperiment] = []
        for key, bucket_records in sorted(buckets.items(), key=lambda kv: str(kv[0])):
            if len(bucket_records) < self.min_group_size:
                continue
            varying = _find_varying_fields(bucket_records)
            if not varying:
                # Seed-only or no variation — skip
                continue
            group_id = _make_group_id(key)
            if group_id in existing_group_ids:
                continue
            display_name = _make_display_name(key, varying)
            items = [_scan_record_to_item(r) for r in bucket_records]
            experiment = DiscoveredReviewExperiment(
                group_id=group_id,
                display_name=display_name,
                stage=key.stage,
                prompt_hash=key.prompt_hash,
                input_lineage_key=key.input_lineage_key,
                status=STATUS_WAITING_REVIEW,
                created_at=_utc_now_iso(),
                updated_at=_utc_now_iso(),
                items=items,
                varying_fields=varying,
            )
            candidates.append(experiment)

        return candidates

    def find_varying_fields(self, records: list[ScanRecord]) -> list[str]:
        """Public wrapper for testing."""
        return _find_varying_fields(records)
