"""Typed, StableNew-owned contracts for still-image execution backends."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.pipeline.artifact_contract import (
    ARTIFACT_SCHEMA_VERSION,
    build_artifact_record,
    canonicalize_variant_entry,
    extract_artifact_paths,
)

#: Durable image backend identities. They are two backends behind the existing one-backend-per-image-NJR boundary and
#: share one WebUI-family runtime slot (one endpoint, one ``WebUIProcessManager``).
A1111_IMAGE_BACKEND_ID = "a1111_webui"
FORGE_IMAGE_BACKEND_ID = "forge_webui"
#: The Diffusers runtime family (PR-IMG-120): a contained child per job, selected only by a model that requires it.
DIFFUSERS_IMAGE_BACKEND_ID = "diffusers"
#: The Comfy still-image backend (PR-IMG-COMFY-100): StableNew's managed ComfyUI, selected by a model that requires it
#: (the frozen Qwen-Image 2.1 profiles) or by the operator's ``image_backend_default`` setting (PR-IMG-COMFY-381, SDXL
#: txt2img); never a fallback target.
COMFY_IMAGE_BACKEND_ID = "comfyui"
#: ``ImageBackendCapabilities.runtime_family`` values.
RUNTIME_FAMILY_WEBUI = "webui"
RUNTIME_FAMILY_DIFFUSERS = "diffusers"
RUNTIME_FAMILY_COMFY = "comfy"

#: The product default for NEW still-image work when no explicit runtime identity is configured (PR-IMG-FORGE-120).
NEW_IMAGE_BACKEND_DEFAULT_ID = FORGE_IMAGE_BACKEND_ID
#: The bounded compatibility rule for HISTORICAL records that predate image backend identity: a missing or blank
#: ``backend_options.image.backend_id`` was A1111 when it was persisted and still resolves to A1111. It is deliberately
#: not the new-work default, so persisted work is never reinterpreted.
LEGACY_MISSING_IMAGE_BACKEND_ID = A1111_IMAGE_BACKEND_ID


#: The persisted setting (PR-IMG-COMFY-381) that picks the still-image backend NEW work defaults to. It is separate from
#: ``webui_runtime_identity`` (which names the WebUI process slot and needs a restart): ``webui`` (also blank/absent) follows
#: that identity, today's behavior; ``comfyui`` makes StableNew's managed ComfyUI the default for new work.
IMAGE_BACKEND_DEFAULT_SETTING = "image_backend_default"
IMAGE_BACKEND_DEFAULT_WEBUI = "webui"
IMAGE_BACKEND_DEFAULT_COMFYUI = "comfyui"
IMAGE_BACKEND_DEFAULT_CHOICES = (IMAGE_BACKEND_DEFAULT_WEBUI, IMAGE_BACKEND_DEFAULT_COMFYUI)


def normalize_image_backend_default(value: Any) -> str:
    """A known ``image_backend_default`` value; blank/absent is ``webui``. An unknown value fails closed (no fallback)."""

    text = str(value or "").strip().lower()
    if not text:
        return IMAGE_BACKEND_DEFAULT_WEBUI
    if text not in IMAGE_BACKEND_DEFAULT_CHOICES:
        from src.api.webui_runtime_identity import WebUIRuntimeConfigurationError

        raise WebUIRuntimeConfigurationError(
            f"Unknown {IMAGE_BACKEND_DEFAULT_SETTING} '{value}'; expected one of "
            f"{list(IMAGE_BACKEND_DEFAULT_CHOICES)}. Fix it in Settings; no backend fallback is performed."
        )
    return text


#: Idle grace (seconds) the managed ComfyUI stays resident after a successful still-image job so the next ComfyUI image job
#: skips the cold start and model load (PR-IMG-COMFY-382). ``0`` restores release-after-every-job. The hold always ends
#: earlier when any other job prepares a runtime, on failure, and at application shutdown.
COMFY_IMAGE_KEEP_WARM_SETTING = "comfy_image_keep_warm_seconds"
COMFY_IMAGE_KEEP_WARM_DEFAULT_SECONDS = 60.0
COMFY_IMAGE_KEEP_WARM_MAX_SECONDS = 3600.0


def normalize_comfy_image_keep_warm_seconds(value: Any) -> float:
    """A bounded idle grace; absent, blank, non-numeric or negative values mean the default or none, never an error."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return COMFY_IMAGE_KEEP_WARM_DEFAULT_SECONDS
    if isinstance(value, bool):
        return 0.0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if seconds != seconds or seconds <= 0:  # NaN or non-positive: no hold
        return 0.0
    return min(seconds, COMFY_IMAGE_KEEP_WARM_MAX_SECONDS)


