"""Scan -> group -> persist orchestration with truthful scan-index dispositions.

The scan index is a disposition cache, not a review store.  An artifact is only
recorded there once the scanner has a definitive answer for it:

* invalid manifests and controlled-experiment artifacts (never observational
  evidence) are recorded as ineligible;
* members of an eligible bucket are recorded with their deterministic group id,
  but only after the group is durably saved.

Records in buckets that cannot form a group yet stay unindexed so future
siblings are scanned together with them.  Existing groups are never rewritten and
their members are never backfilled: a persisted item cannot prove it still matches
the current manifest (VAE, denoising strength, clip skip, LoRA and ADetailer model
are not stored), so those artifacts stay reconsiderable until ``Rebuild Scanned
Inbox`` reconciles them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.learning.discovered_grouping import GroupingEngine
from src.learning.discovered_review_store import DiscoveredReviewStore
from src.learning.output_scan_models import ScanRecord
from src.learning.output_scanner import OutputScanner


@dataclass(frozen=True)
class ScanOutcome:
    new_group_count: int
    record_count: int


def apply_scan(
    scanner: OutputScanner,
    store: DiscoveredReviewStore,
    records: list[ScanRecord],
    *,
    is_controlled: Callable[[ScanRecord], bool],
    engine: GroupingEngine | None = None,
) -> ScanOutcome:
    """Classify *records*, persist new groups, and complete the scan index."""

    engine = engine or GroupingEngine()
    new_groups = 0
    observational: list[ScanRecord] = []
    try:
        for record in records:
            if is_controlled(record):
                scanner.mark_group_assignment(record.artifact_path, record.scan_key, "", False)
            else:
                observational.append(record)

        existing_ids = {h.group_id for h in store.list_handles()}
        for assignment in engine.plan(observational, existing_group_ids=existing_ids):
            if assignment.candidate is None:
                continue  # existing group: duplicate suppressed by id, index left untouched
            store.save_group(assignment.candidate)  # index only after durable save
            new_groups += 1
            for record in assignment.records:
                scanner.mark_group_assignment(
                    record.artifact_path, record.scan_key, assignment.group_id, True
                )
    finally:
        store.save_scan_index(scanner.scan_index)
    return ScanOutcome(new_group_count=new_groups, record_count=len(observational))
