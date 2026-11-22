from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.api.client import DEFAULT_SCHEDULERS, SDWebUIClient, normalize_scheduler_names
from src.api.webui_resources import DEFAULT_CLIENT, WebUIResource
from src.api.webui_resources import WebUIResourceService as BaseWebUIResourceService
from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.assets.component_evidence import (
    ARCH_QWEN_IMAGE_DIT,
    ARCH_Z_IMAGE_DIT,
    ComponentEvidence,
    is_qwen_image_20b_fp8,
)
from src.assets.flux_variant import classify_flux_variant
from src.assets.picker_compatibility import PickerEvidence
from src.assets.registry import AssetRegistry
from src.image_backends.comfy_image_readiness import check_installation
from src.image_backends.comfy_qwen_image_profile import QwenImageProfile
from src.image_backends.forge_flux1_profile import Flux1Profile
from src.image_backends.model_policy import resolve_model_policy, resolve_model_profile_for_policy
from src.image_backends.model_readiness import assess_model_readiness

logger = logging.getLogger(__name__)

CANONICAL_WEBUI_RESOURCE_KEYS: tuple[str, ...] = (
    "models",
    "vaes",
    "samplers",
    "schedulers",
    "upscalers",
    "hypernetworks",
    "embeddings",
    "adetailer_models",
    "adetailer_detectors",
)


def build_empty_resource_map() -> dict[str, list[Any]]:
    return {key: [] for key in CANONICAL_WEBUI_RESOURCE_KEYS}


def normalize_resource_map(payload: dict[str, Any] | None) -> dict[str, list[Any]]:
    resources = build_empty_resource_map()
    if not payload:
        return resources
    for key in CANONICAL_WEBUI_RESOURCE_KEYS:
        resources[key] = list(payload.get(key) or [])
    return resources


