"""The image a job's output was made from, for the phone's compare view of desk reprocess work (PHONE-FAST).

The job is named by the image's own embedded job id, and its recorded input images come from the job repository's
immutable snapshot (read only; nothing is rewritten). A job with several inputs is matched to one by following the run
folder's stage manifests from the output back to a recorded input. Only paths on this PC are read; what leaves it is
the original's id and digest. Blocking work for the sync worker, never Tk.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: ``None``: not made from an input image. ``""``: made from one that cannot be told. Otherwise the input's path.
InputOf = Callable[[Path], str | None]

_MANIFEST_LIMIT = 8 * 1024 * 1024
_MOST_STAGES = 8


def _normal(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _stage_inputs(folder: Path) -> dict[str, str]:
    """``output -> input`` for every image stage a run folder's manifests record."""

    found: dict[str, str] = {}
    for manifest in sorted((folder / "manifests").glob("*.json")):
        try:
            if manifest.stat().st_size > _MANIFEST_LIMIT:
                continue
            payload = json.loads(manifest.read_bytes())
        except (OSError, ValueError, RecursionError):
            continue
        if not isinstance(payload, Mapping):
            continue
        output, source = payload.get("path"), payload.get("input_image")
        if isinstance(output, str) and isinstance(source, str) and output and source:
            found[_normal(output)] = source
    return found


def _chosen(path: Path, inputs: list[str]) -> str:
    """Which of several recorded inputs ``path`` was made from, ``""`` when the manifests do not say."""

    recorded = {_normal(value): value for value in inputs}
    stages = _stage_inputs(path.parent)
    current = _normal(path)
    for _ in range(_MOST_STAGES):
        source = stages.get(current)
        if source is None:
            return ""
        current = _normal(source)
        if current in recorded:
            return recorded[current]
    return ""


def job_input_reader(repository: Any, *, job_id_of: Callable[[Path], str] | None = None) -> InputOf:
    """Read an output image's input from the job that wrote it. Any failure means none: lineage is extra and must
    never hold publishing back."""

    def read(path: Path) -> str | None:
        from src.review.review_evidence import image_source_job
        from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

        try:
            job_id = (job_id_of or image_source_job)(path)
            entry = repository.get_job(job_id) if job_id else None
            record = normalized_job_from_snapshot(getattr(entry, "snapshot", None) or {})
            inputs = [str(value) for value in getattr(record, "input_image_paths", ()) or ()]
            if not inputs or _normal(path) in {_normal(value) for value in inputs}:
                return None  # no input, or a stage that passed its input through unchanged
            return inputs[0] if len(inputs) == 1 else _chosen(path, inputs)
        except Exception:  # noqa: BLE001
            log.debug("Review gateway publish could not read an item's input image")
            return None

    return read
