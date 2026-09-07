from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

OUTPUT_ROUTE_PIPELINE = "Pipeline"
OUTPUT_ROUTE_LEARNING = "Learning"
OUTPUT_ROUTE_REPROCESS = "Reprocess"
OUTPUT_ROUTE_ANIMATEDIFF = "animatediff"
OUTPUT_ROUTE_SVD = "SVD"
OUTPUT_ROUTE_PHOTO_OPTIMIZE = "PhotoOptimize"
OUTPUT_ROUTE_TESTING = "Testing"
OUTPUT_ROUTE_MOVIE_CLIPS = "movie_clips"
OUTPUT_ROUTE_AUTO = "Auto"

KNOWN_OUTPUT_ROUTE_DIRS = (
    OUTPUT_ROUTE_PIPELINE,
    OUTPUT_ROUTE_LEARNING,
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_ANIMATEDIFF,
    OUTPUT_ROUTE_SVD,
    OUTPUT_ROUTE_PHOTO_OPTIMIZE,
    OUTPUT_ROUTE_TESTING,
    OUTPUT_ROUTE_MOVIE_CLIPS,
)
_KNOWN_OUTPUT_ROUTE_DIRS_LOWER = {item.lower() for item in KNOWN_OUTPUT_ROUTE_DIRS}


def _looks_like_test_output_label(raw_value: str | Path | None) -> bool:
    label = str(raw_value or "").strip().lower()
    if not label:
        return False

    normalized = label.replace(" ", "_")
    if "cfg-check" in normalized:
        return True
    if "test_pack" in normalized:
        return True
    if normalized == "testpack" or normalized.startswith("testpack-") or "_testpack-" in normalized:
        return True
    return False


def normalize_output_root(base_output_dir: str | Path = "output") -> Path:
    """Return the canonical base output root without any trailing route folder.

    Users and older settings may point ``output_dir`` at a route-specific folder
    like ``output/animatediff``.  StableNew treats ``output_dir`` as the base
    root, so known trailing route directories are stripped before route
    selection. Single-part values like ``animatediff`` are left untouched to
    avoid collapsing them to ``.`` unexpectedly.
    """
    root = Path(base_output_dir)
    while len(root.parts) > 1 and root.name in KNOWN_OUTPUT_ROUTE_DIRS:
        root = root.parent
    return root


def get_output_root(base_output_dir: str | Path = "output", *, create: bool = True) -> Path:
    root = normalize_output_root(base_output_dir)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def get_output_route_root(
    base_output_dir: str | Path,
    route: str,
    *,
    create: bool = True,
) -> Path:
    root = get_output_root(base_output_dir, create=create)
    if root.name == route:
        return root
    route_root = root / route
    if create:
        route_root.mkdir(parents=True, exist_ok=True)
    return route_root


def resolve_output_artifact_path(
    raw_path: str | Path,
    *,
    base_output_dir: str | Path = "output",
) -> str:
    """Resolve a possibly stale output artifact path across routed output roots.

    This is used when persisted references still point at an older route such as
    ``output/Pipeline/...`` but the run has since been rebalanced to another
    route like ``output/Testing/...``.
    """
    raw = str(raw_path or "").strip()
    if not raw:
        return raw

    candidate = Path(raw).expanduser()
    if candidate.exists():
        try:
            return str(candidate.resolve())
        except Exception:
            return str(candidate)

    output_root = get_output_root(base_output_dir, create=False)
    if not output_root.exists():
        return raw

    parts = list(candidate.parts)
    lower_parts = [part.lower() for part in parts]
    relative_candidates: list[list[str]] = []

    try:
        if candidate.is_absolute():
            relative_candidates.append(list(candidate.relative_to(output_root).parts))
    except Exception:
        pass

    if "output" in lower_parts:
        output_index = len(lower_parts) - 1 - lower_parts[::-1].index("output")
        relative_candidates.append(parts[output_index + 1 :])
    elif parts and parts[0].lower() == "output":
        relative_candidates.append(parts[1:])
    else:
        relative_candidates.append(parts)

    search_paths: list[Path] = []
    seen_relative: set[tuple[str, ...]] = set()

    for relative_parts in relative_candidates:
        normalized_relative = tuple(str(part) for part in relative_parts if str(part).strip())
        if not normalized_relative or normalized_relative in seen_relative:
            continue
        seen_relative.add(normalized_relative)

        rel_parts = list(normalized_relative)
        trimmed = rel_parts[1:] if rel_parts and rel_parts[0].lower() in _KNOWN_OUTPUT_ROUTE_DIRS_LOWER else rel_parts

        if rel_parts:
            search_paths.append(output_root.joinpath(*rel_parts))
        if trimmed:
            search_paths.append(output_root.joinpath(*trimmed))
            for route in KNOWN_OUTPUT_ROUTE_DIRS:
                search_paths.append((output_root / route).joinpath(*trimmed))
            if len(trimmed) >= 2:
                suffix2 = trimmed[-2:]
                for route in KNOWN_OUTPUT_ROUTE_DIRS:
                    search_paths.append((output_root / route).joinpath(*suffix2))
            if len(trimmed) >= 3:
                suffix3 = trimmed[-3:]
                for route in KNOWN_OUTPUT_ROUTE_DIRS:
                    search_paths.append((output_root / route).joinpath(*suffix3))

    seen_paths: set[str] = set()
    for path_obj in search_paths:
        key = str(path_obj)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        if not path_obj.exists():
            continue
        try:
            return str(path_obj.resolve())
        except Exception:
            return str(path_obj)
    return raw


