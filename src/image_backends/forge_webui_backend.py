"""Forge WebUI image backend (PR-IMG-FORGE-100): the ``forge_webui`` identity, the new-work default (PR-IMG-FORGE-120).

Forge shares StableNew's WebUI-family executor with A1111; the stage translation is inherited from
``WebUIFamilyImageBackend`` unchanged. What makes this a distinct backend is its durable identity,
the ``forge_webui`` runtime-transition target (A1111 and Forge occupy one WebUI-family slot, so the
other identity is released only when StableNew owns it), and the read-only runtime identity guard
that requires a *positively identified* Forge endpoint before any generation dispatch. It never
falls back to A1111 and is never selected for historical records without an image backend (those resolve
to A1111, ``LEGACY_MISSING_IMAGE_BACKEND_ID``); only newly constructed work defaults to it.

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
from src.api.webui_identity_attestation import ManagedWebUIIdentityAttestor
from src.image_backends.forge_klein_assets import _active_manager, verify_klein_assets
from src.image_backends.forge_klein_lora import (
    KleinLoraDecision,
    LoraResolver,
    LoraTag,
    RegistryLoraResolver,
    evaluate_klein_loras,
    observe_lora_consumption,
)
from src.image_backends.forge_klein_profile import (
    EDIT_STAGE_CHAIN,
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


class ForgeUnsupportedIntentError(ValueError):
    """The job asks for something the Forge runtime cannot do; refused before any dispatch."""


_HYPERNETWORK_SECTIONS = ("txt2img", "img2img", "adetailer", "upscale")  # the image stages, as config sections and stage types


def requested_hypernetworks(config: Mapping[str, Any] | None) -> list[str]:
    """Hypernetworks a run config asks for: a stage or top-level ``hypernetwork`` that is not none, or a sweep entry."""

    data = config if isinstance(config, Mapping) else {}

    def active(value: Any) -> str:
        text = str(value or "").strip()
        return "" if text.lower() in {"", "none"} else text

    found: list[str] = []
    if active(data.get("hypernetwork")):
        found.append(active(data.get("hypernetwork")))
    for section in _HYPERNETWORK_SECTIONS:
        stage = data.get(section)
        if isinstance(stage, Mapping) and active(stage.get("hypernetwork")):
            found.append(f"{active(stage.get('hypernetwork'))} ({section})")
    pipeline = data.get("pipeline")
    for entry in (pipeline.get("hypernetworks") if isinstance(pipeline, Mapping) else None) or []:
        name = entry.get("name") if isinstance(entry, Mapping) else entry
        if active(name):
            found.append(f"{active(name)} (randomizer sweep)")
    return found


def requested_hypernetworks_for_njr(njr: Any) -> list[str]:
    """Hypernetwork intent anywhere the immutable NJR can execute it.

    ``PipelineRunner`` serializes each ``StageConfig`` and the executor config flattens its ``extra``, so an enabled image
    stage's ``extra`` is read exactly like the run config (``requested_hypernetworks`` is the single rule for both).
    """

    found = requested_hypernetworks(getattr(njr, "config", None))
    for stage in getattr(njr, "stage_chain", None) or ():
        stage_type = str(getattr(stage, "stage_type", "") or "")
        if not getattr(stage, "enabled", False) or stage_type not in _HYPERNETWORK_SECTIONS:
            continue  # a disabled stage is never dispatched; non-image stages are not this backend's
        found.extend(f"{item} ({stage_type} stage extra)" for item in requested_hypernetworks(getattr(stage, "extra", None)))
    return found


class ForgeWebUIImageBackend(WebUIFamilyImageBackend):
    backend_id = FORGE_IMAGE_BACKEND_ID
    capabilities = ImageBackendCapabilities(
        backend_id=backend_id,
        stage_types=("txt2img", "img2img", "adetailer", "upscale"),
        supports_hypernetworks=False,  # the pinned Forge Neo removed Hypernetworks
    )
    transition_target = RUNTIME_FORGE_WEBUI

    def __init__(
        self,
        *,
        transition: RuntimeTransitionCoordinator | None = None,
        memory_probe: Callable[[], HostMemorySnapshot] | None = None,
        lora_resolver: LoraResolver | None = None,
        identity_attestor: ManagedWebUIIdentityAttestor | None = None,
    ) -> None:
        super().__init__(transition=transition, identity_attestor=identity_attestor)
        self._memory_probe = memory_probe
        self._lora_resolver = lora_resolver
        self._lora_evidence: dict[
            str | None, tuple[tuple[KleinLoraDecision, ...], tuple[LoraTag, ...]]
        ] = {}
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

    def _resolver(self) -> LoraResolver:
        if self._lora_resolver is None:
            self._lora_resolver = RegistryLoraResolver()
        return self._lora_resolver

    def _lora_conflicts(
        self,
        profile: KleinProfile,
        *,
        stage_names: Any,
        prompt: str,
        config: Mapping[str, Any],
        declared: Any = (),
    ) -> tuple[list[str], tuple[KleinLoraDecision, ...], tuple[LoraTag, ...]]:
        """Profile v2 only: the one-compatible-LoRA contract (v1 rejects every LoRA via the feature list)."""

        if profile.max_loras <= 0:
            return [], (), ()
        problems, decisions, tags = evaluate_klein_loras(
            max_loras=profile.max_loras,
            prompt=prompt,
            declared=tuple((str(tag.name), float(tag.weight)) for tag in declared or ()),
            lora_strength_overrides=bool(config.get("lora_strengths")),
            resolver=self._resolver(),
        )
        if tags and tuple(str(stage) for stage in stage_names) == EDIT_STAGE_CHAIN:
            problems.append("a LoRA with a single-reference edit is not qualified (text-to-image only)")
        return problems, decisions, tags

    def validate_njr_intent(self, njr: Any, stage_names: list[str]) -> None:
        backend_options = getattr(njr, "backend_options", None) or {}
        config = getattr(njr, "config", None) or {}
        config = config if isinstance(config, Mapping) else {}
        hypernetworks = requested_hypernetworks_for_njr(njr)
        if hypernetworks and not self.capabilities.supports_hypernetworks:
            raise ForgeUnsupportedIntentError(
                "Hypernetworks are not supported by the Forge runtime (the pinned Forge Neo removed them), but this job "
                f"requests: {', '.join(hypernetworks)}. Generation was not dispatched. Remove the hypernetwork, or "
                "select the A1111 compatibility runtime (webui_runtime_identity = a1111_webui) to use it."
            )
        profile = self._profile_for(backend_options)
        if profile is None:
            return
        lora_problems, _decisions, _tags = self._lora_conflicts(
            profile,
            stage_names=stage_names,
            prompt=str(njr.positive_prompt or ""),
            config=config,
            declared=getattr(njr, "lora_tags", ()),
        )
        features = (
            detect_unsupported_features(
                config,
                positive_prompt=str(njr.positive_prompt or ""),
                lora_admitted=profile.max_loras > 0,
            )
            + self._vae_conflict(getattr(njr, "vae", None), profile)
            + self._global_term_conflicts(config)
            + lora_problems
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
        lora_problems, decisions, tags = self._lora_conflicts(
            profile,
            stage_names=(request.stage_name,),
            prompt=request.prompt,
            config=request.execution_config,
        )
        features = (
            detect_unsupported_features(
                request.execution_config,
                positive_prompt=request.prompt,
                lora_admitted=profile.max_loras > 0,
            )
            + self._vae_conflict(request.selected_vae, profile)
            + self._global_term_conflicts(request.execution_config)
            + lora_problems
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
        if tags:
            self._lora_evidence[request.job_id] = (decisions, tags)

    # ------------------------------------------------------------------ served-LoRA binding (PR-IMG-117)

    def _assert_lora_served(self, pipeline: Any, request: ImageExecutionRequest) -> dict[str, Any]:
        """Forge itself must list the admitted adapter, and serve the file the registry identified.

        Read-only. The registry's SHA-256 identity is the only byte authority; this binds it to the file the
        serving Forge reports (a same-named different file is refused), without a second hashing authority.
        """

        _decisions, tags = self._lora_evidence.get(request.job_id, ((), ()))
        client = getattr(pipeline, "client", None)
        lister = getattr(client, "get_loras", None)
        if not callable(lister):
            raise KleinProfileError(
                "This Forge client cannot list LoRAs; refusing to dispatch a LoRA job without confirming "
                "Forge serves the adapter."
            )
        listed = lister()
        if not isinstance(listed, list):
            raise KleinProfileError(
                "Forge's LoRA listing could not be read; refusing to dispatch a LoRA job."
            )
        locator = getattr(self._resolver(), "locations_for", None)
        served: dict[str, Any] = {}
        for tag in tags:
            key = tag.name.strip().lower()
            entry = next(
                (
                    item
                    for item in listed
                    if key in {str(item.get("name") or "").lower(), str(item.get("alias") or "").lower()}
                ),
                None,
            )
            if entry is None:
                raise KleinProfileError(
                    f"Forge does not list the LoRA '{tag.name}'. Place the file where the managed Forge reads "
                    "LoRAs (and restart or refresh Forge) before submitting."
                )
            forge_path = str(entry.get("path") or "")
            bound = None
            if forge_path and callable(locator):
                wanted = {os.path.normcase(os.path.realpath(p)) for p in locator(tag.name)}
                bound = os.path.normcase(os.path.realpath(forge_path)) in wanted
                if not bound:
                    raise KleinProfileError(
                        f"Forge serves the LoRA '{tag.name}' from a different file than StableNew's local asset "
                        "identity (same name, different path); refusing to dispatch."
                    )
            served[tag.name] = {"listed": True, "path_bound_to_registry_identity": bound}
        return served

    @staticmethod
    def _lora_log_observation(tag: LoraTag) -> dict[str, Any]:
        """Forge's own log line for applying the adapter, via the existing manager's output tail (never raises)."""

        try:
            manager = _active_manager()
            tail = manager.get_recent_output_tail(max_lines=400) if manager is not None else {}
            lines = str(tail.get("stdout_tail") or "").splitlines() + str(
                tail.get("stderr_tail") or ""
            ).splitlines()
            return observe_lora_consumption(lines, tag.name)
        except Exception:
            logger.debug("Could not read Forge's LoRA log lines", exc_info=True)
            return {"consumed": None, "source": "unavailable"}

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
        if self._lora_evidence.get(request.job_id, ((), ()))[1]:
            self._identity[request.job_id]["lora_served"] = self._assert_lora_served(pipeline, request)
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
                self._lora_evidence,
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
        lora_state = self._lora_evidence.pop(request.job_id, ((), ()))
        if profile is None or result is None:
            return result
        mode = (
            MODE_SINGLE_REFERENCE_EDIT if request.stage_name == "img2img" else request.stage_name
        )
        lora_block = self._lora_block(lora_state, identity)
        if lora_block is not None and lora_block["observation"].get("consumed") is False:
            raise KleinProfileError(
                f"Forge did not apply the LoRA '{lora_block['name']}' to this model "
                f"({lora_block['observation'].get('line', 'adapter keys did not match')}); the generated image "
                "does not reflect the requested LoRA, so the job is failed rather than recorded as a LoRA result."
            )
        evidence = klein_provenance(profile, mode=mode, lora=lora_block)
        if readiness is not None:
            evidence["host_memory_before_dispatch"] = readiness.as_dict()
        evidence["observed"] = self._observe(pipeline)  # Forge's reported names: supplementary evidence
        if identity is not None:
            evidence["asset_identity"] = identity  # local size + SHA-256 of the files Forge loads
        if verified_source is not None:
            evidence["source_image"] = verified_source
        result.backend_metadata["klein_profile"] = evidence
        return result

    def _lora_block(
        self,
        lora_state: tuple[tuple[KleinLoraDecision, ...], tuple[LoraTag, ...]],
        identity: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Machine-path-free LoRA evidence: logical name, weight, SHA-256, compatibility decision, observation."""

        decisions, tags = lora_state
        if not tags:
            return None
        tag, decision = tags[0], decisions[0]
        return {
            "name": tag.name,
            "requested_weight": tag.weight,
            "sha256": decision.sha256,
            "compatibility": {
                "status": decision.status.value,
                "evidence_source": decision.evidence_source,
                "evidence_raw_value": decision.evidence_raw_value,
            },
            "served": ((identity or {}).get("lora_served") or {}).get(tag.name),
            "observation": self._lora_log_observation(tag),
        }

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
