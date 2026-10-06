"""FLUX.2 Klein 4B FP8 model profile for the existing ``forge_webui`` backend (PR-IMG-116).

Klein is not a backend. It is one bounded, StableNew-owned, *versioned* profile that makes the
semantics qualified by PR-IMG-115 explicit and replayable: exact asset identities, the distilled
sampler/scheduler/steps/CFG, the two supported modes and the two qualified geometries. The NJR
persists only ``backend_options.image.model_profile = {"id", "version"}``; this module resolves that
reference to immutable expectations. A published version never changes; a future change is a new
version. There is deliberately no generic model-profile registry here (PR-IMG-130 owns that).

Everything in this module is pure (no I/O at import, no network, no hashing); asset hashing and
installation live in ``tools/install_forge_klein_assets.ps1`` and the readiness check.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.image_backends.image_backend_types import FORGE_IMAGE_BACKEND_ID

KLEIN_PROFILE_ID = "flux2_klein_4b_fp8"
KLEIN_PROFILE_VERSION = 1
KLEIN_DISPLAY_NAME = "FLUX.2 Klein 4B FP8"

MODE_TXT2IMG = "txt2img"
MODE_SINGLE_REFERENCE_EDIT = "single_reference_edit"

#: Reprocess stage-chain for the single-reference edit mode (Forge ``/img2img`` with the init image
#: as the one Klein reference). ``ImageStitch Integrated`` is never used (PR-IMG-115 Case D).
EDIT_STAGE_CHAIN = ("img2img",)
T2I_STAGE_CHAIN = ("txt2img",)

#: Initial host-memory requirement: the 32-GB-class machine. It is deliberately the decimal 32e9 bytes,
#: not 32 GiB: a physically installed 32 GiB Windows machine reports somewhat less after hardware
#: reservation. Currently available RAM has no floor: it is observational until the production smokes
#: establish evidence (PR-IMG-115 captured no trustworthy pre-dispatch baseline).
MIN_TOTAL_RAM_BYTES = 32_000_000_000


class KleinProfileError(ValueError):
    """The Klein profile cannot be resolved, or the requested work is outside its envelope."""


@dataclass(frozen=True, slots=True)
class KleinAsset:
    role: str
    #: Forge module/checkpoint filename (also the logical name persisted in provenance).
    filename: str
    size: int
    sha256: str
    #: Sub-directory of ``<managed-forge-data>/models`` that holds the file.
    models_subdir: str
    repo: str
    revision: str

    @property
    def logical_name(self) -> str:
        return self.filename.rsplit(".", 1)[0]


@dataclass(frozen=True, slots=True)
class KleinProfile:
    profile_id: str
    version: int
    display_name: str
    backend_id: str
    transformer: KleinAsset
    text_encoder: KleinAsset
    vae: KleinAsset
    sampler: str
    scheduler: str
    steps: int
    cfg_scale: float
    #: Qualified (width, height) pairs; nothing else is accepted.
    geometries: tuple[tuple[int, int], ...]
    modes: tuple[str, ...]
    #: img2img semantics proven by PR-IMG-115 Case C: the init image is the Klein reference and the
    #: whole latent is regenerated (denoise 1.0, resize mode 0).
    edit_denoising_strength: float
    min_total_ram_bytes: int
    #: LoRAs the profile admits for text-to-image work. Version 1 (PR-IMG-116) admits none and keeps meaning
    #: exactly that; version 2 (PR-IMG-117) admits exactly one explicitly Klein-4B-compatible adapter.
    max_loras: int = 0

    @property
    def modules(self) -> tuple[KleinAsset, KleinAsset]:
        """Forge ``forge_additional_modules`` set, in the order PR-IMG-115 selected them."""

        return (self.text_encoder, self.vae)

    @property
    def assets(self) -> tuple[KleinAsset, ...]:
        return (self.transformer, self.text_encoder, self.vae)

    def reference(self) -> dict[str, Any]:
        """The only profile state persisted in an NJR."""

        return {"id": self.profile_id, "version": self.version}


_COMFY_REPO = "Comfy-Org/vae-text-encorder-for-flux-klein-4b"
_COMFY_REVISION = "5f526678002e43af5551dadb73ce2e8c91b43afe"

KLEIN_PROFILE_V1 = KleinProfile(
    profile_id=KLEIN_PROFILE_ID,
    version=1,
    display_name=KLEIN_DISPLAY_NAME,
    backend_id=FORGE_IMAGE_BACKEND_ID,
    transformer=KleinAsset(
        role="transformer",
        filename="flux-2-klein-4b-fp8.safetensors",
        size=4_070_624_520,
        sha256="97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6",
        models_subdir="Stable-diffusion",
        repo="black-forest-labs/FLUX.2-klein-4b-fp8",
        revision="5b4408e59397a4a37ccb46afe426d8ed86379441",
    ),
    text_encoder=KleinAsset(
        role="text_encoder",
        filename="qwen_3_4b.safetensors",
        size=8_044_982_048,
        sha256="6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
        models_subdir="text_encoder",
        repo=_COMFY_REPO,
        revision=_COMFY_REVISION,
    ),
    vae=KleinAsset(
        role="vae",
        filename="flux2-vae.safetensors",
        size=336_211_292,
        sha256="868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3",
        models_subdir="VAE",
        repo=_COMFY_REPO,
        revision=_COMFY_REVISION,
    ),
    sampler="Euler",
    scheduler="Beta",
    steps=4,
    cfg_scale=1.0,
    geometries=((768, 1024), (1024, 1024)),
    modes=(MODE_TXT2IMG, MODE_SINGLE_REFERENCE_EDIT),
    edit_denoising_strength=1.0,
    min_total_ram_bytes=MIN_TOTAL_RAM_BYTES,
)

#: Version 2 (PR-IMG-117): identical assets, sampling, modes, geometry and host-RAM policy; the only envelope
#: expansion is one explicitly FLUX.2 Klein 4B-compatible LoRA on text-to-image work (negative prompts, global
#: terms, the optimizer and every other feature stay unsupported). Version 1 is never edited or upgraded.
KLEIN_PROFILE_V2 = replace(KLEIN_PROFILE_V1, version=2, max_loras=1)

_PROFILES: dict[tuple[str, int], KleinProfile] = {
    (KLEIN_PROFILE_ID, 1): KLEIN_PROFILE_V1,
    (KLEIN_PROFILE_ID, 2): KLEIN_PROFILE_V2,
}

#: The version newly constructed work is stamped with. It moves to a newer published version only after that
#: version's physical qualification succeeds; persisted work keeps the version it froze.
_LATEST_PROFILE = KLEIN_PROFILE_V2


def latest_klein_profile() -> KleinProfile:
    """The version new work is constructed with (existing records keep the version they froze)."""

    return _LATEST_PROFILE


def klein_model_profile_reference() -> dict[str, Any]:
    return latest_klein_profile().reference()


def _image_options(backend_options: Any) -> Mapping[str, Any]:
    if not isinstance(backend_options, Mapping):
        return {}
    image = backend_options.get("image")
    return image if isinstance(image, Mapping) else {}


def resolve_model_profile(backend_options: Any) -> KleinProfile | None:
    """Resolve ``backend_options.image.model_profile`` or ``None`` when the work has no profile.

    A profile reference that is malformed, unknown or of an unknown version fails closed: it is never
    reinterpreted as another profile or as plain SDXL work.
    """

    reference = _image_options(backend_options).get("model_profile")
    if reference is None:
        return None
    if not isinstance(reference, Mapping):
        raise KleinProfileError("backend_options.image.model_profile must be a mapping")
    profile_id = str(reference.get("id") or "").strip()
    try:
        version = int(reference.get("version") or 0)
    except (TypeError, ValueError):
        raise KleinProfileError("model_profile.version must be an integer") from None
    profile = _PROFILES.get((profile_id, version))
    if profile is None:
        raise KleinProfileError(
            f"Unsupported model profile '{profile_id}' version {version}; "
            f"supported: {sorted(f'{pid}@v{ver}' for pid, ver in _PROFILES)}"
        )
    return profile


def _model_key(name: str) -> str:
    base = os.path.basename(str(name or "").strip().replace("\\", "/"))
    # Forge/A1111 listings may append " [shorthash]" to a checkpoint title.
    if base.endswith("]") and " [" in base:
        base = base[: base.rindex(" [")]
    lowered = base.strip().lower()
    for ext in (".safetensors", ".sft", ".ckpt", ".pt", ".pth"):
        if lowered.endswith(ext):
            return lowered[: -len(ext)]
    return lowered


def is_klein_transformer_name(model_name: str | None) -> bool:
    """Exact identity match against the qualified transformer; never a substring heuristic."""

    if not model_name:
        return False
    return _model_key(model_name) == _model_key(KLEIN_PROFILE_V1.transformer.filename)


def model_profile_for_model(model_name: str | None) -> dict[str, Any] | None:
    """The persisted profile reference implied by the selected checkpoint, if it is the Klein one."""

    return klein_model_profile_reference() if is_klein_transformer_name(model_name) else None


def validate_klein_intent(
    profile: KleinProfile,
    *,
    backend_id: str,
    stage_names: Iterable[str],
    model_name: str | None,
    sampler: str | None,
    scheduler: str | None,
    steps: int | float | None,
    cfg_scale: float | None,
    width: int | None,
    height: int | None,
    negative_prompt: str | None,
    unsupported_features: Iterable[str] = (),
) -> str:
    """Reject anything outside the qualified envelope; return the resolved mode.

    Raises one ``KleinProfileError`` that lists every conflict, before any generation dispatch.
    Conflicting immutable intent is rejected, never silently rewritten.
    """

    problems: list[str] = []
    if backend_id != profile.backend_id:
        problems.append(
            f"backend '{backend_id}' is not supported (the Klein profile requires '{profile.backend_id}'; "
            "StableNew never switches the configured backend for you, so select the Forge WebUI "
            "runtime in settings first)"
        )
    stages = tuple(str(stage) for stage in stage_names)
    if stages == T2I_STAGE_CHAIN:
        mode = MODE_TXT2IMG
    elif stages == EDIT_STAGE_CHAIN:
        mode = MODE_SINGLE_REFERENCE_EDIT
    else:
        mode = ""
        problems.append(
            f"stage chain {list(stages)} is not supported (only {list(T2I_STAGE_CHAIN)} or "
            f"{list(EDIT_STAGE_CHAIN)}; no ADetailer, upscale or multi-reference)"
        )
    if model_name is not None and not is_klein_transformer_name(model_name):
        problems.append(
            f"checkpoint '{model_name}' is not the qualified {profile.transformer.filename}"
        )
    if str(sampler or "") != profile.sampler:
        problems.append(f"sampler '{sampler}' conflicts with fixed '{profile.sampler}'")
    if str(scheduler or "") != profile.scheduler:
        problems.append(f"scheduler '{scheduler}' conflicts with fixed '{profile.scheduler}'")
    if steps is None or int(steps) != profile.steps or float(steps) != float(int(steps)):
        problems.append(f"steps {steps} conflicts with fixed {profile.steps}")
    if cfg_scale is None or float(cfg_scale) != profile.cfg_scale:
        problems.append(f"CFG {cfg_scale} conflicts with fixed {profile.cfg_scale}")
    if (width, height) not in profile.geometries:
        allowed = ", ".join(f"{w}x{h}" for w, h in profile.geometries)
        problems.append(f"geometry {width}x{height} is not qualified (supported: {allowed})")
    if str(negative_prompt or "").strip():
        problems.append("a negative prompt is not supported (its semantics were not qualified)")
    problems.extend(f"{feature} is not supported" for feature in unsupported_features)
    if problems:
        raise KleinProfileError(
            f"{profile.display_name} (profile v{profile.version}) cannot run this work: "
            + "; ".join(problems)
        )
    return mode


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _truthy_section(config: Mapping[str, Any], section: str, *keys: str) -> bool:
    data = config.get(section)
    if not isinstance(data, Mapping):
        return False
    return any(bool(data.get(key)) for key in keys)


def detect_unsupported_features(
    execution_config: Mapping[str, Any] | None,
    *,
    positive_prompt: str = "",
    lora_admitted: bool = False,
) -> list[str]:
    """Names of requested features outside the qualified Klein envelope (empty when none).

    The Klein compile policy switches the prompt optimizer off and clears negative text; whatever
    else is *enabled* here (hires fix, refiner, LoRA, ControlNet, aesthetic, hypernetwork) is a real
    conflict and is rejected rather than ignored. ``lora_admitted`` (profile v2) leaves the LoRA decision to
    ``forge_klein_lora.evaluate_klein_loras`` (count, weight, compatibility); it never makes LoRA unchecked.
    """

    config = execution_config if isinstance(execution_config, Mapping) else {}
    txt2img = _mapping(config.get("txt2img"))
    found: list[str] = []
    if (
        _truthy_section(config, "hires_fix", "enabled")
        or bool(txt2img.get("enable_hr"))
        or bool(config.get("enable_hr"))
    ):
        found.append("hires fix")
    if bool(txt2img.get("refiner_enabled")) or bool(config.get("use_refiner")):
        found.append("refiner")
    if _truthy_section(config, "prompt_optimizer", "enabled"):
        found.append("the prompt optimizer")
    if _truthy_section(config, "aesthetic", "enabled"):
        found.append("aesthetic embeddings")
    if not lora_admitted:
        if _truthy_section(config, "style_lora", "enabled") or config.get("lora_strengths"):
            found.append("LoRA")
        elif "<lora:" in str(positive_prompt or "").lower():
            found.append("LoRA")
    if any("controlnet" in str(key).lower() and config.get(key) for key in config):
        found.append("ControlNet")
    if str(txt2img.get("hypernetwork") or "none").strip().lower() not in {"", "none"}:
        found.append("hypernetwork")
    return found


def klein_selected(config: Mapping[str, Any] | None) -> bool:
    """Whether a merged run config selects the qualified Klein transformer."""

    if not isinstance(config, Mapping):
        return False
    txt2img = _mapping(config.get("txt2img"))
    for source in (txt2img, config):
        for key in ("model", "model_name", "sd_model_checkpoint", "base_model"):
            if is_klein_transformer_name(str(source.get(key) or "")):
                return True
    return False


def apply_klein_compile_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Freeze the Klein profile semantics into a merged txt2img run config (in place; returns it).

    A no-op unless the qualified Klein transformer is the selected checkpoint. It fixes the distilled
    sampler/scheduler/steps/CFG, clears negative text and global prompt terms (the qualified runs used
    an empty negative prompt and no global terms), switches the (default-on) prompt optimizer off and
    stamps the profile reference. Anything it does not own (geometry, hires, LoRA, ...) is left for the
    fail-closed validators so a conflict is reported, never silently rewritten.
    """

    if not klein_selected(config):
        return config
    profile = latest_klein_profile()
    txt2img = config.setdefault("txt2img", {})
    if not isinstance(txt2img, dict):
        txt2img = {}
        config["txt2img"] = txt2img
    txt2img.update(
        vae="",
        sampler_name=profile.sampler,
        scheduler=profile.scheduler,
        steps=profile.steps,
        cfg_scale=profile.cfg_scale,
        negative_prompt="",
        prompt_optimizer={"enabled": False},
        global_positive_prompt="",
        global_negative_prompt="",
        global_prompt_policy_source="frozen_njr",
    )
    for flat, value in (
        ("sampler_name", profile.sampler),
        ("sampler", profile.sampler),
        ("scheduler", profile.scheduler),
        ("steps", profile.steps),
        ("cfg_scale", profile.cfg_scale),
        ("negative_prompt", ""),
        ("vae", ""),
    ):
        if flat in config:
            config[flat] = value
    optimizer = config.get("prompt_optimizer")
    config["prompt_optimizer"] = {**(optimizer if isinstance(optimizer, Mapping) else {}), "enabled": False}
    pipeline = dict(config.get("pipeline") or {})
    pipeline["apply_global_positive_txt2img"] = False
    for key in (
        "apply_global_negative_txt2img",
        "apply_global_negative_img2img",
        "apply_global_negative_adetailer",
        "apply_global_negative_upscale",
    ):
        pipeline[key] = False
    config["pipeline"] = pipeline
    config["global_positive_prompt"] = ""
    config["global_negative_prompt"] = ""
    config["global_prompt_policy_source"] = "frozen_njr"
    backend_options = dict(config.get("backend_options") or {})
    image = dict(backend_options.get("image") or {})
    image["model_profile"] = profile.reference()
    backend_options["image"] = image
    config["backend_options"] = backend_options
    return config


