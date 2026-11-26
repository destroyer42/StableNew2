"""The N1 warning for a checkpoint StableNew has no qualified profile for (``src/pipeline/policy_warnings.py``).

Before N1 the Forge backend refused such a checkpoint at dispatch (``ForgeUnqualifiedModelError``), after the job had
waited in the queue. Now it is a warning: the picker, the readiness line and the job record say *why* (what kind of
model it is and which separate files it needs) and *what makes it work* (which file is missing and the folder it goes
in, or which listed module to select in Forge). The job runs with Forge's module selection left exactly as it is
(owner decision N1, option a), so whatever the operator selected in Forge is used.

Pure: it formats an existing ``ModelReadiness`` verdict and reads no file, calls no endpoint and imports no Tk.
A positively identified non-checkpoint (a VAE or text encoder in the checkpoint list) is a real block, never this.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.assets.component_evidence import ROLE_TEXT_ENCODER, ROLE_VAE
from src.image_backends.model_readiness import (
    ModelReadiness,
    ReadinessStatus,
    normalize_module_name,
)
from src.pipeline.policy_warnings import CODE_IMAGE_MODEL_UNQUALIFIED, PolicyWarning

#: Forge Neo's folders for separately supplied modules, relative to the WebUI root.
MODULE_FOLDERS = {ROLE_TEXT_ENCODER: ("models", "text_encoder"), ROLE_VAE: ("models", "VAE")}
ROLE_LABELS = {ROLE_TEXT_ENCODER: "text encoder", ROLE_VAE: "VAE"}
MODULES_LEFT_AS_IS = (
    "Queue runs it anyway: StableNew leaves Forge's module selection exactly as it is for this model, so the "
    "text encoder and VAE you select in Forge are used."
)


def is_policy_refusal(readiness: ModelReadiness) -> bool:
    """True for the old dispatch refusal that N1 turns into a warning (never for a non-checkpoint file)."""

    return readiness.blocks_dispatch and readiness.status is not ReadinessStatus.NOT_A_CHECKPOINT


def module_folder(role: str, webui_root: Path | str | None) -> str:
    parts = MODULE_FOLDERS.get(role, ("models",))
    if webui_root is None or not str(webui_root).strip():
        return "Forge's " + "/".join(parts) + " folder"
    return str(Path(webui_root).joinpath(*parts))


#: Sentences of the old refusal wording that are no longer true under N1 (the fix replaces them).
_REFUSAL_MARKERS = ("refuse", "required before it can run", "no exact qualified execution profile")


def _why(readiness: ModelReadiness) -> str:
    """What the model is and any recorded verdict, without the old "it is refused" sentences."""

    text = " ".join(reason for reason in readiness.reasons if reason)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    kept = [
        part for part in sentences if not any(marker in part.lower() for marker in _REFUSAL_MARKERS)
    ]
    kept.append(
        "StableNew has no qualified profile for it, so nobody has confirmed it loads and renders correctly."
    )
    return " ".join(kept)


def _fix(readiness: ModelReadiness, webui_root: Path | str | None) -> str:
    steps: list[str] = []
    if readiness.catalog_names is None or readiness.selected_modules is None:
        needs = (
            " and ".join(item.description for item in readiness.dependencies)
            or "a separate text encoder and VAE"
        )
        steps.append(
            f"It needs {needs}. Press Check readiness beside the model picker to see which of them Forge already has."
        )
        for item in readiness.dependencies:
            steps.append(
                f"A {ROLE_LABELS.get(item.role, item.role)} goes in {module_folder(item.role, webui_root)}."
            )
    else:
        for item in readiness.dependencies:
            label = ROLE_LABELS.get(item.role, item.role.replace("_", " "))
            if not item.candidates:
                steps.append(
                    f"Missing: {item.description}. Put the file in {module_folder(item.role, webui_root)} and refresh "
                    "the model list; you can ask Claude to find and download it into that folder."
                )
            elif not item.selected:
                steps.append(
                    f"Forge lists {', '.join(item.candidates)} as a matching {label}: select it in Forge's VAE / Text "
                    "Encoder menu before this job runs."
                )
        if not steps:
            steps.append("Forge already has matching modules selected, so it may well run.")
    steps.append(MODULES_LEFT_AS_IS)
    return " ".join(steps)


def unqualified_model_warning(
    readiness: ModelReadiness, *, webui_root: Path | str | None = None
) -> PolicyWarning | None:
    """The warning for ``readiness`` when it is the old policy refusal, else ``None``."""

    if not is_policy_refusal(readiness):
        return None
    return PolicyWarning(
        code=CODE_IMAGE_MODEL_UNQUALIFIED,
        subject=readiness.checkpoint,
        title=f"{readiness.checkpoint} is not qualified.",
        why=_why(readiness),
        fix=_fix(readiness, webui_root),
        source_gate="forge.dependency_gate",
    )


# -- what the picker last showed (N1) -------------------------------------------------------------------------------
#
# The model picker's refresh worker publishes the warnings it showed; Queue reads them to record, in the job's
# provenance, the warning the operator accepted. It is a record of what was shown, never evidence that decides whether
# a job may run (the dispatch gate re-reads the checkpoint itself and runs it either way).

_SHOWN: dict[str, PolicyWarning] = {}
_SHOWN_LOCK = threading.Lock()


def _model_key(name: str | None) -> str:
    return normalize_module_name(str(name or "").split(" [", 1)[0])


def publish_shown_warnings(warnings: Mapping[str, PolicyWarning]) -> None:
    """Replace the shown-warning map with the latest picker refresh (model name -> warning)."""

    shown = {_model_key(name): warning for name, warning in warnings.items() if _model_key(name)}
    with _SHOWN_LOCK:
        _SHOWN.clear()
        _SHOWN.update(shown)


def shown_warning_for(model_name: str | None) -> PolicyWarning | None:
    key = _model_key(model_name)
    if not key:
        return None
    with _SHOWN_LOCK:
        return _SHOWN.get(key)


def shown_model_warnings(record: Any) -> tuple[PolicyWarning, ...]:
    """The shown warnings for every checkpoint an image NJR's enabled stages name (one per model)."""

    names = [getattr(record, "base_model", None)]
    names.extend(
        getattr(stage, "model", None)
        for stage in getattr(record, "stage_chain", ())
        if stage.enabled
    )
    found: dict[str, PolicyWarning] = {}
    for name in names:
        warning = shown_warning_for(name)
        if warning is not None:
            found.setdefault(warning.subject, warning)
    return tuple(found.values())


__all__ = [
    "MODULES_LEFT_AS_IS",
    "is_policy_refusal",
    "module_folder",
    "publish_shown_warnings",
    "shown_model_warnings",
    "shown_warning_for",
    "unqualified_model_warning",
]
