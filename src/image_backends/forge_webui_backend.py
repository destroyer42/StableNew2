"""Forge WebUI image backend (PR-IMG-FORGE-100): explicit, non-default ``forge_webui`` identity.

Forge shares StableNew's WebUI-family executor with A1111; the stage translation is inherited from
``WebUIFamilyImageBackend`` unchanged. What makes this a distinct backend is its durable identity,
the ``forge_webui`` runtime-transition target (A1111 and Forge occupy one WebUI-family slot, so the
other identity is released only when StableNew owns it), and the read-only runtime identity guard
that requires a *positively identified* Forge endpoint before any generation dispatch. It never
falls back to A1111 and is never selected for historical records without an image backend.

Capabilities are exactly the four still-image stages StableNew's executor already drives. ControlNet
is deliberately not a StableNew image stage.

Model-specific Forge translation lives here (PR-IMG-116): when ``backend_options.image.model_profile``
names the qualified FLUX.2 Klein 4B FP8 profile, the backend validates the immutable intent against the
profile (rejecting conflicts instead of rewriting them), gates dispatch on host memory, projects the
profile's exact checkpoint/module set and fixed sampling parameters onto the executor config, and
records durable evidence. Work without a model profile (SDXL, ...) takes the inherited path untouched.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.image_backends.forge_klein_profile import (
    MODE_SINGLE_REFERENCE_EDIT,
    KleinProfile,
    KleinProfileError,
    detect_unsupported_features,
    is_klein_transformer_name,
    klein_provenance,
    resolve_model_profile,
    validate_klein_intent,
)
from src.image_backends.forge_klein_readiness import (
    HostMemorySnapshot,
    KleinReadiness,
    check_klein_host_memory,
    read_host_memory,
)
from src.image_backends.image_backend_types import (
    FORGE_IMAGE_BACKEND_ID,
    ImageBackendCapabilities,
    ImageExecutionRequest,
    ImageExecutionResult,
    resolve_image_backend_id,
)
from src.image_backends.webui_family_backend import WebUIFamilyImageBackend
from src.services.runtime_transition_service import (
    RUNTIME_FORGE_WEBUI,
    RuntimeTransitionCoordinator,
)

logger = logging.getLogger(__name__)

_AUTOMATIC_VAE = frozenset({"", "automatic", "none"})
SD_MODULES_ENDPOINT = "/sdapi/v1/sd-modules"


def _name_key(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    return base.rsplit(".", 1)[0] if "." in base else base


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class ForgeWebUIImageBackend(WebUIFamilyImageBackend):
    backend_id = FORGE_IMAGE_BACKEND_ID
    capabilities = ImageBackendCapabilities(
        backend_id=backend_id,
        stage_types=("txt2img", "img2img", "adetailer", "upscale"),
    )
    transition_target = RUNTIME_FORGE_WEBUI

    def __init__(
        self,
        *,
        transition: RuntimeTransitionCoordinator | None = None,
        memory_probe: Callable[[], HostMemorySnapshot] | None = None,
    ) -> None:
        super().__init__(transition=transition)
        self._memory_probe = memory_probe
        self._readiness: dict[str | None, KleinReadiness] = {}

    # ------------------------------------------------------------------ profile validation

    @staticmethod
    def _profile_for(backend_options: Any) -> KleinProfile | None:
        return resolve_model_profile(backend_options)

    @staticmethod
    def _vae_conflict(vae: Any, profile: KleinProfile) -> list[str]:
        name = str(vae or "").strip()
        if name.lower() in _AUTOMATIC_VAE:
            return []
        if name.lower().rsplit(".", 1)[0] == profile.vae.logical_name.lower():
            return []
        return [f"VAE '{name}' (the profile fixes {profile.vae.filename})"]

    @staticmethod
    def _global_term_conflicts(config: Mapping[str, Any]) -> list[str]:
        found: list[str] = []
        for key, label in (
            ("global_positive_prompt", "global positive prompt terms"),
            ("global_negative_prompt", "global negative prompt terms"),
        ):
            if str(config.get(key) or "").strip():
                found.append(label)
        return found

    def validate_njr_intent(self, njr: Any, stage_names: list[str]) -> None:
        backend_options = getattr(njr, "backend_options", None) or {}
        profile = self._profile_for(backend_options)
        if profile is None:
            return
        config = getattr(njr, "config", None) or {}
        config = config if isinstance(config, Mapping) else {}
        features = (
            detect_unsupported_features(config, positive_prompt=str(njr.positive_prompt or ""))
            + self._vae_conflict(getattr(njr, "vae", None), profile)
            + self._global_term_conflicts(config)
        )
        input_images = tuple(getattr(njr, "input_image_paths", ()) or ())
        mode = validate_klein_intent(
            profile,
            backend_id=resolve_image_backend_id(backend_options),
            stage_names=stage_names,
            model_name=str(getattr(njr, "base_model", "") or ""),
            sampler=getattr(njr, "sampler_name", None),
            scheduler=getattr(njr, "scheduler", None),
            steps=getattr(njr, "steps", None),
            cfg_scale=getattr(njr, "cfg_scale", None),
            width=getattr(njr, "width", None),
            height=getattr(njr, "height", None),
            negative_prompt=getattr(njr, "negative_prompt", None),
            unsupported_features=features,
        )
        expected_inputs = 1 if mode == MODE_SINGLE_REFERENCE_EDIT else 0
        if len(input_images) != expected_inputs:
            raise KleinProfileError(
                f"{profile.display_name} {mode} needs exactly {expected_inputs} source image(s); "
                f"this job has {len(input_images)} (multi-reference is not supported)."
            )

    def _validate_request(self, request: ImageExecutionRequest) -> None:
        profile = self._profile_for(request.backend_options)
        if profile is None:
            return
        features = (
            detect_unsupported_features(request.execution_config, positive_prompt=request.prompt)
            + self._vae_conflict(request.selected_vae, profile)
            + self._global_term_conflicts(request.execution_config)
        )
        if int(request.image_count or 1) != 1:
            features.append(f"image count {request.image_count}")
        validate_klein_intent(
            profile,
            backend_id=request.backend_id,
            stage_names=(request.stage_name,),
            model_name=request.selected_model or "",
            sampler=request.sampler,
            scheduler=request.scheduler,
            steps=request.steps,
            cfg_scale=request.cfg_scale,
            width=request.width,
            height=request.height,
            negative_prompt=request.negative_prompt,
            unsupported_features=features,
        )

    def _before_dispatch(self, pipeline: Any, request: ImageExecutionRequest) -> None:
        profile = self._profile_for(request.backend_options)
        if profile is None:
            return
        self._readiness[request.job_id] = check_klein_host_memory(
            profile, probe=self._memory_probe or read_host_memory
        )
        self._assert_assets_listed(pipeline, profile)

    @staticmethod
    def _assert_assets_listed(pipeline: Any, profile: KleinProfile) -> None:
        """Read-only: refuse before any write if Forge does not list the exact installed assets.

        The executor swallows stage exceptions into a generic "no images" failure, so the actionable
        reason (what is missing and how to install it) is raised here, before anything is selected.
        """

        client = getattr(pipeline, "client", None)
        install_hint = (
            "Install the exact qualified files with scripts/install_forge_klein_assets.ps1 "
            "(-SourceDir <folder holding them>)."
        )
        list_modules = getattr(client, "get_vae_models", None)
        if callable(list_modules):
            listed = {_name_key(str(m.get("model_name") or "")) for m in list_modules() or []}
            missing = [a.filename for a in profile.modules if _name_key(a.filename) not in listed]
            if missing:
                raise KleinProfileError(
                    f"Forge does not list the required module(s) {missing} ({SD_MODULES_ENDPOINT}). "
                    + install_hint
                )
        list_models = getattr(client, "get_models", None)
        models = list_models() if callable(list_models) else []
        if models and not any(
            is_klein_transformer_name(str(entry.get(key) or ""))
            for entry in models
            for key in ("title", "model_name", "filename")
        ):
            raise KleinProfileError(
                f"Forge does not list the checkpoint {profile.transformer.filename}. " + install_hint
            )

    # ------------------------------------------------------------------ projection

    def _finalize_config(
        self, request: ImageExecutionRequest, config: dict[str, Any]
    ) -> dict[str, Any]:
        profile = self._profile_for(request.backend_options)
        if profile is None:
            return config
        projected = dict(config)
        for key in ("vae", "sd_vae", "vae_name"):
            projected.pop(key, None)
        pipeline = dict(projected.get("pipeline") or {})
        for key in (
            "apply_global_positive_txt2img",
            "apply_global_negative_txt2img",
            "apply_global_negative_img2img",
        ):
            pipeline[key] = False
        projected.update(
            model=profile.transformer.filename,
            sd_model_checkpoint=profile.transformer.filename,
            sampler_name=profile.sampler,
            scheduler=profile.scheduler,
            steps=profile.steps,
            cfg_scale=profile.cfg_scale,
            negative_prompt="",
            additional_modules=[asset.filename for asset in profile.modules],
            prompt_optimizer={"enabled": False},
            pipeline=pipeline,
            global_positive_prompt="",
            global_negative_prompt="",
            global_prompt_policy_source="frozen_njr",
        )
        if request.stage_name == "img2img":
            for key in ("mask_image_path", "mask_path", "negative_adjust", "prompt_adjust"):
                projected.pop(key, None)
            projected.update(
                denoising_strength=profile.edit_denoising_strength,
                width=request.width,
                height=request.height,
            )
        return projected

    # ------------------------------------------------------------------ evidence

    def execute(self, pipeline: Any, request: ImageExecutionRequest) -> ImageExecutionResult | None:
        result = super().execute(pipeline, request)
        profile = self._profile_for(request.backend_options)
        readiness = self._readiness.pop(request.job_id, None)
        if profile is None or result is None:
            return result
        mode = (
            MODE_SINGLE_REFERENCE_EDIT if request.stage_name == "img2img" else request.stage_name
        )
        evidence = klein_provenance(profile, mode=mode)
        if readiness is not None:
            evidence["host_memory_before_dispatch"] = readiness.as_dict()
        evidence["observed"] = self._observe(pipeline)
        if request.stage_name == "img2img" and request.input_image_path is not None:
            source = Path(request.input_image_path)
            evidence["source_image"] = {
                "name": source.name,
                "sha256": _sha256_file(source) if source.is_file() else None,
            }
        result.backend_metadata["klein_profile"] = evidence
        return result

    @staticmethod
    def _observe(pipeline: Any) -> dict[str, Any]:
        """Read-only record of what Forge reports as active after the run (never raises)."""

        client = getattr(pipeline, "client", None)
        observed: dict[str, Any] = {}
        try:
            getter = getattr(client, "get_additional_modules", None)
            observed["modules"] = getter() if callable(getter) else None
            model = getattr(client, "get_current_model", None)
            observed["checkpoint"] = model() if callable(model) else None
        except Exception:
            logger.debug("Could not read Forge's active Klein modules", exc_info=True)
        return observed
