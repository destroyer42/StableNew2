"""Forge ControlNet execution contract for one pre-rendered OpenPose unit (PR-IMG-CNET-210).

Forge Neo ships a built-in ``ControlNet`` always-on script, so StableNew does not run its own ControlNet inference: it
admits the job against what the running Forge *advertises* (read-only ``/controlnet/*`` APIs) and then adds exactly one
unit to the base ``/sdapi/v1/txt2img`` request:

    alwayson_scripts.ControlNet.args = [{enabled, module="None", model, image, weight, guidance_start, guidance_end,
                                         control_mode, resize_mode, pixel_perfect=False}]

``module="None"`` means "the image is already an OpenPose map" (no detector runs). The image is the job-owned snapshot,
re-verified by SHA-256 immediately before the request and encoded here; it never enters the NJR, logs or manifests.

Everything here is a pure function over its inputs plus bounded file reads; the HTTP reads live on ``ForgeWebUIClient``
and the stage orchestration stays in the Forge backend and executor. Nothing installs, enables or reconfigures Forge.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.assets.controlnet_structure import (
    STATUS_NOT_SDXL,
    ControlNetEvidence,
    controlnet_evidence_for_name,
    name_key,
)
from src.conditioning.openpose import (
    PREPROCESSOR_NONE,
    SLOT_FIELD,
    ConditioningError,
    OpenPoseDeclarationError,
)
from src.conditioning.openpose_diagnostics import (
    geometry_feedback,
    input_image_facts,
    pose_model_hint,
)
from src.conditioning.openpose_snapshot import FrozenOpenPose, verify_frozen

SCRIPT_KEY = "ControlNet"
#: Config key the Forge backend sets (after admission) so the executor sends the exact advertised model name.
RUNTIME_KEY = "controlnet_openpose_runtime"
STAGE_TXT2IMG = "txt2img"

CODE_BACKEND = "backend_unsupported"
CODE_STAGE = "stage"
CODE_RECORD = "invalid_record"
CODE_RUNTIME = "runtime_unavailable"
CODE_MODEL_MISSING = "model_missing"
CODE_MODEL_AMBIGUOUS = "model_ambiguous"
CODE_MODULE = "module_missing"
CODE_SDXL_MISMATCH = "model_not_sdxl"
CODE_CONFLICT = "script_conflict"
CODE_UNADMITTED = "not_admitted"
CODE_MODALITY = "model_not_openpose"


class OpenPoseDispatchError(ConditioningError):
    """The conditioned request must not be dispatched. ``code`` is stable; the message says what to change."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ControlNetCatalog:
    """What the running Forge advertises through its read-only ControlNet APIs (``None`` = not readable)."""

    models: tuple[str, ...] | None
    modules: tuple[str, ...] | None
    version: int | None = None


@dataclass(frozen=True, slots=True)
class OpenPoseAdmission:
    """The outcome of a successful runtime admission: the model name to send and content-free evidence."""

    unit_model: str
    evidence: dict[str, Any]


# -- intent --------------------------------------------------------------------------------------------------------


def declared(config: Mapping[str, Any] | None) -> bool:
    """Whether a run config asks for OpenPose conditioning (any non-null ``controlnet_openpose`` value)."""

    return isinstance(config, Mapping) and config.get(SLOT_FIELD) is not None


def validate_openpose_intent(
    config: Mapping[str, Any] | None,
    stage_names: Sequence[str],
    *,
    backend_id: str,
    backend_supported: bool,
) -> FrozenOpenPose | None:
    """Pure admission of frozen conditioning intent before any dispatch (``None`` when there is none).

    Refuses (never ignores) conditioning on a backend that cannot run it, on a job without a base txt2img stage, and
    anything that is not exactly the record the compiler froze.
    """

    if not declared(config):
        return None
    assert config is not None
    if not backend_supported:
        raise OpenPoseDispatchError(
            CODE_BACKEND,
            f"OpenPose ControlNet conditioning is not supported on the '{backend_id}' backend, so this job was not "
            "dispatched. Use the Forge WebUI runtime, or remove the conditioning from the PromptPack slot.",
        )
    if STAGE_TXT2IMG not in tuple(str(stage) for stage in stage_names):
        raise OpenPoseDispatchError(
            CODE_STAGE,
            "OpenPose conditioning applies to the base txt2img stage only, but this job has no txt2img stage.",
        )
    try:
        return FrozenOpenPose.from_config(config.get(SLOT_FIELD))
    except OpenPoseDeclarationError as exc:
        raise OpenPoseDispatchError(
            CODE_RECORD,
            "The frozen OpenPose conditioning is invalid and was not dispatched: " + "; ".join(exc.problems),
        ) from exc


