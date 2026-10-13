"""Verified copy-only legacy migration. Originals and frozen evidence remain usable."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from .paths import canonical_path, io_path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with io_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def migrate_assets(legacy_root: Path, target_root: Path) -> list[str]:
    """Publish only fully verified assets; retain failed staging for inspection.

    Only recognized sidecars are copied. No legacy file or destination is removed
    or overwritten. History and baseline snapshots deliberately retain old paths;
    this also keeps every queued NJR's immutable input path valid.
    """
    migrated = []
    if legacy_root.resolve() == target_root.resolve():
        return migrated
    for sidecar in sorted((legacy_root / "assets").glob("*/sidecar.json")):
        sidecar_digest = _digest(sidecar)
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        if payload.get("schema_version") not in {None, "1.0"}:
            raise ValueError(f"Unsupported legacy Photo Optimize sidecar: {sidecar}")
        asset_id = payload.get("asset_id")
        if asset_id != sidecar.parent.name or not asset_id:
            raise ValueError(f"Invalid legacy asset identity: {sidecar}")
        source = sidecar.parent
        destination = io_path(target_root / "assets" / asset_id)
        marker = destination / "migration.json"
        if destination.exists():
            if marker.is_file() and json.loads(marker.read_text(encoding="utf-8")).get(
                "source"
            ) == str(source.resolve()):
                evidence = json.loads(marker.read_text(encoding="utf-8"))["files"]
                if all(
                    io_path(destination / name).is_file() and _digest(destination / name) == sha
                    for name, sha in evidence.items()
                ):
                    continue
            raise FileExistsError(
                f"Photo workspace collision or changed migration copy: {destination}"
            )
        paths = list(source.rglob("*"))
        if source.is_symlink() or any(path.is_symlink() for path in paths):
            raise ValueError(f"Legacy asset contains a symbolic link: {source}")
        # A distinct staging name never replaces a previous interrupted attempt.
        staged = target_root / "migration_staging" / uuid.uuid4().hex
        shutil.copytree(io_path(source, force=True), io_path(staged, force=True))
        hashes = {}
        for path in paths:
            if path.is_file():
                relative = path.relative_to(source)
                sha = _digest(path)
                if _digest(staged / relative) != sha:
                    raise OSError(f"Photo migration verification failed: {path}")
                if relative.name != "sidecar.json":
                    hashes[str(relative)] = sha

        # Change only current managed paths, never history or snapshot evidence.
        def routed(raw, source=source, staged=staged, destination=destination):
            path = Path(raw)
            if not path.is_absolute():
                path = Path.cwd() / path
            try:
                relative = canonical_path(path.resolve()).relative_to(canonical_path(source.resolve()))
            except ValueError:
                return raw
            if not io_path(staged / relative).is_file():
                raise FileNotFoundError(f"Legacy current photo is missing: {raw}")
            return str(io_path(destination / relative))

        payload["managed_original_path"] = routed(payload["managed_original_path"])
        baseline = payload.setdefault("baseline", {})
        if baseline.get("working_image_path"):
            baseline["working_image_path"] = routed(baseline["working_image_path"])
        (staged / "sidecar.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (staged / "migration.json").write_text(
            json.dumps(
                {
                    "source": str(source.resolve()),
                    "files": hashes,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if _digest(sidecar) != sidecar_digest:
            raise OSError(
                f"Legacy photo changed during migration; retry after it is idle: {sidecar}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        # rename fails if another process populated the destination in the meantime.
        staged.rename(destination)
        migrated.append(asset_id)
    return migrated
