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


class ForgeWebUIClient(SDWebUIClient):
    """``SDWebUIClient`` with Forge Neo's VAE/module contract."""

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

    def _resolve_module_name(self, requested: str) -> str:
        """Map a requested VAE name onto an exact Forge module name, or raise."""

        modules = self.get_vae_models()
        by_key = {_module_key(m["model_name"]): m["model_name"] for m in modules}
        key = _module_key(requested)
        if key in by_key:
            return by_key[key]
        stripped = {_strip_extension(k): v for k, v in by_key.items()}
        if _strip_extension(key) in stripped:
            return stripped[_strip_extension(key)]
        raise ForgeVAEError(
            f"VAE '{requested}' is not listed by the Forge endpoint ({SD_MODULES_ENDPOINT}); "
            "refusing to write it because Forge would silently clear the VAE."
        )

    def set_vae(self, vae_name: str) -> bool:
        requested = str(vae_name or "").strip()
        automatic = requested.lower() in _AUTOMATIC_VAE_NAMES
        target = [] if automatic else [self._resolve_module_name(requested)]

        can_send, reason = self._options_can_send()
        if not can_send:
            if reason == "safe_mode":
                logger.warning(
                    "Skipping Forge set_vae because options writes are disabled (SafeMode); "
                    "target=%s",
                    vae_name,
                )
            else:
                logger.debug("Skipping Forge set_vae; reason=%s", reason)
            return False

        with self._request_context(
            "post",
            "/sdapi/v1/options",
            json={FORGE_MODULES_OPTION: target},
            timeout=75,  # a module change may reload the model
        ) as response:
            if response is None:
                return False

        observed = self.get_current_vae()
        expected = "Automatic" if automatic else target[0]
        # get_current_vae() reports "Automatic" for an empty module list, so one comparison covers
        # both the explicit-module and the cleared case.
        if _module_key(observed or "") != _module_key(expected):
            raise ForgeVAEError(
                f"Forge did not apply VAE '{expected}' (endpoint reports '{observed}'); "
                "generation must not proceed with an unverified VAE."
            )
        logger.info("Set Forge VAE module to: %s", expected)
        return True

    def get_current_vae(self) -> str | None:
        endpoint = "/sdapi/v1/options"
        if self._resource_endpoint_on_cooldown(endpoint):
            return None

        with self._request_context("get", endpoint, timeout=10) as response:
            if response is None:
                logger.warning("get_current_vae: response is None")
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
        if not isinstance(modules, list) or not modules:
            return "Automatic"
        names = [os.path.basename(str(item).replace("\\", "/")) for item in modules if item]
        if not names:
            return "Automatic"
        return names[0] if len(names) == 1 else ", ".join(names)


__all__ = [
    "FORGE_MODULES_OPTION",
    "ForgeVAEError",
    "ForgeWebUIClient",
    "SD_MODULES_ENDPOINT",
    "normalize_sd_modules",
]
