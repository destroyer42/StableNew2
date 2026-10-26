"""Prepare Photo Optimize intent using the existing reprocess compiler only."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from src.pipeline.reprocess_builder import (
    ReprocessJobBuilder,
    ReprocessJobPlan,
    ReprocessSourceItem,
)
from src.review.workflow_adapter import ReviewWorkflowAdapter

from .models import PhotoOptimizeBaseline
from .settings import STAGES, normalize_settings, resolve_geometry, validate_settings


def pipeline_defaults(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or not any(
        isinstance(config.get(stage), dict) for stage in STAGES
    ):
        raise ValueError("Live Pipeline stage settings are unavailable; open Pipeline and retry")
    captured_config = deepcopy(config)
    config = normalize_settings(config)
    img = config["img2img"]
    txt = config.get("txt2img", {})

    def identity(key):
        return next(
            (
                str(section[key])
                for section in (img, txt, config)
                if key in section and section[key] is not None
                and (key != "model" or str(section[key]).strip())
            ),
            "",
        )

    return {
        "prompt": "",
        "negative_prompt": "",
        "model": identity("model"),
        "vae": identity("vae"),
        "stage_defaults": {
            stage: bool(config[stage].get("enabled", stage == "img2img")) for stage in STAGES
        },
        "config": config,
        "source": "pipeline_copy",
        "captured_config": captured_config,
    }


def prepare_photo_plan(
    *,
    assets: list[dict[str, Any]],
    stages: list[str],
    fallback_config: dict[str, Any],
    store: Any,
    batch_size: int,
    prompt_delta: str = "",
    negative_prompt_delta: str = "",
    prompt_mode: str = "append",
    negative_prompt_mode: str = "append",
) -> ReprocessJobPlan:
    if not assets:
        raise ValueError("No photo assets were provided for optimization")
    if prompt_mode not in {"append", "replace", "modify"} or negative_prompt_mode not in {
        "append",
        "replace",
        "modify",
    }:
        raise ValueError("Prompt modes must be append, replace, or modify")
    if isinstance(batch_size, bool) or not 1 <= batch_size <= 64:
        raise ValueError("Batch size must be between 1 and 64")
    builder = ReprocessJobBuilder()
    partitions: dict[tuple[str, ...], list[ReprocessSourceItem]] = {}
    seen = set()
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id or asset_id in seen:
            raise ValueError("Photo selection contains a missing or duplicate asset identity")
        seen.add(asset_id)
        if asset.get("archived"):
            raise ValueError(f"Restore archived photo {asset_id} before optimizing")
        raw = asset.get("baseline") or {}
        if hasattr(raw, "to_dict"):
            raw = raw.to_dict()
        baseline = PhotoOptimizeBaseline.from_dict(raw)
        requested = asset.get("stages")
        if requested is None:
            requested = (
                [stage for stage in STAGES if baseline.stage_defaults.get(stage, False)]
                if "stage_defaults" in raw
                else stages
            )
        if not requested or set(requested) - set(STAGES):
            raise ValueError(f"Photo {asset_id} requires at least one valid stage")
        stage_plan = tuple(stage for stage in STAGES if stage in requested)
        path = str(
            asset.get("input_image_path")
            or baseline.working_image_path
            or asset.get("managed_original_path")
            or ""
        )
        # Normalize each authority before merging: a stored flat legacy value must
        # beat a fallback nested value, while explicit nested values beat aliases.
        merged = builder._merge_nested_dicts(
            normalize_settings(fallback_config, defaults=False),
            normalize_settings(baseline.config, defaults=False),
        )
        baseline.config = merged
        config = resolve_geometry(baseline, path)
        validate_settings(config)
        model = (baseline.model or pipeline_defaults(fallback_config)["model"]) if "model" in raw else str(
            config.get("model")
            or config.get("img2img", {}).get("model")
            or config.get("txt2img", {}).get("model")
            or ""
        )
        # Empty VAE explicitly means Automatic; it must not inherit the live VAE.
        vae = baseline.vae if "vae" in raw else str(config.get("vae") or "")
        builder.apply_model_vae_to_config(config, model=model or None, vae=vae)
        positive = ReviewWorkflowAdapter.apply_prompt_delta(
            baseline.prompt, prompt_delta, prompt_mode
        )
        negative = ReviewWorkflowAdapter.apply_prompt_delta(
            baseline.negative_prompt, negative_prompt_delta, negative_prompt_mode
        )
        builder.apply_prompt_overrides(
            config, stages=list(stage_plan), prompt=positive, negative_prompt=negative
        )
        partitions.setdefault(stage_plan, []).append(
            ReprocessSourceItem(
                input_image_path=path,
                prompt=positive,
                negative_prompt=negative,
                model=model or None,
                vae=vae,
                config=config,
                metadata={
                    "photo_asset": {
                        "asset_id": asset_id,
                        "input_image_path": path,
                        "effective_prompt": positive,
                        "effective_negative_prompt": negative,
                        "config_snapshot": deepcopy(config),
                        "stages": list(stage_plan),
                        "geometry_policy": baseline.geometry_policy,
                    }
                },
            )
        )
    result = ReprocessJobPlan()
    for stage_plan, items in partitions.items():

        def metadata(chunk, output_dir, stage_plan=stage_plan):
            return {
                "photo_optimize": {
                    "source": "photo_optimize_tab",
                    "run_id": Path(output_dir).name,
                    "stages": list(stage_plan),
                    "prompt_mode": prompt_mode,
                    "prompt_delta": prompt_delta,
                    "negative_prompt_mode": negative_prompt_mode,
                    "negative_prompt_delta": negative_prompt_delta,
                    "assets": [deepcopy(item.metadata["photo_asset"]) for item in chunk],
                }
            }

        plan = builder.build_grouped_reprocess_jobs(
            items=items,
            stages=list(stage_plan),
            fallback_config={},
            batch_size=batch_size,
            pack_name="PhotoOptimize",
            source="photo_optimize_tab",
            output_dir_factory=lambda chunk: str(store.create_staging_run_dir("photo_optimize")),
            extra_metadata_builder=metadata,
        )
        result.jobs.extend(plan.jobs)
        result.group_count += plan.group_count
    # Freeze metadata from the actual compiler output (including profile handling).
    for job in result.jobs:
        for info in job.extra_metadata["photo_optimize"]["assets"]:
            if info["config_snapshot"] != job.config:
                raise ValueError(
                    "Photo model profile changed requested settings; choose a supported workload"
                )
    return result


def describe_photo_plan(plan: ReprocessJobPlan) -> str:
    photos = sum(len(job.input_image_paths) for job in plan.jobs)
    targets = []
    for job in plan.jobs:
        config = job.config
        img = config["img2img"]
        stages = ", ".join(
            f"{stage.stage_type}: {stage.steps} steps / CFG {stage.cfg_scale} / denoise {stage.denoising_strength} / {stage.sampler_name} / {stage.scheduler or 'sampler default'}"
            for stage in job.stage_chain
        )
        target = (
            f"{len(job.input_image_paths)} photo(s): {img['width']} x {img['height']} | "
            f"{config.get('model') or 'Pipeline model'} | VAE {config.get('vae') or 'Automatic'} | {stages}"
        )
        if "upscale" in [stage.stage_type for stage in job.stage_chain]:
            target += (
                f" | {config['upscale']['upscaler']} x {config['upscale']['upscaling_resize']}"
            )
        targets.append(target)
    return (
        f"{photos} photos / {len(plan.jobs)} jobs / {plan.group_count} compatible groups.\n"
        + "\n".join(targets)
    )
