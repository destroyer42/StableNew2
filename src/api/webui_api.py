"""WebUI API helpers with throttled options plumbing."""

from __future__ import annotations

from enum import Enum
import hashlib
import json
import threading
import time
from collections.abc import Callable
from typing import Any

from src.api.client import SDWebUIClient
from src.api.types import GenerateOutcome
from src.utils import get_logger

logger = get_logger(__name__)
DEFAULT_OPTIONS_MIN_INTERVAL = 8.0


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
            return self._finalize_options_result(OptionsApplyResult.APPLIED, return_status=return_status)

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