def iter_output_run_dirs(base_output_dir: str | Path = "output") -> list[Path]:
    root = get_output_root(base_output_dir, create=False)
    if not root.exists():
        return []
    run_dirs: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name in KNOWN_OUTPUT_ROUTE_DIRS:
            run_dirs.extend(grandchild for grandchild in child.iterdir() if grandchild.is_dir())
        else:
            run_dirs.append(child)
    run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return run_dirs


def classify_njr_output_route(njr: Any) -> str:
    config = getattr(njr, "config", None)
    if isinstance(config, dict):
        pipeline_section = config.get("pipeline")
        if isinstance(pipeline_section, dict):
            explicit_route = str(pipeline_section.get("output_route") or "").strip()
            if explicit_route and explicit_route != OUTPUT_ROUTE_AUTO and explicit_route in KNOWN_OUTPUT_ROUTE_DIRS:
                return explicit_route

    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("STABLENEW_TEST_MODE") == "1":
        return OUTPUT_ROUTE_TESTING

    intent_config = getattr(njr, "intent_config", None)
    if isinstance(intent_config, dict):
        source = str(intent_config.get("source") or "").strip().lower()
        if source in {"history_restore", "debug_replay"}:
            return OUTPUT_ROUTE_TESTING

    extra_metadata = getattr(njr, "extra_metadata", None) or {}
    requested_job_label = ""
    if isinstance(intent_config, dict):
        requested_job_label = str(intent_config.get("requested_job_label") or "").strip()

    label_candidates = (
        getattr(njr, "prompt_pack_name", None),
        getattr(njr, "job_id", None),
        requested_job_label,
        extra_metadata.get("run_name") if isinstance(extra_metadata, dict) else None,
    )
    if any(_looks_like_test_output_label(candidate) for candidate in label_candidates):
        return OUTPUT_ROUTE_TESTING

    if getattr(njr, "learning_context", None):
        return OUTPUT_ROUTE_LEARNING

    metadata = getattr(njr, "extra_metadata", None) or {}
    if isinstance(metadata, dict) and isinstance(metadata.get("photo_optimize"), dict):
        return OUTPUT_ROUTE_PHOTO_OPTIMIZE

    start_stage = str(getattr(njr, "start_stage", "") or "").strip().lower()
    stage_types: list[str] = []
    for stage in list(getattr(njr, "stage_chain", None) or []):
        if isinstance(stage, dict):
            is_enabled = bool(stage.get("enabled", False))
            stage_type = stage.get("stage_type")
        else:
            is_enabled = bool(getattr(stage, "enabled", False))
            stage_type = getattr(stage, "stage_type", None)
        if not is_enabled:
            continue
        if stage_type:
            stage_types.append(str(stage_type).strip().lower())

    prompt_pack_name = str(getattr(njr, "prompt_pack_name", "") or "").strip().lower()
    if "svd_native" in stage_types or start_stage == "svd_native" or prompt_pack_name == "svd":
        return OUTPUT_ROUTE_SVD
    if "animatediff" in stage_types or start_stage == "animatediff":
        return OUTPUT_ROUTE_ANIMATEDIFF
    if getattr(njr, "input_image_paths", None) or start_stage or "reprocess" in prompt_pack_name:
        return OUTPUT_ROUTE_REPROCESS
    return OUTPUT_ROUTE_PIPELINE


