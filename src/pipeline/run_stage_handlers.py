"""Per-stage execution handlers for ``PipelineRunner.run_njr`` (roadmap P4-1).

``run_njr`` stays the only public entry point and is orchestration only: it resolves the run directory, walks the
enabled stages of the RunPlan, asks ``resolve_stage_handler`` for the handler of each stage and records the outcome.
A handler turns "the images the previous stage produced" into "the images this stage produced"; it returns ``None`` when
the stage must be skipped (nothing to process), which the runner treats exactly like the old ``continue``.

There are four handlers:

* ``Txt2ImgHandler``: generates the first images of a job.
* ``PerImageStageHandler``: img2img, adetailer and upscale.  They only differ by a ``PerImageStageSpec`` (which
  adaptive-refinement modes apply to the stage, whether the VRAM is freed around reprocess images, ...).
* ``VideoStageHandler``: video stages, delegating to the runner's video/sequence executors.
* ``MovieAssemblyHandler``: ``movie_assembly`` (PR-VID-ASM-332), FFmpeg assembly of existing outputs from the NJR's
  frozen spec; no backend, model or GPU.

Handlers reach the runner's helpers through the runner instance (``runner._execute_image_backend``, ...), so the existing
test seams keep working and no second execution path exists: every image is still produced by
``PipelineRunner._execute_image_backend``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.learning.experiment_naming import build_learning_filename_prefix
from src.pipeline.njr_core_v26 import thaw_json
from src.utils.file_io import build_safe_image_name

logger = logging.getLogger(__name__)

_MAX_NAME_LENGTH = 100  # conservative limit for Windows paths
_ORIGINAL_STEM_CHARS = 30


@dataclass
class StageRunContext:
    """Everything one run shares across its stages.  ``variants`` and ``metadata`` are mutated by handlers."""

    runner: Any
    njr: Any
    plan: Any
    run_dir: Path
    image_backend_id: str
    cancel_token: Any
    survivor_telemetry: Any
    prompt: str
    negative_prompt: str
    adaptive_refinement_intent: dict[str, Any]
    learning_context: Any
    client: Any
    variants: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: The images the last completed stage produced (the next stage's input); the run's outputs when it finishes.
    paths: list[str] = field(default_factory=list)
    #: The stage being (or last) started, for error reporting.
    current_stage_name: str = ""


class StageHandler:
    """Protocol-style base: ``run`` returns the next stage's input paths, or ``None`` to skip the stage."""

    def run(self, ctx: StageRunContext, stage: Any, paths: list[str]) -> list[str] | None:
        raise NotImplementedError


def _prompt_row(njr: Any) -> int:
    return getattr(njr, "prompt_pack_row_index", 0) or 0


def _pack_name(njr: Any) -> Any:
    return getattr(njr, "prompt_pack_name", None) or getattr(njr, "pack_name", None)


def _matrix_values(njr: Any) -> Any:
    return getattr(njr, "matrix_slot_values", None) if hasattr(njr, "matrix_slot_values") else None


class Txt2ImgHandler(StageHandler):
    def run(self, ctx: StageRunContext, stage: Any, paths: list[str]) -> list[str] | None:
        runner, njr = ctx.runner, ctx.njr
        learning_context = ctx.learning_context
        image_count = max(1, int(njr.images_per_prompt or 1))
        config_dict = runner._stage_config_for_njr(njr, "txt2img")
        prompt_row = _prompt_row(njr)

        # 1-based indexing to match the GUI display (p01 = "Prompt 1", v01 = "Variant 1").
        if learning_context:
            learning_meta = thaw_json(getattr(njr, "extra_metadata", {})).get("learning", {})
            base_prefix = build_learning_filename_prefix(
                stage=stage.stage_name,
                variable=learning_context.variable_under_test,
                value=learning_context.variant_value,
                variant_index=learning_context.variant_index,
                prompt_source=dict(learning_meta.get("prompt_source", {})),
                model=str(config_dict.get("model") or ""),
                timestamp=str(learning_meta.get("experiment_timestamp", "")),
            )
        else:
            base_prefix = f"{stage.stage_name}_p{prompt_row + 1:02d}_v{njr.variant_index + 1:02d}"
        seed = (njr.config or {}).get("seed") or getattr(njr, "extra_metadata", {}).get("seed")
        image_name = build_safe_image_name(
            base_prefix=base_prefix,
            matrix_values=_matrix_values(njr),
            seed=seed,
            pack_name=_pack_name(njr),
            max_length=_MAX_NAME_LENGTH,
        )

        result = runner._execute_image_backend(
            backend_id=ctx.image_backend_id,
            stage_name="txt2img",
            njr=njr,
            stage_config=config_dict,
            run_dir=ctx.run_dir,
            input_image_path=None,
            image_name=image_name,
            prompt=stage.prompt_text,
            negative_prompt=ctx.negative_prompt,
            cancel_token=ctx.cancel_token,
            survivor_telemetry=ctx.survivor_telemetry,
            selected_model=runner._selected_stage_model("txt2img", config_dict, njr=njr),
            selected_vae=runner._selected_stage_vae("txt2img", config_dict, njr=njr),
            learning_sample_names=bool(learning_context),
            image_count=image_count,
        )
        # Every image path is carried forward (batch processing).
        if result and "all_paths" in result:
            next_paths = result["all_paths"]
            logger.info("[pipeline/txt2img] produced %s image(s)", len(next_paths))
        elif result and "path" in result:
            next_paths = [result["path"]]  # single image (backward compatibility)
        else:
            next_paths = []
        if result is not None:
            ctx.variants.append(result)
        return next_paths


