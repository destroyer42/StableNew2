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
records durable evidence. Work without a model profile (SDXL, ...) takes the inherited stage path, preceded by a module-baseline
check (PR-IMG-FORGE-D110): Forge persists ``forge_additional_modules`` across jobs, so a previous Klein
job's text encoder/VAE would otherwise be applied to an ordinary checkpoint. Every such stage reads the
endpoint's module selection and, only when it is a non-empty selection that differs from what the work
needs (nothing for Automatic VAE, exactly the requested VAE otherwise), writes and verifies the needed set
through the existing ``ForgeWebUIClient`` module API before the stage can load a model. Unreadable or
unverifiable state refuses the stage; nothing depends on a previous job's cleanup.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.api.forge_client import ForgeVAEError, module_set_key
from src.image_backends.forge_klein_assets import verify_klein_assets
from src.image_backends.forge_klein_profile import (
    KLEIN_EDIT_METADATA_KEY,
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
from src.utils.webui_resource_names import normalize_vae_config_value

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
        self._identity: dict[str | None, dict[str, Any]] = {}
        self._verified_source: dict[str | None, dict[str, Any]] = {}
        self._module_baseline: dict[str | None, dict[str, Any]] = {}

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

    # ------------------------------------------------------------------ module baseline (D110)

    def _requested_vae(self, request: ImageExecutionRequest) -> str:
        """The VAE the executor will be asked for on this stage ("" means Automatic)."""

        if request.stage_name == "txt2img":
            config = self._txt2img_executor_config(request)
        else:
            config = self._stage_executor_config(request)
        return normalize_vae_config_value(
            config.get("vae") if "vae" in config else config.get("vae_name")
        )

    def _normalize_module_baseline(
        self, pipeline: Any, request: ImageExecutionRequest
    ) -> dict[str, Any]:
        """Ordinary (non-Klein) Forge work must not inherit a previous job's persisted modules.

        Forge keeps ``forge_additional_modules`` until something overwrites it, and the executor's
        in-memory VAE cache cannot see a selection written by an earlier job or process. Read the
        endpoint's real selection before any model transition; a non-empty selection that is not
        exactly what this work needs (nothing for Automatic, the requested VAE otherwise) is replaced
        through the existing verified module write. An empty selection is left alone (an explicit VAE
        is then selected by the executor's normal path). Unreadable or unverifiable state refuses
        the stage before any dispatch; nothing is guessed and Forge is never restarted or edited.
        """

        client = getattr(pipeline, "client", None)
        reader = getattr(client, "get_additional_modules", None)
        setter = getattr(client, "set_additional_modules", None)
        if not callable(reader) or not callable(setter):
            raise ForgeVAEError(
                "This Forge client cannot read and select the module set; refusing to dispatch "
                f"{request.stage_name} without a verified module baseline."
            )
        observed = reader()
        if not isinstance(observed, list):
            raise ForgeVAEError(
                "Forge's current module selection could not be read; refusing to dispatch "
                f"{request.stage_name} without a verified module baseline."
            )
        requested_vae = self._requested_vae(request)
        desired = [requested_vae] if requested_vae else []
        event: dict[str, Any] = {
            "stage": request.stage_name,
            "observed_before": list(observed),
            "required": desired,
            "applied": False,
        }
        if not observed or module_set_key(observed) == module_set_key(desired):
            return event
        logger.warning(
            "[forge/module-baseline] stage=%s endpoint reports persistent modules %s; selecting %s "
            "before any model load",
            request.stage_name,
            observed,
            desired or "Automatic (no modules)",
        )
        if setter(list(desired)) is not True:
            raise ForgeVAEError(
                f"Forge module selection {desired or 'Automatic'} was not applied; refusing to dispatch "
                f"{request.stage_name} with stale modules {observed}."
            )
        after = reader()
        if not isinstance(after, list) or module_set_key(after) != module_set_key(desired):
            raise ForgeVAEError(
                f"Forge reports modules {after} after selecting {desired or 'Automatic'}; refusing to "
                f"dispatch {request.stage_name} with an unverified module baseline."
            )
        event["applied"] = True
        event["observed_after"] = list(after)
        return event

    def _before_dispatch(self, pipeline: Any, request: ImageExecutionRequest) -> None:
        profile = self._profile_for(request.backend_options)
        if profile is None:
            if request.stage_name in self.capabilities.stage_types:
                self._module_baseline[request.job_id] = self._normalize_module_baseline(
                    pipeline, request
                )
            return
        self._readiness[request.job_id] = check_klein_host_memory(
            profile, probe=self._memory_probe or read_host_memory
        )
        # What Forge will load, by bytes: the API names below are only supplementary evidence of selection.
        endpoint = str(getattr(getattr(pipeline, "client", None), "base_url", "") or "")
        self._identity[request.job_id] = verify_klein_assets(profile, endpoint=endpoint)
        self._assert_assets_listed(pipeline, profile)
        if request.stage_name == "img2img":
            self._verified_source[request.job_id] = self._verify_frozen_source(request)

    @staticmethod
    def _verify_frozen_source(request: ImageExecutionRequest) -> dict[str, Any]:
        """The source image must still be exactly the one frozen at Review admission (never refreshed)."""

        if request.input_image_path is None:
            raise KleinProfileError("A Klein edit needs its source image.")
        source = Path(request.input_image_path)
        wanted = os.path.normcase(os.path.abspath(source))
        provenance = request.context_metadata.get("provenance") or {}
        frozen = ""
        for item in (provenance.get("reprocess") or {}).get("source_items") or []:
            if os.path.normcase(os.path.abspath(str(item.get("input_image_path") or ""))) == wanted:
                marker = (item.get("metadata") or {}).get(KLEIN_EDIT_METADATA_KEY)
                frozen = str(marker.get("source_image_sha256") or "") if isinstance(marker, dict) else ""
                break
        if not frozen:
            raise KleinProfileError(
                "The job does not carry the frozen SHA-256 of its Klein source image; refusing to edit an unverified source."
            )
        if not source.is_file():
            raise KleinProfileError(f"The Klein edit source image is missing: {source.name}")
        actual = _sha256_file(source)
        if actual != frozen:
            raise KleinProfileError(
                f"The Klein edit source image {source.name} changed after the job was admitted "
                f"(frozen SHA-256 {frozen}, current {actual}); refusing to dispatch."
            )
        return {"name": source.name, "sha256": actual, "frozen_sha256": frozen, "verified_before_dispatch": True}

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
        try:
            result = super().execute(pipeline, request)
        except BaseException:
            for scratch in (
                self._readiness,
                self._identity,
                self._verified_source,
                self._module_baseline,
            ):
                scratch.pop(request.job_id, None)
            raise
        profile = self._profile_for(request.backend_options)
        baseline = self._module_baseline.pop(request.job_id, None)
        if profile is None and result is not None and baseline is not None:
            result.backend_metadata["forge_module_baseline"] = baseline
        readiness = self._readiness.pop(request.job_id, None)
        identity = self._identity.pop(request.job_id, None)
        verified_source = self._verified_source.pop(request.job_id, None)
        if profile is None or result is None:
            return result
        mode = (
            MODE_SINGLE_REFERENCE_EDIT if request.stage_name == "img2img" else request.stage_name
        )
        evidence = klein_provenance(profile, mode=mode)
        if readiness is not None:
            evidence["host_memory_before_dispatch"] = readiness.as_dict()
        evidence["observed"] = self._observe(pipeline)  # Forge's reported names: supplementary evidence
        if identity is not None:
            evidence["asset_identity"] = identity  # local size + SHA-256 of the files Forge loads
        if verified_source is not None:
            evidence["source_image"] = verified_source
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
