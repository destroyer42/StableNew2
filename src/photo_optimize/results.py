"""Read-only result projection/validation. Promotions persist only through PhotoOptimizeStore."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .models import PhotoOptimizeBaseline
from .paths import canonical_path, io_path
from .settings import STAGES, resolve_geometry, validate_settings


def digest(path: str | Path) -> str:
    with io_path(path, force=True).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(path):
    return canonical_path(io_path(path, force=True).resolve())


def identity(path):
    """Recorded lexical identity; legacy links must never change which copied artifact is selected."""
    return canonical_path(Path(path).absolute())


@dataclass(frozen=True)
class ResultCandidate:
    asset_id: str
    kind: str
    path: str
    history_index: int = -1
    output_index: int = -1
    run_id: str = ""

    def label(self):
        if self.kind == "original":
            return "Imported original"
        if self.kind == "working":
            return "Current working baseline"
        return f"Run {self.run_id} | output {self.output_index + 1}: {Path(self.path).name or '(no recorded outputs)'}"


def list_candidates(asset):
    rows = [
        ResultCandidate(asset.asset_id, "original", asset.managed_original_path),
        ResultCandidate(asset.asset_id, "working", str(asset.current_input_path)),
    ]
    for index in reversed(range(len(asset.history))):
        entry = asset.history[index]
        rows.extend(
            ResultCandidate(asset.asset_id, "history", path, index, output, entry.run_id)
            for output, path in enumerate(entry.output_paths)
        )
        if not entry.output_paths:
            rows.append(ResultCandidate(asset.asset_id, "history", "", index, -1, entry.run_id))
    return rows


def _safe_file(store, asset, raw):
    """Resolve only this managed asset, or its hash-verified migration copy; never read external images."""
    root = canonical(store.asset_dir(asset.asset_id))
    if (
        store.asset_dir(asset.asset_id).is_symlink()
        or store.asset_dir(asset.asset_id).is_junction()
    ):
        raise ValueError("Photo asset directory is a link or junction")
    if not root.is_relative_to(canonical(store.root / "assets")):
        raise ValueError("Photo asset directory escapes the workspace")
    if not raw or not Path(raw).is_absolute() or ".." in Path(raw).parts:
        raise ValueError("Result path is missing or not absolute")
    recorded = identity(raw)
    spelled_root = identity(store.asset_dir(asset.asset_id))
    marker = root / "migration.json"
    record = {}
    if marker.exists():
        if marker.is_symlink() or not marker.is_file():
            raise ValueError("Invalid migration marker")
        record = json.loads(io_path(marker).read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not isinstance(record.get("files"), dict):
            raise ValueError("Invalid migration marker evidence")
    expected = ""
    if recorded.is_relative_to(spelled_root):
        relative = recorded.relative_to(spelled_root)
    elif recorded.is_relative_to(root):
        relative = recorded.relative_to(root)
    else:
        if not record:
            raise ValueError("Result is outside this managed asset; no verified migration mapping")
        source = Path(record.get("source", ""))
        if not source.is_absolute() or ".." in source.parts:
            raise ValueError("Invalid migration source identity")
        try:
            relative = recorded.relative_to(identity(source))
        except ValueError as exc:
            raise ValueError("Result is outside this asset's migration source") from exc
        expected = record["files"].get(str(relative), "")
        if not expected:
            raise ValueError("Historical result has no verified migration copy")
    expected = record.get("files", {}).get(str(relative), expected)
    inspected = store.asset_dir(asset.asset_id) / relative
    supplied = canonical(inspected)
    if not supplied.is_relative_to(root) or supplied == root:
        raise ValueError("Result path escapes this asset")
    # Reject links/junctions, including an asset-directory link. Resolve checks alone permit internal links.
    while canonical_path(inspected.absolute()) != canonical_path(
        store.asset_dir(asset.asset_id).absolute().parent
    ):
        if inspected.is_symlink() or inspected.is_junction():
            raise ValueError("Result paths through links or junctions are ineligible")
        if inspected.parent == inspected:
            raise ValueError("Result path cannot be contained")
        inspected = inspected.parent
    if not supplied.is_file():
        raise ValueError("Recorded result is missing or is not a file")
    checksum = digest(supplied)
    if expected and checksum != expected:
        raise ValueError("Migration copy integrity check failed")
    try:
        with Image.open(io_path(supplied, force=True)) as image:
            image.verify()
        with Image.open(io_path(supplied, force=True)) as image:
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError("Recorded result is corrupt or unreadable") from exc
    if digest(supplied) != checksum:
        raise ValueError("Result changed while validating")
    return str(io_path(supplied)), checksum, bool(expected)


def validate_candidate(store, asset, candidate):
    if candidate.asset_id != asset.asset_id or candidate not in list_candidates(asset):
        raise ValueError("Result no longer has exact asset/history/output membership; refresh")
    path, checksum, migrated = _safe_file(store, asset, candidate.path)
    expected = ""
    if candidate.kind == "original" or identity(candidate.path) == identity(
        asset.managed_original_path
    ):
        expected = asset.original_sha256
    if candidate.kind == "history":
        if not candidate.path or candidate.output_index < 0:
            raise ValueError("This history entry has no recorded output")
        matches = sum(
            identity(p) == identity(candidate.path)
            for entry in asset.history
            for p in entry.output_paths
        )
        if matches != 1:
            raise ValueError("Ambiguous result: this output is recorded more than once")
        expected = asset.history[candidate.history_index].output_sha256.get(candidate.path, "")
    elif candidate.kind == "working" and not expected:
        hashes = [
            entry.output_sha256[p]
            for entry in asset.history
            for p in entry.output_paths
            if identity(p) == identity(candidate.path) and p in entry.output_sha256
        ]
        if len(set(hashes)) > 1:
            raise ValueError("Working image has conflicting recorded integrity evidence")
        expected = next(iter(hashes), "")
    if expected and expected != checksum:
        raise ValueError("Recorded image integrity check failed (SHA-256 mismatch)")
    warning = (
        ""
        if expected or migrated
        else "No historical image hash was recorded; readability and current bytes verified only."
    )
    return path, checksum, warning


def _recorded_baseline(asset, candidate):
    if candidate.kind == "original":
        if asset.original_baseline is None:
            raise ValueError(
                "Original prompt/settings were not recorded; choose Image only + retain current prompt/settings"
            )
        return deepcopy(asset.original_baseline), ""
    if candidate.kind == "working":
        return deepcopy(asset.baseline), ""
    entry = asset.history[candidate.history_index]
    config = entry.config_snapshot
    if (
        not isinstance(config, dict)
        or not isinstance(config.get("model"), str)
        or not config["model"].strip()
        or not isinstance(config.get("vae"), str)
        or not entry.stages
        or set(entry.stages) - set(STAGES)
        or any(not isinstance(config.get(stage), dict) for stage in entry.stages)
    ):
        raise ValueError(
            "Recorded prompt/settings metadata is incomplete; choose Image only + retain current prompt/settings"
        )
    baseline = PhotoOptimizeBaseline(
        prompt=entry.effective_prompt,
        negative_prompt=entry.effective_negative_prompt,
        model=config["model"],
        vae="" if config["vae"].lower() == "automatic" else config["vae"],
        config=deepcopy(config),
        stage_defaults={s: s in entry.stages for s in STAGES},
        geometry_policy=entry.geometry_policy or asset.baseline.geometry_policy,
    )
    warning = ""
    if not entry.geometry_policy:
        warning = "No historical geometry policy recorded; retaining current Auto/Custom policy."
        if asset.baseline.geometry_policy == "custom":
            baseline.config.setdefault("img2img", {}).update(
                {key: asset.baseline.config["img2img"][key] for key in ("width", "height")}
            )
    return baseline, warning


@dataclass
class PromotionPlan:
    asset_id: str
    candidate: ResultCandidate
    mode: str
    fingerprint: str
    image_sha256: str
    before: PhotoOptimizeBaseline
    after: PhotoOptimizeBaseline
    warning: str
    changed: bool

    def describe(self):
        return (
            f"Asset: {self.asset_id}\nSelected: {self.candidate.label()}\n"
            f"Recorded path: {self.candidate.path}\nMode: {self.mode}\n"
            f"SHA-256: {self.image_sha256}\n{self.warning}\n"
            f"Before: {self.before.to_dict()}\nAfter: {self.after.to_dict()}\n"
            "Original, outputs, manifests, history and queued jobs remain unchanged. "
            "Previous baseline and new baseline are saved together in one sidecar replacement."
            + ("\nAlready current; no changes or snapshot needed." if not self.changed else "")
        )


def prepare_promotion(store, asset_id, candidate, *, mode):
    if mode not in {"recorded", "image_only"}:
        raise ValueError(
            "Choose Image + recorded prompt/settings or Image only + retain current prompt/settings"
        )
    signature = digest(store.sidecar_path(asset_id))
    asset = store.get_asset(asset_id)
    if asset is None or asset.asset_id != asset_id:
        raise ValueError("Photo identity is missing or invalid")
    path, checksum, warning = validate_candidate(store, asset, candidate)
    after = deepcopy(asset.baseline)
    if mode == "recorded":
        after, metadata_warning = _recorded_baseline(asset, candidate)
        warning = " ".join(filter(None, (warning, metadata_warning)))
    after.working_image_path = path
    after.source = f"result:{candidate.kind}:{candidate.run_id}:output:{candidate.output_index}"
    if after.geometry_policy == "auto":
        after.config = resolve_geometry(after, path)
    validate_settings(resolve_geometry(after, path))
    json.dumps(after.to_dict(), allow_nan=False)
    before = deepcopy(asset.baseline)
    previous, updated = before.to_dict(), after.to_dict()
    previous.pop("source")
    updated.pop("source")
    previous["working_image_path"] = str(canonical(asset.current_input_path))
    updated["working_image_path"] = str(canonical(path))
    changed = previous != updated
    if not changed:
        after = deepcopy(before)
    if digest(store.sidecar_path(asset_id)) != signature:
        raise ValueError("Photo changed during preparation; refresh and review again")
    return PromotionPlan(
        asset_id, candidate, mode, signature, checksum, before, after, warning, changed
    )