#: ``ReprocessSourceItem.metadata`` key through which Review requests the explicit single-reference
#: Klein edit (never inferred from an image's name or content).
KLEIN_EDIT_METADATA_KEY = "klein_single_reference_edit"


def klein_edit_config(*, width: int, height: int) -> dict[str, Any]:
    """The complete, frozen reprocess config for one single-reference Klein edit (``/img2img``)."""

    profile = latest_klein_profile()
    model = profile.transformer.filename
    stage = {
        "model": model,
        "steps": profile.steps,
        "cfg_scale": profile.cfg_scale,
        "sampler_name": profile.sampler,
        "scheduler": profile.scheduler,
        "denoising_strength": profile.edit_denoising_strength,
        "width": int(width),
        "height": int(height),
    }
    return {
        "img2img": dict(stage),
        "model": model,
        "model_name": model,
        "width": int(width),
        "height": int(height),
        "steps": profile.steps,
        "cfg_scale": profile.cfg_scale,
        "sampler_name": profile.sampler,
        "scheduler": profile.scheduler,
        "negative_prompt": "",
        "prompt_optimizer": {"enabled": False},
        "pipeline": {
            "txt2img_enabled": False,
            "img2img_enabled": True,
            "apply_global_positive_txt2img": False,
            "apply_global_negative_txt2img": False,
            "apply_global_negative_img2img": False,
            "apply_global_negative_adetailer": False,
            "apply_global_negative_upscale": False,
        },
        "global_positive_prompt": "",
        "global_negative_prompt": "",
        "global_prompt_policy_source": "frozen_njr",
        "backend_options": {"image": {"model_profile": profile.reference()}},
    }


