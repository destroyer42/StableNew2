"""API client for Stable Diffusion WebUI"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import requests

from src.api.healthcheck import wait_for_webui_ready
from src.utils import get_logger, LogContext, log_with_ctx

logger = get_logger(__name__)


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
            return wait_for_webui_ready(self.base_url, timeout=effective_timeout, poll_interval=0.25)
        except Exception:
            pass
        try:
            health = validate_webui_health(self.base_url, timeout=effective_timeout)
            if isinstance(health, dict):
                return bool(health.get("accessible"))
            return bool(health)
        except TypeError:
            # Older validate_webui_health implementations may not accept timeout.
            health = validate_webui_health(self.base_url)
            if isinstance(health, dict):
                return bool(health.get("accessible"))
            return bool(health)
        except Exception:
            return False

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

        ctx = LogContext(subsystem="api")
        for attempt in range(retries):
            try:
                response = requests.request(method.upper(), url, timeout=timeout_value, **kwargs)
                try:
                    response.raise_for_status()
                except requests.HTTPError as http_exc:
                    # Log method, URL, status code, and truncated response text
                    status_code = getattr(response, 'status_code', None)
                    resp_text = getattr(response, 'text', None)
                    if resp_text:
                        truncated_text = resp_text[:4000] + ("..." if len(resp_text) > 4000 else "")
                    else:
                        truncated_text = None
                    log_with_ctx(
                        logger,
                        logging.WARNING,
                        f"HTTPError {method.upper()} {url} status={status_code}: {http_exc}",
                        ctx=ctx,
                        extra_fields={"response_text": truncated_text},
                    )
                    raise
                return response
            except Exception as exc:  # noqa: BLE001 - broad to ensure retries
                last_exception = exc
                log_with_ctx(
                    logger,
                    logging.WARNING,
                    f"Request {method.upper()} {url} attempt {attempt + 1}/{retries} failed",
                    ctx=ctx,
                    extra_fields={"error": str(exc)},
                )
                if attempt >= retries - 1:
                    break

                delay = self._calculate_backoff(attempt, backoff_factor)
                if delay > 0:
                    self._sleep(delay)

        if last_exception is not None:
            log_with_ctx(
                logger,
                logging.ERROR,
                f"Request {method.upper()} {url} failed after {retries} attempts",
                ctx=ctx,
                extra_fields={"error": str(last_exception)},
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


# ---------------------------------------------------------------------------
# Backwards-compatibility alias for older tests/imports
# ---------------------------------------------------------------------------
ApiClient = SDWebUIClient
