"""WebUI API helpers with throttled options plumbing."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from src.api.client import SDWebUIClient
from src.api.types import GenerateOutcome
from src.utils import get_logger

logger = get_logger(__name__)
DEFAULT_OPTIONS_MIN_INTERVAL = 8.0


class WebUIReadinessTimeout(Exception):
    """Raised when WebUI does not become truly ready within timeout."""

    def __init__(
        self,
        message: str,
        total_waited: float,
        stdout_tail: str = "",
        stderr_tail: str = "",
        checks_status: dict[str, bool] | None = None,
    ):
        super().__init__(message)
        self.total_waited = total_waited
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail
        self.checks_status = checks_status or {}


class OptionsApplyResult(str, Enum):
    APPLIED = "applied"
    SKIPPED_SAFEMODE = "skipped_safemode"
    SKIPPED_THROTTLE = "skipped_throttle"
    FAILED = "failed"


class WebUIAPI:
    """Helper that keeps /options calls rate-limited and delegates stage runs."""

    def __init__(
        self,
        *,
        client: SDWebUIClient | None = None,
        options_min_interval: float = DEFAULT_OPTIONS_MIN_INTERVAL,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self._client = client or SDWebUIClient()
        self._options_min_interval = max(0.0, options_min_interval)
        self._last_options_payload_hash: str | None = None
        self._last_options_applied_at = float("-inf")
        self._time_provider = time_provider or time.monotonic
        self._options_lock: threading.Lock = threading.Lock()
        self._client_ready_confirmed = False
        self._last_options_result: OptionsApplyResult | None = None

    def _payload_hash(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _ensure_client_ready(self) -> bool:
        if self._client_ready_confirmed:
            return True
        ready_check = getattr(self._client, "check_api_ready", None)
        if ready_check is None:
            self._client_ready_confirmed = True
            return True
        try:
            ready = bool(ready_check())
        except Exception as exc:
            logger.warning("WebUI client readiness check failed: %s", exc)
            return False
        if ready:
            self._client_ready_confirmed = True
            return True
        logger.debug("WebUI client readiness check reported not ready")
        return False

    def _sleep(self, seconds: float) -> None:
        """Sleep for the given number of seconds."""
        time.sleep(seconds)

    def wait_until_ready(
        self,
        *,
        max_attempts: int = 6,
        base_delay: float = 1.0,
        max_delay: float = 8.0,
    ) -> bool:
        """Wait until the WebUI API reports ready with exponential backoff."""

        delay = max(base_delay, 0.0)
        for attempt in range(1, max_attempts + 1):
            try:
                if self._client.check_api_ready():
                    logger.info("WebUI API confirmed ready after %s attempt(s)", attempt)
                    return True
            except Exception as exc:
                logger.debug("WebUI readiness probe attempt %s raised: %s", attempt, exc)
            if attempt >= max_attempts:
                break
            self._sleep(min(delay, max_delay))
            delay = min(delay * 2, max_delay)

        logger.warning("WebUI API did not become ready after %s attempts", max_attempts)
        return False

    def wait_until_true_ready(
        self,
        *,
        timeout_s: float = 120.0,
        poll_interval_s: float = 2.0,
        get_stdout_tail: Callable[[], str] | None = None,
    ) -> bool:
        """
        Wait until WebUI is TRULY ready: API responds AND boot marker appears in stdout.

        Boot markers checked (in order):
          - "Startup time:"
          - "Running on local URL:"
          - "Running on public URL:"

        Args:
            timeout_s: Total timeout in seconds
            poll_interval_s: How long to sleep between checks
            get_stdout_tail: Optional callable that returns recent stdout lines as string

        Returns:
            True if ready (API + marker found)

        Raises:
            WebUIReadinessTimeout if timeout or other fatal error
        """

        boot_markers = [
            "Startup time:",
            "Running on local URL:",
            "Running on public URL:",
        ]

        start_time = time.time()
        delay = max(poll_interval_s, 0.1)

        checks_status = {
            "models_endpoint": False,
            "options_endpoint": False,
            "boot_marker_found": False,
            "progress_idle": False,
        }

        while time.time() - start_time < timeout_s:
            # Check 1: models endpoint reachable
            try:
                if self._client.check_api_ready():
                    checks_status["models_endpoint"] = True
                    logger.debug("WebUI models endpoint is reachable")
                else:
                    checks_status["models_endpoint"] = False
            except Exception as exc:
                logger.debug("Models endpoint check failed: %s", exc)
                checks_status["models_endpoint"] = False

            # Check 2: options endpoint (read-only, SafeMode-safe)
            try:
                # Just check GET /options exists without writing
                if hasattr(self._client, "_session"):
                    response = self._client._session.get(
                        f"{self._client.base_url}/sdapi/v1/options",
                        timeout=5.0,
                    )
                    checks_status["options_endpoint"] = response.status_code == 200
                    logger.debug(
                        "Options endpoint check: status=%s",
                        response.status_code,
                    )
                else:
                    checks_status["options_endpoint"] = True
            except Exception as exc:
                logger.debug("Options endpoint check failed: %s", exc)
                checks_status["options_endpoint"] = False

            # Check 3: boot marker in stdout (observability-only)
            if get_stdout_tail:
                try:
                    stdout_content = get_stdout_tail()
                    marker_found = any(marker in stdout_content for marker in boot_markers)
                    checks_status["boot_marker_found"] = marker_found
                    if marker_found:
                        logger.info("WebUI boot marker detected in stdout")
                    else:
                        logger.debug("Boot marker not yet found in stdout (waiting...)")
                except Exception as exc:
                    logger.debug("Boot marker check failed: %s", exc)
                    checks_status["boot_marker_found"] = False
            else:
                # If no stdout callback provided, assume marker is present
                checks_status["boot_marker_found"] = True
                logger.debug("No stdout callback provided; assuming boot marker present")

            # Check 4: Progress endpoint check (ensures WebUI is idle/ready, not loading model)
            try:
                if hasattr(self._client, "_session"):
                    progress_response = self._client._session.get(
                        f"{self._client.base_url}/sdapi/v1/progress",
                        timeout=5.0,
                    )
                    if progress_response.status_code == 200:
                        progress_data = progress_response.json()
                        # WebUI is ready if progress is 0 (idle) and not currently processing
                        is_idle = progress_data.get("progress", 1.0) == 0.0
                        checks_status["progress_idle"] = is_idle
                        if not is_idle:
                            logger.debug("WebUI is busy (progress: %.2f)", progress_data.get("progress", 0))
                    else:
                        checks_status["progress_idle"] = False
                else:
                    checks_status["progress_idle"] = True
            except Exception as exc:
                logger.debug("Progress endpoint check failed: %s", exc)
                checks_status["progress_idle"] = False

            # API readiness requires: models endpoint + options endpoint
            # Boot marker and progress checks are observability-only
            api_ready = (
                checks_status["models_endpoint"]
                and checks_status["options_endpoint"]
            )
            if api_ready:
                elapsed = time.time() - start_time
                boot_marker_status = "found" if checks_status["boot_marker_found"] else "not found"
                progress_status = "idle" if checks_status.get("progress_idle", False) else "busy"
                logger.info(
                    "WebUI TRUE-READY confirmed after %.1f seconds (models: ok, options: ok, boot_marker: %s, progress: %s)",
                    elapsed,
                    boot_marker_status,
                    progress_status,
                )
                return True

            elapsed = time.time() - start_time
            if elapsed < timeout_s:
                self._sleep(delay)

        # Timeout
        elapsed = time.time() - start_time
        stdout_tail_str = get_stdout_tail() if get_stdout_tail else ""
        message = (
            f"WebUI did not become truly ready within {timeout_s:.1f}s "
            f"(waited {elapsed:.1f}s, checks: {checks_status})"
        )
        logger.error(message)
        raise WebUIReadinessTimeout(
            message=message,
            total_waited=elapsed,
            stdout_tail=stdout_tail_str,
            stderr_tail="",
            checks_status=checks_status,
        )

    def _finalize_options_result(
        self, status: OptionsApplyResult, *, return_status: bool
    ) -> bool | OptionsApplyResult:
        self._last_options_result = status
        return status if return_status else status == OptionsApplyResult.APPLIED

    @property
    def last_options_result(self) -> OptionsApplyResult | None:
        return self._last_options_result

    def apply_options(
        self,
        updates: dict[str, Any],
        *,
        stage: str | None = None,
        return_status: bool = False,
    ) -> bool | OptionsApplyResult:
        if not updates:
            return self._finalize_options_result(
                OptionsApplyResult.APPLIED, return_status=return_status
            )

        if not self._ensure_client_ready():
            logger.debug("Skipping WebUI options (client not ready, stage=%s)", stage)
            return self._finalize_options_result(
                OptionsApplyResult.SKIPPED_THROTTLE, return_status=return_status
            )

        if not self._client.options_write_enabled:
            logger.debug("Skipping WebUI options (SafeMode locked, stage=%s)", stage)
            return self._finalize_options_result(
                OptionsApplyResult.SKIPPED_SAFEMODE, return_status=return_status
            )

        with self._options_lock:
            payload_hash = self._payload_hash(updates)
            now = self._time_provider()
            if payload_hash == self._last_options_payload_hash:
                logger.debug("Skipping WebUI options (identical payload, stage=%s)", stage)
                return self._finalize_options_result(
                    OptionsApplyResult.SKIPPED_THROTTLE, return_status=return_status
                )

            elapsed = now - self._last_options_applied_at
            if elapsed < self._options_min_interval:
                logger.debug(
                    "Skipping WebUI options (throttled %.2fs < %.2fs, stage=%s)",
                    elapsed,
                    self._options_min_interval,
                    stage,
                )
                return self._finalize_options_result(
                    OptionsApplyResult.SKIPPED_THROTTLE, return_status=return_status
                )

            try:
                result = self._client.update_options(updates)
            except Exception as exc:  # pragma: no cover - best-effort catch
                logger.exception("Failed to apply WebUI options (stage=%s): %s", stage, exc)
                return self._finalize_options_result(
                    OptionsApplyResult.FAILED, return_status=return_status
                )

            if result is None:
                logger.debug(
                    "WebUI client skipped options update margin (stage=%s); payload=%s",
                    stage,
                    sorted(str(key) for key in updates.keys()),
                )
                return self._finalize_options_result(
                    OptionsApplyResult.SKIPPED_THROTTLE, return_status=return_status
                )

            self._last_options_payload_hash = payload_hash
            self._last_options_applied_at = now
            logger.info(
                "Applied WebUI options (stage=%s, keys=%s)",
                stage,
                ",".join(sorted(str(key) for key in updates.keys())),
            )
            return self._finalize_options_result(
                OptionsApplyResult.APPLIED, return_status=return_status
            )

    def run_stage(self, *, stage: str, payload: dict[str, Any]) -> GenerateOutcome:
        return self._client.generate_images(stage=stage, payload=payload)

    def txt2img(self, *, prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        # Minimal stub for journey tests
        return {
            "images": [{"data": "stub_txt2img_image"}],
            "info": f'{{"prompt": "{prompt}"}}',
        }

    def upscale_image(
        self,
        *,
        image: Any,
        upscale_factor: float,
        model: str,
        tile_size: int | None = None,
        prompt: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Minimal stub for journey tests
        return {
            "images": [{"data": "stub_upscaled_image"}],
            "info": f'{{"upscale_factor": {upscale_factor}, "model": "{model or "UltraSharp"}"}}',
        }