def classify_existing_output_dir(run_dir: str | Path) -> str:
    path = Path(run_dir)
    name = path.name.lower()

    if path.name in KNOWN_OUTPUT_ROUTE_DIRS:
        return path.name

    if _looks_like_test_output_label(name):
        return OUTPUT_ROUTE_TESTING

    if (
        name.startswith("runner-")
        or "_runner-" in name
        or "smoke" in name
        or "validation" in name
        or "verify" in name
        or name.endswith("_e2e")
        or "_e2e_" in name
        or name.startswith("debug_")
        or name.endswith("_debug")
    ):
        return OUTPUT_ROUTE_TESTING

    manifest_dir = path / "manifests"
    if manifest_dir.exists():
        manifest_names = [item.name.lower() for item in manifest_dir.glob("*.json")]
        if any(item.startswith("svd_native_") for item in manifest_names):
            return OUTPUT_ROUTE_SVD
        if any(item.startswith("animatediff_") for item in manifest_names):
            return OUTPUT_ROUTE_ANIMATEDIFF
        if any("reprocess" in item for item in manifest_names):
            return OUTPUT_ROUTE_REPROCESS
        for manifest_path in manifest_dir.glob("*.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            metadata = payload.get("metadata") or {}
            if isinstance(metadata, dict):
                route = metadata.get("output_route")
                if route in KNOWN_OUTPUT_ROUTE_DIRS:
                    return str(route)
                if isinstance(metadata.get("photo_optimize"), dict):
                    return OUTPUT_ROUTE_PHOTO_OPTIMIZE
            stage = str(payload.get("stage") or "").strip().lower()
            if stage == "svd_native":
                return OUTPUT_ROUTE_SVD
            if stage == "animatediff":
                return OUTPUT_ROUTE_ANIMATEDIFF
            if stage in {"video_workflow", "movie_clips"}:
                return OUTPUT_ROUTE_PIPELINE
    if name == OUTPUT_ROUTE_MOVIE_CLIPS.lower():
        return OUTPUT_ROUTE_MOVIE_CLIPS
    if "learning_" in name:
        return OUTPUT_ROUTE_LEARNING
    if (
        "photooptimize" in name
        or "photooptimiz" in name
        or "photo_optimize" in name
        or "photo-optimize" in name
    ):
        return OUTPUT_ROUTE_PHOTO_OPTIMIZE
    if "reprocess" in name or "reviewreproc" in name:
        return OUTPUT_ROUTE_REPROCESS
    if name.startswith("svd_") or "_svd-" in name or "_svd_" in name or name.endswith("_svd"):
        return OUTPUT_ROUTE_SVD
    if "animatediff" in name:
        return OUTPUT_ROUTE_ANIMATEDIFF
    return OUTPUT_ROUTE_PIPELINE


def migrate_legacy_output_tree(base_output_dir: str | Path = "output") -> dict[str, list[str]]:
    root = get_output_root(base_output_dir, create=True)
    moved: list[str] = []
    skipped: list[str] = []

    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in KNOWN_OUTPUT_ROUTE_DIRS:
            continue
        route = classify_existing_output_dir(child)
        destination_root = get_output_route_root(root, route, create=True)
        destination = destination_root / child.name
        if destination.exists():
            skipped.append(str(child))
            continue
        shutil.move(str(child), str(destination))
        moved.append(f"{child.name} -> {route}")

    return {"moved": moved, "skipped": skipped}


def rebalance_output_tree(base_output_dir: str | Path = "output") -> dict[str, list[str]]:
    root = get_output_root(base_output_dir, create=True)
    moved: list[str] = []
    skipped: list[str] = []

    for route in KNOWN_OUTPUT_ROUTE_DIRS:
        route_root = root / route
        if not route_root.exists():
            continue
        for child in sorted(route_root.iterdir()):
            if not child.is_dir():
                continue
            target_route = classify_existing_output_dir(child)
            if target_route == route:
                continue
            destination_root = get_output_route_root(root, target_route, create=True)
            destination = destination_root / child.name
            if destination.exists():
                skipped.append(str(child))
                continue
            shutil.move(str(child), str(destination))
            moved.append(f"{child.name}: {route} -> {target_route}")

    return {"moved": moved, "skipped": skipped}