def klein_provenance(
    profile: KleinProfile, *, mode: str, lora: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Durable, machine-path-free evidence block recorded with the stage result."""

    evidence: dict[str, Any] = {
        "model_profile": profile.reference(),
        "backend_id": profile.backend_id,
        "mode": mode,
        "transformer": {
            "name": profile.transformer.filename,
            "size": profile.transformer.size,
            "sha256": profile.transformer.sha256,
        },
        "modules": [
            {"name": asset.filename, "size": asset.size, "sha256": asset.sha256}
            for asset in profile.modules
        ],
        "sampler": profile.sampler,
        "scheduler": profile.scheduler,
        "steps": profile.steps,
        "cfg_scale": profile.cfg_scale,
    }
    if lora is not None:
        evidence["lora"] = dict(lora)
    return evidence


__all__ = [
    "EDIT_STAGE_CHAIN",
    "KLEIN_DISPLAY_NAME",
    "KLEIN_EDIT_METADATA_KEY",
    "KLEIN_PROFILE_ID",
    "KLEIN_PROFILE_V1",
    "KLEIN_PROFILE_V2",
    "KLEIN_PROFILE_VERSION",
    "KleinAsset",
    "KleinProfile",
    "KleinProfileError",
    "MIN_TOTAL_RAM_BYTES",
    "MODE_SINGLE_REFERENCE_EDIT",
    "MODE_TXT2IMG",
    "T2I_STAGE_CHAIN",
    "apply_klein_compile_policy",
    "detect_unsupported_features",
    "is_klein_transformer_name",
    "klein_edit_config",
    "klein_selected",
    "klein_model_profile_reference",
    "klein_provenance",
    "latest_klein_profile",
    "model_profile_for_model",
    "resolve_model_profile",
    "validate_klein_intent",
]
