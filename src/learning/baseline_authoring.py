"""Learning's independently authored experiment baseline (toolkit-neutral).

A Learning experiment owns an editable baseline: the fixed settings every variant shares.  It is seeded at most
once, explicitly, from the Pipeline's settings (``seed_from_pipeline``) and from then on it is never re-read from
the Pipeline.  Build Preview freezes it into the experiment snapshot; the frozen copy is the only thing Run compiles.

This module holds the pure rules: which settings an executable experiment needs for each supported stage, how the
Learning-owned copy is edited without creating competing aliases, what is missing, and what each variant will
effectively use.  It never reads a widget, a stage card, a file other than the chosen source image, or the queue.
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.learning.stage_capabilities import STAGE_CAPABILITIES

AUTHORING_KEY = "baseline_authoring"
AUTHORING_VERSION = 1

ORIGIN_PIPELINE_COPY = "pipeline_copy"
ORIGIN_LEARNING = "learning_authored"
ORIGIN_CLONE = "cloned"
ORIGIN_LEGACY = "legacy_frozen"

_ORIGIN_TEXT = {
    ORIGIN_PIPELINE_COPY: "Copied from Pipeline",
    ORIGIN_LEARNING: "Copied from Pipeline, edited in Learning",
    ORIGIN_CLONE: "Cloned from an earlier experiment",
    ORIGIN_LEGACY: "Saved before independent baselines (read-only history)",
}

SOURCE_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

OWNERSHIP_BASELINE = "baseline"
OWNERSHIP_VARIABLE = "variable"
OWNERSHIP_MODEL = "model_policy"
OWNERSHIP_UNSUPPORTED = "unsupported"

_STAGE_FLAGS = ("txt2img_enabled", "img2img_enabled", "adetailer_enabled", "upscale_enabled")
_STAGE_SECTIONS = ("txt2img", "img2img", "adetailer", "upscale")


@dataclass(frozen=True)
class FieldSpec:
    """One setting an operator can author for a stage.

    ``key`` is the canonical key in the stage section.  ``aliases`` are the other keys the canonical builders and
    handlers read for the same setting; editing the field keeps every alias in step so two spellings can never
    disagree about the effective value.
    """

    name: str
    label: str
    section: str
    key: str
    kind: str  # "resource" | "choice" | "int" | "float" | "text" | "bool"
    resource: str = ""
    variable: str = ""
    required: bool = True
    advanced: bool = False
    aliases: tuple[str, ...] = ()
    top_level_aliases: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    default_seed: bool = False


def _f(name: str, label: str, section: str, key: str, kind: str, **kw: Any) -> FieldSpec:
    return FieldSpec(name, label, section, key, kind, **kw)


_TXT2IMG_FIELDS: tuple[FieldSpec, ...] = (
    _f(
        "model",
        "Model",
        "txt2img",
        "model",
        "resource",
        resource="models",
        variable="model",
        aliases=("model_name",),
    ),
    _f(
        "vae",
        "VAE",
        "txt2img",
        "vae",
        "resource",
        resource="vaes",
        variable="vae",
        required=False,
        aliases=("vae_name",),
    ),
    _f(
        "sampler_name",
        "Sampler",
        "txt2img",
        "sampler_name",
        "resource",
        resource="samplers",
        variable="sampler",
    ),
    _f(
        "scheduler",
        "Scheduler",
        "txt2img",
        "scheduler",
        "resource",
        resource="schedulers",
        variable="scheduler",
    ),
    _f("steps", "Steps", "txt2img", "steps", "int", variable="steps", minimum=1, maximum=150),
    _f(
        "cfg_scale",
        "CFG Scale",
        "txt2img",
        "cfg_scale",
        "float",
        variable="cfg_scale",
        minimum=1,
        maximum=30,
    ),
    _f("width", "Width", "txt2img", "width", "int", minimum=64, maximum=8192),
    _f("height", "Height", "txt2img", "height", "int", minimum=64, maximum=8192),
    _f(
        "seed",
        "Seed (-1 = pick once at Preview)",
        "txt2img",
        "seed",
        "int",
        required=False,
        advanced=True,
        default_seed=True,
    ),
    _f("subseed", "Subseed", "txt2img", "subseed", "int", required=False, advanced=True),
    _f(
        "subseed_strength",
        "Subseed strength",
        "txt2img",
        "subseed_strength",
        "float",
        required=False,
        advanced=True,
        minimum=0,
        maximum=1,
    ),
    _f(
        "clip_skip",
        "CLIP skip",
        "txt2img",
        "clip_skip",
        "int",
        required=False,
        advanced=True,
        minimum=1,
        maximum=12,
    ),
)

_IMG2IMG_FIELDS: tuple[FieldSpec, ...] = (
    _f(
        "model",
        "Model",
        "img2img",
        "model",
        "resource",
        resource="models",
        variable="model",
        aliases=("model_name",),
    ),
    _f(
        "vae",
        "VAE",
        "img2img",
        "vae",
        "resource",
        resource="vaes",
        variable="vae",
        required=False,
        aliases=("vae_name",),
    ),
    _f(
        "sampler_name",
        "Sampler",
        "img2img",
        "sampler_name",
        "resource",
        resource="samplers",
        variable="sampler",
        top_level_aliases=("img2img_sampler_name",),
    ),
    _f(
        "scheduler",
        "Scheduler",
        "img2img",
        "scheduler",
        "resource",
        resource="schedulers",
        variable="scheduler",
        required=False,
        top_level_aliases=("img2img_scheduler",),
    ),
    _f(
        "steps",
        "Steps",
        "img2img",
        "steps",
        "int",
        variable="steps",
        minimum=1,
        maximum=150,
        top_level_aliases=("img2img_steps",),
    ),
    _f(
        "cfg_scale",
        "CFG Scale",
        "img2img",
        "cfg_scale",
        "float",
        variable="cfg_scale",
        minimum=1,
        maximum=30,
        top_level_aliases=("img2img_cfg_scale",),
    ),
    _f(
        "denoising_strength",
        "Denoise Strength",
        "img2img",
        "denoising_strength",
        "float",
        variable="denoise_strength",
        minimum=0,
        maximum=1,
        top_level_aliases=("img2img_denoising_strength",),
    ),
    _f(
        "width",
        "Width",
        "img2img",
        "width",
        "int",
        required=False,
        advanced=True,
        minimum=64,
        maximum=8192,
    ),
    _f(
        "height",
        "Height",
        "img2img",
        "height",
        "int",
        required=False,
        advanced=True,
        minimum=64,
        maximum=8192,
    ),
)

_ADETAILER_FIELDS: tuple[FieldSpec, ...] = (
    _f(
        "model",
        "Refinement model",
        "adetailer",
        "model",
        "resource",
        resource="models",
        variable="model",
        aliases=("adetailer_checkpoint_model", "model_name"),
    ),
    _f(
        "vae",
        "VAE",
        "adetailer",
        "vae",
        "resource",
        resource="vaes",
        variable="vae",
        required=False,
        advanced=True,
    ),
    _f(
        "detector",
        "Detector model",
        "adetailer",
        "adetailer_model",
        "choice",
        resource="adetailer_models",
    ),
    _f(
        "confidence",
        "Detector confidence",
        "adetailer",
        "adetailer_confidence",
        "float",
        required=False,
        minimum=0,
        maximum=1,
        aliases=("ad_confidence",),
    ),
    _f(
        "sampler_name",
        "Sampler",
        "adetailer",
        "sampler_name",
        "resource",
        resource="samplers",
        variable="sampler",
        aliases=("adetailer_sampler", "ad_sampler"),
        top_level_aliases=("adetailer_sampler", "ad_sampler"),
    ),
    _f(
        "scheduler",
        "Scheduler",
        "adetailer",
        "scheduler",
        "resource",
        resource="schedulers",
        variable="scheduler",
        required=False,
        aliases=("adetailer_scheduler",),
        top_level_aliases=("adetailer_scheduler",),
    ),
    _f(
        "steps",
        "Steps",
        "adetailer",
        "steps",
        "int",
        variable="steps",
        minimum=1,
        maximum=150,
        aliases=("adetailer_steps", "ad_steps"),
        top_level_aliases=("adetailer_steps", "ad_steps"),
    ),
    _f(
        "cfg_scale",
        "CFG Scale",
        "adetailer",
        "cfg_scale",
        "float",
        variable="cfg_scale",
        minimum=1,
        maximum=30,
        aliases=("adetailer_cfg", "ad_cfg_scale"),
        top_level_aliases=("adetailer_cfg_scale", "adetailer_cfg", "ad_cfg_scale"),
    ),
    _f(
        "denoising_strength",
        "Denoise Strength",
        "adetailer",
        "denoising_strength",
        "float",
        variable="denoise_strength",
        minimum=0,
        maximum=1,
        aliases=("adetailer_denoise", "ad_denoising_strength"),
        top_level_aliases=(
            "adetailer_denoising_strength",
            "adetailer_denoise",
            "ad_denoising_strength",
        ),
    ),
)

_UPSCALE_FIELDS: tuple[FieldSpec, ...] = (
    _f(
        "upscaler",
        "Upscaler",
        "upscale",
        "upscaler",
        "resource",
        resource="upscalers",
        aliases=("upscaler_name", "upscaler_1"),
    ),
    _f(
        "upscale_factor",
        "Upscale factor",
        "upscale",
        "upscale_factor",
        "float",
        variable="upscale_factor",
        minimum=1,
        maximum=8,
        aliases=("upscaling_resize", "scale"),
    ),
    _f(
        "model",
        "Model",
        "upscale",
        "model",
        "resource",
        resource="models",
        variable="model",
        required=False,
        advanced=True,
    ),
    _f(
        "vae",
        "VAE",
        "upscale",
        "vae",
        "resource",
        resource="vaes",
        variable="vae",
        required=False,
        advanced=True,
    ),
    _f(
        "steps",
        "Refinement steps",
        "upscale",
        "steps",
        "int",
        required=False,
        advanced=True,
        minimum=1,
        maximum=150,
    ),
    _f(
        "denoising_strength",
        "Refinement denoise",
        "upscale",
        "denoising_strength",
        "float",
        required=False,
        advanced=True,
        minimum=0,
        maximum=1,
    ),
    _f(
        "sampler_name",
        "Refinement sampler",
        "upscale",
        "sampler_name",
        "resource",
        resource="samplers",
        required=False,
        advanced=True,
    ),
    _f(
        "scheduler",
        "Refinement scheduler",
        "upscale",
        "scheduler",
        "resource",
        resource="schedulers",
        required=False,
        advanced=True,
    ),
)

_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "txt2img": _TXT2IMG_FIELDS,
    "img2img": _IMG2IMG_FIELDS,
    "adetailer": _ADETAILER_FIELDS,
    "upscale": _UPSCALE_FIELDS,
}


def require_stage(stage: Any) -> str:
    """Return a supported stage name; an unknown name is refused, never mapped to txt2img."""
    name = str(stage or "").strip().lower()
    if name not in STAGE_CAPABILITIES:
        raise ValueError(
            f"Unsupported Learning stage {stage!r}. Supported stages: {', '.join(STAGE_CAPABILITIES)}."
        )
    return name


def fields_for_stage(stage: str) -> tuple[FieldSpec, ...]:
    return _FIELDS[require_stage(stage)]


def field_for(stage: str, name: str) -> FieldSpec:
    for spec in fields_for_stage(stage):
        if spec.name == name:
            return spec
    raise KeyError(f"{stage} has no baseline setting {name!r}")


# -- reading and writing ----------------------------------------------------------------------------------------


def _section(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = config.get(name)
    return value if isinstance(value, Mapping) else {}


def _present(value: Any) -> bool:
    if value is None:
        return False
    return not (isinstance(value, str) and not value.strip())


def read_field(config: Mapping[str, Any], spec: FieldSpec) -> Any:
    """The canonical value, falling back to the first alias the canonical builders would have honoured."""
    section = _section(config, spec.section)
    if _present(section.get(spec.key)):
        return section[spec.key]
    for alias in spec.aliases:
        if _present(section.get(alias)):
            return section[alias]
    for alias in spec.top_level_aliases:
        if _present(config.get(alias)):
            return config[alias]
    return None


def _coerce(spec: FieldSpec, value: Any) -> Any:
    if spec.kind == "int":
        return int(float(value))
    if spec.kind == "float":
        return float(value)
    if spec.kind == "bool":
        return bool(value)
    return str(value).strip() if value is not None else ""


def write_field(config: dict[str, Any], spec: FieldSpec, value: Any) -> Any:
    """Set the canonical key and every alias that already exists, so the effective value is unambiguous."""
    coerced = _coerce(spec, value)
    section = config.setdefault(spec.section, {})
    if not isinstance(section, dict):
        section = {}
        config[spec.section] = section
    section[spec.key] = coerced
    for alias in spec.aliases:
        # ADetailer and Upscale handlers read several spellings, so every alias is written, not just present ones.
        if alias in section or spec.section in {"adetailer", "upscale"}:
            section[alias] = coerced
    for alias in spec.top_level_aliases:
        if alias in config:
            config[alias] = coerced
    return coerced


def align_aliases(config: dict[str, Any], stage: str) -> dict[str, Any]:
    """Make every spelling of a stage setting equal the canonical value (idempotent; returns ``config``)."""
    for spec in fields_for_stage(stage):
        value = read_field(config, spec)
        if value is None:
            continue
        try:
            write_field(config, spec, value)
        except (TypeError, ValueError):
            continue
    return config


def set_variable_value(config: dict[str, Any], stage: str, variable: str, value: Any) -> bool:
    """Apply a tested value through the stage's field (keeping aliases aligned); False if no field owns it."""
    for spec in fields_for_stage(stage):
        if spec.variable == variable:
            write_field(config, spec, value)
            return True
    return False


