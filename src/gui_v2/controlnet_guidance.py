"""Toolkit-neutral guidance and local readiness for ordered ControlNet units (PR-GUI-UX-550).

Pure (no Tk, no I/O). It turns what the editor *already knows* (the raw ``controlnet.v1`` declaration, the scanned
reference-map listing, header evidence for installed ControlNet weights and the configured target) into plain-language
labels, help text and an editor-level readiness report. Friendly labels are presentation only: the persisted modality
identifiers stay ``openpose``, ``canny`` and ``depth``.

Nothing here edits a declaration, builds a backend payload or asserts execution eligibility. The report is the *editor*
check only; canonical Preview (the compiler freezing every enabled reference) and Forge admission remain the authorities
and are named as such in ``SCOPE_NOTE``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.assets.controlnet_structure import (
    STATUS_NOT_SDXL,
    STATUS_SDXL,
    ControlNetModelOption,
    name_key,
)
from src.conditioning.controlnet import (
    CONTRACT,
    MAX_UNITS,
    MODALITIES,
    UNIT_CONTRACT,
    declaration_problems,
    parse_units,
)
from src.conditioning.openpose import (
    CONTROL_MODES,
    DEFAULT_CONTROL_MODE,
    DEFAULT_GUIDANCE_END,
    DEFAULT_GUIDANCE_START,
    DEFAULT_RESIZE_MODE,
    MAX_WEIGHT,
    MIN_WEIGHT,
    RESIZE_MODES,
    OpenPoseSelection,
)
from src.image_backends.forge_controlnet_units import MODEL_MODALITIES, model_problem
from src.image_backends.model_policy import EVIDENCE_REGISTRY

SEVERITY_OK = "ok"
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

STATE_NONE = "none"
STATE_INVALID = "invalid"
STATE_CONFLICT = "conflict"
STATE_DISABLED = "disabled"
STATE_BLOCKED = "blocked"
STATE_UNCONFIRMED = "unconfirmed"
STATE_LOCAL_OK = "local_ok"

#: The three readiness authorities are different questions; the editor only answers the first one.
SCOPE_NOTE = (
    "Editor check only. Preview (the compiler) validates the target and freezes each enabled reference with a SHA-256; "
    "Forge admission re-checks the models and modules the running Forge advertises before anything is sent."
)
EMPTY_LIBRARY_HELP = (
    "Add a pre-rendered OpenPose, Canny, or Depth reference image to the configured models/OpenPose library, then "
    "refresh. Choosing a purpose does not prepare or generate the image."
)
NO_PREPROCESSING_NOTE = "Preprocessor: None. StableNew passes your pre-rendered map as-is; it does not detect poses, edges or depth."
STRENGTH_HELP = (
    f"Controls how strongly the reference map influences generation ({MIN_WEIGHT:g}-{MAX_WEIGHT:g}). "
    "Higher values generally emphasize the reference more strongly."
)
GUIDANCE_HELP = (
    "Start and end (0-1, start below end) are the portion of the diffusion process during which this map is applied. "
    "0 to 1 applies it throughout."
)
CONTROL_MODE_HELP: dict[str, str] = {
    "Balanced": "Balances the prompt and the reference map.",
    "My prompt is more important": "Gives the prompt more weight relative to the map.",
    "ControlNet is more important": "Gives the map priority and can overpower the prompt.",
}
RESIZE_HELP: dict[str, str] = {
    "Just Resize": "Stretches the map to the generation size; proportions can change.",
    "Crop and Resize": "Fills the generation size and crops edges; parts of the map can be lost.",
    "Resize and Fill": "Fits the whole map and pads the borders; subject scale can change.",
}


@dataclass(frozen=True, slots=True)
class ModalityGuide:
    modality: str
    label: str
    summary: str
    use_when: str
    limit: str


MODALITY_GUIDES: tuple[ModalityGuide, ...] = (
    ModalityGuide(
        "openpose",
        "Pose / Body Position",
        "Uses an existing pre-rendered OpenPose reference to guide approximate body position and limb arrangement.",
        "Use when approximate human body position or arrangement matters.",
        "StableNew does not generate a pose map for you.",
    ),
    ModalityGuide(
        "canny",
        "Edges / Structure",
        "Uses a pre-rendered Canny-style edge map to preserve outlines, silhouettes and structural boundaries.",
        "Use when the outlines or structure of an existing reference matter.",
        "StableNew does not detect edges for you.",
    ),
    ModalityGuide(
        "depth",
        "Depth / Spatial Layout",
        "Uses a pre-rendered depth map to guide spatial relationships and approximate scene geometry.",
        "Use when approximate spatial composition or distance relationships matter.",
        "StableNew does not estimate depth for you.",
    ),
)
_GUIDES = {guide.modality: guide for guide in MODALITY_GUIDES}
MODALITY_LABELS: tuple[str, ...] = tuple(guide.label for guide in MODALITY_GUIDES)


def modality_label(modality: Any) -> str:
    """The friendly label, or the stored value untouched when it is not a supported modality."""

    guide = _GUIDES.get(modality) if isinstance(modality, str) else None
    return guide.label if guide is not None else str(modality)


def modality_from_label(label: str) -> str | None:
    return next((guide.modality for guide in MODALITY_GUIDES if guide.label == label), None)


def guide_text(modality: Any) -> str:
    guide = _GUIDES.get(modality) if isinstance(modality, str) else None
    if guide is None:
        return "Unsupported modality: this unit is kept as saved and cannot run."
    return f"{guide.summary} {guide.use_when} {guide.limit}"


def new_unit(modality: str, *, asset: str = "", model: str = "") -> dict[str, Any]:
    """A fresh unit carrying the canonical defaults (``OpenPoseSelection``); the asset is still to be chosen."""

    if modality not in MODALITIES:
        raise ValueError(f"unsupported ControlNet modality: {modality}")
    return {
        **OpenPoseSelection(asset=asset, model=model).to_dict(),
        "contract": UNIT_CONTRACT,
        "modality": modality,
    }


def advanced_is_customized(unit: Mapping[str, Any]) -> bool:
    """Whether the Advanced controls hold anything but the canonical defaults (or something unreadable)."""

    defaults: dict[str, Any] = {
        "guidance_start": DEFAULT_GUIDANCE_START,
        "guidance_end": DEFAULT_GUIDANCE_END,
        "control_mode": DEFAULT_CONTROL_MODE,
        "resize_mode": DEFAULT_RESIZE_MODE,
    }
    return any(unit.get(key, default) != default for key, default in defaults.items())


# ------------------------------------------------------------------ model candidates


@dataclass(frozen=True, slots=True)
class ModelChoice:
    name: str
    #: SDXL header evidence status for the installed weight.
    evidence: str
    #: Empty when the editor sees no reason the model cannot serve the modality; otherwise why not.
    problem: str
    ambiguous: bool = False

    @property
    def compatible(self) -> bool:
        return not self.problem and not self.ambiguous


def _installed_counts(models: Sequence[ControlNetModelOption]) -> Counter[str]:
    return Counter(name_key(option.name) for option in models)


def model_choices(
    modality: str, models: Sequence[ControlNetModelOption]
) -> tuple[ModelChoice, ...]:
    """Every installed weight with its fit for ``modality`` (a projection of ``model_problem``; nothing is hidden)."""

    counts = _installed_counts(models)
    choices = []
    for option in models:
        ambiguous = counts[name_key(option.name)] > 1
        choices.append(
            ModelChoice(
                option.name,
                option.evidence.status,
                model_problem(modality, option.name, option.evidence.status),
                ambiguous,
            )
        )
    return tuple(choices)


def recommended_model(modality: str, models: Sequence[ControlNetModelOption]) -> str | None:
    """The single installed weight that is positively SDXL *and* a documented ``modality`` model, else ``None``.

    Two candidates (or an ambiguous name) is no recommendation: the operator chooses.
    """

    fits = [choice for choice in model_choices(modality, models) if choice.compatible]
    return fits[0].name if len(fits) == 1 else None


def documented_models(modality: str) -> tuple[str, ...]:
    return tuple(name for name, known in MODEL_MODALITIES.items() if known == modality)


# ------------------------------------------------------------------ readiness


@dataclass(frozen=True, slots=True)
class UnitReadiness:
    index: int
    state: str
    summary: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConditioningReadiness:
    state: str
    units: tuple[UnitReadiness, ...]
    message: str = ""

    @property
    def text(self) -> str:
        return self.message or "\n".join(unit.summary for unit in self.units) or "No enabled units."


def describe_readiness(
    raw: Any,
    *,
    target: Any = None,
    library_identities: Collection[str] | None = None,
    library_error: str = "",
    models: Sequence[ControlNetModelOption] = (),
    resources_loaded: bool = False,
    legacy_present: bool = False,
    shown: Callable[[str], str] = str,
) -> ConditioningReadiness:
    """What the editor can say about the declaration. ``Cannot execute`` only for definite refusals.

    ``shown`` maps a library/model name to what may be displayed (the redaction hook).
    """

    if raw is None:
        return ConditioningReadiness(
            STATE_CONFLICT if legacy_present else STATE_NONE,
            (),
            (
                "This slot already uses legacy OpenPose conditioning; ordered units are unavailable until you "
                "explicitly replace it."
                if legacy_present
                else "No ControlNet units. Choose what a unit should control to add one (up to two, in order)."
            ),
        )
    problems = declaration_problems(raw)
    if problems:
        pending = [
            item.replace("asset is empty", "no reference map chosen yet") for item in problems
        ]
        awaiting = all(item.endswith("asset is empty") for item in problems)
        return ConditioningReadiness(
            STATE_INVALID,
            (),
            "Cannot execute: "
            + "; ".join(pending)
            + (
                ". Choose a reference map."
                if awaiting
                else ". The saved declaration is kept until you remove it."
            ),
        )
    counts = _installed_counts(models)
    installed = {name_key(option.name): option for option in models}
    target_blocker = (
        "Select a registry-verified SDXL checkpoint on Forge."
        if target is None or not target.executable or target.evidence != EVIDENCE_REGISTRY
        else ""
    )
    results = []
    for index, unit in enumerate(parse_units(raw)):
        prefix = f"Unit {index + 1} ({modality_label(unit.modality)}): "
        if not unit.settings.enabled:
            results.append(
                UnitReadiness(
                    index, STATE_DISABLED, prefix + "disabled; kept in the pack and not sent."
                )
            )
            continue
        blockers: list[str] = []
        unconfirmed: list[str] = []
        if legacy_present:
            blockers.append(
                "a legacy OpenPose declaration is also saved in this slot; Preview refuses both together"
            )
        if not resources_loaded:
            unconfirmed.append("refresh resources to check local availability")
        elif library_error:
            unconfirmed.append("resource refresh failed: " + library_error)
        elif library_identities is not None and unit.settings.asset not in library_identities:
            blockers.append(
                f"reference map '{shown(unit.settings.asset)}' is missing from models/OpenPose "
                "(kept in the pack)"
            )
        model = unit.settings.model
        key = name_key(model)
        if not model:
            blockers.append("choose a ControlNet model")
        elif resources_loaded and not library_error:
            if counts[key] == 0:
                blockers.append(
                    f"ControlNet model '{shown(model)}' is not installed in models/ControlNet "
                    "(kept in the pack)"
                )
            elif counts[key] > 1:
                blockers.append(
                    f"more than one installed weight is named '{shown(model)}'; admission refuses "
                    "an ambiguous model"
                )
            else:
                option = installed[key]
                known = MODEL_MODALITIES.get(key)
                if option.evidence.status == STATUS_NOT_SDXL:
                    blockers.append(
                        f"'{shown(model)}' is not an SDXL ControlNet ({option.evidence.detail})"
                    )
                elif option.evidence.status != STATUS_SDXL:
                    blockers.append(
                        f"SDXL structure of '{shown(model)}' is unverified ({option.evidence.detail}); "
                        "admission requires positive SDXL evidence"
                    )
                elif known is None:
                    blockers.append(
                        f"'{shown(model)}' is not a documented {modality_label(unit.modality)} model; "
                        f"admission accepts: {', '.join(documented_models(unit.modality))}"
                    )
                elif known != unit.modality:
                    blockers.append(
                        f"'{shown(model)}' is documented for {modality_label(known)}, not "
                        f"{modality_label(unit.modality)}"
                    )
        if target_blocker:
            blockers.append(target_blocker)
        if blockers:
            state, text = STATE_BLOCKED, "Cannot execute: " + "; ".join(blockers)
            if unconfirmed:
                text += " (also not yet confirmed: " + "; ".join(unconfirmed) + ")"
        elif unconfirmed:
            state, text = STATE_UNCONFIRMED, "Not yet confirmed: " + "; ".join(unconfirmed)
        else:
            state = STATE_LOCAL_OK
            text = "Local resources compatible; Preview and Forge admission remain required."
        results.append(UnitReadiness(index, state, prefix + text))
    states = {unit.state for unit in results}
    overall = next(
        (
            state
            for state in (STATE_BLOCKED, STATE_UNCONFIRMED, STATE_LOCAL_OK, STATE_DISABLED)
            if state in states
        ),
        STATE_NONE,
    )
    return ConditioningReadiness(overall, tuple(results))


def ordered_summary(raw: Any, shown: Callable[[str], str] = str) -> str:
    """The ordered conditioning at a glance (names, no paths); empty when the declaration is not readable."""

    if declaration_problems(raw) or raw is None:
        return ""
    lines = []
    for index, unit in enumerate(parse_units(raw)):
        settings = unit.settings
        state = "" if settings.enabled else " [disabled: not sent]"
        lines.append(
            f"{index + 1}. {modality_label(unit.modality)}: {shown(settings.asset)}, "
            f"model {shown(settings.model) or '(none)'}, strength {settings.weight:g}{state}"
        )
    return "\n".join(lines)


def unit_choice_label(index: int, unit: Mapping[str, Any]) -> str:
    suffix = "" if unit.get("enabled", True) is True else " (disabled)"
    return f"Unit {index + 1}: {modality_label(unit.get('modality', '?'))}{suffix}"


def accepts_new_unit(raw: Any) -> bool:
    return raw is None or (
        isinstance(raw, Mapping)
        and set(raw) == {"contract", "units"}
        and raw.get("contract") == CONTRACT
        and isinstance(raw.get("units"), list)
        and len(raw["units"]) < MAX_UNITS
        and all(isinstance(unit, Mapping) for unit in raw["units"])
    )


__all__ = [
    "CONTROL_MODES",
    "CONTROL_MODE_HELP",
    "EMPTY_LIBRARY_HELP",
    "GUIDANCE_HELP",
    "MODALITY_GUIDES",
    "MODALITY_LABELS",
    "NO_PREPROCESSING_NOTE",
    "RESIZE_HELP",
    "RESIZE_MODES",
    "SCOPE_NOTE",
    "STATE_BLOCKED",
    "STATE_CONFLICT",
    "STATE_DISABLED",
    "STATE_INVALID",
    "STATE_LOCAL_OK",
    "STATE_NONE",
    "STATE_UNCONFIRMED",
    "STRENGTH_HELP",
    "ConditioningReadiness",
    "ModalityGuide",
    "ModelChoice",
    "UnitReadiness",
    "accepts_new_unit",
    "advanced_is_customized",
    "describe_readiness",
    "documented_models",
    "guide_text",
    "model_choices",
    "modality_from_label",
    "modality_label",
    "new_unit",
    "ordered_summary",
    "recommended_model",
    "unit_choice_label",
]
