"""PromptPack editor readiness (PR-IMG-MODELS-158): structure and target readiness are different answers.

*Structural validity* says the authored pack is well formed. *Target readiness* says what the selected target's exact
profile will refuse or adapt when the compiler later runs. This module evaluates both from the editor's **in-memory**
pack (never an older on-disk copy) and from the canonical ``ModelPolicy``/adaptation/profile validators, and it is pure:
no Tk, file, network, scan, hash or write. It never mutates, adapts or saves the pack and it states its own limits.

It deliberately does *not* claim execution readiness. The compiler consumes the pack's saved file plus the Pipeline-tab
stage selection and the Override-pack-configs choice, which an editor does not own. Rebuilding that controller-owned
configuration here would be a second compile authority, so the final answer stays with Preview/the compiler.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.image_backends.exact_model_profile import profile_prompt_refusal
from src.image_backends.model_policy import ModelPolicy, resolve_model_profile_for_policy
from src.image_backends.operation_compatibility import OperationRequest, assess_operation
from src.prompting.prompt_adaptation import (
    EFFECT_DROPPED,
    EFFECT_REWRITTEN,
    PromptAdaptationInput,
    adapt_prompt_for_target,
)
from src.prompting.prompt_compatibility import target_is_unverified, target_label

_MATRIX_MARKER = re.compile(r"\[\[\s*([^\[\]\n]+?)\s*\]\]")
_MAX_VARIANTS = 64


@dataclass(frozen=True, slots=True)
class PackStructure:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class PackReadiness:
    #: ``"unsaved editor state"`` or ``"saved pack file"``: exactly which version was evaluated.
    evaluated: str
    structure: PackStructure
    target_label: str
    #: What the target's exact profile/compiler will refuse for this pack as authored.
    refusals: tuple[str, ...] = ()
    #: What the compiler will adapt or omit (the saved pack is never changed): stable operation codes.
    notes: tuple[str, ...] = ()
    #: ``False`` when no exact evidence exists for the target (nothing is claimed or refused).
    target_checked: bool = False
    limits: str = ""

    @property
    def clean(self) -> bool:
        return self.structure.valid and not self.refusals

    def lines(self) -> tuple[str, ...]:
        out = [f"Evaluated: {self.evaluated}.", "Structure: valid." if self.structure.valid else "Structure: INVALID."]
        out.extend(f"  - {item}" for item in (*self.structure.errors, *self.structure.warnings))
        out.append(self.target_label)
        if not self.target_checked:
            out.append("  - No exact capability evidence for this target; nothing is claimed or refused here.")
        out.extend(f"  - Will be refused: {item}" for item in self.refusals)
        out.extend(f"  - Will be adapted at compile (pack unchanged): {item}" for item in self.notes)
        if self.limits:
            out.append(self.limits)
        return tuple(out)


def validate_pack_structure(pack: Any) -> PackStructure:
    """Structural checks of the in-memory pack's Matrix (the checks Validate was always meant to run)."""

    errors: list[str] = []
    warnings: list[str] = []
    matrix = getattr(pack, "matrix", None)
    if matrix is not None and getattr(matrix, "enabled", False):
        slots = list(getattr(matrix, "slots", []) or [])
        if not slots:
            warnings.append("Matrix enabled but no slots defined")
        for slot in slots:
            name = str(getattr(slot, "name", "") or "")
            if not name:
                errors.append("Matrix slot missing name")
            elif not getattr(slot, "values", None):
                warnings.append(f"Matrix slot '{name}' has no values")
    return PackStructure(tuple(errors), tuple(warnings))


def _marker_filler(chosen: Mapping[str, str]) -> Callable[[re.Match[str]], str]:
    return lambda match: chosen.get(match.group(1).strip(), "x")