@dataclass(frozen=True)
class PerImageStageSpec:
    """How one image-to-image style stage differs from the others."""

    stage_name: str
    #: Adaptive-refinement modes under which this stage consults the refinement policy (empty: never).
    refinement_modes: frozenset[str] = frozenset()
    #: Name of the runner method that applies a decision bundle's overrides to the per-image config.
    apply_overrides: str | None = None
    #: Reprocess jobs free VRAM before each image after the first / between images to avoid backend timeouts.
    free_vram_before: bool = False
    free_vram_after: bool = False
    #: Whether recorded refinement decisions name the stage.
    decision_names_stage: bool = False
    #: Whether a missing output is logged as a warning and a produced one as an info line.
    log_outputs: bool = False


IMG2IMG_SPEC = PerImageStageSpec(stage_name="img2img")
ADETAILER_SPEC = PerImageStageSpec(
    stage_name="adetailer",
    refinement_modes=frozenset({"adetailer", "full"}),
    apply_overrides="_apply_adetailer_refinement_overrides",
    free_vram_before=True,
    free_vram_after=True,
    log_outputs=True,
)
UPSCALE_SPEC = PerImageStageSpec(
    stage_name="upscale",
    refinement_modes=frozenset({"full"}),
    apply_overrides="_apply_upscale_refinement_overrides",
    free_vram_before=True,
    decision_names_stage=True,
    log_outputs=True,
)