# -- runtime admission ---------------------------------------------------------------------------------------------


def resolve_advertised_model(selected: str, advertised: Sequence[str]) -> str:
    """The exact name Forge advertises for the selected ControlNet model, or ``OpenPoseDispatchError``.

    An exact match wins. Otherwise the selection matches an advertised name with its ``[hash]`` suffix and extension
    ignored, but only when that is unambiguous: two advertised models with the same stem are never resolved by picking one.
    """

    wanted = str(selected or "").strip()
    names = [str(name) for name in advertised]
    if wanted in names:
        return wanted
    key = name_key(wanted)
    matches = [name for name in names if key and name_key(name) == key]
    if len(matches) == 1:
        return matches[0]
    shown = ", ".join(names[:8]) + (" ..." if len(names) > 8 else "")
    if len(matches) > 1:
        raise OpenPoseDispatchError(
            CODE_MODEL_AMBIGUOUS,
            f"The ControlNet model '{wanted}' matches several models Forge lists ({', '.join(matches)}); "
            "remove the duplicate or choose the exact model in the PromptPack editor.",
        )
    raise OpenPoseDispatchError(
        CODE_MODEL_MISSING,
        f"Forge does not list the ControlNet model '{wanted}'. Place the SDXL OpenPose model in models/ControlNet "
        f"and refresh Forge, then rebuild Preview. Forge lists: {shown or 'no ControlNet models'}.",
    )


def admit_openpose(
    frozen: FrozenOpenPose,
    catalog: ControlNetCatalog,
    *,
    controlnet_root: Path | None,
) -> OpenPoseAdmission:
    """Check one frozen unit against what Forge advertises and what the weight file's header proves (read-only)."""

    if catalog.models is None:
        raise OpenPoseDispatchError(
            CODE_RUNTIME,
            "Forge's ControlNet extension did not answer (/controlnet/model_list), so this job was not dispatched. "
            "Enable the built-in ControlNet extension in the Forge runtime; StableNew does not install or enable it.",
        )
    unit_model = resolve_advertised_model(frozen.model, catalog.models)
    if catalog.modules is None:
        raise OpenPoseDispatchError(
            CODE_RUNTIME,
            "Forge's ControlNet module list could not be read (/controlnet/module_list), so this job was not dispatched.",
        )
    if not any(str(module).strip().lower() == PREPROCESSOR_NONE.lower() for module in catalog.modules):
        raise OpenPoseDispatchError(
            CODE_MODULE,
            "Forge's ControlNet does not advertise the 'None' preprocessor, which is required to use a pre-rendered "
            "OpenPose image; this job was not dispatched.",
        )
    sdxl: ControlNetEvidence = controlnet_evidence_for_name(controlnet_root, unit_model)
    if sdxl.status == STATUS_NOT_SDXL:
        raise OpenPoseDispatchError(
            CODE_SDXL_MISMATCH,
            f"The ControlNet model '{unit_model}' is not an SDXL model ({sdxl.detail}); an SDXL checkpoint needs an "
            "SDXL OpenPose ControlNet. This job was not dispatched.",
        )
    modality = pose_model_hint(unit_model)
    if modality.status == "incompatible":
        raise OpenPoseDispatchError(
            CODE_MODALITY,
            f"ControlNet '{unit_model}' is a known {modality.detail} model name, not an OpenPose model. "
            "SDXL tensor widths establish architecture, not pose training modality. Choose an SDXL OpenPose "
            "model and rebuild Preview; the saved selection and frozen job remain unchanged.",
        )
    return OpenPoseAdmission(
        unit_model=unit_model,
        evidence={
            "script": SCRIPT_KEY,
            "advertised_model": unit_model,
            "selected_model": frozen.model,
            "module": PREPROCESSOR_NONE,
            "controlnet_version": catalog.version,
            "model_sdxl": {"status": sdxl.status, "detail": sdxl.detail, "source": sdxl.source},
            "model_modality": {"status": modality.status, "source": modality.source, "detail": modality.detail},
        },
    )


