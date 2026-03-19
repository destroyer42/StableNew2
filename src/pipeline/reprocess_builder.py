# Subsystem: Pipeline
# Role: Build reprocessing jobs from existing images

"""ReprocessJobBuilder: Create jobs to reprocess existing images through specific stages.

This module enables recovery/fix-up workflows where existing images (e.g., from txt2img)
are sent through later pipeline stages (e.g., adetailer, upscale) without regenerating.

Typical use cases:
- Fix faces on images that skipped adetailer due to a bug
- Upscale a batch of existing images
- Apply adetailer + upscale to txt2img outputs
"""

from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.pipeline.artifact_contract import extract_artifact_paths
from src.pipeline.job_models_v2 import (
    JobStatusV2,
    NormalizedJobRecord,
    StageConfig,
)
from src.pipeline.job_requests_v2 import PipelineRunMode, PipelineRunRequest, PipelineRunSource


REPROCESS_SCHEMA_VERSION = "stablenew.reprocess.v2.6"
IMAGE_EDIT_SCHEMA_VERSION = "stablenew.image_edit.v2.6"


@dataclass(slots=True)
class ImageEditSpec:
    mask_image_path: str
    operation: str = "masked_inpaint"
    mask_blur: int = 4
    inpaint_full_res: bool = True
    inpaint_full_res_padding: int = 32
    inpainting_fill: int = 1
    inpainting_mask_invert: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": IMAGE_EDIT_SCHEMA_VERSION,
            "operation": self.operation,
            "mask_image_path": self.mask_image_path,
            "mask_blur": self.mask_blur,
            "inpaint_full_res": self.inpaint_full_res,
            "inpaint_full_res_padding": self.inpaint_full_res_padding,
            "inpainting_fill": self.inpainting_fill,
            "inpainting_mask_invert": self.inpainting_mask_invert,
            "metadata": deepcopy(self.metadata or {}),
        }


@dataclass(slots=True)
class ReprocessSourceItem:
    input_image_path: str
    prompt: str = ""
    negative_prompt: str = ""
    model: str | None = None
    vae: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    output_dir: str | None = None
    image_edit: ImageEditSpec | None = None


@dataclass(slots=True)
class ReprocessJobPlan:
    jobs: list[NormalizedJobRecord] = field(default_factory=list)
    group_count: int = 0


