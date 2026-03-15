"""Controller surface for native SVD selected-image jobs."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.job_requests_v2 import PipelineRunMode, PipelineRunRequest, PipelineRunSource
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.state.output_routing import OUTPUT_ROUTE_SVD
from src.video.svd_config import SVDConfig
from src.video.svd_preprocess import validate_svd_source_image
from src.video.svd_service import SVDService


class SVDController:
    """Validates SVD requests and submits them through the normal queue path."""

    def __init__(self, *, app_controller, svd_service: SVDService | None = None) -> None:
        self._app_controller = app_controller
        self._svd_service = svd_service or SVDService()

    def validate_source_image(self, path: str | Path) -> tuple[bool, str | None]:
        try:
            validate_svd_source_image(path)
            available, reason = self._svd_service.is_available()
            if not available:
                return False, reason or "SVD runtime is unavailable"
            return True, None
        except Exception as exc:
            return False, str(exc)

    def build_svd_config(self, form_data: dict[str, object]) -> SVDConfig:
        return SVDConfig.from_dict(form_data)

    def clear_model_cache(self, *, model_id: str | None = None) -> None:
        self._svd_service.clear_model_cache(model_id=model_id)

    def submit_svd_job(
        self,
        *,
        source_image_path: str | Path,
        config: SVDConfig,
        output_route: str | None = None,
    ) -> str:
        builder = ReprocessJobBuilder()
        output_dir = getattr(self._app_controller, "output_dir", None) or "output"
        source_name = Path(source_image_path).stem.replace("_", " ").strip() or "selected image"
        route_name = str(output_route or OUTPUT_ROUTE_SVD).strip() or OUTPUT_ROUTE_SVD
        njr = builder.build_reprocess_job(
            input_image_paths=[str(source_image_path)],
            stages=["svd_native"],
            config={
                "svd_native": config.to_dict(),
                "pipeline": {"output_route": route_name},
            },
            output_dir=str(output_dir),
            prompt=f"SVD animation source: {source_name}",
            negative_prompt="",
            pack_name="SVD",
        )

        job_service = getattr(self._app_controller, "job_service", None)
        if job_service is None:
            raise RuntimeError("App controller is missing job_service")

        request = PipelineRunRequest(
            prompt_pack_id="svd_native",
            selected_row_ids=["svd_native"],
            config_snapshot_id="svd_native",
            run_mode=PipelineRunMode.QUEUE,
            source=PipelineRunSource.ADD_TO_QUEUE,
            requested_job_label="SVD Img2Vid",
            explicit_output_dir=str(output_dir),
            tags=["svd_native"],
            allow_legacy_fallback=False,
        )
        job_ids = job_service.enqueue_njrs([njr], request)
        if not job_ids:
            raise RuntimeError("Failed to enqueue SVD job")
        return job_ids[0]
