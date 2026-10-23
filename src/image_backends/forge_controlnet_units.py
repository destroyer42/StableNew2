"""All-or-nothing admission and wire projection for ordered pre-rendered units."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.assets.controlnet_identity import MODEL_MODALITIES as MODEL_MODALITIES
from src.assets.controlnet_identity import model_problem as model_problem
from src.assets.controlnet_structure import controlnet_evidence_for_name
from src.conditioning.controlnet import SLOT_FIELD, FrozenControlNet
from src.conditioning.openpose import SLOT_FIELD as LEGACY_FIELD
from src.conditioning.openpose import OpenPoseDeclarationError
from src.conditioning.openpose_snapshot import verify_frozen
from src.image_backends.forge_controlnet import (
    CODE_BACKEND,
    CODE_CONFLICT,
    CODE_MODULE,
    CODE_RECORD,
    CODE_RUNTIME,
    CODE_SDXL_MISMATCH,
    CODE_STAGE,
    CODE_UNADMITTED,
    SCRIPT_KEY,
    ControlNetCatalog,
    OpenPoseDispatchError,
    build_unit,
    resolve_advertised_model,
)
from src.image_backends.model_policy import EVIDENCE_REGISTRY, resolve_model_policy
from src.image_backends.openpose_capability import assess_openpose_target

RUNTIME_KEY = "controlnet_units_runtime"
# The model-identity policy (``MODEL_MODALITIES``, ``model_problem``) is defined once in ``assets.controlnet_identity`` so the
# offline readiness projection cannot drift from this admission; both names stay importable from here.


def validate_intent(
    config: Mapping[str, Any] | None, stages: Sequence[str], *, backend_id: str
) -> FrozenControlNet | None:
    if not isinstance(config, Mapping) or config.get(SLOT_FIELD) is None:
        return None
    if config.get(LEGACY_FIELD) is not None:
        raise OpenPoseDispatchError(
            CODE_CONFLICT, "Use either legacy OpenPose or ordered ControlNet units, not both."
        )
    if backend_id != "forge_webui":
        raise OpenPoseDispatchError(
            CODE_BACKEND, "Ordered ControlNet conditioning requires the Forge backend."
        )
    if "txt2img" not in stages:
        raise OpenPoseDispatchError(CODE_STAGE, "ControlNet requires the base txt2img stage.")
    try:
        return FrozenControlNet.from_config(config[SLOT_FIELD])
    except OpenPoseDeclarationError as exc:
        raise OpenPoseDispatchError(CODE_RECORD, str(exc)) from exc


def validate_target(model: str, backend_id: str, backend_options: Any) -> None:
    from src.image_backends.exact_model_profile import resolve_model_profile

    policy = resolve_model_policy(model)
    if (
        resolve_model_profile(backend_options) is not None
        or policy.evidence != EVIDENCE_REGISTRY
        or not assess_openpose_target(policy, backend_id).executable
    ):
        raise OpenPoseDispatchError(
            CODE_BACKEND,
            "ControlNet requires a registry-verified SDXL checkpoint on Forge; unknown families and exact profiles are refused.",
        )


@dataclass(frozen=True, slots=True)
class UnitsAdmission:
    models: tuple[str, ...]
    record: dict[str, Any]
    evidence: dict[str, Any]


def admit_units(
    frozen: FrozenControlNet, catalog: ControlNetCatalog, *, controlnet_root: Path | None
) -> UnitsAdmission:
    if catalog.models is None or catalog.modules is None:
        raise OpenPoseDispatchError(
            CODE_RUNTIME,
            "Forge's ControlNet model/module catalog is unavailable; no units were admitted.",
        )
    if "none" not in {name.strip().lower() for name in catalog.modules}:
        raise OpenPoseDispatchError(
            CODE_MODULE, "Forge must advertise preprocessor None for pre-rendered ControlNet maps."
        )
    models = []
    evidence = []
    for index, unit in enumerate(frozen.units):
        verify_frozen(unit.image)
        model = resolve_advertised_model(unit.image.model, catalog.models)
        architecture = controlnet_evidence_for_name(controlnet_root, model)
        problem = model_problem(unit.modality, model, architecture.status)
        if problem:
            raise OpenPoseDispatchError(
                CODE_SDXL_MISMATCH,
                f"ControlNet unit {index + 1}: {problem} No generation was dispatched.",
            )
        models.append(model)
        evidence.append(
            {
                **unit.evidence(),
                "advertised_model": model,
                "model_sdxl": {"status": architecture.status, "source": architecture.source},
                "modality_source": "documented_model_identity",
            }
        )
    return UnitsAdmission(
        tuple(models),
        frozen.to_config(),
        {"script": SCRIPT_KEY, "units": evidence, "controlnet_version": catalog.version},
    )


def apply_wire_units(
    config: Mapping[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    frozen = validate_intent(config, ("txt2img",), backend_id="forge_webui")
    if frozen is None:
        return payload, None
    runtime = config.get(RUNTIME_KEY)
    if not isinstance(runtime, Mapping) or runtime.get("record") != frozen.to_config():
        raise OpenPoseDispatchError(
            CODE_UNADMITTED,
            "ControlNet units reached dispatch without matching complete Forge admission.",
        )
    models = runtime.get("models")
    if (
        not isinstance(models, (tuple, list))
        or len(models) != len(frozen.units)
        or any(not isinstance(model, str) or not model for model in models)
    ):
        raise OpenPoseDispatchError(
            CODE_UNADMITTED, "ControlNet admission is incomplete; no generation was dispatched."
        )
    scripts = dict(payload.get("alwayson_scripts") or {})
    if any(str(key).strip().casefold() == SCRIPT_KEY.casefold() for key in scripts):
        raise OpenPoseDispatchError(
            CODE_CONFLICT,
            "The request already carries a ControlNet script; it will not be overwritten.",
        )
    units, evidence = [], []
    for unit, model in zip(frozen.units, models, strict=True):
        data = verify_frozen(unit.image)
        units.append(build_unit(unit.image, model=model, image_bytes=data))
        evidence.append(
            {
                **unit.evidence(),
                "unit_model": model,
                "image_sha256_sent": hashlib.sha256(data).hexdigest(),
            }
        )
    scripts[SCRIPT_KEY] = {"args": units}
    return {**payload, "alwayson_scripts": scripts}, {
        "contract": "controlnet.v1",
        "units": evidence,
        "script": SCRIPT_KEY,
    }


def apply_conditioning(
    config: Mapping[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from src.image_backends.forge_controlnet import apply_openpose_wire_unit

    return (
        apply_wire_units(config, payload)
        if config.get(SLOT_FIELD) is not None
        else apply_openpose_wire_unit(config, payload)
    )


def classify_response(
    response: Any, config: Mapping[str, Any], *, expected: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    from src.conditioning.openpose_snapshot import FrozenOpenPose
    from src.image_backends.openpose_output import classify_openpose_response

    if config.get(SLOT_FIELD) is not None:
        inputs = tuple(
            verify_frozen(unit.image)
            for unit in FrozenControlNet.from_config(config[SLOT_FIELD]).units
        )
    else:
        inputs = (verify_frozen(FrozenOpenPose.from_config(config[LEGACY_FIELD])),)
    return classify_openpose_response(
        response, expected=expected, input_bytes=inputs[0], additional_inputs=inputs[1:]
    )
