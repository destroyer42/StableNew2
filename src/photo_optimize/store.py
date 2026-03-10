from __future__ import annotations

import json
import shutil
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    PHOTO_OPTIMIZE_SCHEMA_VERSION,
    PhotoOptimizeAsset,
    PhotoOptimizeBaseline,
    PhotoOptimizeBaselineSnapshot,
    PhotoOptimizeHistoryEntry,
    default_stage_defaults,
)

PHOTO_OPTIMIZE_ROOT = Path("data") / "photo_optimize"


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _new_asset_id() -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"photo_{timestamp}_{uuid.uuid4().hex[:8]}"


class PhotoOptimizeStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root else PHOTO_OPTIMIZE_ROOT
        self._assets_dir = self._root / "assets"
        self._staging_dir = self._root / "staging_runs"
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def asset_dir(self, asset_id: str) -> Path:
        return self._assets_dir / asset_id

    def sidecar_path(self, asset_id: str) -> Path:
        return self.asset_dir(asset_id) / "sidecar.json"

    def outputs_dir(self, asset_id: str) -> Path:
        path = self.asset_dir(asset_id) / "outputs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def manifests_dir(self, asset_id: str) -> Path:
        path = self.asset_dir(asset_id) / "manifests"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def original_dir(self, asset_id: str) -> Path:
        path = self.asset_dir(asset_id) / "original"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_staging_run_dir(self, prefix: str = "job") -> Path:
        run_id = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        path = self._staging_dir / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def list_assets(self) -> list[PhotoOptimizeAsset]:
        assets: list[PhotoOptimizeAsset] = []
        for sidecar in sorted(self._assets_dir.glob("*/sidecar.json")):
            asset = self._read_asset(sidecar)
            if asset is not None:
                assets.append(asset)
        assets.sort(key=lambda item: item.imported_at, reverse=True)
        return assets

    def get_asset(self, asset_id: str) -> PhotoOptimizeAsset | None:
        return self._read_asset(self.sidecar_path(asset_id))

    def save_asset(self, asset: PhotoOptimizeAsset) -> PhotoOptimizeAsset:
        asset_dir = self.asset_dir(asset.asset_id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        self.original_dir(asset.asset_id)
        self.outputs_dir(asset.asset_id)
        self.manifests_dir(asset.asset_id)
        self.sidecar_path(asset.asset_id).write_text(
            json.dumps(asset.to_dict(), indent=2),
            encoding="utf-8",
        )
        return asset

    def import_photo(
        self,
        source_path: str | Path,
        *,
        baseline_defaults: dict[str, Any] | None = None,
    ) -> PhotoOptimizeAsset:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Photo not found: {source}")

        asset_id = _new_asset_id()
        destination = self.original_dir(asset_id) / source.name
        shutil.copy2(source, destination)

        defaults = baseline_defaults or {}
        config = deepcopy(defaults.get("config") or {})
        stage_defaults = dict(defaults.get("stage_defaults") or default_stage_defaults())
        baseline = PhotoOptimizeBaseline(
            prompt=str(defaults.get("prompt") or ""),
            negative_prompt=str(defaults.get("negative_prompt") or ""),
            model=str(defaults.get("model") or ""),
            vae=str(defaults.get("vae") or ""),
            stage_defaults=stage_defaults,
            config=config,
            source=str(defaults.get("source") or "manual"),
            working_image_path=str(destination),
        )
        asset = PhotoOptimizeAsset(
            asset_id=asset_id,
            source_filename=source.name,
            imported_at=_utc_now(),
            original_path_at_import=str(source.resolve()),
            managed_original_path=str(destination),
            baseline=baseline,
        )
        return self.save_asset(asset)

    def update_asset_fields(
        self,
        asset_id: str,
        *,
        notes: str | None = None,
        tags: list[str] | None = None,
        baseline: PhotoOptimizeBaseline | None = None,
    ) -> PhotoOptimizeAsset:
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        if notes is not None:
            asset.notes = notes
        if tags is not None:
            asset.tags = list(tags)
        if baseline is not None:
            asset.baseline = baseline
        return self.save_asset(asset)

    def append_baseline_snapshot(self, asset_id: str, *, reason: str) -> PhotoOptimizeBaselineSnapshot:
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        snapshot = PhotoOptimizeBaselineSnapshot(
            snapshot_id=f"baseline_{uuid.uuid4().hex[:8]}",
            created_at=_utc_now(),
            reason=reason,
            baseline=PhotoOptimizeBaseline.from_dict(asset.baseline.to_dict()),
        )
        asset.baseline_snapshots.append(snapshot)
        self.save_asset(asset)
        return snapshot

    def promote_latest_output_as_baseline(self, asset_id: str) -> PhotoOptimizeAsset:
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        if not asset.history or not asset.history[-1].output_paths:
            raise ValueError("Asset has no optimize output to promote")
        self.append_baseline_snapshot(asset_id, reason="promote_latest_output")
        asset = self.get_asset(asset_id)
        assert asset is not None
        latest = asset.history[-1]
        promoted = PhotoOptimizeBaseline.from_dict(asset.baseline.to_dict())
        promoted.prompt = latest.effective_prompt
        promoted.negative_prompt = latest.effective_negative_prompt
        promoted.config = deepcopy(latest.config_snapshot or {})
        promoted.stage_defaults = {
            "img2img": "img2img" in latest.stages,
            "adetailer": "adetailer" in latest.stages,
            "upscale": "upscale" in latest.stages,
        }
        promoted.working_image_path = latest.output_paths[-1]
        promoted.source = "restored"
        asset.baseline = promoted
        return self.save_asset(asset)

    def revert_baseline(self, asset_id: str) -> PhotoOptimizeAsset:
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        if not asset.baseline_snapshots:
            raise ValueError("No baseline snapshot is available")
        snapshot = asset.baseline_snapshots.pop()
        asset.baseline = PhotoOptimizeBaseline.from_dict(snapshot.baseline.to_dict())
        return self.save_asset(asset)

    def record_optimize_history(
        self,
        asset_id: str,
        *,
        run_id: str,
        input_image_path: str,
        source_output_paths: list[str] | None,
        prompt_mode: str,
        prompt_delta: str,
        negative_prompt_mode: str,
        negative_prompt_delta: str,
        effective_prompt: str,
        effective_negative_prompt: str,
        stages: list[str],
        config_snapshot: dict[str, Any] | None,
        job_ids: list[str] | None,
    ) -> PhotoOptimizeAsset:
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)

        copied_output_paths: list[str] = []
        copied_manifest_paths: list[str] = []
        for source_path in source_output_paths or []:
            output_file = Path(source_path)
            if not output_file.exists():
                continue
            target_name = f"{run_id}_{output_file.name}"
            target_output = self.outputs_dir(asset_id) / target_name
            shutil.copy2(output_file, target_output)
            copied_output_paths.append(str(target_output))

            manifest_source = self.find_manifest_for_output(output_file)
            if manifest_source is not None and manifest_source.exists():
                target_manifest = self.manifests_dir(asset_id) / f"{target_output.stem}.json"
                shutil.copy2(manifest_source, target_manifest)
                copied_manifest_paths.append(str(target_manifest))

        entry = PhotoOptimizeHistoryEntry(
            run_id=run_id,
            created_at=_utc_now(),
            input_image_path=input_image_path,
            output_paths=copied_output_paths,
            prompt_mode=prompt_mode,
            prompt_delta=prompt_delta,
            negative_prompt_mode=negative_prompt_mode,
            negative_prompt_delta=negative_prompt_delta,
            effective_prompt=effective_prompt,
            effective_negative_prompt=effective_negative_prompt,
            stages=list(stages or []),
            config_snapshot=deepcopy(config_snapshot or {}),
            job_ids=list(job_ids or []),
            manifest_paths=copied_manifest_paths,
        )
        asset.history.append(entry)
        return self.save_asset(asset)

    def find_manifest_for_output(self, output_path: str | Path) -> Path | None:
        output_file = Path(output_path)
        direct = output_file.with_suffix(".json")
        if direct.exists():
            return direct
        manifests_dir = output_file.parent.parent / "manifests"
        manifest = manifests_dir / f"{output_file.stem}.json"
        if manifest.exists():
            return manifest
        return None

    def _read_asset(self, sidecar_path: Path) -> PhotoOptimizeAsset | None:
        try:
            if not sidecar_path.exists():
                return None
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            if payload.get("schema_version") not in {None, PHOTO_OPTIMIZE_SCHEMA_VERSION}:
                return None
            return PhotoOptimizeAsset.from_dict(payload)
        except Exception:
            return None


_global_store: PhotoOptimizeStore | None = None


def get_photo_optimize_store() -> PhotoOptimizeStore:
    global _global_store
    if _global_store is None:
        _global_store = PhotoOptimizeStore()
    return _global_store