def configured_comfy_image_keep_warm_seconds() -> float:
    """The configured idle grace for a held ComfyUI image runtime. Unreadable settings mean no hold (release as before)."""

    try:
        from src.api.webui_runtime_identity import load_backend_settings

        return normalize_comfy_image_keep_warm_seconds(
            load_backend_settings().get(COMFY_IMAGE_KEEP_WARM_SETTING)
        )
    except Exception:  # noqa: BLE001 - holding a GPU runtime is optional; never block a job on it
        return 0.0


def configured_webui_image_backend_id() -> str:
    """The configured WebUI-family identity: ``forge_webui`` (the product default) unless the operator explicitly
    selected the ``a1111_webui`` rollback (``webui_runtime_identity``). An unrecognized or unreadable configuration
    raises ``WebUIRuntimeConfigurationError`` instead of selecting either one."""

    from src.api.webui_runtime_identity import (
        load_backend_settings,
        resolve_configured_webui_runtime_identity,
    )

    return resolve_configured_webui_runtime_identity(load_backend_settings())


def configured_image_backend_id() -> str:
    """The still-image backend NEW work is constructed for when nothing more specific names one.

    ``image_backend_default = "comfyui"`` selects the managed ComfyUI backend; otherwise (the default) the configured
    WebUI-family identity, Forge unless the operator selected the A1111 rollback. This is a global default, not per-job
    runtime switching: an explicit job identity and a model-required backend (Qwen, Ideogram) still win, there is no
    fallback between backends, and unreadable or unknown backend configuration raises instead of selecting either one.
    """

    from src.api.webui_runtime_identity import (
        load_backend_settings,
        resolve_configured_webui_runtime_identity,
    )

    settings = load_backend_settings()
    if (
        normalize_image_backend_default(settings.get(IMAGE_BACKEND_DEFAULT_SETTING))
        == IMAGE_BACKEND_DEFAULT_COMFYUI
    ):
        return COMFY_IMAGE_BACKEND_ID
    return resolve_configured_webui_runtime_identity(settings)


