"""API client for Stable Diffusion WebUI"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from src.api.healthcheck import wait_for_webui_ready
from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome, GenerateResult
from src.utils import LogContext, get_logger, log_with_ctx
from src.utils.api_failure_store_v2 import record_api_failure
from src.utils.config import ConfigManager
from src.utils.retry_policy_v2 import (
    IMG2IMG_RETRY_POLICY,
    STAGE_RETRY_POLICY,
    TXT2IMG_RETRY_POLICY,
    UPSCALE_RETRY_POLICY,
    RetryPolicy,
)

logger = get_logger(__name__)

POOL_CONNECTIONS = 20
POOL_MAXSIZE = 20
POOL_BLOCK = True
DEFAULT_CONNECT_TIMEOUT = 3.0
DEFAULT_READ_TIMEOUT = 60.0
OPTIONS_POST_MIN_INTERVAL = 6.0


class WebUIUnavailableError(Exception):
    """Raised when the WebUI cannot be reached after retrying a POST."""

    def __init__(
        self,
        endpoint: str,
        method: str,
        *,
        stage: str | None = None,
        reason: str | None = None,
        original_exception: Exception | None = None,
    ) -> None:
        message = f"WebUI unavailable for {method.upper()} {endpoint}"
        if stage:
            message = f"{message} (stage={stage})"
        if reason:
            message = f"{message} (reason={reason})"
        super().__init__(message)
        self.endpoint = endpoint
        self.method = method
        self.stage = stage
        self.reason = reason
        self.original_exception = original_exception


class WebUIPayloadValidationError(ValueError):
    """Raised when a payload cannot be serialized or violates safety checks."""


def _format_as_data_url(image_base64: str) -> str:
    if image_base64.startswith("data:"):
        return image_base64
    return f"data:image/png;base64,{image_base64}"


def _log_stage_failure(stage: str, error: str | Exception) -> None:
    log_with_ctx(
        logger,
        logging.ERROR,
        f"{stage.capitalize()} stage failure: {error}",
        ctx=LogContext(subsystem="api", stage=stage),
        extra_fields={"error": str(error)},
    )


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
        retry_callback: Callable[[str, int, int, str], None] | None = None,
        options_write_enabled: bool | None = None,
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
        self._retry_callback = retry_callback
        self._session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=POOL_CONNECTIONS,
            pool_maxsize=POOL_MAXSIZE,
            pool_block=POOL_BLOCK,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._options_lock = threading.Lock()
        self._last_options_post_ts = 0.0
        self._options_min_interval_seconds = OPTIONS_POST_MIN_INTERVAL
        self._options_readiness_provider: Callable[[], bool] | None = None
        resolved_flag = (
            bool(options_write_enabled)
            if options_write_enabled is not None
            else bool(ConfigManager().get_setting("webui_options_write_enabled", False))
        )
        self._options_write_enabled = resolved_flag
        logger.info(
            "WebUI options writes %s",
            "enabled" if self._options_write_enabled else "disabled (SafeMode)",
        )
        self._session_id = id(self._session)
        self._last_http_500_summary: dict[str, Any] | None = None

    def close(self) -> None:
        """Close the shared HTTP session if still open."""

        try:
            self._session.close()
        except Exception as exc:
            logger.debug("Failed to close WebUI HTTP session: %s", exc)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def check_connection(self, timeout: float | None = None) -> bool:
        """
        Lightweight health check for the WebUI API using the configured base URL.

        This wraps validate_webui_health so callers can probe connectivity using the
        same client instance without instantiating additional helpers.
        """
        effective_timeout = timeout if timeout is not None else min(self.timeout, 5.0)
        try:
            return wait_for_webui_ready(
                self.base_url, timeout=effective_timeout, poll_interval=0.25
            )
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

    def apply_retry_policy(self, policy: RetryPolicy) -> None:
        """Configure base retry parameters from a policy."""

        self.max_retries = max(1, policy.max_attempts)
        self.backoff_factor = max(0.0, policy.base_delay_sec)
        self.max_backoff = max(0.0, policy.max_delay_sec)
        self.jitter = max(0.0, policy.jitter_frac)

    def _calculate_backoff(
        self,
        attempt: int,
        *,
        backoff_factor: float | None = None,
        max_backoff: float | None = None,
        jitter: float | None = None,
    ) -> float:
        """Calculate the backoff delay for a retry attempt."""

        base = self.backoff_factor if backoff_factor is None else max(0.0, backoff_factor)
        max_delay = self.max_backoff if max_backoff is None else max(0.0, max_backoff)
        jitter_frac = self.jitter if jitter is None else max(0.0, jitter)
        if base <= 0:
            return 0.0

        delay = base * (2**attempt)
        if max_delay > 0:
            delay = min(delay, max_delay)

        if jitter_frac > 0 and delay > 0:
            delay += random.uniform(0, jitter_frac)

        return delay

    def _resolve_timeout(self, timeout: float | tuple[float, float] | None) -> tuple[float, float]:
        """Return a (connect, read) timeout tuple."""

        candidate = self.timeout if timeout is None else timeout
        if isinstance(candidate, tuple):
            return candidate
        read_timeout = float(candidate)
        if read_timeout <= 0:
            read_timeout = DEFAULT_READ_TIMEOUT
        connect_timeout = (
            min(read_timeout, DEFAULT_CONNECT_TIMEOUT)
            if read_timeout > 0
            else DEFAULT_CONNECT_TIMEOUT
        )
        connect_timeout = max(connect_timeout, 0.1)
        return (connect_timeout, read_timeout)

    def _build_request_summary(
        self,
        *,
        endpoint: str,
        method: str,
        stage: str | None,
        status: int | None = None,
        response_snippet: str | None = None,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "endpoint": endpoint,
            "stage": stage,
            "method": method.upper(),
            "session_id": self._session_id,
        }
        if status is not None:
            summary["status"] = status
        if response_snippet:
            summary["response_snippet"] = response_snippet
        return summary

    def _attach_diagnostics_context(
        self,
        exc: Exception,
        *,
        summary: dict[str, Any],
        webui_unavailable: bool,
        crash_suspected: bool,
        previous_http_error: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        context: dict[str, Any] = {
            "request_summary": summary,
            "webui_unavailable": webui_unavailable,
            "crash_suspected": crash_suspected,
        }
        if previous_http_error:
            context["previous_http_error"] = previous_http_error
        if error_message:
            context["error_message"] = error_message
        exc.diagnostics_context = context

    def _perform_request(
        self,
        method: str,
        endpoint: str,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_factor: float | None = None,
        stage: str | None = None,
        policy: RetryPolicy | None = None,
        ctx: LogContext | None = None,
        **kwargs: Any,
    ) -> requests.Response | None:
        """Perform an HTTP request with retry/backoff handling."""

        stage_key = (stage or "").lower() or None
        selected_policy = policy or (STAGE_RETRY_POLICY.get(stage_key) if stage_key else None)
        retries = (
            max_retries
            if max_retries is not None
            else (selected_policy.max_attempts if selected_policy else self.max_retries)
        )
        retries = max(1, retries)
        timeout_value = self._resolve_timeout(timeout)
        base_delay = (
            backoff_factor
            if backoff_factor is not None
            else (selected_policy.base_delay_sec if selected_policy else self.backoff_factor)
        )
        max_delay = selected_policy.max_delay_sec if selected_policy else self.max_backoff
        jitter_frac = selected_policy.jitter_frac if selected_policy else self.jitter
        url = f"{self.base_url}{endpoint}"
        last_exception: Exception | None = None

        context = ctx or LogContext(subsystem="api")
        if stage_key and not context.stage:
            context.stage = stage_key

        payload_capture = kwargs.get("json") or kwargs.get("data")
        if isinstance(payload_capture, dict):
            payload_capture = dict(payload_capture)

        json_payload = kwargs.get("json")
        if json_payload is not None:
            try:
                json.dumps(json_payload, ensure_ascii=False)
            except (TypeError, ValueError) as json_exc:
                raise WebUIPayloadValidationError(
                    f"Failed to serialize payload for {method.upper()} {endpoint}: {json_exc}"
                ) from json_exc

        def _log_api_failure(
            *, error_text: str, status: int | None = None, response_text: str | None = None
        ) -> None:
            record_api_failure(
                stage=stage_key,
                endpoint=endpoint,
                method=method,
                payload=payload_capture,
                status_code=status,
                response_text=response_text,
                error_message=error_text,
            )

        for attempt in range(retries):
            response: requests.Response | None = None
            try:
                response = self._session.request(
                    method.upper(),
                    url,
                    timeout=timeout_value,
                    **kwargs,
                )
                try:
                    response.raise_for_status()
                except requests.HTTPError as http_exc:
                    status_code = getattr(response, "status_code", None)
                    resp_text = getattr(response, "text", None)
                    truncated_text = (
                        resp_text[:4000] + ("..." if len(resp_text) > 4000 else "")
                        if resp_text
                        else None
                    )
                    summary = self._build_request_summary(
                        endpoint=endpoint,
                        method=method,
                        stage=stage_key,
                        status=status_code,
                        response_snippet=truncated_text,
                    )
                    self._attach_diagnostics_context(
                        http_exc,
                        summary=summary,
                        webui_unavailable=False,
                        crash_suspected=False,
                    )
                    if (
                        status_code == 500
                        and method.upper() == "POST"
                        and endpoint.endswith("/txt2img")
                    ):
                        self._last_http_500_summary = dict(summary)
                    log_with_ctx(
                        logger,
                        logging.WARNING,
                        f"HTTPError {method.upper()} {url} status={status_code}: {http_exc}",
                        ctx=context,
                        extra_fields={
                            "response_text": truncated_text,
                            "timeout": timeout_value,
                            "session_id": self._session_id,
                        },
                    )
                    _log_api_failure(
                        error_text=str(http_exc),
                        status=status_code,
                        response_text=truncated_text,
                    )
                    raise
                self._last_http_500_summary = None
                return response
            except Exception as exc:  # noqa: BLE001 - broad to ensure retries
                if response is not None:
                    response.close()
                last_exception = exc
                existing_context = getattr(exc, "diagnostics_context", None)
                if existing_context and existing_context.get("request_summary"):
                    summary = existing_context["request_summary"]
                else:
                    status_code = getattr(response, "status_code", None) if response else None
                    response_snippet = None
                    if not isinstance(exc, requests.HTTPError):
                        response_snippet = str(exc)
                    summary = self._build_request_summary(
                        endpoint=endpoint,
                        method=method,
                        stage=stage_key,
                        status=status_code,
                        response_snippet=response_snippet,
                    )
                webui_unavailable = isinstance(exc, requests.ConnectionError)
                crash_suspected = webui_unavailable and bool(self._last_http_500_summary)
                if existing_context is None:
                    previous_summary = (
                        dict(self._last_http_500_summary) if crash_suspected else None
                    )
                    self._attach_diagnostics_context(
                        exc,
                        summary=summary,
                        webui_unavailable=webui_unavailable,
                        crash_suspected=crash_suspected,
                        previous_http_error=previous_summary,
                        error_message=str(exc),
                    )
                if crash_suspected:
                    self._last_http_500_summary = None
                attempt_index = attempt + 1
                log_with_ctx(
                    logger,
                    logging.WARNING,
                    f"Request {method.upper()} {url} attempt {attempt_index}/{retries} failed",
                    ctx=context,
                    extra_fields={
                        "error": str(exc),
                        "stage": stage_key,
                        "attempt": attempt_index,
                        "max_attempts": retries,
                        "timeout": timeout_value,
                        "session_id": self._session_id,
                        "reuse_session": True,
                    },
                )
                _log_api_failure(
                    error_text=str(exc),
                    response_text=str(getattr(exc, "response", "") or getattr(exc, "text", None)),
                )
                if self._retry_callback:
                    try:
                        self._retry_callback(
                            stage=stage_key or stage or "api",
                            attempt_index=attempt_index,
                            max_attempts=retries,
                            reason=type(exc).__name__,
                        )
                    except Exception:
                        logger.debug("Retry callback failed", exc_info=True)
                if attempt >= retries - 1:
                    break

                delay = self._calculate_backoff(
                    attempt,
                    backoff_factor=base_delay,
                    max_backoff=max_delay,
                    jitter=jitter_frac,
                )
                if delay > 0:
                    self._sleep(delay)

        if last_exception is not None:
            log_with_ctx(
                logger,
                logging.ERROR,
                f"Request {method.upper()} {url} failed after {retries} attempts",
                ctx=context,
                extra_fields={
                    "error": str(last_exception),
                    "stage": stage_key,
                    "attempts": retries,
                },
            )
            if (
                stage_key
                and method.upper() == "POST"
                and isinstance(last_exception, (requests.ConnectionError, requests.Timeout))
            ):
                raise WebUIUnavailableError(
                    endpoint=url,
                    method=method.upper(),
                    stage=stage_key,
                    reason=str(last_exception),
                    original_exception=last_exception,
                )

        return None

    @contextmanager
    def _request_context(
        self,
        method: str,
        endpoint: str,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_factor: float | None = None,
        stage: str | None = None,
        policy: RetryPolicy | None = None,
        ctx: LogContext | None = None,
        **kwargs: Any,
    ):
        """Context manager that closes responses after use."""

        response = self._perform_request(
            method,
            endpoint,
            timeout=timeout,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            stage=stage,
            policy=policy,
            ctx=ctx,
            **kwargs,
        )
        try:
            yield response
        finally:
            if response is not None:
                response.close()

    def set_options_readiness_provider(self, provider: Callable[[], bool] | None) -> None:
        """Set a callable used to gate /options POST requests."""

        self._options_readiness_provider = provider

    @property
    def options_write_enabled(self) -> bool:
        """Expose whether SafeMode is allowing /options writes."""

        return self._options_write_enabled

    def set_options_write_enabled(self, enabled: bool) -> None:
        """Toggle whether /options POSTs are permitted."""

        self._options_write_enabled = bool(enabled)
        logger.info(
            "WebUI options writes %s",
            "enabled" if self._options_write_enabled else "disabled (SafeMode)",
        )

    def _options_write_allowed(self) -> bool:
        return self._options_write_enabled

    def _options_readiness_ok(self) -> bool:
        provider = self._options_readiness_provider
        if provider is None:
            return True
        try:
            ready = bool(provider())
        except Exception as exc:
            logger.warning("Options readiness provider raised: %s", exc)
            return False
        if not ready:
            logger.debug("Skipping /options POST; readiness provider reports WebUI not ready")
        return ready

    def _options_throttle_allows(self) -> bool:
        now = time.monotonic()
        with self._options_lock:
            delta = now - self._last_options_post_ts
            if delta < self._options_min_interval_seconds:
                logger.debug("Skipping /options POST; throttled (%.2fs since last post)", delta)
                return False
            self._last_options_post_ts = now
        return True

    def _options_can_send(self) -> tuple[bool, str | None]:
        if not self._options_write_allowed():
            return False, "safe_mode"
        if not self._options_readiness_ok():
            return False, "readiness"
        if not self._options_throttle_allows():
            return False, "throttle"
        return True, None

    def _option_supports(self, key: str) -> bool:
        """Return True if the API advertises the given /options key."""

        keys = self._ensure_option_keys()
        return key in keys

    def _ensure_option_keys(self) -> set[str]:
        """Fetch and cache the option keys from the API."""

        if self._option_keys is not None:
            return self._option_keys

        with self._request_context("get", "/sdapi/v1/options", timeout=10) as response:
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

        with self._request_context("get", "/sdapi/v1/options", timeout=10) as response:
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

        can_send, reason = self._options_can_send()
        if not can_send:
            logger.debug("Skipping safe WebUI upscale defaults; reason=%s", reason)
            return

        with self._request_context(
            "post",
            "/sdapi/v1/options",
            json=payload,
            timeout=15,
        ) as response:
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

        can_send, reason = self._options_can_send()
        if not can_send:
            logger.debug("Skipping upscale defaults; reason=%s", reason)
            return

        try:
            with self._request_context(
                "post",
                "/sdapi/v1/options",
                json=payload,
                timeout=30,
            ) as response:
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

        with self._request_context(
            "get",
            "/sdapi/v1/sd-models",
            timeout=10,
            max_retries=max_retries,
            backoff_factor=retry_delay,
        ) as response:
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
        logger.info("🔵 [BATCH_SIZE_DEBUG] client.txt2img: Received payload with batch_size=%s, n_iter=%s", payload.get('batch_size'), payload.get('n_iter'))
        with self._request_context(
            "post",
            "/sdapi/v1/txt2img",
            json=payload,
            stage="txt2img",
            policy=TXT2IMG_RETRY_POLICY,
        ) as response:
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
        with self._request_context(
            "post",
            "/sdapi/v1/img2img",
            json=payload,
            stage="img2img",
            policy=IMG2IMG_RETRY_POLICY,
        ) as response:
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
        with self._request_context(
            "post",
            "/sdapi/v1/extra-single-image",
            json=payload,
            stage="upscale",
            policy=UPSCALE_RETRY_POLICY,
        ) as response:
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
        normalized_image = _format_as_data_url(image_base64)
        if not normalized_image:
            _log_stage_failure("upscale", "Missing image payload for upscale")
            return None

        payload = {
            "resize_mode": 0,
            "upscaling_resize": upscaling_resize,
            "upscaler_1": upscaler,
            "image": normalized_image,
            "gfpgan_visibility": gfpgan_visibility,
            "codeformer_visibility": codeformer_visibility,
            "codeformer_weight": codeformer_weight,
        }
        ctx = LogContext(subsystem="api", stage="upscale")
        log_with_ctx(
            logger,
            logging.DEBUG,
            "Upscale payload built",
            ctx=ctx,
            extra_fields={
                "endpoint": "/sdapi/v1/extra-single-image",
                "image_len": len(payload["image"]),
                "upscaler": upscaler,
                "scale": upscaling_resize,
            },
        )
        with self._request_context(
            "post",
            "/sdapi/v1/extra-single-image",
            json=payload,
            stage="upscale",
            policy=UPSCALE_RETRY_POLICY,
        ) as response:
            if response is None:
                _log_stage_failure("upscale", "No response from extra-single-image")
                return None

            try:
                data = response.json()
            except ValueError as exc:
                _log_stage_failure("upscale", exc)
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

    def _normalize_response_to_result(
        self, stage: str, response: dict[str, Any] | None, timings: dict[str, float] | None
    ) -> GenerateResult | None:
        if response is None:
            return None
        info = response.get("info")
        if isinstance(info, str):
            try:
                info = json.loads(info)
            except Exception:
                info = {}
        if not isinstance(info, dict):
            info = {}
        images = response.get("images")
        if not isinstance(images, list):
            images = []
        return GenerateResult(images=images, info=info, stage=stage, timings=timings)

    def _generate_error_outcome(
        self,
        stage: str,
        message: str,
        code: GenerateErrorCode,
        details: dict[str, Any] | None = None,
    ) -> GenerateOutcome:
        return GenerateOutcome(
            error=GenerateError(code=code, message=message, stage=stage, details=details),
        )

    def generate_images(
        self,
        *,
        stage: str,
        payload: dict[str, Any],
        timings: dict[str, float] | None = None,
    ) -> GenerateOutcome:
        stage_normalized = (stage or "txt2img").lower()
        try:
            if stage_normalized == "txt2img":
                response = self.txt2img(payload)
            elif stage_normalized == "img2img":
                response = self.img2img(payload)
            elif stage_normalized in {"upscale", "upscale_image"}:
                response = self.upscale(payload)
            else:
                raise ValueError(f"Unsupported stage: {stage}")

            result = self._normalize_response_to_result(stage_normalized, response, timings)
            if result is None:
                return self._generate_error_outcome(
                    stage_normalized, "WebUI returned no data", GenerateErrorCode.UNKNOWN
                )
            return GenerateOutcome(result=result)
        except requests.RequestException as exc:
            diag = getattr(exc, "diagnostics_context", None)
            details = {"diagnostics": diag} if diag else None
            return self._generate_error_outcome(
                stage_normalized,
                str(exc),
                GenerateErrorCode.CONNECTION,
                details=details,
            )
        except Exception as exc:
            diag = getattr(exc, "diagnostics_context", None)
            details = {"diagnostics": diag} if diag else None
            return self._generate_error_outcome(
                stage_normalized,
                str(exc),
                GenerateErrorCode.UNKNOWN,
                details=details,
            )

    def get_models(self) -> list[dict[str, Any]]:
        """
        Get list of available SD models.

        Returns:
            List of model information
        """

        with self._request_context("get", "/sdapi/v1/sd-models", timeout=10) as response:
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
        with self._request_context("get", "/sdapi/v1/sd-vae", timeout=10) as response:
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
        with self._request_context("get", "/sdapi/v1/samplers", timeout=10) as response:
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
        with self._request_context("get", "/sdapi/v1/upscalers", timeout=10) as response:
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

        with self._request_context("get", "/sdapi/v1/hypernetworks", timeout=10) as response:
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
        with self._request_context("get", "/sdapi/v1/schedulers", timeout=10) as response:
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

    def get_adetailer_models(self) -> list[str]:
        """
        Get list of available ADetailer models.
        
        Returns:
            List of ADetailer model names (detection models including yolo and mediapipe)
        """
        # Try to get from scripts API
        with self._request_context("get", "/sdapi/v1/scripts", timeout=10) as response:
            if response is None:
                logger.warning("Failed to get scripts from API; using ADetailer defaults")
                return self._get_default_adetailer_models()
            
            try:
                data = response.json()
                # Look for ADetailer in txt2img scripts
                txt2img_scripts = data.get("txt2img", [])
                for script in txt2img_scripts:
                    if isinstance(script, dict) and "adetailer" in script.get("name", "").lower():
                        # Try to extract model list from args
                        # ADetailer typically has args with 'ad_model' or similar
                        args = script.get("args", [])
                        if not args:
                            continue
                            
                        # The first arg in ADetailer is usually the model selector
                        # It may be a dict with 'choices' or 'value' field
                        for i, arg in enumerate(args):
                            if isinstance(arg, dict):
                                # Check for choices field (dropdown options)
                                if "choices" in arg:
                                    choices = arg.get("choices", [])
                                    if choices and len(choices) > 3:  # Sanity check
                                        logger.info("Retrieved %s ADetailer models from scripts API (arg %s)", len(choices), i)
                                        return choices
                                # Also check label for model-related args
                                label = arg.get("label", "").lower()
                                if "model" in label and "choices" in arg:
                                    choices = arg.get("choices", [])
                                    if choices:
                                        logger.info("Retrieved %s ADetailer models from scripts API (via label)", len(choices))
                                        return choices
            except Exception as exc:
                logger.warning(f"Failed to parse ADetailer models from scripts: {exc}")
        
        # Fallback defaults
        defaults = self._get_default_adetailer_models()
        logger.info("Using default ADetailer models: %s", len(defaults))
        return defaults
    
    @staticmethod
    def _get_default_adetailer_models() -> list[str]:
        """Get comprehensive default list of common ADetailer detection models."""
        return [
            "face_yolov8n.pt",
            "face_yolov8s.pt",
            "hand_yolov8n.pt",
            "hand_yolov8s.pt",
            "person_yolov8n-seg.pt",
            "person_yolov8s-seg.pt",
            "mediapipe_face_full",
            "mediapipe_face_short",
            "mediapipe_face_mesh",
            "mediapipe_face_mesh_eyes_only",
        ]

    def get_adetailer_detectors(self) -> list[str]:
        """
        Get list of available ADetailer detectors.
        
        Note: In ADetailer, 'detectors' are the same as 'models' - they're all detection models.
        The GUI may show them separately for UX, but the API uses the same list.
        
        Returns:
            List of ADetailer detector/model names (same as get_adetailer_models)
        """
        # ADetailer doesn't have a separate detector list - it's the same as models
        # Both dropdowns should show the same detection models
        return self.get_adetailer_models()

    def set_model(self, model_name: str) -> bool:
        """
        Set the current SD model.

        Args:
            model_name: Name of the model to set

        Returns:
            True if successful
        """
        payload = {"sd_model_checkpoint": model_name}
        can_send, reason = self._options_can_send()
        if not can_send:
            if reason == "safe_mode":
                logger.warning(
                    "Skipping set_model because options writes are disabled (SafeMode); target=%s",
                    model_name,
                )
            else:
                logger.debug("Skipping set_model; reason=%s", reason)
            return False
        with self._request_context(
            "post",
            "/sdapi/v1/options",
            json=payload,
            timeout=75,  # Model switching can take time
        ) as response:
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
        can_send, reason = self._options_can_send()
        if not can_send:
            if reason == "safe_mode":
                logger.warning(
                    "Skipping set_vae because options writes are disabled (SafeMode); target=%s",
                    vae_name,
                )
            else:
                logger.debug("Skipping set_vae; reason=%s", reason)
            return False
        with self._request_context(
            "post",
            "/sdapi/v1/options",
            json=payload,
            timeout=10,
        ) as response:
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

        can_send, reason = self._options_can_send()
        if not can_send:
            if reason == "safe_mode":
                logger.warning(
                    "Skipping set_hypernetwork because options writes are disabled (SafeMode); target=%s",
                    hyper_name,
                )
            else:
                logger.debug("Skipping set_hypernetwork; reason=%s", reason)
            return False

        with self._request_context(
            "post",
            "/sdapi/v1/options",
            json=payload,
            timeout=10,
        ) as response:
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
        with self._request_context("get", "/sdapi/v1/sd-models", timeout=10) as response:
            if response is None:
                return []

            try:
                data = response.json()
            except ValueError as exc:
                logger.error("get_models_old failed to parse response: %s", exc)
                return []

        return data

    def get_options(self) -> dict[str, Any]:
        """
        Retrieve the current WebUI global options.
        """

        with self._request_context("get", "/sdapi/v1/options", timeout=10) as response:
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

        can_send, reason = self._options_can_send()
        if not can_send:
            if reason == "safe_mode":
                logger.warning(
                    "Skipping WebUI options update because options writes are disabled (SafeMode)"
                )
            else:
                logger.debug("Skipped WebUI options update; reason=%s", reason)
            return None

        with self._request_context(
            "post",
            "/sdapi/v1/options",
            json=updates,
            timeout=15,
        ) as response:
            if response is None:
                raise RuntimeError("Failed to update WebUI options")

            try:
                return response.json()
            except ValueError as exc:
                logger.error("Failed to parse WebUI options update response: %s", exc)
                raise

    def get_current_model(self) -> str | None:
        """
        Get the currently loaded model.

        Returns:
            Current model name
        """
        with self._request_context("get", "/sdapi/v1/options", timeout=10) as response:
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