class ReprocessJobBuilder:
    """Build NormalizedJobRecords for reprocessing existing images.
    
    Creates jobs that skip txt2img and start from provided input images,
    running only the specified stages (e.g., adetailer, upscale).
    """
    
    # Valid stages for reprocessing (stages that can accept input images)
    VALID_REPROCESS_STAGES = {"img2img", "adetailer", "upscale", "animatediff", "svd_native"}
    DEFAULT_STAGE_VALUES: dict[str, dict[str, Any]] = {
        "img2img": {
            "steps": 15,
            "cfg_scale": 7.0,
            "denoising_strength": 0.3,
            "sampler_name": "Euler a",
        },
        "adetailer": {
            "steps": 12,
            "cfg_scale": 5.7,
            "denoising_strength": 0.25,
            "sampler_name": "DPM++ 2M Karras",
        },
        "upscale": {
            "steps": 20,
            "cfg_scale": 7.0,
            "denoising_strength": 0.35,
            "sampler_name": "Euler a",
        },
        "animatediff": {
            "steps": 16,
            "cfg_scale": 7.0,
            "denoising_strength": 0.3,
            "sampler_name": "Euler a",
        },
        "svd_native": {
            "steps": 1,
            "cfg_scale": 1.0,
            "denoising_strength": 0.0,
            "sampler_name": "native",
        },
    }
    
    def __init__(
        self,
        time_fn=None,
        id_fn=None,
    ):
        """Initialize the builder.
        
        Args:
            time_fn: Function returning current timestamp. Defaults to time.time.
            id_fn: Function returning unique job ID. Defaults to uuid4().hex.
        """
        self._time_fn = time_fn or time.time
        self._id_fn = id_fn or (lambda: uuid.uuid4().hex)
    
    def build_reprocess_job(
        self,
        input_image_paths: list[str | Path],
        stages: list[Literal["img2img", "adetailer", "upscale", "animatediff", "svd_native"]],
        config: dict[str, Any] | None = None,
        output_dir: str = "output",
        prompt: str = "",
        negative_prompt: str = "",
        model: str | None = None,
        pack_name: str = "Reprocess",
        source: str = "reprocess",
        extra_metadata: dict[str, Any] | None = None,
    ) -> NormalizedJobRecord:
        """Build a single reprocessing job for a batch of images.
        
        Args:
            input_image_paths: List of paths to input images to reprocess.
            stages: List of stages to run, in order. Must be from VALID_REPROCESS_STAGES.
            config: Optional config dict with stage-specific settings (adetailer, upscale, etc.).
            output_dir: Output directory for processed images.
            prompt: Prompt to use for stages that need it (adetailer).
            negative_prompt: Negative prompt for stages that need it.
            model: Model name for reference (not used for upscale-only).
            pack_name: Pack name for folder organization.
            
        Returns:
            NormalizedJobRecord configured for reprocessing.
            
        Raises:
            ValueError: If no valid stages specified or no input images provided.
        """
        # Validate inputs
        if not input_image_paths:
            raise ValueError("At least one input image path is required")
        
        # Convert to strings and validate paths exist
        path_strs = []
        for p in input_image_paths:
            path = Path(p)
            if not path.exists():
                raise ValueError(f"Input image not found: {p}")
            path_strs.append(str(path))
        
        # Validate stages
        invalid_stages = set(stages) - self.VALID_REPROCESS_STAGES
        if invalid_stages:
            raise ValueError(f"Invalid reprocess stages: {invalid_stages}. Valid: {self.VALID_REPROCESS_STAGES}")
        if not stages:
            raise ValueError("At least one stage must be specified")
        
        # Build stage chain with only the requested stages
        stage_chain = []
        config = config or {}
        
        for stage_name in stages:
            stage_extra = config.get(stage_name, {})
            if not isinstance(stage_extra, dict):
                stage_extra = {}
            defaults = self.DEFAULT_STAGE_VALUES.get(stage_name, {})
            stage_config = StageConfig(
                stage_type=stage_name,
                enabled=True,
                steps=self._resolve_stage_steps(stage_name, config, stage_extra, defaults),
                cfg_scale=self._resolve_stage_cfg_scale(stage_name, config, stage_extra, defaults),
                denoising_strength=self._resolve_stage_denoise(stage_name, config, stage_extra, defaults),
                sampler_name=self._resolve_stage_sampler(stage_name, config, stage_extra, defaults),
                scheduler=self._resolve_stage_scheduler(stage_name, config, stage_extra),
                model=model,
                extra=stage_extra,
            )
            stage_chain.append(stage_config)
        
        # Determine start_stage (first stage in our chain)
        start_stage = stages[0]
        
        base_metadata = {
            "submission_source": str(source or "reprocess"),
            "reprocess_mode": True,
            "original_image_count": len(path_strs),
            "reprocess_stages": list(stages),
            "reprocess": {
                "schema": REPROCESS_SCHEMA_VERSION,
                "source": str(source or "reprocess"),
                "input_count": len(path_strs),
                "input_image_paths": list(path_strs),
                "requested_stages": list(stages),
            },
        }

        record = NormalizedJobRecord(
            job_id=self._id_fn(),
            config=config,
            path_output_dir=output_dir,
            filename_template="{seed}",
            seed=None,
            variant_index=0,
            variant_total=1,
            batch_index=0,
            batch_total=1,
            created_ts=self._time_fn(),
            prompt_pack_name=pack_name,
            prompt_pack_id=f"reprocess_{self._id_fn()[:8]}",
            positive_prompt=prompt,
            negative_prompt=negative_prompt,
            base_model=model or "",
            stage_chain=stage_chain,
            images_per_prompt=len(path_strs),
            input_image_paths=path_strs,
            start_stage=start_stage,
            status=JobStatusV2.QUEUED,
            extra_metadata=self._merge_nested_dicts(base_metadata, extra_metadata or {}),
        )
        record.prompt_source = "reprocess"  # type: ignore[attr-defined]
        return record

    @staticmethod
    def _first_present(*values: Any, default: Any = None) -> Any:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return default

    @staticmethod
    def _merge_nested_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = ReprocessJobBuilder._merge_nested_dicts(
                    dict(merged.get(key) or {}),
                    dict(value),
                )
            else:
                merged[key] = deepcopy(value)
        return merged

    @staticmethod
    def apply_model_vae_to_config(
        config: dict[str, Any],
        *,
        model: str | None,
        vae: str | None,
    ) -> None:
        if model:
            config["model"] = model
            txt2img_cfg = config.setdefault("txt2img", {})
            if isinstance(txt2img_cfg, dict):
                txt2img_cfg["model"] = model
            img2img_cfg = config.setdefault("img2img", {})
            if isinstance(img2img_cfg, dict):
                img2img_cfg["model"] = model
        if vae is not None:
            config["vae"] = vae
            txt2img_cfg = config.setdefault("txt2img", {})
            if isinstance(txt2img_cfg, dict):
                txt2img_cfg["vae"] = vae
            img2img_cfg = config.setdefault("img2img", {})
            if isinstance(img2img_cfg, dict):
                img2img_cfg["vae"] = vae

    @staticmethod
    def apply_prompt_overrides(
        config: dict[str, Any],
        *,
        stages: list[str],
        prompt: str,
        negative_prompt: str,
    ) -> None:
        if "adetailer" not in stages:
            return
        adetailer_cfg = config.setdefault("adetailer", {})
        if isinstance(adetailer_cfg, dict):
            adetailer_cfg["adetailer_prompt"] = prompt
            adetailer_cfg["adetailer_negative_prompt"] = negative_prompt
        config["adetailer_prompt"] = prompt
        config["adetailer_negative_prompt"] = negative_prompt

    @staticmethod
    def apply_image_edit_overrides(
        config: dict[str, Any],
        *,
        stages: list[str],
        image_edit: ImageEditSpec | None,
    ) -> None:
        if image_edit is None or "img2img" not in stages:
            return
        img2img_cfg = config.setdefault("img2img", {})
        if not isinstance(img2img_cfg, dict):
            img2img_cfg = {}
            config["img2img"] = img2img_cfg
        img2img_cfg.update(
            {
                "mask_image_path": image_edit.mask_image_path,
                "mask_blur": int(image_edit.mask_blur),
                "inpaint_full_res": bool(image_edit.inpaint_full_res),
                "inpaint_full_res_padding": int(image_edit.inpaint_full_res_padding),
                "inpainting_fill": int(image_edit.inpainting_fill),
                "inpainting_mask_invert": bool(image_edit.inpainting_mask_invert),
            }
        )

    def _resolve_stage_steps(
        self,
        stage_name: str,
        config: dict[str, Any],
        stage_extra: dict[str, Any],
        defaults: dict[str, Any],
    ) -> int:
        if stage_name == "adetailer":
            value = self._first_present(
                config.get("adetailer_steps"),
                stage_extra.get("adetailer_steps"),
                stage_extra.get("ad_steps"),
                config.get("steps"),
                stage_extra.get("steps"),
                default=defaults.get("steps", 1),
            )
        else:
            value = self._first_present(
                config.get(f"{stage_name}_steps"),
                stage_extra.get("steps"),
                config.get("steps"),
                default=defaults.get("steps", 1),
            )
        return int(value)

    def _resolve_stage_cfg_scale(
        self,
        stage_name: str,
        config: dict[str, Any],
        stage_extra: dict[str, Any],
        defaults: dict[str, Any],
    ) -> float:
        if stage_name == "adetailer":
            value = self._first_present(
                config.get("adetailer_cfg_scale"),
                stage_extra.get("adetailer_cfg"),
                stage_extra.get("ad_cfg_scale"),
                stage_extra.get("cfg_scale"),
                config.get("cfg_scale"),
                default=defaults.get("cfg_scale", 7.0),
            )
        else:
            value = self._first_present(
                config.get(f"{stage_name}_cfg_scale"),
                stage_extra.get("cfg_scale"),
                config.get("cfg_scale"),
                default=defaults.get("cfg_scale", 7.0),
            )
        return float(value)

    def _resolve_stage_denoise(
        self,
        stage_name: str,
        config: dict[str, Any],
        stage_extra: dict[str, Any],
        defaults: dict[str, Any],
    ) -> float:
        if stage_name == "adetailer":
            value = self._first_present(
                config.get("adetailer_denoising_strength"),
                stage_extra.get("adetailer_denoise"),
                stage_extra.get("ad_denoising_strength"),
                stage_extra.get("denoising_strength"),
                config.get("denoising_strength"),
                default=defaults.get("denoising_strength", 0.25),
            )
        else:
            value = self._first_present(
                config.get(f"{stage_name}_denoising_strength"),
                stage_extra.get("denoising_strength"),
                config.get("denoising_strength"),
                default=defaults.get("denoising_strength", 0.3),
            )
        return float(value)

    def _resolve_stage_sampler(
        self,
        stage_name: str,
        config: dict[str, Any],
        stage_extra: dict[str, Any],
        defaults: dict[str, Any],
    ) -> str:
        if stage_name == "adetailer":
            value = self._first_present(
                config.get("adetailer_sampler_name"),
                stage_extra.get("adetailer_sampler"),
                stage_extra.get("ad_sampler"),
                stage_extra.get("sampler_name"),
                config.get("sampler_name"),
                default=defaults.get("sampler_name", "Euler a"),
            )
        else:
            value = self._first_present(
                config.get(f"{stage_name}_sampler_name"),
                stage_extra.get("sampler_name"),
                config.get("sampler_name"),
                default=defaults.get("sampler_name", "Euler a"),
            )
        return str(value)

    def _resolve_stage_scheduler(
        self,
        stage_name: str,
        config: dict[str, Any],
        stage_extra: dict[str, Any],
    ) -> str | None:
        if stage_name == "adetailer":
            value = self._first_present(
                stage_extra.get("scheduler"),
                stage_extra.get("ad_scheduler"),
                config.get("scheduler"),
            )
        else:
            value = self._first_present(
                stage_extra.get("scheduler"),
                config.get("scheduler"),
            )
        return str(value) if value is not None else None
    
    def build_reprocess_jobs_batched(
        self,
        input_image_paths: list[str | Path],
        stages: list[Literal["img2img", "adetailer", "upscale", "animatediff", "svd_native"]],
        batch_size: int = 10,
        **kwargs,
    ) -> list[NormalizedJobRecord]:
        """Build multiple reprocessing jobs, batching input images.
        
        Useful for processing large numbers of images without overwhelming the queue.
        
        Args:
            input_image_paths: All input image paths.
            stages: Stages to run on each batch.
            batch_size: Maximum images per job.
            **kwargs: Additional args passed to build_reprocess_job.
            
        Returns:
            List of NormalizedJobRecords, one per batch.
        """
        jobs = []
        for i in range(0, len(input_image_paths), batch_size):
            batch = input_image_paths[i:i + batch_size]
            job = self.build_reprocess_job(
                input_image_paths=batch,
                stages=stages,
                **kwargs,
            )
            jobs.append(job)
        return jobs

    def build_grouped_reprocess_jobs(
        self,
        *,
        items: list[ReprocessSourceItem],
        stages: list[Literal["img2img", "adetailer", "upscale", "animatediff", "svd_native"]],
        fallback_config: dict[str, Any] | None = None,
        batch_size: int = 1,
        pack_name: str = "Reprocess",
        source: str = "reprocess",
        output_dir: str = "output",
        output_dir_factory=None,
        extra_metadata_builder=None,
    ) -> ReprocessJobPlan:
        if not items:
            return ReprocessJobPlan()
        if batch_size <= 0:
            raise ValueError("batch_size must be >= 1")

        grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        base_config = fallback_config or {}
        for item in items:
            merged_config = self._merge_nested_dicts(base_config, dict(item.config or {}))
            self.apply_model_vae_to_config(
                merged_config,
                model=item.model,
                vae=item.vae,
            )
            self.apply_prompt_overrides(
                merged_config,
                stages=list(stages),
                prompt=str(item.prompt or ""),
                negative_prompt=str(item.negative_prompt or ""),
            )
            self.apply_image_edit_overrides(
                merged_config,
                stages=list(stages),
                image_edit=item.image_edit,
            )
            resolved_output_dir = str(item.output_dir or output_dir)
            config_signature = json.dumps(merged_config, sort_keys=True, default=str)
            group_key = (
                str(item.prompt or ""),
                str(item.negative_prompt or ""),
                str(item.model or ""),
                config_signature,
                resolved_output_dir,
            )
            group = grouped.get(group_key)
            if group is None:
                group = {
                    "items": [],
                    "config": merged_config,
                    "prompt": str(item.prompt or ""),
                    "negative_prompt": str(item.negative_prompt or ""),
                    "model": item.model,
                    "output_dir": resolved_output_dir,
                }
                grouped[group_key] = group
            group["items"].append(item)

        jobs: list[NormalizedJobRecord] = []
        for group in grouped.values():
            group_items = list(group["items"])
            for idx in range(0, len(group_items), batch_size):
                chunk = group_items[idx : idx + batch_size]
                job_output_dir = (
                    str(output_dir_factory(chunk))
                    if callable(output_dir_factory)
                    else str(group["output_dir"])
                )
                chunk_metadata = {
                    "reprocess": {
                        "source_items": [
                            {
                                "input_image_path": str(item.input_image_path),
                                "prompt": str(item.prompt or ""),
                                "negative_prompt": str(item.negative_prompt or ""),
                                "model": str(item.model or ""),
                                "vae": item.vae,
                                "metadata": deepcopy(item.metadata or {}),
                                "image_edit": item.image_edit.to_dict() if item.image_edit else None,
                            }
                            for item in chunk
                        ]
                    }
                }
                if callable(extra_metadata_builder):
                    chunk_metadata = self._merge_nested_dicts(
                        chunk_metadata,
                        extra_metadata_builder(chunk, job_output_dir) or {},
                    )
                jobs.append(
                    self.build_reprocess_job(
                        input_image_paths=[item.input_image_path for item in chunk],
                        stages=stages,
                        config=group["config"],
                        output_dir=job_output_dir,
                        prompt=group["prompt"],
                        negative_prompt=group["negative_prompt"],
                        model=group["model"],
                        pack_name=pack_name,
                        source=source,
                        extra_metadata=chunk_metadata,
                    )
                )
        return ReprocessJobPlan(jobs=jobs, group_count=len(grouped))

    def build_run_request(
        self,
        njrs: list[NormalizedJobRecord],
        *,
        source: str,
        requested_job_label: str | None = None,
    ) -> PipelineRunRequest:
        if not njrs:
            raise ValueError("At least one reprocess NJR is required")
        output_dirs = {str(getattr(record, "path_output_dir", "") or "") for record in njrs}
        shared_output_dir = next(iter(output_dirs)) if len(output_dirs) == 1 else None
        prompt_pack_id = str(getattr(njrs[0], "prompt_pack_id", "") or f"reprocess_{source}")
        return PipelineRunRequest(
            prompt_pack_id=prompt_pack_id,
            selected_row_ids=[str(source or "reprocess")],
            config_snapshot_id=f"reprocess_{source}",
            run_mode=PipelineRunMode.QUEUE,
            source=PipelineRunSource.ADD_TO_QUEUE,
            explicit_output_dir=shared_output_dir,
            tags=["reprocess", str(source or "reprocess")],
            requested_job_label=requested_job_label or "Reprocess",
            max_njr_count=max(1, len(njrs)),
        )