def normalize_image_backend_options(
    existing_options: Any,
    *,
    backend_id: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Persist explicit backend identity for newly constructed image work.

    ``model_name`` (the selected checkpoint) stamps the qualified FLUX.2 Klein ``model_profile``
    reference for new work; it is a no-op for every other model and never overwrites an explicit
    profile.

    This is intentionally a construction-time operation.  The execution
    resolver remains the sole compatibility authority for historical records
    which were persisted before image backend identity existed.
    """

    if existing_options is None:
        options: dict[str, Any] = {}
    elif isinstance(existing_options, Mapping):
        options = dict(existing_options)
    else:
        raise ValueError("backend_options must be a mapping for image work")

    image_options = options.get("image")
    if image_options is None:
        image = {}
    elif isinstance(image_options, Mapping):
        image = dict(image_options)
    else:
        raise ValueError("backend_options.image must be a mapping")

    if backend_id is None and "backend_id" not in image and model_name:
        # A model that exists only behind a non-WebUI runtime (PR-IMG-120) names that runtime for new work.
        from src.image_backends.model_backend_routing import required_backend_for_model

        backend_id = required_backend_for_model(model_name)
    if backend_id is None:
        # Only a construction with no explicit identity consults the configured default; an explicit identity in the
        # options (including a replay or reprocess source) is kept and never rewritten.
        backend_id = (
            configured_image_backend_id()
            if "backend_id" not in image
            else NEW_IMAGE_BACKEND_DEFAULT_ID
        )
    explicit_backend_id = image.get("backend_id", backend_id)
    if not isinstance(explicit_backend_id, str):
        raise ValueError("backend_options.image.backend_id must be a string")
    normalized_backend_id = explicit_backend_id.strip() or backend_id
    if not normalized_backend_id:
        raise ValueError("backend_options.image.backend_id must not be blank")
    image["backend_id"] = normalized_backend_id
    if model_name and "model_profile" not in image:
        from src.image_backends.exact_model_profile import model_profile_for_model

        profile_reference = model_profile_for_model(model_name)
        if profile_reference is not None:
            image["model_profile"] = profile_reference
    options["image"] = image
    return options


def resolve_image_backend_id(backend_options: Any) -> str:
    """Resolve the identity of a PERSISTED record: the sole bounded historical compatibility default.

    Missing or blank identity is A1111 (``LEGACY_MISSING_IMAGE_BACKEND_ID``), never the new-work default.
    """

    options = dict(backend_options or {}) if isinstance(backend_options, Mapping) else {}
    image_options = options.get("image")
    if not isinstance(image_options, Mapping):
        return LEGACY_MISSING_IMAGE_BACKEND_ID
    backend_id = str(image_options.get("backend_id") or "").strip()
    return backend_id or LEGACY_MISSING_IMAGE_BACKEND_ID


@dataclass(frozen=True, slots=True)
class ImageBackendCapabilities:
    backend_id: str
    stage_types: tuple[str, ...]
    requires_input_image: bool = False
    supports_prompt_text: bool = True
    supports_negative_prompt: bool = True
    artifact_type: str = "image"
    #: False for a runtime that has no Hypernetwork support (the pinned Forge Neo removed them): such work is refused
    #: before dispatch and the Randomizer does not present the feature.
    supports_hypernetworks: bool = True
    #: True only for a runtime that can execute a pre-rendered OpenPose ControlNet unit on the base txt2img stage
    #: (PR-IMG-CNET-210). Anything else refuses such work before dispatch rather than silently dropping it.
    supports_openpose_conditioning: bool = False
    #: True only for a runtime that can run ADetailer's masked passes without a whole-image img2img and return the
    #: masks it used (the StableNew companion extension in the managed Forge runtime). A ``localized_only`` ADetailer
    #: stage is refused everywhere else; it never degrades to the whole-image request.
    supports_localized_adetailer: bool = False
    #: The runtime family behind the backend. Only ``webui`` backends use the shared WebUI client (for example the
    #: runner's pre-job WebUI memory cleanup); other families own their runtime entirely inside ``execute``.
    runtime_family: str = RUNTIME_FAMILY_WEBUI


@dataclass(slots=True)
class ImageExecutionRequest:
    backend_id: str
    stage_name: str
    stage_config: dict[str, Any]
    output_dir: Path
    input_image_path: Path | None = None
    image_name: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    selected_model: str | None = None
    selected_vae: str | None = None
    sampler: str | None = None
    scheduler: str | None = None
    steps: int | None = None
    cfg_scale: float | None = None
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    image_count: int = 1
    learning_sample_names: bool = False
    execution_config: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    backend_options: dict[str, Any] = field(default_factory=dict)
    cancel_token: Any = None
    context_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImageExecutionResult:
    backend_id: str
    stage_name: str
    primary_path: str | None
    output_paths: list[str] = field(default_factory=list)
    manifest_path: str | None = None
    thumbnail_path: str | None = None
    artifact: dict[str, Any] = field(default_factory=dict)
    raw_result: dict[str, Any] = field(default_factory=dict)
    backend_metadata: dict[str, Any] = field(default_factory=dict)
    diagnostic_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_stage_result(
        cls,
        *,
        backend_id: str,
        stage_name: str,
        result: dict[str, Any],
        backend_metadata: dict[str, Any] | None = None,
    ) -> ImageExecutionResult:
        normalized = canonicalize_variant_entry(result, stage=stage_name)
        artifact = dict(normalized.get("artifact") or {})
        output_paths = [str(item) for item in extract_artifact_paths(normalized) if item]
        primary_path = (
            artifact.get("primary_path") or normalized.get("path") or normalized.get("output_path")
        )
        if not artifact or artifact.get("schema") != ARTIFACT_SCHEMA_VERSION:
            artifact = build_artifact_record(
                stage=stage_name,
                artifact_type="image",
                primary_path=primary_path,
                output_paths=output_paths,
                manifest_path=normalized.get("manifest_path"),
                thumbnail_path=normalized.get("thumbnail_path"),
                input_image_path=normalized.get("input_image_path"),
            )
        return cls(
            backend_id=backend_id,
            stage_name=stage_name,
            primary_path=str(primary_path) if primary_path else None,
            output_paths=output_paths,
            manifest_path=str(normalized["manifest_path"])
            if normalized.get("manifest_path")
            else None,
            thumbnail_path=str(normalized["thumbnail_path"])
            if normalized.get("thumbnail_path")
            else None,
            artifact=artifact,
            raw_result=normalized,
            backend_metadata=dict(backend_metadata or {}),
        )

    def to_variant_payload(self) -> dict[str, Any]:
        payload = dict(self.raw_result)
        if self.primary_path:
            payload.setdefault("path", self.primary_path)
            payload.setdefault("output_path", self.primary_path)
        if self.output_paths:
            payload["output_paths"] = list(self.output_paths)
        payload["artifact"] = dict(self.artifact)
        payload["image_backend_id"] = self.backend_id
        payload["image_backend_metadata"] = dict(self.backend_metadata)
        return canonicalize_variant_entry(payload, stage=self.stage_name)


class ImageBackendInterface(Protocol):
    backend_id: str
    capabilities: ImageBackendCapabilities

    def execute(
        self, pipeline: Any, request: ImageExecutionRequest
    ) -> ImageExecutionResult | None: ...
