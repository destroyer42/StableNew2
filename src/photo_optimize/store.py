from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock, RLock
from typing import Any

from src.state.workspace_paths import workspace_paths as _wp
from src.utils.atomic_io import atomic_write_text

from .migration import MigrationReport, migrate_assets
from .models import (
    PHOTO_OPTIMIZE_SCHEMA_VERSION,
    PhotoOptimizeAsset,
    PhotoOptimizeBaseline,
    PhotoOptimizeBaselineSnapshot,
    PhotoOptimizeHistoryEntry,
    default_stage_defaults,
)
from .paths import io_path
from .results import digest, list_candidates, prepare_promotion
from .settings import decoded_geometry, resolve_geometry

PHOTO_OPTIMIZE_ROOT: Path = _wp.photo_optimize_root(create=False)


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class StaleBaselineError(ValueError):
    """The stored baseline is no longer the one an edit was made against (another writer changed it)."""


def _new_asset_id() -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"photo_{timestamp}_{uuid.uuid4().hex[:8]}"


class PhotoOptimizeStore:
    def __init__(self, root: Path | str | None = None, *, legacy_root: Path | str | None = None) -> None:
        self._root = Path(root) if root else PHOTO_OPTIMIZE_ROOT
        self._assets_dir = io_path(self._root / "assets")
        self._staging_dir = io_path(self._root / "staging_runs")
        self._legacy_root = Path(legacy_root) if legacy_root is not None else None
        self._migration_lock = Lock()
        # One lock per asset serialises every read-modify-write of its sidecar (GUI baseline saves, batch edit,
        # promotion, revert, archive and job-completion history all re-read inside the lock, so none is lost).
        self._asset_locks: dict[str, RLock] = {}
        self._asset_locks_guard = Lock()
        self.migration_report = MigrationReport()
        self._check_writable()
        if self._legacy_root is not None:
            self.retry_migration()

    def _check_writable(self) -> None:
        try:
            for directory in (self._root, self._assets_dir, self._staging_dir):
                io_path(directory, force=True).mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryFile(dir=io_path(directory, force=True)) as probe:
                    probe.write(b"Photo workspace write check")
                    probe.flush()
        except OSError as exc:
            raise OSError(f"Photo Optimize workspace is not writable at {self._root}: {exc}. "
                          "Check folder permissions and free space; no fallback store was opened.") from exc

    def retry_migration(self) -> MigrationReport:
        """Worker-side retry of retained legacy inputs, through this same store."""
        with self._migration_lock:
            self._check_writable()
            if self._legacy_root is not None:
                self.migration_report = migrate_assets(self._legacy_root, self._root)
            self._check_writable()
            return self.migration_report

    @property
    def root(self) -> Path:
        return self._root

    def asset_dir(self, asset_id: str) -> Path:
        if not asset_id or Path(asset_id).name != asset_id or asset_id in {".", ".."}:
            raise ValueError("Invalid photo asset identity")
        return io_path(self._assets_dir / asset_id)

    def sidecar_path(self, asset_id: str) -> Path:
        return io_path(self.asset_dir(asset_id) / "sidecar.json")

    def outputs_dir(self, asset_id: str) -> Path:
        path = io_path(self.asset_dir(asset_id) / "outputs")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def manifests_dir(self, asset_id: str) -> Path:
        path = io_path(self.asset_dir(asset_id) / "manifests")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def original_dir(self, asset_id: str) -> Path:
        path = io_path(self.asset_dir(asset_id) / "original")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_staging_run_dir(self, prefix: str = "job") -> Path:
        run_id = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        path = io_path(self._staging_dir / run_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @contextmanager
    def asset_lock(self, asset_id: str) -> Iterator[None]:
        """Hold the per-asset sidecar lock (reentrant) for a caller that must check-then-write atomically."""

        self.asset_dir(asset_id)  # rejects an invalid identity before a lock is created for it
        with self._asset_locks_guard:
            lock = self._asset_locks.setdefault(asset_id, RLock())
        with lock:
            yield

    def find_asset_ids_by_content(self, sha256: str, *, include_archived: bool = True) -> list[str]:
        """Managed assets whose recorded original bytes have this SHA-256 (content identity, never a filename)."""

        digest_value = str(sha256 or "").strip().lower()
        if not digest_value:
            return []
        return [
            asset.asset_id
            for asset in self.list_assets(include_archived=include_archived)
            if (asset.original_sha256 or "").lower() == digest_value
        ]

    def list_assets(self, *, include_archived: bool = False) -> list[PhotoOptimizeAsset]:
        assets: list[PhotoOptimizeAsset] = []
        for sidecar in sorted(self._assets_dir.glob("*/sidecar.json")):
            asset = self._read_asset(sidecar)
            if asset is not None and (include_archived or not asset.archived):
                assets.append(asset)
        assets.sort(key=lambda item: item.imported_at, reverse=True)
        return assets

    def get_asset(self, asset_id: str) -> PhotoOptimizeAsset | None:
        return self._read_asset(self.sidecar_path(asset_id))

    def save_asset(self, asset: PhotoOptimizeAsset) -> PhotoOptimizeAsset:
        with self.asset_lock(asset.asset_id):
            asset_dir = self.asset_dir(asset.asset_id)
            asset_dir.mkdir(parents=True, exist_ok=True)
            self.original_dir(asset.asset_id)
            self.outputs_dir(asset.asset_id)
            self.manifests_dir(asset.asset_id)
            sidecar = self.sidecar_path(asset.asset_id)
            payload = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
            serialized = asset.to_dict()
            serialized["baseline"] = {**payload.get("baseline", {}), **serialized["baseline"]}
            payload.update(serialized)
            atomic_write_text(sidecar, json.dumps(payload, indent=2))
            return asset

    def archive_assets(self, asset_ids: list[str]) -> None:
        self._set_archived(asset_ids, True)

    def restore_assets(self, asset_ids: list[str]) -> None:
        self._set_archived(asset_ids, False)

    def _set_archived(self, asset_ids: list[str], archived: bool) -> None:
        assets = [self.get_asset(asset_id) for asset_id in asset_ids]
        if any(asset is None for asset in assets):
            raise ValueError("A selected photo is unavailable; refresh the list")
        for asset_id in asset_ids:
            with self.asset_lock(asset_id):
                asset = self.get_asset(asset_id)
                if asset is None:
                    raise ValueError("A selected photo is unavailable; refresh the list")
                asset.archived = archived
                self.save_asset(asset)

    def import_photo(
        self,
        source_path: str | Path,
        *,
        baseline_defaults: dict[str, Any] | None = None,
    ) -> PhotoOptimizeAsset:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Photo not found: {source}")
        decoded_geometry(source)

        asset_id = _new_asset_id()
        # Reserve a fresh managed directory before copying any source bytes.
        self.asset_dir(asset_id).mkdir(parents=True, exist_ok=False)
        destination = io_path(self.original_dir(asset_id) / source.name)
        shutil.copy2(io_path(source), destination)

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
        baseline.config = resolve_geometry(baseline, destination)
        asset = PhotoOptimizeAsset(
            asset_id=asset_id,
            source_filename=source.name,
            imported_at=_utc_now(),
            original_path_at_import=str(source.resolve()),
            managed_original_path=str(destination),
            baseline=baseline,
            original_baseline=deepcopy(baseline),
            original_sha256=digest(destination),
        )
        return self.save_asset(asset)

    def update_asset_fields(
        self,
        asset_id: str,
        *,
        notes: str | None = None,
        tags: list[str] | None = None,
        baseline: PhotoOptimizeBaseline | None = None,
        expected_baseline: dict[str, Any] | None = None,
    ) -> PhotoOptimizeAsset:
        """Update draft fields. ``expected_baseline`` makes a baseline write conditional: the stored baseline must
        still equal it, otherwise ``StaleBaselineError`` is raised and nothing is written."""

        with self.asset_lock(asset_id):
            asset = self.get_asset(asset_id)
            if asset is None:
                raise KeyError(asset_id)
            if (
                baseline is not None
                and expected_baseline is not None
                and asset.baseline.to_dict() != expected_baseline
            ):
                raise StaleBaselineError(
                    "This photo's baseline was changed by another action (for example a promoted result "
                    "or a batch edit); reselect the photo to reload it before editing again."
                )
            if notes is not None:
                asset.notes = notes
            if tags is not None:
                asset.tags = list(tags)
            if baseline is not None:
                asset.baseline = baseline
            return self.save_asset(asset)

    def list_result_candidates(self, asset_id):
        asset = self.get_asset(asset_id)
        if asset is None or asset.asset_id != asset_id:
            raise ValueError("Photo identity is missing or invalid")
        return list_candidates(asset)

    def prepare_result_promotion(self, asset_id, candidate, *, mode):
        return prepare_promotion(self, asset_id, candidate, mode=mode)

    def apply_result_promotion(self, plan: Any) -> Any:
        with self.asset_lock(plan.asset_id):
            return self._apply_result_promotion_locked(plan)

    def _apply_result_promotion_locked(self, plan: Any) -> Any:
        fresh = prepare_promotion(self, plan.asset_id, plan.candidate, mode=plan.mode)
        if (fresh.fingerprint != plan.fingerprint or fresh.image_sha256 != plan.image_sha256
                or fresh.after.to_dict() != plan.after.to_dict()):
            raise ValueError("Photo or result changed since review; nothing promoted, review again")
        asset = self.get_asset(plan.asset_id)
        if asset is None or digest(self.sidecar_path(plan.asset_id)) != plan.fingerprint:
            raise ValueError("Photo changed since review; nothing promoted")
        if not fresh.changed:
            return asset
        asset.baseline_snapshots.append(PhotoOptimizeBaselineSnapshot(
            snapshot_id=f"baseline_{uuid.uuid4().hex[:8]}", created_at=_utc_now(),
            reason=f"promote {plan.candidate.label()} ({plan.mode})",
            baseline=deepcopy(asset.baseline),
        ))
        asset.baseline = deepcopy(fresh.after)
        return self.save_asset(asset)

    def promote_latest_output_as_baseline(self, asset_id: str) -> PhotoOptimizeAsset:
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        if not asset.history or not asset.history[-1].output_paths:
            raise ValueError("Asset has no optimize output to promote")
        candidate = next(c for c in list_candidates(asset) if c.kind == "history"
                         and c.history_index == len(asset.history) - 1
                         and c.output_index == len(asset.history[-1].output_paths) - 1)
        return self.apply_result_promotion(self.prepare_result_promotion(asset_id, candidate, mode="recorded"))

    def revert_baseline(self, asset_id: str) -> PhotoOptimizeAsset:
        with self.asset_lock(asset_id):
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
        geometry_policy: str = "",
    ) -> PhotoOptimizeAsset:
        with self.asset_lock(asset_id):
            return self._record_optimize_history_locked(
                asset_id,
                run_id=run_id,
                input_image_path=input_image_path,
                source_output_paths=source_output_paths,
                prompt_mode=prompt_mode,
                prompt_delta=prompt_delta,
                negative_prompt_mode=negative_prompt_mode,
                negative_prompt_delta=negative_prompt_delta,
                effective_prompt=effective_prompt,
                effective_negative_prompt=effective_negative_prompt,
                stages=stages,
                config_snapshot=config_snapshot,
                job_ids=job_ids,
                geometry_policy=geometry_policy,
            )

    def _record_optimize_history_locked(
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
        geometry_policy: str = "",
    ) -> PhotoOptimizeAsset:
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)

        if any(entry.run_id == run_id and entry.job_ids == list(job_ids or []) for entry in asset.history):
            return asset
        copied_output_paths: list[str] = []
        copied_manifest_paths: list[str] = []
        for source_path in source_output_paths or []:
            output_file = Path(source_path)
            if not output_file.exists():
                continue
            target_name = f"{run_id}_{output_file.name}"
            target_output = io_path(self.outputs_dir(asset_id) / target_name)
            if target_output.exists():
                raise FileExistsError(f"Photo output already exists; history was preserved: {target_output}")
            shutil.copy2(output_file, target_output)
            copied_output_paths.append(str(target_output))

            manifest_source = self.find_manifest_for_output(output_file)
            if manifest_source is not None and manifest_source.exists():
                target_manifest = io_path(self.manifests_dir(asset_id) / f"{target_output.stem}.json")
                if target_manifest.exists():
                    raise FileExistsError(f"Photo manifest already exists; history was preserved: {target_manifest}")
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
            output_sha256={path: digest(path) for path in copied_output_paths},
            geometry_policy=geometry_policy,
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
_store_lock = Lock()


def get_photo_optimize_store(*, output_root: Path | str | None = None) -> PhotoOptimizeStore:
    global _global_store
    with _store_lock:
        if _global_store is None:
            from src.config.app_config import output_dir_default
            root = _wp.photo_optimize_root(output_root=output_root or output_dir_default(), create=False)
            # Tests may inject PHOTO_OPTIMIZE_ROOT; never migrate operator data then.
            if PHOTO_OPTIMIZE_ROOT != _wp.photo_optimize_root(create=False):
                _global_store = PhotoOptimizeStore(PHOTO_OPTIMIZE_ROOT)
            else:
                _global_store = PhotoOptimizeStore(root, legacy_root=_wp.legacy_photo_optimize_root())
    return _global_store
