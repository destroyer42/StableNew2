from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PHOTO_OPTIMIZE_SCHEMA_VERSION = "1.0"


def default_stage_defaults() -> dict[str, bool]:
    return {
        "img2img": True,
        "adetailer": False,
        "upscale": False,
    }


@dataclass
class PhotoOptimizeBaseline:
    prompt: str = ""
    negative_prompt: str = ""
    model: str = ""
    vae: str = ""
    stage_defaults: dict[str, bool] = field(default_factory=default_stage_defaults)
    config: dict[str, Any] = field(default_factory=dict)
    source: str = "manual"
    working_image_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "model": self.model,
            "vae": self.vae,
            "stage_defaults": dict(self.stage_defaults or {}),
            "config": deepcopy(self.config or {}),
            "source": self.source,
            "working_image_path": self.working_image_path,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PhotoOptimizeBaseline":
        data = payload or {}
        return cls(
            prompt=str(data.get("prompt") or ""),
            negative_prompt=str(data.get("negative_prompt") or ""),
            model=str(data.get("model") or ""),
            vae=str(data.get("vae") or ""),
            stage_defaults=dict(data.get("stage_defaults") or default_stage_defaults()),
            config=deepcopy(data.get("config") or {}),
            source=str(data.get("source") or "manual"),
            working_image_path=str(data.get("working_image_path") or ""),
        )


@dataclass
class PhotoOptimizeBaselineSnapshot:
    snapshot_id: str
    created_at: str
    reason: str
    baseline: PhotoOptimizeBaseline

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "reason": self.reason,
            "baseline": self.baseline.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PhotoOptimizeBaselineSnapshot | None":
        if not isinstance(payload, dict):
            return None
        return cls(
            snapshot_id=str(payload.get("snapshot_id") or ""),
            created_at=str(payload.get("created_at") or ""),
            reason=str(payload.get("reason") or ""),
            baseline=PhotoOptimizeBaseline.from_dict(payload.get("baseline") or {}),
        )


@dataclass
class PhotoOptimizeHistoryEntry:
    run_id: str
    created_at: str
    input_image_path: str
    output_paths: list[str] = field(default_factory=list)
    prompt_mode: str = "append"
    prompt_delta: str = ""
    negative_prompt_mode: str = "append"
    negative_prompt_delta: str = ""
    effective_prompt: str = ""
    effective_negative_prompt: str = ""
    stages: list[str] = field(default_factory=list)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    job_ids: list[str] = field(default_factory=list)
    manifest_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "input_image_path": self.input_image_path,
            "output_paths": list(self.output_paths or []),
            "prompt_mode": self.prompt_mode,
            "prompt_delta": self.prompt_delta,
            "negative_prompt_mode": self.negative_prompt_mode,
            "negative_prompt_delta": self.negative_prompt_delta,
            "effective_prompt": self.effective_prompt,
            "effective_negative_prompt": self.effective_negative_prompt,
            "stages": list(self.stages or []),
            "config_snapshot": deepcopy(self.config_snapshot or {}),
            "job_ids": list(self.job_ids or []),
            "manifest_paths": list(self.manifest_paths or []),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PhotoOptimizeHistoryEntry | None":
        if not isinstance(payload, dict):
            return None
        return cls(
            run_id=str(payload.get("run_id") or ""),
            created_at=str(payload.get("created_at") or ""),
            input_image_path=str(payload.get("input_image_path") or ""),
            output_paths=[str(item) for item in payload.get("output_paths") or []],
            prompt_mode=str(payload.get("prompt_mode") or "append"),
            prompt_delta=str(payload.get("prompt_delta") or ""),
            negative_prompt_mode=str(payload.get("negative_prompt_mode") or "append"),
            negative_prompt_delta=str(payload.get("negative_prompt_delta") or ""),
            effective_prompt=str(payload.get("effective_prompt") or ""),
            effective_negative_prompt=str(payload.get("effective_negative_prompt") or ""),
            stages=[str(item) for item in payload.get("stages") or []],
            config_snapshot=deepcopy(payload.get("config_snapshot") or {}),
            job_ids=[str(item) for item in payload.get("job_ids") or []],
            manifest_paths=[str(item) for item in payload.get("manifest_paths") or []],
        )


@dataclass
class PhotoOptimizeAsset:
    asset_id: str
    source_filename: str
    imported_at: str
    original_path_at_import: str
    managed_original_path: str
    baseline: PhotoOptimizeBaseline = field(default_factory=PhotoOptimizeBaseline)
    history: list[PhotoOptimizeHistoryEntry] = field(default_factory=list)
    baseline_snapshots: list[PhotoOptimizeBaselineSnapshot] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    schema_version: str = PHOTO_OPTIMIZE_SCHEMA_VERSION
    asset_type: str = "external_photo"

    @property
    def current_input_path(self) -> Path:
        working_path = (self.baseline.working_image_path or "").strip()
        return Path(working_path or self.managed_original_path)

    @property
    def last_output_path(self) -> Path | None:
        if not self.history:
            return None
        latest = self.history[-1]
        if not latest.output_paths:
            return None
        return Path(latest.output_paths[-1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "source_filename": self.source_filename,
            "imported_at": self.imported_at,
            "original_path_at_import": self.original_path_at_import,
            "managed_original_path": self.managed_original_path,
            "asset_type": self.asset_type,
            "baseline": self.baseline.to_dict(),
            "history": [entry.to_dict() for entry in self.history],
            "baseline_snapshots": [entry.to_dict() for entry in self.baseline_snapshots],
            "tags": list(self.tags or []),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PhotoOptimizeAsset":
        data = payload or {}
        history: list[PhotoOptimizeHistoryEntry] = []
        for entry in data.get("history") or []:
            parsed = PhotoOptimizeHistoryEntry.from_dict(entry)
            if parsed is not None:
                history.append(parsed)
        snapshots: list[PhotoOptimizeBaselineSnapshot] = []
        for entry in data.get("baseline_snapshots") or []:
            parsed = PhotoOptimizeBaselineSnapshot.from_dict(entry)
            if parsed is not None:
                snapshots.append(parsed)
        return cls(
            schema_version=str(data.get("schema_version") or PHOTO_OPTIMIZE_SCHEMA_VERSION),
            asset_id=str(data.get("asset_id") or ""),
            source_filename=str(data.get("source_filename") or ""),
            imported_at=str(data.get("imported_at") or ""),
            original_path_at_import=str(data.get("original_path_at_import") or ""),
            managed_original_path=str(data.get("managed_original_path") or ""),
            asset_type=str(data.get("asset_type") or "external_photo"),
            baseline=PhotoOptimizeBaseline.from_dict(data.get("baseline") or {}),
            history=history,
            baseline_snapshots=snapshots,
            tags=[str(item) for item in data.get("tags") or []],
            notes=str(data.get("notes") or ""),
        )