def _variants(text: str, matrix_values: Mapping[str, tuple[str, ...]]) -> Iterable[str]:
    """The authored text with each Matrix marker replaced by each of its values (bounded; one slot varied at a time)."""

    names = [match.group(1) for match in _MATRIX_MARKER.finditer(text)]
    if not names:
        yield text
        return
    firsts = {name: (matrix_values.get(name) or ("x",))[0] for name in names}
    produced = 0
    for name in dict.fromkeys(names):
        for value in matrix_values.get(name) or ("x",):
            chosen = {**firsts, name: value}
            yield _MATRIX_MARKER.sub(_marker_filler(chosen), text)
            produced += 1
            if produced >= _MAX_VARIANTS:
                return


def _saved_geometry(preset: Mapping[str, Any]) -> tuple[int | None, int | None]:
    nested = preset.get("txt2img")
    section: Mapping[str, Any] = nested if isinstance(nested, Mapping) else preset
    try:
        return int(section["width"]), int(section["height"])
    except (KeyError, TypeError, ValueError):
        return None, None


def assess_pack_readiness(
    pack: Any,
    policy: ModelPolicy,
    *,
    model_name: str | None,
    backend_id: str | None,
    dirty: bool,
    render_text: Callable[[Any], str] = lambda slot: str(getattr(slot, "text", "") or ""),
    lora_resolver: Any = None,
) -> PackReadiness:
    """Evaluate one in-memory pack against one selected target. Pure; mutates nothing."""

    refusals: list[str] = []
    if policy.qualified:
        width, height = _saved_geometry(getattr(pack, "preset_data", {}) or {})
        assessment = assess_operation(
            policy,
            OperationRequest(stages=("txt2img",), backend_id=backend_id, width=width, height=height),
        )
        refusals.extend(problem.message for problem in assessment.problems)

    profile = resolve_model_profile_for_policy(policy)
    matrix_values = {
        str(getattr(slot, "name", "")): tuple(str(v) for v in (getattr(slot, "values", None) or ()))
        for slot in (getattr(getattr(pack, "matrix", None), "slots", None) or [])
        if getattr(slot, "name", "")
    }
    adapted: set[str] = set()
    incomplete = False
    for slot in getattr(pack, "slots", []) or []:
        text = render_text(slot)
        negative = str(getattr(slot, "negative", "") or "")
        if not (text.strip() or negative.strip()):
            continue
        plan = adapt_prompt_for_target(
            policy,
            PromptAdaptationInput(
                positive_text=text,
                negative_text=negative,
                positive_embeddings=tuple(getattr(slot, "positive_embeddings", ()) or ()),
                negative_embeddings=tuple(getattr(slot, "negative_embeddings", ()) or ()),
                loras=tuple((str(n), float(w)) for n, w in (getattr(slot, "loras", ()) or ())),
            ),
            lora_resolver=lora_resolver,
        )
        adapted.update(
            operation.code
            for operation in plan.operations
            if operation.effect in {EFFECT_REWRITTEN, EFFECT_DROPPED}
        )
        if plan.adaptable and not plan.complete:
            incomplete = True
        if plan.adaptable and profile is not None:
            for variant in _variants(plan.positive_text, matrix_values):
                message = profile_prompt_refusal(profile, variant)
                if message:
                    refusals.append(f"row {int(getattr(slot, 'index', 0)) + 1}: {message}")
                    break
    return PackReadiness(
        evaluated="unsaved editor state" if dirty else "saved pack file",
        structure=validate_pack_structure(pack),
        target_label=target_label(policy, model_name),
        refusals=tuple(dict.fromkeys(refusals)),
        notes=(*sorted(adapted), *(("lora_evidence_incomplete_kept_unchanged",) if incomplete else ())),
        target_checked=policy.qualified or not target_is_unverified(policy),
        limits=(
            "Execution readiness is confirmed by Preview: the compiler also applies the Pipeline-tab stages, "
            "'Override pack configs' and the saved settings. Nothing here was changed or saved."
        ),
    )


__all__ = ["PackReadiness", "PackStructure", "assess_pack_readiness", "validate_pack_structure"]
