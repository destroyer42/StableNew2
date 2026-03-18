# Subsystem: Learning
# Role: Scans output manifests and images to produce ScanRecords.

"""OutputScanner — manifest-first artifact scanner.

Scan order:
1. Manifests under ``output/*/manifests/*.json`` (preferred)
2. Fallback to embedded image metadata when no manifest exists

The scanner is incremental: previously indexed artifacts are skipped unless
their scan_key (manifest mtime hash) has changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from src.learning.output_scan_models import ScanRecord, _utc_now_iso
from src.learning.discovered_review_models import OutputScanIndexEntry
from src.utils.image_metadata import (
    extract_embedded_metadata,
    resolve_prompt_fields,
    resolve_model_vae_fields,
)

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def _sha256_short(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _manifest_scan_key(manifest_path: Path) -> str:
    """Stable key for a manifest — hash of its content bytes."""
    try:
        content = manifest_path.read_bytes()
        return _sha256_short(content)
    except Exception:
        return ""


def _normalize_prompt(text: str) -> str:
    """Lowercase, strip, collapse whitespace for grouping comparisons."""
    parts = [p.strip().lower() for p in text.replace("\n", " ").split(",")]
    return ",".join(p for p in parts if p)


def _prompt_hash(positive: str, negative: str) -> str:
    combined = f"{_normalize_prompt(positive)}||{_normalize_prompt(negative)}"
    return _sha256_short(combined.encode("utf-8"))


def _input_lineage_key(input_image_path: str) -> str:
    if not input_image_path:
        return ""
    return _sha256_short(input_image_path.strip().lower().encode("utf-8"))


def _dedupe_key(record: ScanRecord) -> str:
    key_parts = {
        "stage": record.stage,
        "model": record.model,
        "sampler": record.sampler,
        "scheduler": record.scheduler,
        "steps": record.steps,
        "cfg_scale": record.cfg_scale,
        "seed": record.seed,
        "width": record.width,
        "height": record.height,
        "positive_prompt": _normalize_prompt(record.positive_prompt),
        "negative_prompt": _normalize_prompt(record.negative_prompt),
    }
    raw = json.dumps(key_parts, sort_keys=True).encode("utf-8")
    return _sha256_short(raw)


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed to read manifest %s: %s", manifest_path, exc)
        return {}


def _normalize_record(record: ScanRecord) -> ScanRecord:
    record.prompt_hash = _prompt_hash(record.positive_prompt, record.negative_prompt)
    record.input_lineage_key = _input_lineage_key(record.input_image_path)
    record.dedupe_key = _dedupe_key(record)
    return record


def _record_from_manifest(manifest_path: Path, artifact_path: Path) -> ScanRecord | None:
    """Construct a ScanRecord from a manifest JSON.

    Returns None if the manifest is missing required fields or is unparseable.
    """
    data = _read_manifest(manifest_path)
    if not data:
        return None

    # Normalise prompts via existing image_metadata helpers
    positive, negative = resolve_prompt_fields(data)
    model, vae = resolve_model_vae_fields(data)

    # Resolve generation-level fields
    gen = data.get("generation") or {}
    if isinstance(gen, str):
        gen = {}
    stage_manifest = data.get("stage_manifest") or {}
    if isinstance(stage_manifest, str):
        stage_manifest = {}
    artifact = data.get("artifact") or {}
    if isinstance(artifact, str):
        artifact = {}

    def _safe_int(v: Any) -> int:
        try:
            return int(v)
        except Exception:
            return 0

    def _safe_float(v: Any) -> float:
        try:
            return float(v)
        except Exception:
            return 0.0

    def _pick(*sources: Any) -> str:
        for s in sources:
            if s is not None:
                text = str(s).strip()
                if text:
                    return text
        return ""

    stage = _pick(
        stage_manifest.get("stage"),
        data.get("stage"),
        gen.get("stage"),
    ) or "txt2img"
    sampler = _pick(
        stage_manifest.get("sampler_name"),
        gen.get("sampler_name"),
        data.get("sampler_name"),
        gen.get("sampler"),
        data.get("sampler"),
    )
    scheduler = _pick(
        stage_manifest.get("scheduler"),
        gen.get("scheduler"),
        data.get("scheduler"),
    )
    steps = _safe_int(
        stage_manifest.get("steps") or gen.get("steps") or data.get("steps")
    )
    cfg_scale = _safe_float(
        stage_manifest.get("cfg_scale") or gen.get("cfg_scale") or data.get("cfg_scale")
    )
    seed = _safe_int(
        stage_manifest.get("seed") or gen.get("seed") or data.get("seed") or -1
    )
    width = _safe_int(
        stage_manifest.get("width") or gen.get("width") or data.get("width")
    )
    height = _safe_int(
        stage_manifest.get("height") or gen.get("height") or data.get("height")
    )
    input_img = _pick(
        artifact.get("input_image_path"),
        stage_manifest.get("input_image"),
        gen.get("input_image"),
        data.get("input_image"),
    )

    record = ScanRecord(
        artifact_path=str(artifact_path),
        manifest_path=str(manifest_path),
        stage=stage,
        model=model,
        vae=vae,
        sampler=sampler,
        scheduler=scheduler,
        steps=steps,
        cfg_scale=cfg_scale,
        seed=seed,
        width=width,
        height=height,
        positive_prompt=positive,
        negative_prompt=negative,
        input_image_path=input_img,
        scan_source="manifest",
        scanned_at=_utc_now_iso(),
    )
    return _normalize_record(record)


def _record_from_embedded(image_path: Path) -> ScanRecord | None:
    """Fall back to extracting metadata from image PNGInfo/EXIF."""
    result = extract_embedded_metadata(image_path)
    if result.status != "ok" or not result.payload:
        return None
    payload = result.payload
    positive, negative = resolve_prompt_fields(payload)
    model, vae = resolve_model_vae_fields(payload)

    def _safe_int(v: Any) -> int:
        try:
            return int(v)
        except Exception:
            return 0

    def _safe_float(v: Any) -> float:
        try:
            return float(v)
        except Exception:
            return 0.0

    stage = str(payload.get("stage") or "txt2img")
    gen = payload.get("generation") or {}
    record = ScanRecord(
        artifact_path=str(image_path),
        manifest_path="",
        stage=stage,
        model=model,
        vae=vae,
        sampler=str(gen.get("sampler_name") or payload.get("sampler_name") or ""),
        scheduler=str(gen.get("scheduler") or payload.get("scheduler") or ""),
        steps=_safe_int(gen.get("steps") or payload.get("steps")),
        cfg_scale=_safe_float(gen.get("cfg_scale") or payload.get("cfg_scale")),
        seed=_safe_int(gen.get("seed") or payload.get("seed") or -1),
        width=_safe_int(gen.get("width") or payload.get("width")),
        height=_safe_int(gen.get("height") or payload.get("height")),
        positive_prompt=positive,
        negative_prompt=negative,
        scan_source="embedded",
        scanned_at=_utc_now_iso(),
    )
    return _normalize_record(record)


class OutputScanner:
    """Scans an output directory tree for image artifacts.

    Parameters
    ----------
    output_root:
        Root under which to search for ``manifests/`` directories.
    scan_index:
        Existing scan index keyed by artifact_path.  Updated in place.
    """

    MANIFEST_GLOB = "**/manifests/*.json"
    IMAGE_GLOB = "**/*.png"

    def __init__(
        self,
        output_root: Path | str,
        scan_index: dict[str, OutputScanIndexEntry] | None = None,
    ) -> None:
        self.output_root = Path(output_root)
        self.scan_index: dict[str, OutputScanIndexEntry] = scan_index or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_incremental(self) -> list[ScanRecord]:
        """Return new ScanRecords for artifacts not yet in the index."""
        records: list[ScanRecord] = []
        for manifest_path in sorted(self.output_root.glob(self.MANIFEST_GLOB)):
            artifact_path = self._artifact_for_manifest(manifest_path)
            if artifact_path is None:
                continue
            scan_key = _manifest_scan_key(manifest_path)
            key = str(artifact_path)
            if self._already_indexed(key, scan_key):
                continue
            record = _record_from_manifest(manifest_path, artifact_path)
            if record is None:
                self._mark_indexed(key, scan_key, group_id="", eligible=False)
                continue
            records.append(record)
        return records

    def scan_full(self) -> list[ScanRecord]:
        """Return ScanRecords for every artifact regardless of index state."""
        records: list[ScanRecord] = []
        for manifest_path in sorted(self.output_root.glob(self.MANIFEST_GLOB)):
            artifact_path = self._artifact_for_manifest(manifest_path)
            if artifact_path is None:
                continue
            record = _record_from_manifest(manifest_path, artifact_path)
            if record is not None:
                records.append(record)

        # Image-only fallback for files with no matched manifest
        matched_artifacts = {r.artifact_path for r in records}
        for img_path in sorted(self.output_root.glob(self.IMAGE_GLOB)):
            if str(img_path) in matched_artifacts:
                continue
            if img_path.suffix.lower() not in _IMAGE_EXTENSIONS:
                continue
            record = _record_from_embedded(img_path)
            if record is not None:
                records.append(record)

        return records

    def mark_group_assignment(
        self, artifact_path: str, scan_key: str, group_id: str, eligible: bool
    ) -> None:
        """Record which group an artifact was assigned to."""
        self._mark_indexed(artifact_path, scan_key, group_id=group_id, eligible=eligible)

    def get_updated_index(self) -> dict[str, OutputScanIndexEntry]:
        return dict(self.scan_index)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _artifact_for_manifest(self, manifest_path: Path) -> Path | None:
        """Locate the image file corresponding to *manifest_path*.

        Convention: manifests/<stem>.json lives alongside output images,
        typically in the parent directory.  We accept any recognised image
        extension sibling.
        """
        stem = manifest_path.stem
        parent = manifest_path.parent.parent  # one level up from manifests/
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = parent / f"{stem}{ext}"
            if candidate.exists():
                return candidate
        # Also check the manifests dir itself (some layouts keep images there)
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = manifest_path.parent / f"{stem}{ext}"
            if candidate.exists():
                return candidate
        return None

    def _already_indexed(self, artifact_path: str, scan_key: str) -> bool:
        entry = self.scan_index.get(artifact_path)
        if entry is None:
            return False
        return entry.scan_key == scan_key

    def _mark_indexed(
        self,
        artifact_path: str,
        scan_key: str,
        group_id: str,
        eligible: bool,
    ) -> None:
        self.scan_index[artifact_path] = OutputScanIndexEntry(
            artifact_path=artifact_path,
            scan_key=scan_key,
            scanned_at=_utc_now_iso(),
            group_id=group_id,
            eligible=eligible,
        )
