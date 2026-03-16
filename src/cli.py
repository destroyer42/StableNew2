"""Command-line interface for StableNew"""

import argparse
import logging
from pathlib import Path

from .api import SDWebUIClient
from .pipeline import PipelineRunner, VideoCreator
from .pipeline.cli_njr_builder import build_cli_njr
from .utils import ConfigManager, StructuredLogger, find_webui_api_port, setup_logging


def _collect_video_source_paths(result_variants: list[dict[str, object]]) -> list[Path]:
    preferred_stages = ("upscale", "adetailer", "img2img", "txt2img")
    by_stage: dict[str, list[Path]] = {stage: [] for stage in preferred_stages}

    for variant in result_variants:
        if not isinstance(variant, dict):
            continue
        stage = str(variant.get("stage", "") or "")
        if stage not in by_stage:
            continue
        all_paths = variant.get("all_paths")
        if isinstance(all_paths, list):
            for value in all_paths:
                if value:
                    by_stage[stage].append(Path(str(value)))
            continue
        path_value = variant.get("path")
        if path_value:
            by_stage[stage].append(Path(str(path_value)))

    for stage in preferred_stages:
        paths = [path for path in by_stage[stage] if path]
        if paths:
            return paths
    return []


def main():
    """CLI main function"""
    parser = argparse.ArgumentParser(
        description="StableNew - Stable Diffusion WebUI Automation CLI"
    )

    parser.add_argument(
        "--prompt", type=str, required=True, help="Text prompt for image generation"
    )

    parser.add_argument(
        "--preset", type=str, default="default", help="Configuration preset name (default: default)"
    )

    parser.add_argument(
        "--batch-size", type=int, default=1, help="Number of images to generate (default: 1)"
    )

    parser.add_argument("--run-name", type=str, help="Optional name for this run")

    parser.add_argument(
        "--api-url",
        type=str,
        default="http://127.0.0.1:7860",
        help="SD WebUI API URL (default: http://127.0.0.1:7860)",
    )

    parser.add_argument("--no-img2img", action="store_true", help="Skip img2img cleanup stage")

    parser.add_argument("--no-upscale", action="store_true", help="Skip upscaling stage")

    parser.add_argument(
        "--create-video", action="store_true", help="Create video from generated images"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("StableNew CLI - Starting")
    logger.info("=" * 60)

    # Initialize components
    config_manager = ConfigManager()
    structured_logger = StructuredLogger()

    # Load configuration
    config = config_manager.load_preset(args.preset)
    if not config:
        logger.error(f"Failed to load preset: {args.preset}")
        logger.info("Using default configuration")
        config = config_manager.get_default_config()

    # Modify config based on arguments
    if args.no_img2img:
        config.pop("img2img", None)
        config.setdefault("pipeline", {})["img2img_enabled"] = False
        logger.info("img2img stage disabled")

    if args.no_upscale:
        config.pop("upscale", None)
        config.setdefault("pipeline", {})["upscale_enabled"] = False
        logger.info("Upscale stage disabled")

    # Modify config based on arguments
    if args.api_url:
        config["api"]["base_url"] = args.api_url

    # Initialize API client with port discovery
    api_url = config["api"]["base_url"]
    logger.info("Connecting to SD WebUI API...")

    # Try to find the actual API port if using default
    if api_url == "http://127.0.0.1:7860":
        discovered_url = find_webui_api_port()
        if discovered_url:
            logger.info(f"Found WebUI API at {discovered_url}")
            api_url = discovered_url
        else:
            logger.info(f"Using configured URL: {api_url}")

    client = SDWebUIClient(base_url=api_url, timeout=config["api"]["timeout"])

    # Check API readiness
    logger.info("Checking API readiness...")
    if not client.check_api_ready():
        logger.error("SD WebUI API is not ready. Exiting.")
        logger.info("Common ports to check: 7860, 7861, 7862, 7863, 7864")
        return 1

    runner = PipelineRunner(client, structured_logger)

    # Run pipeline
    try:
        njr = build_cli_njr(
            prompt=args.prompt,
            config=config,
            batch_size=args.batch_size,
            run_name=args.run_name,
        )
        result = runner.run_njr(njr, cancel_token=None)
        if not result.success:
            logger.error("Pipeline failed: %s", result.error or "unknown error")
            return 1

        output_dir = Path(str(result.metadata.get("output_dir") or "output"))
        variants = [variant for variant in result.variants if isinstance(variant, dict)]

        logger.info("=" * 60)
        logger.info("Pipeline Results:")
        logger.info(f"  Run directory: {output_dir}")
        logger.info(f"  Run ID: {result.run_id}")
        logger.info(f"  Variant records: {len(variants)}")
        logger.info(f"  Final outputs: {len(njr.output_paths)}")
        logger.info("=" * 60)

        # Create video if requested
        if args.create_video:
            logger.info("Creating video...")
            video_creator = VideoCreator()
            video_paths = _collect_video_source_paths(variants)
            if video_paths:
                video_dir = output_dir / "video"
                video_dir.mkdir(parents=True, exist_ok=True)
                video_path = video_dir / "cli_video.mp4"
                if video_creator.create_video_from_images(
                    video_paths,
                    video_path,
                    fps=config.get("video", {}).get("fps", 24),
                ):
                    logger.info(f"Video created: {video_path}")
                else:
                    logger.warning("Video creation failed")
            else:
                logger.warning("No image artifacts available for video creation")

        logger.info("=" * 60)
        logger.info("StableNew CLI - Completed successfully")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