# -- wire ----------------------------------------------------------------------------------------------------------


def build_unit(frozen: FrozenOpenPose, *, model: str, image_bytes: bytes) -> dict[str, Any]:
    """The single ControlNet unit (the exact fragment of the txt2img request; see the module docstring)."""

    return {
        "enabled": True,
        "module": PREPROCESSOR_NONE,
        "model": model,
        "image": base64.b64encode(image_bytes).decode("ascii"),
        "weight": frozen.weight,
        "guidance_start": frozen.guidance_start,
        "guidance_end": frozen.guidance_end,
        "control_mode": frozen.control_mode,
        "resize_mode": frozen.resize_mode,
        "pixel_perfect": False,
        "save_detected_map": False,
    }


def apply_openpose_wire_unit(
    config: Mapping[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The request to POST and content-free evidence (``(payload, None)`` for unconditioned work).

    The caller's ``payload`` is not mutated: it stays the unit-free copy used for manifests and logs. Re-verifies the
    job-owned snapshot by hash immediately before use and refuses an unadmitted request, a missing runtime model name or
    an ``alwayson_scripts`` entry that already claims the ControlNet slot (never overwritten, other scripts untouched).
    """

    if not declared(config):
        return payload, None
    try:
        frozen = FrozenOpenPose.from_config(config.get(SLOT_FIELD))
    except OpenPoseDeclarationError as exc:
        raise OpenPoseDispatchError(
            CODE_RECORD, "The frozen OpenPose conditioning is invalid: " + "; ".join(exc.problems)
        ) from exc
    runtime = config.get(RUNTIME_KEY)
    model = str(runtime.get("model") or "") if isinstance(runtime, Mapping) else ""
    if not model:
        raise OpenPoseDispatchError(
            CODE_UNADMITTED,
            "OpenPose conditioning reached dispatch without Forge admission; refusing to send the request.",
        )
    image_bytes = verify_frozen(frozen)  # raises OpenPoseInputError when the snapshot is missing or changed
    scripts = dict(payload.get("alwayson_scripts") or {})
    if any(str(key).strip().lower() == SCRIPT_KEY.lower() for key in scripts):
        raise OpenPoseDispatchError(
            CODE_CONFLICT,
            "The txt2img request already carries a ControlNet script entry; StableNew will not overwrite it.",
        )
    scripts[SCRIPT_KEY] = {"args": [build_unit(frozen, model=model, image_bytes=image_bytes)]}
    wire = dict(payload)
    wire["alwayson_scripts"] = scripts
    evidence = {
        **frozen.evidence(),
        "script": SCRIPT_KEY,
        "units": 1,
        "unit_model": model,
        "module": PREPROCESSOR_NONE,
        "image_sha256_sent": hashlib.sha256(image_bytes).hexdigest(),
        "pixel_perfect": False,
        "save_detected_map": False,
        "input_diagnostics": input_image_facts(image_bytes),
        "geometry": geometry_feedback(
            frozen.width, frozen.height, frozen.resize_mode,
            target=(int(payload.get("width") or 0), int(payload.get("height") or 0)),
        ),
    }
    return wire, evidence


__all__ = [
    "CODE_BACKEND",
    "CODE_CONFLICT",
    "CODE_MODEL_AMBIGUOUS",
    "CODE_MODEL_MISSING",
    "CODE_MODULE",
    "CODE_RECORD",
    "CODE_RUNTIME",
    "CODE_SDXL_MISMATCH",
    "CODE_STAGE",
    "CODE_UNADMITTED",
    "ControlNetCatalog",
    "OpenPoseAdmission",
    "OpenPoseDispatchError",
    "RUNTIME_KEY",
    "SCRIPT_KEY",
    "admit_openpose",
    "apply_openpose_wire_unit",
    "build_unit",
    "declared",
    "resolve_advertised_model",
    "validate_openpose_intent",
]