class WebUIResourceService(BaseWebUIResourceService):
    """WebUI resource helper that can refresh all resource lists at once."""

    def __init__(self, client: SDWebUIClient | None = DEFAULT_CLIENT, **kwargs: Any) -> None:
        super().__init__(client=client, **kwargs)

    def refresh_all(self, timeout: float = 5.0) -> dict[str, list[Any]]:
        """Fetch the canonical resource sets defined by the UI dropdowns.

        Args:
            timeout: Maximum seconds to wait for each resource fetch. Default 5.0.

        Returns:
            Dictionary of resource lists. Empty lists returned on timeout/error.
        """
        # Use ThreadPoolExecutor with timeout to prevent indefinite blocking
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(CANONICAL_WEBUI_RESOURCE_KEYS)
        ) as executor:
            futures = {
                "models": executor.submit(self._classify_pickers, self.list_models, vae=False),
                "vaes": executor.submit(self._classify_pickers, self.list_vaes, vae=True),
                "samplers": executor.submit(self._fetch_samplers),
                "schedulers": executor.submit(self._fetch_schedulers),
                "upscalers": executor.submit(self.list_upscalers),
                "hypernetworks": executor.submit(self.list_hypernetworks),
                "embeddings": executor.submit(self.list_embeddings),
                "adetailer_models": executor.submit(self.list_adetailer_models),
                "adetailer_detectors": executor.submit(self.list_adetailer_detectors),
            }

            results = build_empty_resource_map()
            for key, future in futures.items():
                try:
                    results[key] = future.result(timeout=timeout) or []
                except concurrent.futures.TimeoutError as exc:
                    fallback = self._fallback_for_resource(key)
                    self._log_refresh_failure(key, exc, fallback)
                    results[key] = fallback
                except Exception as exc:
                    fallback = self._fallback_for_resource(key)
                    self._log_refresh_failure(key, exc, fallback)
                    results[key] = fallback

            return results

    def _classify_pickers(self, list_resources: Callable[[], list[Any]], *, vae: bool) -> list[Any]:
        # Reuse the catalog's paths. Only probe an exact direct child when the endpoint supplies a name alone.
        root = self.root_path / "models" / ("VAE" if vae else "Stable-diffusion")
        registry = AssetRegistry(self.root_path)
        result = []
        for entry in list_resources():
            if not isinstance(entry, WebUIResource):
                result.append(entry)
                continue
            raw = entry.raw or {}
            filename = raw.get("path") or raw.get("filename")
            path = None
            try:
                path = Path(filename) if filename else root / Path(entry.name).name
                if filename and not path.is_absolute() and not raw.get("path"):
                    path = root / path
                evidence = registry.inspect_picker_candidate(path, entry.name, vae=vae)
            except (OSError, ValueError, TypeError):
                evidence = PickerEvidence(ComponentEvidence(error="unreadable local catalog entry"))
            if not vae and evidence.component.dependency_bearing:
                variant = classify_flux_variant(evidence.component)
                compatibility = (
                    CompatibilityProfile(
                        CompatibilityStatus.RESOLVED,
                        ModelFamily.FLUX,
                        (),
                        variant.architecture_id,
                    )
                    if variant is not None
                    else None
                )
                if evidence.component.architecture == ARCH_Z_IMAGE_DIT:
                    compatibility = CompatibilityProfile(
                        CompatibilityStatus.RESOLVED, ModelFamily.Z_IMAGE, (), ARCH_Z_IMAGE_DIT
                    )
                elif evidence.component.architecture == ARCH_QWEN_IMAGE_DIT:
                    architecture = (
                        "qwen_image_20b_fp8"
                        if is_qwen_image_20b_fp8(evidence.component)
                        else ARCH_QWEN_IMAGE_DIT
                    )
                    compatibility = CompatibilityProfile(
                        CompatibilityStatus.RESOLVED, ModelFamily.QWEN_IMAGE, (), architecture
                    )
                policy = resolve_model_policy(
                    entry.name, family_lookup=lambda _, compatibility=compatibility: compatibility
                )
                # The dispatch gate already owns the wording and decision for dependency-bearing transformers.
                readiness = assess_model_readiness(
                    entry.name,
                    checkpoint=evidence.component,
                    catalog=None,
                    selected=None,
                    profile_available=policy.qualified,
                )
                refusal = policy.refusal or (
                    " ".join(readiness.reasons) if readiness.blocks_dispatch else ""
                )
                profile = resolve_model_profile_for_policy(policy)
                if isinstance(profile, QwenImageProfile) and profile.structural_transformer:
                    installation = check_installation(profile, model_name=entry.name)
                    if not installation.ready:
                        refusal = installation.summary
                elif isinstance(profile, Flux1Profile) and variant is not None:
                    if variant.precision not in profile.transformer_precisions:
                        refusal = (
                            f"{profile.display_name} cannot use {variant.precision} precision. "
                            f"Select a transformer in one of: {', '.join(profile.transformer_precisions)}."
                        )
                    missing = [
                        asset.filename
                        for asset in profile.modules
                        if not (
                            self.root_path / "models" / asset.models_subdir / asset.filename
                        ).is_file()
                    ]
                    if missing and not refusal:
                        refusal = f"{profile.display_name} needs {', '.join(missing)} in the Forge model folders."
                evidence = replace(evidence, refusal=refusal)
            result.append(replace(entry, picker=replace(evidence, path=path)))
        return result

    def _fetch_samplers(self) -> list[str]:
        if self.client is None:  # filesystem-only mode: samplers are API-only
            return []
        return self._normalize_sampler_names(self.client.get_samplers() or [])

    def _fetch_schedulers(self) -> list[str]:
        """Fetch schedulers while preserving a non-empty compatibility result."""
        if self.client is None:  # filesystem-only mode: schedulers are API-only
            return list(DEFAULT_SCHEDULERS)
        try:
            raw = self.client.get_schedulers()
        except Exception as exc:
            fallback = list(DEFAULT_SCHEDULERS)
            self._log_refresh_failure("schedulers", exc, fallback)
            return fallback

        schedulers = normalize_scheduler_names(raw)
        if schedulers:
            return schedulers
        fallback = list(DEFAULT_SCHEDULERS)
        self._log_refresh_failure(
            "schedulers",
            ValueError("no valid scheduler names in successful response"),
            fallback,
        )
        return fallback

    @staticmethod
    def _fallback_for_resource(key: str) -> list[Any]:
        if key == "schedulers":
            return list(DEFAULT_SCHEDULERS)
        return []

    @staticmethod
    def _log_refresh_failure(key: str, exc: BaseException, fallback: list[Any]) -> None:
        logger.warning(
            "WebUI resource refresh failed resource=%s failure_type=%s reason=%s fallback_used=%s",
            key,
            type(exc).__name__,
            str(exc),
            "yes" if fallback else "no",
        )

    @staticmethod
    def _normalize_sampler_names(data: Iterable[Any]) -> list[str]:
        """Extract sampler names from the API payload into a deduplicated list."""
        seen: set[str] = set()
        values: list[str] = []
        for entry in data:
            name = ""
            if isinstance(entry, dict):
                name = (
                    entry.get("name")
                    or entry.get("label")
                    or entry.get("sampler_name")
                    or entry.get("title")
                    or ""
                )
            else:
                name = str(entry)
            name = name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            values.append(name)
        return values

    def list_adetailer_models(self) -> list[str]:
        getter = getattr(self.client, "get_adetailer_models", None)
        if callable(getter):
            try:
                return [str(item).strip() for item in getter() or [] if str(item).strip()]
            except Exception:
                pass
        return []

    def list_adetailer_detectors(self) -> list[str]:
        getter = getattr(self.client, "get_adetailer_detectors", None)
        if callable(getter):
            try:
                return [str(item).strip() for item in getter() or [] if str(item).strip()]
            except Exception:
                pass
        return []