class PerImageStageHandler(StageHandler):
    """Runs one stage over every image the previous stage produced (img2img, adetailer, upscale)."""

    def __init__(self, spec: PerImageStageSpec) -> None:
        self._spec = spec

    def run(self, ctx: StageRunContext, stage: Any, paths: list[str]) -> list[str] | None:
        spec = self._spec
        name = spec.stage_name
        runner, njr = ctx.runner, ctx.njr
        if not paths:
            logger.warning("%s stage skipped: no input images from previous stage", name)
            return None

        config_dict = runner._stage_config_for_njr(njr, name)
        intent = ctx.adaptive_refinement_intent
        refinement_mode = str(intent.get("mode") or "disabled")
        refinement_enabled = bool(spec.refinement_modes) and (
            bool(intent.get("enabled")) and refinement_mode in spec.refinement_modes
        )
        refinement_prompt_intent: dict[str, Any] = {}
        refinement_service = None
        refinement_notes: list[str] = []
        if spec.refinement_modes:
            refinement_prompt_intent = dict(
                (ctx.metadata.get("adaptive_refinement") or {}).get("prompt_intent") or {}
            )
            refinement_service, refinement_notes = runner._resolve_refinement_policy_service(
                intent.get("detector_preference", "null")
            )
            if refinement_enabled and ctx.metadata.get("adaptive_refinement"):
                ctx.metadata["adaptive_refinement"]["detector_notes"] = list(
                    dict.fromkeys(
                        list(ctx.metadata["adaptive_refinement"].get("detector_notes") or [])
                        + refinement_notes
                    )
                )
                ctx.metadata["adaptive_refinement"].setdefault("image_decisions", [])

        prompt_row = _prompt_row(njr)
        base_prefix = f"{name}_p{prompt_row + 1:02d}_v{njr.variant_index + 1:02d}"
        matrix_values = _matrix_values(njr)
        pack_name = _pack_name(njr)
        # Reprocess jobs include the original input filename so outputs of different inputs never collide.
        original_inputs = getattr(njr, "input_image_paths", None)
        use_original_name = original_inputs and getattr(njr, "start_stage", None)

        next_paths: list[str] = []
        for img_idx, input_path in enumerate(paths):
            logger.debug("[pipeline/%s] processing image %s/%s", name, img_idx + 1, len(paths))
            if spec.free_vram_before and use_original_name and img_idx > 0:
                self._free_vram(ctx, f"[pipeline/{name}] freeing VRAM before image", settle=True)

            if use_original_name and img_idx < len(original_inputs):
                input_stem = Path(original_inputs[img_idx]).stem[:_ORIGINAL_STEM_CHARS]
                unique_prefix = f"{base_prefix}_{input_stem}"
            else:
                unique_prefix = base_prefix
            image_name = build_safe_image_name(
                base_prefix=unique_prefix,
                matrix_values=matrix_values,
                seed=None,
                batch_index=img_idx,
                pack_name=pack_name,
                max_length=_MAX_NAME_LENGTH,
            )

            stage_config = config_dict
            image_refinement_payload: dict[str, Any] | None = None
            if spec.refinement_modes:
                stage_config = dict(config_dict)
                if refinement_enabled:
                    decision_bundle = refinement_service.build_bundle(
                        mode=refinement_mode,
                        prompt_intent=refinement_prompt_intent,
                        image_path=Path(input_path),
                        extra_observation={
                            "stage_name": name,
                            "image_index": img_idx,
                            "total_images": len(paths),
                        },
                    )
                    image_refinement_payload = {
                        "intent": dict(intent),
                        "prompt_intent": dict(refinement_prompt_intent),
                        "decision_bundle": dict(decision_bundle),
                        "detector_notes": list(refinement_notes),
                    }
                    getattr(runner, spec.apply_overrides)(
                        stage_config, decision_bundle.get("applied_overrides")
                    )
                    stage_config["adaptive_refinement"] = image_refinement_payload

            result = runner._execute_image_backend(
                backend_id=ctx.image_backend_id,
                stage_name=name,
                njr=njr,
                stage_config=stage_config,
                run_dir=ctx.run_dir,
                input_image_path=Path(input_path),
                image_name=image_name,
                prompt=ctx.prompt,
                negative_prompt=ctx.negative_prompt,
                cancel_token=ctx.cancel_token,
                survivor_telemetry=ctx.survivor_telemetry,
                selected_model=runner._selected_stage_model(name, config_dict, njr=njr),
                selected_vae=runner._selected_stage_vae(name, config_dict, njr=njr),
            )

            produced = bool(result and "path" in result)
            if produced:
                if spec.log_outputs:
                    logger.info("[pipeline/%s] saved output=%s", name, result["path"])
                next_paths.append(result["path"])
            elif spec.log_outputs:
                logger.warning("[pipeline/%s] no output from image index=%s", name, img_idx)
            if (
                spec.refinement_modes
                and refinement_enabled
                and ctx.metadata.get("adaptive_refinement")
                and image_refinement_payload
            ):
                decision: dict[str, Any] = {}
                if spec.decision_names_stage:
                    decision["stage_name"] = name
                decision["input_image_path"] = str(input_path)
                decision["output_path"] = str(result["path"]) if produced else None
                decision["decision_bundle"] = dict(
                    image_refinement_payload.get("decision_bundle") or {}
                )
                ctx.metadata["adaptive_refinement"]["image_decisions"].append(decision)
            ctx.variants.append(result)

            if spec.free_vram_after and use_original_name and img_idx < len(paths) - 1:
                self._free_vram(ctx, f"[pipeline/{name}] freeing VRAM between images", settle=False)

        logger.info("[pipeline/%s] completed %s image(s)", name, len(next_paths))
        return next_paths

    @staticmethod
    def _free_vram(ctx: StageRunContext, message: str, *, settle: bool) -> None:
        try:
            client = ctx.client
            if client and hasattr(client, "free_vram"):
                logger.info(message)
                client.free_vram(unload_model=True)
                if settle:
                    time.sleep(1.0)  # give the WebUI time to stabilize
        except Exception:  # noqa: BLE001 - non-fatal housekeeping
            logger.debug("free_vram failed", exc_info=True)


class VideoStageHandler(StageHandler):
    def run(self, ctx: StageRunContext, stage: Any, paths: list[str]) -> list[str] | None:
        runner, njr = ctx.runner, ctx.njr
        if not paths:
            logger.warning(
                "%s stage skipped: no input images from previous stage", stage.stage_name
            )
            return None
        stage_cfg = runner._stage_config_dict_for_video(njr, stage.stage_name)
        sequence_config = stage_cfg.get("sequence_metadata") or {}
        if (
            stage.stage_name == "video_workflow"
            and isinstance(sequence_config, dict)
            and int(sequence_config.get("total_segments", 1)) > 1
        ):
            next_paths = runner._execute_sequence(
                stage_name=stage.stage_name,
                njr=njr,
                current_stage_paths=paths,
                sequence_config=sequence_config,
                run_dir=ctx.run_dir,
                cancel_token=ctx.cancel_token,
                variants=ctx.variants,
                metadata=ctx.metadata,
                survivor_telemetry=ctx.survivor_telemetry,
            )
        else:
            next_paths = runner._execute_video_stage(
                stage_name=stage.stage_name,
                njr=njr,
                current_stage_paths=paths,
                prompt=ctx.prompt,
                negative_prompt=ctx.negative_prompt,
                run_dir=ctx.run_dir,
                cancel_token=ctx.cancel_token,
                variants=ctx.variants,
                metadata=ctx.metadata,
                survivor_telemetry=ctx.survivor_telemetry,
            )
        logger.info(
            "[BATCH_PIPELINE] %s completed %d output artifact(s)", stage.stage_name, len(next_paths)
        )
        return next_paths


