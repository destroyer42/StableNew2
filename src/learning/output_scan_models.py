# Subsystem: Learning
# Role: Canonical normalized scan record for output-scanner artifacts.

"""Scan record models — the canonical normalized representation of one scanned image."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


OUTPUT_SCAN_SCHEMA_VERSION = "1.0"

# Fields that are considered "meaningful" for comparison; seed is excluded.
MEANINGFUL_FIELDS = frozenset(
    {
        "model",
        "vae",
        "sampler",
        "scheduler",
        "steps",
        "cfg_scale",
        "width",
        "height",
        "denoising_strength",
        "clip_skip",
        "lora",
        "adetailer_model",
    }
)

# Fields never counted as "varying" (they are always expected to differ)
SEED_ONLY_FIELDS = frozenset({"seed", "subseed"})


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ScanRecord:
    """Canonical normalized representation of one scanned image artifact.

    This is the intermediate form produced by the scanner.  It is NOT persisted
    directly — it is used as input to the grouping engine and then converted into
    DiscoveredReviewItems.
    """

    artifact_path: str            # Resolved string path
    manifest_path: str = ""       # Originating manifest path (if any)
    stage: str = ""
    model: str = ""
    vae: str = ""
    sampler: str = ""
    scheduler: str = ""
    steps: int = 0
    cfg_scale: float = 0.0
    seed: int = -1
    width: int = 0
    height: int = 0
    positive_prompt: str = ""
    negative_prompt: str = ""
    input_image_path: str = ""    # img2img source
    denoising_strength: float = 0.0
    clip_skip: int = 0
    lora: str = ""
    adetailer_model: str = ""
    extra_fields: dict[str, Any] = field(default_factory=dict)
    scan_source: str = "manifest"  # "manifest" or "embedded"
    scanned_at: str = field(default_factory=_utc_now_iso)
    schema_version: str = OUTPUT_SCAN_SCHEMA_VERSION

    # Derived / computed
    prompt_hash: str = ""   # Set by scanner after normalisation
    input_lineage_key: str = ""  # Set by scanner after normalisation
    dedupe_key: str = ""    # Set by scanner

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ScanRecord:
        return ScanRecord(
            artifact_path=str(d.get("artifact_path") or ""),
            manifest_path=str(d.get("manifest_path") or ""),
            stage=str(d.get("stage") or ""),
            model=str(d.get("model") or ""),
            vae=str(d.get("vae") or ""),
            sampler=str(d.get("sampler") or ""),
            scheduler=str(d.get("scheduler") or ""),
            steps=int(d.get("steps") or 0),
            cfg_scale=float(d.get("cfg_scale") or 0.0),
            seed=int(d.get("seed") or -1),
            width=int(d.get("width") or 0),
            height=int(d.get("height") or 0),
            positive_prompt=str(d.get("positive_prompt") or ""),
            negative_prompt=str(d.get("negative_prompt") or ""),
            input_image_path=str(d.get("input_image_path") or ""),
            denoising_strength=float(d.get("denoising_strength") or 0.0),
            clip_skip=int(d.get("clip_skip") or 0),
            lora=str(d.get("lora") or ""),
            adetailer_model=str(d.get("adetailer_model") or ""),
            extra_fields=dict(d.get("extra_fields") or {}),
            scan_source=str(d.get("scan_source") or "manifest"),
            scanned_at=str(d.get("scanned_at") or _utc_now_iso()),
            schema_version=str(d.get("schema_version") or OUTPUT_SCAN_SCHEMA_VERSION),
            prompt_hash=str(d.get("prompt_hash") or ""),
            input_lineage_key=str(d.get("input_lineage_key") or ""),
            dedupe_key=str(d.get("dedupe_key") or ""),
        )

    def get_meaningful_field_map(self) -> dict[str, Any]:
        """Return only the fields that count as 'meaningful' for comparison."""
        return {
            f: getattr(self, f, None)
            for f in MEANINGFUL_FIELDS
            if hasattr(self, f)
        }