def extract_reprocess_output_paths(record: Any, result: Any) -> list[str]:
    existing = list(getattr(record, "output_paths", []) or [])
    if existing:
        return [str(item) for item in existing if item]
    payload = result if isinstance(result, dict) else {}
    direct = payload.get("output_paths")
    if isinstance(direct, list) and direct:
        return [str(item) for item in direct if item]
    variants = payload.get("variants")
    if isinstance(variants, list) and variants:
        paths: list[str] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            for path in extract_artifact_paths(variant):
                if path and path not in paths:
                    paths.append(str(path))
        input_count = len(getattr(record, "input_image_paths", []) or [])
        if input_count > 0 and len(paths) > input_count:
            paths = paths[-input_count:]
        return paths
    return []


def create_adetailer_fixup_jobs(
    image_folder: str | Path,
    output_dir: str = "output",
    include_upscale: bool = True,
    adetailer_config: dict[str, Any] | None = None,
    upscale_config: dict[str, Any] | None = None,
    batch_size: int = 10,
) -> list[NormalizedJobRecord]:
    """Convenience function to create ADetailer fix-up jobs for a folder of images.
    
    Scans a folder for image files and creates reprocessing jobs to run them
    through ADetailer (and optionally upscale).
    
    Args:
        image_folder: Folder containing images to reprocess.
        output_dir: Where to save processed images.
        include_upscale: Whether to also run upscale after adetailer.
        adetailer_config: ADetailer settings (model, confidence, etc.).
        upscale_config: Upscale settings (upscaler, scale, etc.).
        batch_size: Images per job.
        
    Returns:
        List of reprocessing jobs ready for queue.
    """
    folder = Path(image_folder)
    if not folder.exists():
        raise ValueError(f"Image folder not found: {image_folder}")
    
    # Find all image files
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    image_files = [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in image_extensions
    ]
    
    if not image_files:
        raise ValueError(f"No images found in: {image_folder}")
    
    # Build config
    config = {}
    if adetailer_config:
        config["adetailer"] = adetailer_config
    if upscale_config:
        config["upscale"] = upscale_config
    
    # Determine stages
    stages: list[Literal["img2img", "adetailer", "upscale"]] = ["adetailer"]
    if include_upscale:
        stages.append("upscale")
    
    # Create jobs
    builder = ReprocessJobBuilder()
    return builder.build_reprocess_jobs_batched(
        input_image_paths=[str(f) for f in sorted(image_files)],
        stages=stages,
        batch_size=batch_size,
        config=config,
        output_dir=output_dir,
        pack_name=f"Reprocess_{folder.name}",
    )
