"""Toolkit-neutral presentation of a slot's OpenPose conditioning (PR-IMG-CNET-210).

Pure (no Tk, no I/O). Given the slot's raw declaration and what the editor *already knows* (the configured target's
eligibility, the scanned library listing and the ControlNet model's header evidence) it says what the operator should see
and whether the selection would be executable. It is a projection, never an authority: the compiler and the backend
independently enforce the same rules, and nothing here edits, clears or saves a declaration.

A saved selection that a target cannot run is always *shown* (with the reason) and never removed.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from src.assets.controlnet_structure import STATUS_NOT_SDXL, STATUS_SDXL, STATUS_UNVERIFIED
from src.conditioning.openpose import (
    CONTRACT,
    OpenPoseSelection,
    declaration_problems,
    parse_declaration,
)
from src.conditioning.openpose_diagnostics import geometry_feedback, pose_model_hint
from src.image_backends.openpose_capability import (
    STATUS_SUPPORTED,
    STATUS_UNSUPPORTED,
    OpenPoseTarget,
)
from src.image_backends.openpose_capability import (
    STATUS_UNVERIFIED as TARGET_UNVERIFIED,
)

SEVERITY_OK = "ok"
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
#: Model-status value the view uses for "the installed list was read and the selected model is not in it". It is
#: positive evidence of absence. ``None`` means the evidence is unavailable (not scanned, folder unreadable/empty) and
#: never blocks: the backend still resolves the model against what the running Forge advertises.
MODEL_MISSING = "missing"


@dataclass(frozen=True, slots=True)
class StatusLine:
    severity: str
    text: str


@dataclass(frozen=True, slots=True)
class OpenPoseView:
    #: ``True`` only when the declaration is valid, enabled, complete and the target can run it.
    executable: bool
    lines: tuple[StatusLine, ...]
    selection: OpenPoseSelection | None = None

    @property
    def worst(self) -> str:
        order = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO, SEVERITY_OK)
        present = {line.severity for line in self.lines}
        return next((level for level in order if level in present), SEVERITY_INFO)


def describe_openpose(
    raw: Any,
    *,
    target: OpenPoseTarget | None = None,
    library_identities: Collection[str] | None = None,
    model_status: str | None = None,
    image_facts: Mapping[str, Any] | None = None,
) -> OpenPoseView:
    """The editor view of one raw slot declaration (``None`` means the slot has no conditioning)."""

    if raw is None:
        return OpenPoseView(False, ())
    problems = declaration_problems(raw)
    if problems:
        return OpenPoseView(
            False,
            (
                StatusLine(
                    SEVERITY_ERROR,
                    "The saved OpenPose declaration is not valid and was kept unchanged: "
                    + "; ".join(problems)
                    + ". Remove it and choose the pose image again.",
                ),
            ),
        )
    selection = parse_declaration(raw)
    if not selection.enabled:
        return OpenPoseView(
            False,
            (StatusLine(SEVERITY_INFO, "OpenPose conditioning is switched off for this slot; the selection is kept."),),
            selection,
        )
    lines: list[StatusLine] = []
    blocked = False
    if library_identities is not None and selection.asset not in library_identities:
        blocked = True
        lines.append(
            StatusLine(
                SEVERITY_WARNING,
                f"'{selection.asset}' is not in the OpenPose library (models/OpenPose). It is kept in the pack, "
                "but the job cannot run until the image is restored or another one is chosen.",
            )
        )
    if not selection.model:
        blocked = True
        lines.append(StatusLine(SEVERITY_WARNING, "Choose a ControlNet model (an SDXL OpenPose model)."))
    elif model_status == MODEL_MISSING:
        # Known-missing (the installed list was read and the model is not in it) is not "unknown": it cannot run.
        blocked = True
        lines.append(
            StatusLine(
                SEVERITY_ERROR,
                f"ControlNet model '{selection.model}' is not installed in models/ControlNet. The selection is kept, but "
                "the job cannot run until the model is installed or another one is chosen.",
            )
        )
    elif model_status == STATUS_NOT_SDXL:
        blocked = True
        lines.append(
            StatusLine(
                SEVERITY_ERROR,
                f"ControlNet model '{selection.model}' is not an SDXL model; an SDXL checkpoint needs an SDXL OpenPose model.",
            )
        )
    elif model_status == STATUS_UNVERIFIED:
        lines.append(
            StatusLine(
                SEVERITY_INFO,
                f"ControlNet model '{selection.model}': SDXL compatibility is unverified (its header does not identify it).",
            )
        )
    elif model_status == STATUS_SDXL:
        lines.append(StatusLine(SEVERITY_OK, f"ControlNet model '{selection.model}' is identified as SDXL."))
    if selection.model:
        modality = pose_model_hint(selection.model)
        if modality.status == "incompatible":
            blocked = True
            lines.append(StatusLine(
                SEVERITY_ERROR,
                f"'{selection.model}' is a known {modality.detail} model name and cannot consume an OpenPose map. "
                "SDXL architecture evidence is not pose-modality evidence. Choose an SDXL OpenPose model; "
                "the saved choice is kept.",
            ))
        else:
            lines.append(StatusLine(
                SEVERITY_WARNING,
                "OpenPose training modality is unverified; SDXL tensor widths and a model name do not qualify it. "
                "Confirm the model's documented input is a pre-rendered OpenPose map.",
            ))
    lines.append(StatusLine(
        SEVERITY_INFO,
        "Preprocessor None passes the supplied pixels; a photograph, depth map or stylized skeleton is not "
        "automatically converted to the model's OpenPose format. Use its documented colored skeleton on black.",
    ))
    mode_help = {
        "Balanced": "balances prompt and pose influence",
        "My prompt is more important": "reduces pose priority relative to the prompt",
        "ControlNet is more important": "prioritizes conditioning and can overpower the prompt",
    }
    lines.append(StatusLine(
        SEVERITY_INFO,
        f"Strength {selection.weight:g}, guidance {selection.guidance_start:g}-{selection.guidance_end:g}. "
        f"{selection.control_mode} {mode_help[selection.control_mode]}. Increasing strength/end can exaggerate "
        "conditioning; it cannot repair a model/input mismatch. Saved values are unchanged.",
    ))
    if image_facts is not None:
        lines.append(StatusLine(SEVERITY_INFO, geometry_feedback(
            int(image_facts["width"]), int(image_facts["height"]), selection.resize_mode,
        )))
        if image_facts.get("has_transparency"):
            lines.append(StatusLine(
                SEVERITY_WARNING,
                "This map has transparent pixels. Pinned Forge composites them on white, not black; use an "
                "opaque map with the model's documented background. StableNew does not rewrite it.",
            ))
    if target is not None:
        if target.status == STATUS_SUPPORTED:
            lines.append(StatusLine(SEVERITY_OK, "The selected checkpoint and backend can run OpenPose conditioning."))
        elif target.status == TARGET_UNVERIFIED:
            blocked = True
            lines.append(StatusLine(SEVERITY_INFO, target.message))
        elif target.status == STATUS_UNSUPPORTED:
            blocked = True
            lines.append(StatusLine(SEVERITY_WARNING, f"{target.message} Your selection is kept and will not be sent."))
    return OpenPoseView(not blocked and target is not None and target.executable, tuple(lines), selection)


def effective_summary(selection: OpenPoseSelection) -> tuple[str, ...]:
    """Short, human-readable effective settings for the prompt preview (no paths, no content)."""

    return (
        f"Pose image: {selection.asset}",
        f"ControlNet model: {selection.model or '(none selected)'}",
        f"Weight {selection.weight:g}, guidance {selection.guidance_start:g}-{selection.guidance_end:g}, "
        f"control mode '{selection.control_mode}', resize '{selection.resize_mode}'",
        f"Preprocessor: {selection.preprocessor} (pre-rendered OpenPose map)",
        "SDXL compatibility does not establish OpenPose training modality; use a documented SDXL OpenPose model.",
    )


def declaration_from_view(
    current: Mapping[str, Any] | None,
    **changes: Any,
) -> dict[str, Any]:
    """A copy of ``current`` with ``changes`` applied, always carrying the contract marker (editor edit helper)."""

    updated = dict(current or {})
    updated.update(changes)
    updated["contract"] = CONTRACT
    updated.setdefault("preprocessor", "None")
    return updated


__all__ = [
    "MODEL_MISSING",
    "OpenPoseView",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_OK",
    "SEVERITY_WARNING",
    "StatusLine",
    "declaration_from_view",
    "describe_openpose",
    "effective_summary",
]
