"""Forge WebUI transport adapter (PR-IMG-FORGE-100).

``SDWebUIClient`` remains the A1111 client and the transport for every endpoint that Forge Neo
exposes with the same contract (``txt2img``, ``img2img``, ``extra-single-image``, ``progress``,
``interrupt``, ``options``, ``cmd-flags``, ``sd-models``, ``samplers``, ``schedulers``,
``upscalers``, ``scripts``, ``script-info``). This subclass overrides only the VAE contract, where
Forge Neo genuinely differs (verified against the frozen source in
``config/forge_qualification_runtime.json``):

* The VAE/text-encoder listing is ``GET /sdapi/v1/sd-modules`` (there is no ``/sd-vae``); entries
  keep the ``{"model_name", "filename"}`` shape, so they normalize directly into StableNew's
  existing VAE resource contract.
* The ``sd_vae`` option is a non-interactive "Automatic" placeholder. The effective VAE is the
  ``forge_additional_modules`` option, written by module *name* (file basename) and read back as a
  list of file paths. Forge **silently drops** a module name it does not know, which would clear the
  VAE, so every write is verified by reading the option back and a mismatch raises before any
  generation can be dispatched.

No generic runner code needs Forge field knowledge; this class is created only by the runtime-ports
seam for the configured ``forge_webui`` runtime identity.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from typing import Any

from src.api.client import SDWebUIClient

logger = logging.getLogger(__name__)

SD_MODULES_ENDPOINT = "/sdapi/v1/sd-modules"
FORGE_MODULES_OPTION = "forge_additional_modules"
_AUTOMATIC_VAE_NAMES = frozenset({"", "automatic", "none"})
_MODULE_EXTENSIONS = (".safetensors", ".sft", ".pt", ".pth", ".ckpt", ".bin", ".gguf")


class ForgeVAEError(RuntimeError):
    """A requested VAE could not be selected or verified on the Forge endpoint."""


def normalize_sd_modules(payload: Any) -> list[dict[str, Any]]:
    """Normalize Forge's ``/sd-modules`` response into StableNew's VAE resource contract."""

    if not isinstance(payload, list):
        return []
    normalized: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("model_name") or "").strip()
        if not name:
            continue
        normalized.append({"model_name": name, "filename": str(entry.get("filename") or "")})
    return normalized


def _module_key(value: str) -> str:
    return os.path.basename(str(value or "").strip().replace("\\", "/")).lower()


def _strip_extension(value: str) -> str:
    lowered = value.lower()
    for ext in _MODULE_EXTENSIONS:
        if lowered.endswith(ext):
            return lowered[: -len(ext)]
    return lowered


def module_set_key(names: Sequence[str] | None) -> list[str]:
    """Order- and extension-insensitive identity of a module selection (``[]`` is "Automatic")."""

    return sorted(_strip_extension(_module_key(item)) for item in names or [] if str(item or "").strip())


class ForgeWebUIClient(SDWebUIClient):
    """``SDWebUIClient`` with Forge Neo's VAE/module contract."""

    @staticmethod
    def _get_default_adetailer_models() -> list[str]:
        """Detectors to advertise when the endpoint's own list is unavailable: only the managed runtime's accepted set.

        The generic A1111 default (yolov8s variants, person segmentation, MediaPipe) is not installed in the managed
        Forge runtime, so offering it would present controls that fail at execution.
        """

        from src.utils.managed_forge_runtime import accepted_detector_names

        return list(accepted_detector_names())

    def get_vae_models(self) -> list[dict[str, Any]]:
        endpoint = SD_MODULES_ENDPOINT
        if self._resource_endpoint_startup_grace_active(endpoint):
            return []
        if self._resource_endpoint_on_cooldown(endpoint):
            return []

        with self._request_context("get", endpoint, timeout=10) as response:
            if response is None:
                self._mark_resource_endpoint_failed(endpoint)
                return []
            try:
                data = response.json()
            except ValueError as exc:
                logger.error("Failed to parse Forge module response: %s", exc)
                self._mark_resource_endpoint_failed(endpoint)
                return []

        self._clear_resource_endpoint_failure(endpoint)
        modules = normalize_sd_modules(data)
        logger.debug("Retrieved %s Forge VAE/text-encoder modules", len(modules))
        return modules

    def get_loras(self) -> list[dict[str, Any]] | None:
        """LoRAs the serving Forge lists (``GET /sdapi/v1/loras``): ``name``, ``alias``, ``path``.

        Read-only evidence of what Forge itself will load; ``None`` when the listing cannot be read. It is never
        an identity authority (``AssetRegistry`` is) and never refreshes or edits Forge's catalog.
        """

        endpoint = "/sdapi/v1/loras"
        with self._request_context("get", endpoint, timeout=20) as response:
            if response is None:
                return None
            try:
                data = response.json()
            except ValueError:
                return None
        if not isinstance(data, list):
            return None
        return [
            {
                "name": str(item.get("name") or ""),
                "alias": str(item.get("alias") or ""),
                "path": str(item.get("path") or ""),
            }
            for item in data
            if isinstance(item, dict)
        ]

    def _resolve_module_name(self, requested: str, *, noun: str = "VAE") -> str:
        """Map a requested module name onto an exact Forge module name, or raise."""

        modules = self.get_vae_models()
        by_key = {_module_key(m["model_name"]): m["model_name"] for m in modules}
        key = _module_key(requested)
        if key in by_key:
            return by_key[key]
        stripped = {_strip_extension(k): v for k, v in by_key.items()}
        if _strip_extension(key) in stripped:
            return stripped[_strip_extension(key)]
        raise ForgeVAEError(
            f"{noun} '{requested}' is not listed by the Forge endpoint ({SD_MODULES_ENDPOINT}); "
            "refusing to write it because Forge would silently clear the module selection."
        )

    def set_vae(self, vae_name: str) -> bool:
        """Select one VAE module (or clear to Automatic) through the verified module write."""

        requested = str(vae_name or "").strip()
        if requested.lower() in _AUTOMATIC_VAE_NAMES:
            return self._write_modules([], noun="VAE", strict=False)
        return self._write_modules([requested], noun="VAE", strict=False)

    def set_additional_modules(self, modules: Sequence[str]) -> bool:
        """Select the complete Forge module set (e.g. a text encoder plus a VAE) in one write.

        Every requested module is resolved against ``/sdapi/v1/sd-modules`` first (an unavailable
        module raises before any write), the whole list is sent once, and the effective option is
        read back and compared exactly; any mismatch raises so generation cannot proceed with an
        unverified module set. An empty list clears the selection.

        Unlike ``set_vae`` this never *skips* silently: the shared options throttle (a model switch
        just before it) is waited out, and a SafeMode/readiness refusal raises, because a skipped
        write would let Forge load the model without its text encoder (found by the PR-IMG-116 smoke).
        """

        requested = [str(item).strip() for item in modules if str(item or "").strip()]
        return self._write_modules(requested, noun="module", strict=True)

    def _await_options_write_allowed(self, *, noun: str) -> None:
        """Strict writes: wait out the throttle (bounded); any other refusal is an error."""

        deadline = time.monotonic() + max(15.0, 2 * float(self._options_min_interval_seconds))
        while True:
            can_send, reason = self._options_can_send()
            if can_send:
                return
            if reason != "throttle" or time.monotonic() >= deadline:
                raise ForgeVAEError(
                    f"Forge {noun} selection was not applied ({reason}); generation must not proceed "
                    "without the required modules."
                )
            time.sleep(min(0.5, max(0.01, float(self._options_min_interval_seconds) / 4)))

    def _write_modules(self, requested: list[str], *, noun: str, strict: bool = False) -> bool:
        targets = [self._resolve_module_name(item, noun=noun) for item in requested]
        keys = [_strip_extension(_module_key(item)) for item in targets]
        if len(set(keys)) != len(keys):
            raise ForgeVAEError(f"Duplicate Forge {noun} selection: {requested}")

        if strict:
            self._await_options_write_allowed(noun=noun)
            can_send, reason = True, None
        else:
            can_send, reason = self._options_can_send()
        if not can_send:
            if reason == "safe_mode":
                logger.warning(
                    "Skipping Forge module write because options writes are disabled (SafeMode); "
                    "target=%s",
                    requested,
                )
            else:
                logger.debug("Skipping Forge module write; reason=%s", reason)
            return False

        with self._request_context(
            "post",
            "/sdapi/v1/options",
            json={FORGE_MODULES_OPTION: targets},
            timeout=75,  # a module change may reload the model
        ) as response:
            if response is None:
                return False

        observed = self.get_additional_modules()
        observed_keys = sorted(_strip_extension(_module_key(item)) for item in observed or [])
        if observed is None or observed_keys != sorted(keys):
            expected_label = ", ".join(targets) if targets else "Automatic"
            observed_label = ", ".join(observed) if observed else "Automatic"
            raise ForgeVAEError(
                f"Forge did not apply {noun} '{expected_label}' (endpoint reports "
                f"'{observed_label}'); generation must not proceed with an unverified selection."
            )
        logger.info("Set Forge modules to: %s", ", ".join(targets) if targets else "Automatic")
        return True

    def get_additional_modules(self) -> list[str] | None:
        """Effective ``forge_additional_modules`` as file basenames; ``None`` when unreadable."""

        endpoint = "/sdapi/v1/options"
        if self._resource_endpoint_on_cooldown(endpoint):
            return None

        with self._request_context("get", endpoint, timeout=10) as response:
            if response is None:
                logger.warning("get_additional_modules: response is None")
                self._mark_resource_endpoint_failed(endpoint)
                return None
            try:
                data = response.json()
            except ValueError as exc:
                logger.error("Failed to parse current Forge module response: %s", exc)
                self._mark_resource_endpoint_failed(endpoint)
                return None

        self._clear_resource_endpoint_failure(endpoint)
        modules = data.get(FORGE_MODULES_OPTION) if isinstance(data, dict) else None
        if not isinstance(modules, list):
            return []
        return [os.path.basename(str(item).replace("\\", "/")) for item in modules if item]

    def get_current_vae(self) -> str | None:
        names = self.get_additional_modules()
        if names is None:
            return None
        if not names:
            return "Automatic"
        return names[0] if len(names) == 1 else ", ".join(names)


__all__ = [
    "FORGE_MODULES_OPTION",
    "ForgeVAEError",
    "ForgeWebUIClient",
    "SD_MODULES_ENDPOINT",
    "module_set_key",
    "normalize_sd_modules",
]