class MovieAssemblyHandler(StageHandler):
    """Assemble the frozen clips into one movie and record it like any other video artifact."""

    def run(self, ctx: StageRunContext, stage: Any, paths: list[str]) -> list[str] | None:
        from src.pipeline.artifact_contract import build_artifact_record
        from src.video.movie_assembly_engine import ENGINE_ID, run_movie_assembly
        from src.video.movie_assembly_models import MOVIE_ASSEMBLY_STAGE, MovieAssemblySpec
        from src.video.video_artifact_helpers import build_video_artifact_bundle

        njr = ctx.njr
        spec = MovieAssemblySpec.from_dict(njr.config.get(MOVIE_ASSEMBLY_STAGE) or {})
        if [str(path) for path in paths] != [clip.path for clip in spec.clips]:
            raise ValueError(
                "The job's input files and its frozen movie assembly disagree; it cannot run."
            )
        outcome = run_movie_assembly(
            spec, run_dir=ctx.run_dir, cancel_token=ctx.cancel_token, job_id=str(njr.job_id)
        )
        output = str(outcome.output_path)
        manifest = str(outcome.manifest_path)
        record = build_artifact_record(
            stage=MOVIE_ASSEMBLY_STAGE,
            artifact_type="video",
            primary_path=output,
            output_paths=[output],
            manifest_path=manifest,
            input_image_path=spec.clips[0].path,
            job_id=str(njr.job_id),
        )
        aggregate = build_video_artifact_bundle(
            stage=MOVIE_ASSEMBLY_STAGE,
            backend_id=ENGINE_ID,
            primary_path=output,
            output_paths=[output],
            video_paths=[output],
            manifest_path=manifest,
            source_image_path=spec.clips[0].path,
            artifact_records=[record],
        )
        timeline = outcome.timeline
        aggregate["assembly"] = {
            "clip_count": len(spec.clips),
            "total_frames": timeline.total_frames,
            "duration_seconds": round(timeline.duration_seconds, 6),
            "width": spec.width,
            "height": spec.height,
            "fps": timeline.fps,
            "output_sha256": outcome.output_sha256,
        }
        metadata = ctx.metadata
        metadata.setdefault("video_artifacts", {})[MOVIE_ASSEMBLY_STAGE] = dict(aggregate)
        metadata["video_primary_artifact"] = dict(aggregate)
        metadata["video_primary_backend_id"] = ENGINE_ID
        metadata["video_primary_stage"] = MOVIE_ASSEMBLY_STAGE
        metadata["movie_assembly_artifact"] = dict(aggregate)
        ctx.variants.append(
            {
                "stage": MOVIE_ASSEMBLY_STAGE,
                "backend_id": ENGINE_ID,
                "path": output,
                "output_path": output,
                "output_paths": [output],
                "video_path": output,
                "manifest_path": manifest,
                "artifact": record,
            }
        )
        logger.info(
            "[BATCH_PIPELINE] movie_assembly wrote %s (%d frames)", output, timeline.total_frames
        )
        return [output]


_IMAGE_HANDLERS: Mapping[str, StageHandler] = {
    "txt2img": Txt2ImgHandler(),
    "img2img": PerImageStageHandler(IMG2IMG_SPEC),
    "adetailer": PerImageStageHandler(ADETAILER_SPEC),
    "upscale": PerImageStageHandler(UPSCALE_SPEC),
}
_VIDEO_HANDLER = VideoStageHandler()
_ASSEMBLY_HANDLER = MovieAssemblyHandler()


def resolve_stage_handler(
    stage_name: str, is_video_stage: Callable[[str], bool]
) -> StageHandler | None:
    """The handler for ``stage_name`` or ``None`` for an unknown stage (the runner logs and skips it)."""

    handler = _IMAGE_HANDLERS.get(stage_name)
    if handler is not None:
        return handler
    if stage_name == "movie_assembly":
        return _ASSEMBLY_HANDLER
    if is_video_stage(stage_name):
        return _VIDEO_HANDLER
    return None


__all__ = [
    "ADETAILER_SPEC",
    "IMG2IMG_SPEC",
    "UPSCALE_SPEC",
    "MovieAssemblyHandler",
    "PerImageStageHandler",
    "PerImageStageSpec",
    "StageHandler",
    "StageRunContext",
    "Txt2ImgHandler",
    "VideoStageHandler",
    "resolve_stage_handler",
]
