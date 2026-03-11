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

import time
import uuid
from pathlib import Path
from typing import Any, Literal

from src.pipeline.job_models_v2 import (
    JobStatusV2,
    NormalizedJobRecord,
    StageConfig,
)


class ReprocessJobBuilder:
    """Build NormalizedJobRecords for reprocessing existing images.
    
    Creates jobs that skip txt2img and start from provided input images,
    running only the specified stages (e.g., adetailer, upscale).
    """
    
    # Valid stages for reprocessing (stages that can accept input images)
    VALID_REPROCESS_STAGES = {"img2img", "adetailer", "upscale"}
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
        stages: list[Literal["img2img", "adetailer", "upscale"]],
        config: dict[str, Any] | None = None,
        output_dir: str = "output",
        prompt: str = "",
        negative_prompt: str = "",
        model: str | None = None,
        pack_name: str = "Reprocess",
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
        
        # Build the NJR
        return NormalizedJobRecord(
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
            extra_metadata={
                "reprocess_mode": True,
                "original_image_count": len(path_strs),
                "reprocess_stages": list(stages),
            },
        )

    @staticmethod
    def _first_present(*values: Any, default: Any = None) -> Any:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return default

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
        stages: list[Literal["img2img", "adetailer", "upscale"]],
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
