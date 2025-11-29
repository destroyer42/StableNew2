# src directory contents snapshot

Generated on 2025-11-16T22:37:22.039513+00:00 using tracked files.

## `src/__init__.py`

```
"""StableNew - Stable Diffusion WebUI Automation Package"""

__version__ = "1.0.0"

```

## `src/api/__init__.py`

```
"""API module for SD WebUI interaction"""

from .client import SDWebUIClient

__all__ = ["SDWebUIClient"]

```

## `src/api/client.py`

```
"""API client for Stable Diffusion WebUI"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class SDWebUIClient:
    """Client for interacting with Stable Diffusion WebUI API"""

    _option_keys: set[str] | None

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7860",
        timeout: int = 300,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        max_backoff: float = 30.0,
        jitter: float = 0.5,
    ):
        """
        Initialize the SD WebUI API client.

        Args:
            base_url: Base URL of the SD WebUI API
            timeout: Request timeout in seconds
            max_retries: Maximum number of attempts for API requests
            backoff_factor: Base delay (in seconds) used for exponential backoff
            max_backoff: Maximum delay between retry attempts
            jitter: Maximum random jitter added to the backoff delay
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.backoff_factor = max(0.0, backoff_factor)
        self.max_backoff = max(0.0, max_backoff)
        self.jitter = max(0.0, jitter)
        self._option_keys = None
        self.samplers: list[dict[str, Any]] = []
        self.upscalers: list[dict[str, Any]] = []

    def check_connection(self, timeout: float | None = None) -> bool:
        """
        Lightweight health check for the WebUI API using the configured base URL.

        This wraps validate_webui_health so callers can probe connectivity using the
        same client instance without instantiating additional helpers.
        """
        effective_timeout = timeout if timeout is not None else min(self.timeout, 5.0)
        try:
            health = validate_webui_health(self.base_url, timeout=effective_timeout)
        except TypeError:
            # Older validate_webui_health implementations may not accept timeout.
            health = validate_webui_health(self.base_url)
        if isinstance(health, dict):
            return bool(health.get("accessible"))
        return bool(health)

    def _sleep(self, duration: float) -> None:
        """Sleep helper that can be overridden in tests."""

        time.sleep(duration)

    def _calculate_backoff(self, attempt: int, backoff_factor: float | None = None) -> float:
        """Calculate the backoff delay for a retry attempt."""

        base = self.backoff_factor if backoff_factor is None else max(0.0, backoff_factor)
        if base <= 0:
            return 0.0

        delay = base * (2**attempt)
        if self.max_backoff > 0:
            delay = min(delay, self.max_backoff)

        if self.jitter > 0 and delay > 0:
            delay += random.uniform(0, self.jitter)

        return delay

    def _perform_request(
        self,
        method: str,
        endpoint: str,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_factor: float | None = None,
        **kwargs: Any,
    ) -> requests.Response | None:
        """Perform an HTTP request with retry/backoff handling."""

        retries = max_retries if max_retries is not None else self.max_retries
        retries = max(1, retries)
        timeout_value = self.timeout if timeout is None else timeout
        url = f"{self.base_url}{endpoint}"
        last_exception: Exception | None = None

        for attempt in range(retries):
            try:
                response = requests.request(method.upper(), url, timeout=timeout_value, **kwargs)
                response.raise_for_status()
                return response
            except Exception as exc:  # noqa: BLE001 - broad to ensure retries
                last_exception = exc
                logger.warning(
                    "Request %s %s attempt %s/%s failed: %s",
                    method.upper(),
                    url,
                    attempt + 1,
                    retries,
                    exc,
                )
                if attempt >= retries - 1:
                    break

                delay = self._calculate_backoff(attempt, backoff_factor)
                if delay > 0:
                    self._sleep(delay)

        if last_exception is not None:
            logger.error(
                "Request %s %s failed after %s attempts: %s",
                method.upper(),
                url,
                retries,
                last_exception,
            )

        return None

    def _option_supports(self, key: str) -> bool:
        """Return True if the API advertises the given /options key."""

        keys = self._ensure_option_keys()
        return key in keys

    def _ensure_option_keys(self) -> set[str]:
        """Fetch and cache the option keys from the API."""

        if self._option_keys is not None:
            return self._option_keys

        response = self._perform_request("get", "/sdapi/v1/options", timeout=10)
        if response is None:
            self._option_keys = set()
            return self._option_keys

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning(f"Failed to parse options metadata: {exc}")
            self._option_keys = set()
            return self._option_keys

        self._option_keys = {str(k) for k in data.keys()}
        return self._option_keys

    def ensure_safe_upscale_defaults(
        self,
        max_img_mp: float = 8.0,
        max_tile: int = 768,
        max_overlap: int = 128,
    ) -> None:
        """
        Clamp WebUI's upscale defaults to safer ceilings.

        The method only moves values downward (toward safer limits) and skips
        the POST entirely when everything is already within range.
        """

        response = self._perform_request("get", "/sdapi/v1/options", timeout=10)
        if response is None:
            return

        try:
            data = response.json()
        except ValueError as exc:
            logger.debug("ensure_safe_upscale_defaults: failed to parse options: %s", exc)
            return

        payload: dict[str, float | int] = {}
        changes: dict[str, tuple[float | int, float | int]] = {}

        if "img_max_size_mp" in data:
            try:
                current_mp = float(data.get("img_max_size_mp", max_img_mp))
            except (TypeError, ValueError):
                current_mp = max_img_mp
            if current_mp > max_img_mp:
                payload["img_max_size_mp"] = max_img_mp
                changes["img_max_size_mp"] = (current_mp, max_img_mp)

        for key in ("ESRGAN_tile", "DAT_tile"):
            if key not in data:
                continue
            try:
                current_tile = int(data.get(key, max_tile))
            except (TypeError, ValueError):
                current_tile = max_tile
            if current_tile > max_tile:
                payload[key] = max_tile
                changes[key] = (current_tile, max_tile)

        for key in ("ESRGAN_tile_overlap", "DAT_tile_overlap"):
            if key not in data:
                continue
            try:
                current_overlap = int(data.get(key, max_overlap))
            except (TypeError, ValueError):
                continue
            if current_overlap > max_overlap:
                payload[key] = max_overlap
                changes[key] = (current_overlap, max_overlap)

        if not payload:
            return

        response = self._perform_request(
            "post",
            "/sdapi/v1/options",
            json=payload,
            timeout=15,
        )
        if response is None:
            return

        summary = ", ".join(f"{name}={after}" for name, (_before, after) in changes.items())
        logger.info("Applied safe WebUI upscale defaults: %s", summary)

    def apply_upscale_performance_defaults(self) -> None:
        """
        Apply conservative tiling and resolution defaults to the WebUI options.

        Best-effort: failures are logged but do not raise.
        """

        payload = {
            "img_max_size_mp": 16,
            "ESRGAN_tile": 1920,
            "ESRGAN_tile_overlap": 64,
            "DAT_tile": 1920,
            "DAT_tile_overlap": 64,
            "upscaling_max_images_in_cache": 8,
        }

        try:
            response = self._perform_request(
                "post",
                "/sdapi/v1/options",
                json=payload,
                timeout=30,
            )
            if response is None:
                raise RuntimeError("No response from /sdapi/v1/options")

            logger.info(
                "Applied WebUI upscale defaults: img_max_size_mp=%s, ESRGAN_tile=%s, DAT_tile=%s",
                payload.get("img_max_size_mp"),
                payload.get("ESRGAN_tile"),
                payload.get("DAT_tile"),
            )
        except Exception as exc:  # noqa: BLE001 - log and continue
            logger.warning("Failed to apply WebUI upscale defaults: %s", exc)

    def check_api_ready(self, max_retries: int = 5, retry_delay: float = 2.0) -> bool:
        """
        Check if the API is ready to accept requests.

        Args:
            max_retries: Maximum number of retry attempts
            retry_delay: Base delay in seconds for exponential backoff

        Returns:
            True if API is ready, False otherwise
        """

        response = self._perform_request(
            "get",
            "/sdapi/v1/sd-models",
            timeout=10,
            max_retries=max_retries,
            backoff_factor=retry_delay,
        )

        if response is None:
            logger.error("SD WebUI API is not ready after max retries")
            return False

        logger.info("SD WebUI API is ready")
        return True

    def txt2img(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """
        Generate image from text prompt.

        Args:
            payload: Request payload with generation parameters

        Returns:
            Response data including base64 encoded images
        """
        response = self._perform_request(
            "post",
            "/sdapi/v1/txt2img",
            json=payload,
        )

        if response is None:
            return None

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"txt2img response parsing failed: {exc}")
            return None

        # Log parameters returned by the API for correlation
        try:
            params = data.get("parameters")
            if not params:
                # Some servers return a JSON string in 'info'
                info = data.get("info")
                if isinstance(info, str) and info:
                    try:
                        params = json.loads(info)
                    except Exception:
                        params = None
            if isinstance(params, dict):
                logger.info(
                    "txt2img response params => steps=%s, sampler=%s, scheduler=%s, cfg=%s, size=%sx%s",
                    params.get("steps"),
                    params.get("sampler_name"),
                    params.get("scheduler") or params.get("scheduling"),
                    params.get("cfg_scale"),
                    params.get("width"),
                    params.get("height"),
                )
            else:
                logger.debug("txt2img response has no parameters field")
        except Exception:
            logger.debug("Failed to log txt2img response parameters", exc_info=True)

        logger.info(
            "txt2img completed successfully, generated %s images",
            len(data.get("images", [])),
        )
        return data

    def img2img(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """
        Refine image using img2img.

        Args:
            payload: Request payload with generation parameters and init image

        Returns:
            Response data including base64 encoded images
        """
        response = self._perform_request(
            "post",
            "/sdapi/v1/img2img",
            json=payload,
        )

        if response is None:
            return None

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"img2img response parsing failed: {exc}")
            return None

        # Log parameters returned by the API for correlation
        try:
            params = data.get("parameters")
            if not params:
                info = data.get("info")
                if isinstance(info, str) and info:
                    try:
                        params = json.loads(info)
                    except Exception:
                        params = None
            if isinstance(params, dict):
                logger.info(
                    "img2img response params => steps=%s, denoise=%s, sampler=%s, scheduler=%s, size=%sx%s",
                    params.get("steps"),
                    params.get("denoising_strength"),
                    params.get("sampler_name"),
                    params.get("scheduler") or params.get("scheduling"),
                    params.get("width"),
                    params.get("height"),
                )
            else:
                logger.debug("img2img response has no parameters field")
        except Exception:
            logger.debug("Failed to log img2img response parameters", exc_info=True)

        logger.info("img2img completed successfully")
        return data

    def upscale(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """
        Upscale image using extra-single-image endpoint.

        Args:
            payload: Request payload with image and upscaling parameters

        Returns:
            Response data including base64 encoded upscaled image
        """
        response = self._perform_request(
            "post",
            "/sdapi/v1/extra-single-image",
            json=payload,
        )

        if response is None:
            return None

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"Upscale response parsing failed: {exc}")
            return None

        logger.info("Upscaling completed successfully")
        return data

    def upscale_image(
        self,
        image_base64: str,
        upscaler: str,
        upscaling_resize: float,
        gfpgan_visibility: float = 0.0,
        codeformer_visibility: float = 0.0,
        codeformer_weight: float = 0.5,
    ) -> dict[str, Any] | None:
        """
        Upscale image using extra upscalers with optional face restoration.

        Args:
            image_base64: Base64 encoded image
            upscaler: Name of the upscaler to use
            upscaling_resize: Scale factor
            gfpgan_visibility: GFPGAN strength (0.0-1.0)
            codeformer_visibility: CodeFormer strength (0.0-1.0)
            codeformer_weight: CodeFormer fidelity (0.0-1.0)

        Returns:
            Response data with upscaled image
        """
        payload = {
            "resize_mode": 0,
            "upscaling_resize": upscaling_resize,
            "upscaler_1": upscaler,
            "image": image_base64,
            "gfpgan_visibility": gfpgan_visibility,
            "codeformer_visibility": codeformer_visibility,
            "codeformer_weight": codeformer_weight,
        }
        response = self._perform_request(
            "post",
            "/sdapi/v1/extra-single-image",
            json=payload,
        )

        if response is None:
            return None

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"Upscale response parsing failed: {exc}")
            return None

        # Log face restoration usage
        face_restoration_used = []
        if gfpgan_visibility > 0:
            face_restoration_used.append(f"GFPGAN({gfpgan_visibility})")
        if codeformer_visibility > 0:
            face_restoration_used.append(f"CodeFormer({codeformer_visibility})")

        restoration_info = f" + {', '.join(face_restoration_used)}" if face_restoration_used else ""
        logger.info(f"Upscale completed successfully with {upscaler}{restoration_info}")
        return data

    def get_models(self) -> list[dict[str, Any]]:
        """
        Get list of available SD models.

        Returns:
            List of model information
        """

        response = self._perform_request("get", "/sdapi/v1/sd-models", timeout=10)
        if response is None:
            return []

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"Failed to parse models response: {exc}")
            return []

        logger.info("Retrieved %s models", len(data))
        return data

    def get_vae_models(self) -> list[dict[str, Any]]:
        """
        Get list of available VAE models.

        Returns:
            List of VAE model information
        """
        response = self._perform_request("get", "/sdapi/v1/sd-vae", timeout=10)
        if response is None:
            return []

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"Failed to parse VAE models response: {exc}")
            return []

        logger.info("Retrieved %s VAE models", len(data))
        return data

    def get_samplers(self) -> list[dict[str, Any]]:
        """
        Get list of available samplers.

        Returns:
            List of sampler information
        """
        response = self._perform_request("get", "/sdapi/v1/samplers", timeout=10)
        if response is None:
            return []

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"Failed to parse samplers response: {exc}")
            return []

        logger.info("Retrieved %s samplers", len(data))
        self.samplers = data
        return data

    def get_upscalers(self) -> list[dict[str, Any]]:
        """
        Get list of available upscalers.

        Returns:
            List of upscaler information
        """
        response = self._perform_request("get", "/sdapi/v1/upscalers", timeout=10)
        if response is None:
            return []

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"Failed to parse upscalers response: {exc}")
            return []

        logger.info("Retrieved %s upscalers", len(data))
        self.upscalers = data
        return data

    def get_hypernetworks(self) -> list[dict[str, Any]]:
        """
        Get list of available hypernetworks.

        Returns:
            List of hypernetwork metadata dictionaries
        """

        response = self._perform_request("get", "/sdapi/v1/hypernetworks", timeout=10)
        if response is None:
            logger.warning("Failed to retrieve hypernetworks from API")
            return []

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"Failed to parse hypernetworks response: {exc}")
            return []

        logger.info("Retrieved %s hypernetworks", len(data))
        return data

    def get_schedulers(self) -> list[str]:
        """
        Get list of available schedulers.

        Returns:
            List of scheduler names
        """
        response = self._perform_request("get", "/sdapi/v1/schedulers", timeout=10)
        if response is None:
            logger.warning("Failed to get schedulers from API; using defaults")
            return [
                "Normal",
                "Karras",
                "Exponential",
                "SGM Uniform",
                "Simple",
                "DDIM Uniform",
                "Beta",
                "Linear",
                "Cosine",
            ]

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning(f"Failed to parse schedulers response: {exc}; using defaults")
            return [
                "Normal",
                "Karras",
                "Exponential",
                "SGM Uniform",
                "Simple",
                "DDIM Uniform",
                "Beta",
                "Linear",
                "Cosine",
            ]

        schedulers = [
            scheduler.get("name", scheduler.get("label", "")) for scheduler in data if scheduler
        ]
        logger.info("Retrieved %s schedulers", len(schedulers))
        return schedulers

    def set_model(self, model_name: str) -> bool:
        """
        Set the current SD model.

        Args:
            model_name: Name of the model to set

        Returns:
            True if successful
        """
        payload = {"sd_model_checkpoint": model_name}
        response = self._perform_request(
            "post",
            "/sdapi/v1/options",
            json=payload,
            timeout=75,  # Model switching can take time
        )

        if response is None:
            return False

        logger.info(f"Set model to: {model_name}")
        return True

    def set_vae(self, vae_name: str) -> bool:
        """
        Set the current VAE model.

        Args:
            vae_name: Name of the VAE to set

        Returns:
            True if successful
        """
        payload = {"sd_vae": vae_name}
        response = self._perform_request(
            "post",
            "/sdapi/v1/options",
            json=payload,
            timeout=10,
        )

        if response is None:
            return False

        logger.info(f"Set VAE to: {vae_name}")
        return True

    def set_hypernetwork(self, name: str | None, strength: float | None = None) -> bool:
        """
        Set the active hypernetwork (or clear it) and optional strength.

        Args:
            name: Hypernetwork name. Use None/"None" to disable.
            strength: Optional blend strength (0.0-2.0). When omitted, WebUI default is used.

        Returns:
            True if successful
        """

        hyper_name = "None" if not name or str(name).strip().lower() in {"", "none"} else str(name)
        payload: dict[str, Any] = {"sd_hypernetwork": hyper_name}

        if strength is not None:
            if self._option_supports("sd_hypernetwork_strength"):
                clamped = max(0.0, min(2.0, float(strength)))
                payload["sd_hypernetwork_strength"] = clamped
            else:
                logger.info(
                    "Hypernetwork strength option not supported by API; skipping strength set"
                )

        response = self._perform_request(
            "post",
            "/sdapi/v1/options",
            json=payload,
            timeout=10,
        )

        if response is None:
            return False

        if hyper_name == "None":
            logger.info("Cleared active hypernetwork")
        else:
            logger.info(
                "Set hypernetwork to %s (strength=%s)",
                hyper_name,
                payload.get("sd_hypernetwork_strength", "default"),
            )
        return True

    def get_models_old(self) -> list[dict[str, Any]]:
        """
        Get list of available models.

        Returns:
            List of available models
        """
        response = self._perform_request("get", "/sdapi/v1/sd-models", timeout=10)
        if response is None:
            return []

    def get_options(self) -> dict[str, Any]:
        """
        Retrieve the current WebUI global options.
        """

        response = self._perform_request("get", "/sdapi/v1/options", timeout=10)
        if response is None:
            raise RuntimeError("Failed to retrieve WebUI options")

        try:
            return response.json()
        except ValueError as exc:  # noqa: PERF203 - explicit exception handling
            logger.error("Failed to parse WebUI options response: %s", exc)
            raise

    def update_options(self, updates: dict[str, Any]) -> dict[str, Any]:
        """
        Partially update WebUI options.

        Args:
            updates: Mapping of option name -> value.
        """

        response = self._perform_request(
            "post",
            "/sdapi/v1/options",
            json=updates,
            timeout=15,
        )
        if response is None:
            raise RuntimeError("Failed to update WebUI options")

        try:
            return response.json()
        except ValueError as exc:
            logger.error("Failed to parse WebUI options update response: %s", exc)
            raise

        try:
            return response.json()
        except ValueError as exc:
            logger.error(f"Failed to parse models response: {exc}")
            return []

    def get_current_model(self) -> str | None:
        """
        Get the currently loaded model.

        Returns:
            Current model name
        """
        response = self._perform_request("get", "/sdapi/v1/options", timeout=10)
        if response is None:
            return None

        try:
            data = response.json()
        except ValueError as exc:
            logger.error(f"Failed to parse current model response: {exc}")
            return None

        return data.get("sd_model_checkpoint")


def validate_webui_health(*args, **kwargs):
    from src.utils import webui_discovery as _wd

    return _wd.validate_webui_health(*args, **kwargs)


def find_webui_api_port(*args, **kwargs):
    from src.utils import webui_discovery as _wd

    return _wd.find_webui_api_port(*args, **kwargs)

```

## `src/cli.py`

```
"""Command-line interface for StableNew"""

import argparse
import logging
from pathlib import Path

from .api import SDWebUIClient
from .pipeline import Pipeline, VideoCreator
from .utils import ConfigManager, StructuredLogger, find_webui_api_port, setup_logging


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
        logger.info("img2img stage disabled")

    if args.no_upscale:
        config.pop("upscale", None)
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

    # Initialize pipeline
    pipeline = Pipeline(client, structured_logger)

    # Run pipeline
    try:
        results = pipeline.run_full_pipeline(args.prompt, config, args.run_name, args.batch_size)

        logger.info("=" * 60)
        logger.info("Pipeline Results:")
        logger.info(f"  Run directory: {results['run_dir']}")
        logger.info(f"  txt2img images: {len(results['txt2img'])}")
        logger.info(f"  img2img images: {len(results['img2img'])}")
        logger.info(f"  Upscaled images: {len(results['upscaled'])}")
        logger.info("=" * 60)

        # Create video if requested
        if args.create_video:
            logger.info("Creating video...")
            video_creator = VideoCreator()
            run_dir = Path(results["run_dir"])

            # Try to create video from upscaled images first
            for subdir in ["upscaled", "img2img", "txt2img"]:
                image_dir = run_dir / subdir
                if image_dir.exists():
                    video_path = run_dir / "video" / f"{subdir}_video.mp4"
                    video_path.parent.mkdir(exist_ok=True)

                    if video_creator.create_video_from_directory(
                        image_dir, video_path, fps=config.get("video", {}).get("fps", 24)
                    ):
                        logger.info(f"Video created: {video_path}")
                        break

        logger.info("=" * 60)
        logger.info("StableNew CLI - Completed successfully")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())

```

## `src/controller/__init__.py`

```
# Enable src.controller as a package for imports

```

## `src/controller/app_controller.py`

```
"""
StableNew - App Controller (Skeleton + CancelToken + Worker Thread Stub)

This controller is designed to work with the new GUI skeleton
in src/gui/main_window_v2.py and the Architecture_v2 design.

It provides:
- Lifecycle state management (IDLE, RUNNING, STOPPING, ERROR).
- Methods for GUI callbacks (run/stop/preview/etc.).
- A CancelToken + worker-thread stub for future pipeline integration.
- A 'threaded' mode for real runs and a synchronous mode for tests.

Real pipeline execution, WebUI client integration, and logging details
will be wired in later via a PipelineRunner abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional, Protocol
import threading
import time

from src.gui.main_window_v2 import MainWindow


class LifecycleState(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


@dataclass
class RunConfig:
    """
    Minimal placeholder for the full run configuration.

    In a real implementation this will be built from:
    - presets/ JSON
    - GUI state (model, sampler, resolution, randomization, matrix)
    - prompt pack selection
    """
    preset_name: str = ""
    model_name: str = ""
    vae_name: str = ""
    sampler_name: str = ""
    scheduler_name: str = ""
    width: int = 1024
    height: int = 1024
    randomization_enabled: bool = False
    # Future fields:
    # matrix_config, adetailer_config, video_config, etc.


@dataclass
class AppState:
    lifecycle: LifecycleState = LifecycleState.IDLE
    last_error: Optional[str] = None
    current_config: RunConfig = field(default_factory=RunConfig)


class CancelToken:
    """
    Simple cancellable flag for cooperative cancellation of the pipeline.

    A real implementation can grow to include thread-safe semantics if needed.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled


class PipelineRunner(Protocol):
    """
    Protocol for something that can run the pipeline.

    Implementations should:
    - Honor CancelToken for cooperative cancellation.
    - Use log_fn to append log messages.
    """

    def run(
        self,
        config: RunConfig,
        cancel_token: CancelToken,
        log_fn: Callable[[str], None],
    ) -> None:
        ...


class DummyPipelineRunner:
    """
    Default stub runner used when no real pipeline_runner is supplied.

    It just logs a couple of messages and respects CancelToken.
    """

    def run(
        self,
        config: RunConfig,
        cancel_token: CancelToken,
        log_fn: Callable[[str], None],
    ) -> None:
        log_fn("[pipeline] DummyPipelineRunner starting (stub).")
        for i in range(3):
            if cancel_token.is_cancelled():
                log_fn("[pipeline] Cancel detected, aborting (stub).")
                return
            log_fn(f"[pipeline] Working... step {i + 1}/3 (stub).")
            time.sleep(0.05)
        log_fn("[pipeline] DummyPipelineRunner finished (stub).")


class AppController:
    """
    Orchestrates GUI events and (eventually) pipeline execution.

    Responsibilities:
    - Maintain lifecycle state (IDLE/RUNNING/STOPPING/ERROR).
    - Bridge GUI interactions to the pipeline, config, and randomizer.
    - Provide high-level methods for GUI callbacks.

    'threaded' controls whether runs happen in a worker thread (True, default)
    or synchronously (False, ideal for tests).
    """

    def __init__(
        self,
        main_window: MainWindow,
        pipeline_runner: Optional[PipelineRunner] = None,
        threaded: bool = True,
    ) -> None:
        self.main_window = main_window
        self.state = AppState()
        self.threaded = threaded

        self.pipeline_runner: PipelineRunner = pipeline_runner or DummyPipelineRunner()
        self._cancel_token: Optional[CancelToken] = None
        self._worker_thread: Optional[threading.Thread] = None

        # Let the GUI wire its callbacks to us
        self._attach_to_gui()

        # Initial status
        self._update_status("Idle")

    # ------------------------------------------------------------------
    # GUI Wiring
    # ------------------------------------------------------------------

    def _attach_to_gui(self) -> None:
        header = self.main_window.header_zone
        left = self.main_window.left_zone
        bottom = self.main_window.bottom_zone

        # Header events
        header.run_button.configure(command=self.on_run_clicked)
        header.stop_button.configure(command=self.on_stop_clicked)
        header.preview_button.configure(command=self.on_preview_clicked)
        header.settings_button.configure(command=self.on_open_settings)
        header.help_button.configure(command=self.on_help_clicked)

        # Left zone events
        left.load_pack_button.configure(command=self.on_load_pack)
        left.edit_pack_button.configure(command=self.on_edit_pack)
        left.packs_list.bind("<<ListboxSelect>>", self._on_pack_list_select)
        left.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_combo_select)

        # Initial API status (placeholder)
        bottom.api_status_label.configure(text="API: Unknown")

    # ------------------------------------------------------------------
    # Internal helpers (state & logging)
    # ------------------------------------------------------------------

    def _set_lifecycle(self, new_state: LifecycleState, error: Optional[str] = None) -> None:
        self.state.lifecycle = new_state
        self.state.last_error = error

        if new_state == LifecycleState.IDLE:
            self._update_status("Idle")
        elif new_state == LifecycleState.RUNNING:
            self._update_status("Running...")
        elif new_state == LifecycleState.STOPPING:
            self._update_status("Stopping...")
        elif new_state == LifecycleState.ERROR:
            self._update_status(f"Error: {error or 'Unknown error'}")

    def _set_lifecycle_threadsafe(
        self, new_state: LifecycleState, error: Optional[str] = None
    ) -> None:
        """
        Schedule lifecycle change on the Tk main thread if threaded.
        For tests (threaded=False), apply immediately.
        """
        if not self.threaded:
            self._set_lifecycle(new_state, error)
            return

        self.main_window.after(0, lambda: self._set_lifecycle(new_state, error))

    def _update_status(self, text: str) -> None:
        self.main_window.bottom_zone.status_label.configure(text=f"Status: {text}")

    def _append_log(self, text: str) -> None:
        log_widget = self.main_window.bottom_zone.log_text
        log_widget.insert("end", text + "\n")
        log_widget.see("end")

    def _append_log_threadsafe(self, text: str) -> None:
        """
        Schedule a log append on the Tk main thread if threaded.
        For tests (threaded=False), apply immediately.
        """
        if not self.threaded:
            self._append_log(text)
            return

        self.main_window.after(0, lambda: self._append_log(text))

    # ------------------------------------------------------------------
    # Run / Stop / Preview
    # ------------------------------------------------------------------

    def on_run_clicked(self) -> None:
        """
        Called when the user presses RUN.

        In threaded mode:
        - Spawns a worker thread to run the pipeline with a CancelToken.

        In synchronous mode (threaded=False, useful for tests):
        - Runs the pipeline stub synchronously.
        """
        if self.state.lifecycle == LifecycleState.RUNNING:
            self._append_log("[controller] Run requested, but pipeline is already running.")
            return

        # If there was a previous worker, ensure it is not still alive (best-effort)
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._append_log("[controller] Previous worker still running; refusing new run.")
            return

        self._append_log("[controller] Run clicked – gathering config (stub).")
        self._cancel_token = CancelToken()
        self._set_lifecycle(LifecycleState.RUNNING)

        config = self.state.current_config

        if self.threaded:
            self._worker_thread = threading.Thread(
                target=self._run_pipeline_thread, args=(config, self._cancel_token), daemon=True
            )
            self._worker_thread.start()
        else:
            # Synchronous run (for tests)
            self._run_pipeline_thread(config, self._cancel_token)

    def _run_pipeline_thread(self, config: RunConfig, cancel_token: CancelToken) -> None:
        try:
            self._append_log_threadsafe("[controller] Starting pipeline (stub runner).")
            self.pipeline_runner.run(config, cancel_token, self._append_log_threadsafe)

            if cancel_token.is_cancelled():
                self._append_log_threadsafe("[controller] Pipeline ended due to cancel (stub).")
            else:
                self._append_log_threadsafe("[controller] Pipeline completed successfully (stub).")

            self._set_lifecycle_threadsafe(LifecycleState.IDLE)
        except Exception as exc:  # noqa: BLE001
            self._append_log_threadsafe(f"[controller] Pipeline error: {exc!r}")
            self._set_lifecycle_threadsafe(LifecycleState.ERROR, error=str(exc))

    def on_stop_clicked(self) -> None:
        """
        Called when the user presses STOP.

        Sets lifecycle to STOPPING, triggers CancelToken, and lets the
        pipeline exit cooperatively. In synchronous mode, we immediately
        return to IDLE after marking cancel.
        """
        if self.state.lifecycle != LifecycleState.RUNNING:
            self._append_log("[controller] Stop requested, but pipeline is not running.")
            return

        self._append_log("[controller] Stop requested.")
        self._set_lifecycle(LifecycleState.STOPPING)

        if self._cancel_token is not None:
            self._cancel_token.cancel()

        if not self.threaded:
            # In synchronous mode, worker has already finished or is in-process;
            # for the stub we just go to IDLE here.
            self._set_lifecycle(LifecycleState.IDLE)
        # In threaded mode, lifecycle will transition to IDLE in _run_pipeline_thread
        # once the worker exits.

    def on_preview_clicked(self) -> None:
        """
        Called when the user presses Preview Payload.

        In real code, this would run randomizer/matrix to generate a preview
        payload without calling WebUI. For now, we just log a stub message.
        """
        self._append_log("[controller] Preview clicked (stub).")
        # TODO: gather config, pack, randomization, matrix → build preview payload.

    # ------------------------------------------------------------------
    # Settings / Help
    # ------------------------------------------------------------------

    def on_open_settings(self) -> None:
        self._append_log("[controller] Settings clicked (stub).")
        # TODO: open a settings dialog or config editor.

    def on_help_clicked(self) -> None:
        self._append_log("[controller] Help clicked (stub).")
        # TODO: open docs/README in browser or show help overlay.

    # ------------------------------------------------------------------
    # Packs / Presets
    # ------------------------------------------------------------------

    def _on_preset_combo_select(self, event) -> None:  # type: ignore[override]
        combo = self.main_window.left_zone.preset_combo
        new_preset = combo.get()
        self.on_preset_selected(new_preset)

    def on_preset_selected(self, preset_name: str) -> None:
        self._append_log(f"[controller] Preset selected: {preset_name}")
        self.state.current_config.preset_name = preset_name
        # TODO: load preset JSON, update GUI fields, etc.

    def _on_pack_list_select(self, event) -> None:  # type: ignore[override]
        lb = self.main_window.left_zone.packs_list
        if not lb.curselection():
            return
        index = lb.curselection()[0]
        pack_name = lb.get(index)
        self.on_pack_selected(pack_name)

    def on_pack_selected(self, pack_name: str) -> None:
        self._append_log(f"[controller] Pack selected: {pack_name}")
        # TODO: map pack name to file path and load metadata.

    def on_load_pack(self) -> None:
        self._append_log("[controller] Load Pack clicked (stub).")
        # TODO: open file dialog or load selected pack.

    def on_edit_pack(self) -> None:
        self._append_log("[controller] Edit Pack clicked (stub).")
        # TODO: open Advanced Prompt Editor pre-populated with pack contents.

    # ------------------------------------------------------------------
    # Config Changes (model, sampler, resolution, randomization, matrix)
    # ------------------------------------------------------------------

    def on_model_selected(self, model_name: str) -> None:
        self._append_log(f"[controller] Model selected: {model_name}")
        self.state.current_config.model_name = model_name

    def on_vae_selected(self, vae_name: str) -> None:
        self._append_log(f"[controller] VAE selected: {vae_name}")
        self.state.current_config.vae_name = vae_name

    def on_sampler_selected(self, sampler_name: str) -> None:
        self._append_log(f"[controller] Sampler selected: {sampler_name}")
        self.state.current_config.sampler_name = sampler_name

    def on_scheduler_selected(self, scheduler_name: str) -> None:
        self._append_log(f"[controller] Scheduler selected: {scheduler_name}")
        self.state.current_config.scheduler_name = scheduler_name

    def on_resolution_changed(self, width: int, height: int) -> None:
        self._append_log(f"[controller] Resolution changed to {width}x{height}")
        self.state.current_config.width = width
        self.state.current_config.height = height

    def on_randomization_toggled(self, enabled: bool) -> None:
        self._append_log(f"[controller] Randomization toggled: {enabled}")
        self.state.current_config.randomization_enabled = enabled

    def on_matrix_base_prompt_changed(self, text: str) -> None:
        self._append_log("[controller] Matrix base prompt changed (stub).")
        # TODO: store in matrix config.

    def on_matrix_slots_changed(self) -> None:
        self._append_log("[controller] Matrix slots changed (stub).")
        # TODO: store in matrix config.

    # ------------------------------------------------------------------
    # Preview / Right Zone
    # ------------------------------------------------------------------

    def on_request_preview_refresh(self) -> None:
        self._append_log("[controller] Preview refresh requested (stub).")
        # TODO: set preview_label image or text based on latest run or preview.


# Convenience entrypoint for testing the skeleton standalone
if __name__ == "__main__":
    import tkinter as tk
    from src.gui.main_window_v2 import StableNewApp

    app = StableNewApp()
    controller = AppController(app.main_window, threaded=True)
    app.mainloop()
```

## `src/controller/pipeline_controller.py`

```
"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller."""

from src.gui.controller import PipelineController as _GUIPipelineController
from src.gui.state import StateManager


class PipelineController(_GUIPipelineController):
    """Provide a default StateManager so legacy imports keep working."""

    def __init__(self, state_manager: StateManager | None = None, *args, **kwargs):
        super().__init__(state_manager or StateManager(), *args, **kwargs)

```

## `src/gui/__init__.py`

```
"""GUI module"""

# Import state and controller modules which don't require tkinter
from .controller import LogMessage, PipelineController
from .state import CancellationError, CancelToken, GUIState, StateManager

# Don't import StableNewGUI here to avoid tkinter dependency in tests
# Users should import it directly: from src.gui.main_window import StableNewGUI

__all__ = [
    "GUIState",
    "StateManager",
    "CancelToken",
    "CancellationError",
    "PipelineController",
    "LogMessage",
]

```

## `src/gui/adetailer_config_panel.py`

```
"""ADetailer configuration panel for face and detail enhancement."""

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable

logger = logging.getLogger(__name__)


class ADetailerConfigPanel:
    """Panel for configuring ADetailer settings.

    ADetailer is an extension for automatic face/detail detection and enhancement.
    This panel provides controls for model selection, detection confidence,
    and processing parameters.
    """

    # Available ADetailer models
    AVAILABLE_MODELS = [
        "face_yolov8n.pt",
        "face_yolov8s.pt",
        "hand_yolov8n.pt",
        "person_yolov8n-seg.pt",
        "mediapipe_face_full",
        "mediapipe_face_short",
        "mediapipe_face_mesh",
    ]

    SCHEDULER_OPTIONS = [
        "inherit",
        "Automatic",
        "Karras",
        "Exponential",
        "Polyexponential",
        "SGM Uniform",
    ]

    # Default configuration
    DEFAULT_CONFIG = {
        "adetailer_enabled": False,
        "adetailer_model": "face_yolov8n.pt",
        "adetailer_confidence": 0.3,
        "adetailer_mask_feather": 4,
        "adetailer_sampler": "DPM++ 2M",
        "adetailer_scheduler": "inherit",
        "adetailer_steps": 28,
        "adetailer_denoise": 0.4,
        "adetailer_cfg": 7.0,
        "adetailer_prompt": "",
        "adetailer_negative_prompt": "",
    }

    def __init__(self, parent: tk.Widget):
        """Initialize ADetailer configuration panel.

        Args:
            parent: Parent widget
        """
        self.parent = parent

        # Create main frame
        self.frame = ttk.LabelFrame(parent, text="ADetailer Configuration", padding=10)

        # Initialize variables
        self.enabled_var = tk.BooleanVar(value=self.DEFAULT_CONFIG["adetailer_enabled"])
        self.model_var = tk.StringVar(value=self.DEFAULT_CONFIG["adetailer_model"])
        self.confidence_var = tk.DoubleVar(value=self.DEFAULT_CONFIG["adetailer_confidence"])
        self.mask_feather_var = tk.IntVar(value=self.DEFAULT_CONFIG["adetailer_mask_feather"])
        self.sampler_var = tk.StringVar(value=self.DEFAULT_CONFIG["adetailer_sampler"])
        self.scheduler_var = tk.StringVar(value=self.DEFAULT_CONFIG["adetailer_scheduler"])
        self.steps_var = tk.IntVar(value=self.DEFAULT_CONFIG["adetailer_steps"])
        self.denoise_var = tk.DoubleVar(value=self.DEFAULT_CONFIG["adetailer_denoise"])
        self.cfg_var = tk.DoubleVar(value=self.DEFAULT_CONFIG["adetailer_cfg"])

        # Build UI
        self._build_ui()

        # Setup enable/disable behavior
        self._on_enabled_changed()

    def _build_ui(self):
        """Build the configuration UI."""
        # Enable checkbox
        enable_frame = ttk.Frame(self.frame)
        enable_frame.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        self.enable_check = ttk.Checkbutton(
            enable_frame,
            text="Enable ADetailer (Automatic face/detail enhancement)",
            variable=self.enabled_var,
            command=self._on_enabled_changed,
        )
        self.enable_check.pack(side=tk.LEFT)

        # Model selection
        model_label = ttk.Label(self.frame, text="Model:")
        model_label.grid(row=1, column=0, sticky=tk.W, pady=2)

        self.model_combo = ttk.Combobox(
            self.frame,
            textvariable=self.model_var,
            values=self.AVAILABLE_MODELS,
            state="readonly",
            width=25,
        )
        self.model_combo.grid(row=1, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Confidence threshold
        conf_label = ttk.Label(self.frame, text="Detection Confidence:")
        conf_label.grid(row=2, column=0, sticky=tk.W, pady=2)

        conf_frame = ttk.Frame(self.frame)
        conf_frame.grid(row=2, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        self.confidence_scale = ttk.Scale(
            conf_frame,
            from_=0.0,
            to=1.0,
            orient=tk.HORIZONTAL,
            variable=self.confidence_var,
            length=150,
        )
        self.confidence_scale.pack(side=tk.LEFT)

        self.confidence_label = ttk.Label(conf_frame, text="0.30")
        self.confidence_label.pack(side=tk.LEFT, padx=(5, 0))
        self.confidence_scale.configure(command=self._update_confidence_label)

        # Mask feather
        feather_label = ttk.Label(self.frame, text="Mask Feather:")
        feather_label.grid(row=3, column=0, sticky=tk.W, pady=2)

        self.feather_spin = ttk.Spinbox(
            self.frame, from_=0, to=64, textvariable=self.mask_feather_var, width=10
        )
        self.feather_spin.grid(row=3, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Sampler
        sampler_label = ttk.Label(self.frame, text="Sampler:")
        sampler_label.grid(row=4, column=0, sticky=tk.W, pady=2)

        self.sampler_combo = ttk.Combobox(
            self.frame,
            textvariable=self.sampler_var,
            values=["DPM++ 2M", "DPM++ SDE", "Euler a", "Euler", "DDIM", "PLMS"],
            width=15,
        )
        self.sampler_combo.grid(row=4, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Scheduler
        scheduler_label = ttk.Label(self.frame, text="Scheduler:")
        scheduler_label.grid(row=5, column=0, sticky=tk.W, pady=2)

        self.scheduler_combo = ttk.Combobox(
            self.frame,
            textvariable=self.scheduler_var,
            values=self.SCHEDULER_OPTIONS,
            width=20,
            state="readonly",
        )
        self.scheduler_combo.grid(row=5, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Steps
        steps_label = ttk.Label(self.frame, text="Steps:")
        steps_label.grid(row=6, column=0, sticky=tk.W, pady=2)

        self.steps_spin = ttk.Spinbox(
            self.frame, from_=1, to=150, textvariable=self.steps_var, width=10
        )
        self.steps_spin.grid(row=6, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Denoise strength
        denoise_label = ttk.Label(self.frame, text="Denoise Strength:")
        denoise_label.grid(row=7, column=0, sticky=tk.W, pady=2)

        denoise_frame = ttk.Frame(self.frame)
        denoise_frame.grid(row=7, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        self.denoise_scale = ttk.Scale(
            denoise_frame,
            from_=0.0,
            to=1.0,
            orient=tk.HORIZONTAL,
            variable=self.denoise_var,
            length=150,
        )
        self.denoise_scale.pack(side=tk.LEFT)

        self.denoise_label = ttk.Label(denoise_frame, text="0.40")
        self.denoise_label.pack(side=tk.LEFT, padx=(5, 0))
        self.denoise_scale.configure(command=self._update_denoise_label)

        # CFG Scale
        cfg_label = ttk.Label(self.frame, text="CFG Scale:")
        cfg_label.grid(row=8, column=0, sticky=tk.W, pady=2)

        self.cfg_spin = ttk.Spinbox(
            self.frame, from_=1.0, to=30.0, textvariable=self.cfg_var, width=10, increment=0.5
        )
        self.cfg_spin.grid(row=8, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Prompt
        prompt_label = ttk.Label(self.frame, text="Positive Prompt:")
        prompt_label.grid(row=9, column=0, sticky=tk.NW, pady=2)

        self.prompt_text = tk.Text(self.frame, height=3, width=40)
        self.prompt_text.grid(row=9, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Negative prompt
        neg_prompt_label = ttk.Label(self.frame, text="Negative Prompt:")
        neg_prompt_label.grid(row=10, column=0, sticky=tk.NW, pady=2)

        self.neg_prompt_text = tk.Text(self.frame, height=3, width=40)
        self.neg_prompt_text.grid(row=10, column=1, sticky=tk.W, pady=2, padx=(5, 0))

    def _update_confidence_label(self, value):
        """Update confidence label with current value."""
        self.confidence_label.config(text=f"{float(value):.2f}")

    def _update_denoise_label(self, value):
        """Update denoise label with current value."""
        self.denoise_label.config(text=f"{float(value):.2f}")

    def _on_enabled_changed(self):
        """Handle enable/disable toggle."""
        enabled = self.enabled_var.get()
        state = "normal" if enabled else "disabled"

        # Update all controls
        self.model_combo.configure(state="readonly" if enabled else "disabled")
        self.confidence_scale.configure(state=state)
        self.feather_spin.configure(state=state)
        self.sampler_combo.configure(state="readonly" if enabled else "disabled")
        self.scheduler_combo.configure(state="readonly" if enabled else "disabled")
        self.steps_spin.configure(state=state)
        self.denoise_scale.configure(state=state)
        self.cfg_spin.configure(state=state)
        self.prompt_text.configure(state=state)
        self.neg_prompt_text.configure(state=state)

    def get_config(self) -> dict[str, Any]:
        """Get current configuration.

        Returns:
            Dictionary of ADetailer configuration
        """
        scheduler_value = self.scheduler_var.get() or "inherit"
        return {
            "adetailer_enabled": self.enabled_var.get(),
            "adetailer_model": self.model_var.get(),
            "adetailer_confidence": self.confidence_var.get(),
            "adetailer_mask_feather": self.mask_feather_var.get(),
            "adetailer_sampler": self.sampler_var.get(),
            "adetailer_scheduler": scheduler_value,
            "scheduler": scheduler_value,
            "adetailer_steps": self.steps_var.get(),
            "adetailer_denoise": self.denoise_var.get(),
            "adetailer_cfg": self.cfg_var.get(),
            "adetailer_prompt": self.prompt_text.get("1.0", tk.END).strip(),
            "adetailer_negative_prompt": self.neg_prompt_text.get("1.0", tk.END).strip(),
        }

    def set_config(self, config: dict[str, Any]) -> None:
        """Set configuration values.

        Args:
            config: Dictionary of ADetailer configuration
        """
        if "adetailer_enabled" in config:
            self.enabled_var.set(config["adetailer_enabled"])
        if "adetailer_model" in config:
            self.model_var.set(config["adetailer_model"])
        if "adetailer_confidence" in config:
            self.confidence_var.set(config["adetailer_confidence"])
            self._update_confidence_label(config["adetailer_confidence"])
        if "adetailer_mask_feather" in config:
            self.mask_feather_var.set(config["adetailer_mask_feather"])
        if "adetailer_sampler" in config:
            self.sampler_var.set(config["adetailer_sampler"])
        scheduler_value = config.get("adetailer_scheduler", config.get("scheduler"))
        if scheduler_value is not None:
            value = scheduler_value or "inherit"
            if value not in self.SCHEDULER_OPTIONS:
                value = "inherit"
            self.scheduler_var.set(value)
        else:
            self.scheduler_var.set("inherit")
        if "adetailer_steps" in config:
            self.steps_var.set(config["adetailer_steps"])
        if "adetailer_denoise" in config:
            self.denoise_var.set(config["adetailer_denoise"])
            self._update_denoise_label(config["adetailer_denoise"])
        if "adetailer_cfg" in config:
            self.cfg_var.set(config["adetailer_cfg"])
        if "adetailer_prompt" in config:
            self.prompt_text.configure(state=tk.NORMAL)
            self.prompt_text.delete("1.0", tk.END)
            self.prompt_text.insert("1.0", config["adetailer_prompt"])
        if "adetailer_negative_prompt" in config:
            self.neg_prompt_text.configure(state=tk.NORMAL)
            self.neg_prompt_text.delete("1.0", tk.END)
            self.neg_prompt_text.insert("1.0", config["adetailer_negative_prompt"])

        self._on_enabled_changed()

    def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate configuration values.

        Args:
            config: Configuration to validate

        Returns:
            True if valid, False otherwise
        """
        # Check confidence is in valid range
        if "adetailer_confidence" in config:
            conf = config["adetailer_confidence"]
            if not 0.0 <= conf <= 1.0:
                logger.error(f"Invalid confidence: {conf} (must be 0.0-1.0)")
                return False

        # Check denoise is in valid range
        if "adetailer_denoise" in config:
            denoise = config["adetailer_denoise"]
            if not 0.0 <= denoise <= 1.0:
                logger.error(f"Invalid denoise: {denoise} (must be 0.0-1.0)")
                return False

        # Check steps is positive
        if "adetailer_steps" in config:
            steps = config["adetailer_steps"]
            if steps < 1:
                logger.error(f"Invalid steps: {steps} (must be >= 1)")
                return False

        scheduler_value = config.get("adetailer_scheduler", config.get("scheduler"))
        if scheduler_value is not None:
            normalized = scheduler_value or "inherit"
            if normalized not in self.SCHEDULER_OPTIONS:
                logger.error(f"Invalid scheduler: {scheduler_value}")
                return False

        return True

    def get_available_models(self) -> list[str]:
        """Get list of available ADetailer models.

        Returns:
            List of model names
        """
        return self.AVAILABLE_MODELS.copy()

    def generate_api_payload(self) -> dict[str, Any]:
        """Generate API payload for ADetailer.

        Returns:
            Dictionary formatted for SD WebUI API
        """
        config = self.get_config()

        scheduler_value = config.get("adetailer_scheduler", config.get("scheduler", "inherit")) or "inherit"

        payload = {
            "adetailer_model": config["adetailer_model"],
            "adetailer_conf": config["adetailer_confidence"],
            "adetailer_mask_blur": config["adetailer_mask_feather"],
            "adetailer_sampler": config["adetailer_sampler"],
            "adetailer_steps": config["adetailer_steps"],
            "adetailer_denoise": config["adetailer_denoise"],
            "adetailer_cfg_scale": config["adetailer_cfg"],
            "adetailer_prompt": config["adetailer_prompt"],
            "adetailer_negative_prompt": config["adetailer_negative_prompt"],
        }

        if scheduler_value != "inherit":
            payload["adetailer_scheduler"] = scheduler_value

        return payload

    def set_sampler_options(self, samplers: Iterable[str] | None) -> None:
        """Update the sampler dropdown with the provided options."""
        cleaned: list[str] = []
        for sampler in samplers or []:
            if sampler is None:
                continue
            text = str(sampler).strip()
            if text and text not in cleaned:
                cleaned.append(text)

        if not cleaned:
            cleaned = ["Euler a"]

        cleaned.sort(key=str.lower)
        self.sampler_combo.configure(values=cleaned)

        current = self.sampler_var.get()
        if current not in cleaned:
            self.sampler_var.set(cleaned[0])

```

## `src/gui/advanced_prompt_editor.py`

```
"""
Advanced Prompt Pack Editor with validation, embedding/LoRA discovery, and smart features
"""

import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ..utils.config import DEFAULT_GLOBAL_NEGATIVE_PROMPT
from .scrolling import make_scrollable
from .theme import (
    ASWF_BLACK,
    ASWF_DARK_GREY,
    ASWF_ERROR_RED,
    ASWF_GOLD,
    ASWF_LIGHT_GREY,
    ASWF_MED_GREY,
    ASWF_OK_GREEN,
)
from .tooltip import Tooltip


class AdvancedPromptEditor:
    """Advanced prompt pack editor with comprehensive validation and smart features"""

    def __init__(self, parent_window, config_manager, on_packs_changed=None, on_validation=None):
        self.parent = parent_window
        self.config_manager = config_manager
        self.on_packs_changed = on_packs_changed
        self.on_validation = on_validation  # Callback for validation results
        self.window = None
        self.current_pack_path = None
        self.is_modified = False

        # Model caches
        self.embeddings_cache = set()
        self.loras_cache = set()
        # Status label available immediately for tests and status updates
        try:
            self._status_var = tk.StringVar(value="Ready")
            # Create but do not pack; tests only require attribute presence and configurability
            self.status_text = ttk.Label(self.parent, textvariable=self._status_var)
        except Exception:
            # Fallback: minimal object with config() for environments without full Tk
            class _Dummy:
                def config(self, **kwargs):
                    return None

            self.status_text = _Dummy()

        # Ensure key Tk variables exist early to avoid attribute errors during load
        # These are re-bound to UI widgets later in _build_pack_info_panel
        try:
            if not hasattr(self, "pack_name_var"):
                self.pack_name_var = tk.StringVar()
            if not hasattr(self, "format_var"):
                self.format_var = tk.StringVar(value="txt")
        except Exception:
            # In environments without full Tk init, fall back to simple stand-ins
            class _Var:
                def __init__(self, value=""):
                    self._v = value

                def get(self):
                    return self._v

                def set(self, v):
                    self._v = v

            if not hasattr(self, "pack_name_var"):
                self.pack_name_var = _Var()
            if not hasattr(self, "format_var"):
                self.format_var = _Var("txt")

        # Default global negative content storage
        try:
            if self.config_manager and hasattr(self.config_manager, "get_global_negative_prompt"):
                self.global_neg_content = self.config_manager.get_global_negative_prompt()
            else:
                self.global_neg_content = DEFAULT_GLOBAL_NEGATIVE_PROMPT
        except Exception:
            self.global_neg_content = DEFAULT_GLOBAL_NEGATIVE_PROMPT

    def _attach_tooltip(self, widget: tk.Widget, text: str, delay: int = 1500) -> None:
        """Attach a tooltip to a widget when Tk is available."""
        try:
            Tooltip(widget, text, delay=delay)
        except Exception:
            pass

    def open_editor(self, pack_path=None):
        """Open the advanced prompt pack editor"""
        if self.window and self.window.winfo_exists():
            self.window.lift()
            if pack_path:
                try:
                    self._load_pack(Path(pack_path))
                except Exception:
                    pass
            return

        # Always use main Tk root as parent for Toplevel
        root = self.parent if isinstance(self.parent, tk.Tk) else self.parent.winfo_toplevel()
        self.window = tk.Toplevel(root)
        self.window.title("Advanced Prompt Pack Editor")
        self.window.geometry("1200x800")
        self.window.configure(bg=ASWF_BLACK)

        # Apply dark theme
        self._apply_dark_theme()

        # Build the UI
        self._build_advanced_ui()

        # Ensure persisted global negative and model caches are displayed
        self._refresh_global_negative_display()
        try:
            self._refresh_models()
        except Exception:
            pass

        # Load pack if specified
        if pack_path:
            self._load_pack(pack_path)
        else:
            self._new_pack()

        # Set up window close handling
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_dark_theme(self):
        """Apply consistent dark theme using ASWF colors"""
        style = ttk.Style()

        # Configure dark theme styles using ASWF colors
        style.configure("Dark.TFrame", background=ASWF_DARK_GREY)
        style.configure(
            "Dark.TLabel", background=ASWF_DARK_GREY, foreground=ASWF_GOLD
        )  # Gold text on dark background
        style.configure(
            "Dark.TButton", background=ASWF_MED_GREY, foreground="white"
        )  # White text on gray background
        style.configure(
            "Dark.TEntry",
            background=ASWF_MED_GREY,
            fieldbackground=ASWF_MED_GREY,
            foreground="white",  # White text on gray background
            insertcolor=ASWF_GOLD,
        )
        style.configure(
            "Dark.TCombobox", background=ASWF_MED_GREY, foreground="white"
        )  # White text on gray background
        style.configure("Dark.TNotebook", background=ASWF_DARK_GREY)
        style.configure(
            "Dark.TNotebook.Tab", background=ASWF_MED_GREY, foreground="white"
        )  # White text on gray background

    def _build_advanced_ui(self):
        """Build the advanced editor interface"""
        main_frame = ttk.Frame(self.window, style="Dark.TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Toolbar
        self._build_toolbar(main_frame)

        # Pack information panel
        self._build_pack_info_panel(main_frame)

        # Main content area with notebook tabs
        self._build_content_notebook(main_frame)

        # Status bar
        self._build_status_bar(main_frame)

    def _build_toolbar(self, parent):
        """Build the toolbar with all editor actions"""
        toolbar = ttk.Frame(parent, style="Dark.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 10))

        # File operations
        file_frame = ttk.LabelFrame(toolbar, text="File", style="Dark.TLabelframe")
        file_frame.pack(side=tk.LEFT, padx=(0, 10))

        new_btn = ttk.Button(file_frame, text="New", command=self._new_pack, width=10)
        new_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(new_btn, "Create a new blank prompt pack.")

        open_btn = ttk.Button(file_frame, text="Open", command=self._open_pack, width=10)
        open_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(open_btn, "Browse for an existing prompt pack to edit.")

        save_btn = ttk.Button(file_frame, text="Save", command=self._save_pack, width=10)
        save_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(save_btn, "Save changes to the currently loaded pack.")

        save_as_btn = ttk.Button(file_frame, text="Save As", command=self._save_pack_as, width=10)
        save_as_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(save_as_btn, "Save the current pack contents to a new file.")

        # Pack operations
        pack_frame = ttk.LabelFrame(toolbar, text="Pack", style="Dark.TLabelframe")
        pack_frame.pack(side=tk.LEFT, padx=(0, 10))

        clone_btn = ttk.Button(pack_frame, text="Clone Pack", command=self._clone_pack, width=12)
        clone_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(clone_btn, "Duplicate the currently loaded pack under a new name.")

        delete_btn = ttk.Button(pack_frame, text="Delete Pack", command=self._delete_pack, width=12)
        delete_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(delete_btn, "Delete the current pack file from disk.")

        # Validation operations
        validation_frame = ttk.LabelFrame(toolbar, text="Validation", style="Dark.TLabelframe")
        validation_frame.pack(side=tk.LEFT, padx=(0, 10))

        validate_btn = ttk.Button(
            validation_frame, text="Run Validation", command=self._validate_pack, width=14
        )
        validate_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(validate_btn, "Run all syntax checks on the current pack.")

        auto_fix_btn = ttk.Button(
            validation_frame, text="Auto Fix", command=self._auto_fix, width=10
        )
        auto_fix_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(auto_fix_btn, "Attempt to fix common validation issues automatically.")

        models_btn = ttk.Button(
            validation_frame, text="Refresh Models", command=self._refresh_models, width=14
        )
        models_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(
            models_btn, "Reload available embeddings and LoRAs for validation checks."
        )

    def _build_pack_info_panel(self, parent):
        """Build pack information panel"""
        info_frame = ttk.LabelFrame(parent, text="Pack Information", style="Dark.TLabelframe")
        info_frame.pack(fill=tk.X, pady=(0, 10))

        info_grid = ttk.Frame(info_frame, style="Dark.TFrame")
        info_grid.pack(fill=tk.X, padx=10, pady=5)

        # Pack name
        ttk.Label(info_grid, text="Name:", style="Dark.TLabel").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 5)
        )
        self.pack_name_var = tk.StringVar()
        self.pack_name_entry = ttk.Entry(
            info_grid, textvariable=self.pack_name_var, width=30, style="Dark.TEntry"
        )
        self.pack_name_entry.grid(row=0, column=1, padx=(0, 20), sticky=tk.W)
        self.pack_name_entry.bind("<KeyRelease>", self._on_content_changed)

        # Format
        ttk.Label(info_grid, text="Format:", style="Dark.TLabel").grid(
            row=0, column=2, sticky=tk.W, padx=(0, 5)
        )
        self.format_var = tk.StringVar(value="txt")
        format_combo = ttk.Combobox(
            info_grid,
            textvariable=self.format_var,
            values=["txt", "tsv"],
            width=8,
            state="readonly",
            style="Dark.TCombobox",
        )
        format_combo.grid(row=0, column=3, padx=(0, 20), sticky=tk.W)
        format_combo.bind("<<ComboboxSelected>>", self._on_format_changed)

        # Statistics
        ttk.Label(info_grid, text="Stats:", style="Dark.TLabel").grid(
            row=0, column=4, sticky=tk.W, padx=(0, 5)
        )
        self.stats_label = ttk.Label(info_grid, text="0 prompts", style="Dark.TLabel")
        self.stats_label.grid(row=0, column=5, sticky=tk.W)

        # Status
        self.status_label = ttk.Label(
            info_grid, text="Ready", style="Dark.TLabel", foreground=ASWF_OK_GREEN
        )
        self.status_label.grid(row=0, column=6, padx=(20, 0), sticky=tk.E)

        # Configure grid weights
        info_grid.columnconfigure(5, weight=1)

    def _build_content_notebook(self, parent):
        """Build the main content notebook"""
        self.notebook = ttk.Notebook(parent, style="Dark.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Prompts editor tab
        self._build_prompts_tab()

        # Global negative tab
        self._build_global_negative_tab()

        # Validation results tab
        self._build_validation_tab()

        # Model browser tab
        self._build_models_tab()

        # Help tab
        self._build_help_tab()

    def _build_prompts_tab(self):
        """Build the main prompts editing tab"""
        prompts_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(prompts_frame, text="📝 Prompts")

        # Editor controls
        controls_frame = ttk.Frame(prompts_frame, style="Dark.TFrame")
        controls_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(controls_frame, text="Prompt Content:", style="Dark.TLabel").pack(side=tk.LEFT)

        # Format hint
        self.format_hint_label = ttk.Label(
            controls_frame,
            text="TXT Format: Separate prompts with blank lines",
            style="Dark.TLabel",
            foreground=ASWF_LIGHT_GREY,
        )
        self.format_hint_label.pack(side=tk.RIGHT)

        # Text editor
        editor_frame = ttk.Frame(prompts_frame, style="Dark.TFrame")
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Create text widget with scrollbars
        text_container = tk.Frame(editor_frame, bg=ASWF_BLACK)
        text_container.pack(fill=tk.BOTH, expand=True)

        # Vertical scrollbar
        v_scrollbar = tk.Scrollbar(text_container, bg=ASWF_DARK_GREY)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Horizontal scrollbar
        h_scrollbar = tk.Scrollbar(text_container, orient=tk.HORIZONTAL, bg=ASWF_DARK_GREY)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # Text widget
        self.prompts_text = tk.Text(
            text_container,
            wrap=tk.NONE,  # Allow horizontal scrolling
            bg=ASWF_BLACK,
            fg="white",
            insertbackground="white",
            selectbackground=ASWF_GOLD,
            selectforeground="white",
            font=("Consolas", 11),
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set,
            undo=True,
            maxundo=50,
        )
        self.prompts_text.pack(fill=tk.BOTH, expand=True)

        # Configure scrollbars
        v_scrollbar.config(command=self.prompts_text.yview)
        h_scrollbar.config(command=self.prompts_text.xview)

        # Bind events
        self.prompts_text.bind("<KeyRelease>", self._on_content_changed)
        self.prompts_text.bind("<Button-1>", self._on_text_click)

        # Quick insert buttons
        quick_frame = ttk.Frame(prompts_frame, style="Dark.TFrame")
        quick_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        ttk.Label(quick_frame, text="Quick Insert:", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        quality_btn = ttk.Button(
            quick_frame, text="Quality Tags", command=lambda: self._insert_template("quality")
        )
        quality_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            quality_btn, "Insert a template of quality/clarity tags at the cursor."
        )

        style_btn = ttk.Button(
            quick_frame, text="Style Tags", command=lambda: self._insert_template("style")
        )
        style_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            style_btn, "Insert common style descriptors (e.g., cinematic, photorealistic)."
        )

        negative_btn = ttk.Button(
            quick_frame, text="Negative", command=lambda: self._insert_template("negative")
        )
        negative_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            negative_btn, "Insert a negative prompt scaffold for the current block."
        )

        lora_btn = ttk.Button(
            quick_frame, text="LoRA", command=lambda: self._insert_template("lora")
        )
        lora_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(lora_btn, "Insert a LoRA template (name and optional weight).")

        embedding_btn = ttk.Button(
            quick_frame, text="Embedding", command=lambda: self._insert_template("embedding")
        )
        embedding_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(embedding_btn, "Insert an embedding placeholder.")

    def _build_global_negative_tab(self):
        """Build the global negative prompt editor"""
        global_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(global_frame, text="?? Global Negative")

        shell = ttk.Frame(global_frame, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        _, body = make_scrollable(shell, style="Dark.TFrame")

        # Header
        header_frame = ttk.Frame(body, style="Dark.TFrame")
        header_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(
            header_frame,
            text="Global Negative Prompt",
            style="Dark.TLabel",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            header_frame,
            text="This prompt is automatically appended to all negative prompts during generation.",
            style="Dark.TLabel",
            foreground=ASWF_LIGHT_GREY,
        ).pack(anchor=tk.W, pady=(5, 0))

        # Editor
        self.global_neg_text = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            bg=ASWF_BLACK,
            fg="white",
            insertbackground="white",
            font=("Consolas", 10),
            height=15,
        )
        self.global_neg_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Load current global negative
        self.global_neg_text.delete("1.0", tk.END)
        self.global_neg_text.insert("1.0", self.global_neg_content)

        # Save button
        button_frame = ttk.Frame(body, style="Dark.TFrame")
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        save_global_btn = ttk.Button(
            button_frame, text="Save Global Negative", command=self._save_global_negative
        )
        save_global_btn.pack(side=tk.LEFT)
        self._attach_tooltip(
            save_global_btn,
            "Persist the global negative prompt so every pack you load inherits these safety terms.",
        )

        reset_global_btn = ttk.Button(
            button_frame, text="Reset to Default", command=self._reset_global_negative
        )
        reset_global_btn.pack(side=tk.LEFT, padx=(10, 0))
        self._attach_tooltip(
            reset_global_btn,
            "Restore the stock global negative prompt if your custom text causes issues.",
        )

    def _build_validation_tab(self):
        """Build the validation results tab"""
        validation_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(validation_frame, text="? Validation")

        shell = ttk.Frame(validation_frame, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        _, body = make_scrollable(shell, style="Dark.TFrame")

        # Validation controls
        controls_frame = ttk.Frame(body, style="Dark.TFrame")
        controls_frame.pack(fill=tk.X, padx=10, pady=10)

        run_validation_btn = ttk.Button(
            controls_frame, text="Run Validation", command=self._validate_pack
        )
        run_validation_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tooltip(
            run_validation_btn,
            "Analyze the open pack for syntax, missing models, and angle bracket issues.",
        )
        auto_fix_btn = ttk.Button(controls_frame, text="Auto Fix Issues", command=self._auto_fix)
        auto_fix_btn.pack(side=tk.LEFT)
        self._attach_tooltip(
            auto_fix_btn,
            "Attempt to repair common validation problems automatically (experimental).",
        )

        # Auto-validate checkbox
        self.auto_validate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            controls_frame,
            text="Auto-validate on changes",
            variable=self.auto_validate_var,
            style="Dark.TCheckbutton",
        ).pack(side=tk.RIGHT)

        # Results display
        self.validation_text = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            bg=ASWF_BLACK,
            fg="white",
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        self.validation_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Configure text tags for colored output
        self.validation_text.tag_configure("error", foreground=ASWF_ERROR_RED)
        self.validation_text.tag_configure("warning", foreground=ASWF_GOLD)
        self.validation_text.tag_configure("success", foreground=ASWF_OK_GREEN)
        self.validation_text.tag_configure("info", foreground=ASWF_GOLD)

    def _build_status_bar(self, parent):
        """Build status bar at bottom of editor window"""
        status_frame = ttk.Frame(parent, style="Dark.TFrame")
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))

        # Recreate status_text within the editor window (not parent)
        self._status_var = tk.StringVar(value="Ready")
        self.status_text = ttk.Label(
            status_frame,
            textvariable=self._status_var,
            style="Dark.TLabel",
            anchor=tk.W,
            font=("Segoe UI", 9),
        )
        self.status_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    def _build_models_tab(self):
        """Build the models browser tab"""
        models_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(models_frame, text="?? Models")

        shell = ttk.Frame(models_frame, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        _, body = make_scrollable(shell, style="Dark.TFrame")

        # Create paned window for embeddings and LoRAs
        paned_window = ttk.PanedWindow(body, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True)

        # Embeddings panel
        embeddings_frame = ttk.LabelFrame(paned_window, text="Embeddings", style="Dark.TLabelframe")
        paned_window.add(embeddings_frame)

        self.embeddings_listbox = tk.Listbox(
            embeddings_frame,
            bg=ASWF_MED_GREY,
            fg="white",
            selectbackground=ASWF_GOLD,
            font=("Consolas", 9),
        )
        self.embeddings_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.embeddings_listbox.bind("<Double-Button-1>", self._insert_embedding)

        # LoRAs panel
        loras_frame = ttk.LabelFrame(paned_window, text="LoRAs", style="Dark.TLabelframe")
        paned_window.add(loras_frame)

        self.loras_listbox = tk.Listbox(
            loras_frame,
            bg=ASWF_MED_GREY,
            fg="white",
            selectbackground=ASWF_GOLD,
            font=("Consolas", 9),
        )
        self.loras_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.loras_listbox.bind("<Double-Button-1>", self._insert_lora)

        # Populate lists
        self._populate_model_lists()

        # Instructions
        instructions_frame = ttk.Frame(body, style="Dark.TFrame")
        instructions_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Label(
            instructions_frame,
            text="?? Double-click to insert into prompt. Embeddings: <embedding:name>, LoRAs: <lora:name:1.0>",
            style="Dark.TLabel",
            foreground=ASWF_LIGHT_GREY,
        ).pack()

    def _build_help_tab(self):
        """Build the help tab"""
        help_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(help_frame, text="? Help")

        shell = ttk.Frame(help_frame, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        _, body = make_scrollable(shell, style="Dark.TFrame")

        help_text = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            bg=ASWF_BLACK,
            fg="white",
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        help_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        help_content = """
ADVANCED PROMPT PACK EDITOR - HELP

📝 PROMPT FORMATS:

TXT Format (Block-based):
Each prompt block is separated by blank lines. Use 'neg:' prefix for negative prompts.

Example:
masterpiece, best quality, portrait of a woman
detailed face, beautiful eyes
neg: blurry, bad quality, distorted

landscape, mountains, sunset, golden hour
cinematic lighting, epic composition
neg: ugly, malformed, oversaturated

TSV Format (Tab-separated):
Each line: [positive prompt][TAB][negative prompt]

Example:
masterpiece, portrait	blurry, bad quality
landscape, mountains	ugly, malformed

🎭 EMBEDDINGS & LORAS:

Embeddings:
<embedding:name>
- Use exact filename without extension
- Case-sensitive
- Example: <embedding:BadDream>

LoRAs:
<lora:name:weight>
- Weight range: 0.0 to 2.0 (default: 1.0)
- Example: <lora:add-detail-xl:0.8>

🚫 GLOBAL NEGATIVE PROMPT:

The global negative prompt is automatically appended to ALL negative prompts during generation.
Edit it in the "Global Negative" tab to set safety and quality terms that apply universally.

✅ VALIDATION FEATURES:

- Missing embeddings/LoRAs detection
- Invalid syntax checking
- Weight range validation
- Blank prompt detection
- Character encoding verification
- Auto-fix common issues

🔧 KEYBOARD SHORTCUTS:

Ctrl+Z: Undo
Ctrl+Y: Redo
Ctrl+S: Save
Ctrl+N: New pack
Ctrl+O: Open pack

🔍 AUTO-VALIDATION:

Enable auto-validation to check your prompts as you type.
Errors and warnings appear in the Validation tab.

💡 TIPS:

- Use the Models tab to browse available embeddings/LoRAs
- Double-click model names to insert them automatically
- Use Quick Insert buttons for common prompt templates
- Keep prompts under 1000 characters for best performance
- Test prompts with single generations before batch processing

📁 FILE MANAGEMENT:

- Clone: Create a copy of the current pack
- Delete: Remove pack file (careful - this is permanent!)
- Auto-save: Changes are marked with * in title
- UTF-8: All files saved with proper encoding for international text

🎯 VALIDATION LEVELS:

🔴 Errors: Must be fixed (missing models, syntax errors)
🟡 Warnings: Should be reviewed (long prompts, unusual weights)
🟢 Success: Pack is valid and ready to use
"""

        help_text.config(state=tk.NORMAL)
        help_text.insert(tk.END, help_content)
        help_text.config(state=tk.DISABLED)

    def _candidate_model_roots(self) -> list[Path]:
        """Return likely Stable Diffusion WebUI roots for model discovery."""

        roots: list[Path] = []
        seen: set[str] = set()

        def add(path_like):
            if not path_like:
                return
            try:
                candidate = Path(path_like).expanduser()
            except Exception:
                return
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            key = str(resolved).lower()
            if key in seen or not resolved.exists():
                return
            seen.add(key)
            roots.append(resolved)

        # Environment overrides
        for env_var in ("STABLENEW_MODEL_ROOT", "STABLENEW_MODELS_ROOT", "WEBUI_ROOT"):
            try:
                add(os.environ.get(env_var))
            except Exception:
                continue

        # Common install locations
        add(Path.home() / "stable-diffusion-webui")
        add(Path.cwd() / "stable-diffusion-webui")
        try:
            add(Path(__file__).resolve().parents[3] / "stable-diffusion-webui")
        except Exception:
            pass

        return roots

    @staticmethod
    def _collect_model_names(directory: Path, suffixes: set[str]) -> set[str]:
        """Collect model file stems from a directory tree."""

        names: set[str] = set()
        if not directory or not directory.exists():
            return names
        try:
            for file in directory.rglob("*"):
                if file.is_file() and file.suffix.lower() in suffixes:
                    names.add(file.stem)
        except Exception:
            return names
        return names

    def _load_model_caches(self):
        """Load embeddings and LoRAs into local caches.

        Scans known WebUI folders (or overrides) so the editor can offer
        up-to-date insertion menus and validation for embeddings/LoRAs.
        """
        embedding_suffixes = {".pt", ".bin", ".ckpt", ".safetensors", ".embedding"}
        lora_suffixes = {".safetensors", ".ckpt", ".pt"}

        embeddings: set[str] = set()
        loras: set[str] = set()

        for root in self._candidate_model_roots():
            embeddings_dir_candidates = [
                root / "embeddings",
                root / "models" / "embeddings",
            ]
            for directory in embeddings_dir_candidates:
                embeddings.update(self._collect_model_names(directory, embedding_suffixes))

            lora_dir_candidates = [
                root / "loras",
                root / "models" / "Lora",
                root / "models" / "LoRA",
                root / "models" / "LORA",
                root / "models" / "lycoris",
                root / "models" / "LyCORIS",
            ]
            for directory in lora_dir_candidates:
                loras.update(self._collect_model_names(directory, lora_suffixes))

        self.embeddings_cache = embeddings
        self.loras_cache = loras

    def _refresh_global_negative_display(self):
        """Refresh the global negative text editor from stored content."""
        try:
            if self.config_manager and hasattr(self.config_manager, "get_global_negative_prompt"):
                latest = self.config_manager.get_global_negative_prompt()
                self.global_neg_content = latest
            else:
                latest = getattr(self, "global_neg_content", DEFAULT_GLOBAL_NEGATIVE_PROMPT)
            if hasattr(self, "global_neg_text") and self.global_neg_text:
                self.global_neg_text.delete("1.0", tk.END)
                self.global_neg_text.insert("1.0", latest)
        except Exception:
            # Non-fatal in headless or partial UI scenarios
            pass

    def _populate_model_lists(self):
        """Populate the embeddings and LoRAs lists"""
        if not hasattr(self, "embeddings_listbox") or not hasattr(self, "loras_listbox"):
            return
        # Clear existing items
        self.embeddings_listbox.delete(0, tk.END)
        self.loras_listbox.delete(0, tk.END)

        # Add embeddings
        for embedding in sorted(self.embeddings_cache):
            self.embeddings_listbox.insert(tk.END, embedding)

        # Add LoRAs
        for lora in sorted(self.loras_cache):
            self.loras_listbox.insert(tk.END, lora)
        # Update counts in status
        embeddings = sorted(getattr(self, "embeddings_cache", set()))
        loras = sorted(getattr(self, "loras_cache", set()))
        embed_count = len(embeddings)
        lora_count = len(loras)

        if hasattr(self, "status_text"):
            if embed_count or lora_count:
                status = f"Models: {embed_count} embeddings, {lora_count} LoRAs"
            else:
                status = "Models refreshed (none found)"
            self.status_text.config(text=status)

        if not hasattr(self, "embeddings_listbox") or not hasattr(self, "loras_listbox"):
            return

        # Clear existing items
        self.embeddings_listbox.delete(0, tk.END)
        self.loras_listbox.delete(0, tk.END)

        # Add embeddings
        for embedding in embeddings:
            self.embeddings_listbox.insert(tk.END, embedding)

        # Add LoRAs
        for lora in loras:
            self.loras_listbox.insert(tk.END, lora)

    def _refresh_models(self):
        """Refresh the model caches"""
        if hasattr(self, "status_text"):
            self.status_text.config(text="Refreshing models...")
        self._load_model_caches()
        self._populate_model_lists()

    def _insert_embedding(self, event=None):
        """Insert selected embedding into prompt"""
        selection = self.embeddings_listbox.curselection()
        if selection:
            embedding_name = self.embeddings_listbox.get(selection[0])
            self._insert_at_cursor(f"<embedding:{embedding_name}>")

    def _insert_lora(self, event=None):
        """Insert selected LoRA into prompt"""
        selection = self.loras_listbox.curselection()
        if selection:
            lora_name = self.loras_listbox.get(selection[0])
            self._insert_at_cursor(f"<lora:{lora_name}:1.0>")

    def _insert_at_cursor(self, text):
        """Insert text at current cursor position"""
        self.prompts_text.insert(tk.INSERT, text)
        self._on_content_changed()

    def _insert_template(self, template_type):
        """Insert predefined templates"""
        templates = {
            "quality": "masterpiece, best quality, 8k, high resolution, detailed",
            "style": "cinematic lighting, dramatic composition, photorealistic",
            "negative": "neg: blurry, bad quality, distorted, ugly, malformed",
            "lora": "<lora:name:1.0>",
            "embedding": "<embedding:name>",
        }

        if template_type in templates:
            self._insert_at_cursor(templates[template_type])

    def _on_format_changed(self, event=None):
        """Handle format change"""
        format_type = self.format_var.get()
        if format_type == "txt":
            self.format_hint_label.config(text="TXT Format: Separate prompts with blank lines")
        else:
            self.format_hint_label.config(
                text="TSV Format: [positive prompt][TAB][negative prompt]"
            )

        self._on_content_changed()

    def _on_content_changed(self, event=None):
        """Handle content changes"""
        if not self.is_modified:
            self.is_modified = True
            if self.current_pack_path:
                self.window.title(f"Advanced Prompt Pack Editor - {self.current_pack_path.name} *")
            else:
                self.window.title("Advanced Prompt Pack Editor - Untitled *")

        # Auto-validate if enabled
        if hasattr(self, "auto_validate_var") and self.auto_validate_var.get():
            self.window.after(1000, self._auto_validate)  # Delayed validation

    def _auto_validate(self):
        """Perform automatic validation after changes"""
        if self.is_modified:  # Only validate if still modified
            self._validate_pack_silent()

    def _on_text_click(self, event=None):
        """Handle text click for context-sensitive help"""
        # Could add context-sensitive help or suggestions here
        pass

    def _new_pack(self):
        """Create a new prompt pack"""
        if self._check_unsaved_changes():
            self.current_pack_path = None
            self.pack_name_var.set("new_pack")
            self.format_var.set("txt")
            self.prompts_text.delete("1.0", tk.END)

            # Insert template content
            template = """# New Prompt Pack
# Add your prompts here. Separate different prompts with blank lines.
# Use 'neg:' prefix for negative prompts within a block.

masterpiece, best quality, detailed artwork
beautiful composition, professional quality
neg: blurry, bad quality, distorted, ugly

portrait of a character, detailed face
expressive eyes, natural lighting
neg: malformed, bad anatomy, low quality"""

            self.prompts_text.insert("1.0", template)
            self.is_modified = False
            self.window.title("Advanced Prompt Pack Editor - New Pack")
            self._validate_pack_silent()

    def _open_pack(self):
        """Open an existing prompt pack"""
        if not self._check_unsaved_changes():
            return

        file_path = filedialog.askopenfilename(
            title="Open Prompt Pack",
            initialdir="packs",
            filetypes=[("Text files", "*.txt"), ("TSV files", "*.tsv"), ("All files", "*.*")],
        )

        if file_path:
            self._load_pack(Path(file_path))

    def _save_pack_as(self):
        """Save the current pack to a new file via dialog"""
        # Determine proposed filename
        base_name = self.pack_name_var.get().strip() or "new_pack"
        ext = (self.format_var.get() or "txt").lower()
        initial = str(Path("packs") / f"{base_name}.{ext}")

        file_path = filedialog.asksaveasfilename(
            title="Save Prompt Pack As",
            initialfile=Path(initial).name,
            initialdir="packs",
            defaultextension=f".{ext}",
            filetypes=[
                ("Text files", "*.txt"),
                ("TSV files", "*.tsv"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        self._save_content_to_path(Path(file_path))

    def _load_pack(self, pack_path: Path):
        """Load a prompt pack from file"""
        try:
            with open(pack_path, encoding="utf-8") as f:
                content = f.read()

            self.current_pack_path = pack_path
            # Auto-populate pack name from filename
            self.pack_name_var.set(pack_path.stem)
            self.format_var.set(pack_path.suffix[1:] if pack_path.suffix else "txt")

            self.prompts_text.delete("1.0", tk.END)
            self.prompts_text.insert("1.0", content)

            self.is_modified = False
            self.window.title(f"Advanced Prompt Pack Editor - {pack_path.name}")

            # Validate the loaded content
            self._validate_pack_silent()

            # Update format hint
            self._on_format_changed()
            # Load and display global negative if present in config
            self._refresh_global_negative_display()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load pack: {e}")

    def _save_pack(self):
        """Save the current pack (or prompt for location if untitled)"""
        if self.current_pack_path:
            self._save_content_to_path(self.current_pack_path)
        else:
            self._save_pack_as()

    def _save_content_to_path(self, path: Path):
        """Core logic to validate and save to a path"""
        try:
            content = self.prompts_text.get("1.0", tk.END).strip()

            # Validate before saving
            validation_results = self._validate_content(content)
            if validation_results["errors"]:
                if not messagebox.askyesno(
                    "Validation Errors",
                    f"Pack has {len(validation_results['errors'])} errors:\n\n"
                    f"{chr(10).join(validation_results['errors'][:3])}\n\n"
                    f"Save anyway?",
                ):
                    return

            # Ensure directory exists
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            self.current_pack_path = path
            # Update name and title
            try:
                self.pack_name_var.set(path.stem)
            except Exception:
                pass
            self.is_modified = False
            if self.window:
                self.window.title(f"Advanced Prompt Pack Editor - {path.name}")
            if hasattr(self, "_status_var"):
                self._status_var.set(f"Saved: {path.name}")

            # Notify parent of changes
            if self.on_packs_changed:
                self.on_packs_changed()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save pack: {e}")

    def _clone_pack(self):
        """Clone the current pack to a new untitled name"""
        if not self.current_pack_path:
            messagebox.showinfo("Info", "No pack loaded to clone")
            return

        original_name = (self.pack_name_var.get() or self.current_pack_path.stem).strip()
        clone_name = f"{original_name}_copy"

        # Find available name within packs directory
        ext = (
            self.format_var.get()
            or (self.current_pack_path.suffix[1:] if self.current_pack_path else "txt")
        ).lower()
        counter = 1
        while (Path("packs") / f"{clone_name}.{ext}").exists():
            clone_name = f"{original_name}_copy_{counter}"
            counter += 1

        self.pack_name_var.set(clone_name)
        self.current_pack_path = None
        self.is_modified = True
        if self.window:
            self.window.title(f"Advanced Prompt Pack Editor - {clone_name} (Clone) *")
        if hasattr(self, "_status_var"):
            self._status_var.set(f"Cloned as: {clone_name}")

    def _delete_pack(self):
        """Delete the current pack"""
        if not self.current_pack_path:
            messagebox.showinfo("Info", "No pack loaded to delete")
            return

        if messagebox.askyesno(
            "Confirm Delete",
            "This action cannot be undone.",
        ):
            try:
                deleted_name = self.current_pack_path.name
                self.current_pack_path.unlink()
                self.current_pack_path = None
                self.pack_name_var.set("")
                self.prompts_text.delete("1.0", tk.END)
                self.is_modified = False
                self.window.title("Advanced Prompt Pack Editor - Deleted")
                if hasattr(self, "status_text"):
                    self.status_text.config(text=f"Deleted: {deleted_name}")
                # Notify parent of changes
                if self.on_packs_changed:
                    self.on_packs_changed()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete pack: {e}")

    def _validate_pack(self):
        """Validate the current pack and show results"""
        content = self.prompts_text.get("1.0", tk.END).strip()
        results = self._validate_content(content)

        # Switch to validation tab
        self.notebook.select(2)  # Validation tab

        # Display results
        self._display_validation_results(results)

        # Call validation callback if present
        if self.on_validation:
            self.on_validation(results)

        return results

    def _validate_pack_silent(self):
        """Validate pack without switching tabs"""
        content = self.prompts_text.get("1.0", tk.END).strip()
        results = self._validate_content(content)

        # Update status and stats
        self._update_status_from_validation(results)

        return results

    def _validate_content(self, content: str) -> dict:
        """Validate pack content and return comprehensive results"""
        results = {
            "errors": [],
            "warnings": [],
            "info": [],
            "stats": {
                "prompt_count": 0,
                "embedding_count": 0,
                "lora_count": 0,
                "total_chars": len(content),
                "avg_prompt_length": 0,
            },
        }

        if not content.strip():
            results["errors"].append("Pack is empty")
            return results

        # Determine format and validate accordingly
        is_tsv = self.format_var.get() == "tsv"

        if is_tsv:
            self._validate_tsv_content(content, results)
        else:
            self._validate_txt_content(content, results)

        # Calculate average prompt length
        if results["stats"]["prompt_count"] > 0:
            results["stats"]["avg_prompt_length"] = (
                results["stats"]["total_chars"] / results["stats"]["prompt_count"]
            )

        return results

    def _validate_tsv_content(self, content: str, results: dict):
        """Validate TSV format content"""
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")
            if len(parts) < 1:
                results["errors"].append(f"Line {i}: Empty line")
                continue

            positive = parts[0].strip()
            if not positive:
                results["warnings"].append(f"Line {i}: Empty positive prompt")
            else:
                self._validate_prompt_text(positive, f"Line {i} (positive)", results)

            if len(parts) > 1:
                negative = parts[1].strip()
                if negative:
                    self._validate_prompt_text(negative, f"Line {i} (negative)", results)

            results["stats"]["prompt_count"] += 1

    def _validate_txt_content(self, content: str, results: dict):
        """Validate TXT format content"""
        blocks = content.split("\n\n")
        block_num = 0

        for block in blocks:
            block = block.strip()
            if not block or all(
                line.startswith("#") for line in block.splitlines() if line.strip()
            ):
                continue

            block_num += 1
            lines = [line.strip() for line in block.splitlines()]
            lines = [line for line in lines if line and not line.startswith("#")]

            if not lines:
                results["warnings"].append(f"Block {block_num}: Empty block")
                continue

            positive_parts = []
            negative_parts = []

            for line in lines:
                if line.startswith("neg:"):
                    neg_content = line[4:].strip()
                    if neg_content:
                        negative_parts.append(neg_content)
                        self._validate_prompt_text(
                            neg_content, f"Block {block_num} (negative)", results
                        )
                else:
                    positive_parts.append(line)
                    self._validate_prompt_text(line, f"Block {block_num} (positive)", results)

            if not positive_parts:
                results["warnings"].append(f"Block {block_num}: No positive prompt content")

            results["stats"]["prompt_count"] += 1

    def _validate_prompt_text(self, prompt: str, location: str, results: dict):
        """Validate individual prompt text"""
        # Check embeddings
        embedding_pattern = re.compile(r"<embedding:([^>]+)>", flags=re.IGNORECASE)
        embeddings = embedding_pattern.findall(prompt)
        embedding_cache = {e.lower() for e in getattr(self, "embeddings_cache", set())}

        for embedding in embeddings:
            name = embedding.strip()
            results["stats"]["embedding_count"] += 1

            if embedding_cache and name.lower() not in embedding_cache:
                results["errors"].append(f"{location}: Unknown embedding '{name}'")
            else:
                results["info"].append(f"{location}: Found embedding '{name}'")

        # Check LoRAs
        lora_pattern = re.compile(r"<lora:([^:>]+)(?::([^>]+))?>", flags=re.IGNORECASE)
        loras = lora_pattern.findall(prompt)
        lora_cache = {entry.lower() for entry in getattr(self, "loras_cache", set())}

        for lora_name, weight in loras:
            name = lora_name.strip()
            results["stats"]["lora_count"] += 1

            if lora_cache and name.lower() not in lora_cache:
                results["errors"].append(f"{location}: Unknown LoRA '{name}'")
            else:
                results["info"].append(f"{location}: Found LoRA '{name}'")

            if weight:
                try:
                    weight_val = float(weight)
                    if not (0.0 <= weight_val <= 2.0):
                        results["warnings"].append(
                            f"{location}: LoRA weight {weight_val} outside recommended range (0.0-2.0)"
                        )
                    elif weight_val == 0.0:
                        results["warnings"].append(
                            f"{location}: LoRA weight is 0.0 - this will have no effect"
                        )
                except ValueError:
                    results["errors"].append(
                        f"{location}: Invalid LoRA weight '{weight}' - must be a number"
                    )
            else:
                results["info"].append(f"{location}: LoRA '{name}' using default weight (1.0)")

        # Check for common syntax errors
        if "<<" in prompt or ">>" in prompt:
            results["warnings"].append(
                f"{location}: Double angle brackets found - did you mean single brackets?"
            )

        token_pattern = re.compile(r"<[A-Za-z0-9_]+:[^<>]+>")
        sanitized = token_pattern.sub("", prompt)
        sanitized = re.sub(r"<\s*>", "", sanitized)

        if sanitized.count("<") != sanitized.count(">"):
            results["errors"].append(f"{location}: Mismatched angle brackets")

        # Check for very long prompts
        if len(prompt) > 1000:
            results["warnings"].append(
                f"{location}: Very long prompt ({len(prompt)} chars) - may cause issues"
            )

        # Check for suspicious patterns
        if re.search(r"<[^>]*[<>][^>]*>", sanitized):
            results["errors"].append(f"{location}: Nested angle brackets detected")

        # Check for common typos in tags
        common_typos = {
            "masterpeice": "masterpiece",
            "hight quality": "high quality",
            "beatiful": "beautiful",
            "photorealstic": "photorealistic",
        }

        for typo, correction in common_typos.items():
            if typo in prompt.lower():
                results["warnings"].append(
                    f"{location}: Possible typo '{typo}' - did you mean '{correction}'?"
                )

    def _display_validation_results(self, results: dict):
        """Display validation results in the validation tab"""
        self.validation_text.config(state=tk.NORMAL)
        self.validation_text.delete("1.0", tk.END)

        # Summary
        total_issues = len(results["errors"]) + len(results["warnings"])
        if total_issues == 0:
            self.validation_text.insert(tk.END, "✅ VALIDATION PASSED\n\n", "success")
            self.validation_text.insert(
                tk.END, "No issues found. Pack is ready for use!\n\n", "success"
            )
        else:
            if results["errors"]:
                self.validation_text.insert(
                    tk.END, f"❌ {len(results['errors'])} ERRORS FOUND\n", "error"
                )
                for error in results["errors"]:
                    self.validation_text.insert(tk.END, f"  • {error}\n", "error")
                self.validation_text.insert(tk.END, "\n")

            if results["warnings"]:
                self.validation_text.insert(
                    tk.END, f"⚠️ {len(results['warnings'])} WARNINGS\n", "warning"
                )
                for warning in results["warnings"]:
                    self.validation_text.insert(tk.END, f"  • {warning}\n", "warning")
                self.validation_text.insert(tk.END, "\n")

        # Statistics
        stats = results["stats"]
        self.validation_text.insert(tk.END, "📊 STATISTICS\n", "info")
        self.validation_text.insert(tk.END, f"  • Prompts: {stats['prompt_count']}\n", "info")
        self.validation_text.insert(tk.END, f"  • Embeddings: {stats['embedding_count']}\n", "info")
        self.validation_text.insert(tk.END, f"  • LoRAs: {stats['lora_count']}\n", "info")
        self.validation_text.insert(
            tk.END, f"  • Total characters: {stats['total_chars']}\n", "info"
        )
        if stats["avg_prompt_length"] > 0:
            self.validation_text.insert(
                tk.END,
                f"  • Average prompt length: {stats['avg_prompt_length']:.0f} chars\n",
                "info",
            )

        # Information messages
        if results["info"]:
            self.validation_text.insert(
                tk.END, f"\n💡 INFO ({len(results['info'])} items)\n", "info"
            )
            # Only show first few info messages to avoid clutter
            for info in results["info"][:10]:
                self.validation_text.insert(tk.END, f"  • {info}\n", "info")
            if len(results["info"]) > 10:
                self.validation_text.insert(
                    tk.END, f"  • ... and {len(results['info']) - 10} more\n", "info"
                )

        self.validation_text.config(state=tk.DISABLED)

    def _update_status_from_validation(self, results: dict):
        """Update status labels from validation results"""
        stats = results["stats"]

        # Update stats label
        self.stats_label.config(
            text=f"{stats['prompt_count']} prompts, {stats['embedding_count']} embeddings, {stats['lora_count']} LoRAs"
        )

        # Update status label
        if results["errors"]:
            self.status_label.config(
                text=f"{len(results['errors'])} errors", foreground=ASWF_ERROR_RED
            )
        elif results["warnings"]:
            self.status_label.config(
                text=f"{len(results['warnings'])} warnings", foreground="#ffa726"
            )
        else:
            self.status_label.config(text="Valid", foreground="#66bb6a")

    def _auto_fix(self):
        """Automatically fix common issues"""
        content = self.prompts_text.get("1.0", tk.END)
        original_content = content

        fixes_applied = []

        # Fix double angle brackets
        if "<<" in content or ">>" in content:
            content = content.replace("<<", "<").replace(">>", ">")
            fixes_applied.append("Fixed double angle brackets")

        # Fix missing colons in LoRA syntax
        # Pattern: <lora name> -> <lora:name>
        lora_fixes = re.sub(r"<lora\s+([^:>]+)>", r"<lora:\1>", content)
        if lora_fixes != content:
            content = lora_fixes
            fixes_applied.append("Added missing colons to LoRA syntax")

        # Fix missing weights in LoRA syntax (add default 1.0)
        weight_fixes = re.sub(r"<lora:([^:>]+)>", r"<lora:\1:1.0>", content)
        if weight_fixes != content:
            content = weight_fixes
            fixes_applied.append("Added default weights to LoRAs")

        # Normalize whitespace
        lines = content.splitlines()
        cleaned_lines = []
        for line in lines:
            # Normalize internal whitespace but preserve leading/trailing for formatting
            if line.strip():
                # Remove multiple spaces within content but preserve single spaces
                cleaned_line = re.sub(r" +", " ", line.strip())
                cleaned_lines.append(cleaned_line)
            else:
                cleaned_lines.append("")  # Keep blank lines for formatting

        content = "\n".join(cleaned_lines)

        # Remove excessive blank lines (more than 2 consecutive)
        content = re.sub(r"\n{3,}", "\n\n", content)
        fixes_applied.append("Normalized whitespace")

        # Fix common typos
        typo_fixes = {
            "masterpeice": "masterpiece",
            "hight quality": "high quality",
            "beatiful": "beautiful",
            "photorealstic": "photorealistic",
        }

        for typo, correction in typo_fixes.items():
            if typo in content.lower():
                # Case-insensitive replacement
                content = re.sub(re.escape(typo), correction, content, flags=re.IGNORECASE)
                fixes_applied.append(f"Fixed typo: {typo} → {correction}")

        # Apply fixes if any were made
        if content != original_content:
            self.prompts_text.delete("1.0", tk.END)
            self.prompts_text.insert("1.0", content)
            self._on_content_changed()

            # Show results
            messagebox.showinfo(
                "Auto-Fix Complete",
                f"Applied {len(fixes_applied)} fixes:\n\n"
                + "\n".join(f"• {fix}" for fix in fixes_applied),
            )

            # Re-validate
            self._validate_pack_silent()
        else:
            messagebox.showinfo("Auto-Fix", "No fixable issues found.")

    def _save_global_negative(self):
        """Save the global negative prompt"""
        try:
            content = self.global_neg_text.get("1.0", tk.END).strip()
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read global negative: {exc}")
            return

        persisted = True
        if self.config_manager and hasattr(self.config_manager, "save_global_negative_prompt"):
            persisted = self.config_manager.save_global_negative_prompt(content)

        if not persisted:
            messagebox.showerror("Error", "Failed to save global negative prompt to disk.")
            return

        self.global_neg_content = content
        if hasattr(self, "_status_var"):
            self._status_var.set("Global negative prompt updated")
        messagebox.showinfo("Success", "Global negative prompt has been updated.")

    def _reset_global_negative(self):
        """Reset global negative to default"""
        default_neg = DEFAULT_GLOBAL_NEGATIVE_PROMPT
        persisted = True
        if self.config_manager and hasattr(self.config_manager, "save_global_negative_prompt"):
            persisted = self.config_manager.save_global_negative_prompt(default_neg)

        if not persisted:
            messagebox.showerror("Error", "Failed to restore default global negative prompt.")
            return

        self.global_neg_content = default_neg
        self._refresh_global_negative_display()
        if hasattr(self, "_status_var"):
            self._status_var.set("Global negative reset to default")

    def _check_unsaved_changes(self):
        """Check for unsaved changes and prompt user"""
        if self.is_modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes", "You have unsaved changes. Save them before continuing?"
            )
            if result is True:  # Yes, save
                self._save_pack()
                return not self.is_modified  # Return True if save succeeded
            elif result is False:  # No, don't save
                return True
            else:  # Cancel
                return False
        return True

    def _on_close(self):
        """Handle window close event"""
        if self._check_unsaved_changes():
            self.window.destroy()
            self.window = None

```

## `src/gui/api_status_panel.py`

```
"""
APIStatusPanel - UI component for displaying API connection status.

This panel shows the current API connection status with colored indicators.
"""

import logging
import tkinter as tk
from tkinter import ttk

logger = logging.getLogger(__name__)


class APIStatusPanel(ttk.Frame):
    """
    A UI panel for API connection status display.

    This panel handles:
    - Displaying connection status text
    - Color-coded status indicators (green=connected, yellow=connecting, red=error)
    - Simple set_status(text, color) API
    """

    def __init__(self, parent: tk.Widget, coordinator: object | None = None, **kwargs):
        """
        Initialize the APIStatusPanel.

        Args:
            parent: Parent widget
            coordinator: Coordinator object (for mediator pattern)
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.coordinator = coordinator

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the panel UI."""
        # Status bar with dark theme
        status_frame = ttk.Frame(self, style="Dark.TFrame", relief=tk.SUNKEN)
        status_frame.pack(fill=tk.X, expand=True)

        # Status indicator
        self.status_indicator = ttk.Label(
            status_frame,
            text="●",
            style="Dark.TLabel",
            foreground="#888888",  # Default gray
            font=("Segoe UI", 12, "bold"),
        )
        self.status_indicator.pack(side=tk.LEFT, padx=(5, 2))

        # Status text
        self.status_label = ttk.Label(
            status_frame, text="Not connected", style="Dark.TLabel", font=("Segoe UI", 9)
        )
        self.status_label.pack(side=tk.LEFT, padx=(2, 5))

    def set_status(self, text: str, color: str = "gray") -> None:
        """
        Set the status display.

        Args:
            text: Status text to display
            color: Color for the indicator (green, yellow, red, gray)
        """
        # Map color names to hex codes
        color_map = {
            "green": "#4CAF50",
            "yellow": "#FF9800",
            "orange": "#FF9800",
            "red": "#f44336",
            "gray": "#888888",
            "grey": "#888888",
        }

        # Get hex color
        hex_color = color_map.get(color.lower(), color)

        # Update UI (thread-safe via after)
        def update():
            self.status_indicator.config(foreground=hex_color)
            self.status_label.config(text=text)

        # Schedule update on main thread
        try:
            self.after(0, update)
        except:
            # Fallback if not in main thread
            update()

        logger.debug(f"API status set to: {text} ({color})")

```

## `src/gui/center_panel.py`

```
import tkinter as tk
from tkinter import ttk


class CenterPanel(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        # Placeholder for CenterPanel content
        self.label = ttk.Label(self, text="Center Panel")
        self.label.pack(fill=tk.BOTH, expand=True)

```

## `src/gui/config_panel.py`

```
"""
ConfigPanel - UI component for configuration management with tabs.

This panel encapsulates all configuration UI and provides a clean API for
getting/setting configuration and validation.
"""

import logging
import tkinter as tk
from collections.abc import Iterable
from tkinter import ttk
from typing import Any

from .adetailer_config_panel import ADetailerConfigPanel
from .theme import ASWF_BLACK, ASWF_GOLD, ASWF_LIGHT_GREY, ASWF_OK_GREEN

logger = logging.getLogger(__name__)

# Constants for dimension bounds
MAX_DIMENSION = 2260
MIN_DIMENSION = 64


class ConfigPanel(ttk.Frame):
    """
    A UI panel for configuration management.

    This panel handles:
    - Configuration tabs (txt2img, img2img, upscale, api)
    - Configuration validation
    - Dimension bounds checking (≤2260)
    - Face restoration toggle with show/hide controls
    - Hires fix steps setting

    It exposes get_config(), set_config(), and validate() methods.
    """

    def __init__(self, parent: tk.Widget, coordinator: object | None = None, **kwargs):
        """
        Initialize the ConfigPanel.

        Args:
            parent: Parent widget
            coordinator: Coordinator object (for mediator pattern)
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.coordinator = coordinator

        # Initialize variable dictionaries
        self.txt2img_vars: dict[str, tk.Variable] = {}
        self.img2img_vars: dict[str, tk.Variable] = {}
        self.upscale_vars: dict[str, tk.Variable] = {}
        self.api_vars: dict[str, tk.Variable] = {}

        # Widget dictionaries for enabling/disabling and list updates
        self.txt2img_widgets: dict[str, tk.Widget] = {}
        self.img2img_widgets: dict[str, tk.Widget] = {}
        self.upscale_widgets: dict[str, tk.Widget] = {}
        self.adetailer_panel: ADetailerConfigPanel | None = None

        # Face restoration widgets (for show/hide)
        self.face_restoration_widgets: list[tk.Widget] = []
        self._scheduler_options = [
            "Normal",
            "Karras",
            "Exponential",
            "Polyexponential",
            "SGM Uniform",
            "Simple",
            "DDIM Uniform",
            "Beta",
            "Linear",
            "Cosine",
        ]

        # Build UI
        self._build_ui()

    def _normalize_scheduler_value(self, value: str | None) -> str:
        mapping = {
            "normal": "Normal",
            "karras": "Karras",
            "exponential": "Exponential",
            "polyexponential": "Polyexponential",
            "sgm_uniform": "SGM Uniform",
            "sgm uniform": "SGM Uniform",
            "simple": "Simple",
            "ddim_uniform": "DDIM Uniform",
            "ddim uniform": "DDIM Uniform",
            "beta": "Beta",
            "linear": "Linear",
            "cosine": "Cosine",
        }
        if not value:
            return "Normal"
        normalized = str(value).strip()
        return mapping.get(normalized.lower(), normalized)

    def _build_ui(self):
        """Build the panel UI."""
        # Configuration status section
        status_frame = ttk.LabelFrame(
            self, text="Configuration Status", style="Dark.TLabelframe", padding=5
        )
        status_frame.pack(fill=tk.X, padx=10, pady=(5, 10))

        self.config_status_label = ttk.Label(
            status_frame,
            text="Ready",
            style="Dark.TLabel",
            foreground=ASWF_LIGHT_GREY,
            font=("Segoe UI", 9),
            wraplength=600,
        )
        self.config_status_label.pack(fill=tk.X)

        # Create notebook for stage-specific configurations
        self.notebook = ttk.Notebook(self, style="Dark.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Create individual tabs
        self._build_txt2img_tab()
        self._build_img2img_tab()
        self._build_adetailer_tab()
        self._build_upscale_tab()
        self._build_api_tab()

        # Add buttons at bottom
        self._build_action_buttons()
        # Create inline save/apply indicator next to Save button
        try:
            self._ensure_save_indicator()
        except Exception:
            pass

        # Track changes and mark as Apply when any field changes
        try:
            self._attach_change_traces()
        except Exception:
            pass

    def _build_txt2img_tab(self):
        """Build txt2img configuration tab."""
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text="🎨 txt2img")

        toggle_var = getattr(self.coordinator, "txt2img_enabled", None)
        self._add_stage_toggle(tab, "Enable txt2img stage", toggle_var)
        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(0, 5))

        container = ttk.Frame(tab, style="Dark.TFrame")
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg=ASWF_BLACK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Initialize variables with defaults
        self.txt2img_vars["steps"] = tk.IntVar(value=20)
        self.txt2img_vars["cfg_scale"] = tk.DoubleVar(value=7.0)
        self.txt2img_vars["width"] = tk.IntVar(value=512)
        self.txt2img_vars["height"] = tk.IntVar(value=512)
        self.txt2img_vars["sampler_name"] = tk.StringVar(value="Euler a")
        self.txt2img_vars["scheduler"] = tk.StringVar(value="Normal")
        self.txt2img_vars["seed"] = tk.IntVar(value=-1)
        self.txt2img_vars["clip_skip"] = tk.IntVar(value=2)
        self.txt2img_vars["model"] = tk.StringVar(value="")
        self.txt2img_vars["vae"] = tk.StringVar(value="")
        self.txt2img_vars["negative_prompt"] = tk.StringVar(value="")
        self.txt2img_vars["hypernetwork"] = tk.StringVar(value=self._get_hypernetwork_options()[0])
        self.txt2img_vars["hypernetwork_strength"] = tk.DoubleVar(value=1.0)

        # Hires fix
        self.txt2img_vars["enable_hr"] = tk.BooleanVar(value=False)
        self.txt2img_vars["hr_scale"] = tk.DoubleVar(value=2.0)
        self.txt2img_vars["hr_upscaler"] = tk.StringVar(value="Latent")
        self.txt2img_vars["hr_sampler_name"] = tk.StringVar(value="")
        self.txt2img_vars["denoising_strength"] = tk.DoubleVar(value=0.7)
        self.txt2img_vars["hires_steps"] = tk.IntVar(value=0)

        # Face restoration
        self.txt2img_vars["face_restoration_enabled"] = tk.BooleanVar(value=False)
        self.txt2img_vars["face_restoration_model"] = tk.StringVar(value="GFPGAN")
        self.txt2img_vars["face_restoration_weight"] = tk.DoubleVar(value=0.5)

        # Refiner (SDXL)
        self.txt2img_vars["refiner_checkpoint"] = tk.StringVar(value="None")
        self.txt2img_vars["refiner_switch_at"] = tk.DoubleVar(value=0.8)
        self.txt2img_vars["refiner_switch_steps"] = tk.IntVar(value=0)

        basic_frame = ttk.LabelFrame(
            scrollable_frame, text="Basic Settings", padding=10, style="Dark.TLabelframe"
        )
        basic_frame.pack(fill=tk.X, padx=10, pady=5)

        row = 0
        ttk.Label(basic_frame, text="Steps:").grid(row=row, column=0, sticky=tk.W, pady=2)
        steps_spin = ttk.Spinbox(
            basic_frame, from_=1, to=150, textvariable=self.txt2img_vars["steps"], width=15
        )
        steps_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["steps"] = steps_spin
        row += 1

        ttk.Label(basic_frame, text="CFG Scale:").grid(row=row, column=0, sticky=tk.W, pady=2)
        cfg_spin = ttk.Spinbox(
            basic_frame,
            from_=1.0,
            to=30.0,
            increment=0.5,
            textvariable=self.txt2img_vars["cfg_scale"],
            width=15,
        )
        cfg_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["cfg_scale"] = cfg_spin

        # Dimensions section with bounds warning
        dim_frame = ttk.LabelFrame(
            scrollable_frame, text="Image Dimensions", padding=10, style="Dark.TLabelframe"
        )
        dim_frame.pack(fill=tk.X, padx=10, pady=5)

        row = 0
        ttk.Label(dim_frame, text="Width:").grid(row=row, column=0, sticky=tk.W, pady=2)
        width_spin = ttk.Spinbox(
            dim_frame,
            from_=MIN_DIMENSION,
            to=MAX_DIMENSION,
            increment=64,
            textvariable=self.txt2img_vars["width"],
            width=15,
        )
        width_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["width"] = width_spin
        row += 1

        ttk.Label(dim_frame, text="Height:").grid(row=row, column=0, sticky=tk.W, pady=2)
        height_spin = ttk.Spinbox(
            dim_frame,
            from_=MIN_DIMENSION,
            to=MAX_DIMENSION,
            increment=64,
            textvariable=self.txt2img_vars["height"],
            width=15,
        )
        height_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["height"] = height_spin
        row += 1

        # Dimension warning label
        self.dim_warning_label = ttk.Label(
            dim_frame,
            text=f"⚠️ Maximum recommended: {MAX_DIMENSION}x{MAX_DIMENSION}",
            foreground=ASWF_GOLD,
            font=("Segoe UI", 8),
        )
        self.dim_warning_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        row += 1

        # Sampler section
        sampler_frame = ttk.LabelFrame(
            scrollable_frame, text="Sampler Settings", padding=10, style="Dark.TLabelframe"
        )
        sampler_frame.pack(fill=tk.X, padx=10, pady=5)

        row = 0
        ttk.Label(sampler_frame, text="Sampler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        sampler_combo = ttk.Combobox(
            sampler_frame,
            textvariable=self.txt2img_vars["sampler_name"],
            values=["Euler a", "Euler", "DPM++ 2M", "DPM++ SDE", "LMS", "Heun"],
            state="readonly",
            width=18,  # widened for readability
        )
        sampler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["sampler_name"] = sampler_combo
        row += 1

        ttk.Label(sampler_frame, text="Scheduler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        scheduler_combo = ttk.Combobox(
            sampler_frame,
            textvariable=self.txt2img_vars["scheduler"],
            values=self._scheduler_options,
            state="readonly",
            width=18,  # widened for readability
        )
        scheduler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["scheduler"] = scheduler_combo
        row += 1

        ttk.Label(sampler_frame, text="Model:").grid(row=row, column=0, sticky=tk.W, pady=2)
        model_combo = ttk.Combobox(
            sampler_frame,
            textvariable=self.txt2img_vars["model"],
            values=[],
            state="readonly",
            width=40,  # widened for long model names
        )
        model_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["model"] = model_combo
        row += 1

        ttk.Label(sampler_frame, text="VAE:").grid(row=row, column=0, sticky=tk.W, pady=2)
        vae_combo = ttk.Combobox(
            sampler_frame,
            textvariable=self.txt2img_vars["vae"],
            values=[],
            state="readonly",
            width=40,  # widened for long VAE names
        )
        vae_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["vae"] = vae_combo
        row += 1

        self._build_hypernetwork_section(scrollable_frame, self.txt2img_vars, "txt2img")

        # Hires fix section
        hires_frame = ttk.LabelFrame(
            scrollable_frame, text="Hires Fix", padding=10, style="Dark.TLabelframe"
        )
        hires_frame.pack(fill=tk.X, padx=10, pady=5)

        row = 0
        enable_hr_check = ttk.Checkbutton(
            hires_frame, text="Enable Hires Fix", variable=self.txt2img_vars["enable_hr"]
        )
        enable_hr_check.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        row += 1

        ttk.Label(hires_frame, text="Hires Steps:").grid(row=row, column=0, sticky=tk.W, pady=2)
        hires_steps_spin = ttk.Spinbox(
            hires_frame, from_=0, to=150, textvariable=self.txt2img_vars["hires_steps"], width=15
        )
        hires_steps_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["hires_steps"] = hires_steps_spin
        row += 1

        ttk.Label(hires_frame, text="Upscale by:").grid(row=row, column=0, sticky=tk.W, pady=2)
        hr_scale_spin = ttk.Spinbox(
            hires_frame,
            from_=1.0,
            to=4.0,
            increment=0.1,
            textvariable=self.txt2img_vars["hr_scale"],
            width=15,
        )
        hr_scale_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        ttk.Label(hires_frame, text="Upscaler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        hr_upscaler_combo = ttk.Combobox(
            hires_frame,
            textvariable=self.txt2img_vars["hr_upscaler"],
            values=[
                "Latent",
                "Latent (antialiased)",
                "Latent (bicubic)",
                "Latent (bicubic antialiased)",
                "Latent (nearest)",
                "Latent (nearest-exact)",
                "None",
                "Lanczos",
                "Nearest",
                "ESRGAN_4x",
                "LDSR",
                "R-ESRGAN 4x+",
                "R-ESRGAN 4x+ Anime6B",
                "ScuNET GAN",
                "ScuNET PSNR",
                "SwinIR 4x",
            ],
            state="readonly",
            width=25,
        )
        hr_upscaler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["hr_upscaler"] = hr_upscaler_combo
        row += 1

        ttk.Label(hires_frame, text="Hires Sampler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        hr_sampler_combo = ttk.Combobox(
            hires_frame,
            textvariable=self.txt2img_vars["hr_sampler_name"],
            values=["", "Euler a", "Euler", "DPM++ 2M", "DPM++ SDE", "LMS", "Heun"],
            state="readonly",
            width=25,
        )
        hr_sampler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["hr_sampler_name"] = hr_sampler_combo
        row += 1

        ttk.Label(hires_frame, text="Denoising:").grid(row=row, column=0, sticky=tk.W, pady=2)
        denoise_spin = ttk.Spinbox(
            hires_frame,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.txt2img_vars["denoising_strength"],
            width=15,
        )
        denoise_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        # Face Restoration section (NEW)
        face_frame = ttk.LabelFrame(
            scrollable_frame, text="Face Restoration", padding=10, style="Dark.TLabelframe"
        )
        face_frame.pack(fill=tk.X, padx=10, pady=5)

        row = 0
        enable_face_check = ttk.Checkbutton(
            face_frame,
            text="Enable Face Restoration",
            variable=self.txt2img_vars["face_restoration_enabled"],
            command=self._toggle_face_restoration,
        )
        enable_face_check.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        row += 1

        # Face restoration controls (initially hidden)
        face_model_label = ttk.Label(face_frame, text="Model:")
        face_model_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        face_model_combo = ttk.Combobox(
            face_frame,
            textvariable=self.txt2img_vars["face_restoration_model"],
            values=["GFPGAN", "CodeFormer"],
            state="readonly",
            width=13,
        )
        face_model_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.face_restoration_widgets.extend([face_model_label, face_model_combo])
        face_model_label.grid_remove()
        face_model_combo.grid_remove()  # Hide initially
        row += 1

        face_weight_label = ttk.Label(face_frame, text="Weight:")
        face_weight_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        face_weight_spin = ttk.Spinbox(
            face_frame,
            from_=0.0,
            to=1.0,
            increment=0.1,
            textvariable=self.txt2img_vars["face_restoration_weight"],
            width=15,
        )
        face_weight_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.face_restoration_widgets.extend([face_weight_label, face_weight_spin])
        face_weight_label.grid_remove()
        face_weight_spin.grid_remove()  # Hide initially
        row += 1

        # Refiner section (SDXL)
        refiner_frame = ttk.LabelFrame(
            scrollable_frame, text="🎨 Refiner (SDXL)", padding=10, style="Dark.TLabelframe"
        )
        refiner_frame.pack(fill=tk.X, padx=10, pady=5)

        row = 0
        ttk.Label(refiner_frame, text="Refiner Model:").grid(row=row, column=0, sticky=tk.W, pady=2)
        refiner_combo = ttk.Combobox(
            refiner_frame,
            textvariable=self.txt2img_vars["refiner_checkpoint"],
            values=["None"],
            state="readonly",
            width=25,
        )
        refiner_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["refiner_checkpoint"] = refiner_combo
        row += 1

        ttk.Label(refiner_frame, text="Switch ratio:").grid(row=row, column=0, sticky=tk.W, pady=2)
        refiner_switch_spin = ttk.Spinbox(
            refiner_frame,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.txt2img_vars["refiner_switch_at"],
            width=10,
        )
        refiner_switch_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["refiner_switch_at"] = refiner_switch_spin
        row += 1

        ttk.Label(refiner_frame, text="Switch step (abs):").grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        refiner_steps_spin = ttk.Spinbox(
            refiner_frame,
            from_=0,
            to=999,
            increment=1,
            textvariable=self.txt2img_vars["refiner_switch_steps"],
            width=10,
        )
        refiner_steps_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.txt2img_widgets["refiner_switch_steps"] = refiner_steps_spin
        row += 1

        # Live computed mapping label
        self.refiner_mapping_label = ttk.Label(
            refiner_frame, text="", font=("Segoe UI", 8), foreground=ASWF_LIGHT_GREY
        )
        self.refiner_mapping_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 2))
        row += 1

        # Helper text for refiner
        refiner_help = ttk.Label(
            refiner_frame,
            text="💡 Set either ratio or absolute step (ratio ignored if step > 0)",
            font=("Segoe UI", 8),
            foreground=ASWF_LIGHT_GREY,
        )
        refiner_help.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)

        # Seed and advanced
        advanced_frame = ttk.LabelFrame(
            scrollable_frame, text="Advanced", padding=10, style="Dark.TLabelframe"
        )
        advanced_frame.pack(fill=tk.X, padx=10, pady=5)

        row = 0
        ttk.Label(advanced_frame, text="Seed:").grid(row=row, column=0, sticky=tk.W, pady=2)
        seed_entry = ttk.Entry(advanced_frame, textvariable=self.txt2img_vars["seed"], width=15)
        seed_entry.grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        ttk.Label(advanced_frame, text="CLIP Skip:").grid(row=row, column=0, sticky=tk.W, pady=2)
        clip_spin = ttk.Spinbox(
            advanced_frame, from_=1, to=12, textvariable=self.txt2img_vars["clip_skip"], width=15
        )
        clip_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

    def _toggle_face_restoration(self):
        """Show/hide face restoration controls based on checkbox."""
        enabled = self.txt2img_vars["face_restoration_enabled"].get()

        for widget in self.face_restoration_widgets:
            if enabled:
                widget.grid()
            else:
                widget.grid_remove()

    def _build_img2img_tab(self):
        """Build img2img configuration tab."""
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text="🧹 img2img")

        toggle_var = getattr(self.coordinator, "img2img_enabled", None)
        self._add_stage_toggle(tab, "Enable img2img stage", toggle_var)
        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(0, 5))

        container = ttk.Frame(tab, style="Dark.TFrame")
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg=ASWF_BLACK)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Initialize variables
        self.img2img_vars["steps"] = tk.IntVar(value=15)
        self.img2img_vars["denoising_strength"] = tk.DoubleVar(value=0.3)
        self.img2img_vars["cfg_scale"] = tk.DoubleVar(value=7.0)
        self.img2img_vars["sampler_name"] = tk.StringVar(value="Euler a")
        self.img2img_vars["scheduler"] = tk.StringVar(value="Normal")
        self.img2img_vars["seed"] = tk.IntVar(value=-1)
        self.img2img_vars["clip_skip"] = tk.IntVar(value=2)
        self.img2img_vars["model"] = tk.StringVar(value="")
        self.img2img_vars["vae"] = tk.StringVar(value="")
        self.img2img_vars["hypernetwork"] = tk.StringVar(value=self._get_hypernetwork_options()[0])
        self.img2img_vars["hypernetwork_strength"] = tk.DoubleVar(value=1.0)
        self.img2img_vars["prompt_adjust"] = tk.StringVar(value="")
        self.img2img_vars["negative_adjust"] = tk.StringVar(value="")

        # Basic settings
        basic_frame = ttk.LabelFrame(
            scrollable_frame, text="img2img Settings", padding=10, style="Dark.TLabelframe"
        )
        basic_frame.pack(fill=tk.X, padx=10, pady=10)

        row = 0
        ttk.Label(basic_frame, text="Steps:").grid(row=row, column=0, sticky=tk.W, pady=2)
        steps_spin = ttk.Spinbox(
            basic_frame, from_=1, to=150, textvariable=self.img2img_vars["steps"], width=15
        )
        steps_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["steps"] = steps_spin
        row += 1

        ttk.Label(basic_frame, text="Denoising:").grid(row=row, column=0, sticky=tk.W, pady=2)
        denoise_spin = ttk.Spinbox(
            basic_frame,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.img2img_vars["denoising_strength"],
            width=15,
        )
        denoise_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["denoising_strength"] = denoise_spin
        row += 1

        ttk.Label(basic_frame, text="CFG Scale:").grid(row=row, column=0, sticky=tk.W, pady=2)
        cfg_spin = ttk.Spinbox(
            basic_frame,
            from_=1.0,
            to=30.0,
            increment=0.5,
            textvariable=self.img2img_vars["cfg_scale"],
            width=15,
        )
        cfg_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["cfg_scale"] = cfg_spin
        row += 1

        ttk.Label(basic_frame, text="Sampler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        img_sampler_combo = ttk.Combobox(
            basic_frame,
            textvariable=self.img2img_vars["sampler_name"],
            values=["Euler a", "Euler", "DPM++ 2M", "DPM++ SDE", "LMS", "Heun"],
            state="readonly",
            width=18,  # widened for readability
        )
        img_sampler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["sampler_name"] = img_sampler_combo
        row += 1

        ttk.Label(basic_frame, text="Scheduler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        img_scheduler_combo = ttk.Combobox(
            basic_frame,
            textvariable=self.img2img_vars["scheduler"],
            values=self._scheduler_options,
            state="readonly",
            width=18,  # widened for readability
        )
        img_scheduler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["scheduler"] = img_scheduler_combo
        row += 1

        ttk.Label(basic_frame, text="Model:").grid(row=row, column=0, sticky=tk.W, pady=2)
        img_model_combo = ttk.Combobox(
            basic_frame,
            textvariable=self.img2img_vars["model"],
            values=[],
            state="readonly",
            width=40,  # widened for long model names
        )
        img_model_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["model"] = img_model_combo
        row += 1

        ttk.Label(basic_frame, text="VAE:").grid(row=row, column=0, sticky=tk.W, pady=2)
        img_vae_combo = ttk.Combobox(
            basic_frame,
            textvariable=self.img2img_vars["vae"],
            values=[],
            state="readonly",
            width=40,  # widened for long VAE names
        )
        img_vae_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["vae"] = img_vae_combo
        row += 1

        self._build_hypernetwork_section(scrollable_frame, self.img2img_vars, "img2img")

        # Prompt adjustments (appended to positive prompt during img2img)
        ttk.Label(basic_frame, text="Prompt Adjust:").grid(row=row, column=0, sticky=tk.W, pady=2)
        img_prompt_adjust = ttk.Entry(
            basic_frame,
            textvariable=self.img2img_vars["prompt_adjust"],
            width=60,
        )
        img_prompt_adjust.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["prompt_adjust"] = img_prompt_adjust
        row += 1

        # Negative adjustments
        ttk.Label(basic_frame, text="Negative Adjust:").grid(row=row, column=0, sticky=tk.W, pady=2)
        img_neg_adjust = ttk.Entry(
            basic_frame,
            textvariable=self.img2img_vars["negative_adjust"],
            width=60,
        )
        img_neg_adjust.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.img2img_widgets["negative_adjust"] = img_neg_adjust
        row += 1

    def _build_adetailer_tab(self):
        """Build ADetailer configuration tab inside the pipeline notebook."""
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text="🖌️ ADetailer")

        toggle_var = getattr(self.coordinator, "adetailer_enabled", None)
        self._add_stage_toggle(tab, "Enable ADetailer stage", toggle_var)

        container = ttk.Frame(tab, style="Dark.TFrame")
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.adetailer_panel = ADetailerConfigPanel(container)
        self.adetailer_panel.frame.configure(style="Dark.TFrame")
        self.adetailer_panel.frame.pack(fill=tk.BOTH, expand=True)

    def _build_upscale_tab(self):
        """Build upscale configuration tab."""
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text="📈 Upscale")

        toggle_var = getattr(self.coordinator, "upscale_enabled", None)
        self._add_stage_toggle(tab, "Enable upscale stage", toggle_var)
        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(0, 5))

        container = ttk.Frame(tab, style="Dark.TFrame")
        container.pack(fill=tk.BOTH, expand=True)

        # Initialize variables
        self.upscale_vars["upscaler"] = tk.StringVar(value="R-ESRGAN 4x+")
        self.upscale_vars["upscaling_resize"] = tk.DoubleVar(value=2.0)
        self.upscale_vars["upscale_mode"] = tk.StringVar(value="single")
        self.upscale_vars["steps"] = tk.IntVar(value=20)  # Used when Upscale runs via img2img
        self.upscale_vars["sampler_name"] = tk.StringVar(value="Euler a")
        self.upscale_vars["scheduler"] = tk.StringVar(value="Normal")
        self.upscale_vars["denoising_strength"] = tk.DoubleVar(value=0.2)
        self.upscale_vars["gfpgan_visibility"] = tk.DoubleVar(value=0.0)
        self.upscale_vars["codeformer_visibility"] = tk.DoubleVar(value=0.0)
        self.upscale_vars["codeformer_weight"] = tk.DoubleVar(value=0.5)

        # Settings
        settings_frame = ttk.LabelFrame(
            container, text="Upscale Settings", padding=10, style="Dark.TLabelframe"
        )
        settings_frame.pack(fill=tk.X, padx=10, pady=10)

        row = 0
        ttk.Label(settings_frame, text="Method:").grid(row=row, column=0, sticky=tk.W, pady=2)
        method_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.upscale_vars["upscale_mode"],
            values=["single", "img2img"],
            state="readonly",
            width=13,
        )
        method_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        method_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_upscale_mode_state())
        self.upscale_widgets["upscale_mode"] = method_combo
        row += 1
        ttk.Label(settings_frame, text="Upscaler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        upscaler_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.upscale_vars["upscaler"],
            values=["R-ESRGAN 4x+", "ESRGAN_4x", "Latent", "None"],
            state="readonly",
            width=30,
        )
        upscaler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["upscaler"] = upscaler_combo
        row += 1

        ttk.Label(settings_frame, text="Resize:").grid(row=row, column=0, sticky=tk.W, pady=2)
        resize_spin = ttk.Spinbox(
            settings_frame,
            from_=1.0,
            to=4.0,
            increment=0.1,
            textvariable=self.upscale_vars["upscaling_resize"],
            width=15,
        )
        resize_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["upscaling_resize"] = resize_spin
        row += 1

        ttk.Label(settings_frame, text="Steps (img2img):").grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        upscale_steps = ttk.Spinbox(
            settings_frame,
            from_=1,
            to=150,
            textvariable=self.upscale_vars["steps"],
            width=15,
        )
        upscale_steps.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["steps"] = upscale_steps
        row += 1

        ttk.Label(settings_frame, text="Denoise:").grid(row=row, column=0, sticky=tk.W, pady=2)
        upscale_denoise = ttk.Spinbox(
            settings_frame,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.upscale_vars["denoising_strength"],
            width=15,
        )
        upscale_denoise.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["denoising_strength"] = upscale_denoise
        row += 1

        # Optional sampler/scheduler (used in img2img upscale mode)
        ttk.Label(settings_frame, text="Sampler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        up_sampler_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.upscale_vars["sampler_name"],
            values=["Euler a", "Euler", "DPM++ 2M", "DPM++ SDE", "LMS", "Heun"],
            state="readonly",
            width=15,
        )
        up_sampler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["sampler_name"] = up_sampler_combo
        row += 1

        ttk.Label(settings_frame, text="Scheduler:").grid(row=row, column=0, sticky=tk.W, pady=2)
        up_scheduler_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.upscale_vars["scheduler"],
            values=self._scheduler_options,
            state="readonly",
            width=15,
        )
        up_scheduler_combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["scheduler"] = up_scheduler_combo
        row += 1

        ttk.Label(settings_frame, text="GFPGAN:").grid(row=row, column=0, sticky=tk.W, pady=2)
        gfpgan_spin = ttk.Spinbox(
            settings_frame,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.upscale_vars["gfpgan_visibility"],
            width=15,
        )
        gfpgan_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["gfpgan_visibility"] = gfpgan_spin
        row += 1

        ttk.Label(settings_frame, text="CodeFormer Vis:").grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        codeformer_vis = ttk.Spinbox(
            settings_frame,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.upscale_vars["codeformer_visibility"],
            width=15,
        )
        codeformer_vis.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["codeformer_visibility"] = codeformer_vis
        row += 1

        ttk.Label(settings_frame, text="CodeFormer Weight:").grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        codeformer_weight = ttk.Spinbox(
            settings_frame,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.upscale_vars["codeformer_weight"],
            width=15,
        )
        codeformer_weight.grid(row=row, column=1, sticky=tk.W, pady=2)
        self.upscale_widgets["codeformer_weight"] = codeformer_weight
        row += 1

        # Initial enable/disable for img2img-specific controls
        self._apply_upscale_mode_state()

    def _apply_upscale_mode_state(self) -> None:
        """Enable/disable img2img-specific controls based on selected method."""
        try:
            mode = str(self.upscale_vars.get("upscale_mode").get()).lower()
        except Exception:
            mode = "single"
        use_img2img = mode == "img2img"
        for key in ("steps", "denoising_strength", "sampler_name", "scheduler"):
            widget = self.upscale_widgets.get(key)
            if widget is None:
                continue
            try:
                widget.configure(state=("normal" if use_img2img else "disabled"))
            except Exception:
                pass

    def _build_api_tab(self):
        """Build API configuration tab."""
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text="🔌 API")

        # Initialize variables
        self.api_vars["base_url"] = tk.StringVar(value="http://127.0.0.1:7860")
        self.api_vars["timeout"] = tk.IntVar(value=30)

        # Settings
        settings_frame = ttk.LabelFrame(
            tab, text="API Settings", padding=10, style="Dark.TLabelframe"
        )
        settings_frame.pack(fill=tk.X, padx=10, pady=10)

        row = 0
        ttk.Label(settings_frame, text="API URL:").grid(row=row, column=0, sticky=tk.W, pady=2)
        api_entry = ttk.Entry(settings_frame, textvariable=self.api_vars["base_url"], width=30)
        api_entry.grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        ttk.Label(settings_frame, text="Timeout (s):").grid(row=row, column=0, sticky=tk.W, pady=2)
        timeout_spin = ttk.Spinbox(
            settings_frame, from_=10, to=300, textvariable=self.api_vars["timeout"], width=15
        )
        timeout_spin.grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

    def _build_action_buttons(self):
        """Build action buttons at bottom of panel."""
        button_frame = ttk.Frame(self, style="Dark.TFrame")
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(5, 10))
        # Keep a reference for inline indicators
        self._button_frame = button_frame
        # Keep a reference for later indicator placement
        self._button_frame = button_frame

        ttk.Button(
            button_frame,
            text="💾 Save All Changes",
            command=self._on_save_all,
            style="Dark.TButton",
        ).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(
            button_frame, text="↺ Reset All", command=self._on_reset_all, style="Dark.TButton"
        ).pack(side=tk.LEFT, padx=(0, 5))

    def _on_save_all(self):
        """Handle save all button click."""
        # This would be wired to coordinator
        if self.coordinator and hasattr(self.coordinator, "on_config_save"):
            config = self.get_config()
            self.coordinator.on_config_save(config)
            self.show_save_indicator("Saved")

    def _on_reset_all(self):
        """Handle reset all button click."""
        # Reset to defaults
        default_config = self._get_default_config()
        self.set_config(default_config)

    def _get_default_config(self) -> dict[str, Any]:
        """Get default configuration."""
        return {
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "sampler_name": "Euler a",
                "scheduler": "Normal",
                "seed": -1,
                "clip_skip": 2,
                "model": "",
                "vae": "",
                "negative_prompt": "",
                "enable_hr": False,
                "hr_scale": 2.0,
                "hr_upscaler": "Latent",
                "denoising_strength": 0.7,
                "hires_steps": 0,
                "face_restoration_enabled": False,
                "face_restoration_model": "GFPGAN",
                "face_restoration_weight": 0.5,
            },
            "img2img": {
                "steps": 15,
                "denoising_strength": 0.3,
                "cfg_scale": 7.0,
                "sampler_name": "Euler a",
                "scheduler": "Normal",
                "seed": -1,
                "clip_skip": 2,
                "model": "",
                "vae": "",
                "prompt_adjust": "",
            },
            "upscale": {
                "upscaler": "R-ESRGAN 4x+",
                "upscaling_resize": 2.0,
                "upscale_mode": "single",
                "steps": 20,
                "denoising_strength": 0.2,
                "gfpgan_visibility": 0.0,
                "codeformer_visibility": 0.0,
                "codeformer_weight": 0.5,
            },
            "api": {
                "base_url": "http://127.0.0.1:7860",
                "timeout": 30,
            },
        }

    def get_config(self) -> dict[str, Any]:
        """
        Get current configuration from UI.

        Returns:
            Dictionary containing all configuration values
        """
        config = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}

        # Extract txt2img config
        for key, var in self.txt2img_vars.items():
            config["txt2img"][key] = var.get()

        # Map UI-only keys to API config keys
        try:
            # Map hires_steps spinbox to hr_second_pass_steps used by WebUI
            if "hires_steps" in config["txt2img"]:
                config["txt2img"]["hr_second_pass_steps"] = int(
                    config["txt2img"].get("hires_steps", 0)
                )
            # Pass through refiner absolute steps if provided (>0)
            if int(config["txt2img"].get("refiner_switch_steps", 0) or 0) > 0:
                # Keep as user-set; executor converts this to ratio
                config["txt2img"]["refiner_switch_steps"] = int(
                    config["txt2img"].get("refiner_switch_steps", 0)
                )
        except Exception:
            pass

        # Extract img2img config
        for key, var in self.img2img_vars.items():
            config["img2img"][key] = var.get()

        # Extract upscale config
        for key, var in self.upscale_vars.items():
            config["upscale"][key] = var.get()

        # Extract API config
        for key, var in self.api_vars.items():
            config["api"][key] = var.get()

        # Normalize scheduler casing before returning
        for section in ("txt2img", "img2img", "upscale"):
            sec = config.get(section)
            if isinstance(sec, dict) and "scheduler" in sec:
                try:
                    sec["scheduler"] = self._normalize_scheduler_value(sec.get("scheduler"))
                except Exception:
                    pass

        return config

    def _ensure_save_indicator(self) -> None:
        """Ensure the inline Save/Apply indicator is created next to buttons."""
        try:
            if hasattr(self, "_save_indicator") and self._save_indicator:
                return
            self._save_indicator_var = tk.StringVar(value="")
            self._save_indicator = ttk.Label(
                self._button_frame, textvariable=self._save_indicator_var, style="Dark.TLabel"
            )
            self._save_indicator.pack(side=tk.LEFT, padx=(8, 0))
        except Exception:
            pass

    def _add_stage_toggle(
        self, parent: tk.Widget, label: str, variable: tk.BooleanVar | None
    ) -> None:
        """Add a stage enable checkbox to the provided container."""
        if not isinstance(variable, tk.BooleanVar):
            return
        frame = ttk.Frame(parent, style="Dark.TFrame")
        frame.pack(fill=tk.X, padx=10, pady=(5, 4))
        ttk.Checkbutton(
            frame,
            text=label,
            variable=variable,
            style="Dark.TCheckbutton",
        ).pack(anchor=tk.W)

    def _build_hypernetwork_section(
        self, parent: tk.Widget, var_dict: dict[str, tk.Variable], stage_name: str
    ) -> None:
        """Shared hypernetwork dropdown + strength slider."""
        options = self._get_hypernetwork_options()
        if "hypernetwork" not in var_dict:
            var_dict["hypernetwork"] = tk.StringVar(value=options[0])
        if "hypernetwork_strength" not in var_dict:
            var_dict["hypernetwork_strength"] = tk.DoubleVar(value=1.0)

        frame = ttk.LabelFrame(parent, text="Hypernetwork", padding=10, style="Dark.TLabelframe")
        frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(frame, text="Hypernetwork:").grid(row=0, column=0, sticky=tk.W, pady=2)
        combo = ttk.Combobox(
            frame,
            textvariable=var_dict["hypernetwork"],
            values=options,
            state="readonly",
            width=25,
        )
        combo.grid(row=0, column=1, sticky=tk.W, pady=2)

        widget_store = {
            "txt2img": self.txt2img_widgets,
            "img2img": self.img2img_widgets,
        }.get(stage_name)
        if widget_store is not None:
            widget_store["hypernetwork"] = combo

        ttk.Label(frame, text="Strength:").grid(row=1, column=0, sticky=tk.W, pady=2)
        value_label = ttk.Label(frame, text=f"{var_dict['hypernetwork_strength'].get():.2f}")
        value_label.grid(row=1, column=2, sticky=tk.W, padx=(6, 0))
        slider = ttk.Scale(
            frame,
            from_=0.0,
            to=2.0,
            orient=tk.HORIZONTAL,
            variable=var_dict["hypernetwork_strength"],
            length=180,
            style="Dark.Horizontal.TScale",
        )
        slider.grid(row=1, column=1, sticky=tk.W, pady=2)

        def _sync_label(*_):
            value_label.config(text=f"{var_dict['hypernetwork_strength'].get():.2f}")

        var_dict["hypernetwork_strength"].trace_add("write", lambda *_: _sync_label())

    def _get_hypernetwork_options(self) -> list[str]:
        """Fetch available hypernetworks from the coordinator/pipeline."""
        options: list[str] = []
        coordinator = getattr(self, "coordinator", None)
        if coordinator is not None:
            possible = []
            for attr in ("available_hypernetworks", "hypernetworks"):
                value = getattr(coordinator, attr, None)
                if isinstance(value, (list, tuple, set)):
                    possible.extend(value)
            if possible:
                options = sorted({str(item) for item in possible if item})
        return options or ["None"]

    def show_save_indicator(self, text: str = "Saved", duration_ms: int = 2000) -> None:
        """Show a transient indicator next to the Save button with color coding."""
        try:
            self._ensure_save_indicator()
            # Colorize: green for Saved, orange for Apply/others
            color = ASWF_OK_GREEN if (text or "").lower() == "saved" else ASWF_GOLD
            try:
                self._save_indicator.configure(foreground=color)
            except Exception:
                pass
            self._save_indicator_var.set(text)
            if duration_ms and (text or "").lower() == "saved":
                self.after(duration_ms, lambda: self._save_indicator_var.set(""))
        except Exception:
            pass

    # (Old _attach_change_traces removed; see enhanced version later in file)

    def _mark_unsaved(self, *args) -> None:
        try:
            # Show Apply (orange)
            self.show_save_indicator("Apply", duration_ms=0)
            # Auto-apply when the coordinator enables it
            auto = False
            try:
                auto = bool(self.coordinator.auto_apply_var.get())
            except Exception:
                auto = bool(getattr(self.coordinator, "auto_apply_enabled", False))
            if auto and hasattr(self.coordinator, "on_config_save"):
                self.coordinator.on_config_save(self.get_config())
                self.show_save_indicator("Saved")
        except Exception:
            pass

    def set_config(self, config: dict[str, Any]) -> None:
        """
        Set configuration in UI.

        Args:
            config: Dictionary containing configuration values
        """
        import os

        diag = os.environ.get("STABLENEW_DIAG", "").lower() in {"1", "true", "yes"}
        if diag:
            import logging

            logger = logging.getLogger(__name__)
            logger.info("[DIAG] ConfigPanel.set_config: start", extra={"flush": True})
        # Set txt2img config
        if "txt2img" in config:
            if diag:
                logger.info(
                    "[DIAG] ConfigPanel.set_config: processing txt2img", extra={"flush": True}
                )
            # Pre-map hr_second_pass_steps to hires_steps for the UI control
            txt_cfg = dict(config["txt2img"])  # shallow copy
            try:
                if "hr_second_pass_steps" in txt_cfg and "hires_steps" in self.txt2img_vars:
                    self.txt2img_vars["hires_steps"].set(
                        int(txt_cfg.get("hr_second_pass_steps") or 0)
                    )
            except Exception:
                pass
            for key, value in txt_cfg.items():
                if key in self.txt2img_vars:
                    if key == "scheduler":
                        value = self._normalize_scheduler_value(value)
                    self.txt2img_vars[key].set(value)
            # Sync mapping label after setting fields
            try:
                self._update_refiner_mapping_label()
            except Exception:
                pass
            if diag:
                logger.info("[DIAG] ConfigPanel.set_config: txt2img done", extra={"flush": True})

        # Set img2img config
        if "img2img" in config:
            if diag:
                logger.info(
                    "[DIAG] ConfigPanel.set_config: processing img2img", extra={"flush": True}
                )
            for key, value in config["img2img"].items():
                if key in self.img2img_vars:
                    if key == "scheduler":
                        value = self._normalize_scheduler_value(value)
                    self.img2img_vars[key].set(value)
            if diag:
                logger.info("[DIAG] ConfigPanel.set_config: img2img done", extra={"flush": True})

        # Set upscale config
        if "upscale" in config:
            if diag:
                logger.info(
                    "[DIAG] ConfigPanel.set_config: processing upscale", extra={"flush": True}
                )
            for key, value in config["upscale"].items():
                if key in self.upscale_vars:
                    if key == "scheduler":
                        value = self._normalize_scheduler_value(value)
                    self.upscale_vars[key].set(value)
            if diag:
                logger.info("[DIAG] ConfigPanel.set_config: upscale done", extra={"flush": True})

        # Set API config
        if "api" in config:
            if diag:
                logger.info("[DIAG] ConfigPanel.set_config: processing api", extra={"flush": True})
            for key, value in config["api"].items():
                if key in self.api_vars:
                    self.api_vars[key].set(value)
            if diag:
                logger.info("[DIAG] ConfigPanel.set_config: api done", extra={"flush": True})

        # Update face restoration visibility
        if diag:
            logger.info(
                "[DIAG] ConfigPanel.set_config: calling _toggle_face_restoration",
                extra={"flush": True},
            )
        self._toggle_face_restoration()
        if diag:
            logger.info(
                "[DIAG] ConfigPanel.set_config: calling _update_refiner_mapping_label",
                extra={"flush": True},
            )
        try:
            self._update_refiner_mapping_label()
        except Exception:
            pass
        if diag:
            logger.info("[DIAG] ConfigPanel.set_config: end", extra={"flush": True})

    def _update_refiner_mapping_label(self):
        """Compute and display the effective switch mapping."""
        if not hasattr(self, "refiner_mapping_label"):
            return
        try:
            steps = int(self.txt2img_vars.get("steps").get())
        except Exception:
            steps = 0
        ratio = float(self.txt2img_vars.get("refiner_switch_at").get()) if steps else 0.0
        abs_step = int(self.txt2img_vars.get("refiner_switch_steps").get())
        if abs_step > 0 and steps > 0:
            # Show both representations
            computed_ratio = abs_step / float(steps)
            self.refiner_mapping_label.configure(
                text=f"🔀 Will switch at step {abs_step}/{steps} (ratio={computed_ratio:.3f})"
            )
        elif steps > 0 and 0 < ratio < 1:
            target_step = int(round(ratio * steps))
            self.refiner_mapping_label.configure(
                text=f"🔀 Ratio {ratio:.3f} => switch ≈ step {target_step}/{steps}"
            )
        else:
            self.refiner_mapping_label.configure(text="")

    def _attach_change_traces(self) -> None:
        """Attach variable traces to flag unsaved changes (extended to update refiner mapping)."""

        def attach(d: dict[str, tk.Variable]):
            for k, v in d.items():
                try:

                    def _cb(*_):
                        self._mark_unsaved()
                        if k in {"refiner_switch_at", "refiner_switch_steps", "steps"}:
                            self._update_refiner_mapping_label()

                    v.trace_add("write", _cb)
                except Exception:
                    try:
                        v.trace("w", _cb)  # type: ignore[attr-defined]
                    except Exception:
                        pass

        for var_dict in (self.txt2img_vars, self.img2img_vars, self.upscale_vars, self.api_vars):
            attach(var_dict)

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate current configuration.

        Returns:
            Tuple of (ok: bool, messages: List[str])
            ok is True if valid, False if there are errors
            messages contains warning/error messages
        """
        messages = []
        ok = True

        # Check dimension bounds
        width = self.txt2img_vars["width"].get()
        height = self.txt2img_vars["height"].get()

        if width > MAX_DIMENSION:
            ok = False
            messages.append(f"Width {width} exceeds maximum of {MAX_DIMENSION}")

        if height > MAX_DIMENSION:
            ok = False
            messages.append(f"Height {height} exceeds maximum of {MAX_DIMENSION}")

        if width < MIN_DIMENSION:
            ok = False
            messages.append(f"Width {width} below minimum of {MIN_DIMENSION}")

        if height < MIN_DIMENSION:
            ok = False
            messages.append(f"Height {height} below minimum of {MIN_DIMENSION}")

        # Check steps are positive
        if self.txt2img_vars["steps"].get() < 1:
            ok = False
            messages.append("txt2img steps must be at least 1")

        if self.img2img_vars["steps"].get() < 1:
            ok = False
            messages.append("img2img steps must be at least 1")

        return ok, messages

    def set_editable(self, editable: bool) -> None:
        """
        Enable or disable editing of config controls.

        Args:
            editable: True to enable editing, False to disable
        """
        state = "normal" if editable else "disabled"

        # Update txt2img widgets
        for widget in self.txt2img_widgets.values():
            try:
                widget.configure(state=state)
            except:
                pass  # Some widgets may not support state

        # Update img2img widgets
        for widget in self.img2img_widgets.values():
            try:
                widget.configure(state=state)
            except:
                pass

        # Update upscale widgets
        for widget in self.upscale_widgets.values():
            try:
                widget.configure(state=state)
            except:
                pass

    def set_status_message(self, message: str) -> None:
        """
        Set configuration status message.

        Args:
            message: Status message to display
        """
        if hasattr(self, "config_status_label"):
            self.config_status_label.configure(text=message)

    # ------------------------------------------------------------------
    # Option update helpers for integration with main window
    # ------------------------------------------------------------------

    def _set_combobox_values(self, widget: tk.Widget | None, values: Iterable[str]) -> None:
        if widget is None:
            return
        try:
            widget["values"] = tuple(values)
        except (AttributeError, tk.TclError) as e:
            logger.warning(
                "Failed to set combobox values on widget %s: %s",
                type(widget).__name__,
                e,
            )

    def set_model_options(self, models: Iterable[str]) -> None:
        """Update base model selections for txt2img/img2img and refiner."""
        self._set_combobox_values(self.txt2img_widgets.get("model"), models)
        self._set_combobox_values(self.img2img_widgets.get("model"), models)

        # Also populate refiner dropdown with models (prepend "None" option)
        refiner_models = ["None"]
        for m in models or []:
            if m and str(m).strip():
                refiner_models.append(str(m).strip())
        self._set_combobox_values(self.txt2img_widgets.get("refiner_checkpoint"), refiner_models)

    def set_vae_options(self, vae_models: Iterable[str]) -> None:
        """Update VAE selections for txt2img/img2img."""
        self._set_combobox_values(self.txt2img_widgets.get("vae"), vae_models)
        self._set_combobox_values(self.img2img_widgets.get("vae"), vae_models)

    def set_sampler_options(self, samplers: Iterable[str]) -> None:
        """Update sampler dropdowns across stages."""

        cleaned: list[str] = []
        for sampler in samplers or []:
            if sampler is None:
                continue
            text = str(sampler).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        if not cleaned:
            cleaned = ["Euler a"]
        cleaned.sort(key=str.lower)

        targets = [
            self.txt2img_widgets.get("sampler_name"),
            self.txt2img_widgets.get("hr_sampler_name"),
            self.img2img_widgets.get("sampler_name"),
            self.upscale_widgets.get("sampler_name"),
        ]
        for widget in targets:
            self._set_combobox_values(widget, cleaned)

        if self.adetailer_panel is not None:
            try:
                self.adetailer_panel.set_sampler_options(cleaned)
            except Exception:
                logger.exception("Failed to update ADetailer sampler options")

    def set_upscaler_options(self, upscalers: Iterable[str]) -> None:
        """Update upscaler dropdowns (hires + upscale stage)."""

        cleaned: list[str] = []
        for upscaler in upscalers or []:
            if upscaler is None:
                continue
            text = str(upscaler).strip()
            if text and text not in cleaned:
                cleaned.append(text)

        # Ensure latent/None entries remain available for hires fix
        for fallback in (
            "Latent",
            "Latent (antialiased)",
            "Latent (bicubic)",
            "Latent (bicubic antialiased)",
            "Latent (nearest)",
            "Latent (nearest-exact)",
            "None",
        ):
            if fallback not in cleaned:
                cleaned.append(fallback)

        cleaned = [c for c in cleaned if c]
        cleaned.sort(key=str.lower)

        self._set_combobox_values(self.upscale_widgets.get("upscaler"), cleaned)
        self._set_combobox_values(self.txt2img_widgets.get("hr_upscaler"), cleaned)

    def set_scheduler_options(self, schedulers: Iterable[str]) -> None:
        """Update scheduler dropdowns."""
        normalized = [self._normalize_scheduler_value(s) for s in schedulers or [] if s is not None]
        if not normalized:
            normalized = list(self._scheduler_options)
        self._set_combobox_values(self.txt2img_widgets.get("scheduler"), normalized)
        self._set_combobox_values(self.img2img_widgets.get("scheduler"), normalized)
        self._set_combobox_values(self.upscale_widgets.get("scheduler"), normalized)

    def set_hypernetwork_options(self, hypernets: Iterable[str]) -> None:
        """Update hypernetwork dropdowns for txt2img/img2img."""

        cleaned: list[str] = []
        for entry in hypernets or []:
            if entry is None:
                continue
            text = str(entry).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        if "None" not in cleaned:
            cleaned.insert(0, "None")
        self._set_combobox_values(self.txt2img_widgets.get("hypernetwork"), cleaned)
        self._set_combobox_values(self.img2img_widgets.get("hypernetwork"), cleaned)

    def refresh_dynamic_lists_from_api(self, client) -> None:
        """Update sampler/upscaler dropdowns based on the active API client."""

        if client is None:
            return

        try:
            sampler_entries = getattr(client, "samplers", []) or []
            sampler_names = [entry.get("name", "") for entry in sampler_entries if entry.get("name")]
            self.set_sampler_options(sampler_names)
        except Exception:
            logger.exception("Failed to refresh sampler options from API")

        try:
            upscaler_entries = getattr(client, "upscalers", []) or []
            upscaler_names = [entry.get("name", "") for entry in upscaler_entries if entry.get("name")]
            self.set_upscaler_options(upscaler_names)
        except Exception:
            logger.exception("Failed to refresh upscaler options from API")

```

## `src/gui/controller.py`

```
"""Pipeline controller with cancellation support."""

import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

from .state import CancellationError, CancelToken, GUIState, StateManager

logger = logging.getLogger(__name__)


class LogMessage:
    """Log message with level and timestamp."""

    def __init__(self, message: str, level: str = "INFO"):
        """Initialize log message.

        Args:
            message: Log message text
            level: Log level (INFO, WARNING, ERROR, SUCCESS)
        """
        self.message = message
        self.level = level
        self.timestamp = time.time()


class PipelineController:
    """Controls pipeline execution with cancellation support."""

    @property
    def is_terminal(self):
        return self.state_manager.current in (GUIState.IDLE, GUIState.ERROR)

    _JOIN_TIMEOUT = 5.0

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.cancel_token = CancelToken()
        self.log_queue: queue.Queue[LogMessage] = queue.Queue()

        # Worker + subprocess
        self._worker: threading.Thread | None = None
        self._pipeline = None
        self._current_subprocess: subprocess.Popen | None = None
        self._subprocess_lock = threading.Lock()

        # Cleanup & joining
        self._join_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_started = False  # per-run guard (reset at start of each pipeline run)
        self._cleanup_done = threading.Event()  # signals cleanup completed (per run)
        self._cleanup_done.set()  # no prior run on init; don't block first start

        self._stop_in_progress = False

        # Lifecycle signals
        self.lifecycle_event = threading.Event()  # terminal (IDLE/ERROR)
        self.state_change_event = threading.Event()  # pulse on change

        # Test hook
        self._sync_cleanup = False

        # Epoch
        self._epoch_lock = threading.Lock()
        self._epoch_id = 0

        # Progress callbacks
        self._progress_lock = threading.Lock()
        self._progress_callback: Callable[[float], None] | None = None
        self._eta_callback: Callable[[str], None] | None = None
        self._status_callback: Callable[[str], None] | None = None
        self._last_progress: dict[str, Any] = {
            "stage": "Idle",
            "percent": 0.0,
            "eta": "ETA: --",
        }

    def start_pipeline(
        self,
        pipeline_func: Callable[[], dict[str, Any]],
        on_complete: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        if not self.state_manager.can_run():
            logger.warning("Cannot start pipeline - not in valid state")
            return False
        if not self._cleanup_done.is_set():
            logger.warning("Cannot start pipeline - previous cleanup is still running")
            return False
        if not self.state_manager.transition_to(GUIState.RUNNING):
            return False

        # 2) New epoch
        with self._epoch_lock:
            self._epoch_id += 1
            eid = self._epoch_id
        try:
            self._log(f"[controller] Starting pipeline epoch {eid}", "DEBUG")
        except Exception:
            pass

        # 3) Reset per-run signals
        self._cleanup_started = False
        self.lifecycle_event.clear()
        self.cancel_token.reset()

        def worker():
            error_occurred = False
            try:
                self._log("Pipeline started", "INFO")
                result = pipeline_func()
                if on_complete:
                    on_complete(result)
            except CancellationError:
                self._log("Pipeline cancelled by user", "WARNING")
                self.report_progress("Cancelled", self._last_progress["percent"], "Cancelled")
                try:
                    self.lifecycle_event.set()
                except Exception:
                    logger.debug("Failed to signal lifecycle event on cancellation", exc_info=True)
            except Exception as e:
                error_occurred = True
                self._log(f"Pipeline error: {e}", "ERROR")
                self.state_manager.transition_to(GUIState.ERROR)
                self.report_progress("Error", self._last_progress["percent"], "Error")
                if on_error:
                    on_error(e)
                try:
                    self.lifecycle_event.set()
                except Exception:
                    logger.debug("Failed to signal lifecycle event on error", exc_info=True)

            def cleanup():
                self._do_cleanup(eid, error_occurred)

            if self._sync_cleanup:
                cleanup()
            else:
                threading.Thread(target=cleanup, daemon=True).start()

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()
        return True

    def stop_pipeline(self) -> bool:
        if not self.state_manager.can_stop():
            logger.warning("Cannot stop pipeline - not running")
            return False

        with self._cleanup_lock:
            if self._stop_in_progress:
                self._log(
                    "Cleanup already in progress; ignoring duplicate stop request", "DEBUG"
                )
                return False
            self._stop_in_progress = True

        self._log("Stop requested - cancelling pipeline...", "WARNING")
        if not self.state_manager.transition_to(GUIState.STOPPING):
            with self._cleanup_lock:
                self._stop_in_progress = False
            return False
        self.cancel_token.cancel()
        self._terminate_subprocess()
        self.report_progress("Cancelled", self._last_progress["percent"], "Cancelled")

        def cleanup():
            with self._epoch_lock:
                eid = self._epoch_id
            self._do_cleanup(eid, error_occurred=False)

        if self._sync_cleanup:
            logger.debug("Sync cleanup requested (tests only); running inline")
            cleanup()
        else:
            threading.Thread(target=cleanup, daemon=True).start()
        return True

    def _do_cleanup(self, eid: int, error_occurred: bool):
        # Ignore stale cleanup from a previous run
        with self._epoch_lock:
            if eid != self._epoch_id:
                return

        with self._cleanup_lock:
            if self._cleanup_started:
                return
            self._cleanup_started = True
            self._cleanup_done.clear()

        try:
            # NEVER join worker thread - violates architecture rule (GUI must not block on threads)
            with self._join_lock:
                self._worker = None

            # Terminate subprocess if still around
            self._terminate_subprocess()

            # State to terminal AFTER teardown
            if not self.state_manager.is_state(GUIState.ERROR):
                self.state_manager.transition_to(GUIState.IDLE)

            # Pulse state change
            self.state_change_event.set()
            self.state_change_event.clear()

            try:
                self._log(
                    f"[controller] Cleanup complete for epoch {eid} (error={error_occurred})",
                    "DEBUG",
                )
            except Exception:
                pass
        finally:
            with self._cleanup_lock:
                self._cleanup_started = False
                self._stop_in_progress = False
            self._cleanup_done.set()
            self.lifecycle_event.set()

        if not error_occurred and not self.cancel_token.is_cancelled():
            self.report_progress("Idle", 0.0, "Idle")

    def set_pipeline(self, pipeline) -> None:
        """Set the pipeline instance to use."""
        self._pipeline = pipeline
        if pipeline and hasattr(pipeline, "set_progress_controller"):
            try:
                pipeline.set_progress_controller(self)
            except TypeError as exc:  # Catch only known failure mode
                logger.debug("Failed to attach progress controller (TypeError): %s", exc)
            except RuntimeError as exc:
                logger.debug("Failed to attach progress controller (RuntimeError): %s", exc)

    def set_progress_callback(self, callback: Callable[[float], None] | None) -> None:
        """Register callback for progress percentage updates."""
        with self._progress_lock:
            self._progress_callback = callback

    def set_eta_callback(self, callback: Callable[[str], None] | None) -> None:
        """Register callback for ETA updates."""
        with self._progress_lock:
            self._eta_callback = callback

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        """Register callback for status/stage text updates."""
        with self._progress_lock:
            self._status_callback = callback

    def report_progress(self, stage: str, percent: float, eta: str | None) -> None:
        """Report progress to registered callbacks in a thread-safe manner."""

        eta_text = eta if eta else "ETA: --"
        try:
            # Suppress non-error updates only after entering ERROR state;
            # allow progress reports while IDLE for unit tests and initialization.
            if self.state_manager.current == GUIState.ERROR and (stage or "").lower() != "error":
                return
        except Exception:
            pass
        with self._progress_lock:
            self._last_progress = {
                "stage": stage,
                "percent": float(percent),
                "eta": eta_text,
            }

            try:
                if self._status_callback:
                    self._status_callback(stage)
            except Exception:
                logger.debug("status_callback raised; ignoring in report_progress", exc_info=True)
            try:
                if self._progress_callback:
                    self._progress_callback(float(percent))
            except Exception:
                logger.debug("progress_callback raised; ignoring in report_progress", exc_info=True)
            try:
                if self._eta_callback:
                    self._eta_callback(eta_text)
            except Exception:
                logger.debug("eta_callback raised; ignoring in report_progress", exc_info=True)

    def _terminate_subprocess(self) -> None:
        """Terminate any running subprocess (e.g., FFmpeg)."""
        with self._subprocess_lock:
            if self._current_subprocess:
                try:
                    self._log("Terminating subprocess...", "INFO")
                    self._current_subprocess.terminate()
                    self._current_subprocess.wait(timeout=3.0)
                    self._log("Subprocess terminated", "INFO")
                except Exception as e:
                    logger.warning(f"Error terminating subprocess: {e}")
                    try:
                        self._current_subprocess.kill()
                    except Exception:
                        pass
                finally:
                    self._current_subprocess = None

    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files created during pipeline execution."""
        # Disabled during test debugging due to fatal Windows exception
        pass

    def register_subprocess(self, process: subprocess.Popen) -> None:
        """Register subprocess for cancellation tracking."""
        with self._subprocess_lock:
            self._current_subprocess = process

    def unregister_subprocess(self) -> None:
        """Unregister subprocess."""
        with self._subprocess_lock:
            self._current_subprocess = None

    def _log(self, message: str, level: str = "INFO") -> None:
        """Add message to log queue."""
        self.log_queue.put(LogMessage(message, level))

    def get_log_messages(self) -> list[LogMessage]:
        """Get all pending log messages."""
        messages = []
        while not self.log_queue.empty():
            try:
                messages.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def is_running(self) -> bool:
        """Check if pipeline is currently running."""
        return self.state_manager.is_state(GUIState.RUNNING)

    def is_stopping(self) -> bool:
        """Check if pipeline is stopping."""
        return self.state_manager.is_state(GUIState.STOPPING)

```

## `src/gui/engine_settings_dialog.py`

```
"""Dialog for editing a curated subset of WebUI engine settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict

from src.api.client import SDWebUIClient


class EngineSettingsDialog(tk.Toplevel):
    """
    Minimal dialog to edit select /sdapi/v1/options settings.
    """

    def __init__(self, parent: tk.Misc, client: SDWebUIClient) -> None:
        super().__init__(parent)
        self.title("Engine Settings")
        self.client = client
        self._options: Dict[str, Any] = {}

        self._jpeg_quality_var = tk.IntVar(value=95)
        self._webp_lossless_var = tk.BooleanVar()
        self._img_max_size_mp_var = tk.DoubleVar(value=0.0)

        self._enable_pnginfo_var = tk.BooleanVar(value=True)
        self._save_txt_var = tk.BooleanVar()
        self._add_model_name_var = tk.BooleanVar(value=True)
        self._add_model_hash_var = tk.BooleanVar(value=True)
        self._add_vae_name_var = tk.BooleanVar(value=True)
        self._add_vae_hash_var = tk.BooleanVar(value=True)

        self._show_progressbar_var = tk.BooleanVar(value=True)
        self._live_previews_enable_var = tk.BooleanVar(value=True)
        self._show_progress_every_n_steps_var = tk.IntVar(value=10)
        self._live_preview_refresh_period_var = tk.DoubleVar(value=0.5)
        self._interrupt_after_current_var = tk.BooleanVar()

        self._memmon_poll_rate_var = tk.DoubleVar(value=0.5)
        self._enable_upscale_progressbar_var = tk.BooleanVar(value=True)
        self._samples_log_stdout_var = tk.BooleanVar()

        self._build_ui()
        self._load_options()

        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_output_tab(notebook)
        self._build_metadata_tab(notebook)
        self._build_runtime_tab(notebook)
        self._build_monitor_tab(notebook)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Apply", command=self._on_apply).pack(side="right", padx=(5, 0))
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side="right")

    def _build_output_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Output")

        row = 0
        ttk.Label(frame, text="JPEG quality (1–100):").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(
            frame,
            from_=1,
            to=100,
            textvariable=self._jpeg_quality_var,
            width=6,
        ).grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Checkbutton(
            frame,
            text="Use lossless WebP",
            variable=self._webp_lossless_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Label(frame, text="Max image size (MP):").grid(row=row, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self._img_max_size_mp_var, width=8).grid(
            row=row, column=1, sticky="w"
        )

    def _build_metadata_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Metadata")

        options = [
            ("Write infotext into PNG metadata", self._enable_pnginfo_var),
            ("Save .txt next to every image", self._save_txt_var),
            ("Add model name to infotext", self._add_model_name_var),
            ("Add model hash to infotext", self._add_model_hash_var),
            ("Add VAE name to infotext", self._add_vae_name_var),
            ("Add VAE hash to infotext", self._add_vae_hash_var),
        ]
        for row, (label, var) in enumerate(options):
            ttk.Checkbutton(frame, text=label, variable=var).grid(
                row=row,
                column=0,
                sticky="w",
                padx=(0, 8),
                pady=(0 if row == 0 else 2, 0),
            )

    def _build_runtime_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Runtime")

        row = 0
        ttk.Checkbutton(
            frame,
            text="Show progress bar",
            variable=self._show_progressbar_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Checkbutton(
            frame,
            text="Enable live previews",
            variable=self._live_previews_enable_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Label(frame, text="Preview every N steps:").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(
            frame,
            from_=1,
            to=999,
            textvariable=self._show_progress_every_n_steps_var,
            width=6,
        ).grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Label(frame, text="Live preview refresh (s):").grid(row=row, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self._live_preview_refresh_period_var, width=8).grid(
            row=row, column=1, sticky="w"
        )
        row += 1

        ttk.Checkbutton(
            frame,
            text="Interrupt only after current image",
            variable=self._interrupt_after_current_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w")

    def _build_monitor_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Monitoring")

        row = 0
        ttk.Label(frame, text="VRAM poll rate (Hz):").grid(row=row, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self._memmon_poll_rate_var, width=8).grid(
            row=row, column=1, sticky="w"
        )
        row += 1

        ttk.Checkbutton(
            frame,
            text="Show upscaling progress bar",
            variable=self._enable_upscale_progressbar_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Checkbutton(
            frame,
            text="Log samples to stdout",
            variable=self._samples_log_stdout_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w")

    def _load_options(self) -> None:
        try:
            self._options = self.client.get_options()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Engine Settings", f"Failed to load engine settings: {exc}")
            self.destroy()
            return

        get = self._options.get

        self._jpeg_quality_var.set(int(get("jpeg_quality", 95)))
        self._webp_lossless_var.set(bool(get("webp_lossless", False)))
        self._img_max_size_mp_var.set(float(get("img_max_size_mp", 0)))

        self._enable_pnginfo_var.set(bool(get("enable_pnginfo", True)))
        self._save_txt_var.set(bool(get("save_txt", False)))
        self._add_model_name_var.set(bool(get("add_model_name_to_info", True)))
        self._add_model_hash_var.set(bool(get("add_model_hash_to_info", True)))
        self._add_vae_name_var.set(bool(get("add_vae_name_to_info", True)))
        self._add_vae_hash_var.set(bool(get("add_vae_hash_to_info", True)))

        self._show_progressbar_var.set(bool(get("show_progressbar", True)))
        self._live_previews_enable_var.set(bool(get("live_previews_enable", True)))
        self._show_progress_every_n_steps_var.set(int(get("show_progress_every_n_steps", 10)))
        self._live_preview_refresh_period_var.set(
            float(get("live_preview_refresh_period", 0.5))
        )
        self._interrupt_after_current_var.set(bool(get("interrupt_after_current", False)))

        self._memmon_poll_rate_var.set(float(get("memmon_poll_rate", 0.5)))
        self._enable_upscale_progressbar_var.set(bool(get("enable_upscale_progressbar", True)))
        self._samples_log_stdout_var.set(bool(get("samples_log_stdout", False)))

    def _on_apply(self) -> None:
        updates: Dict[str, Any] = {
            "jpeg_quality": int(self._jpeg_quality_var.get()),
            "webp_lossless": bool(self._webp_lossless_var.get()),
            "img_max_size_mp": float(self._img_max_size_mp_var.get()),
            "enable_pnginfo": bool(self._enable_pnginfo_var.get()),
            "save_txt": bool(self._save_txt_var.get()),
            "add_model_name_to_info": bool(self._add_model_name_var.get()),
            "add_model_hash_to_info": bool(self._add_model_hash_var.get()),
            "add_vae_name_to_info": bool(self._add_vae_name_var.get()),
            "add_vae_hash_to_info": bool(self._add_vae_hash_var.get()),
            "show_progressbar": bool(self._show_progressbar_var.get()),
            "live_previews_enable": bool(self._live_previews_enable_var.get()),
            "show_progress_every_n_steps": int(self._show_progress_every_n_steps_var.get()),
            "live_preview_refresh_period": float(self._live_preview_refresh_period_var.get()),
            "interrupt_after_current": bool(self._interrupt_after_current_var.get()),
            "memmon_poll_rate": float(self._memmon_poll_rate_var.get()),
            "enable_upscale_progressbar": bool(self._enable_upscale_progressbar_var.get()),
            "samples_log_stdout": bool(self._samples_log_stdout_var.get()),
        }

        try:
            self.client.update_options(updates)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Engine Settings", f"Failed to apply settings: {exc}")
            return

        messagebox.showinfo("Engine Settings", "Settings applied successfully.")
        self.destroy()

```

## `src/gui/enhanced_slider.py`

```
"""
Enhanced slider widget with arrow buttons for precise control
"""

import tkinter as tk
from tkinter import ttk


class EnhancedSlider(ttk.Frame):
    """Slider with arrow buttons and improved value display"""

    def __init__(
        self,
        parent,
        from_=0,
        to=100,
        variable=None,
        resolution=0.01,
        width=150,
        length=150,
        label="",
        command=None,
        **kwargs,
    ):
        # length is a valid ttk.Scale parameter, so we keep it
        if "length" in kwargs:
            length = kwargs.pop("length")
        else:
            length = 150  # Default value

        super().__init__(parent, **kwargs)

        self.variable = variable or tk.DoubleVar()
        self.command = command

        # Main frame for layout
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.X, expand=True)

        # Label
        if label:
            self.label_widget = ttk.Label(main_frame, text=label, width=12)
            self.label_widget.pack(side=tk.LEFT, padx=(0, 5))

        # Down arrow
        self.down_arrow = ttk.Button(
            main_frame,
            text="◀",
            width=3,
            style="Dark.TButton",
            command=lambda: self.set_value(self.variable.get() - resolution),
        )
        self.down_arrow.pack(side=tk.LEFT)

        # Slider
        self.slider = ttk.Scale(
            main_frame,
            from_=from_,
            to=to,
            orient=tk.HORIZONTAL,
            variable=self.variable,
            command=self._on_slider_change,
            length=length,
            style="Dark.Horizontal.TScale",
        )
        self.slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Up arrow
        self.up_arrow = ttk.Button(
            main_frame,
            text="▶",
            width=3,
            style="Dark.TButton",
            command=lambda: self.set_value(self.variable.get() + resolution),
        )
        self.up_arrow.pack(side=tk.LEFT)

        # Value entry
        self.value_entry = ttk.Entry(main_frame, textvariable=self.variable, width=6)
        self.value_entry.pack(side=tk.LEFT, padx=(5, 0))

        self.value_entry.bind("<Return>", self._on_entry_commit)
        self.value_entry.bind("<FocusOut>", self._on_entry_commit)

    def _on_slider_change(self, value_str):
        """Handle slider value change"""
        value = float(value_str)
        self.variable.set(round(value, 2))
        if self.command:
            self.command(self.variable.get())

    def _on_entry_commit(self, event=None):
        """Handle when user commits a value in the entry box"""
        try:
            value = float(self.value_entry.get())
            self.variable.set(value)
        except ValueError:
            # Revert to last valid value if input is invalid
            self.value_entry.delete(0, tk.END)
            self.value_entry.insert(0, f"{self.variable.get():.2f}")

        if self.command:
            self.command(self.variable.get())

    def set_value(self, value):
        """Set the slider's value programmatically"""
        self.variable.set(value)
        if self.command:
            self.command(value)

    def get_value(self):
        """Get the slider's current value"""
        return self.variable.get()

    def configure_state(self, state):
        """Enable or disable the entire widget"""
        for widget in [self.down_arrow, self.slider, self.up_arrow, self.value_entry]:
            widget.configure(state=state)

    def update_label(self, new_label):
        """Update the label text"""
        if hasattr(self, "label_widget"):
            self.label_widget.config(text=new_label)

        self.from_ = from_
        self.to = to
        self.resolution = resolution
        self.variable = variable or tk.DoubleVar()
        self.command = command

        # Create the widgets
        self._create_widgets(width, label)

        # Bind variable changes
        self.variable.trace("w", self._on_variable_change)

    def _create_widgets(self, width, label):
        """Create the slider widgets"""
        # Left arrow button
        self.left_btn = ttk.Button(
            self, text="◀", width=3, style="Dark.TButton", command=self._decrease_value
        )
        self.left_btn.pack(side=tk.LEFT, padx=(0, 2))

        # Scale widget
        self.scale = ttk.Scale(
            self,
            from_=self.from_,
            to=self.to,
            variable=self.variable,
            orient=tk.HORIZONTAL,
            length=width,
            style="Dark.Horizontal.TScale",
        )
        self.scale.pack(side=tk.LEFT, padx=2)

        # Right arrow button
        self.right_btn = ttk.Button(
            self, text="▶", width=3, style="Dark.TButton", command=self._increase_value
        )
        self.right_btn.pack(side=tk.LEFT, padx=(2, 5))

        # Value display label
        self.value_label = ttk.Label(self, text="0.00", width=6)
        self.value_label.pack(side=tk.LEFT)

        # Update display
        self._update_display()

    def _decrease_value(self):
        """Decrease value by resolution"""
        current = self.variable.get()
        new_value = max(self.from_, current - self.resolution)
        self.variable.set(new_value)

    def _increase_value(self):
        """Increase value by resolution"""
        current = self.variable.get()
        new_value = min(self.to, current + self.resolution)
        self.variable.set(new_value)

    def _on_variable_change(self, *args):
        """Handle variable changes"""
        self._update_display()
        if self.command:
            self.command(self.variable.get())

    def _update_display(self):
        """Update the value display"""
        value = self.variable.get()
        # Format based on resolution
        if self.resolution >= 1:
            display_text = f"{int(value)}"
        elif self.resolution >= 0.1:
            display_text = f"{value:.1f}"
        else:
            display_text = f"{value:.2f}"

        self.value_label.config(text=display_text)

    def get(self):
        """Get current value"""
        return self.variable.get()

    def set(self, value):
        """Set current value"""
        self.variable.set(value)

    def configure(self, **kwargs):
        """Configure the slider"""
        if "command" in kwargs:
            self.command = kwargs.pop("command")
        if "state" in kwargs:
            state = kwargs.pop("state")
            self.scale.config(state=state)
            self.left_btn.config(state=state)
            self.right_btn.config(state=state)

        super().configure(**kwargs)

```

## `src/gui/log_panel.py`

```
"""
LogPanel - UI component for displaying live log messages.

This panel provides a scrolling log view with thread-safe logging handler integration.
"""

import logging
import queue
import tkinter as tk
from tkinter import scrolledtext, ttk

logger = logging.getLogger(__name__)


LEVEL_STYLES: dict[str, str] = {
    "DEBUG": "#888888",
    "INFO": "#4CAF50",
    "SUCCESS": "#2196F3",
    "WARNING": "#FF9800",
    "ERROR": "#f44336",
}

LEVEL_ORDER: tuple[str, ...] = tuple(LEVEL_STYLES.keys())
DEFAULT_LEVEL = "INFO"


class LogPanel(ttk.Frame):
    """
    A UI panel for displaying live log messages.

    This panel handles:
    - Scrolled text widget for log display
    - Color-coded log levels (INFO, WARNING, ERROR, SUCCESS)
    - Thread-safe log message queue
    - log(message, level) API for direct logging
    """

    def __init__(
        self, parent: tk.Widget, coordinator: object | None = None, height: int = 6, **kwargs
    ):
        """
        Initialize the LogPanel.

        Args:
            parent: Parent widget
            coordinator: Coordinator object (for mediator pattern)
            height: Height of log text widget in lines
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.coordinator = coordinator
        self.height = height

        # Message queue for thread-safe logging
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        # Buffer to support filtering and clipboard operations
        self.log_records: list[tuple[str, str]] = []
        self.max_log_lines = 1000
        self._line_count = 0

        # Scroll and filter state
        self.scroll_lock_var = tk.BooleanVar(master=self, value=False)
        self.level_filter_vars: dict[str, tk.BooleanVar] = {}

        # Build UI
        self._build_ui()

        # Start queue processing
        self._process_queue()

    def _build_ui(self):
        """Build the panel UI."""
        # Log frame with dark theme
        log_frame = ttk.LabelFrame(self, text="📋 Live Log", style="Dark.TLabelframe", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        controls_frame = ttk.Frame(log_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Checkbutton(
            controls_frame,
            text="Scroll Lock",
            variable=self.scroll_lock_var,
            command=self._on_scroll_lock_toggle,
        ).pack(side=tk.LEFT)

        ttk.Button(
            controls_frame,
            text="Copy Log",
            command=self.copy_log_to_clipboard,
        ).pack(side=tk.RIGHT)

        filter_frame = ttk.Frame(log_frame)
        filter_frame.pack(fill=tk.X, pady=(0, 5))

        for level in LEVEL_ORDER:
            var = tk.BooleanVar(master=self, value=True)
            self.level_filter_vars[level] = var
            ttk.Checkbutton(
                filter_frame,
                text=level.title(),
                variable=var,
                command=self._on_filter_change,
            ).pack(side=tk.LEFT, padx=(0, 4))

        # Scrolled text widget
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=self.height,
            wrap=tk.WORD,
            bg="#2B2A2C",  # ASWF_DARK_GREY
            fg="#FFC805",  # ASWF_GOLD
            font=("Calibri", 11),  # Consistent with theme
            state=tk.DISABLED,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        for level, color in LEVEL_STYLES.items():
            self.log_text.tag_configure(level, foreground=color)

    def log(self, message: str, level: str = "INFO") -> None:
        """
        Add a log message to the display.

        This method is thread-safe and can be called from any thread.

        Args:
            message: Log message text
            level: Log level (INFO, WARNING, ERROR, SUCCESS, DEBUG)
        """
        # Add to queue for processing on main thread
        self.log_queue.put((message, level))
        try:
            self.after(0, self._process_queue)
        except Exception:
            pass

    def append(self, message: str, level: str = "INFO") -> None:
        """
        Append a log message to the display (alias for log()).

        This method is thread-safe and can be called from any thread.

        Args:
            message: Log message text
            level: Log level (INFO, WARNING, ERROR, SUCCESS, DEBUG)
        """
        self.log(message, level)

    def _process_queue(self):
        """Process pending log messages from queue."""
        # Process all pending messages
        while not self.log_queue.empty():
            try:
                message, level = self.log_queue.get_nowait()
                try:
                    self._add_log_message(message, level)
                except Exception:
                    # Ignore UI errors (widget may be destroyed during teardown)
                    pass
            except queue.Empty:
                break

        # Schedule next processing
        self.after(100, self._process_queue)

    # Test/utility: process queued log messages synchronously (no scheduling)
    def _flush_queue_sync(self) -> None:
        """Synchronously flush the log queue; intended for tests."""
        while not self.log_queue.empty():
            try:
                message, level = self.log_queue.get_nowait()
                self._add_log_message(message, level)
            except queue.Empty:
                break

    def _add_log_message(self, message: str, level: str) -> None:
        """
        Add a log message to the text widget (must be called on main thread).

        Args:
            message: Log message text
            level: Log level for coloring
        """
        normalized_level = level.upper()
        if normalized_level not in LEVEL_STYLES:
            logger.debug(
                f"Unknown log level '{level}' encountered; falling back to DEFAULT_LEVEL ('{DEFAULT_LEVEL}')."
            )
            normalized_level = DEFAULT_LEVEL

        self.log_records.append((message, normalized_level))

        if len(self.log_records) > self.max_log_lines:
            # Only trim and refresh when the log first exceeds the limit
            self.log_records = self.log_records[-self.max_log_lines :]
            self._refresh_display()
            return
        elif len(self.log_records) == self.max_log_lines:
            # Already at limit, pop oldest and insert efficiently
            self.log_records.pop(0)
            self.log_records.append((message, normalized_level))
            if self._should_display(normalized_level):
                self._insert_message(message, normalized_level)
            return

        if self._should_display(normalized_level):
            self._insert_message(message, normalized_level)

    def _insert_message(self, message: str, level: str) -> None:
        preserve_pos = bool(self.scroll_lock_var.get())
        try:
            top_before = self.log_text.yview()[0] if preserve_pos else None
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"{message}\n", level)
            if not self.scroll_lock_var.get():
                self.log_text.see(tk.END)
            elif top_before is not None:
                try:
                    self.log_text.yview_moveto(top_before)
                except Exception:
                    pass
            self.log_text.configure(state=tk.DISABLED)
        except Exception:
            # Widget likely destroyed; safely ignore
            return
        if self._should_display(level) and self._line_count < self.max_log_lines:
            self._line_count += 1

    def _should_display(self, level: str) -> bool:
        var = self.level_filter_vars.get(level)
        return True if var is None else bool(var.get())

    def _refresh_display(self) -> None:
        preserve_pos = bool(self.scroll_lock_var.get())
        try:
            top_before = self.log_text.yview()[0] if preserve_pos else None
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete("1.0", tk.END)
            visible_count = 0
            for message, level in self.log_records:
                if self._should_display(level):
                    self.log_text.insert(tk.END, f"{message}\n", level)
                    visible_count += 1
            if not self.scroll_lock_var.get():
                self.log_text.see(tk.END)
            elif preserve_pos and top_before is not None:
                try:
                    self.log_text.yview_moveto(top_before)
                except Exception:
                    pass
            self.log_text.configure(state=tk.DISABLED)
            self._line_count = min(visible_count, self.max_log_lines)
        except Exception:
            # Widget likely destroyed; ignore refresh request
            pass

    def _on_filter_change(self) -> None:
        self._refresh_display()

    def _on_scroll_lock_toggle(self) -> None:
        if not self.scroll_lock_var.get():
            # Unlock: follow new messages
            self.log_text.see(tk.END)
            if hasattr(self, "_locked_view_top"):
                delattr(self, "_locked_view_top")
        else:
            # Lock: preserve current view top
            try:
                self._locked_view_top = self.log_text.yview()[0]
            except Exception:
                self._locked_view_top = 0.0

    # Convenience API expected by tests
    @property
    def text(self) -> scrolledtext.ScrolledText:
        """Return the underlying text widget (for legacy compatibility)."""
        return self.log_text

    def get_scroll_lock(self) -> bool:
        """Return True if scroll lock is enabled, else False."""
        return bool(self.scroll_lock_var.get())

    def set_scroll_lock(self, enabled: bool) -> None:
        """Enable or disable scroll lock and apply behavior immediately."""
        self.scroll_lock_var.set(bool(enabled))
        self._on_scroll_lock_toggle()

    def copy_log_to_clipboard(self) -> None:
        """Copy the current log contents to the system clipboard."""
        content = self.log_text.get("1.0", tk.END).strip()
        try:
            self.clipboard_clear()
            if content:
                self.clipboard_append(content)
            self._clipboard_cache = content
        except tk.TclError:
            logger.debug("Clipboard unavailable for log copy")
            self._clipboard_cache = content

    def clear(self) -> None:
        """Clear all log messages."""
        self.log_records.clear()
        try:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete("1.0", tk.END)
            self._line_count = 0
            self.log_text.configure(state=tk.DISABLED)
        except Exception:
            # Widget may be destroyed
            self._line_count = 0

    def clipboard_get(self, **kw):
        try:
            return super().clipboard_get(**kw)
        except tk.TclError:
            return getattr(self, "_clipboard_cache", "")


class TkinterLogHandler(logging.Handler):
    """
    Logging handler that forwards log records to a LogPanel.

    This handler is thread-safe and can be used to redirect Python logging
    to the GUI log display.
    """

    def __init__(self, log_panel: LogPanel):
        """
        Initialize the handler.

        Args:
            log_panel: LogPanel instance to send log messages to
        """
        super().__init__()
        self.log_panel = log_panel

        # Set default format
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
        )
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record to the panel.

        Args:
            record: Log record to emit
        """
        try:
            # Format the message
            message = self.format(record)

            # Map logging level to panel level
            level_map = {
                logging.DEBUG: "DEBUG",
                logging.INFO: "INFO",
                logging.WARNING: "WARNING",
                logging.ERROR: "ERROR",
                logging.CRITICAL: "ERROR",
            }

            level = level_map.get(record.levelno, "INFO")

            # Send to panel (thread-safe)
            self.log_panel.log(message, level)

        except Exception:
            # Don't let logging errors break the app
            self.handleError(record)

```

## `src/gui/main_window.py`

```
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from copy import deepcopy
from enum import Enum, auto
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
from typing import Any

from src.api.client import SDWebUIClient, find_webui_api_port, validate_webui_health
from src.controller.pipeline_controller import PipelineController
from src.gui.advanced_prompt_editor import AdvancedPromptEditor
from src.gui.api_status_panel import APIStatusPanel
from src.gui.config_panel import ConfigPanel
from src.gui.enhanced_slider import EnhancedSlider
from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.gui.log_panel import LogPanel, TkinterLogHandler
from src.gui.pipeline_controls_panel import PipelineControlsPanel
from src.gui.prompt_pack_panel import PromptPackPanel
from src.gui.scrolling import enable_mousewheel, make_scrollable
from src.gui.state import GUIState, StateManager
from src.gui.theme import Theme
from src.gui.tooltip import Tooltip
from src.pipeline.executor import Pipeline
from src.services.config_service import ConfigService
from src.utils import StructuredLogger
from src.utils.aesthetic_detection import detect_aesthetic_extension
from src.utils.config import ConfigManager
from src.utils.file_io import get_prompt_packs, read_prompt_pack
from src.utils.preferences import PreferencesManager
from src.utils.randomizer import (
    PromptRandomizer,
    PromptVariant,
    apply_variant_to_config,
    build_variant_plan,
)
from src.utils.state import CancellationError
from src.utils.webui_discovery import WebUIDiscovery
from src.utils.webui_launcher import launch_webui_safely


# Config source state machine
class ConfigSource(Enum):
    PACK = auto()
    PRESET = auto()
    GLOBAL_LOCK = auto()


class ConfigContext:
    def __init__(
        self,
        source=ConfigSource.PACK,
        editor_cfg=None,
        locked_cfg=None,
        active_preset=None,
        active_list=None,
    ):
        self.source = source
        self.editor_cfg = editor_cfg or {}
        self.locked_cfg = locked_cfg
        self.active_preset = active_preset
        self.active_list = active_list


logger = logging.getLogger(__name__)

_FORCE_GUI_TEST_MODE: bool | None = None


def enable_gui_test_mode() -> None:
    """Explicit hook for tests to force GUI test behavior."""

    global _FORCE_GUI_TEST_MODE
    _FORCE_GUI_TEST_MODE = True


def disable_gui_test_mode() -> None:
    """Forcefully disable GUI test mode regardless of environment."""

    global _FORCE_GUI_TEST_MODE
    _FORCE_GUI_TEST_MODE = False


def reset_gui_test_mode() -> None:
    """Return GUI test mode detection to the environment-based default."""

    global _FORCE_GUI_TEST_MODE
    _FORCE_GUI_TEST_MODE = None


def is_gui_test_mode() -> bool:
    """Return True when running under automated GUI test harness."""

    if _FORCE_GUI_TEST_MODE is not None:
        return _FORCE_GUI_TEST_MODE
    return os.environ.get("STABLENEW_GUI_TEST_MODE") == "1"


def sanitize_prompt(text: str) -> str:
    """Strip leftover [[slot]] / __wildcard__ tokens before sending to WebUI."""
    if not text:
        return text
    cleaned = re.sub(r"\[\[[^\]]+\]\]", "", text)
    cleaned = re.sub(r"__\w+__", "", cleaned)
    return " ".join(cleaned.split())

class StableNewGUI:
    def __init__(
        self,
        root: tk.Tk | None = None,
        config_manager: ConfigManager | None = None,
        preferences: PreferencesManager | None = None,
        state_manager: StateManager | None = None,
        controller: PipelineController | None = None,
        webui_discovery: WebUIDiscovery | None = None,
        title: str = "StableNew",
        geometry: str = "1280x820",
        default_preset_name: str | None = None,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.preferences_manager = preferences or PreferencesManager()
        self.state_manager = state_manager or StateManager(initial_state=GUIState.IDLE)

        # Single StructuredLogger instance owned by the GUI and shared with the controller.
        self.structured_logger = StructuredLogger()

        self.controller = controller or PipelineController(self.state_manager)
        try:
            self.controller.structured_logger = self.structured_logger
        except Exception:
            setattr(self.controller, "structured_logger", self.structured_logger)
        self.webui = webui_discovery or WebUIDiscovery()
        self._refreshing_config = False
        if root is not None:
            self.root = root
        else:
            self.root = tk.Tk()
        self._configure_controller_progress_callbacks()
        self.root.title(title)
        self.root.geometry(geometry)
        self.window_min_size = (1024, 720)
        self.root.minsize(*self.window_min_size)
        self._build_menu_bar()

        # Initialize theme
        self.theme = Theme()
        self.theme.apply_root(self.root)

        # Initialize ttk style and theme colors
        self.style = ttk.Style()
        self.theme.apply_ttk_styles(self.style)

        # --- ConfigService and ConfigContext wiring ---
        packs_dir = Path("packs")
        presets_dir = Path("presets")
        lists_dir = Path("lists")
        self.config_service = ConfigService(packs_dir, presets_dir, lists_dir)
        self.ctx = ConfigContext()
        self.config_source_banner = None
        self.current_selected_packs = []
        self.is_locked = False
        self.previous_source = None
        self.previous_banner_text = "Using: Global Config"
        self.current_preset_name = None

        # Initialize API-related variables
        self.api_url_var = tk.StringVar(value="http://127.0.0.1:7860")
        self.preset_var = tk.StringVar(value="default")
        self._wrappable_labels: list[tk.Widget] = []
        self.scrollable_sections: dict[str, dict[str, tk.Widget | None]] = {}
        self._log_min_lines = 7
        self._image_warning_threshold = 250
        self.upscaler_names: list[str] = []
        self.sampler_names: list[str] = []

        # Initialize aesthetic/randomization defaults before building UI
        self.aesthetic_script_available = False
        self.aesthetic_extension_root: Path | None = None
        self.aesthetic_embeddings: list[str] = ["None"]
        self.aesthetic_embedding_var = tk.StringVar(value="None")
        self.aesthetic_status_var = tk.StringVar(value="Aesthetic extension not detected")
        self.aesthetic_widgets: dict[str, list[tk.Widget]] = {
            "all": [],
            "script": [],
            "prompt": [],
        }

        # Stage toggles used by multiple panels
        self.txt2img_enabled = tk.BooleanVar(value=True)
        self.img2img_enabled = tk.BooleanVar(value=True)
        self.adetailer_enabled = tk.BooleanVar(value=False)
        self.upscale_enabled = tk.BooleanVar(value=True)
        self.video_enabled = tk.BooleanVar(value=False)
        self._config_dirty = False
        self._config_panel_prefs_bound = False
        self._preferences_ready = False
        self._new_features_dialog_shown = False

        # Initialize progress-related attributes
        self._progress_eta_default = "ETA: --:--"
        self._progress_idle_message = "Ready"

        # Load preferences before building UI
        default_config = self.config_manager.get_default_config()
        try:
            self.preferences = self.preferences_manager.load_preferences(default_config)
        except Exception as exc:
            logger.error(
                "Failed to load preferences; falling back to defaults: %s", exc, exc_info=True
            )
            self.preferences = self.preferences_manager.default_preferences(default_config)
            self._handle_preferences_load_failure(exc)

        # Build the user interface
        self._build_ui()
        try:
            self.root.bind("<Configure>", self._on_root_resize, add="+")
        except Exception:
            pass
        self._reset_config_dirty_state()
        self._preferences_ready = True

        # Initialize summary variables for live config display
        self.txt2img_summary_var = tk.StringVar(value="")
        self.img2img_summary_var = tk.StringVar(value="")
        self.upscale_summary_var = tk.StringVar(value="")
        self._maybe_show_new_features_dialog()

    def _apply_webui_status(self, status) -> None:
        # Update any labels/combos based on discovered status.
        # (Implement specific UI updates in your controls panel)
        try:
            self.pipeline_controls_panel.on_webui_status(status)
        except Exception:
            logger.exception("Failed to apply WebUI status")

    def _apply_webui_error(self, e: Exception) -> None:
        logger.warning("WebUI error: %s", e)
        # Optionally update UI to reflect disconnected state
        try:
            self.pipeline_controls_panel.on_webui_error(e)
        except Exception:
            logger.exception("Failed to apply WebUI error")

    def _update_config_source_banner(self, text: str) -> None:
        """Update the config source banner with the given text."""
        self.config_source_banner.config(text=text)

    def _effective_cfg_for_pack(self, pack: str) -> dict[str, Any]:
        """Get the effective config for a pack based on current ctx.source."""
        if self.ctx.source is ConfigSource.GLOBAL_LOCK and self.ctx.locked_cfg is not None:
            return deepcopy(self.ctx.locked_cfg)
        if self.ctx.source is ConfigSource.PRESET:
            return deepcopy(self.ctx.editor_cfg)
        cfg = self.config_service.load_pack_config(pack)
        return cfg if cfg else deepcopy(self.ctx.editor_cfg)  # fallback to editor defaults

    def _preview_payload_dry_run(self) -> None:
        """
        Dry-run the selected packs and report how many prompts/variants would be produced.
        """
        selected_packs = self._get_selected_packs()
        if not selected_packs:
            self.log_message("No prompt packs selected for dry run", "WARNING")
            return
        selected_copy = list(selected_packs)

        def worker():
            config_snapshot = self._get_config_snapshot()
            rand_cfg = deepcopy(config_snapshot.get("randomization") or {})

            total_prompts = 0
            total_variants = 0
            sample_variants: list[PromptVariant] = []
            pack_summaries: list[str] = []

            for pack_path in selected_copy:
                prompts = read_prompt_pack(pack_path)
                if not prompts:
                    self.log_message(
                        f"[DRY RUN] No prompts found in {pack_path.name}", "WARNING"
                    )
                    continue

                total_prompts += len(prompts)
                pack_variants, pack_samples = self._estimate_pack_variants(
                    prompts, deepcopy(rand_cfg)
                )
                total_variants += pack_variants
                pack_summaries.append(
                    f"[DRY RUN] Pack {pack_path.name}: {len(prompts)} prompt(s) -> {pack_variants} variant(s)"
                )
                for variant in pack_samples:
                    if len(sample_variants) >= 10:
                        break
                    sample_variants.append(variant)

            images_per_prompt = self._safe_int_from_var(self.images_per_prompt_var, 1)
            loop_multiplier = self._safe_int_from_var(self.loop_count_var, 1)
            predicted_images = total_variants * images_per_prompt * loop_multiplier

            summary = (
                f"[DRY RUN] {len(selected_copy)} pack(s) • "
                f"{total_prompts} prompt(s) • "
                f"{total_variants} variant(s) × {images_per_prompt} img/prompt × loops={loop_multiplier} "
                f"→ ≈ {predicted_images} image(s)"
            )
            self.log_message(summary, "INFO")

            for line in pack_summaries:
                self.log_message(line, "INFO")

            for idx, variant in enumerate(sample_variants[:5], start=1):
                label_part = f" ({variant.label})" if variant.label else ""
                preview_text = (variant.text or "")[:200]
                self.log_message(f"[DRY RUN] ex {idx}{label_part}: {preview_text}", "INFO")

            self._maybe_warn_large_output(predicted_images, "dry run preview")

        threading.Thread(target=worker, daemon=True).start()

    def _safe_int_from_var(self, var: tk.Variable | None, default: int = 1) -> int:
        try:
            value = int(var.get()) if var is not None else default
        except Exception:
            value = default
        return value if value > 0 else default

    def _estimate_pack_variants(
        self, prompts: list[dict[str, str]], rand_cfg: dict[str, Any]
    ) -> tuple[int, list[PromptVariant]]:
        total = 0
        samples: list[PromptVariant] = []
        if not prompts:
            return 0, samples

        simulator: PromptRandomizer | None = None
        rand_enabled = bool(rand_cfg.get("enabled")) if isinstance(rand_cfg, dict) else False
        if rand_enabled:
            try:
                simulator = PromptRandomizer(deepcopy(rand_cfg))
            except Exception:
                simulator = None

        for prompt_data in prompts:
            prompt_text = prompt_data.get("positive", "") or ""
            if simulator:
                variants = simulator.generate(prompt_text)
                if not variants:
                    variants = [PromptVariant(text=prompt_text, label=None)]
            else:
                variants = [PromptVariant(text=prompt_text, label=None)]

            total += len(variants)
            if len(samples) < 10:
                samples.extend(variants[:2])

        return total, samples

    def _maybe_warn_large_output(self, count: int, context: str) -> None:
        threshold = getattr(self, "_image_warning_threshold", 0) or 0
        if threshold and count >= threshold:
            self.log_message(
                f"⚠️ Expected to generate approximately {count} image(s) for {context}. "
                "Adjust randomization or Images/Prompt if this is unintended.",
                "WARNING",
            )


    # -------- mediator selection -> config refresh --------
    def _on_pack_selection_changed_mediator(self, packs: list[str]) -> None:
        """
        Mediator callback from PromptPackPanel; always UI thread.
        We keep this handler strictly non-blocking and UI-only.
        """
        try:
            self.current_selected_packs = packs
            count = len(packs)
            if count == 0:
                logger.info("📦 No pack selected")
            else:
                logger.info("📦 Selected pack: %s", packs[0] if count == 1 else f"{count} packs")
            # Update banner instead of refreshing config
            if packs:
                if len(packs) == 1:
                    text = "Using: Pack Config"
                else:
                    text = "Using: Multi-Pack Config"
            else:
                text = "Using: Global Config"
            self._update_config_source_banner(text)
        except Exception:
            logger.exception("Mediator selection handler failed")

    def _refresh_config(self, packs: list[str]) -> None:
        """
        Load pack config and apply to controls. UI-thread only. Non-reentrant.
        """
        if self._refreshing_config:
            logger.debug("[DIAG] _refresh_config: re-entry detected; skipping")
            return

        self._refreshing_config = True
        try:
            # We currently apply config for first selected pack
            pack = packs[0]
            cfg = self.config_manager.load_pack_config(pack)  # disk read is fine; cheap
            logger.debug("Loaded pack config: %s", pack)

            # Push config to controls panel (must be UI-only logic)
            self.pipeline_controls_panel.apply_config(cfg)
            logger.info("Loaded config for pack: %s", pack)

        except Exception as e:
            logger.exception("Failed to refresh config: %s", e)
            self._safe_messagebox("error", "Config Error", f"{type(e).__name__}: {e}")
        finally:
            self._refreshing_config = False

    # -------- run pipeline --------
    def _on_run_clicked(self) -> None:
        """
        Handler for RUN button; starts pipeline in controller thread.
        Must not block the UI. Error UI is marshaled to Tk thread.
        """
        try:
            selected = self.prompt_pack_panel.get_selected_packs()
            if not selected:
                self._safe_messagebox(
                    "warning", "No Pack Selected", "Please select a prompt pack first."
                )
                return
            packs_str = selected[0] if len(selected) == 1 else f"{len(selected)} packs"
            logger.info("▶️ Starting pipeline execution for %s", packs_str)

            def on_error(err_text):
                self._safe_messagebox("error", "Pipeline Error", err_text)
                try:
                    self.controller.lifecycle_event.set()
                except Exception:
                    pass
                self.root.after(0, lambda: self.state_manager.transition_to(GUIState.ERROR))

            def on_complete():
                try:
                    self.controller.lifecycle_event.set()
                finally:
                    self.root.after(0, lambda: self.state_manager.transition_to(GUIState.IDLE))

            # Launch the controller on a worker thread; it must never touch Tk directly
            threading.Thread(
                target=self.controller.start_pipeline,
                kwargs={
                    "packs": selected,
                    "config_manager": self.config_manager,
                    "on_error": on_error,
                    "on_complete": on_complete,
                },
                daemon=True,
            ).start()

        except Exception as e:
            logger.exception("Run click failed: %s", e)
            self._safe_messagebox("error", "Run Failed", f"{type(e).__name__}: {e}")

    # -------- utilities --------
    def on_error(self, error: Exception | str) -> None:
        """Expose a public error handler for legacy controller/test hooks."""
        if isinstance(error, Exception):
            message = f"{type(error).__name__}: {error}"
        else:
            message = str(error) if error else "Pipeline error"

        try:
            self.state_manager.transition_to(GUIState.ERROR)
        except Exception:
            logger.exception("Failed to transition GUI state to ERROR after pipeline error")

        self._signal_pipeline_finished()

        def handle_error() -> None:
            self._handle_pipeline_error_main_thread(message, error)

        try:
            self.root.after(0, handle_error)
        except Exception:
            handle_error()

    def _handle_pipeline_error_main_thread(self, message: str, error: Exception | str) -> None:
        """Perform UI-safe pipeline error handling on the Tk thread."""

        self.log_message(f"? Pipeline error: {message}", "ERROR")

        suppress_dialog = is_gui_test_mode() or os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {
            "1",
            "true",
            "TRUE",
        }
        if not suppress_dialog:
            self._safe_messagebox("error", "Pipeline Error", message)

    # Duplicate _setup_theme and other duplicate/unused methods removed for linter/ruff compliance

    def _launch_webui(self):
        """Auto-launch Stable Diffusion WebUI with improved detection (non-blocking)."""
        # Allow disabling auto-launch in headless/CI environments
        if os.environ.get("STABLENEW_NO_WEBUI", "").lower() in {"1", "true", "yes"}:
            logger.info("Auto-launch of WebUI disabled by STABLENEW_NO_WEBUI")
            return

        webui_path = Path("C:/Users/rober/stable-diffusion-webui/webui-user.bat")

        # Run discovery/launch in background to avoid freezing Tk mainloop
        def discovery_and_launch():
            # 1) Check if WebUI is already running (may take a few seconds)
            existing_url = find_webui_api_port()
            if existing_url:
                logger.info(f"WebUI already running at {existing_url}")
                self.root.after(0, lambda: self._set_api_url_var(existing_url))
                self.root.after(1000, self._check_api_connection)
                return

            # 2) Attempt to launch WebUI if path exists
            if webui_path.exists():
                self.root.after(
                    0, lambda: self.log_message("🚀 Launching Stable Diffusion WebUI...", "INFO")
                )
                success = launch_webui_safely(webui_path, timeout=15)
                if success:
                    # Find the actual URL and update UI
                    api_url = find_webui_api_port()
                    if api_url:
                        self.root.after(0, lambda: self._set_api_url_var(api_url))
                        self.root.after(1000, self._check_api_connection)
                    else:
                        self.root.after(
                            0,
                            lambda: self.log_message(
                                "⚠️ WebUI launched but API not found", "WARNING"
                            ),
                        )
                else:
                    self.root.after(0, lambda: self.log_message("❌ WebUI launch failed", "ERROR"))
            else:
                logger.warning("WebUI not found at expected location")
                self.root.after(
                    0,
                    lambda: self.log_message(
                        "⚠️ WebUI not found - please start manually", "WARNING"
                    ),
                )
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "WebUI Not Found",
                        (
                            f"WebUI not found at: {webui_path}\n"
                            "Please start Stable Diffusion WebUI manually "
                            "with --api flag and click 'Check API'"
                        ),
                    ),
                )

        threading.Thread(target=discovery_and_launch, daemon=True).start()

    def _ensure_default_preset(self):
        """Ensure default preset exists and load it if set as startup default"""
        if "default" not in self.config_manager.list_presets():
            default_config = self.config_manager.get_default_config()
            self.config_manager.save_preset("default", default_config)

        # Check if a default preset is configured for startup
        default_preset_name = self.config_manager.get_default_preset()
        if default_preset_name:
            logger.info(f"Loading default preset on startup: {default_preset_name}")
            preset_config = self.config_manager.load_preset(default_preset_name)
            if preset_config:
                self.current_preset = default_preset_name
                self.current_config = preset_config
                # preset_var will be set in __init__ after this call
                self.preferences["preset"] = default_preset_name
            else:
                logger.warning(f"Failed to load default preset '{default_preset_name}'")

    def _build_ui(self):
        """Build the modern user interface"""
        # Create main container with minimal padding for space efficiency
        main_frame = ttk.Frame(self.root, style="Dark.TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Config source banner at the top
        self.config_source_banner = ttk.Label(
            main_frame, text="Using: Pack Config", style="Dark.TLabel"
        )
        self.config_source_banner.pack(anchor=tk.W, padx=5, pady=(0, 5))

        # Action bar for explicit config loading
        self._build_action_bar(main_frame)

        # Main content + log splitter so the bottom panel stays visible
        vertical_split = ttk.Panedwindow(main_frame, orient=tk.VERTICAL)
        self._vertical_split = vertical_split
        vertical_split.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Main content frame - optimized layout
        content_frame = ttk.Frame(vertical_split, style="Dark.TFrame")
        vertical_split.add(content_frame, weight=4)

        # Configure grid for better space utilization
        content_frame.columnconfigure(
            0, weight=0, minsize=280
        )  # Left: wider pack list for long names
        content_frame.columnconfigure(1, weight=1)  # Center: flexible config
        content_frame.rowconfigure(0, weight=1)

        # Left panel - Compact prompt pack selection
        self._build_prompt_pack_panel(content_frame)

        # Center panel - Configuration notebook
        self._build_config_pipeline_panel(content_frame)

        # Bottom frame - Compact log and action buttons (resizable split)
        bottom_shell = ttk.Frame(vertical_split, style="Dark.TFrame")
        vertical_split.add(bottom_shell, weight=3)
        self._bottom_pane = bottom_shell
        self._build_bottom_panel(bottom_shell)

        # Defer all heavy UI state initialization until after Tk mainloop starts
        try:
            self.root.after(0, self._initialize_ui_state_async)
        except Exception as exc:
            logger.warning("Failed to schedule UI state init: %s", exc)

        # Setup state callbacks
        self._setup_state_callbacks()

        # Attempt to auto-launch WebUI / discover API on startup
        try:
            self._launch_webui()
        except Exception:
            logger.exception("Failed to launch WebUI")

        try:
            self.root.after(1500, self._check_api_connection)
        except Exception:
            logger.warning("Unable to schedule API connection check")

    def _build_api_status_frame(self, parent):
        """Build the API status frame using APIStatusPanel."""
        frame = ttk.Frame(parent, style="Dark.TFrame", relief=tk.SUNKEN)
        frame.pack(fill=tk.X, padx=5, pady=(4, 0))
        frame.configure(height=48)
        frame.pack_propagate(False)

        self.api_status_panel = APIStatusPanel(frame, coordinator=self, style="Dark.TFrame")
        self.api_status_panel.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.check_api_btn = ttk.Button(
            frame,
            text="Check API",
            command=self._check_api_connection,
            style="Accent.TButton",
        )
        self.check_api_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._attach_tooltip(
            self.check_api_btn, "Manually retry connecting to the Stable Diffusion WebUI API."
        )

    def _build_prompt_pack_panel(self, parent):
        """Build the prompt pack selection panel."""
        # Create PromptPackPanel
        self.prompt_pack_panel = PromptPackPanel(
            parent,
            coordinator=self,
            on_selection_changed=self._on_pack_selection_changed_mediator,
            style="Dark.TFrame",
        )
        self.prompt_pack_panel.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))

    def _build_config_pipeline_panel(self, parent):
        """Build the consolidated configuration notebook with Pipeline, Randomization, and General tabs."""
        # Create main notebook for center panel
        self.center_notebook = ttk.Notebook(parent, style="Dark.TNotebook")
        self.center_notebook.grid(row=0, column=1, sticky=tk.NSEW, padx=(0, 5))

        # Pipeline tab - configuration
        pipeline_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
        self.center_notebook.add(pipeline_tab, text="Pipeline")

        self._build_info_box(
            pipeline_tab,
            "Pipeline Configuration",
            "Configure txt2img, img2img, and upscale behavior for the next run. "
            "Use override mode to apply these settings to every selected pack.",
        ).pack(fill=tk.X, padx=10, pady=(10, 4))

        try:
            override_header = ttk.Frame(pipeline_tab, style="Dark.TFrame")
            override_header.pack(fill=tk.X, padx=10, pady=(0, 4))
            override_checkbox = ttk.Checkbutton(
                override_header,
                text="Override pack settings with current config",
                variable=self.override_pack_var,
                style="Dark.TCheckbutton",
                command=self._on_override_changed,
            )
            override_checkbox.pack(side=tk.LEFT)
            self._attach_tooltip(
                override_checkbox,
                "When enabled, the visible configuration is applied to every selected pack. Disable to use each pack's saved config.",
            )
        except Exception:
            pass

        config_scroll = ttk.Frame(pipeline_tab, style="Dark.TFrame")
        config_scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        pipeline_canvas, config_body = make_scrollable(config_scroll, style="Dark.TFrame")
        self._register_scrollable_section("pipeline", pipeline_canvas, config_body)

        self.config_panel = ConfigPanel(config_body, coordinator=self, style="Dark.TFrame")
        self.config_panel.pack(fill=tk.BOTH, expand=True)

        self.txt2img_vars = self.config_panel.txt2img_vars
        self.img2img_vars = self.config_panel.img2img_vars
        self.upscale_vars = self.config_panel.upscale_vars
        self.api_vars = self.config_panel.api_vars
        self.config_status_label = self.config_panel.config_status_label
        self.adetailer_panel = getattr(self.config_panel, "adetailer_panel", None)

        try:
            summary_frame = ttk.LabelFrame(
                pipeline_tab, text="Next Run Summary", style="Dark.TLabelframe", padding=5
            )
            summary_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

            self.txt2img_summary_var = getattr(self, "txt2img_summary_var", tk.StringVar(value=""))
            self.img2img_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
            self.upscale_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
            self.upscale_summary_var = getattr(self, "upscale_summary_var", tk.StringVar(value=""))

            for var in (
                self.txt2img_summary_var,
                self.img2img_summary_var,
                self.upscale_summary_var,
            ):
                ttk.Label(
                    summary_frame,
                    textvariable=var,
                    style="Dark.TLabel",
                    font=("Consolas", 9),
                ).pack(anchor=tk.W, pady=1)

            self._attach_summary_traces()
            self._update_live_config_summary()
        except Exception:
            pass

        # Randomization tab
        randomization_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
        self.center_notebook.add(randomization_tab, text="Randomization")
        self._build_randomization_tab(randomization_tab)

        # General tab - pipeline controls and API settings
        general_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
        self.center_notebook.add(general_tab, text="General")

        general_split = ttk.Frame(general_tab, style="Dark.TFrame")
        general_split.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))

        general_scroll_container = ttk.Frame(general_split, style="Dark.TFrame")
        general_scroll_container.pack(fill=tk.BOTH, expand=True)
        general_canvas, general_body = make_scrollable(general_scroll_container, style="Dark.TFrame")
        self._register_scrollable_section("general", general_canvas, general_body)

        self._build_info_box(
            general_body,
            "General Settings",
            "Manage batch size, looping behavior, and API connectivity. "
            "These settings apply to every run regardless of prompt pack.",
        ).pack(fill=tk.X, pady=(0, 6))

        video_frame = ttk.Frame(general_body, style="Dark.TFrame")
        video_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(
            video_frame,
            text="Enable video stage",
            variable=self.video_enabled,
            style="Dark.TCheckbutton",
        ).pack(anchor=tk.W)

        # Pipeline controls in General tab
        self._build_pipeline_controls_panel(general_body)

        api_frame = ttk.LabelFrame(
            general_body, text="API Configuration", style="Dark.TLabelframe", padding=8
        )
        api_frame.pack(fill=tk.X, pady=(10, 10))
        ttk.Label(api_frame, text="Base URL:", style="Dark.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        ttk.Entry(
            api_frame,
            textvariable=self.api_vars.get("base_url"),
            style="Dark.TEntry",
        ).grid(row=0, column=1, sticky=tk.EW, pady=2, padx=(5, 0))
        api_frame.columnconfigure(1, weight=1)

        ttk.Label(api_frame, text="Timeout (s):", style="Dark.TLabel").grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        ttk.Entry(
            api_frame,
            textvariable=self.api_vars.get("timeout"),
            style="Dark.TEntry",
        ).grid(row=1, column=1, sticky=tk.EW, pady=2, padx=(5, 0))

        # Advanced editor tab for legacy editor access
        advanced_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
        self.center_notebook.add(advanced_tab, text="Advanced Editor")
        self._build_advanced_editor_tab(advanced_tab)

    def _handle_preferences_load_failure(self, exc: Exception) -> None:
        """Notify the user that preferences failed to load and backup the corrupt file."""

        warning_text = (
            "Your last settings could not be loaded. StableNew has reset to safe defaults.\n\n"
            "The previous settings file was moved aside (or removed) to prevent future issues."
        )
        try:
            messagebox.showwarning("StableNew", warning_text)
        except Exception:
            logger.exception("Failed to display corrupt preferences warning dialog")

        try:
            self.preferences_manager.backup_corrupt_preferences()
        except Exception:
            logger.exception("Failed to backup corrupt preferences file")

        self._reset_randomization_to_defaults()

    def _initialize_ui_state_async(self):
        """Initialize UI state asynchronously after mainloop starts."""
        # Restore UI state from preferences
        self._restore_ui_state_from_preferences()

    def _initialize_ui_state(self):
        """Legacy synchronous initialization hook retained for tests."""

        self._initialize_ui_state_async()

    def _restore_ui_state_from_preferences(self):
        """Restore UI state from loaded preferences."""
        try:
            if "preset" in self.preferences:
                self.preset_var.set(self.preferences["preset"])

            if "selected_packs" in self.preferences:
                self.current_selected_packs = self.preferences["selected_packs"]
                if hasattr(self, "prompt_pack_panel"):
                    self.prompt_pack_panel.set_selected_packs(self.current_selected_packs)

            if "override_pack" in self.preferences and hasattr(self, "override_pack_var"):
                self.override_pack_var.set(self.preferences["override_pack"])

            if "pipeline_controls" in self.preferences and hasattr(self, "pipeline_controls_panel"):
                self.pipeline_controls_panel.set_state(self.preferences["pipeline_controls"])

            if "config" in self.preferences:
                self.current_config = self.preferences["config"]
                if hasattr(self, "config_panel"):
                    self._load_config_into_forms(self.current_config)
        except Exception as exc:
            logger.error("Failed to restore preferences to UI; reverting to defaults: %s", exc)
            try:
                fallback_cfg = self.config_manager.get_default_config()
                self.preferences = self.preferences_manager.default_preferences(fallback_cfg)
                self.preset_var.set(self.preferences.get("preset", "default"))
                self.current_selected_packs = []
                if hasattr(self, "prompt_pack_panel"):
                    self.prompt_pack_panel.set_selected_packs([])
                if hasattr(self, "override_pack_var"):
                    self.override_pack_var.set(False)
                if hasattr(self, "pipeline_controls_panel"):
                    self.pipeline_controls_panel.set_state(
                        self.preferences.get("pipeline_controls", {})
                    )
                if hasattr(self, "config_panel"):
                    self._load_config_into_forms(self.preferences.get("config", {}))
                self._reset_randomization_to_defaults()
            except Exception:
                logger.exception("Failed to apply fallback preferences after restore failure")

    def _reset_randomization_to_defaults(self) -> None:
        """Reset randomization config to defaults and update UI if available."""

        try:
            default_cfg = self.config_manager.get_default_config() or {}
            random_defaults = deepcopy(default_cfg.get("randomization", {}) or {})
        except Exception as exc:
            logger.error("Failed to obtain default randomization config: %s", exc)
            return

        self.preferences.setdefault("config", {})["randomization"] = random_defaults

        if hasattr(self, "randomization_vars"):
            try:
                self._load_randomization_config({"randomization": random_defaults})
            except Exception:
                logger.exception("Failed to apply default randomization settings to UI")

    def _build_action_bar(self, parent):
        """Build the action bar with explicit load controls."""
        action_bar = ttk.Frame(parent, style="Dark.TFrame")
        action_bar.pack(fill=tk.X, padx=5, pady=(0, 5))

        button_width = 28

        def add_toolbar_button(container, column, text, command, tooltip=None, style="Dark.TButton"):
            btn = ttk.Button(container, text=text, command=command, style=style, width=button_width)
            btn.grid(row=0, column=column, padx=4, pady=2, sticky="ew")
            container.grid_columnconfigure(column, weight=1)
            if tooltip:
                self._attach_tooltip(btn, tooltip)
            return btn

        row1 = ttk.Frame(action_bar, style="Dark.TFrame")
        row1.pack(fill=tk.X, pady=(0, 4))
        row2 = ttk.Frame(action_bar, style="Dark.TFrame")
        row2.pack(fill=tk.X)

        add_toolbar_button(
            row1,
            0,
            "Load Pack Config",
            self._ui_load_pack_config,
            "Load the selected pack's saved configuration into the editor.",
        )

        preset_container = ttk.Frame(row1, style="Dark.TFrame")
        preset_container.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        row1.grid_columnconfigure(1, weight=2)
        ttk.Label(preset_container, text="Preset:", style="Dark.TLabel").pack(side=tk.LEFT)
        self.preset_combobox = ttk.Combobox(
            preset_container,
            textvariable=self.preset_var,
            values=self.config_service.list_presets(),
            state="readonly",
            width=30,
            style="Dark.TCombobox",
        )
        self.preset_combobox.pack(side=tk.LEFT, padx=(5, 6))
        preset_load_btn = ttk.Button(
            preset_container, text="Load Preset", command=self._ui_load_preset, style="Dark.TButton"
        )
        preset_load_btn.pack(side=tk.LEFT)
        self._attach_tooltip(preset_load_btn, "Load the selected preset into the editor.")

        add_toolbar_button(
            row1,
            2,
            "Save Editor → Preset",
            self._ui_save_preset,
            "Persist the current editor configuration to the active preset slot.",
        )
        add_toolbar_button(
            row1,
            3,
            "Delete Preset",
            self._ui_delete_preset,
            "Remove the selected preset from disk.",
            style="Danger.TButton",
        )

        list_container = ttk.Frame(row2, style="Dark.TFrame")
        list_container.grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        row2.grid_columnconfigure(0, weight=2)
        ttk.Label(list_container, text="List:", style="Dark.TLabel").pack(side=tk.LEFT)
        self.list_combobox = ttk.Combobox(
            list_container,
            values=self.config_service.list_lists(),
            state="readonly",
            width=24,
            style="Dark.TCombobox",
        )
        self.list_combobox.pack(side=tk.LEFT, padx=(5, 6))
        list_load_btn = ttk.Button(
            list_container, text="Load List", command=self._ui_load_list, style="Dark.TButton"
        )
        list_load_btn.pack(side=tk.LEFT)
        self._attach_tooltip(list_load_btn, "Load saved pack selections from the chosen list.")

        add_toolbar_button(
            row2,
            1,
            "Save Selection as List",
            self._ui_save_list,
            "Persist the current pack selection as a reusable list.",
        )
        add_toolbar_button(
            row2,
            2,
            "Overwrite List",
            self._ui_overwrite_list,
            "Replace the chosen list with the current selection.",
        )
        add_toolbar_button(
            row2,
            3,
            "Delete List",
            self._ui_delete_list,
            "Remove the chosen list from disk.",
            style="Danger.TButton",
        )
        self.lock_button = add_toolbar_button(
            row2,
            4,
            "Lock This Config",
            self._ui_toggle_lock,
            "Prevent accidental edits by locking the current configuration.",
        )
        add_toolbar_button(
            row2,
            5,
            "Apply Editor → Pack(s)",
            self._ui_apply_editor_to_packs,
            "Push the editor settings into the selected pack(s).",
        )
        add_toolbar_button(
            row2,
            6,
            "Preview Payload (Dry Run)",
            self._preview_payload_dry_run,
            "Simulate a run and show prompt/variant counts without calling WebUI.",
        )

    def _build_menu_bar(self) -> None:
        """Construct the top-level menu bar."""

        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(
            label="Engine settings...",
            command=self._open_engine_settings_dialog,
        )
        menubar.add_cascade(label="Settings", menu=settings_menu)
        self.root.config(menu=menubar)
        self._menubar = menubar
        self._settings_menu = settings_menu

    def _apply_editor_from_cfg(self, cfg: dict) -> None:
        """Apply config to the editor (config panel)."""
        if not cfg:
            return
        if hasattr(self, "config_panel"):
            self.config_panel.set_config(cfg)
        try:
            self.pipeline_controls_panel.apply_config(cfg)
        except Exception:
            logger.debug("Pipeline controls apply_config skipped", exc_info=True)
        try:
            self._apply_adetailer_config_section(cfg.get("adetailer", {}))
        except Exception:
            logger.debug("ADetailer config apply skipped", exc_info=True)
        try:
            self._load_randomization_config(cfg)
        except Exception:
            logger.debug("Randomization config apply skipped", exc_info=True)
        try:
            self._load_aesthetic_config(cfg)
        except Exception:
            logger.debug("Aesthetic config apply skipped", exc_info=True)

    def _apply_adetailer_config_section(self, adetailer_cfg: dict | None) -> None:
        """Apply ADetailer config to the panel, normalizing scheduler defaults."""
        panel = getattr(self, "adetailer_panel", None)
        if not panel:
            return
        cfg = dict(adetailer_cfg or {})
        scheduler_value = cfg.get("adetailer_scheduler", cfg.get("scheduler", "inherit")) or "inherit"
        cfg["adetailer_scheduler"] = scheduler_value
        cfg["scheduler"] = scheduler_value
        panel.set_config(cfg)

    def _ui_toggle_lock(self) -> None:
        """Toggle the config lock state."""
        if self.is_locked:
            self._unlock_config()
        else:
            self._lock_config()

    def _open_engine_settings_dialog(self) -> None:
        """Open the Engine Settings dialog wired to WebUI options."""

        if self.client is None:
            messagebox.showerror(
                "Engine Settings",
                "Connect to the Stable Diffusion API before editing engine settings.",
            )
            return

        try:
            self._add_log_message("⚙️ Opening Engine Settings dialog…")
        except Exception:
            pass

        try:
            EngineSettingsDialog(self.root, self.client)
        except Exception as exc:
            messagebox.showerror("Engine Settings", f"Unable to open dialog: {exc}")

    def _lock_config(self) -> None:
        """Lock the current config."""
        self.previous_source = self.ctx.source
        self.previous_banner_text = self.config_source_banner.cget("text")
        self.ctx.source = ConfigSource.GLOBAL_LOCK
        self.ctx.locked_cfg = deepcopy(self.pipeline_controls_panel.get_settings())
        self.is_locked = True
        self.lock_button.config(text="Unlock Config")
        self._update_config_source_banner("Using: Global Lock")

    def _unlock_config(self) -> None:
        """Unlock the config."""
        self.ctx.source = self.previous_source
        self.ctx.locked_cfg = None
        self.is_locked = False
        self.lock_button.config(text="Lock This Config")
        self._update_config_source_banner(self.previous_banner_text)

    def _ui_load_pack_config(self) -> None:
        """Load config from the first selected pack into the editor."""
        if self._check_lock_before_load():
            if not self.current_selected_packs:
                return
            pack = self.current_selected_packs[0]
            cfg = self.config_service.load_pack_config(pack)
            if not cfg:
                self._safe_messagebox(
                    "info",
                    "No Saved Config",
                    f"No config saved for '{pack}'. Showing defaults.",
                )
                return
            self._apply_editor_from_cfg(cfg)
            self._update_config_source_banner("Using: Pack Config (view)")
            self._reset_config_dirty_state()

    def _ui_load_preset(self) -> None:
        """Load selected preset into the editor."""
        if self._check_lock_before_load():
            name = self.preset_combobox.get()
            if not name:
                return
            cfg = self.config_service.load_preset(name)
            self._apply_editor_from_cfg(cfg)
            self.current_preset_name = name
            self._update_config_source_banner(f"Using: Preset: {name}")
            self._reset_config_dirty_state()

    def _check_lock_before_load(self) -> bool:
        """Check if locked and prompt to unlock. Returns True if should proceed."""
        if not self.is_locked:
            return True
        result = messagebox.askyesno("Config Locked", "Unlock to proceed?")
        if result:
            self._unlock_config()
            return True
        return False

    def _ui_apply_editor_to_packs(self) -> None:
        """Apply current editor config to selected packs."""
        if not self.current_selected_packs:
            messagebox.showwarning("No Selection", "Please select one or more packs first.")
            return

        num_packs = len(self.current_selected_packs)
        result = messagebox.askyesno(
            "Confirm Overwrite",
            f"Overwrite configs for {num_packs} pack{'s' if num_packs > 1 else ''}?",
        )
        if not result:
            return

        # Capture the full editor config (txt2img/img2img/upscale/pipeline/randomization/etc.)
        editor_cfg = self._get_config_from_forms()
        if not editor_cfg:
            messagebox.showerror("Error", "Unable to read the current editor configuration.")
            return

        # Save in worker thread
        def save_worker():
            try:
                for pack in self.current_selected_packs:
                    self.config_service.save_pack_config(pack, editor_cfg)
                # Success callback on UI thread
                def _on_success():
                    messagebox.showinfo(
                        "Success", f"Applied to {num_packs} pack{'s' if num_packs > 1 else ''}."
                    )
                    self._reset_config_dirty_state()

                self.root.after(0, _on_success)
            except Exception as exc:
                error_msg = str(exc)
                # Error callback on UI thread
                self.root.after(
                    0, lambda: messagebox.showerror("Error", f"Failed to save configs: {error_msg}")
                )

        threading.Thread(target=save_worker, daemon=True).start()

    def _refresh_preset_dropdown(self) -> None:
        """Refresh the preset dropdown with current presets."""
        self.preset_combobox["values"] = self.config_service.list_presets()

    def _refresh_list_dropdown(self) -> None:
        """Refresh the list dropdown with current lists."""
        self.list_combobox["values"] = self.config_service.list_lists()

    def _ui_save_preset(self) -> None:
        """Save current editor config as a new preset."""
        name = simpledialog.askstring("Save Preset", "Enter preset name:")
        if not name:
            return
        if name in self.config_service.list_presets():
            if not messagebox.askyesno(
                "Overwrite Preset", f"Preset '{name}' already exists. Overwrite?"
            ):
                return
        editor_cfg = self.pipeline_controls_panel.get_settings()
        try:
            self.config_service.save_preset(name, editor_cfg, overwrite=True)
            self._refresh_preset_dropdown()
            messagebox.showinfo("Success", f"Preset '{name}' saved.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save preset: {e}")

    def _ui_delete_preset(self) -> None:
        """Delete the selected preset."""
        name = self.preset_combobox.get()
        if not name:
            messagebox.showwarning("No Selection", "Please select a preset to delete.")
            return
        if not messagebox.askyesno("Delete Preset", f"Delete preset '{name}'?"):
            return
        try:
            self.config_service.delete_preset(name)
            self._refresh_preset_dropdown()
            # Clear selection
            self.preset_combobox.set("")
            # If it was the current preset, revert banner
            if self.current_preset_name == name:
                self.current_preset_name = None
                if self.current_selected_packs:
                    self._update_config_source_banner("Using: Pack Config (view)")
                else:
                    self._update_config_source_banner("Using: Pack Config")
            messagebox.showinfo("Success", f"Preset '{name}' deleted.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete preset: {e}")

    def _ui_load_list(self) -> None:
        """Load selected list and set pack selection."""
        name = self.list_combobox.get()
        if not name:
            messagebox.showwarning("No Selection", "Please select a list to load.")
            return
        try:
            packs = self.config_service.load_list(name)
            if not packs:
                messagebox.showinfo("Empty List", f"List '{name}' has no packs saved.")
                return
            available = list(self.prompt_pack_panel.packs_listbox.get(0, tk.END))
            valid_packs = [p for p in packs if p in available]
            if not valid_packs:
                messagebox.showwarning(
                    "No Matching Packs",
                    f"None of the packs from '{name}' are available in this workspace.",
                )
                return
            self.prompt_pack_panel.set_selected_packs(valid_packs)
            try:
                self.root.update_idletasks()
            except Exception:
                pass
            selected_after = self.prompt_pack_panel.get_selected_packs()
            self.current_selected_packs = selected_after or valid_packs
            self.ctx.active_list = name
            messagebox.showinfo("Success", f"List '{name}' loaded ({len(valid_packs)} packs).")
            self._reset_config_dirty_state()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load list: {e}")

    def _ui_save_list(self) -> None:
        """Save current pack selection as a new list."""
        if not self.current_selected_packs:
            messagebox.showwarning("No Selection", "Please select packs to save as list.")
            return
        name = simpledialog.askstring("Save List", "Enter list name:")
        if not name:
            return
        if name in self.config_service.list_lists():
            if not messagebox.askyesno(
                "Overwrite List", f"List '{name}' already exists. Overwrite?"
            ):
                return
        try:
            self.config_service.save_list(name, self.current_selected_packs, overwrite=True)
            self.ctx.active_list = name
            self._refresh_list_dropdown()
            messagebox.showinfo(
                "Success", f"List '{name}' saved ({len(self.current_selected_packs)} packs)."
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save list: {e}")

    def _ui_overwrite_list(self) -> None:
        """Overwrite the current active list with current selection."""
        if not self.ctx.active_list:
            messagebox.showwarning(
                "No Active List", "No list is currently active. Use 'Save Selection as List' first."
            )
            return
        if not self.current_selected_packs:
            messagebox.showwarning("No Selection", "Please select packs to save.")
            return
        if not messagebox.askyesno(
            "Overwrite List", f"Overwrite list '{self.ctx.active_list}' with current selection?"
        ):
            return
        try:
            self.config_service.save_list(
                self.ctx.active_list, self.current_selected_packs, overwrite=True
            )
            messagebox.showinfo(
                "Success",
                f"List '{self.ctx.active_list}' updated ({len(self.current_selected_packs)} packs).",
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to overwrite list: {e}")

    def _ui_delete_list(self) -> None:
        """Delete the selected list."""
        name = self.list_combobox.get()
        if not name:
            messagebox.showwarning("No Selection", "Please select a list to delete.")
            return
        if not messagebox.askyesno("Delete List", f"Delete list '{name}'?"):
            return
        try:
            self.config_service.delete_list(name)
            self._refresh_list_dropdown()
            self.list_combobox.set("")
            if self.ctx.active_list == name:
                self.ctx.active_list = None
            messagebox.showinfo("Success", f"List '{name}' deleted.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete list: {e}")

    def _setup_theme(self):
        self.style.configure(
            "Dark.TCheckbutton",
            background=self.bg_color,
            foreground=self.fg_color,
            focuscolor="none",
            font=("Segoe UI", 9),
        )
        self.style.configure(
            "Dark.TRadiobutton",
            background=self.bg_color,
            foreground=self.fg_color,
            focuscolor="none",
            font=("Segoe UI", 9),
        )
        self.style.configure("Dark.TNotebook", background=self.bg_color, borderwidth=0)
        self.style.configure(
            "Dark.TNotebook.Tab",
            background=self.button_bg,
            foreground=self.fg_color,
            padding=[20, 8],
            borderwidth=0,
        )

        # Accent button styles for CTAs
        self.style.configure(
            "Accent.TButton",
            background="#0078d4",
            foreground=self.fg_color,
            borderwidth=1,
            focuscolor="none",
            font=("Segoe UI", 9, "bold"),
        )
        self.style.configure(
            "Danger.TButton",
            background="#dc3545",
            foreground=self.fg_color,
            borderwidth=1,
            focuscolor="none",
            font=("Segoe UI", 9, "bold"),
        )

        # Map states
        self.style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", self.entry_bg)],
            selectbackground=[("readonly", "#0078d4")],
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", "#106ebe"), ("pressed", "#005a9e")],
            foreground=[("active", self.fg_color)],
        )
        self.style.map(
            "Dark.TNotebook.Tab",
            background=[("selected", "#0078d4"), ("active", self.button_active)],
        )

    def _layout_panels(self):
        # Example layout for preset bar and dropdown
        preset_bar = ttk.Frame(self.root, style="Dark.TFrame")
        preset_bar.grid(row=0, column=0, sticky=tk.W)
        ttk.Label(preset_bar, text="Preset:", style="Dark.TLabel").grid(
            row=0, column=0, sticky=tk.W, padx=(2, 4)
        )
        self.preset_dropdown = ttk.Combobox(
            preset_bar,
            textvariable=self.preset_var,
            state="readonly",
            width=28,
            values=self.config_manager.list_presets(),
        )
        self.preset_dropdown.grid(row=0, column=1, sticky=tk.W)
        self.preset_dropdown.grid(row=0, column=1, sticky=tk.W)
        self.preset_dropdown.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_preset_dropdown_changed()
        )
        self._attach_tooltip(
            self.preset_dropdown,
            "Select a preset to load its settings into the active configuration (spans all tabs).",
        )

        apply_default_btn = ttk.Button(
            preset_bar,
            text="Apply Default",
            command=self._apply_default_to_selected_packs,
            width=14,
            style="Dark.TButton",
        )
        apply_default_btn.grid(row=0, column=2, padx=(8, 4))
        self._attach_tooltip(
            apply_default_btn,
            "Load the 'default' preset into the form (not saved until you click Save to Pack(s)).",
        )

        # Right-aligned action strip
        actions_strip = ttk.Frame(preset_bar, style="Dark.TFrame")
        actions_strip.grid(row=0, column=3, sticky=tk.E, padx=(10, 4))

        save_packs_btn = ttk.Button(
            actions_strip,
            text="Save to Pack(s)",
            command=self._save_config_to_packs,
            style="Accent.TButton",
            width=18,
        )
        save_packs_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            save_packs_btn,
            "Persist current configuration to selected pack(s). Single selection saves that pack; multi-selection saves all.",
        )

        save_as_btn = ttk.Button(
            actions_strip,
            text="Save As Preset…",
            command=self._save_preset_as,
            width=16,
        )
        save_as_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            save_as_btn, "Create a new preset from the current configuration state."
        )

        set_default_btn = ttk.Button(
            actions_strip,
            text="Set Default",
            command=self._set_as_default_preset,
            width=12,
        )
        set_default_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(set_default_btn, "Mark the selected preset as the startup default.")

        del_preset_btn = ttk.Button(
            actions_strip,
            text="Delete",
            command=self._delete_selected_preset,
            style="Danger.TButton",
            width=10,
        )
        del_preset_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            del_preset_btn, "Delete the selected preset (cannot delete 'default')."
        )

        # Notebook sits below preset bar

    def _build_randomization_tab(self, parent: tk.Widget) -> None:
        """Build the randomization tab UI and data bindings."""

        scroll_shell = ttk.Frame(parent, style="Dark.TFrame")
        scroll_shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 10))
        canvas, body = make_scrollable(scroll_shell, style="Dark.TFrame")
        self._register_scrollable_section("randomization", canvas, body)

        self._build_info_box(
            body,
            "Prompt Randomization & Aesthetic Tools",
            "Enable randomized prompt variations using AUTOMATIC1111-style syntax. "
            "Combine Prompt S/R rules, wildcard tokens, matrices, and optional aesthetic gradients.",
        ).pack(fill=tk.X, padx=10, pady=(0, 6))

        self.randomization_vars = {
            "enabled": tk.BooleanVar(value=False),
            "prompt_sr_enabled": tk.BooleanVar(value=False),
            "prompt_sr_mode": tk.StringVar(value="random"),
            "wildcards_enabled": tk.BooleanVar(value=False),
            "wildcard_mode": tk.StringVar(value="random"),
            "matrix_enabled": tk.BooleanVar(value=False),
            "matrix_mode": tk.StringVar(value="fanout"),
            "matrix_prompt_mode": tk.StringVar(value="replace"),
            "matrix_limit": tk.IntVar(value=8),
        }
        self.randomization_widgets = {}

        self.aesthetic_vars = {
            "enabled": tk.BooleanVar(value=False),
            "mode": tk.StringVar(value="script" if self.aesthetic_script_available else "prompt"),
            "weight": tk.DoubleVar(value=0.9),
            "steps": tk.IntVar(value=5),
            "learning_rate": tk.StringVar(value="0.0001"),
            "slerp": tk.BooleanVar(value=False),
            "slerp_angle": tk.DoubleVar(value=0.1),
            "text": tk.StringVar(value=""),
            "text_is_negative": tk.BooleanVar(value=False),
            "fallback_prompt": tk.StringVar(value=""),
        }
        self.aesthetic_widgets = {"all": [], "script": [], "prompt": []}

        master_frame = ttk.Frame(body, style="Dark.TFrame")
        master_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
        ttk.Checkbutton(
            master_frame,
            text="Enable randomization for the next run",
            variable=self.randomization_vars["enabled"],
            style="Dark.TCheckbutton",
            command=self._update_randomization_states,
        ).pack(side=tk.LEFT)

        ttk.Label(
            master_frame,
            text="Randomization expands prompts before the pipeline starts, so counts multiply per stage.",
            style="Dark.TLabel",
            wraplength=600,
        ).pack(side=tk.LEFT, padx=(10, 0))

        # Prompt S/R section
        sr_frame = ttk.LabelFrame(body, text="Prompt S/R", style="Dark.TLabelframe", padding=10)
        sr_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        sr_header = ttk.Frame(sr_frame, style="Dark.TFrame")
        sr_header.pack(fill=tk.X)
        ttk.Checkbutton(
            sr_header,
            text="Enable Prompt S/R replacements",
            variable=self.randomization_vars["prompt_sr_enabled"],
            style="Dark.TCheckbutton",
            command=self._update_randomization_states,
        ).pack(side=tk.LEFT)

        sr_mode_frame = ttk.Frame(sr_frame, style="Dark.TFrame")
        sr_mode_frame.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(sr_mode_frame, text="Selection mode:", style="Dark.TLabel").pack(side=tk.LEFT)
        ttk.Radiobutton(
            sr_mode_frame,
            text="Random per prompt",
            variable=self.randomization_vars["prompt_sr_mode"],
            value="random",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            sr_mode_frame,
            text="Round robin",
            variable=self.randomization_vars["prompt_sr_mode"],
            value="round_robin",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(
            sr_frame,
            text="Format: search term => replacement A | replacement B. One rule per line. "
            "Matches are case-sensitive and apply before wildcard/matrix expansion.",
            style="Dark.TLabel",
            wraplength=700,
        ).pack(fill=tk.X, pady=(2, 4))

        sr_text = scrolledtext.ScrolledText(sr_frame, height=6, wrap=tk.WORD)
        sr_text.pack(fill=tk.BOTH, expand=True)
        self.randomization_widgets["prompt_sr_text"] = sr_text
        enable_mousewheel(sr_text)
        # Persist on edits
        self._bind_autosave_text(sr_text)

        # Wildcards section
        wildcard_frame = ttk.LabelFrame(
            body, text="Wildcards (__token__ syntax)", style="Dark.TFrame", padding=10
        )
        wildcard_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        wildcard_header = ttk.Frame(wildcard_frame, style="Dark.TFrame")
        wildcard_header.pack(fill=tk.X)
        ttk.Checkbutton(
            wildcard_header,
            text="Enable wildcard replacements",
            variable=self.randomization_vars["wildcards_enabled"],
            style="Dark.TCheckbutton",
            command=self._update_randomization_states,
        ).pack(side=tk.LEFT)

        ttk.Label(
            wildcard_frame,
            text="Use __token__ in your prompts (same as AUTOMATIC1111 wildcards). "
            "Provide values below using token: option1 | option2.",
            style="Dark.TLabel",
            wraplength=700,
        ).pack(fill=tk.X, pady=(4, 4))

        wildcard_mode_frame = ttk.Frame(wildcard_frame, style="Dark.TFrame")
        wildcard_mode_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(wildcard_mode_frame, text="Selection mode:", style="Dark.TLabel").pack(
            side=tk.LEFT
        )
        ttk.Radiobutton(
            wildcard_mode_frame,
            text="Random per prompt",
            variable=self.randomization_vars["wildcard_mode"],
            value="random",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            wildcard_mode_frame,
            text="Sequential (loop through values)",
            variable=self.randomization_vars["wildcard_mode"],
            value="sequential",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))

        wildcard_text = scrolledtext.ScrolledText(wildcard_frame, height=6, wrap=tk.WORD)
        wildcard_text.pack(fill=tk.BOTH, expand=True)
        self.randomization_widgets["wildcard_text"] = wildcard_text
        enable_mousewheel(wildcard_text)
        self._bind_autosave_text(wildcard_text)

        # Prompt matrix section
        matrix_frame = ttk.LabelFrame(
            body, text="Prompt Matrix ([[Slot]] syntax)", style="Dark.TFrame", padding=10
        )
        matrix_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        matrix_header = ttk.Frame(matrix_frame, style="Dark.TFrame")
        matrix_header.pack(fill=tk.X)
        ttk.Checkbutton(
            matrix_header,
            text="Enable prompt matrix expansion",
            variable=self.randomization_vars["matrix_enabled"],
            style="Dark.TCheckbutton",
            command=self._update_randomization_states,
        ).pack(side=tk.LEFT)

        matrix_mode_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
        matrix_mode_frame.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(matrix_mode_frame, text="Expansion mode:", style="Dark.TLabel").pack(side=tk.LEFT)
        ttk.Radiobutton(
            matrix_mode_frame,
            text="Fan-out (all combos)",
            variable=self.randomization_vars["matrix_mode"],
            value="fanout",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            matrix_mode_frame,
            text="Rotate per prompt",
            variable=self.randomization_vars["matrix_mode"],
            value="rotate",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))

        # Prompt mode: how base_prompt relates to pack prompt
        prompt_mode_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
        prompt_mode_frame.pack(fill=tk.X, pady=(2, 2))
        ttk.Label(prompt_mode_frame, text="Prompt mode:", style="Dark.TLabel").pack(side=tk.LEFT)
        ttk.Radiobutton(
            prompt_mode_frame,
            text="Replace pack",
            variable=self.randomization_vars["matrix_prompt_mode"],
            value="replace",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            prompt_mode_frame,
            text="Append to pack",
            variable=self.randomization_vars["matrix_prompt_mode"],
            value="append",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            prompt_mode_frame,
            text="Prepend before pack",
            variable=self.randomization_vars["matrix_prompt_mode"],
            value="prepend",
            style="Dark.TRadiobutton",
        ).pack(side=tk.LEFT, padx=(8, 0))

        limit_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
        limit_frame.pack(fill=tk.X, pady=(2, 4))
        ttk.Label(limit_frame, text="Combination cap:", style="Dark.TLabel").pack(side=tk.LEFT)
        ttk.Spinbox(
            limit_frame,
            from_=1,
            to=64,
            width=5,
            textvariable=self.randomization_vars["matrix_limit"],
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(
            limit_frame,
            text="(prevents runaway combinations when many slots are defined)",
            style="Dark.TLabel",
        ).pack(side=tk.LEFT, padx=(6, 0))

        # Base prompt field
        base_prompt_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
        base_prompt_frame.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(
            base_prompt_frame,
            text="Base prompt:",
            style="Dark.TLabel",
            width=14,
        ).pack(side=tk.LEFT)
        base_prompt_entry = ttk.Entry(base_prompt_frame)
        base_prompt_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        self.randomization_widgets["matrix_base_prompt"] = base_prompt_entry
        self._bind_autosave_entry(base_prompt_entry)

        ttk.Label(
            matrix_frame,
            text="Add [[Slot Name]] markers in your base prompt. Define combination slots below:",
            style="Dark.TLabel",
            wraplength=700,
        ).pack(fill=tk.X, pady=(2, 4))

        # Scrollable container for slot rows
        slots_container = ttk.Frame(matrix_frame, style="Dark.TFrame")
        slots_container.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        slots_canvas = tk.Canvas(
            slots_container,
            bg="#2b2b2b",
            highlightthickness=0,
            height=150,
        )
        slots_scrollbar = ttk.Scrollbar(
            slots_container,
            orient=tk.VERTICAL,
            command=slots_canvas.yview,
        )
        slots_scrollable_frame = ttk.Frame(slots_canvas, style="Dark.TFrame")

        slots_scrollable_frame.bind(
            "<Configure>",
            lambda e: slots_canvas.configure(scrollregion=slots_canvas.bbox("all")),
        )

        slots_canvas.create_window((0, 0), window=slots_scrollable_frame, anchor="nw")
        slots_canvas.configure(yscrollcommand=slots_scrollbar.set)

        slots_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        slots_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.randomization_widgets["matrix_slots_frame"] = slots_scrollable_frame
        self.randomization_widgets["matrix_slots_canvas"] = slots_canvas
        self.randomization_widgets["matrix_slot_rows"] = []

        # Add slot button
        add_slot_btn = ttk.Button(
            matrix_frame,
            text="+ Add Combination Slot",
            command=self._add_matrix_slot_row,
        )
        add_slot_btn.pack(fill=tk.X, pady=(0, 4))

        # Legacy text view (hidden by default, for advanced users)
        legacy_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
        legacy_frame.pack(fill=tk.BOTH, expand=True)

        self.randomization_vars["matrix_show_legacy"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            legacy_frame,
            text="Show advanced text editor (legacy format)",
            variable=self.randomization_vars["matrix_show_legacy"],
            style="Dark.TCheckbutton",
            command=self._toggle_matrix_legacy_view,
        ).pack(fill=tk.X, pady=(0, 2))

        legacy_text_container = ttk.Frame(legacy_frame, style="Dark.TFrame")
        self.randomization_widgets["matrix_legacy_container"] = legacy_text_container

        matrix_text = scrolledtext.ScrolledText(
            legacy_text_container,
            height=6,
            wrap=tk.WORD,
        )
        matrix_text.pack(fill=tk.BOTH, expand=True)
        self.randomization_widgets["matrix_text"] = matrix_text
        enable_mousewheel(matrix_text)
        self._bind_autosave_text(matrix_text)

        # Aesthetic gradient section
        aesthetic_frame = ttk.LabelFrame(
            body, text="Aesthetic Gradient", style="Dark.TLabelframe", padding=10
        )
        aesthetic_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        aesthetic_header = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
        aesthetic_header.pack(fill=tk.X)
        ttk.Checkbutton(
            aesthetic_header,
            text="Enable aesthetic gradient adjustments",
            variable=self.aesthetic_vars["enabled"],
            style="Dark.TCheckbutton",
            command=self._update_aesthetic_states,
        ).pack(side=tk.LEFT)

        ttk.Label(
            aesthetic_header,
            textvariable=self.aesthetic_status_var,
            style="Dark.TLabel",
            wraplength=400,
        ).pack(side=tk.LEFT, padx=(12, 0))

        mode_frame = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
        mode_frame.pack(fill=tk.X, pady=(6, 4))
        ttk.Label(mode_frame, text="Mode:", style="Dark.TLabel").pack(side=tk.LEFT)
        script_radio = ttk.Radiobutton(
            mode_frame,
            text="Use Aesthetic Gradient script",
            variable=self.aesthetic_vars["mode"],
            value="script",
            style="Dark.TRadiobutton",
            state=tk.NORMAL if self.aesthetic_script_available else tk.DISABLED,
            command=self._update_aesthetic_states,
        )
        script_radio.pack(side=tk.LEFT, padx=(6, 0))
        prompt_radio = ttk.Radiobutton(
            mode_frame,
            text="Fallback prompt / embedding",
            variable=self.aesthetic_vars["mode"],
            value="prompt",
            style="Dark.TRadiobutton",
            command=self._update_aesthetic_states,
        )
        prompt_radio.pack(side=tk.LEFT, padx=(6, 0))
        self.aesthetic_widgets["all"].extend([script_radio, prompt_radio])

        embedding_row = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
        embedding_row.pack(fill=tk.X, pady=(2, 4))
        ttk.Label(embedding_row, text="Embedding:", style="Dark.TLabel", width=14).pack(
            side=tk.LEFT
        )
        self.aesthetic_embedding_combo = ttk.Combobox(
            embedding_row,
            textvariable=self.aesthetic_embedding_var,
            state="readonly",
            width=24,
            values=self.aesthetic_embeddings,
        )
        self.aesthetic_embedding_combo.pack(side=tk.LEFT, padx=(4, 0))
        refresh_btn = ttk.Button(
            embedding_row, text="Refresh", command=self._refresh_aesthetic_embeddings, width=8
        )
        refresh_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.aesthetic_widgets["all"].extend([self.aesthetic_embedding_combo, refresh_btn])

        script_box = ttk.LabelFrame(
            aesthetic_frame, text="Script Parameters", style="Dark.TLabelframe", padding=6
        )
        script_box.pack(fill=tk.X, pady=(4, 4))

        weight_row = ttk.Frame(script_box, style="Dark.TFrame")
        weight_row.pack(fill=tk.X, pady=2)
        ttk.Label(weight_row, text="Weight:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
        weight_slider = EnhancedSlider(
            weight_row,
            from_=0.0,
            to=1.0,
            resolution=0.01,
            variable=self.aesthetic_vars["weight"],
            width=140,
        )
        weight_slider.pack(side=tk.LEFT, padx=(4, 10))

        steps_row = ttk.Frame(script_box, style="Dark.TFrame")
        steps_row.pack(fill=tk.X, pady=2)
        ttk.Label(steps_row, text="Steps:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
        steps_slider = EnhancedSlider(
            steps_row,
            from_=0,
            to=50,
            resolution=1,
            variable=self.aesthetic_vars["steps"],
            width=140,
        )
        steps_slider.pack(side=tk.LEFT, padx=(4, 10))

        lr_row = ttk.Frame(script_box, style="Dark.TFrame")
        lr_row.pack(fill=tk.X, pady=2)
        ttk.Label(lr_row, text="Learning rate:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
        lr_entry = ttk.Entry(lr_row, textvariable=self.aesthetic_vars["learning_rate"], width=12)
        lr_entry.pack(side=tk.LEFT, padx=(4, 10))

        slerp_row = ttk.Frame(script_box, style="Dark.TFrame")
        slerp_row.pack(fill=tk.X, pady=2)
        slerp_check = ttk.Checkbutton(
            slerp_row,
            text="Enable slerp interpolation",
            variable=self.aesthetic_vars["slerp"],
            style="Dark.TCheckbutton",
            command=self._update_aesthetic_states,
        )
        slerp_check.pack(side=tk.LEFT)
        ttk.Label(slerp_row, text="Angle:", style="Dark.TLabel", width=8).pack(
            side=tk.LEFT, padx=(10, 0)
        )
        slerp_angle_slider = EnhancedSlider(
            slerp_row,
            from_=0.0,
            to=1.0,
            resolution=0.01,
            variable=self.aesthetic_vars["slerp_angle"],
            width=120,
        )
        slerp_angle_slider.pack(side=tk.LEFT, padx=(4, 0))

        text_row = ttk.Frame(script_box, style="Dark.TFrame")
        text_row.pack(fill=tk.X, pady=2)
        ttk.Label(text_row, text="Text prompt:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
        text_entry = ttk.Entry(text_row, textvariable=self.aesthetic_vars["text"])
        text_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        text_neg_check = ttk.Checkbutton(
            text_row,
            text="Apply as negative text",
            variable=self.aesthetic_vars["text_is_negative"],
            style="Dark.TCheckbutton",
        )
        text_neg_check.pack(side=tk.LEFT, padx=(6, 0))

        self.aesthetic_widgets["script"].extend(
            [
                weight_slider,
                steps_slider,
                lr_entry,
                slerp_check,
                slerp_angle_slider,
                text_entry,
                text_neg_check,
            ]
        )

        prompt_box = ttk.LabelFrame(
            aesthetic_frame, text="Fallback Prompt Injection", style="Dark.TLabelframe", padding=6
        )
        prompt_box.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(
            prompt_box,
            text="Optional phrase appended to the positive prompt when using fallback mode.",
            style="Dark.TLabel",
            wraplength=700,
        ).pack(fill=tk.X, pady=(0, 4))
        fallback_entry = ttk.Entry(prompt_box, textvariable=self.aesthetic_vars["fallback_prompt"])
        fallback_entry.pack(fill=tk.X, padx=2)

        self.aesthetic_widgets["prompt"].append(fallback_entry)
        self.aesthetic_widgets["all"].append(fallback_entry)
        self.aesthetic_widgets["all"].extend(
            [
                weight_slider,
                steps_slider,
                lr_entry,
                slerp_check,
                slerp_angle_slider,
                text_entry,
                text_neg_check,
            ]
        )

        for key in ("enabled", "prompt_sr_enabled", "wildcards_enabled", "matrix_enabled"):
            try:

                def _rand_trace_cb(*_args, _k=key):
                    self._update_randomization_states()
                    if _k.endswith("enabled"):
                        self._autosave_preferences_if_needed()

                self.randomization_vars[key].trace_add("write", _rand_trace_cb)
            except Exception:
                pass
        # Persist changes to modes/limits too
        for key in (
            "prompt_sr_mode",
            "wildcard_mode",
            "matrix_mode",
            "matrix_prompt_mode",
            "matrix_limit",
        ):
            try:
                self.randomization_vars[key].trace_add(
                    "write", lambda *_: self._autosave_preferences_if_needed()
                )
            except Exception:
                pass

        try:
            self.aesthetic_vars["enabled"].trace_add(
                "write", lambda *_: self._aesthetic_autosave_handler()
            )
            self.aesthetic_vars["mode"].trace_add(
                "write", lambda *_: self._aesthetic_autosave_handler()
            )
            self.aesthetic_vars["slerp"].trace_add(
                "write", lambda *_: self._aesthetic_autosave_handler()
            )
            # Also persist other aesthetic fields on change
            for _k, _var in self.aesthetic_vars.items():
                try:
                    _var.trace_add("write", lambda *_: self._autosave_preferences_if_needed())
                except Exception:
                    pass
        except Exception:
            pass

        self._update_randomization_states()
        self._refresh_aesthetic_embeddings()
        self._update_aesthetic_states()

    def _update_randomization_states(self) -> None:
        """Enable/disable randomization widgets based on current toggles."""

        vars_dict = getattr(self, "randomization_vars", None)
        widgets = getattr(self, "randomization_widgets", None)
        if not vars_dict or not widgets:
            return

        master = bool(vars_dict.get("enabled", tk.BooleanVar(value=False)).get())
        section_enabled = {
            "prompt_sr_text": master
            and bool(vars_dict.get("prompt_sr_enabled", tk.BooleanVar()).get()),
            "wildcard_text": master
            and bool(vars_dict.get("wildcards_enabled", tk.BooleanVar()).get()),
            "matrix_text": master and bool(vars_dict.get("matrix_enabled", tk.BooleanVar()).get()),
        }

        for key, widget in widgets.items():
            if widget is None or isinstance(widget, list):
                continue
            state = tk.NORMAL if section_enabled.get(key, master) else tk.DISABLED
            try:
                widget.configure(state=state)
            except (tk.TclError, AttributeError):
                pass
        # Throttled autosave to keep last_settings.json aligned with UI
        self._autosave_preferences_if_needed()

    def _autosave_preferences_if_needed(self, force: bool = False) -> None:
        """Autosave preferences (including randomization enabled flag) with 2s throttle."""
        if not getattr(self, "_preferences_ready", False) and not force:
            return
        now = time.time()
        last = getattr(self, "_last_pref_autosave", 0.0)
        if not force and now - last < 2.0:
            return
        self._last_pref_autosave = now
        try:
            prefs = self._collect_preferences()
            if self.preferences_manager.save_preferences(prefs):
                self.preferences = prefs
        except Exception:
            pass

    def _bind_autosave_text(self, widget: tk.Text) -> None:
        """Bind common events on a Text widget to autosave preferences (throttled)."""
        try:
            widget.bind("<KeyRelease>", lambda _e: self._autosave_preferences_if_needed())
            widget.bind("<FocusOut>", lambda _e: self._autosave_preferences_if_needed())
        except Exception:
            pass

    def _bind_autosave_entry(self, widget: tk.Entry) -> None:
        """Bind common events on an Entry widget to autosave preferences (throttled)."""
        try:
            widget.bind("<KeyRelease>", lambda _e: self._autosave_preferences_if_needed())
            widget.bind("<FocusOut>", lambda _e: self._autosave_preferences_if_needed())
        except Exception:
            pass

    def _aesthetic_autosave_handler(self) -> None:
        """Handler for aesthetic state changes that also triggers autosave."""
        self._update_aesthetic_states()
        self._autosave_preferences_if_needed()

    def _get_randomization_text(self, key: str) -> str:
        """Return trimmed contents of a randomization text widget."""

        widget = self.randomization_widgets.get(key)
        if widget is None:
            return ""
        try:
            current_state = widget["state"]
        except (tk.TclError, KeyError):
            current_state = tk.NORMAL

        try:
            if current_state == tk.DISABLED:
                widget.configure(state=tk.NORMAL)
                value = widget.get("1.0", tk.END)
                widget.configure(state=tk.DISABLED)
            else:
                value = widget.get("1.0", tk.END)
        except tk.TclError:
            value = ""
        return value.strip()

    def _set_randomization_text(self, key: str, value: str) -> None:
        """Populate a randomization text widget with new content."""

        widget = self.randomization_widgets.get(key)
        if widget is None:
            return
        try:
            current_state = widget["state"]
        except (tk.TclError, KeyError):
            current_state = tk.NORMAL

        try:
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            if value:
                widget.insert(tk.END, value)
        except tk.TclError:
            pass
        finally:
            try:
                widget.configure(state=current_state)
            except tk.TclError:
                pass

    def _update_aesthetic_states(self) -> None:
        """Enable/disable aesthetic widgets based on mode and availability."""

        vars_dict = getattr(self, "aesthetic_vars", None)
        widgets = getattr(self, "aesthetic_widgets", None)
        if not vars_dict or not widgets:
            return

        enabled = bool(vars_dict.get("enabled", tk.BooleanVar(value=False)).get())
        mode = vars_dict.get("mode", tk.StringVar(value="prompt")).get()
        if mode == "script" and not self.aesthetic_script_available:
            mode = "prompt"
            vars_dict["mode"].set("prompt")

        def set_state(target_widgets: list[tk.Widget], active: bool) -> None:
            for widget in target_widgets:
                if widget is None:
                    continue
                state = tk.NORMAL if active else tk.DISABLED
                try:
                    widget.configure(state=state)
                except (tk.TclError, AttributeError):
                    if hasattr(widget, "configure_state"):
                        try:
                            widget.configure_state("normal" if active else "disabled")
                        except Exception:
                            continue

        set_state(widgets.get("all", []), enabled)
        set_state(widgets.get("script", []), enabled and mode == "script")
        set_state(widgets.get("prompt", []), enabled and mode == "prompt")

        if self.aesthetic_script_available:
            status = "Aesthetic extension detected"
        else:
            status = "Extension not detected – fallback mode only"
        if len(self.aesthetic_embeddings) <= 1:
            status += " (no embeddings found)"
        self.aesthetic_status_var.set(status)

    def _detect_aesthetic_extension_root(self):
        """Locate the Aesthetic Gradient extension directory if present."""

        candidates: list[Path] = []
        env_root = os.environ.get("WEBUI_ROOT")
        if env_root:
            candidates.append(Path(env_root))
        candidates.append(Path.home() / "stable-diffusion-webui")
        repo_candidate = Path(__file__).resolve().parents[3] / "stable-diffusion-webui"
        candidates.append(repo_candidate)
        local_candidate = Path("..") / "stable-diffusion-webui"
        candidates.append(local_candidate.resolve())

        detected, extension_dir = detect_aesthetic_extension(candidates)
        if detected and extension_dir:
            return True, extension_dir
        return False, None

    def _refresh_aesthetic_embeddings(self, *_):
        """Reload available aesthetic embedding names from disk."""

        embeddings = ["None"]
        if self.aesthetic_extension_root:
            embed_dir = self.aesthetic_extension_root / "aesthetic_embeddings"
            if embed_dir.exists():
                for file in sorted(embed_dir.glob("*.pt")):
                    embeddings.append(file.stem)
        self.aesthetic_embeddings = sorted(
            dict.fromkeys(embeddings), key=lambda name: (name != "None", name.lower())
        )

        if self.aesthetic_embedding_var.get() not in self.aesthetic_embeddings:
            self.aesthetic_embedding_var.set("None")

        if hasattr(self, "aesthetic_embedding_combo"):
            try:
                self.aesthetic_embedding_combo["values"] = self.aesthetic_embeddings
            except Exception:
                pass

        if self.aesthetic_script_available:
            status = "Aesthetic extension detected"
        else:
            status = "Extension not detected – fallback mode only"
        if len(self.aesthetic_embeddings) <= 1:
            status += " (no embeddings found)"
        self.aesthetic_status_var.set(status)

    def _collect_randomization_config(self) -> dict[str, Any]:
        """Collect randomization settings into a serializable dict."""

        vars_dict = getattr(self, "randomization_vars", None)
        if not vars_dict:
            return {}

        sr_text = self._get_randomization_text("prompt_sr_text")
        wildcard_text = self._get_randomization_text("wildcard_text")

        # Collect matrix data from UI fields (not legacy text)
        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
        base_prompt = base_prompt_widget.get() if base_prompt_widget else ""

        matrix_slots = []
        for row in self.randomization_widgets.get("matrix_slot_rows", []):
            name = row["name_entry"].get().strip()
            values_text = row["values_entry"].get().strip()
            if name and values_text:
                values = [v.strip() for v in values_text.split("|") if v.strip()]
                if values:
                    matrix_slots.append({"name": name, "values": values})

        # Build raw_text for backward compatibility
        matrix_raw_lines = []
        if base_prompt:
            matrix_raw_lines.append(f"# Base: {base_prompt}")
        matrix_raw_lines.append(self._format_matrix_lines(matrix_slots))
        matrix_raw_text = "\n".join(matrix_raw_lines)

        return {
            "enabled": bool(vars_dict["enabled"].get()),
            "prompt_sr": {
                "enabled": bool(vars_dict["prompt_sr_enabled"].get()),
                "mode": vars_dict["prompt_sr_mode"].get(),
                "rules": self._parse_prompt_sr_rules(sr_text),
                "raw_text": sr_text,
            },
            "wildcards": {
                "enabled": bool(vars_dict["wildcards_enabled"].get()),
                "mode": vars_dict["wildcard_mode"].get(),
                "tokens": self._parse_token_lines(wildcard_text),
                "raw_text": wildcard_text,
            },
            "matrix": {
                "enabled": bool(vars_dict["matrix_enabled"].get()),
                "mode": vars_dict["matrix_mode"].get(),
                "prompt_mode": vars_dict["matrix_prompt_mode"].get(),
                "limit": int(vars_dict["matrix_limit"].get() or 0),
                "slots": matrix_slots,
                "raw_text": matrix_raw_text,
                "base_prompt": base_prompt,
            },
        }

    def _load_randomization_config(self, config: dict[str, Any]) -> None:
        """Populate randomization UI from configuration values."""

        vars_dict = getattr(self, "randomization_vars", None)
        if not vars_dict:
            return

        try:
            data = (config or {}).get("randomization", {})
            vars_dict["enabled"].set(bool(data.get("enabled", False)))

            sr = data.get("prompt_sr", {})
            vars_dict["prompt_sr_enabled"].set(bool(sr.get("enabled", False)))
            vars_dict["prompt_sr_mode"].set(sr.get("mode", "random"))
            sr_text = sr.get("raw_text") or self._format_prompt_sr_rules(sr.get("rules", []))
            self._set_randomization_text("prompt_sr_text", sr_text)

            wildcards = data.get("wildcards", {})
            vars_dict["wildcards_enabled"].set(bool(wildcards.get("enabled", False)))
            vars_dict["wildcard_mode"].set(wildcards.get("mode", "random"))
            wildcard_text = wildcards.get("raw_text") or self._format_token_lines(
                wildcards.get("tokens", [])
            )
            self._set_randomization_text("wildcard_text", wildcard_text)

            matrix = data.get("matrix", {})
            vars_dict["matrix_enabled"].set(bool(matrix.get("enabled", False)))
            vars_dict["matrix_mode"].set(matrix.get("mode", "fanout"))
            vars_dict["matrix_prompt_mode"].set(matrix.get("prompt_mode", "replace"))
            vars_dict["matrix_limit"].set(int(matrix.get("limit", 8)))

            base_prompt = matrix.get("base_prompt", "")
            base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
            if base_prompt_widget:
                base_prompt_widget.delete(0, tk.END)
                base_prompt_widget.insert(0, base_prompt)

            slots = matrix.get("slots", [])
            self._clear_matrix_slot_rows()
            for slot in slots:
                name = slot.get("name", "")
                values = slot.get("values", [])
                if name and values:
                    values_str = " | ".join(values)
                    self._add_matrix_slot_row(name, values_str)

            matrix_text = matrix.get("raw_text") or self._format_matrix_lines(slots)
            self._set_randomization_text("matrix_text", matrix_text)

            self._update_randomization_states()
        except Exception as exc:
            logger.error("Failed to load randomization config: %s", exc)

    def _collect_aesthetic_config(self) -> dict[str, Any]:
        """Collect aesthetic gradient settings."""

        vars_dict = getattr(self, "aesthetic_vars", None)
        if not vars_dict:
            return {}

        mode = vars_dict["mode"].get()
        if mode == "script" and not self.aesthetic_script_available:
            mode = "prompt"

        def _safe_float(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        config = {
            "enabled": bool(vars_dict["enabled"].get()),
            "mode": mode,
            "weight": _safe_float(vars_dict["weight"].get(), 0.9),
            "steps": int(vars_dict["steps"].get() or 0),
            "learning_rate": _safe_float(vars_dict["learning_rate"].get(), 0.0001),
            "slerp": bool(vars_dict["slerp"].get()),
            "slerp_angle": _safe_float(vars_dict["slerp_angle"].get(), 0.1),
            "embedding": self.aesthetic_embedding_var.get() or "None",
            "text": vars_dict["text"].get().strip(),
            "text_is_negative": bool(vars_dict["text_is_negative"].get()),
            "fallback_prompt": vars_dict["fallback_prompt"].get().strip(),
        }
        return config

    def _load_aesthetic_config(self, config: dict[str, Any]) -> None:
        """Populate aesthetic gradient UI from stored configuration."""

        vars_dict = getattr(self, "aesthetic_vars", None)
        if not vars_dict:
            return

        data = (config or {}).get("aesthetic", {})
        vars_dict["enabled"].set(bool(data.get("enabled", False)))
        desired_mode = data.get("mode", "script")
        if desired_mode == "script" and not self.aesthetic_script_available:
            desired_mode = "prompt"
        vars_dict["mode"].set(desired_mode)
        vars_dict["weight"].set(float(data.get("weight", 0.9)))
        vars_dict["steps"].set(int(data.get("steps", 5)))
        vars_dict["learning_rate"].set(str(data.get("learning_rate", 0.0001)))
        vars_dict["slerp"].set(bool(data.get("slerp", False)))
        vars_dict["slerp_angle"].set(float(data.get("slerp_angle", 0.1)))
        vars_dict["text"].set(data.get("text", ""))
        vars_dict["text_is_negative"].set(bool(data.get("text_is_negative", False)))
        vars_dict["fallback_prompt"].set(data.get("fallback_prompt", ""))

        embedding = data.get("embedding", "None") or "None"
        if embedding not in self.aesthetic_embeddings:
            embedding = "None"
        self.aesthetic_embedding_var.set(embedding)
        self._update_aesthetic_states()

    @staticmethod
    def _parse_prompt_sr_rules(text: str) -> list[dict[str, Any]]:
        """Parse Prompt S/R rule definitions."""

        rules: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=>" not in line:
                continue
            search, replacements = line.split("=>", 1)
            search = search.strip()
            replacement_values = [item.strip() for item in replacements.split("|") if item.strip()]
            if search and replacement_values:
                rules.append({"search": search, "replacements": replacement_values})
        return rules

    @staticmethod
    def _format_prompt_sr_rules(rules: list[dict[str, Any]]) -> str:
        """Format Prompt S/R rules back into editable text."""

        lines: list[str] = []
        for entry in rules or []:
            search = entry.get("search", "")
            replacements = entry.get("replacements", [])
            if not search or not replacements:
                continue
            lines.append(f"{search} => {' | '.join(replacements)}")
        return "\n".join(lines)

    @staticmethod
    def _parse_token_lines(text: str) -> list[dict[str, Any]]:
        """Parse wildcard token definitions."""

        tokens: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            token, values = line.split(":", 1)
            base_name = token.strip().strip("_")
            value_list = [item.strip() for item in values.split("|") if item.strip()]
            if base_name and value_list:
                tokens.append({"token": f"__{base_name}__", "values": value_list})
        return tokens

    @staticmethod
    def _format_token_lines(tokens: list[dict[str, Any]]) -> str:
        """Format wildcard tokens back into editable text."""

        lines: list[str] = []
        for token in tokens or []:
            name = token.get("token", "")
            values = token.get("values", [])
            if not name or not values:
                continue
            stripped_name = (
                name.strip("_") if name.startswith("__") and name.endswith("__") else name
            )
            lines.append(f"{stripped_name}: {' | '.join(values)}")
        return "\n".join(lines)

    @staticmethod
    def _parse_matrix_lines(text: str) -> list[dict[str, Any]]:
        """Parse matrix slot definitions."""

        slots: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            slot, values = line.split(":", 1)
            slot_name = slot.strip()
            value_list = [item.strip() for item in values.split("|") if item.strip()]
            if slot_name and value_list:
                slots.append({"name": slot_name, "values": value_list})
        return slots

    @staticmethod
    def _format_matrix_lines(slots: list[dict[str, Any]]) -> str:
        """Format matrix slots back into editable text."""

        lines: list[str] = []
        for slot in slots or []:
            name = slot.get("name", "")
            values = slot.get("values", [])
            if not name or not values:
                continue
            lines.append(f"{name}: {' | '.join(values)}")
        return "\n".join(lines)

    def _add_matrix_slot_row(self, slot_name: str = "", slot_values: str = "") -> None:
        """Add a new matrix slot row to the UI."""

        slots_frame = self.randomization_widgets.get("matrix_slots_frame")
        if not slots_frame:
            return

        row_frame = ttk.Frame(slots_frame, style="Dark.TFrame")
        row_frame.pack(fill=tk.X, pady=2)

        # Slot name entry
        ttk.Label(row_frame, text="Slot:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)
        name_entry = ttk.Entry(row_frame, width=15)
        name_entry.pack(side=tk.LEFT, padx=(2, 4))
        if slot_name:
            name_entry.insert(0, slot_name)
        # Autosave when editing slot name
        self._bind_autosave_entry(name_entry)

        # Values entry
        ttk.Label(row_frame, text="Options (| separated):", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(4, 2)
        )
        values_entry = ttk.Entry(row_frame)
        values_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 4))
        if slot_values:
            values_entry.insert(0, slot_values)
        # Autosave when editing slot values
        self._bind_autosave_entry(values_entry)

        # Remove button
        remove_btn = ttk.Button(
            row_frame,
            text="−",
            width=3,
            command=lambda: self._remove_matrix_slot_row(row_frame),
        )
        remove_btn.pack(side=tk.LEFT)

        # Store row data
        row_data = {
            "frame": row_frame,
            "name_entry": name_entry,
            "values_entry": values_entry,
        }
        self.randomization_widgets["matrix_slot_rows"].append(row_data)

        # Update scroll region
        canvas = self.randomization_widgets.get("matrix_slots_canvas")
        if canvas:
            canvas.configure(scrollregion=canvas.bbox("all"))

    def _remove_matrix_slot_row(self, row_frame: tk.Widget) -> None:
        """Remove a matrix slot row from the UI."""

        slot_rows = self.randomization_widgets.get("matrix_slot_rows", [])
        self.randomization_widgets["matrix_slot_rows"] = [
            row for row in slot_rows if row["frame"] != row_frame
        ]
        row_frame.destroy()

        # Update scroll region
        canvas = self.randomization_widgets.get("matrix_slots_canvas")
        if canvas:
            canvas.configure(scrollregion=canvas.bbox("all"))

    def _clear_matrix_slot_rows(self) -> None:
        """Clear all matrix slot rows from the UI."""

        for row in self.randomization_widgets.get("matrix_slot_rows", []):
            row["frame"].destroy()
        self.randomization_widgets["matrix_slot_rows"] = []

        # Update scroll region
        canvas = self.randomization_widgets.get("matrix_slots_canvas")
        if canvas:
            canvas.configure(scrollregion=canvas.bbox("all"))

    def _toggle_matrix_legacy_view(self) -> None:
        """Toggle between modern UI and legacy text editor for matrix config."""

        show_legacy = self.randomization_vars.get("matrix_show_legacy", tk.BooleanVar()).get()
        legacy_container = self.randomization_widgets.get("matrix_legacy_container")

        if legacy_container:
            if show_legacy:
                # Sync from UI to legacy text before showing
                self._sync_matrix_ui_to_text()
                legacy_container.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
            else:
                # Sync from legacy text to UI before hiding
                self._sync_matrix_text_to_ui()
                legacy_container.pack_forget()

    def _sync_matrix_ui_to_text(self) -> None:
        """Sync matrix UI fields to the legacy text widget."""

        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
        base_prompt = base_prompt_widget.get() if base_prompt_widget else ""

        slots = []
        for row in self.randomization_widgets.get("matrix_slot_rows", []):
            name = row["name_entry"].get().strip()
            values_text = row["values_entry"].get().strip()
            if name and values_text:
                slots.append(
                    {
                        "name": name,
                        "values": [v.strip() for v in values_text.split("|") if v.strip()],
                    }
                )

        # Build legacy format: base prompt on first line, then slots
        lines = []
        if base_prompt:
            lines.append(f"# Base: {base_prompt}")
        lines.append(self._format_matrix_lines(slots))

        matrix_text = self.randomization_widgets.get("matrix_text")
        if matrix_text:
            matrix_text.delete("1.0", tk.END)
            matrix_text.insert("1.0", "\n".join(lines))

    def _sync_matrix_text_to_ui(self) -> None:
        """Sync legacy text widget to matrix UI fields."""

        matrix_text = self.randomization_widgets.get("matrix_text")
        if not matrix_text:
            return

        text = matrix_text.get("1.0", tk.END).strip()
        lines = text.splitlines()

        # Check for base prompt marker
        base_prompt = ""
        slot_lines = []
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("# Base:"):
                base_prompt = line_stripped[7:].strip()
            elif line_stripped and not line_stripped.startswith("#"):
                slot_lines.append(line_stripped)

        # Update base prompt
        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
        if base_prompt_widget:
            base_prompt_widget.delete(0, tk.END)
            base_prompt_widget.insert(0, base_prompt)

        # Parse slots and rebuild UI
        slots = self._parse_matrix_lines("\n".join(slot_lines))
        self._clear_matrix_slot_rows()
        for slot in slots:
            values_str = " | ".join(slot.get("values", []))
            self._add_matrix_slot_row(slot.get("name", ""), values_str)
        return "\n".join(lines)

    def _build_pipeline_controls_panel(self, parent):
        """Build compact pipeline controls panel using PipelineControlsPanel component, with state restore."""
        # Save previous state if panel exists
        prev_state = None
        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
            try:
                prev_state = self.pipeline_controls_panel.get_state()
            except Exception as e:
                logger.warning(f"Failed to get PipelineControlsPanel state: {e}")
        # Destroy old panel if present
        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
            self.pipeline_controls_panel.destroy()
        # Determine initial state for the new panel
        initial_state = (
            prev_state if prev_state is not None else self.preferences.get("pipeline_controls")
        )

        # Create the PipelineControlsPanel component
        stage_vars = {
            "txt2img": self.txt2img_enabled,
            "img2img": self.img2img_enabled,
            "adetailer": self.adetailer_enabled,
            "upscale": self.upscale_enabled,
            "video": self.video_enabled,
        }

        self.pipeline_controls_panel = PipelineControlsPanel(
            parent,
            initial_state=initial_state,
            stage_vars=stage_vars,
            show_variant_controls=False,
            on_change=self._on_pipeline_controls_changed,
            style="Dark.TFrame",
        )
        # Place inside parent with pack for consistency with surrounding layout
        self.pipeline_controls_panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        # Restore previous state if available
        if prev_state:
            try:
                self.pipeline_controls_panel.set_state(prev_state)
            except Exception as e:
                logger.warning(f"Failed to restore PipelineControlsPanel state: {e}")
        # Keep shared references for non-stage settings
        self.video_enabled = self.pipeline_controls_panel.video_enabled
        self.loop_type_var = self.pipeline_controls_panel.loop_type_var
        self.loop_count_var = self.pipeline_controls_panel.loop_count_var
        self.pack_mode_var = self.pipeline_controls_panel.pack_mode_var
        self.images_per_prompt_var = self.pipeline_controls_panel.images_per_prompt_var

    def _build_config_display_tab(self, notebook):
        """Build interactive configuration tabs using ConfigPanel"""

        config_frame = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(config_frame, text="⚙️ Configuration")

        # Create ConfigPanel component
        self.config_panel = ConfigPanel(config_frame, coordinator=self, style="Dark.TFrame")
        self.config_panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Set up variable references for backward compatibility
        self.txt2img_vars = self.config_panel.txt2img_vars
        self.img2img_vars = self.config_panel.img2img_vars
        self.upscale_vars = self.config_panel.upscale_vars
        self.api_vars = self.config_panel.api_vars
        self._bind_config_panel_persistence_hooks()

    def _build_bottom_panel(self, parent):
        """Build bottom panel with logs and action buttons"""
        bottom_frame = ttk.Frame(parent, style="Dark.TFrame")
        bottom_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # Compact action buttons frame
        actions_frame = ttk.Frame(bottom_frame, style="Dark.TFrame")
        actions_frame.pack(fill=tk.X, pady=(0, 5))

        # Main execution buttons with accent colors
        main_buttons = ttk.Frame(actions_frame, style="Dark.TFrame")
        main_buttons.pack(side=tk.LEFT)

        self.run_pipeline_btn = ttk.Button(
            main_buttons,
            text="Run Full Pipeline",
            command=self._run_full_pipeline,
            style="Success.TButton",
        )  # Green for success/primary action
        self.run_pipeline_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tooltip(
            self.run_pipeline_btn,
            "Process every highlighted pack sequentially using the current configuration. Override mode applies when enabled.",
        )

        txt2img_only_btn = ttk.Button(
            main_buttons,
            text="txt2img Only",
            command=self._run_txt2img_only,
            style="Dark.TButton",
        )
        txt2img_only_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tooltip(
            txt2img_only_btn,
            "Generate txt2img outputs for the selected pack(s) only.",
        )

        upscale_only_btn = ttk.Button(
            main_buttons,
            text="Upscale Only",
            command=self._run_upscale_only,
            style="Dark.TButton",
        )
        upscale_only_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tooltip(
            upscale_only_btn,
            "Run only the upscale stage for the currently selected outputs (skips txt2img/img2img).",
        )

        create_video_btn = ttk.Button(
            main_buttons, text="Create Video", command=self._create_video, style="Dark.TButton"
        )
        create_video_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tooltip(create_video_btn, "Combine rendered images into a video file.")

        # Utility buttons
        util_buttons = ttk.Frame(actions_frame, style="Dark.TFrame")
        util_buttons.pack(side=tk.RIGHT)

        open_output_btn = ttk.Button(
            util_buttons,
            text="Open Output",
            command=self._open_output_folder,
            style="Dark.TButton",
        )
        open_output_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tooltip(
            open_output_btn, "Open the output directory in your system file browser."
        )

        stop_btn = ttk.Button(
            util_buttons, text="Stop", command=self._stop_execution, style="Danger.TButton"
        )
        stop_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tooltip(
            stop_btn,
            "Request cancellation of the pipeline run. The current stage finishes before stopping.",
        )

        exit_btn = ttk.Button(
            util_buttons, text="Exit", command=self._graceful_exit, style="Danger.TButton"
        )
        exit_btn.pack(side=tk.LEFT)
        self._attach_tooltip(exit_btn, "Gracefully stop background work and close StableNew.")

        # Reparent early log panel to bottom_frame
        # (log_panel was created early in __init__ to avoid AttributeError)
        # Create log panel directly with bottom_frame as parent
        self.log_panel = LogPanel(bottom_frame, coordinator=self, height=18, style="Dark.TFrame")
        self.log_panel.pack(fill=tk.BOTH, expand=True)
        self.log_panel.pack_propagate(False)
        self.add_log = self.log_panel.append
        self.log_text = getattr(self.log_panel, "log_text", None)
        if self.log_text is not None:
            enable_mousewheel(self.log_text)
        self._ensure_log_panel_min_height()

        # Attach logging handler to redirect standard logging to GUI
        if not hasattr(self, "gui_log_handler"):
            self.gui_log_handler = TkinterLogHandler(self.log_panel)
            logging.getLogger().addHandler(self.gui_log_handler)

        self._build_api_status_frame(bottom_frame)
        self._build_status_bar(bottom_frame)

    def _ensure_log_panel_min_height(self) -> None:
        """Ensure the log panel retains a minimum visible height."""
        if not hasattr(self, "log_panel"):
            return
        min_lines = max(1, getattr(self, "_log_min_lines", 7))
        text_widget = getattr(self.log_panel, "log_text", None)
        if text_widget is not None:
            try:
                current_height = int(text_widget.cget("height"))
            except Exception:
                current_height = min_lines
            if current_height < min_lines:
                try:
                    text_widget.configure(height=min_lines)
                except Exception:
                    pass

        def _apply_min_height():
            try:
                self.log_panel.update_idletasks()
                line_height = 18
                try:
                    if text_widget is not None:
                        info = text_widget.dlineinfo("1.0")
                        if info:
                            line_height = info[3] or line_height
                except Exception:
                    pass
                min_height = int(line_height * min_lines + 60)
                self.log_panel.configure(height=min_height)
                self.log_panel.pack_propagate(False)
                if (
                    hasattr(self, "_vertical_split")
                    and hasattr(self, "_bottom_pane")
                    and getattr(self, "_vertical_split", None) is not None
                ):
                    try:
                        self._vertical_split.paneconfigure(self._bottom_pane, minsize=min_height + 120)
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            self.root.after(0, _apply_min_height)
        except Exception:
            _apply_min_height()

    def _build_status_bar(self, parent):
        """Build status bar showing current state"""
        status_frame = ttk.Frame(parent, style="Dark.TFrame", relief=tk.SUNKEN)
        status_frame.pack(fill=tk.X, pady=(4, 0))
        status_frame.configure(height=52)
        status_frame.pack_propagate(False)

        # State indicator
        self.state_label = ttk.Label(
            status_frame, text="● Idle", style="Dark.TLabel", foreground="#4CAF50"
        )
        self.state_label.pack(side=tk.LEFT, padx=5)

        # Progress bar
        self.progress_bar = ttk.Progressbar(status_frame, mode="determinate")
        self.progress_bar.config(maximum=100, value=0)
        self.progress_bar.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        # ETA indicator
        self.eta_var = tk.StringVar(value=self._progress_eta_default)
        # Keep alias in sync for tests
        self.progress_eta_var = self.eta_var
        ttk.Label(status_frame, textvariable=self.eta_var, style="Dark.TLabel").pack(
            side=tk.LEFT, padx=5
        )

        # Progress message
        self.progress_message_var = tk.StringVar(value=self._progress_idle_message)
        # Keep alias in sync for tests
        self.progress_status_var = self.progress_message_var
        ttk.Label(status_frame, textvariable=self.progress_message_var, style="Dark.TLabel").pack(
            side=tk.LEFT, padx=10
        )

        # Spacer
        ttk.Label(status_frame, text="", style="Dark.TLabel").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        self._apply_progress_reset()

    def _apply_progress_reset(self, message: str | None = None) -> None:
        """Reset progress UI elements synchronously."""
        if hasattr(self, "progress_bar"):
            self.progress_bar.config(value=0)
        if hasattr(self, "eta_var"):
            self.eta_var.set(self._progress_eta_default)
        if hasattr(self, "progress_message_var"):
            self.progress_message_var.set(message or self._progress_idle_message)

    def _reset_progress_ui(self, message: str | None = None) -> None:
        """Reset the progress UI immediately when possible, else schedule on Tk loop."""
        try:
            self._apply_progress_reset(message)
        except Exception:
            pass
        try:
            self.root.after(0, lambda: self._apply_progress_reset(message))
        except Exception:
            pass

    def _apply_progress_update(self, stage: str, percent: float, eta: str | None) -> None:
        """Apply progress updates to the UI synchronously."""
        clamped_percent = max(0.0, min(100.0, float(percent) if percent is not None else 0.0))
        if hasattr(self, "progress_bar"):
            self.progress_bar.config(value=clamped_percent)

        if hasattr(self, "progress_message_var"):
            stage_text = stage.strip() if stage else "Progress"
            self.progress_message_var.set(f"{stage_text} ({clamped_percent:.0f}%)")

        if hasattr(self, "eta_var"):
            self.eta_var.set(f"ETA: {eta}" if eta else self._progress_eta_default)

    def _update_progress(self, stage: str, percent: float, eta: str | None = None) -> None:
        """Update progress UI, immediately if on Tk thread, else via event loop."""
        try:
            # Attempt immediate update (helps tests that call from main thread)
            self._apply_progress_update(stage, percent, eta)
        except Exception:
            # Fallback to Tk event loop scheduling only
            pass
        # Always ensure an event-loop scheduled update as well
        try:
            self.root.after(0, lambda: self._apply_progress_update(stage, percent, eta))
        except Exception:
            pass

    def _setup_state_callbacks(self):
        """Setup callbacks for state transitions"""

        def on_state_change(old_state, new_state):
            """Called when state changes"""
            state_colors = {
                GUIState.IDLE: ("#4CAF50", "● Idle"),
                GUIState.RUNNING: ("#2196F3", "● Running"),
                GUIState.STOPPING: ("#FF9800", "● Stopping"),
                GUIState.ERROR: ("#f44336", "● Error"),
            }

            color, text = state_colors.get(new_state, ("#888888", "● Unknown"))
            self.state_label.config(text=text, foreground=color)

            if new_state == GUIState.RUNNING:
                self.progress_message_var.set("Running pipeline...")
            elif new_state == GUIState.STOPPING:
                self.progress_message_var.set("Cancelling pipeline...")
            elif new_state == GUIState.ERROR:
                self.progress_message_var.set("Error")
            elif new_state == GUIState.IDLE and old_state == GUIState.STOPPING:
                self.progress_message_var.set("Ready")

            # Update button states
            if new_state == GUIState.RUNNING:
                self.run_pipeline_btn.config(state=tk.DISABLED)
            elif new_state == GUIState.IDLE:
                self._reset_progress_ui()
                self.run_pipeline_btn.config(state=tk.NORMAL if self.api_connected else tk.DISABLED)
            elif new_state == GUIState.ERROR:
                self.run_pipeline_btn.config(state=tk.NORMAL if self.api_connected else tk.DISABLED)

        self.state_manager.on_transition(on_state_change)

    def _configure_controller_progress_callbacks(self) -> None:
        """Connect controller progress callbacks to Tk-driven UI updates."""

        controller = getattr(self, "controller", None)
        if controller is None:
            return

        def _normalize_percent(value) -> float:
            try:
                percent = float(value if value is not None else 0.0)
            except (TypeError, ValueError):
                return 0.0
            if 0.0 <= percent <= 1.0:
                # Support normalized values supplied by unit tests.
                return percent * 100.0
            return percent

        def progress_handler(value=None, *args, **_kwargs) -> None:
            percent = _normalize_percent(value)
            self._queue_progress_update(percent)
            # Some callbacks also provide stage text as a secondary argument.
            if args:
                maybe_status = args[0]
                if isinstance(maybe_status, str):
                    self._queue_status_update(maybe_status)

        def eta_handler(value=None, *args, **_kwargs) -> None:
            eta_value = value if value is not None else (args[0] if args else None)
            self._queue_eta_update(eta_value)

        def reset_handler(*_args, **_kwargs) -> None:
            self._reset_progress_ui()

        def status_handler(value=None, *_args, **_kwargs) -> None:
            self._queue_status_update(value)

        callback_payload = {
            "progress": progress_handler,
            "eta": eta_handler,
            "reset": reset_handler,
            "status": status_handler,
        }

        configured = False
        for name in ("set_progress_callbacks", "register_progress_callbacks", "configure_progress_callbacks"):
            method = getattr(controller, name, None)
            if callable(method):
                try:
                    method(**callback_payload)
                    configured = True
                    break
                except TypeError:
                    logger.debug("Progress callback registration failed via %s", name, exc_info=True)

        if configured:
            return

        try:
            setter = getattr(controller, "set_progress_callback", None)
            if callable(setter):
                setter(progress_handler)
        except Exception:
            logger.debug("Failed to attach progress callback", exc_info=True)
        try:
            setter = getattr(controller, "set_eta_callback", None)
            if callable(setter):
                setter(lambda eta: eta_handler(eta))
        except Exception:
            logger.debug("Failed to attach ETA callback", exc_info=True)
        try:
            setter = getattr(controller, "set_status_callback", None)
            if callable(setter):
                setter(lambda status: status_handler(status))
        except Exception:
            logger.debug("Failed to attach status callback", exc_info=True)

    def _signal_pipeline_finished(self, event=None) -> None:
        """Notify tests waiting on lifecycle_event that the run has terminated."""

        event = event or getattr(self.controller, "lifecycle_event", None)
        if event is None:
            logger.debug("No lifecycle_event available to signal")
            return
        try:
            event.set()
        except Exception:
            logger.debug("Failed to signal lifecycle_event", exc_info=True)

    def _queue_progress_update(self, percent: float) -> None:
        """Update progress widgets on the Tk thread."""

        def update() -> None:
            clamped = max(0.0, min(100.0, float(percent) if percent is not None else 0.0))
            progress_bar = getattr(self, "progress_bar", None)
            if progress_bar is not None:
                progress_bar["value"] = clamped
            percent_var = getattr(self, "progress_percent_var", None)
            if percent_var is not None:
                percent_var.set(f"{clamped:.0f}%")

        self.root.after(0, update)

    def _queue_eta_update(self, eta: str | None) -> None:
        """Update ETA label on the Tk thread."""

        def update() -> None:
            eta_var = getattr(self, "eta_var", None)
            if eta_var is not None:
                eta_var.set(eta if eta else "ETA: --")

        self.root.after(0, update)

    def _queue_status_update(self, text: str | None) -> None:
        """Update status text via Tk event loop."""
        # If forced error status (test harness), ignore non-error updates
        if getattr(self, "_force_error_status", False):
            if not (text and str(text).strip().lower() == "error"):
                return
        self.root.after(0, lambda: self._apply_status_text(text))

    def _apply_status_text(self, text: str | None) -> None:
        """Apply status text to both status bar and execution label."""
        # If forced error status (tests), always show Error regardless of queued updates
        if getattr(self, "_force_error_status", False):
            forced = "Error" if not (text and str(text).strip().lower() == "error") else "Error"
            message_var = getattr(self, "progress_message_var", None)
            if message_var is not None:
                message_var.set(forced)
            progress_var = getattr(self, "progress_var", None)
            if progress_var is not None:
                progress_var.set(forced)
            return

        if text is None:
            try:
                from .state import GUIState

                if hasattr(self, "state_manager") and self.state_manager.is_state(GUIState.ERROR):
                    message = "Error"
                else:
                    message = "Ready"
            except Exception:
                message = "Ready"
        else:
            message = text
        # Normalize cancellation text to Ready once we've returned to IDLE
        try:
            from .state import GUIState

            if (
                str(message).strip().lower() == "cancelled"
                and hasattr(self, "state_manager")
                and self.state_manager.is_state(GUIState.IDLE)
            ):
                message = "Ready"
        except Exception:
            pass
        message_var = getattr(self, "progress_message_var", None)
        if message_var is not None:
            message_var.set(message)
        progress_var = getattr(self, "progress_var", None)
        if progress_var is not None:
            progress_var.set(message)

    def _normalize_api_url(self, value: Any) -> str:
        """Ensure downstream API clients always receive a fully-qualified URL."""
        if isinstance(value, (int, float)):
            return f"http://127.0.0.1:{int(value)}"
        url = str(value or "").strip()
        if not url:
            return "http://127.0.0.1:7860"
        lowered = url.lower()
        if lowered.startswith(("http://", "https://")):
            return url
        if lowered.startswith("://"):
            return f"http{url}"
        if lowered.startswith(("127.", "localhost")):
            return f"http://{url}"
        if lowered.startswith(":"):
            return f"http://127.0.0.1{url}"
        return f"http://{url}"

    def _set_api_url_var(self, value: Any) -> None:
        if hasattr(self, "api_url_var"):
            self.api_url_var.set(self._normalize_api_url(value))

    def _poll_controller_logs(self):
        """Poll controller for log messages and display them"""
        messages = self.controller.get_log_messages()
        for msg in messages:
            self.log_message(msg.message, msg.level)
            self._apply_status_text(msg.message)

        # Schedule next poll
        self.root.after(100, self._poll_controller_logs)

    # Class-level API check method
    def _check_api_connection(self):
        """Check API connection status with improved diagnostics."""

        if is_gui_test_mode():
            return
        if os.environ.get("STABLENEW_NO_WEBUI", "").lower() in {"1", "true", "yes"}:
            return

        try:
            initial_api_url = self._normalize_api_url(self.api_url_var.get())
        except Exception:
            initial_api_url = self._normalize_api_url("")
        timeout_value: int | None = None
        if hasattr(self, "api_vars") and "timeout" in self.api_vars:
            try:
                timeout_value = int(self.api_vars["timeout"].get() or 30)
            except Exception:
                timeout_value = None

        def check_in_thread(initial_url: str, timeout: int | None):
            api_url = initial_url

            # Try the specified URL first
            self.log_message("?? Checking API connection...", "INFO")

            # First try direct connection
            client = SDWebUIClient(api_url)
            # Apply configured timeout from API tab (keeps UI responsive on failures)
            if timeout:
                try:
                    client.timeout = timeout
                except Exception:
                    pass
            if client.check_api_ready():
                # Perform health check
                health = validate_webui_health(api_url)

                self.api_connected = True
                self.client = client
                self.pipeline = Pipeline(client, self.structured_logger)
                self.controller.set_pipeline(self.pipeline)

                self.root.after(0, lambda: self._update_api_status(True, api_url))

                if health["models_loaded"]:
                    self.log_message(
                        f"? API connected! Found {health.get('model_count', 0)} models", "SUCCESS"
                    )
                else:
                    self.log_message("?? API connected but no models loaded", "WARNING")
                return

            # If direct connection failed, try port discovery
            self.log_message("?? Trying port discovery...", "INFO")
            discovered_url = find_webui_api_port()

            if discovered_url:
                # Test the discovered URL
                client = SDWebUIClient(discovered_url)
                if timeout:
                    try:
                        client.timeout = timeout
                    except Exception:
                        pass
                if client.check_api_ready():
                    health = validate_webui_health(discovered_url)

                    self.api_connected = True
                    self.client = client
                    self.pipeline = Pipeline(client, self.structured_logger)
                    self.controller.set_pipeline(self.pipeline)

                    # Update URL field and status
                    self.root.after(0, lambda: self._set_api_url_var(discovered_url))
                    self.root.after(1000, self._check_api_connection)

                    if health["models_loaded"]:
                        self.log_message(
                            f"? API found at {discovered_url}! Found {health.get('model_count', 0)} models",
                            "SUCCESS",
                        )
                    else:
                        self.log_message("?? API found but no models loaded", "WARNING")
                    return

            # Connection failed
            self.api_connected = False
            self.root.after(0, lambda: self._update_api_status(False))
            self.log_message(
                "? API connection failed. Please ensure WebUI is running with --api", "ERROR"
            )
            self.log_message("?? Tip: Check ports 7860-7864, restart WebUI if needed", "INFO")
        threading.Thread(
            target=check_in_thread, args=(initial_api_url, timeout_value), daemon=True
        ).start()
        # Note: previously this method started two identical threads; that was redundant and has been removed

    def _update_api_status(self, connected: bool, url: str = None):
        """Update API status indicator"""
        if connected:
            if hasattr(self, "api_status_panel"):
                self.api_status_panel.set_status("Connected", "green")
            self.run_pipeline_btn.config(state=tk.NORMAL)

            # Update URL field if we found a different working port
            normalized_url = self._normalize_api_url(url) if url else None
            if normalized_url and normalized_url != self.api_url_var.get():
                self._set_api_url_var(normalized_url)
                self.log_message(f"Updated API URL to working port: {normalized_url}", "INFO")

            # Refresh models, VAE, samplers, upscalers, and schedulers when connected
            def refresh_all():
                try:
                    # Perform API calls in worker thread
                    self._refresh_models_async()
                    self._refresh_vae_models_async()
                    self._refresh_samplers_async()
                    self._refresh_hypernetworks_async()
                    self._refresh_upscalers_async()
                    self._refresh_schedulers_async()
                except Exception as exc:
                    # Marshal error message back to main thread
                    # Capture exception in default argument to avoid closure issues
                    self.root.after(
                        0,
                        lambda err=exc: self.log_message(
                            f"⚠️ Failed to refresh model lists: {err}", "WARNING"
                        ),
                    )

            # Run refresh in a separate thread to avoid blocking UI
            threading.Thread(target=refresh_all, daemon=True).start()
        else:
            if hasattr(self, "api_status_panel"):
                self.api_status_panel.set_status("Disconnected", "red")
            self.run_pipeline_btn.config(state=tk.DISABLED)

    def _on_pack_selection_changed_mediator(self, selected_packs: list[str]):
        """
        Mediator callback for pack selection changes from PromptPackPanel.

        Args:
            selected_packs: List of selected pack names
        """
        if getattr(self, "_diag_enabled", False):
            logger.info(
                f"[DIAG] mediator _on_pack_selection_changed_mediator start; packs={selected_packs}"
            )
        # Update internal state
        self.selected_packs = selected_packs
        self.current_selected_packs = selected_packs

        if selected_packs:
            pack_name = selected_packs[0]
            self.log_message(f"📦 Selected pack: {pack_name}")
            self._last_selected_pack = pack_name
        else:
            self.log_message("No pack selected")
            self._last_selected_pack = None

        # NOTE: Pack selection no longer auto-loads config - use Load Pack Config button instead
        if getattr(self, "_diag_enabled", False):
            logger.info("[DIAG] mediator _on_pack_selection_changed_mediator end")

    # ...existing code...

    # ...existing code...

    # ...existing code...

    def _refresh_prompt_packs(self):
        """Refresh the prompt packs list"""
        if hasattr(self, "prompt_pack_panel"):
            self.prompt_pack_panel.refresh_packs(silent=False)
            self.log_message("Refreshed prompt packs", "INFO")

    def _refresh_prompt_packs_silent(self):
        """Refresh the prompt packs list without logging (for initialization)"""
        if hasattr(self, "prompt_pack_panel"):
            self.prompt_pack_panel.refresh_packs(silent=True)

    def _refresh_prompt_packs_async(self):
        """Scan packs directory on a worker thread and populate asynchronously."""
        if not hasattr(self, "prompt_pack_panel"):
            return

        def scan_and_populate():
            try:
                packs_dir = Path("packs")
                pack_files = get_prompt_packs(packs_dir)
                self.root.after(0, lambda: self.prompt_pack_panel.populate(pack_files))
                self.root.after(
                    0, lambda: self.log_message(f"?? Loaded {len(pack_files)} prompt packs", "INFO")
                )
            except Exception as exc:
                self.root.after(
                    0, lambda err=exc: self.log_message(f"? Failed to load packs: {err}", "WARNING")
                )

        threading.Thread(target=scan_and_populate, daemon=True).start()

    def _refresh_config(self):
        """Refresh configuration based on pack selection and override state"""
        if getattr(self, "_diag_enabled", False):
            logger.info("[DIAG] _refresh_config start")
        # Prevent recursive refreshes
        if self._refreshing_config:
            if getattr(self, "_diag_enabled", False):
                logger.info("[DIAG] _refresh_config skipped (already refreshing)")
            return

        self._refreshing_config = True
        try:
            selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
            selected_packs = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]

            # Update UI state based on selection and override mode
            override_mode = hasattr(self, "override_pack_var") and self.override_pack_var.get()
            if override_mode:
                # Override mode: use current GUI config for all selected packs
                self._handle_override_mode(selected_packs)
            elif len(selected_packs) == 1:
                # Single pack: show that pack's individual config
                self._handle_single_pack_mode(selected_packs[0])
            elif len(selected_packs) > 1:
                # Multiple packs: grey out config, show status message
                self._handle_multi_pack_mode(selected_packs)
            else:
                # No packs selected: show preset config
                self._handle_no_pack_mode()

        finally:
            self._refreshing_config = False
            if getattr(self, "_diag_enabled", False):
                logger.info("[DIAG] _refresh_config end")

    def _handle_override_mode(self, selected_packs):
        """Handle override mode: current config applies to all selected packs"""
        # Enable all config controls
        self._set_config_editable(True)

        # Update status messages
        if hasattr(self, "current_pack_label"):
            self.current_pack_label.configure(
                text=f"Override mode: {len(selected_packs)} packs selected", foreground="#ffa500"
            )

        # Show override message in config area
        self._show_config_status(
            "Override mode active - current config will be used for all selected packs"
        )

        self.log_message(f"Override mode: Config will apply to {len(selected_packs)} packs", "INFO")

    def _handle_single_pack_mode(self, pack_name):
        """Handle single pack selection: show pack's individual config"""
        if getattr(self, "_diag_enabled", False):
            logger.info(f"[DIAG] _handle_single_pack_mode start; pack={pack_name}")
        # If override mode is NOT enabled, load the pack's config
        if not (hasattr(self, "override_pack_var") and self.override_pack_var.get()):
            # Ensure pack has a config file
            pack_config = self.config_manager.ensure_pack_config(
                pack_name, self.preset_var.get() or "default"
            )

            # Load pack's individual config into forms
            self._load_config_into_forms(pack_config)
            self.current_config = pack_config

            self.log_message(f"Loaded config for pack: {pack_name}", "INFO")
        else:
            # Override mode: keep current config visible (don't reload from pack)
            self.log_message(f"Override mode: keeping current config for pack: {pack_name}", "INFO")

        # Enable config controls
        self._set_config_editable(True)

        # Update status
        if hasattr(self, "current_pack_label"):
            override_enabled = hasattr(self, "override_pack_var") and self.override_pack_var.get()
            if override_enabled:
                self.current_pack_label.configure(
                    text=f"Pack: {pack_name} (Override)", foreground="#ffa500"
                )
            else:
                self.current_pack_label.configure(text=f"Pack: {pack_name}", foreground="#00ff00")

        if override_enabled:
            self._show_config_status(f"Override mode: current config will apply to {pack_name}")
        else:
            self._show_config_status(f"Showing config for pack: {pack_name}")
        if getattr(self, "_diag_enabled", False):
            logger.info(f"[DIAG] _handle_single_pack_mode end; pack={pack_name}")

    def _handle_multi_pack_mode(self, selected_packs):
        """Handle multiple pack selection: show first pack's config, save applies to all"""
        # If override mode is NOT enabled, load the first pack's config
        if not self.override_pack_var.get():
            first_pack = selected_packs[0]
            pack_config = self.config_manager.ensure_pack_config(
                first_pack, self.preset_var.get() or "default"
            )

            # Load first pack's config into forms
            self._load_config_into_forms(pack_config)
            self.current_config = pack_config

            self.log_message(f"Showing config from first selected pack: {first_pack}", "INFO")
        else:
            # Override mode: keep current config visible
            self.log_message(
                f"Override mode: current config will apply to {len(selected_packs)} packs", "INFO"
            )

        # Enable config controls
        self._set_config_editable(True)

        # Update status
        if hasattr(self, "current_pack_label"):
            override_enabled = hasattr(self, "override_pack_var") and self.override_pack_var.get()
            if override_enabled:
                self.current_pack_label.configure(
                    text=f"{len(selected_packs)} packs (Override)", foreground="#ffa500"
                )
            else:
                self.current_pack_label.configure(
                    text=f"{len(selected_packs)} packs selected", foreground="#ffff00"
                )

        if override_enabled:
            self._show_config_status(
                f"Override mode: current config will apply to all {len(selected_packs)} packs"
            )
        else:
            self._show_config_status(
                f"Showing config from first pack ({selected_packs[0]}). Click Save to apply to all {len(selected_packs)} pack(s)."
            )

    def _handle_no_pack_mode(self):
        """Handle no pack selection: show preset config"""
        # Enable config controls
        self._set_config_editable(True)

        # Load preset config
        preset_config = self.config_manager.load_preset(self.preset_var.get())
        if preset_config:
            self._load_config_into_forms(preset_config)
            self.current_config = preset_config

        # Update status
        if hasattr(self, "current_pack_label"):
            self.current_pack_label.configure(text="No pack selected", foreground="#ff6666")

        self._show_config_status(f"Showing preset config: {self.preset_var.get()}")

    def _set_config_editable(self, editable: bool):
        """Enable/disable config form controls"""
        if hasattr(self, "config_panel"):
            self.config_panel.set_editable(editable)

    def _show_config_status(self, message: str):
        """Show configuration status message in the config area"""
        if hasattr(self, "config_panel"):
            self.config_panel.set_status_message(message)

    def _get_config_from_forms(self) -> dict[str, Any]:
        """Extract current configuration from GUI forms"""
        config = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
        # 1) Start with ConfigPanel values if present
        if hasattr(self, "config_panel") and self.config_panel is not None:
            try:
                config = self.config_panel.get_config()
            except Exception as exc:
                self.log_message(f"Error reading config from panel: {exc}", "ERROR")
        # 2) Overlay with values from this form if available (authoritative when present)
        try:
            if hasattr(self, "txt2img_vars"):
                for k, v in self.txt2img_vars.items():
                    config.setdefault("txt2img", {})[k] = v.get()
            if hasattr(self, "img2img_vars"):
                for k, v in self.img2img_vars.items():
                    config.setdefault("img2img", {})[k] = v.get()
            if hasattr(self, "upscale_vars"):
                for k, v in self.upscale_vars.items():
                    config.setdefault("upscale", {})[k] = v.get()
        except Exception as exc:
            self.log_message(f"Error overlaying config from main form: {exc}", "ERROR")

        # 3) Pipeline controls
        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
            try:
                config["pipeline"] = self.pipeline_controls_panel.get_settings()
            except Exception:
                pass

        if hasattr(self, "adetailer_panel") and self.adetailer_panel is not None:
            try:
                config["adetailer"] = self.adetailer_panel.get_config()
            except Exception:
                pass

        try:
            config["randomization"] = self._collect_randomization_config()
        except Exception:
            config["randomization"] = {}

        try:
            config["aesthetic"] = self._collect_aesthetic_config()
        except Exception:
            config["aesthetic"] = {}

        return config

    def _get_config_snapshot(self) -> dict[str, Any]:
        """Capture a deep copy of the current form configuration."""
        try:
            snapshot = self._get_config_from_forms()
        except Exception as exc:
            self.log_message(f"Failed to capture config snapshot: {exc}", "WARNING")
            snapshot = {}
        return deepcopy(snapshot or {})

    def _attach_summary_traces(self) -> None:
        """Attach change traces to update live summaries."""
        if getattr(self, "_summary_traces_attached", False):
            return
        try:

            def attach_dict(dct: dict):
                for var in dct.values():
                    try:
                        var.trace_add("write", lambda *_: self._update_live_config_summary())
                    except Exception:
                        pass

            if hasattr(self, "txt2img_vars"):
                attach_dict(self.txt2img_vars)
            if hasattr(self, "img2img_vars"):
                attach_dict(self.img2img_vars)
            if hasattr(self, "upscale_vars"):
                attach_dict(self.upscale_vars)
            if hasattr(self, "pipeline_controls_panel"):
                p = self.pipeline_controls_panel
                for v in (
                    getattr(p, "txt2img_enabled", None),
                    getattr(p, "img2img_enabled", None),
                    getattr(p, "upscale_enabled", None),
                ):
                    try:
                        v and v.trace_add("write", lambda *_: self._update_live_config_summary())
                    except Exception:
                        pass
            self._summary_traces_attached = True
        except Exception:
            pass

    def _update_live_config_summary(self) -> None:
        """Compute and render the per-tab "next run" summaries from current vars."""
        try:
            # txt2img summary
            if hasattr(self, "txt2img_vars") and hasattr(self, "txt2img_summary_var"):
                t = self.txt2img_vars
                steps = t.get("steps").get() if "steps" in t else "-"
                sampler = t.get("sampler_name").get() if "sampler_name" in t else "-"
                cfg = t.get("cfg_scale").get() if "cfg_scale" in t else "-"
                width = t.get("width").get() if "width" in t else "-"
                height = t.get("height").get() if "height" in t else "-"
                self.txt2img_summary_var.set(
                    f"Next run: steps {steps}, sampler {sampler}, cfg {cfg}, size {width}x{height}"
                )

            # img2img summary
            if hasattr(self, "img2img_vars") and hasattr(self, "img2img_summary_var"):
                i2i = self.img2img_vars
                steps = i2i.get("steps").get() if "steps" in i2i else "-"
                denoise = (
                    i2i.get("denoising_strength").get() if "denoising_strength" in i2i else "-"
                )
                sampler = i2i.get("sampler_name").get() if "sampler_name" in i2i else "-"
                self.img2img_summary_var.set(
                    f"Next run: steps {steps}, denoise {denoise}, sampler {sampler}"
                )

            # upscale summary
            if hasattr(self, "upscale_vars") and hasattr(self, "upscale_summary_var"):
                up = self.upscale_vars
                mode = (up.get("upscale_mode").get() if "upscale_mode" in up else "single").lower()
                scale = up.get("upscaling_resize").get() if "upscaling_resize" in up else "-"
                if mode == "img2img":
                    steps = up.get("steps").get() if "steps" in up else "-"
                    denoise = (
                        up.get("denoising_strength").get() if "denoising_strength" in up else "-"
                    )
                    sampler = up.get("sampler_name").get() if "sampler_name" in up else "-"
                    self.upscale_summary_var.set(
                        f"Mode: img2img — steps {steps}, denoise {denoise}, sampler {sampler}, scale {scale}x"
                    )
                else:
                    upscaler = up.get("upscaler").get() if "upscaler" in up else "-"
                    self.upscale_summary_var.set(
                        f"Mode: single — upscaler {upscaler}, scale {scale}x"
                    )
        except Exception:
            pass

    def _save_current_pack_config(self):
        """Save current configuration to the selected pack (single pack mode only)"""
        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
        if len(selected_indices) == 1 and not (
            hasattr(self, "override_pack_var") and self.override_pack_var.get()
        ):
            pack_name = self.prompt_pack_panel.packs_listbox.get(selected_indices[0])
            current_config = self._get_config_from_forms()

            if self.config_manager.save_pack_config(pack_name, current_config):
                self.log_message(f"Saved configuration for pack: {pack_name}", "SUCCESS")
                self._show_config_status(f"Configuration saved for pack: {pack_name}")
            else:
                self.log_message(f"Failed to save configuration for pack: {pack_name}", "ERROR")

    def log_message(self, message: str, level: str = "INFO"):
        """Add message to live log with safe console fallback."""
        import datetime
        import sys
        import threading

        if threading.current_thread() is not threading.main_thread():
            try:
                self.root.after(0, lambda: self.log_message(message, level))
                return
            except Exception:
                # If we cannot schedule onto Tk, fall back to console logging below.
                pass

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"

        # Prefer GUI log panel once available
        try:
            add_log = getattr(self, "add_log", None)
            if callable(add_log):
                add_log(log_entry.strip(), level)
            elif getattr(self, "log_panel", None) is not None:
                self.log_panel.log(log_entry.strip(), level)
            else:
                raise RuntimeError("GUI log not ready")
        except Exception:
            # Safe console fallback that won't crash on Windows codepages
            try:
                enc = getattr(sys.stdout, "encoding", None) or "utf-8"
                safe_line = f"[{level}] {log_entry.strip()}".encode(enc, errors="replace").decode(
                    enc, errors="replace"
                )
                print(safe_line)
            except Exception:
                # Last-resort: swallow to avoid crashing the GUI init
                pass

        # Mirror to standard logger
        if level == "ERROR":
            logger.error(message)
        elif level == "WARNING":
            logger.warning(message)
        else:
            logger.info(message)

    def _attach_tooltip(self, widget: tk.Widget, text: str, delay: int = 1500) -> None:
        """Attach a tooltip to a widget if possible."""
        try:
            Tooltip(widget, text, delay=delay)
        except Exception:
            pass

    def _run_full_pipeline(self):
        if not self._confirm_run_with_dirty():
            return
        self._run_full_pipeline_impl()

    def _run_full_pipeline_impl(self):
        """Run the complete pipeline"""
        if not self.api_connected:
            messagebox.showerror("API Error", "Please connect to API first")
            return

        # Controller-based, cancellable implementation (bypasses legacy thread path below)
        from src.utils.file_io import read_prompt_pack

        from .state import CancellationError

        selected_packs = self._get_selected_packs()
        if not selected_packs:
            self.log_message("No prompt packs selected", "WARNING")
            return

        pack_summary = ", ".join(pack.name for pack in selected_packs)
        self.log_message(
            f"▶️ Starting pipeline execution for {len(selected_packs)} pack(s): {pack_summary}",
            "INFO",
        )
        try:
            override_mode = bool(self.override_pack_var.get())
        except Exception:
            override_mode = False

        # Snapshot Tk-backed values on the main thread (thread-safe)
        try:
            config_snapshot = self._get_config_from_forms()
        except Exception:
            config_snapshot = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
        try:
            batch_size_snapshot = int(self.images_per_prompt_var.get())
        except Exception:
            batch_size_snapshot = 1

        config_snapshot = config_snapshot or {
            "txt2img": {},
            "img2img": {},
            "upscale": {},
            "api": {},
        }
        pipeline_overrides = deepcopy(config_snapshot.get("pipeline", {}))
        api_overrides = deepcopy(config_snapshot.get("api", {}))
        try:
            preset_snapshot = self.preset_var.get()
        except Exception:
            preset_snapshot = "default"

        def resolve_config_for_pack(pack_file: Path) -> dict[str, Any]:
            """Return per-pack configuration honoring override mode."""
            if override_mode:
                return deepcopy(config_snapshot)

            pack_config: dict[str, Any] = {}
            if hasattr(self, "config_manager") and self.config_manager:
                try:
                    pack_config = self.config_manager.ensure_pack_config(
                        pack_file.name, preset_snapshot or "default"
                    )
                except Exception as exc:
                    self.log_message(
                        f"⚠️ Failed to load config for {pack_file.name}: {exc}. Using current form values.",
                        "WARNING",
                    )

            merged = deepcopy(pack_config) if pack_config else {}
            if pipeline_overrides:
                merged.setdefault("pipeline", {}).update(pipeline_overrides)
            if api_overrides:
                merged.setdefault("api", {}).update(api_overrides)
            # Always honor runtime-only sections from the current form (they are not stored per-pack)
            for runtime_key in ("randomization", "aesthetic"):
                snapshot_section = (
                    deepcopy(config_snapshot.get(runtime_key)) if config_snapshot else None
                )
                if snapshot_section:
                    merged[runtime_key] = snapshot_section

            # Overlay live model / VAE selections from the form in non-override mode if present.
            # Packs often persist a model/vae, but user dropdown changes should take effect for the run.
            try:
                live_txt2img = (config_snapshot or {}).get("txt2img", {})
                if live_txt2img:
                    for k in ("model", "sd_model_checkpoint", "vae"):
                        val = live_txt2img.get(k)
                        if isinstance(val, str) and val.strip():
                            merged.setdefault("txt2img", {})[k] = val.strip()
                live_img2img = (config_snapshot or {}).get("img2img", {})
                if live_img2img:
                    for k in ("model", "sd_model_checkpoint", "vae"):
                        val = live_img2img.get(k)
                        if isinstance(val, str) and val.strip():
                            merged.setdefault("img2img", {})[k] = val.strip()
            except Exception as exc:
                self.log_message(
                    f"⚠️ Failed to overlay live model/VAE selections: {exc}", "WARNING"
                )

            if merged:
                return merged
            return deepcopy(config_snapshot)

        def pipeline_func():
            cancel = self.controller.cancel_token
            session_run_dir = self.structured_logger.create_run_directory()
            self.log_message(f"📁 Session directory: {session_run_dir.name}", "INFO")

            total_generated = 0
            for pack_file in list(selected_packs):
                if cancel.is_cancelled():
                    raise CancellationError("User cancelled before pack start")
                self.log_message(f"📦 Processing pack: {pack_file.name}", "INFO")
                prompts = read_prompt_pack(pack_file)
                if not prompts:
                    self.log_message(f"No prompts found in {pack_file.name}", "WARNING")
                    continue
                config = resolve_config_for_pack(pack_file)
                config_mode = "override" if override_mode else "pack"
                self.log_message(
                    f"⚙️ Using {config_mode} configuration for {pack_file.name}", "INFO"
                )
                rand_cfg = config.get("randomization", {}) or {}
                if rand_cfg.get("enabled"):
                    sr_count = len((rand_cfg.get("prompt_sr", {}) or {}).get("rules", []) or [])
                    wc_count = len((rand_cfg.get("wildcards", {}) or {}).get("tokens", []) or [])
                    mx_slots = len((rand_cfg.get("matrix", {}) or {}).get("slots", []) or [])
                    mx_base = (rand_cfg.get("matrix", {}) or {}).get("base_prompt", "")
                    mx_prompt_mode = (rand_cfg.get("matrix", {}) or {}).get(
                        "prompt_mode", "replace"
                    )
                    self.log_message(
                        f"🎲 Randomization active: S/R={sr_count}, wildcards={wc_count}, matrix slots={mx_slots}",
                        "INFO",
                    )
                    seed_val = rand_cfg.get("seed", None)
                    if seed_val is not None:
                        self.log_message(f"🎲 Randomization seed: {seed_val}", "INFO")
                    if mx_base:
                        mode_verb = {
                            "replace": "replace",
                            "append": "append to",
                            "prepend": "prepend to",
                        }
                        verb = mode_verb.get(mx_prompt_mode, "replace")
                        self.log_message(
                            f"🎯 Matrix base_prompt will {verb} pack prompts: {mx_base[:60]}...",
                            "INFO",
                        )
                pack_variant_estimate, _ = self._estimate_pack_variants(
                    prompts, deepcopy(rand_cfg)
                )
                approx_images = pack_variant_estimate * batch_size_snapshot
                loop_multiplier = self._safe_int_from_var(self.loop_count_var, 1)
                if loop_multiplier > 1:
                    approx_images *= loop_multiplier
                self.log_message(
                    f"?? Prediction for {pack_file.name}: {pack_variant_estimate} variant(s) -> "
                    f"≈ {approx_images} image(s) at {batch_size_snapshot} img/prompt (loops={loop_multiplier})",
                    "INFO",
                )
                self._maybe_warn_large_output(approx_images, f"pack {pack_file.name}")
                try:
                    randomizer = PromptRandomizer(rand_cfg)
                except Exception as exc:
                    self.log_message(
                        f"?? Randomization disabled for {pack_file.name}: {exc}", "WARNING"
                    )
                    randomizer = PromptRandomizer({})
                variant_plan = build_variant_plan(config)
                if variant_plan.active:
                    self.log_message(
                        f"🎛️ Variant plan ({variant_plan.mode}) with {len(variant_plan.variants)} combo(s)",
                        "INFO",
                    )
                batch_size = batch_size_snapshot
                rotate_cursor = 0
                prompt_run_index = 0

                for i, prompt_data in enumerate(prompts):
                    if cancel.is_cancelled():
                        raise CancellationError("User cancelled during prompt loop")
                    prompt_text = (prompt_data.get("positive") or "").strip()
                    negative_override = (prompt_data.get("negative") or "").strip()
                    self.log_message(
                        f"📝 Prompt {i+1}/{len(prompts)}: {prompt_text[:50]}...",
                        "INFO",
                    )

                    randomized_variants = randomizer.generate(prompt_text)
                    if rand_cfg.get("enabled") and len(randomized_variants) == 1:
                        self.log_message(
                            "ℹ️ Randomization produced only one variant. Ensure prompt contains tokens (e.g. __mood__, [[slot]]) and rules have matches.",
                            "INFO",
                        )
                    if not randomized_variants:
                        randomized_variants = [PromptVariant(text=prompt_text, label=None)]

                    sanitized_negative = sanitize_prompt(negative_override) if negative_override else ""

                    for random_variant in randomized_variants:
                        random_label = random_variant.label
                        variant_prompt_text = sanitize_prompt(random_variant.text)
                        if random_label:
                            self.log_message(f"🎲 Randomization: {random_label}", "INFO")

                        if variant_plan.active and variant_plan.variants:
                            if variant_plan.mode == "fanout":
                                variants_to_run = variant_plan.variants
                            else:
                                variant = variant_plan.variants[
                                    rotate_cursor % len(variant_plan.variants)
                                ]
                            variants_to_run = [variant]
                            rotate_cursor += 1
                        else:
                            variants_to_run = [None]

                        for variant in variants_to_run:
                            if cancel.is_cancelled():
                                raise CancellationError("User cancelled during prompt loop")

                            stage_variant_label = None
                            variant_index = 0
                            if variant is not None:
                                stage_variant_label = variant.label
                                variant_index = variant.index
                                self.log_message(
                                    f"?? Variant {variant.index + 1}/{len(variant_plan.variants)}: {stage_variant_label}",
                                    "INFO",
                                )

                            effective_config = apply_variant_to_config(config, variant)
                            try:
                                t2i_cfg = effective_config.setdefault("txt2img", {}) or {}
                                t2i_cfg["prompt"] = variant_prompt_text
                                if sanitized_negative:
                                    t2i_cfg["negative_prompt"] = sanitized_negative
                            except Exception:
                                logger.exception("Failed to inject randomized prompt into txt2img config")
                            # Log effective model/VAE selections for visibility in live log
                            try:
                                t2i_cfg = (effective_config or {}).get("txt2img", {}) or {}
                                model_name = (
                                    t2i_cfg.get("model") or t2i_cfg.get("sd_model_checkpoint") or ""
                                )
                                vae_name = t2i_cfg.get("vae") or ""
                                if model_name or vae_name:
                                    self.log_message(
                                        f"🎛️ txt2img weights → model: {model_name or '(unchanged)'}; VAE: {vae_name or '(unchanged)'}",
                                        "INFO",
                                    )
                                i2i_enabled = bool(
                                    (effective_config or {})
                                    .get("pipeline", {})
                                    .get("img2img_enabled", False)
                                )
                                if i2i_enabled:
                                    i2i_cfg = (effective_config or {}).get("img2img", {}) or {}
                                    i2i_model = (
                                        i2i_cfg.get("model")
                                        or i2i_cfg.get("sd_model_checkpoint")
                                        or ""
                                    )
                                    i2i_vae = i2i_cfg.get("vae") or ""
                                    if i2i_model or i2i_vae:
                                        self.log_message(
                                            f"🎛️ img2img weights → model: {i2i_model or '(unchanged)'}; VAE: {i2i_vae or '(unchanged)'}",
                                            "INFO",
                                        )
                            except Exception:
                                pass
                            result = self.pipeline.run_pack_pipeline(
                                pack_name=pack_file.stem,
                                prompt=variant_prompt_text,
                                config=effective_config,
                                run_dir=session_run_dir,
                                prompt_index=prompt_run_index,
                                batch_size=batch_size,
                                variant_index=variant_index,
                                variant_label=stage_variant_label,
                            )
                            prompt_run_index += 1

                            if cancel.is_cancelled():
                                raise CancellationError("User cancelled after pack stage")

                            if result and result.get("summary"):
                                gen = len(result["summary"])
                                total_generated += gen
                                suffix_parts = []
                                if random_label:
                                    suffix_parts.append(f"random: {random_label}")
                                if stage_variant_label:
                                    suffix_parts.append(f"variant {variant_index + 1}")
                                suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
                                self.log_message(
                                    f"✅ Generated {gen} image(s) for prompt {i+1}{suffix}",
                                    "SUCCESS",
                                )
                            else:
                                suffix_parts = []
                                if random_label:
                                    suffix_parts.append(f"random: {random_label}")
                                if stage_variant_label:
                                    suffix_parts.append(f"variant {variant_index + 1}")
                                suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
                                self.log_message(
                                    f"❌ Failed to generate images for prompt {i+1}{suffix}",
                                    "ERROR",
                                )
                self.log_message(f"✅ Completed pack '{pack_file.stem}'", "SUCCESS")
            return {"images_generated": total_generated, "output_dir": str(session_run_dir)}

        def on_complete(result: dict):
            try:
                num_images = int(result.get("images_generated", 0)) if result else 0
                output_dir = result.get("output_dir", "") if result else ""
            except Exception:
                num_images, output_dir = 0, ""
            self.log_message(f"?? Pipeline completed: {num_images} image(s)", "SUCCESS")
            if output_dir:
                self.log_message(f"?? Output: {output_dir}", "INFO")
            # Combined summary of effective weights
            try:
                model = getattr(self.pipeline, "_current_model", None)
                vae = getattr(self.pipeline, "_current_vae", None)
                hyper = getattr(self.pipeline, "_current_hypernetwork", None)
                hn_strength = getattr(self.pipeline, "_current_hn_strength", None)
                self.log_message(
                    f"?? Run summary  model={model or '(none)'}; vae={vae or '(none)'}; hypernetwork={hyper or '(none)'}; strength={hn_strength if hn_strength is not None else '(n/a)'}",
                    "INFO",
                )
            except Exception:
                pass

        def on_error(e: Exception):
            self._handle_pipeline_error(e)

        started = self.controller.start_pipeline(
            pipeline_func, on_complete=on_complete, on_error=on_error
        )
        if started and is_gui_test_mode():
            try:
                event = getattr(self.controller, "lifecycle_event", None)
                if event is not None:
                    if not event.wait(timeout=5.0):
                        self._signal_pipeline_finished(event)
            except Exception:
                pass
        return

        def run_pipeline_thread():
            try:
                # Create single session run directory for all packs
                session_run_dir = self.structured_logger.create_run_directory()
                self.log_message(f"📁 Created session directory: {session_run_dir.name}", "INFO")

                # Get selected prompt packs
                selected_packs = self._get_selected_packs()
                if not selected_packs:
                    self.log_message("No prompt packs selected", "WARNING")
                    return

                # Process each pack
                for pack_file in selected_packs:
                    self.log_message(f"Processing pack: {pack_file.name}", "INFO")

                    # Read prompts from pack
                    prompts = read_prompt_pack(pack_file)
                    if not prompts:
                        self.log_message(f"No prompts found in {pack_file.name}", "WARNING")
                        continue

                    # Always read the latest form values to ensure UI changes are respected
                    config = self._get_config_from_forms()

                    # Process each prompt in the pack
                    images_generated = 0
                    for i, prompt_data in enumerate(prompts):
                        try:
                            self.log_message(
                                f"Processing prompt {i+1}/{len(prompts)}: {prompt_data['positive'][:50]}...",
                                "INFO",
                            )

                            # Run pipeline with new directory structure
                            result = self.pipeline.run_pack_pipeline(
                                pack_name=pack_file.stem,
                                prompt=prompt_data["positive"],
                                config=config,
                                run_dir=session_run_dir,
                                prompt_index=i,
                                batch_size=int(self.images_per_prompt_var.get()),
                            )

                            if result and result.get("summary"):
                                images_generated += len(result["summary"])
                                self.log_message(
                                    f"✅ Generated {len(result['summary'])} images for prompt {i+1}",
                                    "SUCCESS",
                                )
                            else:
                                self.log_message(
                                    f"❌ Failed to generate images for prompt {i+1}", "ERROR"
                                )

                        except Exception as e:
                            self.log_message(f"❌ Error processing prompt {i+1}: {str(e)}", "ERROR")
                            continue

                    self.log_message(
                        f"Completed pack {pack_file.name}: {images_generated} images", "SUCCESS"
                    )

                self.log_message("🎉 Pipeline execution completed!", "SUCCESS")

            except Exception as e:
                self.log_message(f"Pipeline execution failed: {e}", "ERROR")

        # Run in separate thread to avoid blocking UI
        self.log_message("🚀 Starting pipeline execution...", "INFO")
        threading.Thread(target=run_pipeline_thread, daemon=True).start()

    def _run_txt2img_only(self):
        """Run only txt2img generation"""
        if not self.api_connected:
            messagebox.showerror("API Error", "Please connect to API first")
            return

        selected = self._get_selected_packs()
        if not selected:
            messagebox.showerror("Selection Error", "Please select at least one prompt pack")
            return

        self.log_message("🎨 Running txt2img only...", "INFO")

        def txt2img_thread():
            try:
                run_dir = self.structured_logger.create_run_directory("txt2img_only")
                images_per_prompt = self._safe_int_from_var(self.images_per_prompt_var, 1)
                try:
                    preset_name = self.preset_var.get() or "default"
                except Exception:
                    preset_name = "default"

                for pack_path in selected:
                    pack_name = pack_path.name
                    self.log_message(f"Processing pack: {pack_name}", "INFO")

                    prompts = read_prompt_pack(pack_path)
                    if not prompts:
                        self.log_message(f"No prompts found in {pack_name}", "WARNING")
                        continue

                    try:
                        pack_config = self.config_manager.ensure_pack_config(pack_name, preset_name)
                    except Exception as exc:
                        self.log_message(
                            f"?? Failed to load config for {pack_name}: {exc}. Using default settings.",
                            "WARNING",
                        )
                        pack_config = {}

                    rand_cfg = deepcopy(pack_config.get("randomization") or {})
                    randomizer = None
                    if isinstance(rand_cfg, dict) and rand_cfg.get("enabled"):
                        try:
                            randomizer = PromptRandomizer(rand_cfg)
                        except Exception as exc:
                            self.log_message(
                                f"?? Randomization disabled for {pack_name}: {exc}", "WARNING"
                            )
                            randomizer = None

                    txt2img_base_cfg = deepcopy(pack_config.get("txt2img", {}) or {})
                    total_variants = 0

                    for idx, prompt_data in enumerate(prompts):
                        prompt_text = (prompt_data.get("positive") or "").strip()
                        negative_override = (prompt_data.get("negative") or "").strip()
                        sanitized_negative = (
                            sanitize_prompt(negative_override) if negative_override else ""
                        )
                        variants = (
                            randomizer.generate(prompt_text)
                            if randomizer
                            else [PromptVariant(text=prompt_text, label=None)]
                        )
                        total_variants += len(variants)

                        if randomizer and len(variants) == 1:
                            self.log_message(
                                "?? Randomization produced only one variant. Ensure prompt contains tokens (e.g. __mood__, [[slot]]) and rules have matches.",
                                "INFO",
                            )

                        for variant in variants:
                            variant_prompt = sanitize_prompt(variant.text)
                            cfg = deepcopy(txt2img_base_cfg)
                            cfg["prompt"] = variant_prompt
                            if sanitized_negative:
                                cfg["negative_prompt"] = sanitized_negative
                            if variant.label:
                                self.log_message(f"?? Randomization: {variant.label}", "INFO")

                            try:
                                results = self.pipeline.run_txt2img(
                                    prompt=variant_prompt,
                                    config=cfg,
                                    run_dir=run_dir,
                                    batch_size=images_per_prompt,
                                )
                                if results:
                                    self.log_message(
                                        f"✅ Generated {len(results)} image(s) for prompt {idx+1}",
                                        "SUCCESS",
                                    )
                                else:
                                    self.log_message(
                                        f"❌ Failed to generate image {idx+1}", "ERROR"
                                    )
                            except Exception as exc:
                                self.log_message(
                                    f"❌ Error generating image {idx+1}: {exc}", "ERROR"
                                )

                    approx_images = total_variants * images_per_prompt
                    self._maybe_warn_large_output(
                        approx_images, f"txt2img-only pack {pack_name}"
                    )

                self.log_message("🎉 Txt2img generation completed!", "SUCCESS")

            except Exception as exc:
                self.log_message(f"❌ Txt2img generation failed: {exc}", "ERROR")

        thread = threading.Thread(target=txt2img_thread, daemon=True)
        thread.start()

    def _run_upscale_only(self):
        """Run upscaling on existing images"""
        if not self.api_connected:
            messagebox.showerror("API Error", "Please connect to API first")
            return

        # Open file dialog to select images
        file_paths = filedialog.askopenfilenames(
            title="Select Images to Upscale",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff")],
        )

        if not file_paths:
            return

        def upscale_thread():
            try:
                config = self.current_config or self.config_manager.get_default_config()
                run_dir = self.structured_logger.create_run_directory("upscale_only")

                for file_path in file_paths:
                    image_path = Path(file_path)
                    self.log_message(f"Upscaling: {image_path.name}", "INFO")

                    result = self.pipeline.run_upscale(image_path, config["upscale"], run_dir)
                    if result:
                        self.log_message(f"✅ Upscaled: {image_path.name}", "SUCCESS")
                    else:
                        self.log_message(f"❌ Failed to upscale: {image_path.name}", "ERROR")

                self.log_message("Upscaling completed!", "SUCCESS")

            except Exception as e:
                self.log_message(f"Upscaling failed: {e}", "ERROR")

        threading.Thread(target=upscale_thread, daemon=True).start()

    def _create_video(self):
        """Create video from image sequence"""
        # Open folder dialog to select image directory
        folder_path = filedialog.askdirectory(title="Select Image Directory")
        if not folder_path:
            return

        def video_thread():
            try:
                image_dir = Path(folder_path)
                image_files = []

                for ext in ["*.png", "*.jpg", "*.jpeg"]:
                    image_files.extend(image_dir.glob(ext))

                if not image_files:
                    self.log_message("No images found in selected directory", "WARNING")
                    return

                # Create output video path
                video_path = image_dir / "output_video.mp4"
                video_path.parent.mkdir(exist_ok=True)

                self.log_message(f"Creating video from {len(image_files)} images...", "INFO")

                success = self.video_creator.create_video_from_images(
                    image_files, video_path, fps=24
                )

                if success:
                    self.log_message(f"✅ Video created: {video_path}", "SUCCESS")
                else:
                    self.log_message("❌ Video creation failed", "ERROR")

            except Exception as e:
                self.log_message(f"Video creation failed: {e}", "ERROR")

        threading.Thread(target=video_thread, daemon=True).start()

    def _get_selected_packs(self) -> list[Path]:
        """Resolve the currently selected prompt packs in UI order."""
        pack_names: list[str] = []

        if getattr(self, "selected_packs", None):
            pack_names = list(dict.fromkeys(self.selected_packs))
        elif hasattr(self, "prompt_pack_panel") and hasattr(
            self.prompt_pack_panel, "get_selected_packs"
        ):
            try:
                pack_names = list(self.prompt_pack_panel.get_selected_packs())
            except Exception:
                pack_names = []

        if (
            not pack_names
            and hasattr(self, "prompt_pack_panel")
            and hasattr(self.prompt_pack_panel, "packs_listbox")
        ):
            try:
                selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
                pack_names = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]
            except Exception:
                pack_names = []

        packs_dir = Path("packs")
        resolved: list[Path] = []
        for pack_name in pack_names:
            pack_path = packs_dir / pack_name
            if pack_path.exists():
                resolved.append(pack_path)
            else:
                self.log_message(f"⚠️ Pack not found on disk: {pack_path}", "WARNING")

        return resolved

    def _build_info_box(self, parent, title: str, text: str):
        """Reusable helper for informational sections within tabs."""
        frame = ttk.LabelFrame(parent, text=title, style="Dark.TLabelframe", padding=6)
        label = ttk.Label(
            frame,
            text=text,
            style="Dark.TLabel",
            wraplength=self._current_wraplength(),
            justify=tk.LEFT,
        )
        label.pack(fill=tk.X)
        self._register_wrappable_label(label)
        return frame

    def _build_advanced_editor_tab(self, parent: tk.Widget) -> None:
        shell = ttk.Frame(parent, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        canvas, body = make_scrollable(shell, style="Dark.TFrame")
        self._register_scrollable_section("advanced_editor", canvas, body)

        self._build_info_box(
            body,
            "Advanced Prompt Editor",
            "Manage prompt packs, validate syntax, and edit long-form content in the Advanced "
            "Prompt Editor. Use this tab to launch the editor without digging through menus.",
        ).pack(fill=tk.X, pady=(0, 6))

        launch_frame = ttk.Frame(body, style="Dark.TFrame")
        launch_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(
            launch_frame,
            text="Open Advanced Prompt Editor",
            style="Primary.TButton",
            command=self._open_prompt_editor,
        ).pack(side=tk.LEFT, padx=(0, 12))
        helper_label = ttk.Label(
            launch_frame,
            text="Opens a new window with multi-tab editing, validation, and global negative tools.",
            style="Dark.TLabel",
            wraplength=self._current_wraplength(),
            justify=tk.LEFT,
        )
        helper_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._register_wrappable_label(helper_label)

        features_label = ttk.Label(
            body,
            text="Features:\n• Block-based and TSV editing modes.\n• Global negative prompt manager.\n"
            "• Validation for missing embeddings/LoRAs.\n• Model browser with quick insert actions.",
            style="Dark.TLabel",
            justify=tk.LEFT,
            wraplength=self._current_wraplength(),
        )
        features_label.pack(fill=tk.X, pady=(0, 10))
        self._register_wrappable_label(features_label)

    def _bind_config_panel_persistence_hooks(self) -> None:
        """Ensure key config fields trigger preference persistence when changed."""
        if getattr(self, "_config_panel_prefs_bound", False):
            return
        if not hasattr(self, "config_panel"):
            return

        tracked_vars = []
        for key in ("model", "refiner_checkpoint"):
            var = self.config_panel.txt2img_vars.get(key)
            if isinstance(var, tk.Variable):
                tracked_vars.append(var)

        if not tracked_vars:
            return

        self._config_panel_prefs_bound = True
        for var in tracked_vars:
            try:
                var.trace_add("write", lambda *_: self._on_config_panel_primary_change())
            except Exception:
                continue

    def _on_config_panel_primary_change(self) -> None:
        self._autosave_preferences_if_needed(force=True)

    def _on_pipeline_controls_changed(self) -> None:
        self._set_config_dirty(True)
        self._autosave_preferences_if_needed(force=True)

    def _set_config_dirty(self, dirty: bool) -> None:
        self._config_dirty = bool(dirty)

    def _reset_config_dirty_state(self) -> None:
        self._set_config_dirty(False)

    def _confirm_run_with_dirty(self) -> bool:
        if not getattr(self, "_config_dirty", False):
            return True
        if is_gui_test_mode():
            return True
        return messagebox.askyesno(
            "Unsaved Changes",
            "The config has unsaved changes that won’t be applied to any pack. Continue anyway?",
        )

    def _maybe_show_new_features_dialog(self) -> None:
        """Optionally show the 'new features' dialog unless running under tests."""

        if is_gui_test_mode():
            return
        if getattr(self, "_new_features_dialog_shown", False):
            return
        self._new_features_dialog_shown = True
        self._show_new_features_dialog()

    def _show_new_features_dialog(self) -> None:
        """Display the latest feature highlights. Skips errors silently."""

        try:
            messagebox.showinfo(
                "New Features Available",
                (
                    "New GUI enhancements have been added in this release.\n\n"
                    "• Advanced prompt editor with validation tools.\n"
                    "• Improved pack persistence and scheduler handling.\n"
                    "• Faster pipeline startup diagnostics.\n\n"
                    "See CHANGELOG.md for full details."
                ),
            )
        except Exception:
            logger.debug("Failed to display new features dialog", exc_info=True)

    def _register_scrollable_section(
        self, name: str, canvas: tk.Canvas, body: tk.Widget
    ) -> None:
        scrollbar = getattr(canvas, "_vertical_scrollbar", None)
        self.scrollable_sections[name] = {
            "canvas": canvas,
            "body": body,
            "scrollbar": scrollbar,
        }

    def _current_wraplength(self, width: int | None = None) -> int:
        if width is None or width <= 0:
            try:
                width = self.root.winfo_width()
            except Exception:
                width = None
        if not width or width <= 1:
            width = self.window_min_size[0]
        return max(int(width * 0.55), 360)

    def _register_wrappable_label(self, label: tk.Widget) -> None:
        self._wrappable_labels.append(label)
        try:
            label.configure(wraplength=self._current_wraplength())
        except Exception:
            pass

    def _on_root_resize(self, event) -> None:
        if getattr(event, "widget", None) is not self.root:
            return
        wrap = self._current_wraplength(event.width)
        for label in list(self._wrappable_labels):
            try:
                label.configure(wraplength=wrap)
            except Exception:
                continue

    def _open_output_folder(self):
        """Open the output folder"""
        output_dir = Path("output")
        if output_dir.exists():
            if sys.platform == "win32":
                subprocess.run(["explorer", str(output_dir)])
            elif sys.platform == "darwin":
                subprocess.run(["open", str(output_dir)])
            else:
                subprocess.run(["xdg-open", str(output_dir)])
        else:
            messagebox.showinfo("No Output", "Output directory doesn't exist yet")



    def _stop_execution(self):
        """Stop the running pipeline"""
        try:
            stopping = self.controller.stop_pipeline()
        except Exception as exc:
            self.log_message(f"⏹️ Stop failed: {exc}", "ERROR")
            return

        if stopping:
            self.log_message("⏹️ Stop requested - cancelling pipeline...", "WARNING")
        else:
            self.log_message("⏹️ No pipeline running", "INFO")

    def _open_prompt_editor(self):
        """Open the advanced prompt pack editor"""
        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
        pack_path = None

        if selected_indices:
            pack_name = self.prompt_pack_panel.packs_listbox.get(selected_indices[0])
            pack_path = Path("packs") / pack_name

        # Initialize advanced editor if not already done
        if not hasattr(self, "advanced_editor"):
            self.advanced_editor = AdvancedPromptEditor(
                parent_window=self.root,
                config_manager=self.config_manager,
                on_packs_changed=self._refresh_prompt_packs,
                on_validation=self._handle_editor_validation,
            )

        # Open editor with selected pack
        self.advanced_editor.open_editor(pack_path)

    def _handle_editor_validation(self, results):
        """Handle validation results from the prompt editor"""
        # Log validation summary
        error_count = len(results.get("errors", []))
        warning_count = len(results.get("warnings", []))
        # info_count = len(results.get("info", []))  # Removed unused variable

        if error_count == 0 and warning_count == 0:
            self.log_message("✅ Pack validation passed - no issues found", "SUCCESS")
        else:
            if error_count > 0:
                self.log_message(f"❌ Pack validation found {error_count} error(s)", "ERROR")
                for error in results["errors"][:3]:  # Show first 3 errors
                    self.log_message(f"  • {error}", "ERROR")
                if error_count > 3:
                    self.log_message(f"  ... and {error_count - 3} more", "ERROR")

            if warning_count > 0:
                self.log_message(f"⚠️  Pack has {warning_count} warning(s)", "WARNING")
                for warning in results["warnings"][:2]:  # Show first 2 warnings
                    self.log_message(f"  • {warning}", "WARNING")
                if warning_count > 2:
                    self.log_message(f"  ... and {warning_count - 2} more", "WARNING")

        # Show stats
        stats = results.get("stats", {})
        self.log_message(
            f"📊 Pack stats: {stats.get('prompt_count', 0)} prompts, "
            f"{stats.get('embedding_count', 0)} embeddings, "
            f"{stats.get('lora_count', 0)} LoRAs",
            "INFO",
        )

    def _open_advanced_editor(self):
        """Wrapper method for opening advanced editor (called by button)"""
        self._open_prompt_editor()

    def _graceful_exit(self):
        """Gracefully exit the application and guarantee process termination."""
        self.log_message("Shutting down gracefully...", "INFO")

        try:
            self.log_message("✅ Graceful shutdown complete", "SUCCESS")
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.error("Error during shutdown logging: %s", exc)

        try:
            preferences = self._collect_preferences()
            if self.preferences_manager.save_preferences(preferences):
                self.preferences = preferences
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to save preferences: %s", exc)

        try:
            if (
                hasattr(self, "controller")
                and self.controller is not None
                and not self.controller.is_terminal
            ):
                try:
                    self.controller.stop_pipeline()
                except Exception:
                    logger.exception("Error while stopping pipeline during exit")
                try:
                    self.controller.lifecycle_event.wait(timeout=5.0)
                except Exception:
                    logger.exception("Error waiting for controller cleanup during exit")
        except Exception:
            logger.exception("Unexpected error during controller shutdown")

        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            logger.exception("Error tearing down Tk root during exit")

        os._exit(0)

    def run(self):
        """Start the GUI application"""
        # Start initial config refresh
        self._refresh_config()

        # Now refresh prompt packs asynchronously to avoid blocking
        self._refresh_prompt_packs_async()

        # Set up proper window closing
        self.root.protocol("WM_DELETE_WINDOW", self._graceful_exit)

        self.log_message("🚀 StableNew GUI started", "SUCCESS")
        self.log_message("Please connect to WebUI API to begin", "INFO")

        # Ensure window is visible and focused before starting mainloop
        self.root.deiconify()  # Make sure window is not minimized
        self.root.lift()  # Bring to front
        self.root.focus_force()  # Force focus

        # Log window state for debugging
        self.log_message("🖥️ GUI window should now be visible", "INFO")

        # Add a periodic check to ensure window stays visible
        def check_window_visibility():
            if self.root.state() == "iconic":  # Window is minimized
                self.log_message("⚠️ Window was minimized, restoring...", "WARNING")
                self.root.deiconify()
                self.root.lift()
            # Schedule next check in 30 seconds
            self.root.after(30000, check_window_visibility)

        # Start the visibility checker
        self.root.after(5000, check_window_visibility)  # First check after 5 seconds

    def run(self):
        """Start the Tkinter main loop with diagnostics."""
        logger.info("[DIAG] About to enter Tkinter mainloop", extra={"flush": True})
        self.root.mainloop()

    def _build_txt2img_config_tab(self, notebook):
        """Build txt2img configuration form"""
        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(tab_frame, text="🎨 txt2img")

        # Pack status header
        pack_status_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
        pack_status_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(
            pack_status_frame, text="Current Pack:", style="Dark.TLabel", font=("Arial", 9, "bold")
        ).pack(side=tk.LEFT)
        self.current_pack_label = ttk.Label(
            pack_status_frame,
            text="No pack selected",
            style="Dark.TLabel",
            font=("Arial", 9),
            foreground="#ffa500",
        )
        self.current_pack_label.pack(side=tk.LEFT, padx=(5, 0))

        # Override controls
        override_frame = ttk.Frame(tab_frame, style="Dark.TFrame")

        self.override_pack_var = tk.BooleanVar(value=False)
        override_checkbox = ttk.Checkbutton(
            override_frame,
            text="Override pack settings with current config",
            variable=self.override_pack_var,
            style="Dark.TCheckbutton",
            command=self._on_override_changed,
        )
        override_checkbox.pack(side=tk.LEFT)

        ttk.Separator(tab_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)

        # Create scrollable frame
        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
        scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Initialize config variables and widget references
        self.txt2img_vars = {}
        self.txt2img_widgets = {}

        # Compact generation settings
        gen_frame = ttk.LabelFrame(
            scrollable_frame, text="Generation Settings", style="Dark.TLabelframe", padding=5
        )
        gen_frame.pack(fill=tk.X, pady=2)

        # Steps - compact inline
        steps_row = ttk.Frame(gen_frame, style="Dark.TFrame")
        steps_row.pack(fill=tk.X, pady=2)
        ttk.Label(steps_row, text="Generation Steps:", style="Dark.TLabel", width=15).pack(
            side=tk.LEFT
        )
        self.txt2img_vars["steps"] = tk.IntVar(value=20)
        steps_spin = ttk.Spinbox(
            steps_row, from_=1, to=150, width=8, textvariable=self.txt2img_vars["steps"]
        )
        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
        self.txt2img_widgets["steps"] = steps_spin

        # Sampler - compact inline
        sampler_row = ttk.Frame(gen_frame, style="Dark.TFrame")
        sampler_row.pack(fill=tk.X, pady=2)
        ttk.Label(sampler_row, text="Sampler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.txt2img_vars["sampler_name"] = tk.StringVar(value="Euler a")
        sampler_combo = ttk.Combobox(
            sampler_row,
            textvariable=self.txt2img_vars["sampler_name"],
            values=[
                "Euler a",
                "Euler",
                "LMS",
                "Heun",
                "DPM2",
                "DPM2 a",
                "DPM++ 2S a",
                "DPM++ 2M",
                "DPM++ SDE",
                "DPM fast",
                "DPM adaptive",
                "LMS Karras",
                "DPM2 Karras",
                "DPM2 a Karras",
                "DPM++ 2S a Karras",
                "DPM++ 2M Karras",
                "DPM++ SDE Karras",
                "DDIM",
                "PLMS",
            ],
            width=18,
            state="readonly",
        )
        sampler_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.txt2img_widgets["sampler_name"] = sampler_combo

        # CFG Scale - compact inline
        cfg_row = ttk.Frame(gen_frame, style="Dark.TFrame")
        cfg_row.pack(fill=tk.X, pady=2)
        ttk.Label(cfg_row, text="CFG Scale:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.txt2img_vars["cfg_scale"] = tk.DoubleVar(value=7.0)
        cfg_slider = EnhancedSlider(
            cfg_row,
            from_=1.0,
            to=20.0,
            variable=self.txt2img_vars["cfg_scale"],
            resolution=0.1,
            width=120,
        )
        cfg_slider.pack(side=tk.LEFT, padx=(5, 5))
        self.txt2img_widgets["cfg_scale"] = cfg_slider

        # Dimensions - compact single row
        dims_frame = ttk.LabelFrame(
            scrollable_frame, text="Image Dimensions", style="Dark.TLabelframe", padding=5
        )
        dims_frame.pack(fill=tk.X, pady=2)

        dims_row = ttk.Frame(dims_frame, style="Dark.TFrame")
        dims_row.pack(fill=tk.X)

        ttk.Label(dims_row, text="Width:", style="Dark.TLabel", width=8).pack(side=tk.LEFT)
        self.txt2img_vars["width"] = tk.IntVar(value=512)
        width_combo = ttk.Combobox(
            dims_row,
            textvariable=self.txt2img_vars["width"],
            values=[256, 320, 384, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024],
            width=8,
        )
        width_combo.pack(side=tk.LEFT, padx=(2, 10))
        self.txt2img_widgets["width"] = width_combo

        ttk.Label(dims_row, text="Height:", style="Dark.TLabel", width=8).pack(side=tk.LEFT)
        self.txt2img_vars["height"] = tk.IntVar(value=512)
        height_combo = ttk.Combobox(
            dims_row,
            textvariable=self.txt2img_vars["height"],
            values=[256, 320, 384, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024],
            width=8,
        )
        height_combo.pack(side=tk.LEFT, padx=2)
        self.txt2img_widgets["height"] = height_combo

        # Advanced Settings
        advanced_frame = ttk.LabelFrame(
            scrollable_frame, text="Advanced Settings", style="Dark.TLabelframe", padding=5
        )
        advanced_frame.pack(fill=tk.X, pady=2)

        # Seed controls
        seed_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
        seed_row.pack(fill=tk.X, pady=2)
        ttk.Label(seed_row, text="Seed:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.txt2img_vars["seed"] = tk.IntVar(value=-1)
        seed_spin = ttk.Spinbox(
            seed_row, from_=-1, to=2147483647, width=12, textvariable=self.txt2img_vars["seed"]
        )
        seed_spin.pack(side=tk.LEFT, padx=(5, 5))
        self.txt2img_widgets["seed"] = seed_spin
        ttk.Button(
            seed_row,
            text="🎲 Random",
            command=lambda: self.txt2img_vars["seed"].set(-1),
            width=10,
            style="Dark.TButton",
        ).pack(side=tk.LEFT, padx=(5, 0))

        # CLIP Skip
        clip_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
        clip_row.pack(fill=tk.X, pady=2)
        ttk.Label(clip_row, text="CLIP Skip:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.txt2img_vars["clip_skip"] = tk.IntVar(value=2)
        clip_spin = ttk.Spinbox(
            clip_row, from_=1, to=12, width=8, textvariable=self.txt2img_vars["clip_skip"]
        )
        clip_spin.pack(side=tk.LEFT, padx=(5, 0))
        self.txt2img_widgets["clip_skip"] = clip_spin

        # Scheduler
        scheduler_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
        scheduler_row.pack(fill=tk.X, pady=2)
        ttk.Label(scheduler_row, text="Scheduler:", style="Dark.TLabel", width=15).pack(
            side=tk.LEFT
        )
        self.txt2img_vars["scheduler"] = tk.StringVar(value="normal")
        scheduler_combo = ttk.Combobox(
            scheduler_row,
            textvariable=self.txt2img_vars["scheduler"],
            values=[
                "normal",
                "Karras",
                "exponential",
                "sgm_uniform",
                "simple",
                "ddim_uniform",
                "beta",
                "linear",
                "cosine",
            ],
            width=15,
            state="readonly",
        )
        scheduler_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.txt2img_widgets["scheduler"] = scheduler_combo

        # Model Selection
        model_frame = ttk.LabelFrame(
            scrollable_frame, text="Model & VAE Selection", style="Dark.TLabelframe", padding=5
        )
        model_frame.pack(fill=tk.X, pady=2)

        # SD Model
        model_row = ttk.Frame(model_frame, style="Dark.TFrame")
        model_row.pack(fill=tk.X, pady=2)
        ttk.Label(model_row, text="SD Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.txt2img_vars["model"] = tk.StringVar(value="")
        self.model_combo = ttk.Combobox(
            model_row, textvariable=self.txt2img_vars["model"], width=40, state="readonly"
        )
        self.model_combo.pack(side=tk.LEFT, padx=(5, 5))
        self.txt2img_widgets["model"] = self.model_combo
        ttk.Button(
            model_row, text="🔄", command=self._refresh_models, width=3, style="Dark.TButton"
        ).pack(side=tk.LEFT)

        # VAE Model
        vae_row = ttk.Frame(model_frame, style="Dark.TFrame")
        vae_row.pack(fill=tk.X, pady=2)
        ttk.Label(vae_row, text="VAE Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.txt2img_vars["vae"] = tk.StringVar(value="")
        self.vae_combo = ttk.Combobox(
            vae_row, textvariable=self.txt2img_vars["vae"], width=40, state="readonly"
        )
        self.vae_combo.pack(side=tk.LEFT, padx=(5, 5))
        self.txt2img_widgets["vae"] = self.vae_combo
        ttk.Button(
            vae_row, text="🔄", command=self._refresh_vae_models, width=3, style="Dark.TButton"
        ).pack(side=tk.LEFT)

        # Hires.Fix Settings
        hires_frame = ttk.LabelFrame(
            scrollable_frame, text="High-Res Fix (Hires.fix)", style="Dark.TFrame", padding=5
        )
        hires_frame.pack(fill=tk.X, pady=2)

        # Enable Hires.fix checkbox
        hires_enable_row = ttk.Frame(hires_frame, style="Dark.TFrame")
        hires_enable_row.pack(fill=tk.X, pady=2)
        self.txt2img_vars["enable_hr"] = tk.BooleanVar(value=False)
        hires_check = ttk.Checkbutton(
            hires_enable_row,
            text="Enable High-Resolution Fix",
            variable=self.txt2img_vars["enable_hr"],
            style="Dark.TCheckbutton",
            command=self._on_hires_toggle,
        )
        hires_check.pack(side=tk.LEFT)
        self.txt2img_widgets["enable_hr"] = hires_check

        # Hires scale
        scale_row = ttk.Frame(hires_frame, style="Dark.TFrame")
        scale_row.pack(fill=tk.X, pady=2)
        ttk.Label(scale_row, text="Scale Factor:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.txt2img_vars["hr_scale"] = tk.DoubleVar(value=2.0)
        scale_spin = ttk.Spinbox(
            scale_row,
            from_=1.1,
            to=4.0,
            increment=0.1,
            width=8,
            textvariable=self.txt2img_vars["hr_scale"],
        )
        scale_spin.pack(side=tk.LEFT, padx=(5, 0))
        self.txt2img_widgets["hr_scale"] = scale_spin

        # Hires upscaler
        upscaler_row = ttk.Frame(hires_frame, style="Dark.TFrame")
        upscaler_row.pack(fill=tk.X, pady=2)
        ttk.Label(upscaler_row, text="HR Upscaler:", style="Dark.TLabel", width=15).pack(
            side=tk.LEFT
        )
        self.txt2img_vars["hr_upscaler"] = tk.StringVar(value="Latent")
        hr_upscaler_combo = ttk.Combobox(
            upscaler_row,
            textvariable=self.txt2img_vars["hr_upscaler"],
            values=[
                "Latent",
                "Latent (antialiased)",
                "Latent (bicubic)",
                "Latent (bicubic antialiased)",
                "Latent (nearest)",
                "Latent (nearest-exact)",
                "None",
                "Lanczos",
                "Nearest",
                "LDSR",
                "BSRGAN",
                "ESRGAN_4x",
                "R-ESRGAN General 4xV3",
                "ScuNET GAN",
                "ScuNET PSNR",
                "SwinIR 4x",
            ],
            width=20,
            state="readonly",
        )
        hr_upscaler_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.txt2img_widgets["hr_upscaler"] = hr_upscaler_combo

        # Hires denoising strength
        hr_denoise_row = ttk.Frame(hires_frame, style="Dark.TFrame")
        hr_denoise_row.pack(fill=tk.X, pady=2)
        ttk.Label(hr_denoise_row, text="HR Denoising:", style="Dark.TLabel", width=15).pack(
            side=tk.LEFT
        )
        self.txt2img_vars["denoising_strength"] = tk.DoubleVar(value=0.7)
        hr_denoise_slider = EnhancedSlider(
            hr_denoise_row,
            from_=0.0,
            to=1.0,
            variable=self.txt2img_vars["denoising_strength"],
            resolution=0.05,
            length=150,
        )
        hr_denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
        self.txt2img_widgets["denoising_strength"] = hr_denoise_slider

        # Additional Positive Prompt - compact
        pos_frame = ttk.LabelFrame(
            scrollable_frame,
            text="Additional Positive Prompt (appended to pack prompts)",
            style="Dark.TFrame",
            padding=5,
        )
        pos_frame.pack(fill=tk.X, pady=2)
        self.txt2img_vars["prompt"] = tk.StringVar(value="")
        self.pos_text = tk.Text(
            pos_frame, height=2, bg="#3d3d3d", fg="#ffffff", wrap=tk.WORD, font=("Segoe UI", 9)
        )
        self.pos_text.pack(fill=tk.X, pady=2)

        # Additional Negative Prompt - compact
        neg_frame = ttk.LabelFrame(
            scrollable_frame,
            text="Additional Negative Prompt (appended to pack negative prompts)",
            style="Dark.TFrame",
            padding=5,
        )
        neg_frame.pack(fill=tk.X, pady=2)
        self.txt2img_vars["negative_prompt"] = tk.StringVar(
            value="blurry, bad quality, distorted, ugly, malformed"
        )
        self.neg_text = tk.Text(
            neg_frame, height=2, bg="#3d3d3d", fg="#ffffff", wrap=tk.WORD, font=("Segoe UI", 9)
        )
        self.neg_text.pack(fill=tk.X, pady=2)
        self.neg_text.insert(1.0, self.txt2img_vars["negative_prompt"].get())

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        enable_mousewheel(canvas)
        enable_mousewheel(canvas)
        enable_mousewheel(canvas)

        # Live summary for next run (txt2img)
        try:
            self.txt2img_summary_var = getattr(self, "txt2img_summary_var", tk.StringVar(value=""))
            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
            ttk.Label(
                summary_frame,
                textvariable=self.txt2img_summary_var,
                style="Dark.TLabel",
                font=("Consolas", 9),
            ).pack(side=tk.LEFT)
        except Exception:
            pass

        # Attach traces and initialize summary text
        try:
            self._attach_summary_traces()
            self._update_live_config_summary()
        except Exception:
            pass

    def _build_img2img_config_tab(self, notebook):
        """Build img2img configuration form"""
        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(tab_frame, text="🧹 img2img")

        # Create scrollable frame
        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # Initialize config variables
        self.img2img_vars = {}
        self.img2img_widgets = {}

        # Generation Settings
        gen_frame = ttk.LabelFrame(
            scrollable_frame, text="Generation Settings", style="Dark.TLabelframe", padding=5
        )
        gen_frame.pack(fill=tk.X, pady=2)

        # Steps
        steps_row = ttk.Frame(gen_frame, style="Dark.TFrame")
        steps_row.pack(fill=tk.X, pady=2)
        ttk.Label(steps_row, text="Steps:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.img2img_vars["steps"] = tk.IntVar(value=15)
        steps_spin = ttk.Spinbox(
            steps_row, from_=1, to=150, width=8, textvariable=self.img2img_vars["steps"]
        )
        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
        self.img2img_widgets["steps"] = steps_spin

        # Denoising Strength
        denoise_row = ttk.Frame(gen_frame, style="Dark.TFrame")
        denoise_row.pack(fill=tk.X, pady=2)
        ttk.Label(denoise_row, text="Denoising:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.img2img_vars["denoising_strength"] = tk.DoubleVar(value=0.3)
        denoise_slider = EnhancedSlider(
            denoise_row,
            from_=0.0,
            to=1.0,
            variable=self.img2img_vars["denoising_strength"],
            resolution=0.01,
            width=120,
        )
        denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
        self.img2img_widgets["denoising_strength"] = denoise_slider

        # Sampler
        sampler_row = ttk.Frame(gen_frame, style="Dark.TFrame")
        sampler_row.pack(fill=tk.X, pady=2)
        ttk.Label(sampler_row, text="Sampler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.img2img_vars["sampler_name"] = tk.StringVar(value="Euler a")
        sampler_combo = ttk.Combobox(
            sampler_row,
            textvariable=self.img2img_vars["sampler_name"],
            values=[
                "Euler a",
                "Euler",
                "LMS",
                "Heun",
                "DPM2",
                "DPM2 a",
                "DPM++ 2S a",
                "DPM++ 2M",
                "DPM++ SDE",
                "DPM fast",
                "DPM adaptive",
                "LMS Karras",
                "DPM2 Karras",
                "DPM2 a Karras",
                "DPM++ 2S a Karras",
                "DPM++ 2M Karras",
                "DPM++ SDE Karras",
                "DDIM",
                "PLMS",
            ],
            width=18,
            state="readonly",
        )
        sampler_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.img2img_widgets["sampler_name"] = sampler_combo

        # CFG Scale
        cfg_row = ttk.Frame(gen_frame, style="Dark.TFrame")
        cfg_row.pack(fill=tk.X, pady=2)
        ttk.Label(cfg_row, text="CFG Scale:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.img2img_vars["cfg_scale"] = tk.DoubleVar(value=7.0)
        cfg_slider = EnhancedSlider(
            cfg_row,
            from_=1.0,
            to=20.0,
            variable=self.img2img_vars["cfg_scale"],
            resolution=0.5,
            length=150,
        )
        cfg_slider.pack(side=tk.LEFT, padx=(5, 5))
        self.img2img_widgets["cfg_scale"] = cfg_slider

        # Advanced Settings
        advanced_frame = ttk.LabelFrame(
            scrollable_frame, text="Advanced Settings", style="Dark.TLabelframe", padding=5
        )
        advanced_frame.pack(fill=tk.X, pady=2)

        # Seed
        seed_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
        seed_row.pack(fill=tk.X, pady=2)
        ttk.Label(seed_row, text="Seed:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.img2img_vars["seed"] = tk.IntVar(value=-1)
        seed_spin = ttk.Spinbox(
            seed_row, from_=-1, to=2147483647, width=12, textvariable=self.img2img_vars["seed"]
        )
        seed_spin.pack(side=tk.LEFT, padx=(5, 5))
        self.img2img_widgets["seed"] = seed_spin
        ttk.Button(
            seed_row,
            text="🎲 Random",
            command=lambda: self.img2img_vars["seed"].set(-1),
            width=10,
            style="Dark.TButton",
        ).pack(side=tk.LEFT, padx=(5, 0))

        # CLIP Skip
        clip_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
        clip_row.pack(fill=tk.X, pady=2)
        ttk.Label(clip_row, text="CLIP Skip:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.img2img_vars["clip_skip"] = tk.IntVar(value=2)
        clip_spin = ttk.Spinbox(
            clip_row, from_=1, to=12, width=8, textvariable=self.img2img_vars["clip_skip"]
        )
        clip_spin.pack(side=tk.LEFT, padx=(5, 0))
        self.img2img_widgets["clip_skip"] = clip_spin

        # Scheduler
        scheduler_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
        scheduler_row.pack(fill=tk.X, pady=2)
        ttk.Label(scheduler_row, text="Scheduler:", style="Dark.TLabel", width=15).pack(
            side=tk.LEFT
        )
        self.img2img_vars["scheduler"] = tk.StringVar(value="normal")
        scheduler_combo = ttk.Combobox(
            scheduler_row,
            textvariable=self.img2img_vars["scheduler"],
            values=[
                "normal",
                "Karras",
                "exponential",
                "sgm_uniform",
                "simple",
                "ddim_uniform",
                "beta",
                "linear",
                "cosine",
            ],
            width=15,
            state="readonly",
        )
        scheduler_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.img2img_widgets["scheduler"] = scheduler_combo

        # Model Selection
        model_frame = ttk.LabelFrame(
            scrollable_frame, text="Model & VAE Selection", style="Dark.TLabelframe", padding=5
        )
        model_frame.pack(fill=tk.X, pady=2)

        # SD Model
        model_row = ttk.Frame(model_frame, style="Dark.TFrame")
        model_row.pack(fill=tk.X, pady=2)
        ttk.Label(model_row, text="SD Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.img2img_vars["model"] = tk.StringVar(value="")
        self.img2img_model_combo = ttk.Combobox(
            model_row, textvariable=self.img2img_vars["model"], width=40, state="readonly"
        )
        self.img2img_model_combo.pack(side=tk.LEFT, padx=(5, 5))
        self.img2img_widgets["model"] = self.img2img_model_combo
        ttk.Button(
            model_row, text="🔄", command=self._refresh_models, width=3, style="Dark.TButton"
        ).pack(side=tk.LEFT)

        # VAE Model
        vae_row = ttk.Frame(model_frame, style="Dark.TFrame")
        vae_row.pack(fill=tk.X, pady=2)
        ttk.Label(vae_row, text="VAE Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.img2img_vars["vae"] = tk.StringVar(value="")
        self.img2img_vae_combo = ttk.Combobox(
            vae_row, textvariable=self.img2img_vars["vae"], width=40, state="readonly"
        )
        self.img2img_vae_combo.pack(side=tk.LEFT, padx=(5, 5))
        self.img2img_widgets["vae"] = self.img2img_vae_combo
        ttk.Button(
            vae_row, text="🔄", command=self._refresh_vae_models, width=3, style="Dark.TButton"
        ).pack(side=tk.LEFT)

        canvas.pack(fill="both", expand=True)

        # Live summary for next run (upscale)
        try:
            self.upscale_summary_var = getattr(self, "upscale_summary_var", tk.StringVar(value=""))
            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
            ttk.Label(
                summary_frame,
                textvariable=self.upscale_summary_var,
                style="Dark.TLabel",
                font=("Consolas", 9),
            ).pack(side=tk.LEFT)
        except Exception:
            pass

        try:
            self._attach_summary_traces()
            self._update_live_config_summary()
        except Exception:
            pass

        # Live summary for next run (img2img)
        try:
            self.img2img_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
            ttk.Label(
                summary_frame,
                textvariable=self.img2img_summary_var,
                style="Dark.TLabel",
                font=("Consolas", 9),
            ).pack(side=tk.LEFT)
        except Exception:
            pass

        try:
            self._attach_summary_traces()
            self._update_live_config_summary()
        except Exception:
            pass

    def _build_upscale_config_tab(self, notebook):
        """Build upscale configuration form"""
        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(tab_frame, text="📈 Upscale")

        # Create scrollable frame
        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # Initialize config variables
        self.upscale_vars = {}
        self.upscale_widgets = {}

        # Upscaling Method
        method_frame = ttk.LabelFrame(
            scrollable_frame, text="Upscaling Method", style="Dark.TLabelframe", padding=5
        )
        method_frame.pack(fill=tk.X, pady=2)

        method_row = ttk.Frame(method_frame, style="Dark.TFrame")
        method_row.pack(fill=tk.X, pady=2)
        ttk.Label(method_row, text="Method:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.upscale_vars["upscale_mode"] = tk.StringVar(value="single")
        method_combo = ttk.Combobox(
            method_row,
            textvariable=self.upscale_vars["upscale_mode"],
            values=["single", "img2img"],
            width=20,
            state="readonly",
        )
        method_combo.pack(side=tk.LEFT, padx=(5, 5))
        try:
            method_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_upscale_method_state())
        except Exception:
            pass
        self.upscale_widgets["upscale_mode"] = method_combo
        ttk.Label(method_row, text="ℹ️ img2img allows denoising", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(10, 0)
        )

        # Basic Upscaling Settings
        basic_frame = ttk.LabelFrame(
            scrollable_frame, text="Basic Settings", style="Dark.TLabelframe", padding=5
        )
        basic_frame.pack(fill=tk.X, pady=2)

        # Upscaler selection
        upscaler_row = ttk.Frame(basic_frame, style="Dark.TFrame")
        upscaler_row.pack(fill=tk.X, pady=2)
        ttk.Label(upscaler_row, text="Upscaler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.upscale_vars["upscaler"] = tk.StringVar(value="R-ESRGAN 4x+")
        self.upscaler_combo = ttk.Combobox(
            upscaler_row, textvariable=self.upscale_vars["upscaler"], width=40, state="readonly"
        )
        self.upscaler_combo.pack(side=tk.LEFT, padx=(5, 5))
        self.upscale_widgets["upscaler"] = self.upscaler_combo
        ttk.Button(
            upscaler_row, text="🔄", command=self._refresh_upscalers, width=3, style="Dark.TButton"
        ).pack(side=tk.LEFT)

        # Scale factor
        scale_row = ttk.Frame(basic_frame, style="Dark.TFrame")
        scale_row.pack(fill=tk.X, pady=2)
        ttk.Label(scale_row, text="Scale Factor:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.upscale_vars["upscaling_resize"] = tk.DoubleVar(value=2.0)
        scale_spin = ttk.Spinbox(
            scale_row,
            from_=1.1,
            to=4.0,
            increment=0.1,
            width=8,
            textvariable=self.upscale_vars["upscaling_resize"],
        )
        scale_spin.pack(side=tk.LEFT, padx=(5, 0))
        self.upscale_widgets["upscaling_resize"] = scale_spin

        # Steps for img2img mode
        steps_row = ttk.Frame(basic_frame, style="Dark.TFrame")
        steps_row.pack(fill=tk.X, pady=2)
        ttk.Label(steps_row, text="Steps (img2img):", style="Dark.TLabel", width=15).pack(
            side=tk.LEFT
        )
        try:
            self.upscale_vars["steps"]
        except Exception:
            self.upscale_vars["steps"] = tk.IntVar(value=20)
        steps_spin = ttk.Spinbox(
            steps_row,
            from_=1,
            to=150,
            textvariable=self.upscale_vars["steps"],
            width=8,
        )
        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
        self.upscale_widgets["steps"] = steps_spin

        # Denoising (for img2img mode)
        denoise_row = ttk.Frame(basic_frame, style="Dark.TFrame")
        denoise_row.pack(fill=tk.X, pady=2)
        ttk.Label(denoise_row, text="Denoising:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.upscale_vars["denoising_strength"] = tk.DoubleVar(value=0.35)
        denoise_slider = EnhancedSlider(
            denoise_row,
            from_=0.0,
            to=1.0,
            variable=self.upscale_vars["denoising_strength"],
            resolution=0.05,
            length=150,
        )
        denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
        self.upscale_widgets["denoising_strength"] = denoise_slider

        # Face Restoration
        face_frame = ttk.LabelFrame(
            scrollable_frame, text="Face Restoration", style="Dark.TLabelframe", padding=5
        )
        face_frame.pack(fill=tk.X, pady=2)

        # GFPGAN
        gfpgan_row = ttk.Frame(face_frame, style="Dark.TFrame")
        gfpgan_row.pack(fill=tk.X, pady=2)
        ttk.Label(gfpgan_row, text="GFPGAN:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
        self.upscale_vars["gfpgan_visibility"] = tk.DoubleVar(value=0.5)  # Default to 0.5
        gfpgan_slider = EnhancedSlider(
            gfpgan_row,
            from_=0.0,
            to=1.0,
            variable=self.upscale_vars["gfpgan_visibility"],
            resolution=0.01,
            width=120,
        )
        gfpgan_slider.pack(side=tk.LEFT, padx=(5, 5))
        self.upscale_widgets["gfpgan_visibility"] = gfpgan_slider

        # CodeFormer
        codeformer_row = ttk.Frame(face_frame, style="Dark.TFrame")
        codeformer_row.pack(fill=tk.X, pady=2)
        ttk.Label(codeformer_row, text="CodeFormer:", style="Dark.TLabel", width=15).pack(
            side=tk.LEFT
        )
        self.upscale_vars["codeformer_visibility"] = tk.DoubleVar(value=0.0)
        codeformer_slider = EnhancedSlider(
            codeformer_row,
            from_=0.0,
            to=1.0,
            variable=self.upscale_vars["codeformer_visibility"],
            resolution=0.05,
            length=150,
        )
        codeformer_slider.pack(side=tk.LEFT, padx=(5, 5))
        self.upscale_widgets["codeformer_visibility"] = codeformer_slider

        # CodeFormer Weight
        cf_weight_row = ttk.Frame(face_frame, style="Dark.TFrame")
        cf_weight_row.pack(fill=tk.X, pady=2)
        ttk.Label(cf_weight_row, text="CF Fidelity:", style="Dark.TLabel", width=15).pack(
            side=tk.LEFT
        )
        self.upscale_vars["codeformer_weight"] = tk.DoubleVar(value=0.5)
        cf_weight_slider = EnhancedSlider(
            cf_weight_row,
            from_=0.0,
            to=1.0,
            variable=self.upscale_vars["codeformer_weight"],
            resolution=0.05,
            length=150,
        )
        cf_weight_slider.pack(side=tk.LEFT, padx=(5, 5))
        self.upscale_widgets["codeformer_weight"] = cf_weight_slider

        canvas.pack(fill="both", expand=True)

        # Apply initial enabled/disabled state for img2img-only controls
        try:
            self._apply_upscale_method_state()
        except Exception:
            pass

    def _apply_upscale_method_state(self) -> None:
        """Enable/disable Upscale img2img-only controls based on selected method."""
        try:
            mode = str(self.upscale_vars.get("upscale_mode").get()).lower()
        except Exception:
            mode = "single"
        use_img2img = mode == "img2img"
        # Steps (standard widget)
        steps_widget = self.upscale_widgets.get("steps")
        if steps_widget is not None:
            try:
                steps_widget.configure(state=("normal" if use_img2img else "disabled"))
            except Exception:
                pass
        # Denoising (EnhancedSlider supports .configure(state=...))
        denoise_widget = self.upscale_widgets.get("denoising_strength")
        if denoise_widget is not None:
            try:
                denoise_widget.configure(state=("normal" if use_img2img else "disabled"))
            except Exception:
                pass

    def _build_api_config_tab(self, notebook):
        """Build API configuration form"""
        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(tab_frame, text="🔌 API")

        # API settings
        api_frame = ttk.LabelFrame(
            tab_frame, text="API Connection", style="Dark.TLabelframe", padding=10
        )
        api_frame.pack(fill=tk.X, pady=5)

        # Base URL
        url_frame = ttk.Frame(api_frame, style="Dark.TFrame")
        url_frame.pack(fill=tk.X, pady=5)
        ttk.Label(url_frame, text="Base URL:", style="Dark.TLabel").pack(side=tk.LEFT)
        self.api_vars = {}
        self.api_vars["base_url"] = self.api_url_var  # Use the same variable
        url_entry = ttk.Entry(url_frame, textvariable=self.api_vars["base_url"], width=30)
        url_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Timeout
        timeout_frame = ttk.Frame(api_frame, style="Dark.TFrame")
        timeout_frame.pack(fill=tk.X, pady=5)
        ttk.Label(timeout_frame, text="Timeout (s):", style="Dark.TLabel").pack(side=tk.LEFT)
        self.api_vars["timeout"] = tk.IntVar(value=300)
        timeout_spin = ttk.Spinbox(
            timeout_frame, from_=30, to=3600, width=10, textvariable=self.api_vars["timeout"]
        )
        timeout_spin.pack(side=tk.LEFT, padx=5)

    def _save_all_config(self):
        """Save all configuration changes"""
        try:
            # Build full config via form binder
            config = self._get_config_from_forms()

            # When packs are selected and not in override mode, persist to each selected pack
            selected = []
            if hasattr(self, "prompt_pack_panel") and hasattr(
                self.prompt_pack_panel, "packs_listbox"
            ):
                selected = [
                    self.prompt_pack_panel.packs_listbox.get(i)
                    for i in self.prompt_pack_panel.packs_listbox.curselection()
                ]
            # Fallback: if UI focus cleared the visual selection, use last-known pack
            if (not selected) and hasattr(self, "_last_selected_pack") and self._last_selected_pack:
                selected = [self._last_selected_pack]

            if selected and not (
                hasattr(self, "override_pack_var") and self.override_pack_var.get()
            ):
                saved_any = False
                for pack_name in selected:
                    if self.config_manager.save_pack_config(pack_name, config):
                        saved_any = True
                if saved_any:
                    self.log_message(
                        f"Saved configuration for {len(selected)} selected pack(s)", "SUCCESS"
                    )
                    self._show_config_status(
                        f"Configuration saved for {len(selected)} selected pack(s)"
                    )
                    try:
                        messagebox.showinfo(
                            "Config Saved",
                            f"Saved configuration for {len(selected)} selected pack(s)",
                        )
                    except Exception:
                        pass
                    try:
                        if hasattr(self, "config_panel"):
                            self.config_panel.show_save_indicator("Saved")
                    except Exception:
                        pass
                    try:
                        self.show_top_save_indicator("Saved")
                    except Exception:
                        pass
                else:
                    self.log_message("Failed to save configuration for selected packs", "ERROR")
            else:
                # Save as current config and optionally preset (override/preset path)
                self.current_config = config
                preset_name = tk.simpledialog.askstring(
                    "Save Preset", "Enter preset name (optional):"
                )
                if preset_name:
                    self.config_manager.save_preset(preset_name, config)
                    self.log_message(f"Saved configuration as preset: {preset_name}", "SUCCESS")
                    try:
                        messagebox.showinfo(
                            "Preset Saved",
                            f"Saved configuration as preset: {preset_name}",
                        )
                    except Exception:
                        pass
                    try:
                        if hasattr(self, "config_panel"):
                            self.config_panel.show_save_indicator("Saved")
                    except Exception:
                        pass
                    try:
                        self.show_top_save_indicator("Saved")
                    except Exception:
                        pass
                else:
                    self.log_message("Configuration updated (not saved as preset)", "INFO")
                    self._show_config_status("Configuration updated (not saved as preset)")
                    try:
                        if hasattr(self, "config_panel"):
                            self.config_panel.show_save_indicator("Saved")
                    except Exception:
                        pass
                    try:
                        self.show_top_save_indicator("Saved")
                    except Exception:
                        pass

        except Exception as e:
            self.log_message(f"Failed to save configuration: {e}", "ERROR")

    def _reset_all_config(self):
        """Reset all configuration to defaults"""
        defaults = self.config_manager.get_default_config()
        self._load_config_into_forms(defaults)
        self.log_message("Configuration reset to defaults", "INFO")

    def on_config_save(self, _config: dict) -> None:
        """Coordinator callback from ConfigPanel to save current settings."""
        try:
            self._save_all_config()
            if hasattr(self, "config_panel"):
                self.config_panel.show_save_indicator("Saved")
            self.show_top_save_indicator("Saved")
        except Exception:
            pass

    def show_top_save_indicator(self, text: str = "Saved", duration_ms: int = 2000) -> None:
        """Show a colored indicator next to the top Save button."""
        try:
            color = "#00c853" if (text or "").lower() == "saved" else "#ffa500"
            try:
                self.top_save_indicator.configure(foreground=color)
            except Exception:
                pass
            self.top_save_indicator_var.set(text)
            if duration_ms and (text or "").lower() == "saved":
                self.root.after(duration_ms, lambda: self.top_save_indicator_var.set(""))
        except Exception:
            pass

    def _on_preset_changed(self, event=None):
        """Handle preset dropdown selection changes"""
        preset_name = self.preset_var.get()
        if preset_name:
            self.log_message(f"Preset selected: {preset_name} (click Load to apply)", "INFO")

    def _on_preset_dropdown_changed(self):
        """Handle preset dropdown selection changes"""
        preset_name = self.preset_var.get()
        if not preset_name:
            return

        config = self.config_manager.load_preset(preset_name)
        if not config:
            self.log_message(f"Failed to load preset: {preset_name}", "ERROR")
            return

        self.current_preset = preset_name

        # Load the preset into the visible forms
        self._load_config_into_forms(config)

        # If override mode is enabled, this becomes the new override config
        if hasattr(self, "override_pack_var") and self.override_pack_var.get():
            self.current_config = config
            self.log_message(
                f"✓ Loaded preset '{preset_name}' (Pipeline + Randomization + General)",
                "SUCCESS",
            )
        else:
            # Not in override mode - preset loaded but not persisted until Save is clicked
            self.current_config = config
            self.log_message(
                f"✓ Loaded preset '{preset_name}' (Pipeline + Randomization + General). Click Save to apply to selected pack",
                "INFO",
            )

    def _apply_default_to_selected_packs(self):
        """Apply the default preset to currently selected pack(s)"""
        default_config = self.config_manager.load_preset("default")
        if not default_config:
            self.log_message("Failed to load default preset", "ERROR")
            return

        # Load into forms
        self._load_config_into_forms(default_config)
        self.current_config = default_config
        self.preset_var.set("default")
        self.current_preset = "default"

        self.log_message(
            "✓ Loaded default preset (click Save to apply to selected pack)", "SUCCESS"
        )

    def _save_config_to_packs(self):
        """Save current configuration to selected pack(s)"""
        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
        if not selected_indices:
            self.log_message("No packs selected", "WARNING")
            return

        selected_packs = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]
        current_config = self._get_config_from_forms()

        saved_count = 0
        for pack_name in selected_packs:
            if self.config_manager.save_pack_config(pack_name, current_config):
                saved_count += 1

        if saved_count > 0:
            if len(selected_packs) == 1:
                self.log_message(f"✓ Saved config to pack: {selected_packs[0]}", "SUCCESS")
            else:
                self.log_message(
                    f"✓ Saved config to {saved_count}/{len(selected_packs)} pack(s)", "SUCCESS"
                )
        else:
            self.log_message("Failed to save config to packs", "ERROR")

    def _load_selected_preset(self):
        """Load the currently selected preset into the form"""
        preset_name = self.preset_var.get()
        if not preset_name:
            self.log_message("No preset selected", "WARNING")
            return

        config = self.config_manager.load_preset(preset_name)
        if config:
            self.current_preset = preset_name
            if not (hasattr(self, "override_pack_var") and self.override_pack_var.get()):
                self._load_config_into_forms(config)
            self.current_config = config
            self.log_message(f"✓ Loaded preset: {preset_name}", "SUCCESS")
            self._refresh_config()
            # Refresh pack list asynchronously to reflect any changes
            try:
                self._refresh_prompt_packs_async()
            except Exception:
                pass
        else:
            self.log_message(f"Failed to load preset: {preset_name}", "ERROR")

    def _save_preset_as(self):
        """Save current configuration as a new preset with user-provided name"""
        from tkinter import simpledialog

        current_config = self._get_config_from_forms()

        preset_name = simpledialog.askstring(
            "Save Preset As",
            "Enter a name for the new preset:",
            initialvalue="",
        )

        if not preset_name:
            return

        # Clean up the name
        preset_name = preset_name.strip()
        if not preset_name:
            self.log_message("Preset name cannot be empty", "WARNING")
            return

        # Check if preset already exists
        if preset_name in self.config_manager.list_presets():
            from tkinter import messagebox

            overwrite = messagebox.askyesno(
                "Preset Exists",
                f"Preset '{preset_name}' already exists. Overwrite it?",
            )
            if not overwrite:
                return

        if self.config_manager.save_preset(preset_name, current_config):
            self.log_message(f"✓ Saved preset as: {preset_name}", "SUCCESS")
            # Refresh dropdown
            self.preset_dropdown["values"] = self.config_manager.list_presets()
            # Select the new preset
            self.preset_var.set(preset_name)
            self.current_preset = preset_name
        else:
            self.log_message(f"Failed to save preset: {preset_name}", "ERROR")

    def _delete_selected_preset(self):
        """Delete the currently selected preset after confirmation"""
        from tkinter import messagebox

        preset_name = self.preset_var.get()
        if not preset_name:
            self.log_message("No preset selected", "WARNING")
            return

        if preset_name == "default":
            messagebox.showwarning(
                "Cannot Delete Default",
                "The 'default' preset is protected and cannot be deleted.\n\nYou can overwrite it with different settings, but it cannot be removed.",
            )
            return

        confirm = messagebox.askyesno(
            "Delete Preset",
            f"Are you sure you want to delete the '{preset_name}' preset forever?",
        )

        if not confirm:
            return

        if self.config_manager.delete_preset(preset_name):
            self.log_message(f"✓ Deleted preset: {preset_name}", "SUCCESS")
            # Refresh dropdown
            self.preset_dropdown["values"] = self.config_manager.list_presets()
            # Select default
            self.preset_var.set("default")
            self.current_preset = "default"
            # Load default into forms
            self._on_preset_dropdown_changed()
        else:
            self.log_message(f"Failed to delete preset: {preset_name}", "ERROR")

    def _set_as_default_preset(self):
        """Mark the currently selected preset as the default (auto-loads on startup)"""
        from tkinter import messagebox

        preset_name = self.preset_var.get()
        if not preset_name:
            self.log_message("No preset selected", "WARNING")
            return

        # Check if there's already a default
        current_default = self.config_manager.get_default_preset()
        if current_default == preset_name:
            messagebox.showinfo(
                "Already Default",
                f"'{preset_name}' is already marked as the default preset.",
            )
            return

        if self.config_manager.set_default_preset(preset_name):
            self.log_message(f"⭐ Marked '{preset_name}' as default preset", "SUCCESS")
            messagebox.showinfo(
                "Default Preset Set",
                f"'{preset_name}' will now auto-load when the application starts.",
            )
        else:
            self.log_message(f"Failed to set default preset: {preset_name}", "ERROR")

    def _save_override_preset(self):
        """Save current configuration as the override preset (updates selected preset)"""
        current_config = self._get_config_from_forms()
        preset_name = self.preset_var.get()

        if not preset_name:
            self.log_message("No preset selected to update", "WARNING")
            return

        if self.config_manager.save_preset(preset_name, current_config):
            self.log_message(f"✓ Updated preset: {preset_name}", "SUCCESS")
        else:
            self.log_message(f"Failed to update preset: {preset_name}", "ERROR")

    def _on_override_changed(self):
        """Handle override checkbox changes"""
        # Refresh configuration display based on new override state
        self._refresh_config()

        if hasattr(self, "override_pack_var") and self.override_pack_var.get():
            self.log_message(
                "📝 Override mode enabled - current config will apply to all selected packs", "INFO"
            )
        else:
            self.log_message("📝 Override mode disabled - packs will use individual configs", "INFO")

    def _preserve_pack_selection(self):
        """Preserve pack selection when config changes"""
        if hasattr(self, "_last_selected_pack") and self._last_selected_pack:
            # Find and reselect the last selected pack
            current_selection = self.prompt_pack_panel.packs_listbox.curselection()
            if not current_selection:  # Only restore if nothing is selected
                for i in range(self.prompt_pack_panel.packs_listbox.size()):
                    if self.prompt_pack_panel.packs_listbox.get(i) == self._last_selected_pack:
                        self.prompt_pack_panel.packs_listbox.selection_set(i)
                        self.prompt_pack_panel.packs_listbox.activate(i)
                        # Pack selection restored silently - no need to log every restore
                        break

    def _load_config_into_forms(self, config):
        """Load configuration values into form widgets"""
        if getattr(self, "_diag_enabled", False):
            logger.info("[DIAG] _load_config_into_forms: start", extra={"flush": True})
        # Preserve current pack selection before updating forms
        current_selection = self.prompt_pack_panel.packs_listbox.curselection()
        selected_pack = None
        if current_selection:
            selected_pack = self.prompt_pack_panel.packs_listbox.get(current_selection[0])

        try:
            if hasattr(self, "config_panel"):
                if getattr(self, "_diag_enabled", False):
                    logger.info(
                        "[DIAG] _load_config_into_forms: calling config_panel.set_config",
                        extra={"flush": True},
                    )
                self.config_panel.set_config(config)
                if getattr(self, "_diag_enabled", False):
                    logger.info(
                        "[DIAG] _load_config_into_forms: config_panel.set_config returned",
                        extra={"flush": True},
                    )
            if hasattr(self, "adetailer_panel") and self.adetailer_panel:
                if getattr(self, "_diag_enabled", False):
                    logger.info(
                        "[DIAG] _load_config_into_forms: calling adetailer_panel.set_config",
                        extra={"flush": True},
                    )
                self._apply_adetailer_config_section(config.get("adetailer", {}))
            if getattr(self, "_diag_enabled", False):
                logger.info(
                    "[DIAG] _load_config_into_forms: calling _load_randomization_config",
                    extra={"flush": True},
                )
            self._load_randomization_config(config)
            if getattr(self, "_diag_enabled", False):
                logger.info(
                    "[DIAG] _load_config_into_forms: calling _load_aesthetic_config",
                    extra={"flush": True},
                )
            self._load_aesthetic_config(config)
        except Exception as e:
            self.log_message(f"Error loading config into forms: {e}", "ERROR")
            if getattr(self, "_diag_enabled", False):
                logger.error(
                    f"[DIAG] _load_config_into_forms: exception {e}",
                    exc_info=True,
                    extra={"flush": True},
                )

        # Restore pack selection if it was lost during form updates
        if selected_pack and not self.prompt_pack_panel.packs_listbox.curselection():
            if getattr(self, "_diag_enabled", False):
                logger.info(
                    "[DIAG] _load_config_into_forms: restoring pack selection",
                    extra={"flush": True},
                )
            for i in range(self.prompt_pack_panel.packs_listbox.size()):
                if self.prompt_pack_panel.packs_listbox.get(i) == selected_pack:
                    # Use unwrapped selection_set to avoid triggering callback recursively
                    if hasattr(self.prompt_pack_panel, "_orig_selection_set"):
                        self.prompt_pack_panel._orig_selection_set(i)
                    else:
                        self.prompt_pack_panel.packs_listbox.selection_set(i)
                    self.prompt_pack_panel.packs_listbox.activate(i)
                    break
        if getattr(self, "_diag_enabled", False):
            logger.info("[DIAG] _load_config_into_forms: end", extra={"flush": True})

    def _apply_saved_preferences(self):
        """Apply persisted preferences to the current UI session."""

        prefs = getattr(self, "preferences", None)
        if not prefs:
            return

        try:
            # Restore preset selection and override mode
            self.current_preset = prefs.get("preset", "default")
            if hasattr(self, "preset_var"):
                self.preset_var.set(self.current_preset)
            if hasattr(self, "override_pack_var"):
                self.override_pack_var.set(prefs.get("override_pack", False))

            # Restore pipeline control toggles
            pipeline_state = prefs.get("pipeline_controls")
            if pipeline_state and hasattr(self, "pipeline_controls_panel"):
                try:
                    self.pipeline_controls_panel.set_state(pipeline_state)
                except Exception as exc:
                    logger.warning(f"Failed to restore pipeline preferences: {exc}")

            # Restore pack selections
            selected_packs = prefs.get("selected_packs", [])
            if selected_packs and hasattr(self, "packs_listbox"):
                self.prompt_pack_panel.packs_listbox.selection_clear(0, tk.END)
                for pack_name in selected_packs:
                    for index in range(self.prompt_pack_panel.packs_listbox.size()):
                        if self.prompt_pack_panel.packs_listbox.get(index) == pack_name:
                            self.prompt_pack_panel.packs_listbox.selection_set(index)
                            self.prompt_pack_panel.packs_listbox.activate(index)
                self._update_selection_highlights()
                self.selected_packs = selected_packs
                if selected_packs:
                    self._last_selected_pack = selected_packs[0]

            # Restore configuration values into forms
            config = prefs.get("config")
            if config:
                self._load_config_into_forms(config)
                self.current_config = config
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning(f"Failed to apply saved preferences: {exc}")

    def _collect_preferences(self) -> dict[str, Any]:
        """Collect current UI preferences for persistence."""

        preferences = {
            "preset": self.preset_var.get() if hasattr(self, "preset_var") else "default",
            "selected_packs": [],
            "override_pack": (
                bool(self.override_pack_var.get()) if hasattr(self, "override_pack_var") else False
            ),
            "pipeline_controls": self.preferences_manager.default_pipeline_controls(),
            "config": self._get_config_from_forms(),
        }

        if hasattr(self, "packs_listbox"):
            preferences["selected_packs"] = [
                self.prompt_pack_panel.packs_listbox.get(i)
                for i in self.prompt_pack_panel.packs_listbox.curselection()
            ]

        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
            try:
                preferences["pipeline_controls"] = self.pipeline_controls_panel.get_state()
            except Exception as exc:  # pragma: no cover - defensive logging path
                logger.warning(f"Failed to capture pipeline controls state: {exc}")

        return preferences

    def _build_settings_tab(self, parent):
        """Build settings tab"""
        settings_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD)
        settings_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Show current preset
        presets = self.config_manager.list_presets()
        settings_text.insert(1.0, "Available Presets:")
        for preset in presets:
            settings_text.insert(tk.END, f"- {preset}")

        settings_text.insert(tk.END, "Default Configuration:")
        default_config = self.config_manager.get_default_config()
        settings_text.insert(tk.END, json.dumps(default_config, indent=2))

        settings_text.config(state=tk.DISABLED)

    def _build_log_tab(self, parent):
        """Build log tab"""
        self.log_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Add a handler to redirect logs to the text widget
        # This is a simple implementation - could be enhanced
        self._add_log_message("Log viewer initialized")

    def _add_log_message(self, message: str):
        """Add message to log viewer"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _refresh_presets(self):
        """Refresh preset list"""
        presets = self.config_manager.list_presets()
        self.preset_combo["values"] = presets
        if presets and not self.preset_var.get():
            self.preset_var.set(presets[0])

    def _run_pipeline(self):
        """Run the full pipeline using controller"""
        if not self.client or not self.pipeline:
            messagebox.showerror("Error", "Please check API connection first")
            return

        prompt = self.prompt_text.get(1.0, tk.END).strip()
        if not prompt:
            messagebox.showerror("Error", "Please enter a prompt")
            return

        # Get configuration from GUI forms (current user settings)
        config = self._get_config_from_forms()
        if not config:
            messagebox.showerror("Error", "Failed to read configuration from forms")
            return

        # Modify config based on options
        if not self.enable_img2img_var.get():
            config.pop("img2img", None)
        if not self.enable_upscale_var.get():
            config.pop("upscale", None)

        batch_size = self.batch_size_var.get()
        run_name = self.run_name_var.get() or None

        self.controller.report_progress("Running pipeline...", 0.0, "ETA: --")

        # Define pipeline function that checks cancel token
        # Snapshot Tk-backed values on the main thread (thread-safe)
        try:
            config_snapshot = self._get_config_from_forms()
        except Exception:
            config_snapshot = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
        try:
            batch_size_snapshot = int(self.images_per_prompt_var.get())
        except Exception:
            batch_size_snapshot = 1

        def pipeline_func():
            try:
                # Pass cancel_token to pipeline
                results = self.pipeline.run_full_pipeline(
                    prompt, config, run_name, batch_size, cancel_token=self.controller.cancel_token
                )
                return results
            except CancellationError:
                # Signal completion and prefer Ready status after cancellation
                self._signal_pipeline_finished()
                try:
                    self._force_error_status = False
                    if hasattr(self, "progress_message_var"):
                        # Schedule on Tk to mirror normal status handling
                        self.root.after(0, lambda: self.progress_message_var.set("Ready"))
                except Exception:
                    pass
                raise
            except Exception:
                logger.exception("Pipeline execution error")
                # Build error text up-front
                try:
                    import sys

                    ex_type, ex, _ = sys.exc_info()
                    err_text = (
                        f"Pipeline failed: {ex_type.__name__}: {ex}"
                        if (ex_type and ex)
                        else "Pipeline failed"
                    )
                except Exception:
                    err_text = "Pipeline failed"

                # Log friendly error line to app log first (test captures this)
                try:
                    self.log_message(f"? {err_text}", "ERROR")
                except Exception:
                    pass

                # Marshal error dialog to Tk thread (or bypass if env says so)
                def _show_err():
                    try:
                        import os

                        if os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {"1", "true", "TRUE"}:
                            return
                        if not getattr(self, "_error_dialog_shown", False):
                            messagebox.showerror("Pipeline Error", err_text)
                            self._error_dialog_shown = True
                    except Exception:
                        logger.exception("Unable to display error dialog")

                try:
                    self.root.after(0, _show_err)
                except Exception:
                    # Fallback for test harnesses without a real root loop
                    _show_err()

                # Ensure tests waiting on lifecycle_event are not blocked
                try:
                    self._signal_pipeline_finished()
                except Exception:
                    pass

                # Force visible error state/status
                self._force_error_status = True
                try:
                    if hasattr(self, "progress_message_var"):
                        self.progress_message_var.set("Error")
                except Exception:
                    pass
                try:
                    from .state import GUIState

                    # Schedule transition on Tk thread for deterministic callback behavior
                    self.root.after(0, lambda: self.state_manager.transition_to(GUIState.ERROR))
                except Exception:
                    pass

                # (Already logged above)
                raise

        # Completion callback
        def on_complete(results):
            output_dir = results.get("run_dir", "Unknown")
            num_images = len(results.get("summary", []))

            self.root.after(
                0,
                lambda: self.log_message(
                    f"✓ Pipeline completed: {num_images} images generated", "SUCCESS"
                ),
            )
            self.root.after(0, lambda: self.log_message(f"Output directory: {output_dir}", "INFO"))
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Success",
                    f"Pipeline completed!{num_images} images generatedOutput: {output_dir}",
                ),
            )
            # Reset error-control flags for the next run
            try:
                self._force_error_status = False
                self._error_dialog_shown = False
            except Exception:
                pass
            # Ensure lifecycle_event is signaled for tests waiting on completion
            self._signal_pipeline_finished()

        # Error callback
        def on_error(e):
            # Log and alert immediately (safe for tests with mocked messagebox)
            try:
                err_text = f"Pipeline failed: {type(e).__name__}: {e}"
                self.log_message(f"? {err_text}", "ERROR")
                try:
                    if hasattr(self, "progress_message_var"):
                        self.progress_message_var.set("Error")
                except Exception:
                    pass
                try:
                    if not getattr(self, "_error_dialog_shown", False):
                        messagebox.showerror("Pipeline Error", err_text)
                        self._error_dialog_shown = True
                except Exception:
                    pass
                try:
                    # Also schedule to ensure it wins over any queued 'Running' updates
                    self.root.after(
                        0,
                        lambda: hasattr(self, "progress_message_var")
                        and self.progress_message_var.set("Error"),
                    )
                    # Schedule explicit ERROR transition to drive status callbacks
                    from .state import GUIState

                    self.root.after(0, lambda: self.state_manager.transition_to(GUIState.ERROR))
                except Exception:
                    pass
            except Exception:
                pass

            # Also schedule the standard UI error handler
            def _show_err():
                import os

                if os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {"1", "true", "TRUE"}:
                    return
                try:
                    if not getattr(self, "_error_dialog_shown", False):
                        messagebox.showerror("Pipeline Error", str(e))
                        self._error_dialog_shown = True
                except Exception:
                    logger.exception("Unable to display error dialog")

            try:
                self.root.after(0, _show_err)
            except Exception:
                _show_err()
            # Ensure lifecycle_event is signaled promptly on error
            try:
                self._signal_pipeline_finished()
            except Exception:
                pass

        # Start pipeline using controller (tests may toggle _sync_cleanup themselves)
        self.controller.start_pipeline(pipeline_func, on_complete=on_complete, on_error=on_error)

    def _handle_pipeline_error(self, error: Exception) -> None:
        """Log and surface pipeline errors to the user.

        This method may be called from a worker thread, so GUI operations
        must be marshaled to the main thread using root.after().
        """

        error_message = f"Pipeline failed: {type(error).__name__}: {error}\nA fatal error occurred. Please restart StableNew to continue."
        self.log_message(f"✗ {error_message}", "ERROR")

        # Marshal messagebox to main thread to avoid Tkinter threading violations
        def show_error_dialog():
            try:
                if not getattr(self, "_error_dialog_shown", False):
                    messagebox.showerror("Pipeline Error", error_message)
                    self._error_dialog_shown = True
            except tk.TclError:
                logger.error("Unable to display error dialog", exc_info=True)

        import os
        import sys
        import threading

        def exit_app():
            try:
                self.root.destroy()
            except Exception:
                pass
            try:
                sys.exit(1)
            except SystemExit:
                pass

        def force_exit_thread():
            import time

            time.sleep(1)
            os._exit(1)

        threading.Thread(target=force_exit_thread, daemon=True).start()

        try:
            self.root.after(0, show_error_dialog)
            self.root.after(100, exit_app)
        except Exception:
            show_error_dialog()
            exit_app()
        # Progress message update is handled by state transition callback; redundant here.

    def _create_video(self):
        """Create video from output images"""
        # Ask user to select output directory
        output_dir = filedialog.askdirectory(title="Select output directory containing images")

        if not output_dir:
            return

        output_path = Path(output_dir)

        # Try to find upscaled images first, then img2img, then txt2img
        for subdir in ["upscaled", "img2img", "txt2img"]:
            image_dir = output_path / subdir
            if image_dir.exists():
                video_path = output_path / "video" / f"{subdir}_video.mp4"
                video_path.parent.mkdir(exist_ok=True)

                self._add_log_message(f"Creating video from {subdir}...")

                if self.video_creator.create_video_from_directory(image_dir, video_path):
                    self._add_log_message(f"✓ Video created: {video_path}")
                    messagebox.showinfo("Success", f"Video created:{video_path}")
                else:
                    self._add_log_message(f"✗ Failed to create video from {subdir}")

                return

        messagebox.showerror("Error", "No image directories found")

    def _refresh_models(self):
        """Refresh the list of available SD models (main thread version)"""
        if self.client is None:
            messagebox.showerror("Error", "API client not connected")
            return

        try:
            models = self.client.get_models()
            model_names = [""] + [
                model.get("title", model.get("model_name", "")) for model in models
            ]

            if hasattr(self, "config_panel"):
                self.config_panel.set_model_options(model_names)

            self.log_message(f"🔄 Loaded {len(models)} SD models")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh models: {e}")

    def _refresh_models_async(self):
        """Refresh the list of available SD models (thread-safe version)"""
        from functools import partial

        if self.client is None:
            # Schedule error message on main thread
            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
            return

        try:
            # Perform API call in worker thread
            models = self.client.get_models()
            model_names = [""] + [
                model.get("title", model.get("model_name", "")) for model in models
            ]

            # Marshal widget updates back to main thread
            def update_widgets():
                if hasattr(self, "model_combo"):
                    self.model_combo["values"] = tuple(model_names)
                if hasattr(self, "img2img_model_combo"):
                    self.img2img_model_combo["values"] = tuple(model_names)
                self._add_log_message(f"🔄 Loaded {len(models)} SD models")

            self.root.after(0, update_widgets)

            # Also update unified ConfigPanel if present using partial to capture value
            if hasattr(self, "config_panel"):
                self.root.after(0, partial(self.config_panel.set_model_options, list(model_names)))

        except Exception as exc:
            # Marshal error message back to main thread
            # Capture exception in default argument to avoid closure issues
            self.root.after(
                0,
                lambda err=exc: messagebox.showerror("Error", f"Failed to refresh models: {err}"),
            )

    def _refresh_hypernetworks_async(self):
        """Refresh available hypernetworks (thread-safe)."""

        if self.client is None:
            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
            return

        def worker():
            try:
                entries = self.client.get_hypernetworks()
                names = ["None"]
                for entry in entries:
                    name = ""
                    if isinstance(entry, dict):
                        name = entry.get("name") or entry.get("title") or ""
                    else:
                        name = str(entry)
                    name = name.strip()
                    if name and name not in names:
                        names.append(name)

                self.available_hypernetworks = names

                def update_widgets():
                    if hasattr(self, "config_panel"):
                        try:
                            self.config_panel.set_hypernetwork_options(names)
                        except Exception:
                            pass

                self.root.after(0, update_widgets)
                self._add_log_message(f"🔄 Loaded {len(names) - 1} hypernetwork(s)")
            except Exception as exc:  # pragma: no cover - Tk loop dispatch
                self.root.after(
                    0,
                    lambda err=exc: messagebox.showerror(
                        "Error", f"Failed to refresh hypernetworks: {err}"
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_vae_models(self):
        """Refresh the list of available VAE models (main thread version)"""
        if self.client is None:
            messagebox.showerror("Error", "API client not connected")
            return

        try:
            vae_models = self.client.get_vae_models()
            vae_names = [""] + [vae.get("model_name", "") for vae in vae_models]

            if hasattr(self, "config_panel"):
                self.config_panel.set_vae_options(vae_names)

            self.log_message(f"🔄 Loaded {len(vae_models)} VAE models")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh VAE models: {e}")

    def _refresh_vae_models_async(self):
        """Refresh the list of available VAE models (thread-safe version)"""
        from functools import partial

        if self.client is None:
            # Schedule error message on main thread
            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
            return

        try:
            # Perform API call in worker thread
            vae_models = self.client.get_vae_models()
            vae_names_local = [""] + [vae.get("model_name", "") for vae in vae_models]

            # Store in instance attribute
            self.vae_names = list(vae_names_local)

            # Marshal widget updates back to main thread
            def update_widgets():
                if hasattr(self, "vae_combo"):
                    self.vae_combo["values"] = tuple(self.vae_names)
                if hasattr(self, "img2img_vae_combo"):
                    self.img2img_vae_combo["values"] = tuple(self.vae_names)
                self._add_log_message(f"🔄 Loaded {len(vae_models)} VAE models")

            self.root.after(0, update_widgets)

            # Also update config panel if present using partial to capture value
            if hasattr(self, "config_panel"):
                self.root.after(0, partial(self.config_panel.set_vae_options, list(self.vae_names)))

        except Exception as exc:
            # Marshal error message back to main thread
            # Capture exception in default argument to avoid closure issues
            self.root.after(
                0,
                lambda err=exc: messagebox.showerror(
                    "Error", f"Failed to refresh VAE models: {err}"
                ),
            )

    def _refresh_samplers(self):
        """Refresh the list of available samplers (main thread version)."""
        if self.client is None:
            messagebox.showerror("Error", "API client not connected")
            return

        try:
            samplers = self.client.get_samplers()
            sampler_names = sorted(
                {s.get("name", "") for s in samplers if s.get("name")},
                key=str.lower,
            )
            self.sampler_names = list(sampler_names)
            if hasattr(self, "config_panel"):
                self.config_panel.set_sampler_options(self.sampler_names)
            if hasattr(self, "pipeline_controls_panel"):
                panel = self.pipeline_controls_panel
                if hasattr(panel, "set_sampler_options"):
                    panel.set_sampler_options(self.sampler_names)
                elif hasattr(panel, "refresh_dynamic_lists_from_api"):
                    panel.refresh_dynamic_lists_from_api(self.client)
            self._add_log_message(f"✅ Loaded {len(samplers)} samplers from API")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to refresh samplers: {exc}")

    def _refresh_samplers_async(self):
        """Refresh the list of available samplers (thread-safe version)."""
        if self.client is None:
            # Schedule error message on main thread
            self.root.after(
                0,
                lambda: messagebox.showerror("Error", "API client not connected"),
            )
            return

        def worker():
            try:
                samplers = self.client.get_samplers()
                names = sorted(
                    {s.get("name", "") for s in samplers if s.get("name")},
                    key=str.lower,
                )
                # Keep a local cache if needed later
                self.sampler_names = list(names)

                def update_widgets():
                    self._add_log_message(f"✅ Loaded {len(samplers)} samplers from API")
                    if hasattr(self, "config_panel"):
                        self.config_panel.set_sampler_options(self.sampler_names)
                    if hasattr(self, "pipeline_controls_panel"):
                        panel = self.pipeline_controls_panel
                        if hasattr(panel, "set_sampler_options"):
                            panel.set_sampler_options(self.sampler_names)
                        elif hasattr(panel, "refresh_dynamic_lists_from_api"):
                            panel.refresh_dynamic_lists_from_api(self.client)

                self.root.after(0, update_widgets)
            except Exception as exc:
                self.root.after(
                    0,
                    lambda err=exc: messagebox.showerror(
                        "Error", f"Failed to refresh samplers: {err}"
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_upscalers(self):
        """Refresh the list of available upscalers (main thread version)"""
        if self.client is None:
            messagebox.showerror("Error", "API client not connected")
            return

        try:
            upscalers = self.client.get_upscalers()
            upscaler_names = sorted(
                {u.get("name", "") for u in upscalers if u.get("name")},
                key=str.lower,
            )
            self.upscaler_names = list(upscaler_names)
            if hasattr(self, "config_panel"):
                self.config_panel.set_upscaler_options(self.upscaler_names)
            if hasattr(self, "pipeline_controls_panel"):
                panel = self.pipeline_controls_panel
                if hasattr(panel, "set_upscaler_options"):
                    panel.set_upscaler_options(self.upscaler_names)
                elif hasattr(panel, "refresh_dynamic_lists_from_api"):
                    panel.refresh_dynamic_lists_from_api(self.client)
            if hasattr(self, "upscaler_combo"):
                self.upscaler_combo["values"] = tuple(self.upscaler_names)
            self._add_log_message(f"✅ Loaded {len(upscalers)} upscalers from API")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to refresh upscalers: {exc}")

    def _refresh_upscalers_async(self):
        """Refresh the list of available upscalers (thread-safe version)"""
        if self.client is None:
            # Schedule error message on main thread
            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
            return

        try:
            upscalers = self.client.get_upscalers()
            upscaler_names_local = sorted(
                {u.get("name", "") for u in upscalers if u.get("name")},
                key=str.lower,
            )
            self.upscaler_names = list(upscaler_names_local)

            def update_widgets():
                if hasattr(self, "upscaler_combo"):
                    self.upscaler_combo["values"] = tuple(self.upscaler_names)
                self._add_log_message(f"✅ Loaded {len(upscalers)} upscalers from API")
                if hasattr(self, "config_panel"):
                    self.config_panel.set_upscaler_options(self.upscaler_names)
                if hasattr(self, "pipeline_controls_panel"):
                    panel = self.pipeline_controls_panel
                    if hasattr(panel, "set_upscaler_options"):
                        panel.set_upscaler_options(self.upscaler_names)
                    elif hasattr(panel, "refresh_dynamic_lists_from_api"):
                        panel.refresh_dynamic_lists_from_api(self.client)

            self.root.after(0, update_widgets)

        except Exception as exc:
            # Marshal error message back to main thread
            # Capture exception in default argument to avoid closure issues
            self.root.after(
                0,
                lambda err=exc: messagebox.showerror(
                    "Error", f"Failed to refresh upscalers: {err}"
                ),
            )

    def _refresh_schedulers(self):
        """Refresh the list of available schedulers (main thread version)"""
        if not self.client:
            messagebox.showerror("Error", "API client not connected")
            return

        try:
            schedulers = self.client.get_schedulers()

            if hasattr(self, "config_panel"):
                self.config_panel.set_scheduler_options(schedulers)

            self.log_message(f"🔄 Loaded {len(schedulers)} schedulers")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh schedulers: {e}")

    def _refresh_schedulers_async(self):
        """Refresh the list of available schedulers (thread-safe version)"""
        from functools import partial

        if not self.client:
            # Schedule error message on main thread
            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
            return

        try:
            # Perform API call in worker thread
            schedulers = self.client.get_schedulers()

            # Store in instance attribute
            self.schedulers = list(schedulers)

            # Marshal widget updates back to main thread using partial
            def update_widgets():
                if hasattr(self, "scheduler_combo"):
                    self.scheduler_combo["values"] = tuple(self.schedulers)
                if hasattr(self, "img2img_scheduler_combo"):
                    self.img2img_scheduler_combo["values"] = tuple(self.schedulers)
                self._add_log_message(f"🔄 Loaded {len(self.schedulers)} schedulers")

            self.root.after(0, update_widgets)

            # Also update config panel if present using partial to capture value
            if hasattr(self, "config_panel"):
                self.root.after(
                    0, partial(self.config_panel.set_scheduler_options, list(self.schedulers))
                )

        except Exception as exc:
            # Marshal error message back to main thread
            # Capture exception in default argument to avoid closure issues
            self.root.after(
                0,
                lambda err=exc: messagebox.showerror(
                    "Error", f"Failed to refresh schedulers: {err}"
                ),
            )

    def _on_hires_toggle(self):
        """Handle hires.fix enable/disable toggle"""
        # This method can be used to enable/disable hires.fix related controls
        # For now, just log the change
        enabled = self.txt2img_vars.get("enable_hr", tk.BooleanVar()).get()
        self.log_message(f"📏 Hires.fix {'enabled' if enabled else 'disabled'}")

    def _randomize_seed(self, var_dict_name):
        """Generate a random seed for the specified variable dictionary"""
        import random

        random_seed = random.randint(1, 2147483647)  # Max int32 value
        var_dict = getattr(self, f"{var_dict_name}_vars", {})
        if "seed" in var_dict:
            var_dict["seed"].set(random_seed)
            self.log_message(f"🎲 Random seed generated: {random_seed}")

    def _randomize_txt2img_seed(self):
        """Generate random seed for txt2img"""
        self._randomize_seed("txt2img")

    def _randomize_img2img_seed(self):
        """Generate random seed for img2img"""
        self._randomize_seed("img2img")



```

## `src/gui/pipeline_controls_panel.py`

```
"""
Pipeline Controls Panel - UI component for configuring pipeline execution.
"""

import logging
import re
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PipelineControlsPanel(ttk.Frame):
    def get_settings(self) -> dict[str, Any]:
        """
        Return current toggles and loop/batch settings as a dictionary.
        """
        try:
            loop_count = int(self.loop_count_var.get())
        except ValueError:
            loop_count = 1

        try:
            images_per_prompt = int(self.images_per_prompt_var.get())
        except ValueError:
            images_per_prompt = 1

        return {
            "txt2img_enabled": bool(self.txt2img_enabled.get()),
            "img2img_enabled": bool(self.img2img_enabled.get()),
            "adetailer_enabled": bool(self.adetailer_enabled.get()),
            "upscale_enabled": bool(self.upscale_enabled.get()),
            "video_enabled": bool(self.video_enabled.get()),
            # Global negative per-stage toggles
            "apply_global_negative_txt2img": bool(self.global_neg_txt2img.get()),
            "apply_global_negative_img2img": bool(self.global_neg_img2img.get()),
            "apply_global_negative_upscale": bool(self.global_neg_upscale.get()),
            "apply_global_negative_adetailer": bool(self.global_neg_adetailer.get()),
            "loop_type": self.loop_type_var.get(),
            "loop_count": loop_count,
            "pack_mode": self.pack_mode_var.get(),
            "images_per_prompt": images_per_prompt,
            "model_matrix": self._parse_model_matrix(self.model_matrix_var.get()),
            "hypernetworks": self._parse_hypernetworks(self.hypernetworks_var.get()),
            "variant_mode": str(self.variant_mode_var.get()).strip().lower() or "fanout",
        }

    def get_state(self) -> dict:
        """
        Return the current state of the panel as a dictionary.
        Includes stage toggles, loop config, and batch config.
        """
        return {
            "txt2img_enabled": bool(self.txt2img_enabled.get()),
            "img2img_enabled": bool(self.img2img_enabled.get()),
            "adetailer_enabled": bool(self.adetailer_enabled.get()),
            "upscale_enabled": bool(self.upscale_enabled.get()),
            "video_enabled": bool(self.video_enabled.get()),
            "apply_global_negative_txt2img": bool(self.global_neg_txt2img.get()),
            "apply_global_negative_img2img": bool(self.global_neg_img2img.get()),
            "apply_global_negative_upscale": bool(self.global_neg_upscale.get()),
            "apply_global_negative_adetailer": bool(self.global_neg_adetailer.get()),
            "loop_type": self.loop_type_var.get(),
            "loop_count": int(self.loop_count_var.get()),
            "pack_mode": self.pack_mode_var.get(),
            "images_per_prompt": int(self.images_per_prompt_var.get()),
            "model_matrix": self._parse_model_matrix(self.model_matrix_var.get()),
            "hypernetworks": self._parse_hypernetworks(self.hypernetworks_var.get()),
            "variant_mode": str(self.variant_mode_var.get()),
        }

    def set_state(self, state: dict) -> None:
        """
        Restore the panel state from a dictionary.
        Ignores missing keys and type errors.
        """
        self._suspend_callbacks = True
        try:
            try:
                if "txt2img_enabled" in state:
                    self.txt2img_enabled.set(bool(state["txt2img_enabled"]))
                if "img2img_enabled" in state:
                    self.img2img_enabled.set(bool(state["img2img_enabled"]))
                if "adetailer_enabled" in state:
                    self.adetailer_enabled.set(bool(state["adetailer_enabled"]))
                if "upscale_enabled" in state:
                    self.upscale_enabled.set(bool(state["upscale_enabled"]))
                if "video_enabled" in state:
                    self.video_enabled.set(bool(state["video_enabled"]))
                if "apply_global_negative_txt2img" in state:
                    self.global_neg_txt2img.set(bool(state["apply_global_negative_txt2img"]))
                if "apply_global_negative_img2img" in state:
                    self.global_neg_img2img.set(bool(state["apply_global_negative_img2img"]))
                if "apply_global_negative_upscale" in state:
                    self.global_neg_upscale.set(bool(state["apply_global_negative_upscale"]))
                if "apply_global_negative_adetailer" in state:
                    self.global_neg_adetailer.set(bool(state["apply_global_negative_adetailer"]))
                if "loop_type" in state:
                    self.loop_type_var.set(str(state["loop_type"]))
                if "loop_count" in state:
                    self.loop_count_var.set(str(state["loop_count"]))
                if "pack_mode" in state:
                    self.pack_mode_var.set(str(state["pack_mode"]))
                if "images_per_prompt" in state:
                    self.images_per_prompt_var.set(str(state["images_per_prompt"]))
                if "model_matrix" in state:
                    self._set_model_matrix_display(state["model_matrix"])
                if "hypernetworks" in state:
                    self._set_hypernetwork_display(state["hypernetworks"])
                if "variant_mode" in state:
                    self.variant_mode_var.set(str(state["variant_mode"]))
            except Exception as e:
                logger.warning(f"PipelineControlsPanel: Failed to restore state: {e}")
        finally:
            self._suspend_callbacks = False

    def refresh_dynamic_lists_from_api(self, client) -> None:
        """Update cached sampler/upscaler lists from the API client."""

        if client is None:
            return

        try:
            sampler_entries = getattr(client, "samplers", []) or []
            sampler_names = [entry.get("name", "") for entry in sampler_entries if entry.get("name")]
            self.set_sampler_options(sampler_names)
        except Exception:
            logger.exception("PipelineControlsPanel: Failed to refresh sampler options from API")

        try:
            upscaler_entries = getattr(client, "upscalers", []) or []
            upscaler_names = [entry.get("name", "") for entry in upscaler_entries if entry.get("name")]
            self.set_upscaler_options(upscaler_names)
        except Exception:
            logger.exception("PipelineControlsPanel: Failed to refresh upscaler options from API")

    def set_sampler_options(self, sampler_names: list[str]) -> None:
        """Cache sampler names for future pipeline controls."""

        cleaned: list[str] = []
        for name in sampler_names or []:
            if not name:
                continue
            text = str(name).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        cleaned.sort(key=str.lower)
        self._sampler_options = cleaned

    def set_upscaler_options(self, upscaler_names: list[str]) -> None:
        """Cache upscaler names for future pipeline controls."""

        cleaned: list[str] = []
        for name in upscaler_names or []:
            if not name:
                continue
            text = str(name).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        cleaned.sort(key=str.lower)
        self._upscaler_options = cleaned

    """
    A UI panel for pipeline execution controls.

    This panel handles:
    - Loop configuration (single/stages/pipeline)
    - Loop count settings
    - Batch configuration (pack mode selection)
    - Images per prompt setting

    It exposes a get_settings() method to retrieve current configuration.
    """

    def __init__(
        self,
        parent: tk.Widget,
        initial_state: dict[str, Any] | None = None,
        stage_vars: dict[str, tk.BooleanVar] | None = None,
        show_variant_controls: bool = False,
        on_change: Callable[[], None] | None = None,
        **kwargs,
    ):
        """
        Initialize the PipelineControlsPanel.

        Args:
            parent: Parent widget
            initial_state: Optional dictionary used to pre-populate control values
            stage_vars: Optional mapping of existing stage BooleanVars
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)
        self.parent = parent
        self._initial_state = initial_state or {}
        self._stage_vars = stage_vars or {}
        self._show_variant_controls = show_variant_controls
        self._on_change = on_change
        self._suspend_callbacks = False
        self._trace_handles: list[tuple[tk.Variable, str]] = []
        self._sampler_options: list[str] = []
        self._upscaler_options: list[str] = []

        # Initialize control variables
        self._init_variables()

        # Build UI
        self._build_ui()
        self._bind_change_listeners()

    def _init_variables(self):
        """Initialize all control variables with defaults."""
        state = self._initial_state

        # Stage toggles
        self.txt2img_enabled = self._stage_vars.get("txt2img") or tk.BooleanVar(
            value=bool(state.get("txt2img_enabled", True))
        )
        self.img2img_enabled = self._stage_vars.get("img2img") or tk.BooleanVar(
            value=bool(state.get("img2img_enabled", True))
        )
        self.adetailer_enabled = self._stage_vars.get("adetailer") or tk.BooleanVar(
            value=bool(state.get("adetailer_enabled", False))
        )
        self.upscale_enabled = self._stage_vars.get("upscale") or tk.BooleanVar(
            value=bool(state.get("upscale_enabled", True))
        )
        self.video_enabled = self._stage_vars.get("video") or tk.BooleanVar(
            value=bool(state.get("video_enabled", False))
        )
        # Global negative per-stage toggles (default True for backward compatibility)
        self.global_neg_txt2img = tk.BooleanVar(
            value=bool(state.get("apply_global_negative_txt2img", True))
        )
        self.global_neg_img2img = tk.BooleanVar(
            value=bool(state.get("apply_global_negative_img2img", True))
        )
        self.global_neg_upscale = tk.BooleanVar(
            value=bool(state.get("apply_global_negative_upscale", True))
        )
        self.global_neg_adetailer = tk.BooleanVar(
            value=bool(state.get("apply_global_negative_adetailer", True))
        )

        # Loop configuration
        self.loop_type_var = tk.StringVar(value=str(state.get("loop_type", "single")))
        self.loop_count_var = tk.StringVar(value=str(state.get("loop_count", 1)))

        # Batch configuration
        self.pack_mode_var = tk.StringVar(value=str(state.get("pack_mode", "selected")))
        self.images_per_prompt_var = tk.StringVar(value=str(state.get("images_per_prompt", 1)))
        matrix_state = state.get("model_matrix", [])
        if isinstance(matrix_state, list):
            matrix_display = ", ".join(matrix_state)
        else:
            matrix_display = str(matrix_state)
        self.model_matrix_var = tk.StringVar(value=matrix_display)

        hyper_state = state.get("hypernetworks", [])
        if isinstance(hyper_state, list):
            hyper_display = ", ".join(
                f"{item.get('name')}:{item.get('strength', 1.0)}" for item in hyper_state if item
            )
        else:
            hyper_display = str(hyper_state)
        self.hypernetworks_var = tk.StringVar(value=hyper_display)
        self.variant_mode_var = tk.StringVar(value=str(state.get("variant_mode", "fanout")))

    def _build_ui(self):
        """Build the panel UI."""
        # Pipeline controls frame
        pipeline_frame = ttk.LabelFrame(
            self, text="🚀 Pipeline Controls", style="Dark.TLabelframe", padding=5
        )
        pipeline_frame.pack(fill=tk.BOTH, expand=True)

        # Loop configuration - compact
        self._build_loop_config(pipeline_frame)

        # Batch configuration - compact
        self._build_batch_config(pipeline_frame)
        if self._show_variant_controls:
            self._build_variant_config(pipeline_frame)
        self._build_global_negative_toggles(pipeline_frame)

    def _bind_change_listeners(self) -> None:
        """Attach variable traces to notify the host of user-driven changes."""
        if not self._on_change:
            return

        vars_to_watch: list[tk.Variable] = [
            self.loop_type_var,
            self.loop_count_var,
            self.pack_mode_var,
            self.images_per_prompt_var,
            self.model_matrix_var,
            self.hypernetworks_var,
            self.variant_mode_var,
            self.txt2img_enabled,
            self.img2img_enabled,
            self.adetailer_enabled,
            self.upscale_enabled,
            self.video_enabled,
            self.global_neg_txt2img,
            self.global_neg_img2img,
            self.global_neg_upscale,
            self.global_neg_adetailer,
        ]

        callback = lambda *_: self._notify_change()
        for var in vars_to_watch:
            try:
                handle = var.trace_add("write", callback)
                self._trace_handles.append((var, handle))
            except Exception:
                continue

    def _notify_change(self) -> None:
        if self._suspend_callbacks or not self._on_change:
            return
        try:
            self._on_change()
        except Exception:
            logger.debug("PipelineControlsPanel: change callback failed", exc_info=True)

    def _build_loop_config(self, parent):
        """Build loop configuration controls with logging."""
        loop_frame = ttk.LabelFrame(parent, text="Loop Config", style="Dark.TLabelframe", padding=5)
        loop_frame.pack(fill=tk.X, pady=(0, 5))

        def log_loop_type():
            logger.info(f"PipelineControlsPanel: loop_type set to {self.loop_type_var.get()}")

        ttk.Radiobutton(
            loop_frame,
            text="Single",
            variable=self.loop_type_var,
            value="single",
            style="Dark.TRadiobutton",
            command=log_loop_type,
        ).pack(anchor=tk.W, pady=1)

        ttk.Radiobutton(
            loop_frame,
            text="Loop stages",
            variable=self.loop_type_var,
            value="stages",
            style="Dark.TRadiobutton",
            command=log_loop_type,
        ).pack(anchor=tk.W, pady=1)

        ttk.Radiobutton(
            loop_frame,
            text="Loop pipeline",
            variable=self.loop_type_var,
            value="pipeline",
            style="Dark.TRadiobutton",
            command=log_loop_type,
        ).pack(anchor=tk.W, pady=1)

        # Loop count - inline
        count_frame = ttk.Frame(loop_frame, style="Dark.TFrame")
        count_frame.pack(fill=tk.X, pady=2)

        ttk.Label(count_frame, text="Count:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)

        def log_loop_count(*_):
            logger.info(f"PipelineControlsPanel: loop_count set to {self.loop_count_var.get()}")

        self.loop_count_var.trace_add("write", log_loop_count)
        count_spin = ttk.Spinbox(
            count_frame,
            from_=1,
            to=100,
            width=4,
            textvariable=self.loop_count_var,
            style="Dark.TSpinbox",
        )
        count_spin.pack(side=tk.LEFT, padx=2)

    def _build_batch_config(self, parent):
        """Build batch configuration controls with logging."""
        batch_frame = ttk.LabelFrame(
            parent, text="Batch Config", style="Dark.TLabelframe", padding=5
        )
        batch_frame.pack(fill=tk.X, pady=(0, 5))

        def log_pack_mode():
            logger.info(f"PipelineControlsPanel: pack_mode set to {self.pack_mode_var.get()}")

        ttk.Radiobutton(
            batch_frame,
            text="Selected packs",
            variable=self.pack_mode_var,
            value="selected",
            style="Dark.TRadiobutton",
            command=log_pack_mode,
        ).pack(anchor=tk.W, pady=1)

        ttk.Radiobutton(
            batch_frame,
            text="All packs",
            variable=self.pack_mode_var,
            value="all",
            style="Dark.TRadiobutton",
            command=log_pack_mode,
        ).pack(anchor=tk.W, pady=1)

        ttk.Radiobutton(
            batch_frame,
            text="Custom list",
            variable=self.pack_mode_var,
            value="custom",
            style="Dark.TRadiobutton",
            command=log_pack_mode,
        ).pack(anchor=tk.W, pady=1)

        # Images per prompt - inline
        images_frame = ttk.Frame(batch_frame, style="Dark.TFrame")
        images_frame.pack(fill=tk.X, pady=2)

        ttk.Label(images_frame, text="Images:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)

        def log_images_per_prompt(*_):
            logger.info(
                f"PipelineControlsPanel: images_per_prompt set to {self.images_per_prompt_var.get()}"
            )

        self.images_per_prompt_var.trace_add("write", log_images_per_prompt)
        images_spin = ttk.Spinbox(
            images_frame,
            from_=1,
            to=10,
            width=4,
            textvariable=self.images_per_prompt_var,
            style="Dark.TSpinbox",
        )
        images_spin.pack(side=tk.LEFT, padx=2)

    def _build_variant_config(self, parent):
        """Build controls for model/hypernetwork combinations."""
        variant_frame = ttk.LabelFrame(
            parent, text="Model Matrix & Hypernets", style="Dark.TLabelframe", padding=5
        )
        variant_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(
            variant_frame,
            text="Model checkpoints (comma/newline separated):",
            style="Dark.TLabel",
        ).pack(anchor=tk.W, pady=(0, 2))
        ttk.Entry(variant_frame, textvariable=self.model_matrix_var, width=40).pack(
            fill=tk.X, pady=(0, 4)
        )

        ttk.Label(
            variant_frame,
            text="Hypernetworks (name:strength, separated by commas):",
            style="Dark.TLabel",
        ).pack(anchor=tk.W, pady=(4, 2))
        ttk.Entry(variant_frame, textvariable=self.hypernetworks_var, width=40).pack(fill=tk.X)

        mode_frame = ttk.Frame(variant_frame, style="Dark.TFrame")
        mode_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(mode_frame, text="Variant strategy:", style="Dark.TLabel").pack(anchor=tk.W)
        ttk.Radiobutton(
            mode_frame,
            text="Fan-out (run every combo)",
            variable=self.variant_mode_var,
            value="fanout",
            style="Dark.TRadiobutton",
        ).pack(anchor=tk.W, pady=(2, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Rotate per prompt",
            variable=self.variant_mode_var,
            value="rotate",
            style="Dark.TRadiobutton",
        ).pack(anchor=tk.W, pady=(2, 0))

    def _build_global_negative_toggles(self, parent):
        """Build per-stage Global Negative enable toggles."""
        frame = ttk.LabelFrame(
            parent, text="Global Negative (per stage)", style="Dark.TLabelframe", padding=5
        )
        frame.pack(fill=tk.X, pady=(0, 5))

        def _mk(cb_text, var, key):
            def _log():
                logger.info(f"PipelineControlsPanel: {key} set to {var.get()}")

            ttk.Checkbutton(
                frame, text=cb_text, variable=var, style="Dark.TCheckbutton", command=_log
            ).pack(anchor=tk.W)

        _mk("Apply to txt2img", self.global_neg_txt2img, "apply_global_negative_txt2img")
        _mk("Apply to img2img", self.global_neg_img2img, "apply_global_negative_img2img")
        _mk("Apply to upscale", self.global_neg_upscale, "apply_global_negative_upscale")
        _mk("Apply to ADetailer", self.global_neg_adetailer, "apply_global_negative_adetailer")

    def set_settings(self, settings: dict[str, Any]):
        """
        Set pipeline control settings from a dictionary.

        Args:
            settings: Dictionary containing pipeline settings
        """
        if "txt2img_enabled" in settings:
            self.txt2img_enabled.set(settings["txt2img_enabled"])
        if "img2img_enabled" in settings:
            self.img2img_enabled.set(settings["img2img_enabled"])
        if "adetailer_enabled" in settings:
            self.adetailer_enabled.set(settings["adetailer_enabled"])
        if "upscale_enabled" in settings:
            self.upscale_enabled.set(settings["upscale_enabled"])
        if "video_enabled" in settings:
            self.video_enabled.set(settings["video_enabled"])

        if "loop_type" in settings:
            self.loop_type_var.set(settings["loop_type"])
        if "loop_count" in settings:
            self.loop_count_var.set(str(settings["loop_count"]))

        if "pack_mode" in settings:
            self.pack_mode_var.set(settings["pack_mode"])
        if "images_per_prompt" in settings:
            self.images_per_prompt_var.set(str(settings["images_per_prompt"]))
        if "model_matrix" in settings:
            self._set_model_matrix_display(settings["model_matrix"])
        if "hypernetworks" in settings:
            self._set_hypernetwork_display(settings["hypernetworks"])
        if "variant_mode" in settings:
            self.variant_mode_var.set(str(settings["variant_mode"]))

    def apply_config(self, cfg: dict[str, Any]) -> None:
        """Apply a configuration payload (e.g., from packs/presets) to the controls."""
        if not cfg:
            return

        target = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else cfg
        if not isinstance(target, dict):
            return

        self._suspend_callbacks = True
        try:
            self.set_settings(target)
        finally:
            self._suspend_callbacks = False

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_model_matrix(self, raw: str) -> list[str]:
        if not raw:
            return []
        values: list[str] = []
        for chunk in re.split(r"[\n,]+", raw):
            sanitized = chunk.strip()
            if sanitized:
                values.append(sanitized)
        return values

    def _parse_hypernetworks(self, raw: str) -> list[dict[str, Any]]:
        if not raw:
            return []
        entries: list[dict[str, Any]] = []
        for chunk in re.split(r"[\n,]+", raw):
            sanitized = chunk.strip()
            if not sanitized:
                continue
            if ":" in sanitized:
                name, strength = sanitized.split(":", 1)
                try:
                    weight = float(strength.strip())
                except ValueError:
                    weight = 1.0
                entries.append({"name": name.strip(), "strength": weight})
            else:
                entries.append({"name": sanitized, "strength": 1.0})
        return entries

    def _set_model_matrix_display(self, value):
        if isinstance(value, list):
            self.model_matrix_var.set(", ".join(value))
        else:
            self.model_matrix_var.set(str(value))

    def _set_hypernetwork_display(self, value):
        if isinstance(value, list):
            self.hypernetworks_var.set(
                ", ".join(
                    f"{item.get('name')}:{item.get('strength', 1.0)}"
                    for item in value
                    if item and item.get("name")
                )
            )
        else:
            self.hypernetworks_var.set(str(value))

```

## `src/gui/prompt_pack_list_manager.py`

```
"""
Manages loading, saving, and editing custom prompt pack lists.
"""

import json
from pathlib import Path


class PromptPackListManager:
    """Manages loading, saving, and editing custom prompt pack lists."""

    def __init__(self, file_path: str = "custom_pack_lists.json"):
        """
        Initializes the list manager.

        Args:
            file_path: The path to the JSON file storing the lists.
        """
        self.file_path = Path(file_path)
        self.lists: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        """Loads the lists from the JSON file if it exists."""
        if self.file_path.exists():
            try:
                with self.file_path.open("r", encoding="utf-8") as f:
                    # Ensure we handle empty files
                    content = f.read()
                    if not content:
                        return {}
                    return json.loads(content)
            except (OSError, json.JSONDecodeError):
                # If file is corrupted or unreadable, start fresh
                return {}
        return {}

    def _save(self) -> bool:
        """Saves the current lists to the JSON file."""
        try:
            with self.file_path.open("w", encoding="utf-8") as f:
                json.dump(self.lists, f, indent=2, ensure_ascii=False)
            return True
        except OSError:
            return False

    def get_list_names(self) -> list[str]:
        """Returns a sorted list of all custom list names."""
        return sorted(self.lists.keys())

    def get_list(self, name: str) -> list[str] | None:
        """
        Retrieves a specific list of packs by its name.

        Args:
            name: The name of the list to retrieve.

        Returns:
            A list of pack names, or None if the list doesn't exist.
        """
        return self.lists.get(name)

    def save_list(self, name: str, packs: list[str]) -> bool:
        """
        Saves or updates a list of packs.

        Args:
            name: The name of the list.
            packs: A list of pack file names.

        Returns:
            True if saving was successful, False otherwise.
        """
        if not name or not isinstance(packs, list):
            return False
        self.lists[name] = sorted(packs)  # Store sorted for consistency
        return self._save()

    def delete_list(self, name: str) -> bool:
        """
        Deletes a list by its name.

        Args:
            name: The name of the list to delete.

        Returns:
            True if the list was deleted and saved, False otherwise.
        """
        if name in self.lists:
            del self.lists[name]
            return self._save()
        return False

    def refresh(self):
        """Reloads the lists from the file."""
        self.lists = self._load()

```

## `src/gui/prompt_pack_panel.py`

```
import logging
import os
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from ..utils.file_io import get_prompt_packs
from .theme import ASWF_BLACK, ASWF_DARK_GREY, ASWF_GOLD
from .tooltip import Tooltip


"""
Prompt Pack Panel - UI component for managing and selecting prompt packs.
"""

logger = logging.getLogger(__name__)


class PromptPackPanel(ttk.Frame):
    def tk_safe_call(self, func, *args, wait=False, **kwargs):
        # (removed local imports; all imports are now at the top of the file)
        if threading.current_thread() is threading.main_thread():
            return func(*args, **kwargs)
        if not wait:
            self.after(0, lambda: func(*args, **kwargs))
            return None
        q: queue.Queue = queue.Queue(maxsize=1)

        def wrapper():
            try:
                q.put(func(*args, **kwargs))
            except Exception as e:
                q.put(e)

        self.after(0, wrapper)
        try:
            result = q.get(timeout=2)
        except queue.Empty:
            logging.error(
                "tk_safe_call: main thread did not process scheduled call within 2 seconds; possible deadlock."
            )
            return None
        if isinstance(result, Exception):
            raise result
        return result

    """
    A UI panel for managing and selecting prompt packs.

    This panel handles:
    - Displaying available prompt packs
    - Multi-select listbox for pack selection
    - Custom pack lists (save/load/edit/delete)
    - Refresh and advanced editor integration

    It communicates with a coordinator via callbacks for selection changes.
    """

    def __init__(
        self,
        parent: tk.Widget,
        coordinator: object | None = None,
        list_manager: object | None = None,
        on_selection_changed: Callable[[list[str]], None] | None = None,
        on_advanced_editor: Callable[[], None] | None = None,
        **kwargs,
    ):
        logger.debug("PromptPackPanel: init start")
        """
        Initialize the PromptPackPanel.

        Args:
            parent: Parent widget
            coordinator: Coordinator object (for mediator pattern)
            list_manager: PromptPackListManager instance for custom lists
            on_selection_changed: Callback when pack selection changes, receives list of selected pack names
            on_advanced_editor: Callback to open advanced editor
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.coordinator = coordinator
        self.list_manager = list_manager
        self._on_selection_changed = on_selection_changed
        self._on_advanced_editor = on_advanced_editor

        # Internal state
        self._last_selected_pack: str | None = None
        self._last_selection: list[str] = []
        self._suppress_selection_callbacks = False
        self._is_handling_selection = False

        # Build UI
        self._build_ui()

        # Load initial packs
        self.refresh_packs(silent=True)
        logger.debug("PromptPackPanel: initial refresh complete")

    def _attach_tooltip(self, widget: tk.Widget, text: str, delay: int = 1500) -> None:
        """Best-effort tooltip attachment that won't crash headless tests."""
        try:
            Tooltip(widget, text, delay=delay)
        except Exception:
            pass

    def _build_ui(self):
        """Build the panel UI."""
        # Prompt packs section - compact
        packs_frame = ttk.LabelFrame(self, text="📝 Prompt Packs", style="Dark.TLabelframe", padding=5)
        packs_frame.pack(fill=tk.BOTH, expand=True)

        # Compact list management
        self._build_list_management(packs_frame)

        # Multi-select listbox for prompt packs
        self._build_packs_listbox(packs_frame)

        # Pack management buttons
        self._build_pack_buttons(packs_frame)

    def _build_list_management(self, parent):
        """Build custom list management controls."""
        list_mgmt_frame = ttk.Frame(parent, style="Dark.TFrame")
        list_mgmt_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(list_mgmt_frame, text="Lists:", style="Dark.TLabel").pack(side=tk.LEFT)

        self.saved_lists_var = tk.StringVar()
        self.saved_lists_combo = ttk.Combobox(
            list_mgmt_frame,
            textvariable=self.saved_lists_var,
            style="Dark.TCombobox",
            width=24,
            state="readonly",
        )
        self.saved_lists_combo.pack(side=tk.LEFT, padx=(3, 2))

        # Update combo values if list_manager is available
        if self.list_manager:
            self.saved_lists_combo["values"] = self.list_manager.get_list_names()

        # Compact button layout
        btn_frame = ttk.Frame(list_mgmt_frame, style="Dark.TFrame")
        btn_frame.pack(side=tk.LEFT, padx=(3, 0))

        load_btn = ttk.Button(
            btn_frame, text="📁", command=self._load_pack_list, style="Dark.TButton", width=3
        )
        load_btn.grid(row=0, column=0, padx=1)
        self._attach_tooltip(
            load_btn,
            "Apply the packs stored in the selected list. Current selection is replaced.",
        )

        save_btn = ttk.Button(
            btn_frame, text="💾", command=self._save_pack_list, style="Dark.TButton", width=3
        )
        save_btn.grid(row=0, column=1, padx=1)
        self._attach_tooltip(
            save_btn,
            "Save the currently highlighted packs as a reusable list for future runs.",
        )

        edit_btn = ttk.Button(
            btn_frame, text="✏️", command=self._edit_pack_list, style="Dark.TButton", width=3
        )
        edit_btn.grid(row=0, column=2, padx=1)
        self._attach_tooltip(
            edit_btn,
            "Load the saved list into the selector so you can adjust it before saving again.",
        )

        delete_btn = ttk.Button(
            btn_frame, text="🗑️", command=self._delete_pack_list, style="Dark.TButton", width=3
        )
        delete_btn.grid(row=0, column=3, padx=1)
        self._attach_tooltip(
            delete_btn, "Remove the saved list entry (does not delete pack files)."
        )

    def _build_packs_listbox(self, parent):
        """Build the packs listbox with scrollbar."""
        packs_list_frame = ttk.Frame(parent, style="Dark.TFrame")
        packs_list_frame.pack(fill=tk.BOTH, expand=True)

        # Listbox with scrollbar
        listbox_frame = tk.Frame(packs_list_frame, bg=ASWF_DARK_GREY)
        listbox_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(listbox_frame, bg=ASWF_DARK_GREY, troughcolor=ASWF_BLACK)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.packs_listbox = tk.Listbox(
            listbox_frame,
            selectmode=tk.EXTENDED,
            yscrollcommand=scrollbar.set,
            exportselection=False,
            borderwidth=2,
            highlightthickness=1,
            highlightcolor=ASWF_GOLD,
            activestyle="dotbox",
        )
        # Apply theme styling
        from .theme import Theme

        theme = Theme()
        theme.style_listbox(self.packs_listbox)
        self.packs_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.packs_listbox.yview)
        self._attach_tooltip(
            self.packs_listbox,
            "Ctrl/Cmd-click or Shift-click to select multiple packs. Selection persists even when focus changes.",
        )

        # Bind selection events (use lambda + add to avoid clobbering default virtual bindings)
        self.packs_listbox.bind("<<ListboxSelect>>", self._on_pack_selection_changed, add="+")

    def _build_pack_buttons(self, parent):
        """Build pack management buttons."""
        pack_buttons_frame = ttk.Frame(parent, style="Dark.TFrame")
        pack_buttons_frame.pack(pady=(10, 0))

        refresh_btn = ttk.Button(
            pack_buttons_frame,
            text="🔄 Refresh Packs",
            command=lambda: self.refresh_packs(silent=False),
            style="Dark.TButton",
        )
        refresh_btn.pack(side=tk.LEFT, padx=(0, 5))
        self._attach_tooltip(
            refresh_btn,
            "Rescan the packs folder and keep any current selection when possible.",
        )

        if self._on_advanced_editor:
            editor_btn = ttk.Button(
                pack_buttons_frame,
                text="✏️ Advanced Editor",
                command=self._on_advanced_editor,
                style="Dark.TButton",
            )
            editor_btn.pack(side=tk.LEFT)
            self._attach_tooltip(
                editor_btn,
                "Open the Advanced Prompt Editor for the first selected pack (multi-select safe).",
            )

    def _on_pack_selection_changed(self, event: object = None) -> None:
        if self._suppress_selection_callbacks:
            logger.debug("PromptPackPanel: selection change suppressed")
            return

        selected_indices = list(self.packs_listbox.curselection())
        selected_packs = [self.packs_listbox.get(i) for i in selected_indices]

        if selected_packs == self._last_selection:
            return
        self._last_selection = list(selected_packs)
        self._last_selected_pack = selected_packs[0] if selected_packs else None

        self._update_selection_highlights(selected_indices)

        if selected_packs:
            logger.info("PromptPackPanel: pack selection changed: %s", selected_packs)
        else:
            logger.info("PromptPackPanel: no pack selected")

        if self._on_selection_changed:
            try:
                self._on_selection_changed(selected_packs)
            except Exception:
                logger.exception("PromptPackPanel: selection callback failed")

    def _update_selection_highlights(self, selected_indices: list[int] | None = None):
        """Update visual highlighting for selected items."""
        if threading.current_thread() is not threading.main_thread():
            self.after(0, lambda: self._update_selection_highlights(selected_indices))
            return
        size = self.packs_listbox.size()
        for i in range(size):
            self.packs_listbox.itemconfig(i, {"bg": "#3d3d3d"})
        if selected_indices is None:
            selected_indices = list(self.packs_listbox.curselection())
        for index in selected_indices:
            self.packs_listbox.itemconfig(index, {"bg": "#0078d4"})

    def refresh_packs(self, silent: bool = False) -> None:
        """
        Refresh the prompt packs list from the packs directory.
        Args:
            silent: If True, don't log the refresh action
        """
        packs_dir = Path("packs")
        pack_files = get_prompt_packs(packs_dir)
        # Save current selection
        current_selection = self.get_selected_packs()
        # Clear and repopulate
        self.tk_safe_call(self.packs_listbox.delete, 0, tk.END)
        for pack_file in pack_files:
            self.packs_listbox.insert(tk.END, pack_file.name)
        # Restore selection if possible
        if current_selection:
            size = self.tk_safe_call(self.packs_listbox.size, wait=True)
            for i in range(size):
                pack_name = self.tk_safe_call(self.packs_listbox.get, i, wait=True)
                if pack_name in current_selection:
                    self.packs_listbox.selection_set(i)
        if not silent:
            logger.info(f"PromptPackPanel: Refreshed, found {len(pack_files)} prompt packs.")

    def populate(self, packs: list[Path] | list[str]) -> None:
        """Populate the listbox with provided pack entries on the Tk thread.

        Args:
            packs: List of Path or str representing pack files
        """
        # Normalize to names
        names: list[str] = []
        for p in packs:
            try:
                names.append(p.name if isinstance(p, Path) else str(p))
            except Exception:
                continue

        # Preserve selection
        current_selection = self.get_selected_packs()
        self.tk_safe_call(self.packs_listbox.delete, 0, tk.END)
        for name in names:
            self.packs_listbox.insert(tk.END, name)
        if current_selection:
            size = self.tk_safe_call(self.packs_listbox.size, wait=True)
            for i in range(size):
                pack_name = self.tk_safe_call(self.packs_listbox.get, i, wait=True)
                if pack_name in current_selection:
                    self.packs_listbox.selection_set(i)
        logger.debug("PromptPackPanel: populated %s packs (async)", len(names))

    def get_selected_packs(self) -> list[str]:
        """
        Get list of currently selected pack names.
        Returns:
            List of selected pack names
        """
        selected_indices = self.tk_safe_call(self.packs_listbox.curselection)
        return [self.packs_listbox.get(i) for i in selected_indices]

    def set_selected_packs(self, pack_names: list[str]) -> None:
        """
        Set the selected packs by name.
        Args:
            pack_names: List of pack names to select
        """
        if threading.current_thread() is not threading.main_thread():
            self.after(0, lambda: self.set_selected_packs(pack_names))
            return

        desired = {str(name) for name in pack_names}
        selected_indices: list[int] = []
        self._suppress_selection_callbacks = True
        try:
            self.packs_listbox.selection_clear(0, tk.END)
            for i in range(self.packs_listbox.size()):
                pack_name = self.packs_listbox.get(i)
                if pack_name in desired:
                    self.packs_listbox.selection_set(i)
                    selected_indices.append(i)
            if selected_indices:
                self.packs_listbox.activate(selected_indices[0])
            elif self.packs_listbox.size() > 0:
                self.packs_listbox.activate(0)
            self._update_selection_highlights(selected_indices)
        finally:
            self._suppress_selection_callbacks = False

        logger.debug("PromptPackPanel: set_selected_packs -> %s", pack_names)
        self._on_pack_selection_changed()

    def select_first_pack(self) -> None:
        """Select the first pack if available."""
        size = self.tk_safe_call(self.packs_listbox.size)
        if size > 0:
            first_name = self.packs_listbox.get(0)
            self.set_selected_packs([first_name])
            logger.debug("PromptPackPanel: first pack selected via helper")

    def _load_pack_list(self):
        """Load saved pack list."""
        if not self.list_manager:
            messagebox.showwarning("No Manager", "List manager not configured")
            return

        list_name = self.saved_lists_var.get()
        if not list_name:
            return

        pack_list = self.list_manager.get_list(list_name)
        if pack_list is None:
            return

        # Set selection to the packs in the list
        self.set_selected_packs(pack_list)
        logger.info(f"Loaded pack list: {list_name}")

    def _save_pack_list(self):
        """Save current pack selection as list."""
        if not self.list_manager:
            messagebox.showwarning("No Manager", "List manager not configured")
            return
        selected_packs = self.get_selected_packs()
        if not selected_packs:
            messagebox.showwarning("No Selection", "Please select prompt packs first")
            return

        list_name = simpledialog.askstring("Save List", "Enter list name:")
        if not list_name:
            return

        if self.list_manager.save_list(list_name, selected_packs):
            # Update combo box
            self.saved_lists_combo["values"] = self.list_manager.get_list_names()
            logger.info(f"Saved pack list: {list_name}")
            messagebox.showinfo("Success", f"List '{list_name}' saved successfully")
        else:
            messagebox.showerror("Save Error", "Failed to save list")

    def _edit_pack_list(self):
        """Edit existing pack list."""
        if not self.list_manager:
            messagebox.showwarning("No Manager", "List manager not configured")
            return

        list_name = self.saved_lists_var.get()
        if not list_name:
            messagebox.showinfo("No List Selected", "Please select a list to edit")
            return

        # Load the list for editing
        self._load_pack_list()
        messagebox.showinfo(
            "Edit Mode",
            f"List '{list_name}' loaded for editing.\n" "Modify selection and save to update.",
        )

    def _delete_pack_list(self):
        """Delete saved pack list."""
        if not self.list_manager:
            messagebox.showwarning("No Manager", "List manager not configured")
            return

        list_name = self.saved_lists_var.get()
        if not list_name:
            return

        if messagebox.askyesno("Confirm Delete", f"Delete list '{list_name}'?"):
            if self.list_manager.delete_list(list_name):
                # Update combo box
                self.saved_lists_combo["values"] = self.list_manager.get_list_names()
                self.saved_lists_var.set("")
                logger.info(f"Deleted pack list: {list_name}")
                messagebox.showinfo("Success", f"List '{list_name}' deleted")
            else:
                messagebox.showerror("Delete Error", "Failed to delete list")

```

## `src/gui/scrolling.py`

```
"""Shared helpers for scrollable Tk/ttk containers."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


SCROLL_CANVAS_BG = "#2B2A2C"


def enable_mousewheel(widget: tk.Widget) -> None:
    """Enable mousewheel scrolling for the given widget in a cross-platform way."""

    def _on_mousewheel(event):
        delta = event.delta
        if delta == 0 and getattr(event, "num", None) in (4, 5):
            delta = 120 if event.num == 4 else -120
        step = int(-1 * (delta / 120))
        try:
            widget.yview_scroll(step, "units")
        except Exception:
            return
        return "break"

    def _bind(_event):
        widget.bind_all("<MouseWheel>", _on_mousewheel)
        widget.bind_all("<Button-4>", _on_mousewheel)
        widget.bind_all("<Button-5>", _on_mousewheel)

    def _unbind(_event):
        widget.unbind_all("<MouseWheel>")
        widget.unbind_all("<Button-4>")
        widget.unbind_all("<Button-5>")

    widget.bind("<Enter>", _bind, add="+")
    widget.bind("<Leave>", _unbind, add="+")


def make_scrollable(parent: tk.Widget, *, style: str = "Dark.TFrame") -> tuple[tk.Canvas, tk.Frame]:
    """Create a scrollable region inside *parent* using a canvas + frame + scrollbar."""

    canvas = tk.Canvas(parent, bg=SCROLL_CANVAS_BG, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas, style=style)

    window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

    def _on_frame_config(_event):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_config(event):
        canvas.itemconfigure(window_id, width=event.width)

    scrollable_frame.bind("<Configure>", _on_frame_config)
    canvas.bind("<Configure>", _on_canvas_config)
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    enable_mousewheel(canvas)

    # Expose scrollbar for callers/tests when needed
    canvas._vertical_scrollbar = scrollbar  # type: ignore[attr-defined]
    scrollable_frame._vertical_scrollbar = scrollbar  # type: ignore[attr-defined]

    return canvas, scrollable_frame

```

## `src/gui/stage_chooser.py`

```
"""Stage chooser modal for per-image pipeline stage selection."""

import logging
import queue
import tkinter as tk
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

from .theme import Theme

logger = logging.getLogger(__name__)


class StageChoice(Enum):
    """Available stage choices for processing."""

    IMG2IMG = "img2img"
    ADETAILER = "adetailer"
    UPSCALE = "upscale"
    NONE = "none"


class StageChooser:
    """Non-blocking modal for choosing next pipeline stage per image.

    This modal displays after txt2img generation and allows the user to choose
    which processing stages to apply to each image. Communication happens via
    a Queue to avoid blocking the main Tk event loop.
    """

    def __init__(
        self,
        # Prefer the more typical tkinter "parent" naming used by tests,
        # but keep backward compatibility with code that passed "root".
        parent: tk.Misc | None = None,
        image_path: Path | None = None,
        image_index: int = 1,
        total_images: int = 1,
        result_queue: queue.Queue | None = None,
        on_retune: Callable | None = None,
        # Back-compat: allow callers to still pass root, but tests use parent
        root: tk.Misc | None = None,
    ):
        """Initialize stage chooser modal.

        Args:
            parent: Parent Tk widget/window (preferred)
            image_path: Path to the generated image to preview
            image_index: Current image number (1-based)
            total_images: Total number of images in batch
            result_queue: Queue to send choice results to
            on_retune: Optional callback for re-tuning settings
        """
        # Resolve parent/root with backwards compatibility
        self.root = parent or root  # type: ignore[assignment]
        if self.root is None:
            # Create a default root if none provided (useful for ad-hoc calls/tests)
            self.root = tk.Tk()

        # Store core parameters (with sensible defaults for tests)
        self.image_path = image_path or Path("")
        self.image_index = image_index
        self.total_images = total_images
        self.result_queue = result_queue or queue.Queue()
        self.on_retune_callback = on_retune

        self.selected_choice: StageChoice | None = None
        self.apply_to_batch: bool = False

        # Create modal window
        self.window = tk.Toplevel(self.root)
        self.window.title(f"Choose Next Stage - Image {image_index} of {total_images}")
        self.window.geometry("700x600")
        self.window.configure(bg="#2b2b2b")

        # Make modal
        self.window.transient(root)
        self.window.grab_set()

        # Batch toggle variable
        self.batch_var = tk.BooleanVar(value=False)

        # Build UI
        self._build_ui()

        # Load and display preview
        self._load_preview()

        # Center window
        self._center_window()

        # Handle window close
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build_ui(self):
        """Build the chooser UI."""
        main_frame = ttk.Frame(self.window, style="Dark.TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Apply dark theme
        self._apply_dark_theme()

        # Header
        self._build_header(main_frame)

        # Preview area
        self._build_preview(main_frame)

        # Choice buttons
        self._build_choices(main_frame)

        # Batch toggle
        self._build_batch_toggle(main_frame)

        # Action buttons
        self._build_actions(main_frame)

    def _apply_dark_theme(self):
        """Apply dark theme to widgets."""
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.TFrame", background="#2b2b2b")
        style.configure("Dark.TLabel", background="#2b2b2b", foreground="white")
        style.configure("Dark.TButton", background="#404040", foreground="white")
        style.configure("Dark.TCheckbutton", background="#2b2b2b", foreground="white")

    def _build_header(self, parent):
        """Build header with title and info."""
        header_frame = ttk.Frame(parent, style="Dark.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 15))

        title = ttk.Label(
            header_frame,
            text="Choose Next Processing Stage",
            style="Dark.TLabel",
            font=("Segoe UI", 14, "bold"),
        )
        title.pack(anchor=tk.W)

        info = ttk.Label(
            header_frame,
            text=f"Select how to process this image (Image {self.image_index} of {self.total_images})",
            style="Dark.TLabel",
            font=("Segoe UI", 10),
        )
        info.pack(anchor=tk.W, pady=(5, 0))

    def _build_preview(self, parent):
        """Build image preview area."""
        preview_frame = ttk.Frame(parent, style="Dark.TFrame")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Preview label
        self.preview_label = ttk.Label(
            preview_frame, text="Loading preview...", style="Dark.TLabel", anchor=tk.CENTER
        )
        self.preview_label.pack(fill=tk.BOTH, expand=True)

    def _build_choices(self, parent):
        """Build stage choice buttons."""
        choices_frame = ttk.LabelFrame(parent, text="Processing Options", style="Dark.TLabelframe")
        choices_frame.pack(fill=tk.X, pady=(0, 15))

        # Grid layout for buttons
        btn_frame = ttk.Frame(choices_frame, style="Dark.TFrame")
        btn_frame.pack(padx=10, pady=10)

        # img2img button
        img2img_btn = tk.Button(
            btn_frame,
            text="🎨 img2img\n(Cleanup/Refine)",
            font=("Calibri", 11, "bold"),
            width=18,
            height=3,
            command=lambda: self._select_choice(StageChoice.IMG2IMG),
        )
        Theme().style_button_primary(img2img_btn)
        img2img_btn.grid(row=0, column=0, padx=5, pady=5)

        # ADetailer button
        adetailer_btn = tk.Button(
            btn_frame,
            text="✨ ADetailer\n(Face/Detail Fix)",
            font=("Calibri", 11, "bold"),
            width=18,
            height=3,
            command=lambda: self._select_choice(StageChoice.ADETAILER),
        )
        Theme().style_button_primary(adetailer_btn)
        adetailer_btn.grid(row=0, column=1, padx=5, pady=5)

        # Upscale button
        upscale_btn = tk.Button(
            btn_frame,
            text="🔍 Upscale\n(Enhance Quality)",
            font=("Calibri", 11, "bold"),
            width=18,
            height=3,
            command=lambda: self._select_choice(StageChoice.UPSCALE),
        )
        Theme().style_button_primary(upscale_btn)
        upscale_btn.grid(row=1, column=0, padx=5, pady=5)

        # None button
        none_btn = tk.Button(
            btn_frame,
            text="⏭️ None\n(Skip to Next)",
            font=("Calibri", 11, "bold"),
            width=18,
            height=3,
            command=lambda: self._select_choice(StageChoice.NONE),
        )
        Theme().style_button_primary(none_btn)
        none_btn.grid(row=1, column=1, padx=5, pady=5)

    def _build_batch_toggle(self, parent):
        """Build batch application toggle."""
        batch_frame = ttk.Frame(parent, style="Dark.TFrame")
        batch_frame.pack(fill=tk.X, pady=(0, 15))

        batch_check = ttk.Checkbutton(
            batch_frame,
            text="Apply this choice to all remaining images in this batch",
            variable=self.batch_var,
            style="Dark.TCheckbutton",
        )
        batch_check.pack(anchor=tk.W)

        # Show only if there are more images
        if self.image_index >= self.total_images:
            batch_check.configure(state="disabled")

    def _build_actions(self, parent):
        """Build action buttons."""
        action_frame = ttk.Frame(parent, style="Dark.TFrame")
        action_frame.pack(fill=tk.X)

        # Re-tune settings link (if callback provided)
        if self.on_retune_callback:
            retune_btn = tk.Button(
                action_frame,
                text="⚙️ Re-tune Settings",
                font=("Calibri", 10, "underline"),
                relief=tk.FLAT,
                cursor="hand2",
                command=self._on_retune,
            )
            Theme().style_button_primary(retune_btn)
            retune_btn.pack(side=tk.LEFT)

        # Cancel button
        cancel_btn = tk.Button(
            action_frame,
            text="Cancel Remaining",
            font=("Calibri", 10),
            command=self._on_cancel,
        )
        Theme().style_button_danger(cancel_btn)
        cancel_btn.pack(side=tk.RIGHT, padx=(10, 0))

    def _load_preview(self):
        """Load and display image preview."""
        try:
            if not self.image_path.exists():
                self.preview_label.config(text="Image not found")
                return

            # Load image
            img = Image.open(self.image_path)

            # Calculate scaling to fit in preview area (max 400x400)
            max_size = 400
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(img)

            # Update label
            self.preview_label.config(image=photo, text="")
            self.preview_label.image = photo  # Keep reference

        except Exception as e:
            logger.error(f"Error loading preview image: {e}")
            self.preview_label.config(text="Error loading preview")

    def _center_window(self):
        """Center window on screen."""
        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (width // 2)
        y = (self.window.winfo_screenheight() // 2) - (height // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _select_choice(self, choice: StageChoice):
        """Handle stage choice selection.

        Args:
            choice: Selected stage choice
        """
        self.selected_choice = choice
        self.apply_to_batch = self.batch_var.get()

        # Send result to queue
        result = {
            "choice": choice,
            "apply_to_batch": self.apply_to_batch,
            "cancelled": False,
            "image_index": self.image_index,
        }
        self.result_queue.put(result)

        logger.info(
            f"Stage choice: {choice.value} "
            f"(batch={self.apply_to_batch}, image={self.image_index})"
        )

        # Close window
        self._close()

    def _on_cancel(self):
        """Handle cancel action."""
        result = {
            "choice": None,
            "apply_to_batch": False,
            "cancelled": True,
            "image_index": self.image_index,
        }
        self.result_queue.put(result)

        logger.info("Stage chooser cancelled")
        self._close()

    def _on_retune(self):
        """Handle re-tune settings action."""
        if self.on_retune_callback:
            self.on_retune_callback()

        # Don't close window - let user adjust and come back

    def _close(self):
        """Close the modal window."""
        try:
            self.window.grab_release()
            self.window.destroy()
        except Exception as e:
            logger.error(f"Error closing stage chooser window: {e}")

```

## `src/gui/state.py`

```
"""GUI state management with state machine pattern."""

import logging
import threading
from collections.abc import Callable
from enum import Enum, auto

logger = logging.getLogger(__name__)


class GUIState(Enum):
    """GUI application states."""

    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


class CancellationError(Exception):
    """Raised when operation is cancelled by user."""

    pass


class CancelToken:
    """Thread-safe cancellation token for cooperative cancellation."""

    def __init__(self):
        """Initialize cancel token."""
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Request cancellation."""
        with self._lock:
            self._cancelled.set()
            logger.info("Cancellation requested")

    def is_cancelled(self) -> bool:
        """Check if cancellation was requested.

        Returns:
            True if cancelled, False otherwise
        """
        return self._cancelled.is_set()

    def check_cancelled(self) -> None:
        """Check if cancelled and raise exception if so.

        Raises:
            CancellationError: If cancellation was requested
        """
        if self._cancelled.is_set():
            raise CancellationError("Operation cancelled by user")

    def reset(self) -> None:
        """Reset the cancellation token for reuse."""
        with self._lock:
            self._cancelled.clear()


class StateManager:
    """Manages application state transitions with callbacks."""

    def __init__(self, initial_state: GUIState = GUIState.IDLE):
        """Initialize state manager."""
        self._state = initial_state
        self._lock = threading.Lock()
        self._callbacks: dict[GUIState, list[Callable]] = {state: [] for state in GUIState}
        self._transition_callbacks: list[Callable[[GUIState, GUIState], None]] = []

    @property
    def current(self) -> GUIState:
        """Get current state.

        Returns:
            Current GUI state
        """
        with self._lock:
            return self._state

    @property
    def state(self) -> GUIState:
        """Backward-compatible alias for tests expecting `.state`."""
        return self.current

    def is_state(self, state: GUIState) -> bool:
        """Check if in specific state.

        Args:
            state: State to check

        Returns:
            True if in that state, False otherwise
        """
        with self._lock:
            return self._state == state

    def can_run(self) -> bool:
        """Check if pipeline can be started.

        Returns:
            True if in IDLE or ERROR state
        """
        with self._lock:
            return self._state in (GUIState.IDLE, GUIState.ERROR)

    def can_stop(self) -> bool:
        """Check if pipeline can be stopped.

        Returns:
            True if in RUNNING state
        """
        with self._lock:
            return self._state == GUIState.RUNNING

    def transition_to(self, new_state: GUIState) -> bool:
        """Transition to new state if valid.

        Args:
            new_state: Target state

        Returns:
            True if transition successful, False if invalid
        """
        with self._lock:
            old_state = self._state

            # Validate transitions
            valid = self._is_valid_transition(old_state, new_state)
            if not valid:
                logger.warning(f"Invalid state transition: {old_state.name} -> {new_state.name}")
                return False

            self._state = new_state
            logger.info(f"State transition: {old_state.name} -> {new_state.name}")

        # Call callbacks outside lock to avoid deadlock
        self._notify_transition(old_state, new_state)
        self._notify_state_callbacks(new_state)

        return True

    def _is_valid_transition(self, from_state: GUIState, to_state: GUIState) -> bool:
        """Check if state transition is valid.

        Args:
            from_state: Current state
            to_state: Target state

        Returns:
            True if transition is allowed
        """
        valid_transitions = {
            GUIState.IDLE: {GUIState.RUNNING, GUIState.ERROR},
            GUIState.RUNNING: {GUIState.STOPPING, GUIState.IDLE, GUIState.ERROR},
            GUIState.STOPPING: {GUIState.IDLE, GUIState.ERROR},
            GUIState.ERROR: {GUIState.IDLE},
        }

        return to_state in valid_transitions.get(from_state, set())

    def on_state(self, state: GUIState, callback: Callable) -> None:
        """Register callback for when entering specific state.

        Args:
            state: State to watch
            callback: Function to call when entering state
        """
        with self._lock:
            self._callbacks[state].append(callback)

    def on_transition(self, callback: Callable[[GUIState, GUIState], None]) -> None:
        """Register callback for any state transition.

        Args:
            callback: Function to call with (old_state, new_state)
        """
        with self._lock:
            self._transition_callbacks.append(callback)

    def _notify_state_callbacks(self, state: GUIState) -> None:
        """Notify callbacks registered for specific state.

        Args:
            state: State that was entered
        """
        callbacks = []
        with self._lock:
            callbacks = self._callbacks[state].copy()

        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in state callback: {e}")

    def _notify_transition(self, old_state: GUIState, new_state: GUIState) -> None:
        """Notify callbacks registered for transitions.

        Args:
            old_state: Previous state
            new_state: New state
        """
        callbacks = []
        with self._lock:
            callbacks = self._transition_callbacks.copy()

        for callback in callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.error(f"Error in transition callback: {e}")

    def reset(self) -> None:
        """Reset to IDLE state."""
        self.transition_to(GUIState.IDLE)

```

## `src/gui/theme.py`

```
"""Theme system for StableNew GUI using ASWF color tokens."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# ASWF Color Tokens
ASWF_BLACK = "#221F20"
ASWF_GOLD = "#FFC805"
ASWF_DARK_GREY = "#2B2A2C"
ASWF_MED_GREY = "#3A393D"
ASWF_LIGHT_GREY = "#4A4950"
ASWF_ERROR_RED = "#CC3344"
ASWF_OK_GREEN = "#44AA55"

# Font Tokens
FONT_FAMILY = "Calibri"
FONT_SIZE_BASE = 11  # Consistent base size for all widgets
FONT_SIZE_LABEL = 11  # Same as base for consistency
FONT_SIZE_BUTTON = 11  # Same as base for consistency
FONT_SIZE_HEADING = 13  # Increased for headings only


class Theme:
    """Central theme management for StableNew GUI."""

    def apply_root(self, root: tk.Tk) -> None:
        """Apply theme to the root Tk window."""
        root.configure(bg=ASWF_BLACK)
        root.option_add("*Font", f"{FONT_FAMILY} {FONT_SIZE_BASE}")
        root.option_add("*background", ASWF_BLACK)
        root.option_add("*foreground", ASWF_GOLD)

    def apply_ttk_styles(self, style: ttk.Style) -> None:
        """Apply ttk theme and style settings using ASWF theme."""
        # Set default ttk theme to use our custom styles
        style.theme_use('default')  # Use default theme as base

        # Configure default ttk styles to use our dark theme
        style.configure(
            "TFrame",
            background=ASWF_BLACK,  # Black background for all frames
        )
        style.configure(
            "TLabel",
            background=ASWF_BLACK,  # Black background
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE),
        )
        style.configure(
            "TButton",
            background=ASWF_DARK_GREY,  # Grey background for buttons
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
            relief="raised",  # Raised for curved appearance
            borderwidth=2,
        )
        style.map(
            "TButton",
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )
        style.configure(
            "TCombobox",
            fieldbackground=ASWF_BLACK,  # Black background
            background=ASWF_DARK_GREY,  # Grey frame
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            borderwidth=2,
            relief="raised",
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", ASWF_BLACK)],
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )
        style.configure(
            "TEntry",
            fieldbackground=ASWF_BLACK,  # Black background
            background=ASWF_BLACK,
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            borderwidth=2,
            relief="raised",
        )
        style.map(
            "TEntry",
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )
        style.configure(
            "TNotebook",
            background=ASWF_BLACK,  # Black background
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=ASWF_DARK_GREY,  # Grey background for tabs
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            borderwidth=2,
            relief="raised",
            padding=[10, 5],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", ASWF_BLACK)],  # Black background when selected
            foreground=[("selected", ASWF_GOLD)],  # Gold text when selected
        )
        style.configure(
            "TLabelframe",
            background=ASWF_BLACK,  # Black background
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
            borderwidth=2,
            relief="raised",
        )
        style.configure(
            "TLabelframe.Label",
            background=ASWF_BLACK,  # Black background
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
        )
        style.configure(
            "TRadiobutton",
            background=ASWF_BLACK,  # Black background
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE),
        )
        style.map(
            "TRadiobutton",
            background=[("active", ASWF_BLACK)],
            foreground=[("active", ASWF_GOLD)],
        )
        style.configure(
            "TCheckbutton",
            background=ASWF_BLACK,  # Black background
            foreground=ASWF_GOLD,  # Gold text
            font=(FONT_FAMILY, FONT_SIZE_BASE),
        )
        style.map(
            "TCheckbutton",
            background=[("active", ASWF_BLACK)],
            foreground=[("active", ASWF_GOLD)],
            indicatorcolor=[
                ("selected", "#00ff00"),
                ("alternate", "#00ff00"),
                ("!selected", "#ffffff"),
            ],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=ASWF_DARK_GREY,  # Grey background
            troughcolor=ASWF_BLACK,  # Black trough
            borderwidth=2,
            relief="raised",
        )

        # Configure Dark.* styles for explicit usage
        style.configure(
            "Dark.TFrame",
            background=ASWF_BLACK,
        )
        style.configure(
            "Dark.TLabel",
            background=ASWF_BLACK,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE),
        )
        style.configure(
            "Dark.TButton",
            background=ASWF_DARK_GREY,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
            relief="raised",
            borderwidth=2,
        )
        style.map(
            "Dark.TButton",
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )
        style.configure(
            "Dark.TCombobox",
            fieldbackground=ASWF_BLACK,
            background=ASWF_DARK_GREY,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            borderwidth=2,
            relief="raised",
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", ASWF_BLACK)],
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )
        style.configure(
            "Dark.TEntry",
            fieldbackground=ASWF_BLACK,
            background=ASWF_BLACK,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            borderwidth=2,
            relief="raised",
        )
        style.map(
            "Dark.TEntry",
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )
        style.configure(
            "Dark.TNotebook",
            background=ASWF_BLACK,
            borderwidth=0,
        )
        style.configure(
            "Dark.TNotebook.Tab",
            background=ASWF_DARK_GREY,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            borderwidth=2,
            relief="raised",
            padding=[10, 5],
        )
        style.map(
            "Dark.TNotebook.Tab",
            background=[("selected", ASWF_BLACK)],
            foreground=[("selected", ASWF_GOLD)],
        )
        style.configure(
            "Dark.TLabelframe",
            background=ASWF_BLACK,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
            borderwidth=2,
            relief="raised",
        )
        style.configure(
            "Dark.TLabelframe.Label",
            background=ASWF_BLACK,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
        )
        style.configure(
            "Dark.TRadiobutton",
            background=ASWF_BLACK,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE),
        )
        style.map(
            "Dark.TRadiobutton",
            background=[("active", ASWF_BLACK)],
            foreground=[("active", ASWF_GOLD)],
        )
        style.configure(
            "Dark.TCheckbutton",
            background=ASWF_BLACK,
            foreground=ASWF_GOLD,
            font=(FONT_FAMILY, FONT_SIZE_BASE),
        )
        style.map(
            "Dark.TCheckbutton",
            background=[("active", ASWF_BLACK)],
            foreground=[("active", ASWF_GOLD)],
            indicatorcolor=[
                ("selected", "#00ff00"),
                ("alternate", "#00ff00"),
                ("!selected", "#ffffff"),
            ],
        )

        # Spinbox styling (increment boxes)
        spinbox_common = {
            "background": ASWF_DARK_GREY,
            "fieldbackground": ASWF_BLACK,
            "foreground": ASWF_GOLD,
            "arrowcolor": ASWF_GOLD,
            "font": (FONT_FAMILY, FONT_SIZE_BASE),
            "borderwidth": 2,
            "relief": "raised",
        }
        style.configure("TSpinbox", **spinbox_common)
        style.configure("Dark.TSpinbox", **spinbox_common)
        style.map(
            "Dark.TSpinbox",
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
            fieldbackground=[("readonly", ASWF_BLACK)],
        )

        # Slider styling
        scale_common = {
            "background": ASWF_BLACK,
            "troughcolor": ASWF_DARK_GREY,
            "borderwidth": 0,
            "sliderthickness": 16,
        }
        style.configure("Horizontal.TScale", **scale_common)
        style.configure("Dark.Horizontal.TScale", **scale_common)

        # Special button styles
        style.configure(
            "Primary.TButton",
            background=ASWF_GOLD,
            foreground=ASWF_BLACK,
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
            relief="raised",
            borderwidth=2,
        )
        style.map(
            "Primary.TButton",
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )
        style.configure(
            "Danger.TButton",
            background=ASWF_ERROR_RED,
            foreground="white",
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
            relief="raised",
            borderwidth=2,
        )
        style.map(
            "Danger.TButton",
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )
        style.configure(
            "Success.TButton",
            background=ASWF_OK_GREEN,
            foreground="white",
            font=(FONT_FAMILY, FONT_SIZE_BASE, "bold"),
            relief="raised",
            borderwidth=2,
        )
        style.map(
            "Success.TButton",
            background=[("active", ASWF_LIGHT_GREY)],
            foreground=[("active", ASWF_BLACK)],
        )

    def style_button_primary(self, btn: tk.Button) -> None:
        """Style a primary action button."""
        btn.configure(
            bg=ASWF_GOLD,
            fg=ASWF_BLACK,
            font=(FONT_FAMILY, FONT_SIZE_BUTTON, "bold"),
            relief=tk.FLAT,
            borderwidth=0,
            padx=10,
            pady=5,
        )

    def style_button_danger(self, btn: tk.Button) -> None:
        """Style a danger/error button."""
        btn.configure(
            bg=ASWF_ERROR_RED,
            fg="white",
            font=(FONT_FAMILY, FONT_SIZE_BUTTON),
            relief=tk.FLAT,
            borderwidth=0,
            padx=10,
            pady=5,
        )

    def style_frame(self, frame: tk.Frame) -> None:
        """Style a frame."""
        frame.configure(bg=ASWF_DARK_GREY, relief=tk.FLAT, borderwidth=0)

    def style_label(self, label: tk.Label) -> None:
        """Style a label."""
        label.configure(
            bg=ASWF_DARK_GREY,
            fg=ASWF_GOLD,  # Gold text on dark background for contrast
            font=(FONT_FAMILY, FONT_SIZE_LABEL),
        )

    def style_label_heading(self, label: tk.Label) -> None:
        """Style a heading label."""
        label.configure(
            bg=ASWF_DARK_GREY,
            fg=ASWF_GOLD,  # Gold text on dark background
            font=(FONT_FAMILY, FONT_SIZE_HEADING, "bold"),
        )

    def style_entry(self, entry: tk.Entry) -> None:
        """Style an entry widget."""
        entry.configure(
            bg=ASWF_MED_GREY,  # Gray background
            fg="white",  # White text on gray background for contrast
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            insertbackground=ASWF_GOLD,
            relief=tk.FLAT,
            borderwidth=1,
        )

    def style_text(self, text: tk.Text) -> None:
        """Style a text widget."""
        text.configure(
            bg=ASWF_MED_GREY,  # Gray background
            fg=ASWF_LIGHT_GREY,  # Light grey text on gray background for contrast
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            insertbackground=ASWF_GOLD,
            relief=tk.FLAT,
            borderwidth=1,
        )

    def style_listbox(self, listbox: tk.Listbox) -> None:
        """Style a listbox."""
        listbox.configure(
            bg=ASWF_MED_GREY,  # Gray background
            fg="white",  # White text on gray background for contrast
            font=(FONT_FAMILY, FONT_SIZE_BASE),
            selectbackground=ASWF_GOLD,
            selectforeground=ASWF_BLACK,
            relief=tk.FLAT,
            borderwidth=1,
        )

    def style_scrollbar(self, scrollbar: tk.Scrollbar) -> None:
        """Style a scrollbar."""
        scrollbar.configure(
            bg=ASWF_MED_GREY,
            troughcolor=ASWF_DARK_GREY,
            relief=tk.FLAT,
            borderwidth=1,
        )

```

## `src/gui/tooltip.py`

```
"""Simple tooltip helper for Tk widgets."""

import tkinter as tk


class Tooltip:
    """Attach a hover tooltip to any Tk widget."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 1500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id: str | None = None
        self._tooltip: tk.Toplevel | None = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _event):
        self._schedule()

    def _on_leave(self, _event=None):
        self._cancel()
        self._hide_tooltip()

    def _schedule(self):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show_tooltip)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show_tooltip(self):
        if self._tooltip or not self.text:
            return
        self._tooltip = tk.Toplevel(self.widget)
        self._tooltip.wm_overrideredirect(True)
        self._tooltip.configure(bg="#202020")
        try:
            x, y, cx, cy = self.widget.bbox("insert") or (0, 0, 0, 0)
        except Exception:
            x = y = cx = cy = 0
        screen_x = self.widget.winfo_rootx() + x + cx + 10
        screen_y = self.widget.winfo_rooty() + y + cy + 10
        self._tooltip.wm_geometry(f"+{screen_x}+{screen_y}")
        label = tk.Label(
            self._tooltip,
            text=self.text,
            justify=tk.LEFT,
            background="#202020",
            foreground="#ffffff",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 8),
            wraplength=300,
        )
        label.pack(ipadx=6, ipady=4)

    def _hide_tooltip(self):
        if self._tooltip is not None:
            try:
                self._tooltip.destroy()
            except Exception:
                pass
            self._tooltip = None

```

## `src/main.py`

```
# --- logging bypass ---
import logging
import os
import socket
import sys

if os.getenv("STABLENEW_LOGGING_BYPASS") == "1":
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    logging.raiseExceptions = False

try:
    from tkinter import messagebox
except Exception:  # pragma: no cover - Tk not ready
    messagebox = None

from .gui.main_window import StableNewGUI
from .utils import setup_logging

_INSTANCE_PORT = 47631


def _acquire_single_instance_lock() -> socket.socket | None:
    """Attempt to bind a localhost TCP port as a simple process lock."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", _INSTANCE_PORT))
        sock.listen(1)
    except OSError:
        return None
    return sock


def main():
    """Main function"""
    setup_logging("INFO")

    lock_sock = _acquire_single_instance_lock()
    if lock_sock is None:
        msg = (
            "StableNew is already running.\n\n"
            "Please close the existing window before starting a new one."
        )
        if messagebox is not None:
            try:
                messagebox.showerror("StableNew", msg)
            except Exception:
                print(msg, file=sys.stderr)
        else:
            print(msg, file=sys.stderr)
        return

    app = StableNewGUI()
    app.run()


if __name__ == "__main__":
    main()

```

## `src/pipeline/__init__.py`

```
"""Pipeline module"""

from .executor import Pipeline
from .video import VideoCreator

__all__ = ["Pipeline", "VideoCreator"]

```

## `src/pipeline/executor.py`

```
"""Pipeline execution module"""

import base64
import json
import logging
import re
import time
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from ..api import SDWebUIClient
from ..gui.state import CancelToken, CancellationError
from ..utils import (
    ConfigManager,
    StructuredLogger,
    build_sampler_scheduler_payload,
    load_image_to_base64,
    save_image_from_base64,
)


@lru_cache(maxsize=128)
def _cached_image_base64(path_str: str) -> str | None:
    """LRU cache for recently loaded images to cut down disk reads."""
    return load_image_to_base64(Path(path_str))


logger = logging.getLogger(__name__)


class Pipeline:
    """Main pipeline orchestrator for txt2img → img2img → upscale → video"""

    def __init__(self, client: SDWebUIClient, structured_logger: StructuredLogger):
        """
        Initialize pipeline.

        Args:
            client: SD WebUI API client
            structured_logger: Structured logger instance
        """
        self.client = client
        self.logger = structured_logger
        self.config_manager = ConfigManager()  # For global negative prompt handling
        self.progress_controller = None
        self._current_model: str | None = None
        self._current_vae: str | None = None
        self._current_hypernetwork: str | None = None
        self._current_hn_strength: float | None = None
        self._webui_defaults_applied = False
        self._last_txt2img_results: list[dict[str, Any]] = []
        self._last_img2img_result: dict[str, Any] | None = None
        self._last_upscale_result: dict[str, Any] | None = None
        self._last_full_pipeline_results: dict[str, Any] = {}
        self._current_run_dir: Path | None = None

    def _clean_metadata_payload(self, payload: Any) -> Any:
        """Remove large binary blobs (e.g., base64 images) from metadata payloads."""
        if not isinstance(payload, dict):
            return payload

        excluded_keys = {
            "image",
            "images",
            "init_images",
            "input_image",
            "input_images",
            "mask",
            "image_cfg_scale",
        }
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            if key in excluded_keys:
                continue
            cleaned[key] = value
        return cleaned

    def set_progress_controller(self, controller: Any | None) -> None:
        """Attach a progress reporting controller."""

        self.progress_controller = controller

    def _apply_webui_defaults_once(self) -> None:
        """
        Apply StableNew-required WebUI defaults (metadata, upscale safety) once per run.
        """

        if self._webui_defaults_applied:
            return

        try:
            if hasattr(self.client, "apply_metadata_defaults"):
                self.client.apply_metadata_defaults()

            if hasattr(self.client, "apply_upscale_performance_defaults"):
                self.client.apply_upscale_performance_defaults()

            self._webui_defaults_applied = True
        except Exception as exc:
            logger.warning("Could not apply WebUI defaults: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers for throughput improvements
    # ------------------------------------------------------------------

    def _ensure_model_and_vae(self, model_name: str | None, vae_name: str | None) -> None:
        """Only call into WebUI when the requested weights change."""
        try:
            if model_name and model_name != self._current_model:
                logger.info(f"Switching to model: {model_name}")
                self.client.set_model(model_name)
                self._current_model = model_name
        except Exception:
            self._current_model = None
            raise

        try:
            if vae_name and vae_name != self._current_vae:
                logger.info(f"Switching to VAE: {vae_name}")
                self.client.set_vae(vae_name)
                self._current_vae = vae_name
        except Exception:
            self._current_vae = None
            raise

    def _ensure_hypernetwork(self, name: str | None, strength: float | None) -> None:
        """
        Ensure the requested hypernetwork (and optional strength) is active.

        Args:
            name: Hypernetwork name or None/"None" to disable.
            strength: Optional strength override.
        """

        normalized = None
        if isinstance(name, str) and name.strip():
            candidate = name.strip()
            if candidate.lower() != "none":
                normalized = candidate

        target_strength = float(strength) if strength is not None else None

        if normalized == self._current_hypernetwork and (
            (target_strength is None and self._current_hn_strength is None)
            or (
                target_strength is not None
                and self._current_hn_strength is not None
                and abs(self._current_hn_strength - target_strength) < 1e-3
            )
        ):
            return

        try:
            self.client.set_hypernetwork(normalized, target_strength)
            self._current_hypernetwork = normalized
            self._current_hn_strength = target_strength
        except Exception:
            # Reset cached state so future attempts are not skipped
            self._current_hypernetwork = None
            self._current_hn_strength = None
            raise

    def _load_image_base64(self, path: Path) -> str | None:
        """Load images through the shared cache to avoid redundant disk IO."""
        return _cached_image_base64(str(path))

    def _ensure_not_cancelled(self, cancel_token, context: str) -> None:
        """Raise CancellationError if a cancel token has been triggered."""
        if (
            cancel_token
            and getattr(cancel_token, "is_cancelled", None)
            and cancel_token.is_cancelled()
        ):
            logger.info("Cancellation requested, aborting %s", context)
            raise CancellationError(f"Cancelled during {context}")

    def _log_pipeline_cancellation(self, phase: str, exc: Exception) -> None:
        """Emit a consistent INFO-level log for pipeline cancellations."""

        logger.info("⚠️ Pipeline cancelled during %s; aborting remaining stages. (%s)", phase, exc)

    def run_upscale(
        self,
        input_image_path: Path,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Batch-friendly wrapper for upscaling with cancellation handling.
        """

        try:
            return self._run_upscale_impl(input_image_path, config, run_dir, cancel_token=cancel_token)
        except CancellationError as exc:
            if isinstance(cancel_token, CancelToken):
                self._log_pipeline_cancellation("upscale", exc)
                return getattr(self, "_last_upscale_result", None)
            raise

    def _run_upscale_impl(
        self,
        input_image_path: Path,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Batch-friendly wrapper for upscaling an image, used in pipeline orchestration.

        Args:
            input_image_path: Path to input image
            config: Upscale configuration
            run_dir: Run directory for this pipeline run
            cancel_token: Optional cancellation token

        Returns:
            Metadata for upscaled image or None if failed/cancelled
        """
        self._last_upscale_result: dict[str, Any] | None = None

        upscale_dir = run_dir / "upscaled"
        upscale_dir.mkdir(parents=True, exist_ok=True)
        image_name = Path(input_image_path).stem

        # Early cancel
        self._ensure_not_cancelled(cancel_token, "upscale start")

        result = self.run_upscale_stage(
            input_image_path,
            config,
            upscale_dir,
            image_name,
        )

        # Post cancel
        self._ensure_not_cancelled(cancel_token, "post-upscale")

        if result:
            self._last_upscale_result = result
        return result

    def _normalize_config_for_pipeline(self, config: dict[str, Any]) -> dict[str, Any]:
        """Normalize config for consistent WebUI behavior.

        - Optionally disable txt2img hires-fix when downstream stages (img2img/upscale) are enabled,
          unless explicitly allowed by config["pipeline"]["allow_hr_with_stages"].
        - Normalize scheduler casing to match WebUI expectations (e.g., "karras" -> "Karras").
        """
        cfg = deepcopy(config or {})

        def norm_sched(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            v = value.strip()
            mapping = {
                "normal": "Normal",
                "karras": "Karras",
                "exponential": "Exponential",
                "polyexponential": "Polyexponential",
                "sgm_uniform": "SGM Uniform",
                "simple": "Simple",
                "ddim_uniform": "DDIM Uniform",
                "beta": "Beta",
                "linear": "Linear",
                "cosine": "Cosine",
            }
            return mapping.get(v.lower(), v)

        # Normalize schedulers across sections
        for section in ("txt2img", "img2img", "upscale"):
            sec = cfg.get(section)
            if isinstance(sec, dict) and "scheduler" in sec:
                try:
                    sec["scheduler"] = norm_sched(sec.get("scheduler"))
                except Exception:
                    pass

        # Optionally disable hires fix when running downstream stages
        try:
            pipeline = cfg.get("pipeline", {})
            disable_hr = (
                pipeline.get("img2img_enabled", True) or pipeline.get("upscale_enabled", True)
            ) and not pipeline.get("allow_hr_with_stages", False)
            if disable_hr:
                txt = cfg.setdefault("txt2img", {})
                if txt.get("enable_hr"):
                    txt["enable_hr"] = False
                    # Ensure second-pass is disabled
                    txt["hr_second_pass_steps"] = 0
                    logger.info(
                        "Disabled txt2img hires-fix for downstream stages (override with pipeline.allow_hr_with_stages)"
                    )
        except Exception:
            pass

        return cfg

    def _apply_aesthetic_to_payload(
        self, payload: dict[str, Any], full_config: dict[str, Any]
    ) -> tuple[str, str]:
        """Attach aesthetic gradient script data or fallback prompts to the payload."""

        prompt = payload.get("prompt", "")
        negative = payload.get("negative_prompt", "")

        aesthetic_cfg = (full_config or {}).get("aesthetic", {})
        if not aesthetic_cfg.get("enabled"):
            return prompt, negative

        mode = aesthetic_cfg.get("mode", "script")
        if mode == "script":
            script_args = self._build_aesthetic_script_args(aesthetic_cfg)
            if script_args:
                scripts = payload.setdefault("alwayson_scripts", {})
                scripts["Aesthetic embeddings"] = {"args": script_args}
            else:
                mode = "prompt"

        def append_phrase(base: str, addition: str) -> str:
            addition = (addition or "").strip()
            if not addition:
                return base
            return f"{base}, {addition}" if base else addition

        if mode == "prompt":
            text = aesthetic_cfg.get("text", "").strip()
            if text:
                if aesthetic_cfg.get("text_is_negative"):
                    negative = append_phrase(negative, text)
                else:
                    prompt = append_phrase(prompt, text)

            fallback = aesthetic_cfg.get("fallback_prompt", "").strip()
            if fallback:
                prompt = append_phrase(prompt, fallback)

            embedding = aesthetic_cfg.get("embedding")
            if embedding and embedding != "None":
                prompt = append_phrase(prompt, f"<embedding:{embedding}>")

        return prompt, negative

    def _build_aesthetic_script_args(self, cfg: dict[str, Any]) -> list[Any] | None:
        """Construct Always-on script args for the Aesthetic Gradient extension."""

        try:
            weight = float(cfg.get("weight", 0.9))
        except (TypeError, ValueError):
            weight = 0.9
        try:
            steps = int(cfg.get("steps", 5))
        except (TypeError, ValueError):
            steps = 5
        try:
            learning_rate = float(cfg.get("learning_rate", 0.0001))
        except (TypeError, ValueError):
            learning_rate = 0.0001
        slerp = bool(cfg.get("slerp", False))
        embedding = cfg.get("embedding", "None") or "None"
        text = cfg.get("text", "")
        try:
            angle = float(cfg.get("slerp_angle", 0.1))
        except (TypeError, ValueError):
            angle = 0.1
        text_negative = bool(cfg.get("text_is_negative", False))

        return [weight, steps, f"{learning_rate}", slerp, embedding, text, angle, text_negative]

    def _annotate_active_variant(
        self,
        config: dict[str, Any],
        variant_index: int,
        variant_label: str | None,
    ) -> None:
        """Record the active variant inside the pipeline config for downstream consumers."""

        pipeline_cfg = config.setdefault("pipeline", {})
        if variant_label or variant_index:
            pipeline_cfg["active_variant"] = {
                "index": variant_index,
                "label": variant_label,
            }
        else:
            pipeline_cfg.pop("active_variant", None)

    @staticmethod
    def _tag_variant_metadata(
        metadata: dict[str, Any] | None,
        variant_index: int,
        variant_label: str | None,
    ) -> dict[str, Any] | None:
        """Attach variant context to stage metadata dictionaries."""

        if not isinstance(metadata, dict):
            return metadata
        metadata["variant"] = {
            "index": variant_index,
            "label": variant_label,
        }
        return metadata

    @staticmethod
    def _build_variant_suffix(variant_index: int, variant_label: str | None) -> str:
        """Return a filesystem-safe suffix for the active variant."""

        slug = ""
        if variant_label:
            slug = re.sub(r"[^A-Za-z0-9]+", "-", variant_label).strip("-").lower()
        if slug:
            return f"_{slug}"
        if variant_index:
            return f"_v{variant_index + 1:02d}"
        return ""

    def _parse_sampler_config(self, config: dict[str, Any]) -> dict[str, str]:
        """
        Parse sampler configuration and extract scheduler if present.

        Args:
            config: Configuration dict that may contain sampler_name and scheduler

        Returns:
            Dict with 'sampler_name' and optional 'scheduler'
        """
        raw_sampler = config.get("sampler_name", "Euler a")
        sampler_name = (raw_sampler or "Euler a").strip() or "Euler a"
        scheduler_value = config.get("scheduler")

        scheduler_mappings = {
            "Karras": "Karras",
            "Exponential": "Exponential",
            "Polyexponential": "Polyexponential",
            "SGM Uniform": "SGM Uniform",
        }

        if not scheduler_value:
            for scheduler_keyword, mapped in scheduler_mappings.items():
                if scheduler_keyword in sampler_name:
                    sampler_name = sampler_name.replace(scheduler_keyword, "").strip()
                    scheduler_value = mapped
                    break

        sampler_payload = build_sampler_scheduler_payload(sampler_name, scheduler_value)
        if sampler_payload:
            return sampler_payload

        # Fallback to default sampler
        return {"sampler_name": "Euler a"}

    @staticmethod
    def _format_eta(seconds: float) -> str:
        """Format remaining seconds into a human-friendly ETA string."""

        if seconds <= 0:
            return "ETA: 00:00"

        total_seconds = int(round(seconds))
        minutes, secs = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if hours:
            return f"ETA: {hours:d}h {minutes:02d}m {secs:02d}s"
        return f"ETA: {minutes:02d}:{secs:02d}"

    def _extract_name_prefix(self, prompt: str) -> str | None:
        """
        Extract name prefix from prompt if it contains 'name:' metadata.

        Args:
            prompt: Text prompt that may contain 'name:' on first line

        Returns:
            Name prefix if found, None otherwise
        """
        lines = prompt.strip().split("\n")
        if lines:
            first_line = lines[0].strip()
            if first_line.lower().startswith("name:"):
                # Extract and clean the name
                name = first_line.split(":", 1)[1].strip()
                # Clean for filesystem safety
                name = re.sub(r"[^\w_-]", "_", name)
                return name if name else None
        return None

    def run_txt2img(
        self,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        batch_size: int = 1,
        cancel_token=None,
    ) -> list[dict[str, Any]]:
        """
        Run txt2img generation with cancellation handling.
        """

        try:
            return self._run_txt2img_impl(prompt, config, run_dir, batch_size, cancel_token)
        except CancellationError as exc:
            if isinstance(cancel_token, CancelToken):
                self._log_pipeline_cancellation("txt2img", exc)
                return getattr(self, "_last_txt2img_results", [])
            raise

    def _run_txt2img_impl(
        self,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        batch_size: int = 1,
        cancel_token=None,
    ) -> list[dict[str, Any]]:
        """
        Run txt2img generation.

        Args:
            prompt: Text prompt
            config: Configuration for txt2img
            run_dir: Run directory
            batch_size: Number of images to generate
            cancel_token: Optional cancellation token

        Returns:
            List of generated image metadata
        """
        self._last_txt2img_results: list[dict[str, Any]] = []

        # Check for cancellation before starting
        self._ensure_not_cancelled(cancel_token, "txt2img start")

        logger.info(f"Starting txt2img with prompt: {prompt[:50]}...")
        # Extract name prefix if present
        name_prefix = self._extract_name_prefix(prompt)

        # Apply global NSFW prevention to negative prompt (with optional adjustments)
        base_negative = config.get("negative_prompt", "")
        negative_adjust = (config.get("negative_adjust") or "").strip()
        combined_negative = (
            base_negative if not negative_adjust else f"{base_negative} {negative_adjust}".strip()
        )
        enhanced_negative = self.config_manager.add_global_negative(combined_negative)
        logger.info(
            f"🛡️ Applied global NSFW prevention - Original: '{base_negative}' → Enhanced: '{enhanced_negative[:100]}...'"
        )

        # Parse sampler configuration
        sampler_config = self._parse_sampler_config(config)

        # Set model and VAE if specified
        model_name = config.get("model") or config.get("sd_model_checkpoint")
        if model_name:
            self.client.set_model(model_name)
        if config.get("vae"):
            self.client.set_vae(config["vae"])

        payload = {
            "prompt": prompt,
            "negative_prompt": enhanced_negative,
            "steps": config.get("steps", 20),
            "cfg_scale": config.get("cfg_scale", 7.0),
            "width": config.get("width", 512),
            "height": config.get("height", 512),
            "seed": config.get("seed", -1),
            "seed_resize_from_h": config.get("seed_resize_from_h", -1),
            "seed_resize_from_w": config.get("seed_resize_from_w", -1),
            "clip_skip": config.get("clip_skip", 2),
            "batch_size": batch_size,
            "n_iter": config.get("n_iter", 1),
            "restore_faces": config.get("restore_faces", False),
            "tiling": config.get("tiling", False),
            "do_not_save_samples": config.get("do_not_save_samples", False),
            "do_not_save_grid": config.get("do_not_save_grid", False),
        }

        # Always include hires.fix parameters (will be ignored if enable_hr is False)
        payload.update(
            {
                "enable_hr": config.get("enable_hr", False),
                "hr_scale": config.get("hr_scale", 2.0),
                "hr_upscaler": config.get("hr_upscaler", "Latent"),
                "hr_second_pass_steps": config.get("hr_second_pass_steps", 0),
                "hr_resize_x": config.get("hr_resize_x", 0),
                "hr_resize_y": config.get("hr_resize_y", 0),
                "denoising_strength": config.get("denoising_strength", 0.7),
            }
        )
        # Optional separate sampler for hires second pass
        try:
            hr_sampler_name = config.get("hr_sampler_name")
            if hr_sampler_name:
                payload["hr_sampler_name"] = hr_sampler_name
        except Exception:
            pass

        payload.update(sampler_config)

        # Add styles if specified
        if config.get("styles"):
            payload["styles"] = config["styles"]

        self._apply_webui_defaults_once()
        response = self.client.txt2img(payload)

        # Check for cancellation after API call
        self._ensure_not_cancelled(cancel_token, "txt2img post-call")

        if not response or "images" not in response:
            logger.error("txt2img failed")
            return []

        results = self._last_txt2img_results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for idx, img_base64 in enumerate(response["images"]):
            # Check for cancellation before saving each image
            self._ensure_not_cancelled(cancel_token, f"txt2img save {idx}")
            # Build image name with optional prefix
            if name_prefix:
                image_name = f"{name_prefix}_{timestamp}_{idx:03d}"
            else:
                image_name = f"txt2img_{timestamp}_{idx:03d}"
            image_path = run_dir / "txt2img" / f"{image_name}.png"

            if save_image_from_base64(img_base64, image_path):
                metadata = {
                    "name": image_name,
                    "stage": "txt2img",
                    "timestamp": timestamp,
                    "prompt": prompt,
                    "config": self._clean_metadata_payload(payload),
                    "path": str(image_path),
                }

                self.logger.save_manifest(run_dir, image_name, metadata)
                results.append(metadata)

        logger.info(f"txt2img completed: {len(results)} images generated")
        return results
        """
        Run txt2img generation.

        Args:
            prompt: Text prompt
            config: Configuration for txt2img
            run_dir: Run directory
            batch_size: Number of images to generate
            cancel_token: Optional cancellation token

        Returns:
            List of generated image metadata
        """
        # Check for cancellation before starting
        self._ensure_not_cancelled(cancel_token, "txt2img start")

        logger.info(f"Starting txt2img with prompt: {prompt[:50]}...")
        # Extract name prefix if present
        name_prefix = self._extract_name_prefix(prompt)
        # Apply global NSFW prevention to negative prompt
        base_negative = config.get("negative_prompt", "")
        enhanced_negative = self.config_manager.add_global_negative(base_negative)
        logger.info(
            f"🛡️ Applied global NSFW prevention - Original: '{base_negative}' → Enhanced: '{enhanced_negative[:100]}...'"
        )

        # Parse sampler configuration
        sampler_config = self._parse_sampler_config(config)

        # Set model and VAE if specified
        model_name = config.get("model") or config.get("sd_model_checkpoint")
        if model_name:
            self.client.set_model(model_name)
        if config.get("vae"):
            self.client.set_vae(config["vae"])

        payload = {
            "prompt": prompt,
            "negative_prompt": enhanced_negative,
            "steps": config.get("steps", 20),
            "cfg_scale": config.get("cfg_scale", 7.0),
            "width": config.get("width", 512),
            "height": config.get("height", 512),
            "seed": config.get("seed", -1),
            "seed_resize_from_h": config.get("seed_resize_from_h", -1),
            "seed_resize_from_w": config.get("seed_resize_from_w", -1),
            "clip_skip": config.get("clip_skip", 2),
            "batch_size": batch_size,
            "n_iter": config.get("n_iter", 1),
            "restore_faces": config.get("restore_faces", False),
            "tiling": config.get("tiling", False),
            "do_not_save_samples": config.get("do_not_save_samples", False),
            "do_not_save_grid": config.get("do_not_save_grid", False),
        }

        # Always include hires.fix parameters (will be ignored if enable_hr is False)
        payload.update(
            {
                "enable_hr": config.get("enable_hr", False),
                "hr_scale": config.get("hr_scale", 2.0),
                "hr_upscaler": config.get("hr_upscaler", "Latent"),
                "hr_second_pass_steps": config.get("hr_second_pass_steps", 0),
                "hr_resize_x": config.get("hr_resize_x", 0),
                "hr_resize_y": config.get("hr_resize_y", 0),
                "denoising_strength": config.get("denoising_strength", 0.7),
            }
        )

        payload.update(sampler_config)

        # Add styles if specified
        if config.get("styles"):
            payload["styles"] = config["styles"]

        self._apply_webui_defaults_once()
        response = self.client.txt2img(payload)

        # Check for cancellation after API call
        self._ensure_not_cancelled(cancel_token, "txt2img post-call")

        if not response or "images" not in response:
            logger.error("txt2img failed")
            return []

        results = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for idx, img_base64 in enumerate(response["images"]):
            # Check for cancellation before saving each image
            self._ensure_not_cancelled(cancel_token, f"txt2img save {idx}")
            # Build image name with optional prefix
            if name_prefix:
                image_name = f"{name_prefix}_{timestamp}_{idx:03d}"
            else:
                image_name = f"txt2img_{timestamp}_{idx:03d}"
            image_path = run_dir / "txt2img" / f"{image_name}.png"

            if save_image_from_base64(img_base64, image_path):
                metadata = {
                    "name": image_name,
                    "stage": "txt2img",
                    "timestamp": timestamp,
                    "prompt": prompt,
                    "config": self._clean_metadata_payload(payload),
                    "path": str(image_path),
                }

                self.logger.save_manifest(run_dir, image_name, metadata)
                results.append(metadata)

        logger.info(f"txt2img completed: {len(results)} images generated")
        return results

    def run_img2img(
        self,
        input_image_path: Path,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run img2img cleanup/refinement with cancellation handling.
        """

        try:
            return self._run_img2img_impl(input_image_path, prompt, config, run_dir, cancel_token)
        except CancellationError as exc:
            if isinstance(cancel_token, CancelToken):
                self._log_pipeline_cancellation("img2img", exc)
                return getattr(self, "_last_img2img_result", None)
            raise

    def _run_img2img_impl(
        self,
        input_image_path: Path,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run img2img cleanup/refinement.

        Args:
            input_image_path: Path to input image
            prompt: Text prompt
            config: Configuration for img2img
            run_dir: Run directory
            cancel_token: Optional cancellation token

        Returns:
            Generated image metadata
        """
        self._last_img2img_result: dict[str, Any] | None = None

        # Check for cancellation before starting
        self._ensure_not_cancelled(cancel_token, "img2img start")

        logger.info(f"Starting img2img cleanup for: {input_image_path.name}")

        # Load input image
        input_base64 = load_image_to_base64(input_image_path)
        if not input_base64:
            logger.error("Failed to load input image for img2img")
            return None

        # Apply global NSFW prevention to negative prompt
        base_negative = config.get("negative_prompt", "")
        enhanced_negative = self.config_manager.add_global_negative(base_negative)
        logger.info(
            f"🛡️ Applied global NSFW prevention (img2img) - Enhanced: '{enhanced_negative[:100]}...'"
        )

        # Set model and VAE if specified
        if config.get("model"):
            self.client.set_model(config["model"])
        if config.get("vae"):
            self.client.set_vae(config["vae"])

        # Apply optional prompt adjustments from config
        prompt_adjust = (config.get("prompt_adjust") or "").strip()
        combined_prompt = prompt if not prompt_adjust else f"{prompt} {prompt_adjust}".strip()

        sampler_config = self._parse_sampler_config(config)

        payload = {
            "init_images": [input_base64],
            "prompt": combined_prompt,
            "negative_prompt": enhanced_negative,
            "steps": config.get("steps", 15),
            "cfg_scale": config.get("cfg_scale", 7.0),
            "denoising_strength": config.get("denoising_strength", 0.3),
            "width": config.get("width", 512),
            "height": config.get("height", 512),
            "seed": config.get("seed", -1),
            "clip_skip": config.get("clip_skip", 2),
        }

        payload.update(sampler_config)

        response = self.client.img2img(payload)

        # Check for cancellation after API call
        self._ensure_not_cancelled(cancel_token, "img2img post-call")

        if not response or "images" not in response:
            logger.error("img2img failed")
            return None

        # Save cleaned image
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_name = f"img2img_{timestamp}"
        image_path = run_dir / "img2img" / f"{image_name}.png"

        if save_image_from_base64(response["images"][0], image_path):
            metadata = {
                "name": image_name,
                "stage": "img2img",
                "timestamp": timestamp,
                "prompt": prompt,
                "input_image": str(input_image_path),
                "config": self._clean_metadata_payload(payload),
                "path": str(image_path),
            }

            self.logger.save_manifest(run_dir, image_name, metadata)
            self._last_img2img_result = metadata
            logger.info(f"img2img completed: {image_name}")
            return metadata
        return None

    def run_adetailer(
        self,
        input_image_path: Path,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run ADetailer for automatic face/detail enhancement.

        Args:
            input_image_path: Path to input image
            prompt: Text prompt
            config: Configuration for ADetailer
            run_dir: Run directory
            cancel_token: Optional cancellation token

        Returns:
            Enhanced image metadata or None if cancelled/failed
        """
        # Check for cancellation before starting
        self._ensure_not_cancelled(cancel_token, "adetailer start")

        # Check if ADetailer is enabled
        if not config.get("adetailer_enabled", False):
            logger.info("ADetailer is disabled, skipping")
            return None

        logger.info(f"Starting ADetailer for: {input_image_path.name}")

        # Load input image
        init_image = self._load_image_base64(input_image_path)
        if not init_image:
            logger.error("Failed to load input image")
            return None

        # Determine the working resolution for this image
        actual_width: int | None = None
        actual_height: int | None = None
        try:
            with Image.open(input_image_path) as image:
                actual_width, actual_height = image.size
        except Exception:
            actual_width = None
            actual_height = None

        def _coerce_dimension(value: Any, fallback: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        payload_width = actual_width or _coerce_dimension(config.get("width"), 512)
        payload_height = actual_height or _coerce_dimension(config.get("height"), 512)

        # Optionally apply global negative to adetailer negative prompt
        base_ad_neg = config.get("adetailer_negative_prompt", "")
        apply_global = (config.get("pipeline", {}) if isinstance(config, dict) else {}).get(
            "apply_global_negative_adetailer", True
        )
        if apply_global:
            ad_neg_final = self.config_manager.add_global_negative(base_ad_neg)
            try:
                logger.info(
                    "🛡️ Applied global NSFW prevention (adetailer stage) - Enhanced: '%s'",
                    (ad_neg_final[:120] + "...") if len(ad_neg_final) > 120 else ad_neg_final,
                )
            except Exception:
                pass
        else:
            ad_neg_final = base_ad_neg

        # Build ADetailer payload
        payload = {
            "init_images": [init_image],
            "prompt": config.get("adetailer_prompt", prompt),
            "negative_prompt": ad_neg_final,
            "sampler_name": config.get("adetailer_sampler", "DPM++ 2M"),
            "steps": config.get("adetailer_steps", 28),
            "cfg_scale": config.get("adetailer_cfg", 7.0),
            "denoising_strength": config.get("adetailer_denoise", 0.4),
            "width": payload_width,
            "height": payload_height,
            # ADetailer specific parameters
            "alwayson_scripts": {
                "ADetailer": {
                    "args": [
                        {
                            "ad_model": config.get("adetailer_model", "face_yolov8n.pt"),
                            "ad_confidence": config.get("adetailer_confidence", 0.3),
                            "ad_mask_blur": config.get("adetailer_mask_feather", 4),
                            "ad_denoising_strength": config.get("adetailer_denoise", 0.4),
                            "ad_inpaint_only_masked": True,
                            "ad_inpaint_only_masked_padding": 32,
                            "ad_use_inpaint_width_height": False,
                            "ad_sampler": config.get("adetailer_sampler", "DPM++ 2M"),
                            "ad_steps": config.get("adetailer_steps", 28),
                            "ad_cfg_scale": config.get("adetailer_cfg", 7.0),
                            "ad_prompt": config.get("adetailer_prompt", ""),
                            "ad_negative_prompt": ad_neg_final,
                        }
                    ]
                }
            },
        }

        # Call img2img endpoint with ADetailer extension
        response = self.client.img2img(payload)

        # Check for cancellation after API call
        self._ensure_not_cancelled(cancel_token, "adetailer post-call")

        if not response or "images" not in response:
            logger.error("adetailer failed")
            return None

        # Save enhanced image
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_name = f"adetailer_{timestamp}"
        image_path = run_dir / "adetailer" / f"{image_name}.png"

        if save_image_from_base64(response["images"][0], image_path):
            metadata = {
                "name": image_name,
                "stage": "adetailer",
                "timestamp": timestamp,
                "original_prompt": prompt,
                "final_prompt": payload.get("prompt", prompt),
                "original_negative_prompt": base_ad_neg,
                "final_negative_prompt": ad_neg_final,
                "global_negative_applied": apply_global,
                "global_negative_terms": self.config_manager.get_global_negative_prompt()
                if apply_global
                else "",
                "input_image": str(input_image_path),
                "config": self._clean_metadata_payload(payload),
                "path": str(image_path),
            }

            self.logger.save_manifest(run_dir, image_name, metadata)
            logger.info(f"adetailer completed: {image_name}")
            return metadata

        return None
        """
        Run upscaling.

        Args:
            input_image_path: Path to input image
            config: Configuration for upscaling
            run_dir: Run directory
            cancel_token: Optional cancellation token

        Returns:
            Upscaled image metadata
        """
        # Check for cancellation before starting
        self._ensure_not_cancelled(cancel_token, "upscale stage start")

        logger.info(f"Starting upscale for: {input_image_path.name}")

        init_image = load_image_to_base64(input_image_path)
        if not init_image:
            logger.error("Failed to load input image")
            return None

        if hasattr(self.client, "ensure_safe_upscale_defaults"):
            try:
                self.client.ensure_safe_upscale_defaults()
            except Exception as exc:  # noqa: BLE001 - best-effort clamp
                logger.debug("ensure_safe_upscale_defaults failed: %s", exc)

        response = self.client.upscale_image(
            init_image,
            upscaler=config.get("upscaler", "R-ESRGAN 4x+"),
            upscaling_resize=config.get("upscaling_resize", 2.0),
            gfpgan_visibility=config.get("gfpgan_visibility", 0.0),
            codeformer_visibility=config.get("codeformer_visibility", 0.0),
            codeformer_weight=config.get("codeformer_weight", 0.5),
        )

        # Check for cancellation after API call
        self._ensure_not_cancelled(cancel_token, "upscale stage post-call")

        if not response or "image" not in response:
            logger.error("Upscale failed")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_name = f"upscaled_{input_image_path.stem}_{timestamp}"
        image_path = run_dir / "upscaled" / f"{image_name}.png"

        if save_image_from_base64(response["image"], image_path):
            metadata = {
                "name": image_name,
                "stage": "upscale",
                "timestamp": timestamp,
                "input_image": str(input_image_path),
                "config": config,
                "path": str(image_path),
            }

            self.logger.save_manifest(run_dir, image_name, metadata)
            logger.info("Upscale completed successfully")
            return metadata

        return None

    def run_full_pipeline(
        self,
        prompt: str,
        config: dict[str, Any],
        run_name: str | None = None,
        batch_size: int = 1,
        cancel_token=None,
    ) -> dict[str, Any]:
        """
        Run the full pipeline with cancellation handling.
        """

        try:
            result = self._run_full_pipeline_impl(
                prompt, config, run_name=run_name, batch_size=batch_size, cancel_token=cancel_token
            )
            if self._current_run_dir:
                self.logger.record_run_status(self._current_run_dir, "success")
            return result
        except CancellationError as exc:
            if isinstance(cancel_token, CancelToken):
                self._log_pipeline_cancellation("full pipeline", exc)
                if self._current_run_dir:
                    self.logger.record_run_status(self._current_run_dir, "cancelled", str(exc))
                return getattr(
                    self,
                    "_last_full_pipeline_results",
                    {
                        "run_dir": "",
                        "prompt": prompt,
                        "txt2img": [],
                        "img2img": [],
                        "upscaled": [],
                        "summary": [],
                    },
                )
            raise

    def _run_full_pipeline_impl(
        self,
        prompt: str,
        config: dict[str, Any],
        run_name: str | None = None,
        batch_size: int = 1,
        cancel_token=None,
    ) -> dict[str, Any]:
        """
        Run complete pipeline: txt2img → img2img (optional) → upscale (optional).

        Args:
            prompt: Text prompt
            config: Full pipeline configuration with optional pipeline.img2img_enabled and pipeline.upscale_enabled
            run_name: Optional run name
            batch_size: Number of images to generate
            cancel_token: Optional cancellation token

        Returns:
            Pipeline results summary
        """
        self._current_run_dir = None
        self._last_full_pipeline_results = {
            "run_dir": "",
            "prompt": prompt,
            "txt2img": [],
            "img2img": [],
            "upscaled": [],
            "summary": [],
        }

        # Check for cancellation at start
        self._ensure_not_cancelled(cancel_token, "pipeline start")

        logger.info("=" * 60)
        logger.info("Starting full pipeline execution")

        # Check pipeline stage configuration
        pipeline_cfg: dict[str, Any] = config.get("pipeline", {}) or {}
        img2img_enabled: bool = pipeline_cfg.get("img2img_enabled", True)
        upscale_enabled: bool = pipeline_cfg.get("upscale_enabled", True)
        upscale_only_last: bool = pipeline_cfg.get("upscale_only_last", False)

        logger.info(
            "Pipeline stages: txt2img=ON, img2img=%s, upscale=%s (upscale_only_last=%s)",
            "ON" if img2img_enabled else "SKIP",
            "ON" if upscale_enabled else "SKIP",
            upscale_only_last,
        )
        logger.info("=" * 60)

        # Create run directory
        run_dir = self.logger.create_run_directory(run_name)
        self._current_run_dir = run_dir

        results = self._last_full_pipeline_results
        results["run_dir"] = str(run_dir)
        results["prompt"] = prompt
        results["txt2img"] = []
        results["img2img"] = []
        results["upscaled"] = []
        results["summary"] = []

        progress_controller = self.progress_controller
        total_units = 1
        completed_units = 0
        start_time = time.monotonic()

        def compute_eta(units_done: float) -> str:
            if units_done <= 0:
                return "ETA: --"
            elapsed = time.monotonic() - start_time
            if elapsed <= 0:
                return "ETA: --"
            remaining_units = max(total_units - units_done, 0)
            if remaining_units <= 0:
                return "ETA: 00:00"
            avg_per_unit = elapsed / units_done
            if avg_per_unit <= 0:
                return "ETA: --"
            return self._format_eta(avg_per_unit * remaining_units)

        def emit(stage_label: str, units_override: float | None = None) -> None:
            if progress_controller is None:
                return
            units_done = completed_units if units_override is None else units_override
            percent = 0.0
            if total_units > 0:
                percent = max(0.0, min(100.0, (units_done / total_units) * 100.0))
            eta_text = compute_eta(units_done)
            progress_controller.report_progress(stage_label, percent, eta_text)

        emit("txt2img", completed_units)

        # Step 1: txt2img
        txt2img_results = self.run_txt2img(
            prompt, config.get("txt2img", {}), run_dir, batch_size, cancel_token
        )
        results["txt2img"] = txt2img_results

        completed_units += 1
        emit("txt2img", completed_units)

        # Check for cancellation after txt2img
        self._ensure_not_cancelled(cancel_token, "pipeline post-txt2img")

        if not txt2img_results:
            logger.error("Pipeline failed at txt2img stage")
            return results

        total_images = len(txt2img_results)

        txt2img_cfg = config.get("txt2img", {}) or {}
        diag_batch_size = txt2img_cfg.get("batch_size", batch_size)
        diag_n_iter = txt2img_cfg.get("n_iter", 1)
        logger.info(
            "PIPELINE DIAG: txt2img produced %d images (batch_size=%s, n_iter=%s)",
            total_images,
            diag_batch_size,
            diag_n_iter,
        )

        per_image_units = int(bool(img2img_enabled)) + int(bool(upscale_enabled))
        if per_image_units and total_images:
            total_units = 1 + total_images * per_image_units
        else:
            total_units = max(total_units, 1)

        # Step 2: img2img cleanup (optional, for each generated image)
        for index, txt2img_meta in enumerate(txt2img_results, start=1):
            self._ensure_not_cancelled(cancel_token, "pipeline img2img loop")

            last_image_path = txt2img_meta["path"]
            final_image_path = last_image_path
            image_label = f"{index}/{total_images}" if total_images else str(index)

            if img2img_enabled:
                emit(f"img2img ({image_label})", completed_units)
                img2img_meta = self.run_img2img(
                    Path(txt2img_meta["path"]),
                    prompt,
                    config.get("img2img", {}),
                    run_dir,
                    cancel_token,
                )
                if img2img_meta:
                    results["img2img"].append(img2img_meta)
                    last_image_path = img2img_meta["path"]
                    logger.info(f"✓ img2img completed for {txt2img_meta['name']}")
                else:
                    logger.warning(
                        f"img2img failed for {txt2img_meta['name']}, using txt2img output for next steps"
                    )
                completed_units += 1
                emit(f"img2img ({image_label})", completed_units)
            else:
                logger.info(f"⊘ img2img skipped for {txt2img_meta['name']}")

            self._ensure_not_cancelled(cancel_token, "pipeline pre-upscale")

            do_upscale = upscale_enabled and (not upscale_only_last or index == total_images)

            if do_upscale:
                emit(f"upscale ({image_label})", completed_units)
                upscaled_meta = self.run_upscale(
                    Path(last_image_path), config.get("upscale", {}), run_dir, cancel_token
                )
                if upscaled_meta:
                    results["upscaled"].append(upscaled_meta)
                    final_image_path = upscaled_meta["path"]
                    logger.info(f"✓ upscale completed for {Path(last_image_path).name}")
                else:
                    logger.warning(
                        f"upscale failed for {Path(last_image_path).name}, using previous output"
                    )
                    final_image_path = last_image_path
                completed_units += 1
                emit(f"upscale ({image_label})", completed_units)
            else:
                if upscale_enabled and upscale_only_last:
                    logger.info(
                        "⊘ upscale skipped for %s (upscale_only_last=True, index=%d/%d)",
                        Path(last_image_path).name,
                        index,
                        total_images,
                    )
                else:
                    logger.info(f"⊘ upscale skipped for {Path(last_image_path).name}")
                final_image_path = last_image_path

            summary_entry = {
                "prompt": prompt,
                "txt2img_path": txt2img_meta["path"],
                "final_image_path": final_image_path,
                "timestamp": txt2img_meta["timestamp"],
                "stages_completed": ["txt2img"],
            }

            if img2img_enabled and len(results["img2img"]) > 0:
                summary_entry["img2img_path"] = results["img2img"][-1]["path"]
                summary_entry["stages_completed"].append("img2img")

            if upscale_enabled and len(results["upscaled"]) > 0:
                summary_entry["upscaled_path"] = results["upscaled"][-1]["path"]
                summary_entry["stages_completed"].append("upscale")

            results["summary"].append(summary_entry)

        if progress_controller and (not cancel_token or not cancel_token.is_cancelled()):
            completed_units = max(completed_units, total_units)
            emit("Completed", completed_units)

        # Create CSV summary
        if results["summary"]:
            self.logger.create_csv_summary(run_dir, results["summary"])

        logger.info("=" * 60)
        logger.info(f"Pipeline completed: {len(results['summary'])} images processed")
        logger.info(f"Output directory: {run_dir}")
        logger.info("=" * 60)

        return results

    def run_pack_pipeline(
        self,
        pack_name: str,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        prompt_index: int = 0,
        batch_size: int = 1,
        variant_index: int = 0,
        variant_label: str | None = None,
        negative_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Run pipeline for a single prompt from a pack with new directory structure.

        Args:
            pack_name: Name of the prompt pack (without .txt)
            prompt: Text prompt to process
            config: Configuration dictionary
            run_dir: Main session run directory
            prompt_index: Index of prompt within pack
            batch_size: Number of images to generate
            variant_index: Index of the active model/hypernetwork variant (0-based)
            variant_label: Human readable label for the active variant

        Returns:
            Pipeline results for this prompt
        """
        logger.info(f"🎨 Processing prompt {prompt_index + 1} from pack '{pack_name}'")

        # Create pack-specific directory structure
        pack_dir = self.logger.create_pack_directory(run_dir, pack_name)

        # Save config for this pack run
        config_path = pack_dir / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        results: dict[str, Any] = {
            "pack_name": pack_name,
            "pack_dir": str(pack_dir),
            "prompt": prompt,
            "txt2img": [],  # list[dict]
            "img2img": [],  # list[dict]
            "adetailer": [],  # list[dict]
            "upscaled": [],  # list[dict]
            "summary": [],  # list[dict]
        }

        # Normalize config for this run (disable conflicting hires, normalize scheduler casing)
        config = self._normalize_config_for_pipeline(config)
        self._annotate_active_variant(config, variant_index, variant_label)

        # Emit a concise summary of stage parameters for this pack
        try:
            i2i_steps = config.get("img2img", {}).get("steps")
            up_mode = config.get("upscale", {}).get("upscale_mode", "single")
            up_steps = config.get("upscale", {}).get("steps")
            enable_hr = config.get("txt2img", {}).get("enable_hr")
            logger.info(
                "Pack '%s' params => img2img.steps=%s, upscale.mode=%s, upscale.steps=%s, txt2img.enable_hr=%s",
                pack_name,
                i2i_steps,
                up_mode,
                up_steps,
                enable_hr,
            )
        except Exception:
            pass

        # If caller provided an explicit negative prompt override, apply it early so
        # both the stage call and the config snapshot reflect the value (tests rely on this).
        if negative_prompt is not None:
            # Ensure txt2img section exists
            config.setdefault("txt2img", {})["negative_prompt"] = negative_prompt

        # ------------------------------------------------------------------
        # Batching strategy: generate ALL base txt2img images first, then perform
        # refinement & upscale passes. This minimizes costly model checkpoint
        # swaps when refiner is enabled but compare_mode is False.
        # ------------------------------------------------------------------
        txt_cfg = config.get("txt2img", {})
        refiner_checkpoint = txt_cfg.get("refiner_checkpoint")
        # Defensive: ensure refiner_checkpoint is string or None
        if refiner_checkpoint is not None:
            refiner_checkpoint = str(refiner_checkpoint)
        refiner_switch_at = txt_cfg.get("refiner_switch_at", 0.8)
        compare_mode = bool(config.get("pipeline", {}).get("refiner_compare_mode", False))
        use_refiner = (
            refiner_checkpoint
            and refiner_checkpoint != "None"
            and str(refiner_checkpoint).strip() != ""
            and 0.0 < float(refiner_switch_at) < 1.0
        )
        img2img_enabled = config.get("pipeline", {}).get("img2img_enabled", True)
        adetailer_enabled = config.get("pipeline", {}).get("adetailer_enabled", False)
        upscale_enabled = config.get("pipeline", {}).get("upscale_enabled", True)

        # Phase 1: txt2img for all images
        for batch_idx in range(batch_size):
            image_number = (prompt_index * batch_size) + batch_idx + 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            variant_suffix = self._build_variant_suffix(variant_index, variant_label)
            image_name = f"{image_number:03d}_{timestamp}{variant_suffix}"
            txt2img_dir = pack_dir / "txt2img"
            effective_negative = config.get("txt2img", {}).get("negative_prompt", "")
            meta = self.run_txt2img_stage(
                prompt, effective_negative, config, txt2img_dir, image_name
            )
            if meta:
                # ensure name present for downstream base prefix extraction
                meta = self._tag_variant_metadata(meta, variant_index, variant_label)
                results["txt2img"].append(meta)

        # Early exit if no base images
        if not results["txt2img"]:
            logger.error("No txt2img outputs produced; aborting pack pipeline early")
            return results

        # Phase 2: refinement (img2img/adetailer/upscale) per base image
        for batch_idx, txt2img_meta in enumerate(results["txt2img"]):
            image_number = (prompt_index * batch_size) + batch_idx + 1
            # txt2img_meta is a dict; name key guaranteed from stage
            base_image_name = Path(txt2img_meta.get("name", "base")).stem
            last_image_path = txt2img_meta.get("path", "")
            final_image_path = last_image_path

            # Compare mode keeps original + refined branch logic (unchanged broadly)
            if compare_mode and use_refiner:
                candidates: list[dict[str, str]] = [{"label": "base", "path": txt2img_meta["path"]}]
                try:
                    # Defensive: ensure refiner_checkpoint is string before split
                    ref_str = str(refiner_checkpoint) if refiner_checkpoint else ""
                    ref_clean = ref_str.split(" [")[0] if " [" in ref_str else ref_str
                except Exception:
                    ref_clean = str(refiner_checkpoint) if refiner_checkpoint else ""
                forced_i2i_cfg = dict(config.get("img2img", {}))
                forced_i2i_cfg["model"] = ref_clean or forced_i2i_cfg.get("model", "")
                forced_i2i_cfg.setdefault("denoising_strength", 0.25)
                forced_i2i_cfg.setdefault("steps", max(10, int(forced_i2i_cfg.get("steps", 15))))
                img2img_dir_cmp = pack_dir / "img2img"
                refined_name = f"{base_image_name}_refined"
                try:
                    cmp_meta = self.run_img2img_stage(
                        Path(txt2img_meta["path"]),
                        prompt,
                        forced_i2i_cfg,
                        img2img_dir_cmp,
                        refined_name,
                        config,
                    )
                except TypeError:
                    cmp_meta = self.run_img2img_stage(
                        Path(txt2img_meta["path"]),
                        prompt,
                        forced_i2i_cfg,
                        img2img_dir_cmp,
                        refined_name,
                    )
                if cmp_meta:
                    cmp_meta = self._tag_variant_metadata(cmp_meta, variant_index, variant_label)
                    results["img2img"].append(cmp_meta)
                    candidates.append({"label": "refined", "path": cmp_meta["path"]})

                processed_final_paths: list[str] = []
                for cand in candidates:
                    branch_last = cand["path"]
                    if adetailer_enabled:
                        adetailer_cfg = dict(config.get("adetailer", {}))
                        txt_settings = config.get("txt2img", {})
                        adetailer_cfg.setdefault("width", txt_settings.get("width", 512))
                        adetailer_cfg.setdefault("height", txt_settings.get("height", 512))
                        pipe_flags = dict(config.get("pipeline", {}))
                        adetailer_cfg["pipeline"] = {
                            "apply_global_negative_adetailer": pipe_flags.get(
                                "apply_global_negative_adetailer", True
                            )
                        }
                        adetailer_meta = self.run_adetailer(
                            Path(branch_last), prompt, adetailer_cfg, pack_dir
                        )
                        if adetailer_meta:
                            adetailer_meta = self._tag_variant_metadata(
                                adetailer_meta, variant_index, variant_label
                            )
                            results["adetailer"].append(adetailer_meta)
                            branch_last = adetailer_meta["path"]
                    if upscale_enabled:
                        upscale_dir = pack_dir / "upscaled"
                        up_name = f"{base_image_name}_{cand['label']}"
                        up_meta = self.run_upscale_stage(
                            Path(branch_last), config.get("upscale", {}), upscale_dir, up_name
                        )
                        if up_meta:
                            up_meta = self._tag_variant_metadata(
                                up_meta, variant_index, variant_label
                            )
                            results["upscaled"].append(up_meta)
                            processed_final_paths.append(up_meta["path"])
                        else:
                            processed_final_paths.append(branch_last)
                    else:
                        processed_final_paths.append(branch_last)
                final_image_path = (
                    processed_final_paths[0]
                    if processed_final_paths
                    else txt2img_meta.get("path", "")
                )
                last_image_path = final_image_path
            else:
                # Non-compare mode refinement path (single branch)
                if img2img_enabled:
                    img2img_dir = pack_dir / "img2img"
                    try:
                        img2img_meta = self.run_img2img_stage(
                            Path(txt2img_meta["path"]),
                            prompt,
                            config.get("img2img", {}),
                            img2img_dir,
                            base_image_name,
                            config,
                        )
                    except TypeError:
                        img2img_meta = self.run_img2img_stage(
                            Path(txt2img_meta["path"]),
                            prompt,
                            config.get("img2img", {}),
                            img2img_dir,
                            base_image_name,
                        )
                    if img2img_meta:
                        img2img_meta = self._tag_variant_metadata(
                            img2img_meta, variant_index, variant_label
                        )
                        results["img2img"].append(img2img_meta)
                        last_image_path = img2img_meta["path"]
                        final_image_path = last_image_path
                if adetailer_enabled:
                    adetailer_cfg = dict(config.get("adetailer", {}))
                    txt_settings = config.get("txt2img", {})
                    adetailer_cfg.setdefault("width", txt_settings.get("width", 512))
                    adetailer_cfg.setdefault("height", txt_settings.get("height", 512))
                    pipe_flags = dict(config.get("pipeline", {}))
                    adetailer_cfg["pipeline"] = {
                        "apply_global_negative_adetailer": pipe_flags.get(
                            "apply_global_negative_adetailer", True
                        )
                    }
                    adetailer_meta = self.run_adetailer(
                        Path(last_image_path), prompt, adetailer_cfg, pack_dir
                    )
                    if adetailer_meta:
                        adetailer_meta = self._tag_variant_metadata(
                            adetailer_meta, variant_index, variant_label
                        )
                        results["adetailer"].append(adetailer_meta)
                        last_image_path = adetailer_meta["path"]
                        final_image_path = last_image_path
                if upscale_enabled:
                    upscale_dir = pack_dir / "upscaled"
                    upscaled_meta = self.run_upscale_stage(
                        Path(last_image_path),
                        config.get("upscale", {}),
                        upscale_dir,
                        base_image_name,
                    )
                    if upscaled_meta:
                        upscaled_meta = self._tag_variant_metadata(
                            upscaled_meta, variant_index, variant_label
                        )
                        results["upscaled"].append(upscaled_meta)
                        final_image_path = upscaled_meta["path"]
                    else:
                        final_image_path = last_image_path
                else:
                    final_image_path = last_image_path

            # Build summary entry
            summary_entry = {
                "pack": pack_name,
                "prompt_index": prompt_index,
                "batch_index": batch_idx,
                "image_number": image_number,
                "prompt": prompt,
                "final_image": final_image_path,
                "steps_completed": [],
                "variant": {"index": variant_index, "label": variant_label},
                "txt2img_final_prompt": txt2img_meta.get("final_prompt", ""),
                "txt2img_final_negative": txt2img_meta.get("final_negative_prompt", ""),
            }
            summary_entry["steps_completed"].append("txt2img")
            if results["img2img"]:
                # Collect img2img prompts for this base name
                try:
                    base_prefix = Path(txt2img_meta.get("name", "base")).stem
                    img2img_prompts: list[str] = []
                    img2img_negatives: list[str] = []
                    for m in results["img2img"]:
                        if isinstance(m, dict) and m.get("name", "").startswith(base_prefix):
                            img2img_prompts.append(m.get("final_prompt") or m.get("prompt", ""))
                            img2img_negatives.append(
                                m.get("final_negative_prompt") or m.get("negative_prompt", "")
                            )
                    if img2img_prompts:
                        summary_entry["steps_completed"].append("img2img")
                        summary_entry["img2img_final_prompt"] = "; ".join(img2img_prompts)
                        summary_entry["img2img_final_negative"] = "; ".join(img2img_negatives)
                except Exception:
                    pass
            if results["adetailer"]:
                try:
                    adetailer_meta = next(
                        (
                            m
                            for m in results["adetailer"]
                            if isinstance(m, dict) and m.get("path") == last_image_path
                        ),
                        None,
                    )
                    if adetailer_meta:
                        summary_entry["steps_completed"].append("adetailer")
                        summary_entry["adetailer_final_prompt"] = adetailer_meta.get(
                            "final_prompt", ""
                        )
                        summary_entry["adetailer_final_negative"] = adetailer_meta.get(
                            "final_negative_prompt", ""
                        )
                except Exception:
                    pass
            if results["upscaled"]:
                try:
                    up_meta = next(
                        (
                            m
                            for m in results["upscaled"]
                            if isinstance(m, dict) and m.get("path") == final_image_path
                        ),
                        None,
                    )
                    if up_meta:
                        summary_entry["steps_completed"].append("upscaled")
                        summary_entry["upscale_final_negative"] = up_meta.get(
                            "final_negative_prompt", ""
                        )
                except Exception:
                    pass
            results["summary"].append(summary_entry)

        # Create CSV summary for this pack
        if results["summary"]:
            summary_path = pack_dir / "summary.csv"
            self.logger.create_pack_csv_summary(summary_path, results["summary"])

        logger.info(
            f"✅ Completed pack '{pack_name}' prompt {prompt_index + 1}: {len(results['summary'])} images"
        )
        return results

    def run_txt2img_stage(
        self,
        prompt: str,
        negative_prompt: str,
        config: dict[str, Any],
        output_dir: Path,
        image_name: str,
    ) -> dict[str, Any] | None:
        """
        Run single txt2img stage for individual prompt.

        Args:
            prompt: Text prompt
            negative_prompt: Negative prompt
            config: Configuration dictionary
            output_dir: Output directory
            image_index: Index for naming

        Returns:
            Generated image metadata or None if failed
        """
        try:
            # Ensure output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)

            # Build txt2img payload
            txt2img_config = config.get("txt2img", {})

            # Optionally apply global NSFW prevention to negative prompt based on stage flag
            apply_global = config.get("pipeline", {}).get("apply_global_negative_txt2img", True)
            if apply_global:
                enhanced_negative = self.config_manager.add_global_negative(negative_prompt)
                logger.info(
                    f"🛡️ Applied global NSFW prevention (txt2img stage) - Enhanced: '{enhanced_negative[:100]}...'"
                )
            else:
                enhanced_negative = negative_prompt

            # Check if refiner is configured for SDXL (native API support via override_settings)
            refiner_checkpoint = txt2img_config.get("refiner_checkpoint")
            # Allow either ratio (0-1) or absolute step count via refiner_switch_steps
            refiner_switch_at = txt2img_config.get("refiner_switch_at", 0.8)
            try:
                base_steps_for_switch = int(txt2img_config.get("steps", 20))
            except Exception:
                base_steps_for_switch = 20
            try:
                switch_steps = int(txt2img_config.get("refiner_switch_steps", 0) or 0)
            except Exception:
                switch_steps = 0
            if switch_steps and base_steps_for_switch > 0:
                # Convert absolute step to ratio clamped to (0,1)
                computed_ratio = max(0.01, min(0.99, switch_steps / float(base_steps_for_switch)))
                logger.info(
                    "🔀 Converting refiner_switch_steps=%d of %d to ratio=%.3f",
                    switch_steps,
                    base_steps_for_switch,
                    computed_ratio,
                )
                refiner_switch_at = computed_ratio
            use_refiner = (
                refiner_checkpoint
                and refiner_checkpoint != "None"
                and refiner_checkpoint.strip() != ""
                and 0.0 < refiner_switch_at < 1.0
            )

            if use_refiner:
                # Compute expected switch step number within the base pass and within combined progress
                try:
                    base_steps = int(txt2img_config.get("steps", 20))
                except Exception:
                    base_steps = 20
                enable_hr = bool(txt2img_config.get("enable_hr", False))
                hr_steps_cfg = int(txt2img_config.get("hr_second_pass_steps", 0) or 0)
                effective_hr_steps = (
                    (hr_steps_cfg if hr_steps_cfg > 0 else base_steps) if enable_hr else 0
                )
                expected_switch_step_base = max(1, int(round(refiner_switch_at * base_steps)))
                expected_switch_step_total = (
                    expected_switch_step_base  # progress bars often show total steps
                )
                total_steps_progress = base_steps + effective_hr_steps
                logger.info(
                    "🎨 SDXL Refiner enabled: %s | switch_at=%s (≈ step %d of base %d; ≈ %d/%d total)",
                    refiner_checkpoint,
                    refiner_switch_at,
                    expected_switch_step_base,
                    base_steps,
                    expected_switch_step_total,
                    total_steps_progress,
                )

            # Set model and VAE if specified
            model_name = txt2img_config.get("model") or txt2img_config.get("sd_model_checkpoint")
            vae_name = txt2img_config.get("vae")
            if model_name or vae_name:
                self._ensure_model_and_vae(model_name, vae_name)

            self._ensure_hypernetwork(
                txt2img_config.get("hypernetwork"),
                txt2img_config.get("hypernetwork_strength"),
            )

            # Parse sampler configuration for this stage
            sampler_config = self._parse_sampler_config(txt2img_config)

            # Log configuration validation
            logger.debug(f"📝 Input txt2img config: {json.dumps(txt2img_config, indent=2)}")

            payload = {
                "prompt": prompt,
                "negative_prompt": enhanced_negative,
                "steps": txt2img_config.get("steps", 20),
                "cfg_scale": txt2img_config.get("cfg_scale", 7.0),
                "width": txt2img_config.get("width", 512),
                "height": txt2img_config.get("height", 512),
                "seed": txt2img_config.get("seed", -1),
                "seed_resize_from_h": txt2img_config.get("seed_resize_from_h", -1),
                "seed_resize_from_w": txt2img_config.get("seed_resize_from_w", -1),
                "clip_skip": txt2img_config.get("clip_skip", 2),
                "batch_size": txt2img_config.get("batch_size", 1),
                "n_iter": txt2img_config.get("n_iter", 1),
                "restore_faces": txt2img_config.get("restore_faces", False),
                "tiling": txt2img_config.get("tiling", False),
                "do_not_save_samples": txt2img_config.get("do_not_save_samples", False),
                "do_not_save_grid": txt2img_config.get("do_not_save_grid", False),
            }

            # Always include hires.fix parameters (will be ignored if enable_hr is False)
            payload.update(
                {
                    "enable_hr": txt2img_config.get("enable_hr", False),
                    "hr_scale": txt2img_config.get("hr_scale", 2.0),
                    "hr_upscaler": txt2img_config.get("hr_upscaler", "Latent"),
                    "hr_second_pass_steps": txt2img_config.get("hr_second_pass_steps", 0),
                    "hr_resize_x": txt2img_config.get("hr_resize_x", 0),
                    "hr_resize_y": txt2img_config.get("hr_resize_y", 0),
                    "denoising_strength": txt2img_config.get("denoising_strength", 0.7),
                }
            )
            # Optional separate sampler for hires second pass
            try:
                hr_sampler_name = txt2img_config.get("hr_sampler_name")
                if hr_sampler_name:
                    payload["hr_sampler_name"] = hr_sampler_name
            except Exception:
                pass

            payload.update(sampler_config)

            prompt_after, negative_after = self._apply_aesthetic_to_payload(payload, config)
            payload["prompt"] = prompt_after
            payload["negative_prompt"] = negative_after
            try:
                logger.info(
                    "🎨 Final txt2img negative prompt (with global + aesthetic): '%s'",
                    (negative_after[:160] + "...") if len(negative_after) > 160 else negative_after,
                )
            except Exception:
                pass

            # Add styles if specified
            if txt2img_config.get("styles"):
                payload["styles"] = txt2img_config["styles"]

            # Add refiner support (SDXL native API - top-level parameters)
            if use_refiner:
                # Strip hash from checkpoint name if present (e.g., "model.safetensors [abc123]" -> "model.safetensors")
                # Defensive: ensure refiner_checkpoint is string before split
                try:
                    ref_str = str(refiner_checkpoint) if refiner_checkpoint else ""
                    refiner_checkpoint_clean = (
                        ref_str.split(" [")[0] if " [" in ref_str else ref_str
                    )
                except Exception:
                    refiner_checkpoint_clean = str(refiner_checkpoint) if refiner_checkpoint else ""
                # Refiner parameters go at the top level of the payload
                payload["refiner_checkpoint"] = refiner_checkpoint_clean
                payload["refiner_switch_at"] = refiner_switch_at
                logger.debug(
                    f"🎨 Refiner params: checkpoint={refiner_checkpoint_clean}, switch_at={refiner_switch_at}"
                )

            # Log final payload for validation
            logger.debug(f"🚀 Sending txt2img payload: {json.dumps(payload, indent=2)}")

            # Generate image
            self._apply_webui_defaults_once()
            response = self.client.txt2img(payload)
            if not response or "images" not in response or not response["images"]:
                logger.error("txt2img failed - no images returned")
                return None

            # Save final image with provided name
            image_path = output_dir / f"{image_name}.png"

            if save_image_from_base64(response["images"][0], image_path):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                metadata = {
                    "name": image_name,
                    "stage": "txt2img",
                    "timestamp": timestamp,
                    "original_prompt": prompt,
                    "final_prompt": payload.get("prompt", prompt),
                    "prompt": payload.get("prompt", prompt),  # backward compatibility
                    "original_negative_prompt": negative_prompt,
                    "final_negative_prompt": payload.get("negative_prompt", enhanced_negative),
                    "negative_prompt": payload.get(
                        "negative_prompt", enhanced_negative
                    ),  # backward compatibility
                    "global_negative_applied": apply_global,
                    "global_negative_terms": self.config_manager.get_global_negative_prompt()
                    if apply_global
                    else "",
                    "config": self._clean_metadata_payload(payload),
                    "output_path": str(image_path),
                    "path": str(image_path),
                }

                # Save manifest (pack manifests for GUI, run manifests for CLI) - use stage-suffixed name
                if output_dir.name in ["txt2img", "img2img", "upscaled"]:
                    pack_dir = output_dir.parent
                    manifest_name = f"{image_name}_txt2img"
                    try:
                        self.logger.save_pack_manifest(pack_dir, manifest_name, metadata)
                    except Exception:
                        manifest_dir = pack_dir / "manifests"
                        manifest_dir.mkdir(exist_ok=True, parents=True)
                        with open(
                            manifest_dir / f"{manifest_name}.json", "w", encoding="utf-8"
                        ) as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)
                else:
                    try:
                        self.logger.save_manifest(output_dir, image_name, metadata)
                    except Exception:
                        manifest_dir = output_dir / "manifests"
                        manifest_dir.mkdir(exist_ok=True, parents=True)
                        with open(manifest_dir / f"{image_name}.json", "w", encoding="utf-8") as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)

                return metadata
            else:
                logger.error("Failed to save generated image")
                return None

        except Exception as e:
            logger.error(f"txt2img stage failed: {str(e)}")
            return None

    def run_img2img_stage(
        self,
        input_image_path: Path,
        prompt: str,
        config: dict[str, Any],
        output_dir: Path,
        image_name: str,
        full_config: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Run img2img stage for image cleanup/refinement.

        Args:
            input_image_path: Path to input image
            prompt: Text prompt
            config: img2img configuration
            output_dir: Output directory
            image_name: Base name for output image

        Returns:
            Generated image metadata or None if failed
        """
        try:
            # Ensure output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)

            # Load input image as base64
            input_image_b64 = self._load_image_base64(input_image_path)
            if not input_image_b64:
                logger.error(f"Failed to load input image: {input_image_path}")
                return None

            # Set model and VAE if specified
            model_name = config.get("model")
            vae_name = config.get("vae")
            if model_name or vae_name:
                self._ensure_model_and_vae(model_name, vae_name)

            self._ensure_hypernetwork(
                config.get("hypernetwork"),
                config.get("hypernetwork_strength"),
            )

            # Build img2img payload
            # Combine negative prompt with optional adjustments
            base_negative = config.get("negative_prompt", "")
            neg_adjust = (config.get("negative_adjust") or "").strip()
            original_negative_prompt = (
                base_negative if not neg_adjust else f"{base_negative} {neg_adjust}".strip()
            )

            # Optionally apply global negative safety terms based on stage flag
            apply_global = (
                (full_config or {}).get("pipeline", {}).get("apply_global_negative_img2img", True)
            )
            if apply_global:
                enhanced_negative = self.config_manager.add_global_negative(
                    original_negative_prompt
                )
                try:
                    logger.info(
                        "🛡️ Applied global NSFW prevention (img2img stage) - Enhanced: '%s'",
                        (enhanced_negative[:100] + "...")
                        if len(enhanced_negative) > 100
                        else enhanced_negative,
                    )
                except Exception:
                    pass
            else:
                enhanced_negative = original_negative_prompt

            sampler_config = self._parse_sampler_config(config)

            payload = {
                "init_images": [input_image_b64],
                "prompt": prompt,
                "negative_prompt": enhanced_negative,
                "steps": config.get("steps", 15),
                "cfg_scale": config.get("cfg_scale", 7.0),
                "denoising_strength": config.get("denoising_strength", 0.3),
                "width": config.get("width", 512),
                "height": config.get("height", 512),
                "seed": config.get("seed", -1),
                "clip_skip": config.get("clip_skip", 2),
                "batch_size": 1,
                "n_iter": 1,
            }

            payload.update(sampler_config)

            # Apply aesthetic adjustments AFTER global negative safety terms so they layer on top
            prompt_after, negative_after = self._apply_aesthetic_to_payload(
                payload, full_config or {"aesthetic": {}}
            )
            payload["prompt"] = prompt_after
            payload["negative_prompt"] = negative_after
            try:
                logger.info(
                    "🎨 Final img2img negative prompt (with%s global + aesthetic): '%s'",
                    "" if apply_global else "out",
                    (negative_after[:160] + "...") if len(negative_after) > 160 else negative_after,
                )
            except Exception:
                pass

            # Log key parameters at INFO to correlate with WebUI progress
            try:
                logger.info(
                    "img2img params => steps=%s, denoise=%s, sampler=%s, scheduler=%s",
                    payload.get("steps"),
                    payload.get("denoising_strength"),
                    payload.get("sampler_name"),
                    payload.get("scheduler"),
                )
            except Exception:
                pass

            # Execute img2img
            response = self.client.img2img(payload)
            if not response or "images" not in response or not response["images"]:
                logger.error("img2img request failed or returned no images")
                return None

            # Save image
            image_path = output_dir / f"{image_name}.png"

            if save_image_from_base64(response["images"][0], image_path):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                metadata = {
                    "name": image_name,
                    "stage": "img2img",
                    "timestamp": timestamp,
                    "original_prompt": prompt,
                    "final_prompt": payload.get("prompt", prompt),
                    "prompt": payload.get("prompt", prompt),
                    "original_negative_prompt": original_negative_prompt,
                    "final_negative_prompt": payload.get("negative_prompt", ""),
                    "negative_prompt": payload.get("negative_prompt", ""),
                    "global_negative_applied": apply_global,
                    "global_negative_terms": self.config_manager.get_global_negative_prompt()
                    if apply_global
                    else "",
                    "input_image": str(input_image_path),
                    "config": self._clean_metadata_payload(payload),
                    "path": str(image_path),
                }

                # Save manifest (pack manifests for GUI, run manifests for CLI) - stage-suffixed
                if output_dir.name in ["txt2img", "img2img", "upscaled"]:
                    pack_dir = output_dir.parent
                    manifest_name = f"{image_name}_img2img"
                    try:
                        self.logger.save_pack_manifest(pack_dir, manifest_name, metadata)
                    except Exception:
                        manifest_dir = pack_dir / "manifests"
                        manifest_dir.mkdir(exist_ok=True, parents=True)
                        with open(
                            manifest_dir / f"{manifest_name}.json", "w", encoding="utf-8"
                        ) as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)
                else:
                    try:
                        self.logger.save_manifest(output_dir, image_name, metadata)
                    except Exception:
                        manifest_dir = output_dir / "manifests"
                        manifest_dir.mkdir(exist_ok=True, parents=True)
                        with open(manifest_dir / f"{image_name}.json", "w", encoding="utf-8") as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)

                logger.info(f"✅ img2img completed: {image_path.name}")
                return metadata
            else:
                logger.error(f"Failed to save img2img image: {image_path}")
                return None

        except Exception as e:
            logger.error(f"img2img stage failed: {e}")
            return None

    def run_upscale_stage(
        self, input_image_path: Path, config: dict[str, Any], output_dir: Path, image_name: str
    ) -> dict[str, Any] | None:
        """
        Run upscale stage for image enhancement.

        Args:
            input_image_path: Path to input image
            config: Upscale configuration
            output_dir: Output directory
            image_name: Base name for output image

        Returns:
            Generated image metadata or None if failed
        """
        try:
            # Ensure output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)

            # Load input image as base64
            input_image_b64 = self._load_image_base64(input_image_path)
            if not input_image_b64:
                logger.error(f"Failed to load input image: {input_image_path}")
                return None

            upscale_mode = config.get("upscale_mode", "single")

            if hasattr(self.client, "ensure_safe_upscale_defaults"):
                try:
                    self.client.ensure_safe_upscale_defaults()
                except Exception as exc:  # noqa: BLE001 - best-effort safety clamp
                    logger.debug("ensure_safe_upscale_defaults failed: %s", exc)

            if upscale_mode == "img2img":
                # Use img2img for upscaling with denoising
                # First get original image dimensions to calculate target size
                try:
                    image_bytes = base64.b64decode(input_image_b64)
                    with Image.open(BytesIO(image_bytes)) as pil_image:
                        orig_width, orig_height = pil_image.size
                except Exception as exc:
                    logger.error("Failed to inspect image dimensions for upscale: %s", exc)
                    return None

                upscale_factor = config.get("upscaling_resize", 2.0)
                target_width = int(orig_width * upscale_factor)
                target_height = int(orig_height * upscale_factor)

                logger.info(
                    "UPSCALE DIAG: mode=img2img, upscaler=%s, resize=%s, input=%sx%s, target=%sx%s",
                    config.get("upscaler", "R-ESRGAN 4x+"),
                    upscale_factor,
                    orig_width,
                    orig_height,
                    target_width,
                    target_height,
                )

                payload = {
                    "init_images": [input_image_b64],
                    "prompt": config.get("prompt", ""),
                    "negative_prompt": config.get("negative_prompt", ""),
                    "steps": config.get("steps", 20),
                    "cfg_scale": config.get("cfg_scale", 7.0),
                    "denoising_strength": config.get("denoising_strength", 0.35),
                    "width": target_width,
                    "height": target_height,
                    "sampler_name": config.get("sampler_name", "Euler a"),
                    "scheduler": config.get("scheduler", "normal"),
                    "seed": config.get("seed", -1),
                    "clip_skip": config.get("clip_skip", 2),
                    "batch_size": 1,
                    "n_iter": 1,
                }

                try:
                    logger.info(
                        "upscale(img2img) params => steps=%s, denoise=%s, sampler=%s, scheduler=%s, target=%sx%s",
                        payload.get("steps"),
                        payload.get("denoising_strength"),
                        payload.get("sampler_name"),
                        payload.get("scheduler"),
                        target_width,
                        target_height,
                    )
                except Exception:
                    pass

                # Apply global negative if any (upscale-as-img2img path may include a negative prompt)
                try:
                    original_neg = payload.get("negative_prompt", "")
                    if original_neg:
                        apply_global = (
                            config.get("pipeline", {}) if isinstance(config, dict) else {}
                        ).get("apply_global_negative_upscale", True)
                        if apply_global:
                            enhanced_neg = self.config_manager.add_global_negative(original_neg)
                            payload["negative_prompt"] = enhanced_neg
                            logger.info(
                                "🛡️ Applied global NSFW prevention (upscale img2img) - Enhanced: '%s'",
                                (enhanced_neg[:120] + "...")
                                if len(enhanced_neg) > 120
                                else enhanced_neg,
                            )
                        else:
                            logger.info("⚠️ Global negative skipped for upscale(img2img) stage")
                except Exception:
                    pass

                response = self.client.img2img(payload)
                response_key = "images"
                image_key = 0
            else:
                # Use extra-single-image upscaling via client API
                upscaler = config.get("upscaler", "R-ESRGAN 4x+")
                upscaling_resize = config.get("upscaling_resize", 2.0)
                gfpgan_vis = config.get("gfpgan_visibility", 0.0)
                codeformer_vis = config.get("codeformer_visibility", 0.0)
                codeformer_weight = config.get("codeformer_weight", 0.5)

                orig_width: int | None = None
                orig_height: int | None = None
                try:
                    image_bytes = base64.b64decode(input_image_b64)
                    with Image.open(BytesIO(image_bytes)) as pil_image:
                        orig_width, orig_height = pil_image.size
                except Exception as exc:
                    logger.warning(
                        "UPSCALE DIAG: failed to read input size for %s: %s",
                        input_image_path.name,
                        exc,
                    )

                logger.info(
                    "UPSCALE DIAG: mode=single, upscaler=%s, resize=%s, input=%sx%s, target=%sx%s",
                    upscaler,
                    upscaling_resize,
                    orig_width if orig_width is not None else "?",
                    orig_height if orig_height is not None else "?",
                    int(orig_width * upscaling_resize) if orig_width is not None else "?",
                    int(orig_height * upscaling_resize) if orig_height is not None else "?",
                )

                # Prepare payload for metadata regardless of call method
                payload = {
                    "image": input_image_b64,
                    "upscaling_resize": upscaling_resize,
                    "upscaler_1": upscaler,
                    "gfpgan_visibility": gfpgan_vis,
                    "codeformer_visibility": codeformer_vis,
                    "codeformer_weight": codeformer_weight,
                }
                try:
                    # Preferred: typed helper with explicit parameters
                    response = self.client.upscale_image(
                        input_image_b64,
                        upscaler,
                        upscaling_resize,
                        gfpgan_vis,
                        codeformer_vis,
                        codeformer_weight,
                    )
                except TypeError:
                    # Fallback: older dict-based helper
                    response = getattr(self.client, "upscale", lambda p: None)(payload)
                response_key = "image"
                image_key = None

            if not response or response_key not in response:
                logger.error("Upscale request failed or returned no image")
                return None

            # Save image
            image_path = output_dir / f"{image_name}.png"

            # Extract the correct image data based on upscale mode
            if image_key is None:
                image_data = response[response_key]
            else:
                if not response[response_key] or len(response[response_key]) <= image_key:
                    logger.error("No image data returned from upscale")
                    return None
                image_data = response[response_key][image_key]

            if save_image_from_base64(image_data, image_path):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                metadata = {
                    "name": image_name,
                    "stage": "upscale",
                    "timestamp": timestamp,
                    "input_image": str(input_image_path),
                    "final_negative_prompt": payload.get("negative_prompt"),
                    "global_negative_applied": (
                        config.get("pipeline", {}) if isinstance(config, dict) else {}
                    ).get("apply_global_negative_upscale", True)
                    if isinstance(payload, dict) and "init_images" in payload
                    else False,
                    "global_negative_terms": self.config_manager.get_global_negative_prompt()
                    if (
                        isinstance(payload, dict)
                        and "init_images" in payload
                        and payload.get("negative_prompt")
                    )
                    else "",
                    "config": self._clean_metadata_payload(payload),
                    "path": str(image_path),
                }

                # Save manifest (prefer pack manifests) with stage suffix to avoid overwriting
                if output_dir.name in ["txt2img", "img2img", "upscaled"]:
                    pack_dir = output_dir.parent
                    manifest_name = f"{image_name}_upscale"
                    try:
                        self.logger.save_pack_manifest(pack_dir, manifest_name, metadata)
                    except Exception:
                        manifest_dir = pack_dir / "manifests"
                        manifest_dir.mkdir(exist_ok=True, parents=True)
                        with open(
                            manifest_dir / f"{manifest_name}.json", "w", encoding="utf-8"
                        ) as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)
                else:
                    manifest_dir = output_dir / "manifests"
                    manifest_dir.mkdir(exist_ok=True)
                    with open(
                        manifest_dir / f"{image_name}_upscale.json", "w", encoding="utf-8"
                    ) as f:
                        json.dump(metadata, f, indent=2, ensure_ascii=False)

                logger.info(f"✅ Upscale completed: {image_path.name}")
                return metadata
            else:
                logger.error(f"Failed to save upscaled image: {image_path}")
                return None

        except Exception as e:
            logger.error(f"Upscale stage failed: {e}")
            return None

```

## `src/pipeline/variant_planner.py`

```
"""Helpers for building model/hypernetwork variant runs."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from typing import Any


@dataclass(frozen=True)
class VariantSpec:
    """Concrete model/hypernetwork combination to apply to a prompt run."""

    index: int
    model: str | None
    hypernetwork: str | None
    hypernetwork_strength: float | None

    @property
    def label(self) -> str:
        """Human readable description."""

        model_part = f"model={self.model}" if self.model else "model=base"
        if self.hypernetwork:
            hyper_part = f"hyper={self.hypernetwork}" + (
                f" ({self.hypernetwork_strength:.2f})"
                if self.hypernetwork_strength is not None
                else ""
            )
        else:
            hyper_part = "hyper=off"
        return f"{model_part} | {hyper_part}"


@dataclass(frozen=True)
class VariantPlan:
    """Describes how to iterate variant combinations."""

    mode: str
    variants: list[VariantSpec]

    @property
    def active(self) -> bool:
        return bool(self.variants)


def _clean_matrix_entries(raw: Iterable[Any]) -> list[str]:
    cleaned: list[str] = []
    for entry in raw or []:
        if entry is None:
            continue
        text = str(entry).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _clean_hypernet_entries(raw: Iterable[Any]) -> list[tuple[str | None, float | None]]:
    cleaned: list[tuple[str | None, float | None]] = []
    for entry in raw or []:
        if isinstance(entry, dict):
            name = entry.get("name")
            strength = entry.get("strength")
        else:
            name = entry
            strength = None
        if name is None:
            continue
        text = str(name).strip()
        if not text:
            continue
        if text.lower() == "none":
            cleaned.append((None, None))
        else:
            try:
                strength_value = float(strength) if strength is not None else None
            except (TypeError, ValueError):
                strength_value = None
            cleaned.append((text, strength_value))
    return cleaned


def build_variant_plan(config: dict[str, Any] | None) -> VariantPlan:
    """Create a VariantPlan from the current pipeline configuration."""

    config = config or {}
    pipeline_cfg = config.get("pipeline", {}) or {}

    base_txt = config.get("txt2img", {}) or {}
    base_img = config.get("img2img", {}) or {}
    base_model = base_txt.get("model") or base_img.get("model")
    base_hn = base_txt.get("hypernetwork") or base_img.get("hypernetwork")
    base_hn_strength = base_txt.get("hypernetwork_strength") or base_img.get(
        "hypernetwork_strength"
    )

    matrix_entries = _clean_matrix_entries(pipeline_cfg.get("model_matrix", []))
    hyper_entries = _clean_hypernet_entries(pipeline_cfg.get("hypernetworks", []))

    matrix_defined = bool(matrix_entries)
    hyper_defined = bool(hyper_entries)

    if not matrix_entries:
        matrix_entries = [base_model] if base_model else [None]

    if not hyper_entries:
        if base_hn or base_hn_strength is not None:
            hyper_entries = [(base_hn if base_hn else None, base_hn_strength)]
        else:
            hyper_entries = [(None, None)]

    mode = str(pipeline_cfg.get("variant_mode", "fanout")).strip().lower()
    if mode not in {"fanout", "rotate"}:
        mode = "fanout"

    # If neither matrix nor hypernets were explicitly configured, treat as inactive.
    if not matrix_defined and not hyper_defined:
        return VariantPlan(mode=mode, variants=[])

    variants: list[VariantSpec] = []
    for idx, (model_entry, hyper_entry) in enumerate(product(matrix_entries, hyper_entries)):
        model_value = model_entry if model_entry else None
        hyper_name, hyper_strength = hyper_entry
        variants.append(
            VariantSpec(
                index=idx,
                model=model_value,
                hypernetwork=hyper_name,
                hypernetwork_strength=hyper_strength,
            )
        )

    return VariantPlan(mode=mode, variants=variants)


def apply_variant_to_config(
    config: dict[str, Any] | None,
    variant: VariantSpec | None,
) -> dict[str, Any]:
    """Return a deepcopy of config with the variant overrides applied."""

    cfg = deepcopy(config or {})
    pipeline_cfg = cfg.setdefault("pipeline", {})

    if variant is None:
        pipeline_cfg.pop("active_variant", None)
        return cfg

    for section in ("txt2img", "img2img"):
        stage = cfg.setdefault(section, {})
        if variant.model is not None:
            stage["model"] = variant.model

    for section in ("txt2img", "img2img"):
        stage = cfg.setdefault(section, {})
        stage["hypernetwork"] = variant.hypernetwork
        stage["hypernetwork_strength"] = variant.hypernetwork_strength

    pipeline_cfg["active_variant"] = {
        "index": variant.index,
        "label": variant.label,
    }

    return cfg

```

## `src/pipeline/video.py`

```
"""Video creation utilities using FFmpeg"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoCreator:
    """Create videos from image sequences using FFmpeg"""

    def __init__(self):
        """Initialize video creator"""
        self.ffmpeg_available = self._check_ffmpeg()

    def _check_ffmpeg(self) -> bool:
        """
        Check if FFmpeg is available.

        Returns:
            True if FFmpeg is available
        """
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                logger.info("FFmpeg is available")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("FFmpeg not found or not responding")

        return False

    def create_video_from_images(
        self,
        image_paths: list[Path],
        output_path: Path,
        fps: int = 24,
        codec: str = "libx264",
        quality: str = "medium",
    ) -> bool:
        """
        Create video from a list of images.

        Args:
            image_paths: List of paths to images
            output_path: Path for output video
            fps: Frames per second (default: 24)
            codec: Video codec (default: libx264)
            quality: Quality preset (default: medium)

        Returns:
            True if video created successfully
        """
        if not self.ffmpeg_available:
            logger.error("FFmpeg not available, cannot create video")
            return False

        if not image_paths:
            logger.error("No images provided for video creation")
            return False

        try:
            # Sort images by name for proper sequence
            sorted_paths = sorted(image_paths, key=lambda x: x.name)

            # Create temporary file list for FFmpeg
            temp_dir = output_path.parent / "temp"
            temp_dir.mkdir(exist_ok=True)

            # Copy/symlink images with sequential names
            temp_images = []
            for i, img_path in enumerate(sorted_paths):
                if not img_path.exists():
                    logger.warning(f"Image not found: {img_path}")
                    continue

                temp_name = f"frame_{i:06d}{img_path.suffix}"
                temp_path = temp_dir / temp_name

                # Create symlink or copy
                try:
                    if hasattr(temp_path, "symlink_to"):
                        temp_path.symlink_to(img_path.absolute())
                    else:
                        import shutil

                        shutil.copy2(img_path, temp_path)
                    temp_images.append(temp_path)
                except Exception as e:
                    logger.warning(f"Failed to link/copy {img_path.name}: {e}")

            if not temp_images:
                logger.error("No valid images for video creation")
                return False

            # Build FFmpeg command
            input_pattern = str(temp_dir / "frame_%06d*")

            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-framerate",
                str(fps),
                "-pattern_type",
                "glob",
                "-i",
                input_pattern,
                "-c:v",
                codec,
                "-preset",
                quality,
                "-pix_fmt",
                "yuv420p",  # Compatibility
                str(output_path),
            ]

            logger.info(f"Creating video with {len(temp_images)} frames")
            logger.info(f"FFmpeg command: {' '.join(cmd)}")

            # Execute FFmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            # Cleanup temp directory
            try:
                import shutil

                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {e}")

            if result.returncode == 0:
                logger.info(f"Video created successfully: {output_path.name}")
                return True
            else:
                logger.error(f"FFmpeg failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg timed out")
            return False
        except Exception as e:
            logger.error(f"Video creation failed: {e}")
            return False

    def create_slideshow_video(
        self,
        image_paths: list[Path],
        output_path: Path,
        duration_per_image: float = 3.0,
        transition_duration: float = 0.5,
        fps: int = 24,
    ) -> bool:
        """
        Create a slideshow video with transitions.

        Args:
            image_paths: List of paths to images
            output_path: Path for output video
            duration_per_image: Duration each image is shown (seconds)
            transition_duration: Duration of fade transitions (seconds)
            fps: Frames per second

        Returns:
            True if video created successfully
            fps: Frames per second
            codec: Video codec to use
            quality: Video quality preset

        Returns:
            True if video created successfully
        """
        if not self.ffmpeg_available:
            logger.error("FFmpeg is not available")
            return False

        if not image_paths:
            logger.error("No images provided")
            return False

        try:
            # Create a temporary file list for FFmpeg
            list_file = output_path.parent / "ffmpeg_input.txt"
            with open(list_file, "w", encoding="utf-8") as f:
                for img_path in image_paths:
                    # FFmpeg concat demuxer format
                    f.write(f"file '{img_path.absolute()}'\n")
                    f.write(f"duration {1/fps}\n")
                # Add last image again for proper duration
                if image_paths:
                    f.write(f"file '{image_paths[-1].absolute()}'\n")

            # Build FFmpeg command
            cmd = [
                "ffmpeg",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c:v",
                codec,
                "-preset",
                quality,
                "-pix_fmt",
                "yuv420p",
                "-y",  # Overwrite output file
                str(output_path),
            ]

            logger.info(f"Creating video with {len(image_paths)} images at {fps} fps")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            # Clean up temp file
            list_file.unlink(missing_ok=True)

            if result.returncode == 0:
                logger.info(f"Video created successfully: {output_path.name}")
                return True
            else:
                logger.error(f"FFmpeg failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg command timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to create video: {e}")
            return False

    def create_video_from_directory(
        self,
        image_dir: Path,
        output_path: Path,
        pattern: str = "*.png",
        fps: int = 24,
        codec: str = "libx264",
        quality: str = "medium",
    ) -> bool:
        """
        Create video from all images in a directory.

        Args:
            image_dir: Directory containing images
            output_path: Path for output video
            pattern: Glob pattern for image files
            fps: Frames per second
            codec: Video codec to use
            quality: Video quality preset

        Returns:
            True if video created successfully
        """
        image_paths = sorted(image_dir.glob(pattern))
        if not image_paths:
            logger.warning(f"No images found in {image_dir} with pattern {pattern}")
            return False

        logger.info(f"Found {len(image_paths)} images in {image_dir}")
        return self.create_video_from_images(image_paths, output_path, fps, codec, quality)

```

## `src/services/config_service.py`

```
import json
from pathlib import Path
from typing import Any, cast


class ConfigService:
    def __init__(self, packs_dir: Path, presets_dir: Path, lists_dir: Path):
        self.packs_dir = Path(packs_dir)
        self.presets_dir = Path(presets_dir)
        self.lists_dir = Path(lists_dir)

        self.packs_dir.mkdir(parents=True, exist_ok=True)
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        self.lists_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_pack_path(self, pack: str | Path) -> Path:
        candidate = Path(pack)
        if candidate.suffix.lower() == ".json":
            base = candidate.name
        elif candidate.suffix:
            base = candidate.with_suffix("").name
        else:
            base = candidate.name
        return self.packs_dir / f"{base}.json"

    def load_pack_config(self, pack: str) -> dict[str, Any]:
        path = self._resolve_pack_path(pack)
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))

    def save_pack_config(self, pack: str, cfg: dict) -> None:
        path = self._resolve_pack_path(pack)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def list_presets(self) -> list[str]:
        return [p.stem for p in self.presets_dir.glob("*.json")]

    def load_preset(self, name: str) -> dict[str, Any]:
        path = self.presets_dir / f"{name}.json"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))

    def save_preset(self, name: str, cfg: dict, overwrite: bool = True) -> None:
        path = self.presets_dir / f"{name}.json"
        if path.exists() and not overwrite:
            raise FileExistsError(f"Preset {name} already exists.")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def delete_preset(self, name: str) -> None:
        path = self.presets_dir / f"{name}.json"
        if path.exists():
            path.unlink()

    def _resolve_list_path(self, name: str | Path) -> Path:
        candidate = Path(name)
        if candidate.suffix.lower() == ".json":
            return self.lists_dir / candidate.name
        return self.lists_dir / f"{candidate.stem}.json"

    def load_list(self, name: str) -> list[str]:
        path = self._resolve_list_path(name)
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = cast(dict[str, Any], json.load(f))
        return cast(list[str], data.get("packs", []))

    def save_list(self, name: str, packs: list[str], overwrite: bool = True) -> None:
        path = self._resolve_list_path(name)
        if path.exists() and not overwrite:
            raise FileExistsError(f"List {name} already exists.")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"packs": packs}, f, indent=2)

    def delete_list(self, name: str) -> None:
        path = self._resolve_list_path(name)
        if path.exists():
            path.unlink()

    def list_lists(self) -> list[str]:
        return sorted(p.stem for p in self.lists_dir.glob("*.json"))

```

## `src/utils/__init__.py`

```
"""Utilities module"""

from .config import ConfigManager, build_sampler_scheduler_payload
from .file_io import (
    get_prompt_packs,
    get_safe_filename,
    load_image_to_base64,
    read_prompt_pack,
    read_text_file,
    save_image_from_base64,
    write_text_file,
)
from .logger import StructuredLogger, setup_logging
from .preferences import PreferencesManager
from .webui_discovery import find_webui_api_port, wait_for_webui_ready

__all__ = [
    "ConfigManager",
    "build_sampler_scheduler_payload",
    "StructuredLogger",
    "setup_logging",
    "PreferencesManager",
    "save_image_from_base64",
    "load_image_to_base64",
    "read_text_file",
    "write_text_file",
    "read_prompt_pack",
    "get_prompt_packs",
    "get_safe_filename",
    "find_webui_api_port",
    "wait_for_webui_ready",
]

```

## `src/utils/_extract_name_prefix.py`

```
def extract_name_prefix(name: str, base: str) -> str:
    """
    Generate a filename prefix from a name and a base string.
    Both are sanitized for safe filenames.
    """
    import re

    def safe(s):
        # Remove or replace invalid filename characters
        s = re.sub(r'[<>:"\\/|?*]', "_", s)
        s = s.strip(" .")
        return s

    return f"{safe(name)}_{safe(base)}"

```

## `src/utils/aesthetic.py`

```
"""Helpers for locating the Aesthetic Gradient extension."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

# Normalised names observed in the wild for the Aesthetic Gradient extension
KNOWN_AESTHETIC_EXTENSION_NAMES = {
    "stable-diffusion-webui-aesthetic-gradients",
    "stable-diffusion-webui-aesthetic-gradients-master",
    "sd-webui-aesthetic-gradients",
    "sd-webui-aesthetic-gradients-master",
}


def _normalise(path: Path | str) -> str:
    return str(path).strip().lower()


def find_aesthetic_extension_dir(extensions_root: Path) -> Path | None:
    """Return the first extension directory that looks like Aesthetic Gradient."""

    if not extensions_root or not extensions_root.is_dir():
        return None

    for child in sorted(extensions_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name.lower()
        if name in KNOWN_AESTHETIC_EXTENSION_NAMES:
            return child
        if "aesthetic" in name and "gradient" in name:
            return child
    return None


def detect_aesthetic_extension(candidates: Iterable[Path]) -> tuple[bool, Path | None]:
    """Scan candidate roots for the extension directory."""

    seen: set[str] = set()
    for root in candidates:
        if not root:
            continue
        root_path = Path(root)
        key = _normalise(root_path)
        if key in seen:
            continue
        seen.add(key)
        extensions_dir = root_path / "extensions"
        match = find_aesthetic_extension_dir(extensions_dir)
        if match:
            return True, match
    return False, None

```

## `src/utils/aesthetic_detection.py`

```
from pathlib import Path
from typing import Optional


def detect_aesthetic_extension(candidates: list[Path]) -> tuple[bool, Optional[Path]]:
    """
    Scan candidate directories for an 'extensions/Aesthetic-Gradient' subdir.
    Returns (found, extension_dir) where extension_dir is the Path if found.
    """
    for root in candidates:
        ext_dir = root / "extensions" / "Aesthetic-Gradient"
        if ext_dir.exists() and ext_dir.is_dir():
            return True, ext_dir
    return False, None

```

## `src/utils/config.py`

```
"""Configuration management utilities"""

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_GLOBAL_NEGATIVE_PROMPT = (
    "blurry, bad quality, distorted, ugly, malformed, nsfw, nude, naked, explicit, "
    "sexual content, adult content, immodest"
)

logger = logging.getLogger(__name__)


def _normalize_scheduler_name(scheduler: Optional[str]) -> Optional[str]:
    """
    Normalize scheduler names into values WebUI understands.

    Treats None, empty strings, "None", and "Automatic" (case-insensitive) as no scheduler.
    """

    if scheduler is None:
        return None

    value = str(scheduler).strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered in {"none", "automatic"}:
        return None

    return value


def build_sampler_scheduler_payload(
    sampler_name: Optional[str],
    scheduler_name: Optional[str],
) -> Dict[str, str]:
    """
    Build sampler / scheduler payload segment following WebUI expectations.

    When a scheduler is selected, we send both the combined sampler name
    (e.g., "DPM++ 2M Karras") and the explicit scheduler field. Otherwise
    we omit the scheduler key entirely and send only the sampler name.
    """

    payload: Dict[str, str] = {}

    sampler = (sampler_name or "").strip()
    if not sampler:
        return payload

    normalized_scheduler = _normalize_scheduler_name(scheduler_name)

    if normalized_scheduler:
        payload["sampler_name"] = f"{sampler} {normalized_scheduler}"
        payload["scheduler"] = normalized_scheduler
    else:
        payload["sampler_name"] = sampler

    return payload


class ConfigManager:
    """Manages configuration and presets"""

    def __init__(self, presets_dir: str = "presets"):
        """
        Initialize configuration manager.

        Args:
            presets_dir: Directory containing preset files
        """
        self.presets_dir = Path(presets_dir)
        self.presets_dir.mkdir(exist_ok=True)
        self._global_negative_path = self.presets_dir / "global_negative.txt"
        self._global_negative_cache: str | None = None
        self._default_preset_path = self.presets_dir / ".default_preset"

    def load_preset(self, name: str) -> dict[str, Any] | None:
        """
        Load a preset configuration.

        Args:
            name: Name of the preset

        Returns:
            Preset configuration dictionary
        """
        preset_path = self.presets_dir / f"{name}.json"
        if not preset_path.exists():
            logger.warning(f"Preset '{name}' not found at {preset_path}")
            return None

        try:
            with open(preset_path, encoding="utf-8") as f:
                preset = self._merge_config_with_defaults(json.load(f))
            logger.info(f"Loaded preset: {name}")
            return preset
        except Exception as e:
            logger.error(f"Failed to load preset '{name}': {e}")
            return None

    def save_preset(self, name: str, config: dict[str, Any]) -> bool:
        """
        Save a preset configuration.

        Args:
            name: Name of the preset
            config: Configuration dictionary

        Returns:
            True if saved successfully
        """
        preset_path = self.presets_dir / f"{name}.json"
        try:
            merged = self._merge_config_with_defaults(config)
            with open(preset_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved preset: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save preset '{name}': {e}")
            return False

    def list_presets(self) -> list:
        """
        List all available presets.

        Returns:
            List of preset names
        """
        presets = [p.stem for p in self.presets_dir.glob("*.json")]
        logger.info(f"Found {len(presets)} presets")
        return sorted(presets)

    def delete_preset(self, name: str) -> bool:
        """
        Delete a preset configuration.

        Args:
            name: Name of the preset to delete

        Returns:
            True if deleted successfully
        """
        if name == "default":
            logger.warning("Cannot delete the default preset")
            return False

        preset_path = self.presets_dir / f"{name}.json"
        if not preset_path.exists():
            logger.warning(f"Preset '{name}' not found at {preset_path}")
            return False

        try:
            preset_path.unlink()
            logger.info(f"Deleted preset: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete preset '{name}': {e}")
            return False

    def get_default_config(self) -> dict[str, Any]:
        """
        Get the default configuration for all pipeline stages.

        IMPORTANT: When adding new parameters to this configuration,
        run the validation test to ensure proper parameter pass-through:

        python tests/test_config_passthrough.py

        See CONFIGURATION_TESTING_GUIDE.md for detailed maintenance instructions.

        Returns:
            Dictionary containing default configuration for all stages
        """
        """
        Get default configuration.

        Returns:
            Default configuration dictionary
        """
        return {
            "txt2img": {
                "steps": 20,
                "sampler_name": "Euler a",
                "scheduler": "Normal",
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "negative_prompt": "blurry, bad quality, distorted",
                "seed": -1,  # -1 for random
                "seed_resize_from_h": -1,
                "seed_resize_from_w": -1,
                "enable_hr": False,  # High-res fix / hires.fix
                "hr_scale": 2.0,  # Hires.fix upscale factor
                "hr_upscaler": "Latent",  # Hires.fix upscaler
                "hr_sampler_name": "",  # Optional separate sampler for hires second pass
                "hr_second_pass_steps": 0,  # 0 = use same as steps
                "hr_resize_x": 0,  # 0 = automatic based on hr_scale
                "hr_resize_y": 0,  # 0 = automatic based on hr_scale
                "denoising_strength": 0.7,  # For hires.fix second pass
                "clip_skip": 2,  # CLIP layers to skip
                "model": "",  # SD model checkpoint (empty = use current)
                "vae": "",  # VAE model (empty = use model default)
                "hypernetwork": "None",
                "hypernetwork_strength": 1.0,
                "styles": [],  # Style names to apply
                # SDXL refiner controls
                "refiner_checkpoint": "",
                "refiner_switch_at": 0.8,  # ratio 0-1 used by WebUI
                "refiner_switch_steps": 0,  # optional: absolute step number within base pass; 0=unused
            },
            "img2img": {
                "steps": 15,
                "sampler_name": "Euler a",
                "scheduler": "Normal",
                "cfg_scale": 7.0,
                "denoising_strength": 0.3,
                "seed": -1,  # -1 for random
                "clip_skip": 2,
                "model": "",  # SD model checkpoint (empty = use current)
                "vae": "",  # VAE model (empty = use model default)
                "hypernetwork": "None",
                "hypernetwork_strength": 1.0,
                "prompt_adjust": "",
                "negative_adjust": "",
            },
            "upscale": {
                "upscaler": "R-ESRGAN 4x+",
                "upscaling_resize": 2.0,
                "upscale_mode": "single",  # "single" (direct) or "img2img" (more control)
                "denoising_strength": 0.35,  # For img2img-based upscaling
                "steps": 20,
                "sampler_name": "Euler a",
                "scheduler": "Normal",
                "gfpgan_visibility": 0.0,  # Face restoration strength
                "codeformer_visibility": 0.0,  # Face restoration alternative
                "codeformer_weight": 0.5,  # CodeFormer fidelity
            },
        "adetailer": {
            "adetailer_enabled": False,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_confidence": 0.3,
            "adetailer_mask_feather": 4,
            "adetailer_sampler": "DPM++ 2M",
            "adetailer_scheduler": "inherit",
            "adetailer_steps": 28,
            "adetailer_denoise": 0.4,
            "adetailer_cfg": 7.0,
            "adetailer_prompt": "",
            "adetailer_negative_prompt": "",
            },
            "video": {"fps": 24, "codec": "libx264", "quality": "medium"},
            "api": {"base_url": "http://127.0.0.1:7860", "timeout": 300},
            "randomization": {
                "enabled": False,
                # Optional seed for deterministic randomization.
                # When None, a fresh RNG seed is used each run.
                "seed": None,
                "prompt_sr": {
                    "enabled": False,
                    "mode": "random",
                    "rules": [],
                    "raw_text": "",
                },
                "wildcards": {
                    "enabled": False,
                    "mode": "random",
                    "tokens": [],
                    "raw_text": "",
                },
                "matrix": {
                    "enabled": False,
                    "mode": "fanout",
                    "limit": 8,
                    "slots": [],
                    "raw_text": "",
                },
            },
            "aesthetic": {
                "enabled": False,
                "mode": "script",
                "weight": 0.9,
                "steps": 5,
                "learning_rate": 0.0001,
                "slerp": False,
                "slerp_angle": 0.1,
                "embedding": "None",
                "text": "",
                "text_is_negative": False,
                "fallback_prompt": "",
            },
            "pipeline": {
                "img2img_enabled": True,
                "upscale_enabled": True,
                "adetailer_enabled": False,
                "allow_hr_with_stages": False,
                "refiner_compare_mode": False,  # When True and refiner+hires enabled, branch original & refined
                # Global negative application toggles per-stage (default True for backward compatibility)
                "apply_global_negative_txt2img": True,
                "apply_global_negative_img2img": True,
                "apply_global_negative_upscale": True,
                "apply_global_negative_adetailer": True,
            },
        }

    def resolve_config(
        self,
        preset_name: str = None,
        pack_overrides: dict[str, Any] = None,
        runtime_params: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """
        Resolve configuration with hierarchy: Default → Preset → Pack overrides → Runtime params.

        Args:
            preset_name: Name of preset to load
            pack_overrides: Pack-specific configuration overrides
            runtime_params: Runtime parameter overrides

        Returns:
            Resolved configuration dictionary
        """
        # Start with default config
        config = self.get_default_config()

        # Apply preset overrides
        if preset_name:
            preset_config = self.load_preset(preset_name)
            if preset_config:
                config = self._merge_configs(config, preset_config)

        # Apply pack-specific overrides
        if pack_overrides:
            config = self._merge_configs(config, pack_overrides)

        # Apply runtime parameters
        if runtime_params:
            config = self._merge_configs(config, runtime_params)

        return config

    def _merge_configs(
        self, base_config: dict[str, Any], override_config: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Deep merge two configuration dictionaries.

        Args:
            base_config: Base configuration
            override_config: Override configuration

        Returns:
            Merged configuration
        """
        import copy

        merged = copy.deepcopy(base_config)

        for key, value in override_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value

        return merged

    def get_pack_overrides(self, pack_name: str) -> dict[str, Any]:
        """
        Get pack-specific configuration overrides.

        Args:
            pack_name: Name of the prompt pack

        Returns:
            Pack override configuration
        """
        overrides_file = self.presets_dir / "pack_overrides.json"
        if not overrides_file.exists():
            return {}

        try:
            with open(overrides_file, encoding="utf-8") as f:
                all_overrides = json.load(f)

            return all_overrides.get(pack_name, {})
        except Exception as e:
            logger.error(f"Failed to load pack overrides: {e}")
            return {}

    def save_pack_overrides(self, pack_name: str, overrides: dict[str, Any]) -> bool:
        """
        Save pack-specific configuration overrides.

        Args:
            pack_name: Name of the prompt pack
            overrides: Override configuration

        Returns:
            True if saved successfully
        """
        overrides_file = self.presets_dir / "pack_overrides.json"

        try:
            # Load existing overrides
            all_overrides = {}
            if overrides_file.exists():
                with open(overrides_file, encoding="utf-8") as f:
                    all_overrides = json.load(f)

            # Update with new overrides
            all_overrides[pack_name] = overrides

            # Save back
            with open(overrides_file, "w", encoding="utf-8") as f:
                json.dump(all_overrides, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved pack overrides for: {pack_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save pack overrides: {e}")
            return False

    def get_pack_config(self, pack_name: str) -> dict[str, Any]:
        """
        Get individual pack configuration from its .json file.

        Args:
            pack_name: Name of the prompt pack (e.g., "heroes.txt")

        Returns:
            Pack configuration or empty dict if not found
        """
        from pathlib import Path

        # Convert pack_name to config filename (heroes.txt -> heroes.json)
        pack_stem = Path(pack_name).stem
        config_path = Path("packs") / f"{pack_stem}.json"

        if not config_path.exists():
            return {}

        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            logger.debug(f"Loaded pack config: {pack_name}")
            return config
        except Exception as e:
            logger.error(f"Failed to load pack config '{pack_name}': {e}")
            return {}

    def save_pack_config(self, pack_name: str, config: dict[str, Any]) -> bool:
        """
        Save individual pack configuration to its .json file.

        Args:
            pack_name: Name of the prompt pack (e.g., "heroes.txt")
            config: Configuration to save

        Returns:
            True if successful
        """
        from pathlib import Path

        try:
            # Convert pack_name to config filename (heroes.txt -> heroes.json)
            pack_stem = Path(pack_name).stem
            config_path = Path("packs") / f"{pack_stem}.json"

            # Ensure packs directory exists
            config_path.parent.mkdir(exist_ok=True)

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved pack config: {pack_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save pack config '{pack_name}': {e}")
            return False

    def ensure_pack_config(self, pack_name: str, preset_name: str = "default") -> dict[str, Any]:
        """
        Ensure pack has a configuration file, creating one with preset defaults if needed.

        Args:
            pack_name: Name of the prompt pack
            preset_name: Preset to use as base for new pack config

        Returns:
            Pack configuration
        """
        config = self._merge_config_with_defaults(self.get_pack_config(pack_name))

        if not config:
            # Create pack config from preset defaults
            preset_config = self.load_preset(preset_name)
            if preset_config:
                self.save_pack_config(pack_name, preset_config)
                logger.info(
                    f"Created pack config for '{pack_name}' based on preset '{preset_name}'"
                )
                return self._merge_config_with_defaults(preset_config)
            else:
                logger.warning(f"Failed to create pack config - preset '{preset_name}' not found")

        return self._merge_config_with_defaults(config)

    def get_global_negative_prompt(self) -> str:
        """Return the persisted global negative prompt, creating a default if missing."""

        if self._global_negative_cache is not None:
            return self._global_negative_cache

        prompt = DEFAULT_GLOBAL_NEGATIVE_PROMPT
        try:
            if self._global_negative_path.exists():
                text = self._global_negative_path.read_text(encoding="utf-8").strip()
                if text:
                    prompt = text
            else:
                self._global_negative_path.parent.mkdir(parents=True, exist_ok=True)
                self._global_negative_path.write_text(prompt, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - log and fall back to default
            logger.warning("Failed reading global negative prompt: %s", exc)
        self._global_negative_cache = prompt
        return prompt

    def save_global_negative_prompt(self, prompt: str) -> bool:
        """Persist a custom global negative prompt to disk."""

        text = (prompt or "").strip()
        try:
            self._global_negative_path.parent.mkdir(parents=True, exist_ok=True)
            self._global_negative_path.write_text(text, encoding="utf-8")
            self._global_negative_cache = text
            logger.info("Saved global negative prompt (%s chars)", len(text))
            return True
        except Exception as exc:  # noqa: BLE001 - surface failure but keep running
            logger.error("Failed to save global negative prompt: %s", exc)
            return False

    def add_global_negative(self, negative_prompt: str) -> str:
        """
        Add global safety terms to the provided negative prompt.

        Args:
            negative_prompt: Existing negative prompt

        Returns:
            Combined negative prompt string
        """

        global_neg = self.get_global_negative_prompt().strip()
        base = (negative_prompt or "").strip()
        if not global_neg:
            return base
        if base:
            return f"{base}, {global_neg}"
        return global_neg

    def _merge_config_with_defaults(self, config: dict[str, Any] | None) -> dict[str, Any]:
        base = self.get_default_config()
        return self._deep_merge_dicts(base, config or {})

    def _deep_merge_dicts(self, base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in (overrides or {}).items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_dicts(merged.get(key, {}), value)
            else:
                merged[key] = value
        return merged

    def set_default_preset(self, preset_name: str) -> bool:
        """
        Set a preset as the default to load on startup.

        Args:
            preset_name: Name of the preset to set as default

        Returns:
            True if set successfully
        """
        if not preset_name:
            logger.warning("Cannot set empty preset name as default")
            return False

        # Verify preset exists
        preset_path = self.presets_dir / f"{preset_name}.json"
        if not preset_path.exists():
            logger.warning(f"Preset '{preset_name}' does not exist, cannot set as default")
            return False

        try:
            self._default_preset_path.write_text(preset_name, encoding="utf-8")
            logger.info(f"Set default preset to: {preset_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to set default preset: {e}")
            return False

    def get_default_preset(self) -> str | None:
        """
        Get the name of the default preset.

        Returns:
            Name of default preset, or None if not set
        """
        if not self._default_preset_path.exists():
            return None

        try:
            preset_name = self._default_preset_path.read_text(encoding="utf-8").strip()
            if preset_name:
                # Verify preset still exists
                preset_path = self.presets_dir / f"{preset_name}.json"
                if preset_path.exists():
                    return preset_name
                else:
                    logger.warning(f"Default preset '{preset_name}' no longer exists")
                    # Clean up stale reference
                    self._default_preset_path.unlink(missing_ok=True)
                    return None
            return None
        except Exception as e:
            logger.error(f"Failed to read default preset: {e}")
            return None

    def clear_default_preset(self) -> bool:
        """
        Clear the default preset setting.

        Returns:
            True if cleared successfully
        """
        try:
            self._default_preset_path.unlink(missing_ok=True)
            logger.info("Cleared default preset")
            return True
        except Exception as e:
            logger.error(f"Failed to clear default preset: {e}")
            return False

```

## `src/utils/file_io.py`

```
"""File I/O utilities with UTF-8 support"""

import base64
import logging
from io import BytesIO
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


def save_image_from_base64(base64_str: str, output_path: Path) -> bool:
    """
    Save base64 encoded image to file.

    Args:
        base64_str: Base64 encoded image string
        output_path: Path to save the image

    Returns:
        True if saved successfully
    """
    try:
        # Remove data URL prefix if present
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]

        image_data = base64.b64decode(base64_str)
        image = Image.open(BytesIO(image_data))

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        image.save(output_path)
        logger.info(f"Saved image: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return False


def load_image_to_base64(image_path: Path) -> str | None:
    """
    Load image and convert to base64.

    Args:
        image_path: Path to the image

    Returns:
        Base64 encoded image string
    """
    try:
        with Image.open(image_path) as img:
            buffered = BytesIO()
            img.save(buffered, format=img.format or "PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        logger.info(f"Loaded image to base64: {image_path.name}")
        return img_str
    except Exception as e:
        logger.error(f"Failed to load image: {e}")
        return None


def read_text_file(file_path: Path) -> str | None:
    """
    Read text file with UTF-8 encoding.

    Args:
        file_path: Path to the text file

    Returns:
        File contents as string
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        logger.info(f"Read text file: {file_path.name}")
        return content
    except Exception as e:
        logger.error(f"Failed to read text file: {e}")
        return None


def write_text_file(file_path: Path, content: str) -> bool:
    """
    Write text file with UTF-8 encoding.

    Args:
        file_path: Path to save the file
        content: Content to write

    Returns:
        True if saved successfully
    """
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Wrote text file: {file_path.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to write text file: {e}")
        return False


def read_prompt_pack(pack_path: Path) -> list:
    """
    Read prompt pack from .txt or .tsv file with UTF-8 safety.

    Supports:
    - Line-based .txt files with blank line separators
    - Tab-separated .tsv files
    - 'neg:' prefix for negative prompts
    - Comments starting with #

    Args:
        pack_path: Path to the prompt pack file

    Returns:
        List of prompt dictionaries with 'positive' and 'negative' keys
    """
    try:
        if not pack_path.exists():
            logger.error(f"Prompt pack not found: {pack_path}")
            return []

        # Read file with UTF-8 encoding
        with open(pack_path, encoding="utf-8") as f:
            content = f.read()

        prompts = []

        if pack_path.suffix.lower() == ".tsv":
            # Tab-separated format
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = line.split("\t", 1)
                positive = parts[0].strip()
                negative = parts[1].strip() if len(parts) > 1 else ""

                prompts.append({"positive": positive, "negative": negative})
        else:
            # Block-based .txt format
            blocks = content.split("\n\n")

            for block in blocks:
                if not block.strip():
                    continue

                lines = [line.strip() for line in block.strip().splitlines()]
                lines = [line for line in lines if line and not line.startswith("#")]

                if not lines:
                    continue

                positive_parts = []
                negative_parts = []

                for line in lines:
                    if line.startswith("neg:"):
                        negative_parts.append(line[4:].strip())
                    else:
                        positive_parts.append(line)

                positive = " ".join(positive_parts)
                negative = " ".join(negative_parts)

                prompts.append({"positive": positive, "negative": negative})

        logger.info(f"Read {len(prompts)} prompts from {pack_path.name}")
        return prompts

    except Exception as e:
        logger.error(f"Failed to read prompt pack {pack_path.name}: {e}")
        return []


def get_prompt_packs(packs_dir: Path) -> list:
    """
    Get list of available prompt pack files.

    Args:
        packs_dir: Directory containing prompt packs

    Returns:
        List of prompt pack file paths
    """
    try:
        if not packs_dir.exists():
            packs_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created packs directory: {packs_dir}")
            return []

        pack_files = []
        for ext in ["*.txt", "*.tsv"]:
            pack_files.extend(packs_dir.glob(ext))

        pack_files.sort()
        logger.info(f"Found {len(pack_files)} prompt packs in {packs_dir}")
        return pack_files

    except Exception as e:
        logger.error(f"Failed to scan prompt packs directory: {e}")
        return []


def get_safe_filename(name: str) -> str:
    """
    Convert string to safe filename by removing/replacing invalid characters.

    Args:
        name: Input string

    Returns:
        Safe filename string
    """
    # Replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    safe_name = name

    for char in invalid_chars:
        safe_name = safe_name.replace(char, "_")

    # Remove leading/trailing whitespace and dots
    safe_name = safe_name.strip(" .")

    # Limit length
    if len(safe_name) > 200:
        safe_name = safe_name[:200]

    return safe_name or "unnamed"

```

## `src/utils/logger.py`

```
"""Logging utilities with structured JSON output"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


class StructuredLogger:
    """Logger that creates JSON manifests and CSV summaries"""

    def __init__(self, output_dir: str = "output"):
        """
        Initialize structured logger.

        Args:
            output_dir: Base output directory
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Setup Python logging
        self.logger = logging.getLogger("StableNew")

    def create_run_directory(self, run_name: str | None = None) -> Path:
        """
        Create a new run directory with improved architecture:
        single_date_time_folder/pack_name/combined_steps_folder/numbered_images.png

        Args:
            run_name: Optional name for the run

        Returns:
            Path to the run directory
        """
        if run_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_name = f"run_{timestamp}"

        run_dir = self.output_dir / run_name
        run_dir.mkdir(exist_ok=True, parents=True)

        # NOTE: Pack-specific subdirectories will be created as needed
        # Structure: run_dir / pack_name / steps_folder / images
        # No longer pre-creating generic subdirectories

        self.logger.info(f"Created run directory: {run_dir}")
        return run_dir

    def create_pack_directory(self, run_dir: Path, pack_name: str) -> Path:
        """
        Create directory structure for a specific pack with traditional pipeline folders.

        Args:
            run_dir: Main run directory
            pack_name: Name of the prompt pack (without .txt extension)

        Returns:
            Path to the pack directory
        """
        # Remove .txt extension if present and add _pack suffix
        clean_pack_name = pack_name.replace(".txt", "")
        if not clean_pack_name.endswith("_pack"):
            clean_pack_name += "_pack"

        pack_dir = run_dir / clean_pack_name
        pack_dir.mkdir(exist_ok=True, parents=True)

        # Create traditional pipeline subdirectories within pack
        (pack_dir / "txt2img").mkdir(exist_ok=True)
        (pack_dir / "img2img").mkdir(exist_ok=True)
        (pack_dir / "adetailer").mkdir(exist_ok=True)
        (pack_dir / "upscaled").mkdir(exist_ok=True)
        (pack_dir / "video").mkdir(exist_ok=True)
        (pack_dir / "manifests").mkdir(exist_ok=True)

        self.logger.info(f"Created pack directory with pipeline folders: {pack_dir}")
        return pack_dir

    def save_manifest(self, run_dir: Path, image_name: str, metadata: dict[str, Any]) -> bool:
        """
        Save JSON manifest for an image.

        Args:
            run_dir: Run directory
            image_name: Name of the image
            metadata: Metadata to save

        Returns:
            True if saved successfully
        """
        manifest_dir = run_dir / "manifests"
        manifest_dir.mkdir(exist_ok=True, parents=True)  # Ensure manifests directory exists

        manifest_path = manifest_dir / f"{image_name}.json"
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved manifest: {manifest_path.name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save manifest: {e}")
            return False

    def save_pack_manifest(self, pack_dir: Path, image_name: str, metadata: dict[str, Any]) -> bool:
        """Save a per-image JSON manifest inside a pack directory.

        Args:
            pack_dir: The pack directory (contains txt2img/img2img/etc.)
            image_name: Base name of the image (without extension)
            metadata: Metadata dictionary to persist

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            manifest_dir = pack_dir / "manifests"
            manifest_dir.mkdir(exist_ok=True, parents=True)
            manifest_path = manifest_dir / f"{image_name}.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved pack manifest: {manifest_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save pack manifest: {e}")
            return False

    def create_csv_summary(self, run_dir: Path, images_data: list) -> bool:
        """
        Create CSV rollup summary of all images.

        Args:
            run_dir: Run directory
            images_data: List of image metadata dictionaries

        Returns:
            True if created successfully
        """
        if not images_data:
            self.logger.warning("No image data to summarize")
            return False

        try:
            summary_file = run_dir / "summary.csv"

            # Define CSV headers
            headers = [
                "image_name",
                "stage",
                "timestamp",
                "prompt",
                "negative_prompt",
                "steps",
                "sampler",
                "cfg_scale",
                "width",
                "height",
                "seed",
                "model",
                "file_path",
                "file_size",
            ]

            with open(summary_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()

                for img_data in images_data:
                    # Extract config data safely
                    config = img_data.get("config", {})

                    # Get file size if file exists
                    file_size = ""
                    if "path" in img_data:
                        try:
                            file_path = Path(img_data["path"])
                            if file_path.exists():
                                file_size = file_path.stat().st_size
                        except:
                            pass

                    row = {
                        "image_name": img_data.get("name", ""),
                        "stage": img_data.get("stage", ""),
                        "timestamp": img_data.get("timestamp", ""),
                        "prompt": img_data.get("prompt", ""),
                        "negative_prompt": config.get("negative_prompt", ""),
                        "steps": config.get("steps", ""),
                        "sampler": config.get("sampler_name", ""),
                        "cfg_scale": config.get("cfg_scale", ""),
                        "width": config.get("width", ""),
                        "height": config.get("height", ""),
                        "seed": config.get("seed", ""),
                        "model": img_data.get("model", ""),
                        "file_path": img_data.get("path", ""),
                        "file_size": file_size,
                    }
                    writer.writerow(row)

            self.logger.info(f"Created CSV summary: {summary_file}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create CSV summary: {e}")
            return False

    def create_pack_csv_summary(
        self, summary_path: Path, summary_data: list[dict[str, Any]]
    ) -> bool:
        """
        Create CSV summary for a specific pack.

        Args:
            summary_path: Path where to save the CSV
            summary_data: List of summary entries

        Returns:
            True if created successfully
        """
        try:
            with open(summary_path, "w", newline="", encoding="utf-8") as csvfile:
                if not summary_data:
                    return False

                fieldnames = summary_data[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(summary_data)

            self.logger.info(f"Created pack CSV summary: {summary_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create pack CSV summary: {e}")
            return False
            return True

        except Exception as e:
            self.logger.error(f"Failed to create CSV summary: {e}")
            return False

    def create_rollup_manifest(self, run_dir: Path) -> bool:
        """
        Create rollup manifest from all individual JSON manifests.

        Args:
            run_dir: Run directory

        Returns:
            True if created successfully
        """
        try:
            manifests_dir = run_dir / "manifests"
            if not manifests_dir.exists():
                self.logger.warning("No manifests directory found")
                return True

            # Collect all manifest files
            manifest_files = list(manifests_dir.glob("*.json"))
            if not manifest_files:
                self.logger.warning("No manifest files found")
                return True

            # Read all manifests
            all_images = []
            for manifest_file in manifest_files:
                try:
                    with open(manifest_file, encoding="utf-8") as f:
                        manifest_data = json.load(f)
                        all_images.append(manifest_data)
                except Exception as e:
                    self.logger.error(f"Failed to read manifest {manifest_file.name}: {e}")

            if not all_images:
                self.logger.warning("No valid manifest data found")
                return True

            # Create rollup manifest
            rollup_data = {
                "run_info": {
                    "run_directory": str(run_dir),
                    "timestamp": datetime.now().isoformat(),
                    "total_images": len(all_images),
                },
                "images": all_images,
            }

            rollup_file = run_dir / "rollup_manifest.json"
            with open(rollup_file, "w", encoding="utf-8") as f:
                json.dump(rollup_data, f, indent=2, ensure_ascii=False)

            # Create CSV summary
            self.create_csv_summary(run_dir, all_images)

            self.logger.info(f"Created rollup manifest with {len(all_images)} images")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create rollup manifest: {e}")
            return False

    def record_run_status(self, run_dir: Path, status: str, reason: str | None = None) -> bool:
        """
        Persist the final status of a pipeline run (e.g., success, cancelled).

        Args:
            run_dir: Run directory for the pipeline.
            status: Status string such as "success", "cancelled", or "error".
            reason: Optional human-readable reason to record.
        """
        try:
            run_dir = Path(run_dir)
            run_dir.mkdir(exist_ok=True, parents=True)
            payload: dict[str, Any] = {
                "status": status,
                "timestamp": datetime.now().isoformat(),
            }
            if reason:
                payload["reason"] = reason
            status_path = run_dir / "run_status.json"
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Recorded run status '{status}' at {status_path}")
            return True
        except Exception as exc:  # noqa: BLE001 - log and continue
            self.logger.error(f"Failed to record run status: {exc}")
            return False


def setup_logging(log_level: str = "INFO", log_file: str | None = None):
    """
    Setup logging configuration.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file path
    """
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, log_level.upper()), format=log_format, handlers=handlers
    )

```

## `src/utils/preferences.py`

```
"""Persistence helpers for GUI preferences and last-used settings."""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PreferencesManager:
    """Read and write last-used GUI preferences as JSON."""

    _DEFAULT_PIPELINE_CONTROLS: dict[str, Any] = {
        "txt2img_enabled": True,
        "img2img_enabled": True,
        "adetailer_enabled": False,
        "upscale_enabled": True,
        "video_enabled": False,
        "loop_type": "single",
        "loop_count": 1,
        "pack_mode": "selected",
        "images_per_prompt": 1,
        "model_matrix": [],
        "hypernetworks": [],
        "variant_mode": "fanout",
    }

    def __init__(self, path: str | Path | None = None):
        """Initialise manager with optional custom storage path."""

        if path is None:
            path = Path("presets") / "last_settings.json"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def default_pipeline_controls(self) -> dict[str, Any]:
        """Return a copy of the default pipeline controls payload."""

        return copy.deepcopy(self._DEFAULT_PIPELINE_CONTROLS)

    def default_preferences(self, default_config: dict[str, Any]) -> dict[str, Any]:
        """Return default preferences merged with provided default config."""

        return {
            "preset": "default",
            "selected_packs": [],
            "override_pack": False,
            "pipeline_controls": self.default_pipeline_controls(),
            "config": copy.deepcopy(default_config),
        }

    def load_preferences(self, default_config: dict[str, Any]) -> dict[str, Any]:
        """Load preferences from disk, merging with defaults for missing keys."""

        preferences = self.default_preferences(default_config)

        if not self.path.exists():
            return preferences

        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as err:  # pragma: no cover - defensive logging path
            logger.warning(
                "Failed to load preferences from %s: %s. Using defaults.", self.path, err
            )
            return preferences

        preferences["preset"] = data.get("preset", preferences["preset"])
        preferences["selected_packs"] = data.get("selected_packs", preferences["selected_packs"])
        preferences["override_pack"] = bool(data.get("override_pack", preferences["override_pack"]))

        pipeline_overrides = data.get("pipeline_controls", {})
        preferences["pipeline_controls"] = self._merge_dicts(
            preferences["pipeline_controls"], pipeline_overrides
        )

        config_overrides = data.get("config", {})
        preferences["config"] = self._merge_dicts(preferences["config"], config_overrides)

        return preferences

    def save_preferences(self, preferences: dict[str, Any]) -> bool:
        """Persist preferences to disk. Returns True when successful."""

        try:
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(preferences, handle, indent=2, ensure_ascii=False)
            logger.info("Saved preferences to %s", self.path)
            return True
        except Exception as err:  # pragma: no cover - defensive logging path
            logger.error("Failed to save preferences to %s: %s", self.path, err)
            return False

    def backup_corrupt_preferences(self) -> None:
        """Move a corrupt preferences file out of the way (or delete if rename fails)."""

        if not self.path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{self.path.stem}_corrupt_{timestamp}{self.path.suffix}"
        backup_path = self.path.with_name(backup_name)

        try:
            self.path.rename(backup_path)
            logger.warning("Backed up corrupt preferences to %s", backup_path)
            return
        except Exception as exc:
            logger.error("Failed to move corrupt preferences to %s: %s", backup_path, exc)

        try:
            self.path.unlink()
            logger.warning("Deleted corrupt preferences file at %s", self.path)
        except Exception:
            logger.exception("Failed to delete corrupt preferences file at %s", self.path)

    def _merge_dicts(self, base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dictionaries without mutating the inputs."""

        result = copy.deepcopy(base)
        for key, value in overrides.items():
            if isinstance(result.get(key), dict) and isinstance(value, dict):
                result[key] = self._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result

```

## `src/utils/prompt_pack.py`

```
# Minimal stub for src.utils.prompt_pack to resolve import error


def get_prompt_packs(*args, **kwargs):
    return []


def read_prompt_pack(*args, **kwargs):
    return {}

```

## `src/utils/randomizer.py`

```
"""Prompt randomization utilities for txt2img pipeline."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any

from src.pipeline.variant_planner import (
    VariantPlan,
    VariantSpec,
    apply_variant_to_config,
    build_variant_plan,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_VARIANTS = 512
HARD_MAX_VARIANTS = 8192

@dataclass
class PromptVariant:
    """Represents one randomized prompt."""

    text: str
    label: str | None = None


class PromptRandomizer:
    """Applies Prompt S/R, wildcard, and matrix rules prior to pipeline runs."""

    def __init__(
        self,
        config: dict[str, Any] | None,
        rng: random.Random | None = None,
        max_variants: int | None = None,
    ) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled"))
        # Optional deterministic seed for reproducible runs.
        seed = cfg.get("seed", None)
        seed_value: int | None
        try:
            seed_value = int(seed) if seed is not None else None
        except (TypeError, ValueError):
            seed_value = None

        # If an external RNG is provided, it wins. Otherwise we construct one,
        # optionally using the configured seed. random.Random(None) uses
        # system randomness, so leaving seed_value as None preserves old behavior.
        if rng is not None:
            self._rng = rng
        else:
            self._rng = random.Random(seed_value)
        self._max_variants = self._resolve_max_variants(cfg, max_variants)

        # Prompt S/R
        self._sr_config = cfg.get("prompt_sr", {}) or {}
        self._sr_rules = []
        if self._sr_config.get("enabled"):
            self._sr_rules = [
                rule
                for rule in (self._sr_config.get("rules") or [])
                if rule.get("search") and rule.get("replacements")
            ]
        self._sr_mode = (self._sr_config.get("mode") or "random").lower()
        self._sr_indices = [0] * len(self._sr_rules)

        # Wildcards
        self._wildcard_config = cfg.get("wildcards", {}) or {}
        self._wildcard_tokens = []
        if self._wildcard_config.get("enabled"):
            raw_tokens = self._wildcard_config.get("tokens") or []
            self._wildcard_tokens = [
                token for token in raw_tokens if token.get("token") and token.get("values")
            ]
        self._wildcard_mode = (self._wildcard_config.get("mode") or "random").lower()
        self._wildcard_indices = {token["token"]: 0 for token in self._wildcard_tokens}

        # Matrix
        self._matrix_config = cfg.get("matrix", {}) or {}
        self._matrix_enabled = bool(self._matrix_config.get("enabled"))
        self._matrix_base_prompt = self._matrix_config.get("base_prompt", "")
        self._matrix_prompt_mode = (self._matrix_config.get("prompt_mode") or "replace").lower()
        self._matrix_slots = []
        if self._matrix_enabled:
            self._matrix_slots = [
                slot
                for slot in (self._matrix_config.get("slots") or [])
                if slot.get("name") and slot.get("values")
            ]

        raw_mode = (self._matrix_config.get("mode") or "fanout").lower()
        if raw_mode in {"fanout", "grid", "all"}:
            self._matrix_mode = "fanout"
        elif raw_mode in {"rotate", "random", "per_prompt"}:
            self._matrix_mode = "random"
        elif raw_mode in {"sequential", "round_robin"}:
            self._matrix_mode = "sequential"
        else:
            logger.warning(
                "Randomizer: unknown matrix mode '%s'; defaulting to sequential", raw_mode
            )
            self._matrix_mode = "sequential"

        self._matrix_limit = int(self._matrix_config.get("limit") or 0)
        self._matrix_total_possible = self._estimate_matrix_combo_total()
        self._matrix_effective_limit = self._resolve_matrix_limit()
        self._matrix_combos = self._build_matrix_combos()
        self._matrix_requested = (
            min(self._matrix_total_possible, self._matrix_limit)
            if self._matrix_limit > 0
            else self._matrix_total_possible
        )
        self._matrix_index = 0

        estimated = self.estimated_matrix_combos()
        if estimated:
            slot_names = [slot.get("name") for slot in self._matrix_slots if slot.get("name")]
            logger.info(
                "Randomizer matrix: mode=%s slots=%s limit=%s combos=%s",
                self._matrix_mode,
                ", ".join(slot_names),
                self._matrix_limit,
                estimated,
            )
            if self._matrix_limit == 0 and estimated > 1024:
                logger.warning(
                    "Randomizer: matrix limit is 0 (unlimited) and %s combos were built; "
                    "runs may be slow or memory-heavy.",
                    estimated,
                )

    def generate(self, prompt_text: str) -> list[PromptVariant]:
        """Return one or more prompt variants for the supplied text.

        Matrix prompt_mode behavior:
        - "replace": base_prompt replaces pack prompt (default for backward compatibility)
        - "append": base_prompt is appended to pack prompt with ", " separator
        - "prepend": base_prompt is prepended to pack prompt with ", " separator
        """

        if not self.enabled:
            return [PromptVariant(prompt_text, None)]

        # Determine working prompt based on matrix prompt_mode
        working_prompt = prompt_text
        if self._matrix_enabled and self._matrix_base_prompt:
            base_prompt = self._matrix_base_prompt
            if self._matrix_prompt_mode == "append":
                base_norm = base_prompt.strip().lower()
                prompt_norm = prompt_text.strip().lower()
                if base_norm and prompt_norm.endswith(base_norm):
                    working_prompt = prompt_text
                else:
                    working_prompt = f"{prompt_text}, {base_prompt}"
            elif self._matrix_prompt_mode == "prepend":
                base_norm = base_prompt.strip().lower()
                prompt_norm = prompt_text.strip().lower()
                if base_norm and prompt_norm.startswith(base_norm):
                    working_prompt = prompt_text
                else:
                    working_prompt = f"{base_prompt}, {prompt_text}"
            else:
                working_prompt = base_prompt

        matrix_combos = self._matrix_combos_for_prompt()
        sr_variants = self._expand_prompt_sr(working_prompt)
        matrix_requested = self._matrix_requested if self._matrix_enabled else 1

        variants: list[PromptVariant] = []
        truncated = False
        for sr_text, sr_labels in sr_variants:
            wildcard_variants = self._expand_wildcards(sr_text, list(sr_labels))
            for wildcard_text, wildcard_labels in wildcard_variants:
                for combo in matrix_combos:
                    labels = list(wildcard_labels)
                    final_text = self._apply_matrix(wildcard_text, combo, labels)
                    label_value = "; ".join(labels) or None
                    variants.append(PromptVariant(text=final_text, label=label_value))
                    if len(variants) >= self._max_variants:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break

        # Deduplicate while preserving order
        deduped: list[PromptVariant] = []
        seen: set[tuple[str, str | None]] = set()
        for variant in variants or [PromptVariant(prompt_text, None)]:
            key = (variant.text, variant.label)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(variant)

        if truncated:
            estimated = self._estimate_variant_upper_bound(
                working_prompt, matrix_requested or 1
            )
            logger.warning(
                "Randomization requested approximately %s combinations but cap is %s; "
                "returning first %s variant(s). Reduce randomization scope or set "
                "`randomization.max_variants` to raise the cap.",
                estimated,
                self._max_variants,
                self._max_variants,
            )

        return deduped or [PromptVariant(prompt_text, None)]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _ordered_sr_choices(self, rule_index: int, replacements: list[str]) -> list[str]:
        """Legacy helper for fanout S/R mode."""
        if self._sr_mode == "round_robin":
            start = self._sr_indices[rule_index]
            rotated = replacements[start:] + replacements[:start]
            return rotated or replacements
        return list(replacements)

    def _expand_prompt_sr(self, text: str) -> list[tuple[str, list[str]]]:
        """Apply prompt S/R rules.

        New semantics:
        - mode == "random":        one random replacement per rule (per prompt)
        - mode == "round_robin":   one sequential replacement per rule (per prompt)
        - other modes (e.g. "fanout"): legacy fanout behavior

        In 'random' and 'round_robin', we always return a single variant so
        only the matrix controls the number of prompt variants.
        """
        if not self._sr_rules:
            return [(text, [])]

        # Single-path behavior: one replacement per rule for this prompt
        if self._sr_mode in {"random", "round_robin"}:
            current_text = text
            labels: list[str] = []

            for idx, rule in enumerate(self._sr_rules):
                search = rule.get("search", "")
                replacements = rule.get("replacements") or []
                if not search or not replacements or search not in current_text:
                    continue

                if self._sr_mode == "random":
                    replacement = self._rng.choice(replacements)
                else:  # "round_robin"
                    index = self._sr_indices[idx] % len(replacements)
                    replacement = replacements[index]
                    self._sr_indices[idx] = (index + 1) % len(replacements)

                current_text = current_text.replace(search, replacement)
                labels.append(f"{search}->{replacement}")

            return [(current_text, labels)]

        # Fallback: legacy fanout over all replacements (if someone explicitly asks for it)
        variants: list[tuple[str, list[str]]] = [(text, [])]
        for idx, rule in enumerate(self._sr_rules):
            search = rule.get("search", "")
            replacements = rule.get("replacements") or []
            if not search or not replacements:
                continue

            choices = self._ordered_sr_choices(idx, replacements)
            applied = False
            new_variants: list[tuple[str, list[str]]] = []
            for current_text, current_labels in variants:
                if search not in current_text:
                    new_variants.append((current_text, current_labels))
                    continue
                applied = True
                for replacement in choices:
                    replaced_text = current_text.replace(search, replacement)
                    new_labels = current_labels + [f"{search}->{replacement}"]
                    new_variants.append((replaced_text, new_labels))
            variants = new_variants or variants
            if applied and self._sr_mode == "round_robin" and replacements:
                start = self._sr_indices[idx]
                self._sr_indices[idx] = (start + 1) % len(replacements)
        return variants

    def _ordered_wildcard_values(self, token_name: str, values: list[str]) -> list[str]:
        """Legacy helper for fanout wildcard mode."""
        if self._wildcard_mode == "sequential":
            start = self._wildcard_indices.get(token_name, 0)
            return values[start:] + values[:start]
        return list(values)

    def _expand_wildcards(self, text: str, base_labels: list[str]) -> list[tuple[str, list[str]]]:
        """Apply wildcard expansion.

        New semantics:
        - mode == "random":      one random value per token per prompt
        - mode == "sequential":  one sequential value per token per prompt
        - other modes: legacy fanout over all values

        In 'random' and 'sequential', we always return a single variant so
        only the matrix controls the number of prompt variants.
        """
        if not self._wildcard_tokens:
            return [(text, base_labels)]

        # Single-path behavior for random / sequential
        if self._wildcard_mode in {"random", "sequential"}:
            current_text = text
            labels = list(base_labels)

            for token in self._wildcard_tokens:
                token_name = token.get("token")
                values = token.get("values") or []
                if not token_name or not values or token_name not in current_text:
                    continue

                if self._wildcard_mode == "random":
                    value = self._rng.choice(values)
                else:  # "sequential"
                    idx = self._wildcard_indices.get(token_name, 0) % len(values)
                    value = values[idx]
                    self._wildcard_indices[token_name] = (idx + 1) % len(values)

                current_text = current_text.replace(token_name, value)
                labels.append(f"{token_name}={value}")

            return [(current_text, labels)]

        # Fallback: legacy fanout behavior
        variants: list[tuple[str, list[str]]] = [(text, base_labels)]
        for token in self._wildcard_tokens:
            token_name = token.get("token")
            values = token.get("values") or []
            if not token_name or not values:
                continue

            choices = self._ordered_wildcard_values(token_name, values)
            applied = False
            new_variants: list[tuple[str, list[str]]] = []
            for current_text, current_labels in variants:
                if token_name not in current_text:
                    new_variants.append((current_text, current_labels))
                    continue
                applied = True
                for value in choices:
                    replaced_text = current_text.replace(token_name, value)
                    new_labels = current_labels + [f"{token_name}={value}"]
                    new_variants.append((replaced_text, new_labels))
            variants = new_variants or variants
            if applied and self._wildcard_mode == "sequential" and values:
                start = self._wildcard_indices.get(token_name, 0)
                self._wildcard_indices[token_name] = (start + 1) % len(values)
        return variants

    def _apply_matrix(
        self,
        text: str,
        combo: dict[str, str] | None,
        label_parts: list[str],
    ) -> str:
        if not combo:
            return text

        for slot_name, slot_value in combo.items():
            token = f"[[{slot_name}]]"
            if token in text:
                text = text.replace(token, slot_value)
                label_parts.append(f"[{slot_name}]={slot_value}")

        return text

    def _matrix_combos_for_prompt(self) -> list[dict[str, str] | None]:
        """
        Return the matrix combinations to apply for the current prompt.

        - Disabled/no slots -> [None]
        - mode == "fanout": return every combination for this prompt (grid behavior)
        - mode == "random": return one random combo per prompt
        - other modes: return exactly one combo, rotating across prompts ("sequential")
        """
        if not self._matrix_enabled or not self._matrix_slots or not self._matrix_combos:
            return [None]

        # fanout: expand to every matrix combo for this prompt
        if self._matrix_mode == "fanout":
            return self._matrix_combos

        # random: pick a single random combo for this prompt
        if self._matrix_mode == "random":
            # Defensive: if combos exist, choose one; otherwise fall back to [None]
            if self._matrix_combos:
                combo = self._rng.choice(self._matrix_combos)
                return [combo]
            return [None]

        # default / "rotate": one combo at a time in a stable order
        combo = self._matrix_combos[self._matrix_index]
        self._matrix_index = (self._matrix_index + 1) % len(self._matrix_combos)
        return [combo]

    def _build_matrix_combos(self) -> list[dict[str, str] | None]:
        if not self._matrix_slots:
            return [None]

        combos: list[dict[str, str]] = []
        limit = max(0, self._matrix_effective_limit)

        def backtrack(idx: int, current: dict[str, str]) -> None:
            if limit > 0 and len(combos) >= limit:
                return
            if idx == len(self._matrix_slots):
                combos.append(current.copy())
                return

            slot = self._matrix_slots[idx]
            values = slot.get("values") or []
            for value in values:
                current[slot["name"]] = value
                backtrack(idx + 1, current)
                if limit > 0 and len(combos) >= limit:
                    break

        backtrack(0, {})
        return combos or [None]

    def _resolve_max_variants(
        self, cfg: dict[str, Any], override: int | None = None
    ) -> int:
        candidate = override if override is not None else cfg.get("max_variants")
        try:
            candidate_int = int(candidate)
        except (TypeError, ValueError):
            candidate_int = None

        if candidate_int is None or candidate_int <= 0:
            return DEFAULT_MAX_VARIANTS

        if candidate_int > HARD_MAX_VARIANTS:
            logger.warning(
                "randomization.max_variants=%s exceeds hard safety cap (%s); using %s",
                candidate_int,
                HARD_MAX_VARIANTS,
                HARD_MAX_VARIANTS,
            )
            return HARD_MAX_VARIANTS
        return candidate_int

    def _estimate_matrix_combo_total(self) -> int:
        if not self._matrix_slots:
            return 1
        total = 1
        for slot in self._matrix_slots:
            values = slot.get("values") or []
            total *= max(1, len(values))
        return total

    def _resolve_matrix_limit(self) -> int:
        if not self._matrix_enabled or not self._matrix_slots:
            return 0

        user_limit = max(0, self._matrix_limit)
        if self._matrix_mode != "fanout":
            return user_limit

        if user_limit > 0:
            if user_limit > self._max_variants:
                logger.warning(
                    "Matrix limit %s exceeds randomization max_variants %s; capping to %s",
                    user_limit,
                    self._max_variants,
                    self._max_variants,
                )
            return min(user_limit, self._max_variants)

        if self._matrix_total_possible > self._max_variants:
            logger.warning(
                "Matrix fanout would expand to %s combinations; auto-limiting to %s. "
                "Set matrix.limit or randomization.max_variants to override.",
                self._matrix_total_possible,
                self._max_variants,
            )
            return self._max_variants
        return 0

    def _estimate_variant_upper_bound(self, prompt: str, matrix_count: int) -> int:
        sr_total = 1
        for rule in self._sr_rules:
            search = rule.get("search")
            replacements = rule.get("replacements") or []
            if search and search in prompt and replacements:
                sr_total *= len(replacements)

        wildcard_total = 1
        for token in self._wildcard_tokens:
            token_name = token.get("token")
            values = token.get("values") or []
            if token_name and token_name in prompt and values:
                wildcard_total *= len(values)

        matrix_total = max(1, matrix_count)
        return max(1, sr_total) * max(1, wildcard_total) * matrix_total

    def estimated_matrix_combos(self) -> int:
        """Return how many matrix combinations were pre-computed."""
        if not self._matrix_enabled or not self._matrix_slots:
            return 0
        if not self._matrix_combos:
            return 0
        if len(self._matrix_combos) == 1 and self._matrix_combos[0] is None:
            return 0
        return len(self._matrix_combos)


# --- Minimal stubs for missing functions ---

```

## `src/utils/state.py`

```
class CancellationError(Exception):
    """Raised when a cooperative cancellation is requested in the pipeline or GUI."""

    pass

```

## `src/utils/webui_discovery.py`

```
# --- Compatibility shim class for GUI code expecting a service object ---


# --- Compatibility shim class for GUI code expecting a service object ---

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

# --- Compatibility shim class for GUI code expecting a service object ---


class WebUIDiscovery:
    def __init__(
        self, base_url: str = "http://127.0.0.1", start_port: int = 7860, max_attempts: int = 5
    ):
        self.base_url = base_url
        self.start_port = start_port
        self.max_attempts = max_attempts

    def discover(self, timeout: tuple[float, float] | None = (1.5, 6.0)) -> dict:
        """
        Try to locate the WebUI API and return a dict compatible with GUI expectations.
        Returns a dict with keys:
          - url (str|None)
          - accessible (bool)
          - models_loaded (bool)
          - samplers_available (bool)
          - errors (list[str])
          - model_count (int, optional)
          - sampler_count (int, optional)
        """
        url = find_webui_api_port(self.base_url, self.start_port, self.max_attempts)
        if not url:
            return {
                "url": None,
                "accessible": False,
                "models_loaded": False,
                "samplers_available": False,
                "errors": [
                    f"WebUI not found on ports {self.start_port}-{self.start_port + self.max_attempts - 1}"
                ],
            }

        # Optionally tighten requests' per-call timeouts by overriding requests.Session defaults,
        # but for now just rely on validate_webui_health() internal timeouts.
        health = validate_webui_health(url)
        health["url"] = url  # ensure url is always present
        return health

    def ensure_ready(self, api_url: str, max_wait_seconds: int = 60) -> bool:
        """Block until the API reports a loaded model (or timeout)."""
        return wait_for_webui_ready(api_url, max_wait_seconds)

    def launch_if_needed(self, webui_path: Path, wait_time: int = 10) -> bool:
        """Try to launch WebUI if not already running; returns True if available."""
        # If already up, cheap exit:
        existing = find_webui_api_port(self.base_url, self.start_port, self.max_attempts)
        if existing:
            logger.info(f"WebUI already running at {existing}")
            return True
        return launch_webui_safely(webui_path, timeout=wait_time)


"""Utility functions for WebUI API discovery"""

import logging
import subprocess
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


def _normalize_candidate_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "http://127.0.0.1:7860"
    if value.isdigit():
        return f"http://127.0.0.1:{value}"
    if value.startswith(":"):
        return f"http://127.0.0.1{value}"
    if value.startswith(("http://", "https://")):
        return value.rstrip("/")
    if value.startswith("://"):
        return f"http{value}".rstrip("/")
    return f"http://{value}".rstrip("/")


def _probe_api(url: str, timeout: float = 5.0) -> bool:
    try:
        response = requests.get(f"{url.rstrip('/')}/sdapi/v1/sd-models", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def find_webui_api_port(
    base_url: str = "http://127.0.0.1", start_port: int = 7860, max_attempts: int = 5
) -> str | None:
    """
    Find the actual port where WebUI API is running.

    WebUI auto-increments ports when 7860 is busy, so this tries common ports.

    Args:
        base_url: Base URL without port
        start_port: Starting port to check (default: 7860)
        max_attempts: Maximum number of ports to try

    Returns:
        Full URL of working API or None if not found
    """
    override = os.getenv("STABLENEW_WEBUI_BASE_URL")
    if override:
        candidate = _normalize_candidate_url(override)
        if _probe_api(candidate):
            logger.info("Using STABLENEW_WEBUI_BASE_URL=%s", candidate)
            return candidate
        logger.warning("STABLENEW_WEBUI_BASE_URL unreachable: %s", candidate)

    base = (base_url or "http://127.0.0.1").rstrip("/")

    for i in range(max_attempts):
        port = start_port + i
        test_url = f"{base}:{port}"

        try:
            # Quick health check
            response = requests.get(f"{test_url}/sdapi/v1/sd-models", timeout=5)
            if response.status_code == 200:
                logger.info(f"Found WebUI API at {test_url}")
                return test_url
        except Exception:
            continue

    logger.warning(
        f"Could not find WebUI API on ports {start_port}-{start_port + max_attempts - 1}"
    )
    return None


def wait_for_webui_ready(api_url: str, max_wait_seconds: int = 60) -> bool:
    """
    Wait for WebUI to be ready and model loaded.

    Args:
        api_url: Full API URL
        max_wait_seconds: Maximum time to wait

    Returns:
        True if WebUI is ready, False if timeout
    """
    # time already imported at top

    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        try:
            # Check if API responds
            response = requests.get(f"{api_url}/sdapi/v1/options", timeout=5)
            if response.status_code == 200:
                options = response.json()

                # Check if model is loaded (has a current model)
                if options.get("sd_model_checkpoint"):
                    logger.info(f"WebUI ready with model: {options['sd_model_checkpoint']}")
                    return True

        except Exception as e:
            logger.debug(f"WebUI not ready yet: {e}")

        time.sleep(2)

    logger.error(f"WebUI did not become ready within {max_wait_seconds} seconds")
    return False


def launch_webui_safely(webui_path: Path, timeout: int = 60) -> bool:
    """
    Launch the Stable Diffusion WebUI if the executable exists.
    Returns True if the process was started (or already running), False otherwise.
    """
    logger = logging.getLogger(__name__)

    if not webui_path.exists():
        logger.warning("WebUI path does not exist: %s", webui_path)
        return False

    try:
        existing_url = find_webui_api_port()
        if existing_url:
            logger.info("WebUI already running at %s", existing_url)
            return True

        cmd = [str(webui_path)]
        cwd = str(webui_path.parent)
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

        logger.info("Launching WebUI via %s (cwd=%s)", cmd, cwd)
        subprocess.Popen(cmd, cwd=cwd, creationflags=creationflags)

        # Give the launcher a brief head start; readiness is probed elsewhere.
        time.sleep(min(max(timeout, 1), 5))
        return True

    except Exception as e:
        logger.exception("Failed to launch WebUI: %s", e)
        return False


def validate_webui_health(api_url: str) -> dict:
    """
    Perform comprehensive health check on WebUI API.

    Args:
        api_url: WebUI API URL

    Returns:
        Dictionary with health check results
    """
    health_status = {
        "url": api_url,
        "accessible": False,
        "models_loaded": False,
        "samplers_available": False,
        "errors": [],
    }

    try:
        # Basic connectivity
        response = requests.get(f"{api_url}/sdapi/v1/sd-models", timeout=5)
        if response.status_code == 200:
            health_status["accessible"] = True
            models = response.json()
            health_status["models_loaded"] = len(models) > 0
            health_status["model_count"] = len(models)
        else:
            health_status["errors"].append(f"Models endpoint returned {response.status_code}")

    except requests.exceptions.ConnectionError:
        health_status["errors"].append("Connection refused - WebUI not running")
    except requests.exceptions.Timeout:
        health_status["errors"].append("Connection timeout - WebUI may be starting up")
    except Exception as e:
        health_status["errors"].append(f"Unexpected error: {e}")

    try:
        # Samplers check
        if health_status["accessible"]:
            response = requests.get(f"{api_url}/sdapi/v1/samplers", timeout=5)
            if response.status_code == 200:
                samplers = response.json()
                health_status["samplers_available"] = len(samplers) > 0
                health_status["sampler_count"] = len(samplers)

    except Exception as e:
        health_status["errors"].append(f"Samplers check failed: {e}")

    return health_status


if __name__ == "__main__":
    info = WebUIDiscovery().discover()
    print("Discover:", info)

```

## `src/utils/webui_launcher.py`

```
# Thin wrapper so legacy imports go through the real launcher impl.
def launch_webui_safely(*args, **kwargs):
    from .webui_discovery import launch_webui_safely as _launch_webui

    return _launch_webui(*args, **kwargs)

```

