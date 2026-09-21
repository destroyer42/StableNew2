"""Scan -> group -> persist orchestration with truthful scan-index dispositions.

The scan index is a disposition cache, not a review store.  An artifact is only
recorded there once the scanner has a definitive answer for it:

* invalid manifests and controlled-experiment artifacts (never observational
  evidence) are recorded as ineligible;
* members of an eligible bucket are recorded with their deterministic group id,
  but only after the group is durably saved, or (for a group that already
  exists) when the persisted item still reflects the current manifest data.

Records in buckets that cannot form a group yet stay unindexed so future
siblings are scanned together with them.  Existing groups are never rewritten.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.learning.discovered_grouping import GroupingEngine, item_reflects_record
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
            if assignment.candidate is not None:
                store.save_group(assignment.candidate)  # index only after durable save
                new_groups += 1
                indexable = assignment.records
            else:
                group = store.load_group(assignment.group_id)
                items = {i.artifact_path: i for i in (group.items if group else [])}
                indexable = tuple(
                    r
                    for r in assignment.records
                    if r.artifact_path in items and item_reflects_record(items[r.artifact_path], r)
                )
            for record in indexable:
                scanner.mark_group_assignment(
                    record.artifact_path, record.scan_key, assignment.group_id, True
                )
    finally:
        store.save_scan_index(scanner.scan_index)
    return ScanOutcome(new_group_count=new_groups, record_count=len(observational))
