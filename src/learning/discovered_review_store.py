# Subsystem: Learning
# Role: Durable store for discovered-review experiments and scan index.

"""DiscoveredReviewStore — persists groups, items, and the scan index.

Directory layout under root:
    discovered_experiments/
        <group_id>/
            meta.json          — group metadata (no items)
            items.json         — list of DiscoveredReviewItem dicts
            review_state.json  — per-item rating state (mirrors items ratings)
        scan_index.json        — OutputScanIndexEntry records keyed by artifact_path
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.curation.curation_manifest import build_selection_event_block
from src.curation.models import SelectionEvent
from src.learning.discovered_review_models import (
    RATING_UNRATED,
    STATUS_CLOSED,
    STATUS_IGNORED,
    STATUS_IN_REVIEW,
    STATUS_WAITING_REVIEW,
    VALID_STATUSES,
    DiscoveredReviewExperiment,
    DiscoveredReviewHandle,
    DiscoveredReviewItem,
    OutputScanIndexEntry,
    _utc_now_iso,
)

logger = logging.getLogger(__name__)

_SCAN_INDEX_FILE = "scan_index.json"
_GROUPS_DIR = "discovered_experiments"
_SELECTION_EVENTS_FILE = "selection_events.json"


class DiscoveredReviewStore:
    """Persist and query discovered-review experiments.

    All paths are rooted at *root* which defaults to ``data/learning``.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._groups_root = self.root / _GROUPS_DIR
        self._scan_index_path = self._groups_root / _SCAN_INDEX_FILE
        self._groups_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Group CRUD
    # ------------------------------------------------------------------

    def save_group(self, experiment: DiscoveredReviewExperiment) -> None:
        """Persist meta, items, and review_state for *experiment*."""
        group_dir = self._groups_root / experiment.group_id
        group_dir.mkdir(parents=True, exist_ok=True)

        experiment.updated_at = _utc_now_iso()
        self._write_json(group_dir / "meta.json", experiment.to_meta_dict())
        self._write_json(group_dir / "items.json", experiment.to_items_list())

        review_state = {
            item.item_id: {
                "rating": item.rating,
                "rating_notes": item.rating_notes,
                "rated_at": item.rated_at,
            }
            for item in experiment.items
        }
        self._write_json(group_dir / "review_state.json", review_state)

    def load_group(self, group_id: str) -> DiscoveredReviewExperiment | None:
        """Load the full experiment or return *None* if it doesn't exist."""
        group_dir = self._groups_root / group_id
        meta_path = group_dir / "meta.json"
        items_path = group_dir / "items.json"
        if not meta_path.exists():
            return None
        meta = self._read_json(meta_path) or {}
        items = self._read_json(items_path) or []

        # Merge persisted review state into items
        review_state: dict[str, Any] = self._read_json(group_dir / "review_state.json") or {}
        for item_dict in items:
            iid = str(item_dict.get("item_id") or "")
            state = review_state.get(iid)
            if state:
                item_dict["rating"] = state.get("rating", RATING_UNRATED)
                item_dict["rating_notes"] = state.get("rating_notes", "")
                item_dict["rated_at"] = state.get("rated_at", "")

        return DiscoveredReviewExperiment.from_meta_and_items(meta, items)

    def delete_group(self, group_id: str) -> bool:
        """Remove all files for *group_id*. Returns True if anything was removed."""
        import shutil
        group_dir = self._groups_root / group_id
        if group_dir.exists():
            shutil.rmtree(group_dir, ignore_errors=True)
            return True
        return False

    # ------------------------------------------------------------------
    # Status lifecycle
    # ------------------------------------------------------------------

    def transition_status(self, group_id: str, new_status: str) -> bool:
        """Change group status to *new_status*. Returns True on success."""
        if new_status not in VALID_STATUSES:
            logger.warning("Invalid status %r for group %s", new_status, group_id)
            return False
        exp = self.load_group(group_id)
        if exp is None:
            return False
        exp.transition_status(new_status)
        self.save_group(exp)
        return True

    def close_group(self, group_id: str) -> bool:
        return self.transition_status(group_id, STATUS_CLOSED)

    def ignore_group(self, group_id: str) -> bool:
        return self.transition_status(group_id, STATUS_IGNORED)

    def reopen_group(self, group_id: str) -> bool:
        return self.transition_status(group_id, STATUS_WAITING_REVIEW)

    def begin_review(self, group_id: str) -> bool:
        return self.transition_status(group_id, STATUS_IN_REVIEW)

    # ------------------------------------------------------------------
    # Per-item rating
    # ------------------------------------------------------------------

    def save_item_rating(
        self,
        group_id: str,
        item_id: str,
        rating: int,
        notes: str = "",
    ) -> bool:
        """Persist rating for a single item. Returns True on success."""
        exp = self.load_group(group_id)
        if exp is None:
            return False
        for item in exp.items:
            if item.item_id == item_id:
                item.rating = rating
                item.rating_notes = notes
                item.rated_at = _utc_now_iso()
                self.save_group(exp)
                return True
        return False

    def save_item_extra_fields(
        self,
        group_id: str,
        item_id: str,
        extra_fields: dict[str, Any],
    ) -> bool:
        """Merge extra_fields into a single stored item."""
        exp = self.load_group(group_id)
        if exp is None:
            return False
        for item in exp.items:
            if item.item_id != item_id:
                continue
            merged = dict(item.extra_fields or {})
            for key, value in (extra_fields or {}).items():
                if value is None:
                    merged.pop(str(key), None)
                else:
                    merged[str(key)] = value
            item.extra_fields = merged
            self.save_group(exp)
            return True
        return False

    # ------------------------------------------------------------------
    # Staged-curation selection events
    # ------------------------------------------------------------------

    def load_selection_events(self, group_id: str) -> list[SelectionEvent]:
        """Return staged-curation selection events for *group_id*."""
        group_dir = self._groups_root / group_id
        raw = self._read_json(group_dir / _SELECTION_EVENTS_FILE) or []
        events: list[SelectionEvent] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            payload = dict(entry)
            payload.pop("schema", None)
            try:
                events.append(SelectionEvent.from_dict(payload))
            except Exception as exc:
                logger.warning("Skipping corrupt selection event for %s: %s", group_id, exc)
        return events

    def append_selection_event(self, group_id: str, event: SelectionEvent) -> bool:
        """Append a staged-curation selection event for *group_id*."""
        group_dir = self._groups_root / group_id
        if not (group_dir / "meta.json").exists():
            return False
        existing = self._read_json(group_dir / _SELECTION_EVENTS_FILE) or []
        if not isinstance(existing, list):
            existing = []
        existing.append(build_selection_event_block(event))
        self._write_json(group_dir / _SELECTION_EVENTS_FILE, existing)
        return True

    # ------------------------------------------------------------------
    # Handle listing
    # ------------------------------------------------------------------

    def list_handles(
        self,
        status: str | None = None,
    ) -> list[DiscoveredReviewHandle]:
        """Return lightweight handles, optionally filtered by *status*.

        Results are sorted by ``created_at`` ascending (oldest first).
        """
        handles: list[DiscoveredReviewHandle] = []
        for group_dir in sorted(self._groups_root.iterdir()):
            if not group_dir.is_dir():
                continue
            meta_path = group_dir / "meta.json"
            if not meta_path.exists():
                continue
            meta = self._read_json(meta_path) or {}
            try:
                handle = DiscoveredReviewHandle(
                    group_id=str(meta.get("group_id") or group_dir.name),
                    display_name=str(meta.get("display_name") or ""),
                    stage=str(meta.get("stage") or ""),
                    status=str(meta.get("status") or STATUS_WAITING_REVIEW),
                    item_count=self._count_items(group_dir),
                    varying_fields=tuple(meta.get("varying_fields") or []),
                    created_at=str(meta.get("created_at") or ""),
                    updated_at=str(meta.get("updated_at") or ""),
                )
            except Exception as exc:
                logger.warning("Skipping corrupt group dir %s: %s", group_dir, exc)
                continue
            if status is None or handle.status == status:
                handles.append(handle)
        return handles

    def list_handles_by_status(
        self, statuses: list[str]
    ) -> list[DiscoveredReviewHandle]:
        """Return handles whose status is in *statuses*."""
        desired = set(statuses)
        return [h for h in self.list_handles() if h.status in desired]

    # ------------------------------------------------------------------
    # Scan index
    # ------------------------------------------------------------------

    def load_scan_index(self) -> dict[str, OutputScanIndexEntry]:
        """Return the scan index keyed by artifact_path."""
        raw = self._read_json(self._scan_index_path) or {}
        result: dict[str, OutputScanIndexEntry] = {}
        for path_str, entry_dict in raw.items():
            try:
                result[path_str] = OutputScanIndexEntry.from_dict(entry_dict)
            except Exception as exc:
                logger.warning("Skipping corrupt scan index entry %s: %s", path_str, exc)
        return result

    def save_scan_index(self, index: dict[str, OutputScanIndexEntry]) -> None:
        """Persist the full scan index."""
        self._write_json(
            self._scan_index_path,
            {k: v.to_dict() for k, v in index.items()},
        )

    def update_scan_index_entries(
        self, entries: list[OutputScanIndexEntry]
    ) -> None:
        """Merge *entries* into the existing scan index."""
        index = self.load_scan_index()
        for entry in entries:
            index[entry.artifact_path] = entry
        self.save_scan_index(index)

    def is_artifact_in_index(self, artifact_path: str) -> bool:
        index = self.load_scan_index()
        return artifact_path in index

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _count_items(self, group_dir: Path) -> int:
        items_path = group_dir / "items.json"
        if not items_path.exists():
            return 0
        data = self._read_json(items_path)
        return len(data) if isinstance(data, list) else 0

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return None