def seed_from_pipeline(
    pipeline_config: Mapping[str, Any], stage: str, *, now: datetime | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One-time, explicit import of the Pipeline's settings: a deep copy plus its authoring record.

    The copy is canonicalised for the target stage (flat card keys are absorbed into the stage section) so the
    Learning baseline reads the same through every consumer.  Nothing stays linked to the Pipeline afterwards.
    """
    config = copy.deepcopy(dict(pipeline_config or {}))
    for name in _STAGE_SECTIONS:
        if not isinstance(config.get(name), dict):
            config[name] = {}
    if not isinstance(config.get("pipeline"), dict):
        config["pipeline"] = {}
    for name in _STAGE_SECTIONS:
        align_aliases(config, name)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    return config, new_authoring(ORIGIN_PIPELINE_COPY, copied_at=stamp)


def new_authoring(origin: str, *, copied_at: str = "", source: str = "pipeline") -> dict[str, Any]:
    return {
        "version": AUTHORING_VERSION,
        "origin": origin,
        "copied_from": source,
        "copied_at": copied_at,
        "edited": [],
    }


def record_edit(authoring: dict[str, Any], stage: str, name: str) -> dict[str, Any]:
    """Note that a Learning-owned setting differs from what was copied; the origin label follows."""
    marker = f"{stage}.{name}"
    edited = [str(item) for item in authoring.get("edited") or []]
    if marker not in edited:
        edited.append(marker)
    authoring["edited"] = edited
    if authoring.get("origin") == ORIGIN_PIPELINE_COPY:
        authoring["origin"] = ORIGIN_LEARNING
    return authoring


def origin_text(authoring: Mapping[str, Any] | None) -> str:
    if not authoring:
        return "Not initialized: copy the current Pipeline settings, or choose every setting below."
    text = _ORIGIN_TEXT.get(str(authoring.get("origin") or ""), "Learning baseline")
    if authoring.get("origin") == ORIGIN_LEARNING and authoring.get("copied_from") == "learning":
        text = "Authored in Learning"
    stamp = str(authoring.get("copied_at") or "")
    if stamp and authoring.get("origin") in {ORIGIN_PIPELINE_COPY, ORIGIN_LEARNING}:
        text += f" at {stamp.replace('T', ' ')}"
    edited = authoring.get("edited") or []
    if edited:
        text += f"; {len(edited)} setting{'s' if len(edited) != 1 else ''} changed in Learning"
    return text


def has_authoring(snapshot_or_metadata: Mapping[str, Any] | None) -> bool:
    record = (snapshot_or_metadata or {}).get(AUTHORING_KEY)
    return isinstance(record, Mapping) and bool(record.get("origin"))


def signature(config: Mapping[str, Any] | None, stage: str = "") -> str:
    """Stable digest of the settings an operator can author; used to mark a Preview stale."""
    payload = json.dumps(
        {"stage": stage, "config": config or {}}, sort_keys=True, separators=(",", ":"), default=str
    )
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# -- ownership -------------------------------------------------------------------------------------------------


def field_ownership(
    spec: FieldSpec,
    *,
    variable: str = "",
    policy_controls: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Who decides this setting's effective value: the baseline, the sweep, or the model profile."""
    if variable and spec.variable and spec.variable == variable:
        return OWNERSHIP_VARIABLE
    control = (policy_controls or {}).get(spec.variable) if spec.variable else None
    if control and str(control.get("mode") or "") not in {"", "configurable"}:
        return OWNERSHIP_MODEL
    return OWNERSHIP_BASELINE


# -- validation ------------------------------------------------------------------------------------------------


def _number(spec: FieldSpec, value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{spec.label} must be a number"
    if spec.minimum is not None and number < spec.minimum:
        return f"{spec.label} must be at least {spec.minimum:g}"
    if spec.maximum is not None and number > spec.maximum:
        return f"{spec.label} must be at most {spec.maximum:g}"
    return ""


def source_image_problem(stage: str, path: Any) -> str:
    """Why the chosen source cannot define this stage's experiment; empty when it can."""
    capability = STAGE_CAPABILITIES[require_stage(stage)]
    text = str(path or "").strip()
    if not capability.requires_input_image:
        return ""
    if not text:
        return f"{capability.display_name} experiments require a source image"
    if not os.path.isfile(text):
        return f"Source image not found: {text}"
    if not text.lower().endswith(SOURCE_IMAGE_SUFFIXES):
        return f"Source is not a supported image file: {os.path.basename(text)}"
    try:
        if os.path.getsize(text) <= 0:
            return f"Source image is empty: {os.path.basename(text)}"
    except OSError as exc:
        return f"Source image cannot be read: {exc}"
    return ""


def source_image_identity(path: Any) -> dict[str, Any]:
    """What was observed about the source at Preview.  A file stat, not a content hash or an immutable copy."""
    text = str(path or "").strip()
    if not text:
        return {}
    try:
        stat = os.stat(text)
    except OSError:
        return {}
    return {"path": text, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def source_image_changed(identity: Mapping[str, Any] | None) -> str:
    """Non-empty reason when the source no longer matches what Preview observed."""
    if not identity or not identity.get("path"):
        return ""
    current = source_image_identity(identity["path"])
    if not current:
        return f"Source image is no longer available: {identity['path']}"
    if current["size"] != identity.get("size") or current["mtime_ns"] != identity.get("mtime_ns"):
        return f"Source image changed after Preview: {identity['path']}"
    return ""


def policy_owned(model_context: Mapping[str, Any] | None) -> frozenset[str]:
    """Variable names whose value the model profile decides (fixed/unsupported), from a frozen policy context."""
    controls = ((model_context or {}).get("contract") or {}).get("controls") or {}
    return frozenset(
        str(name)
        for name, raw in controls.items()
        if str((raw or {}).get("mode") or "") not in {"", "configurable"}
    )


def baseline_problems(
    config: Mapping[str, Any] | None,
    stage: str,
    *,
    input_image_path: Any = "",
    resources: Mapping[str, Sequence[Any]] | None = None,
    fixed_by_policy: frozenset[str] = frozenset(),
) -> list[str]:
    """Everything that stops this baseline from defining an executable experiment (no value is invented)."""
    try:
        stage = require_stage(stage)
    except ValueError as exc:
        return [str(exc)]
    config = config or {}
    problems: list[str] = []
    if not any(_section(config, name) for name in _STAGE_SECTIONS):
        return [
            "The Learning baseline is empty. Copy the current Pipeline settings or choose each setting."
        ]
    for spec in _FIELDS[stage]:
        value = read_field(config, spec)
        if value is None:
            # A setting the model profile fixes is the profile's to supply, not the operator's.
            if spec.required and spec.variable not in fixed_by_policy:
                problems.append(f"{spec.label} is required for a {stage} experiment")
            continue
        if spec.kind in {"int", "float"}:
            message = _number(spec, value)
            if message:
                problems.append(message)
        available = resource_names(resources, spec.resource) if spec.resource else []
        if available and spec.kind in {"resource", "choice"} and not is_available(value, available):
            if spec.name in {"vae"} and str(value).strip().lower() in {
                "automatic",
                "none",
                "none (baked)",
            }:
                continue
            problems.append(f"{spec.label} '{value}' is not available in the current resources")
    if stage != "txt2img":
        txt2img_model = _section(config, "txt2img").get("model")
        # A stage with no model of its own is refused rather than silently borrowing txt2img's.
        model_spec = field_for(stage, "model")
        if (
            stage != "upscale"
            and read_field(config, model_spec) is None
            and not _present(txt2img_model)
        ):
            problems.append(f"{model_spec.label} is required for a {stage} experiment")
    image = source_image_problem(stage, input_image_path)
    if image:
        problems.append(image)
    return list(dict.fromkeys(problems))


_HASH_SUFFIX = re.compile(r"\s*\[[0-9a-fA-F]+\]\s*$")


def without_hash(name: Any) -> str:
    """A checkpoint's name without the trailing ``[hash]`` WebUI titles carry (the only equivalence applied)."""
    return _HASH_SUFFIX.sub("", str(name or "")).strip()


def resource_names(resources: Mapping[str, Sequence[Any]] | None, key: str) -> list[str]:
    names: list[str] = []
    for entry in (resources or {}).get(key) or []:
        if isinstance(entry, str):
            names.append(entry)
            continue
        for attr in ("name", "display_name", "title", "model_name", "label"):
            value = entry.get(attr) if isinstance(entry, Mapping) else getattr(entry, attr, None)
            if value:
                names.append(str(value))
    return list(dict.fromkeys(names))


def is_available(value: Any, available: Sequence[str]) -> bool:
    wanted = without_hash(value)
    return str(value) in available or any(without_hash(name) == wanted for name in available)


# -- stage enablement and effective settings --------------------------------------------------------------------


def finalize_for_stage(config: dict[str, Any], stage: str) -> dict[str, Any]:
    """Make the target stage the only enabled one, in every flag spelling, and align aliases.

    The requested operation is authoritative: a stale ``pipeline.adetailer_enabled`` or ``adetailer.enabled``
    copied from the Pipeline can neither add a stage nor contradict the one being tested.
    """
    stage = require_stage(stage)
    pipeline = config.setdefault("pipeline", {})
    if not isinstance(pipeline, dict):
        pipeline = {}
        config["pipeline"] = pipeline
    for flag in _STAGE_FLAGS:
        pipeline[flag] = flag == f"{stage}_enabled"
    adetailer = config.get("adetailer")
    if isinstance(adetailer, dict):
        for key in ("enabled", "adetailer_enabled"):
            if key in adetailer or stage == "adetailer":
                adetailer[key] = stage == "adetailer"
    if "adetailer_enabled" in config:
        config["adetailer_enabled"] = stage == "adetailer"
    align_aliases(config, stage)
    return config


def effective_settings(
    config: Mapping[str, Any], stage: str, *, variable: str = "", include_advanced: bool = True
) -> list[dict[str, Any]]:
    """Ordered, display-ready rows of what the stage will use, flagging the one the sweep owns."""
    rows: list[dict[str, Any]] = []
    for spec in fields_for_stage(stage):
        if spec.advanced and not include_advanced:
            continue
        value = read_field(config, spec)
        rows.append(
            {
                "name": spec.name,
                "label": spec.label,
                "value": value,
                "ownership": field_ownership(spec, variable=variable),
            }
        )
    return rows


def variant_projection(
    config: Mapping[str, Any], stage: str, variable: str, value: Any
) -> dict[str, Any]:
    """The comparable effective settings of one variant: the baseline with only the tested value replaced."""
    stage = require_stage(stage)
    working = copy.deepcopy(dict(config))
    if variable and isinstance(value, (int, float, str)) and not isinstance(value, bool):
        set_variable_value(working, stage, variable, value)
    projection: dict[str, Any] = {"stage": stage}
    for spec in fields_for_stage(stage):
        current = read_field(working, spec)
        if current is not None:
            projection[spec.name] = current
    return projection


def stage_values_from_record(record: Any, stage: str) -> dict[str, Any]:
    """What the compiled NJR's stage will actually carry, for the Preview/Run equality proof."""
    stage = require_stage(stage)
    chain = [
        item
        for item in getattr(record, "stages", ()) or ()
        if getattr(item, "stage_type", "") == stage
    ]
    if len(getattr(record, "stages", ()) or ()) != 1 or not chain:
        raise ValueError(f"Compiled job does not contain exactly the requested {stage} stage")
    stage_config = chain[0]
    extra = dict(getattr(stage_config, "extra", {}) or {})
    values: dict[str, Any] = {"stage": stage}
    mapping = {
        "model": "model",
        "steps": "steps",
        "cfg_scale": "cfg_scale",
        "sampler_name": "sampler_name",
        "scheduler": "scheduler",
        "denoising_strength": "denoising_strength",
    }
    for name, attr in mapping.items():
        if name == "model" and stage == "upscale":
            continue
        if name == "denoising_strength" and stage == "txt2img":
            continue
        value = getattr(stage_config, attr, None)
        if _present(value):
            values[name] = value
    if stage == "upscale":
        for name in ("upscaler", "upscale_factor"):
            if _present(extra.get(name)):
                values[name] = extra[name]
    return values


def parity_mismatches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    """Settings the Preview promised that the compiled job does not carry (numeric compare, not text)."""
    problems: list[str] = []
    for name, promised in expected.items():
        if name == "stage" or name not in actual:
            continue
        got = actual[name]
        same = got == promised
        if not same:
            try:
                same = abs(float(got) - float(promised)) < 1e-9
            except (TypeError, ValueError):
                same = str(got).strip() == str(promised).strip()
        if not same:
            problems.append(f"{name}: Preview promised {promised!r} but the job carries {got!r}")
    return problems
