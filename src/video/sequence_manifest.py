"""Sequence manifest builder and writer for multi-segment video.

PR-VIDEO-216: Writes a JSON manifest describing an entire completed (or
partially completed) sequence run. Mirrors the per-job manifest convention
already established by comfy_workflow_backend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.video.sequence_models import VideoSequenceResult

# Schema label stamped into every sequence manifest.
SEQUENCE_MANIFEST_SCHEMA = "stablenew_sequence_manifest_v1"


def build_sequence_manifest(
    result: VideoSequenceResult,
    *,
    sequence_job_dict: dict[str, Any],
    schema: str = SEQUENCE_MANIFEST_SCHEMA,
) -> dict[str, Any]:
    """Return a dict representation of the completed sequence manifest.

    Args:
        result:            The aggregated sequence result to describe.
        sequence_job_dict: The originating ``VideoSequenceJob.to_dict()`` snapshot.
        schema:            Schema label. Defaults to ``SEQUENCE_MANIFEST_SCHEMA``.
    """
    return {
        "schema": schema,
        "sequence_id": result.sequence_id,
        "job_id": result.job_id,
        "total_segments": result.total_segments,
        "completed_segments": result.completed_segments,
        "is_complete": result.is_complete,
        "sequence_job": sequence_job_dict,
        "segment_provenance": [p.to_dict() for p in result.segment_provenance],
        "all_output_paths": list(result.all_output_paths),
        "all_frame_paths": list(result.all_frame_paths),
        "sequence_manifest_path": result.sequence_manifest_path,
    }


def write_sequence_manifest(
    result: VideoSequenceResult,
    manifest_dir: str | Path,
    *,
    sequence_job_dict: dict[str, Any],
) -> Path:
    """Serialize the sequence manifest to disk and return the written path.

    The file is named ``sequence_manifest_{sequence_id}.json`` inside
    *manifest_dir*.  The directory is created if it does not exist.

    The ``result.sequence_manifest_path`` is **not** mutated here; callers
    must assign the returned path themselves so the runner controls state.
    """
    manifest_dir = Path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    safe_id = result.sequence_id.replace("/", "_").replace(":", "_")
    manifest_path = manifest_dir / f"sequence_manifest_{safe_id}.json"

    manifest = build_sequence_manifest(result, sequence_job_dict=sequence_job_dict)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    return manifest_path
