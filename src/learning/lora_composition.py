"""Controlled LoRA composition: one designated LoRA position varies, every other input is frozen.

Toolkit-neutral Learning contract ``learning_lora_composition/1``. The canonical PromptPack intent, target adaptation
and rendering (``resolution_layer``) stay authoritative: this module only decides *which structured LoRA contribution*
each candidate holds, refuses anything it cannot prove is a one-position change, and later checks the observed final
prompt against the whole expected LoRA set. Asset identity comes from an injected resolver over the existing
``AssetRegistry`` (cache-only in production); nothing here scans, hashes, writes or imports a toolkit.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.image_backends.forge_klein_lora import extract_lora_tags
from src.image_backends.model_policy import EVIDENCE_REGISTRY, ModelPolicy
from src.image_backends.model_policy_lora import assess_lora_selection
from src.learning.prompt_slot_experiment import (
    digest,
    expected_execution_prompts,
    slots_in,
)
from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import (
    adapt_pack_intent,
    pack_prompt_intent_to_dict,
    render_pack_intent,
    resolve_pack_intent,
    substitute_matrix_tokens,
)
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

STUDY_TYPE = "lora_composition"
CONTRACT = "learning_lora_composition/1"
VARIABLE = "LoRA Composition"
ADD_REMOVE = "add_remove"
REPLACE = "replace"
COMPARE = "compare"
OPERATIONS = (ADD_REMOVE, REPLACE, COMPARE)
OPERATION_LABELS = {ADD_REMOVE: "Add / Remove", REPLACE: "Replace", COMPARE: "Compare Candidates"}
MAX_STRENGTH = 2.0

STATUS_COMPATIBLE = "compatible"
STATUS_UNCERTAIN = "uncertain"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_MISSING = "missing"
STATUS_AMBIGUOUS = "ambiguous"

EVIDENCE_LIMITS = (
    "Verified: the frozen canonical LoRA intent, the observed final prompt readback and registry asset "
    "identity. The prompt readback is not independent proof that the backend loaded the intended LoRA bytes."
)

_ASSET_PHRASES = {
    STATUS_MISSING: "was not found in the local asset registry",
    STATUS_AMBIGUOUS: "is ambiguous: its name matches more than one local asset",
    STATUS_INCOMPATIBLE: "is incompatible with the target model",
}
_TOKEN = re.compile(r"<\s*(?:lora|lyco)\s*:[^>]*>", re.IGNORECASE)


def _key(name: str) -> str:
    return str(name).strip().casefold()


@dataclass(frozen=True)
class LoraAsset:
    """Path-free identity and compatibility evidence for one named LoRA."""

    name: str
    status: str
    sha256: str = ""
    family: str = ""
    evidence: str = ""
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.status in (STATUS_COMPATIBLE, STATUS_UNCERTAIN)

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "sha256": self.sha256,
            "family": self.family,
            "evidence": self.evidence,
        }


AssetResolver = Callable[[str], LoraAsset]


@dataclass(frozen=True)
class Candidate:
    """One assignment to the tested position; ``name`` None (or strength 0) means the position is empty."""

    name: str | None
    weight: float = 0.0

    def __post_init__(self) -> None:
        weight = float(self.weight)
        if not math.isfinite(weight) or weight < 0 or weight > MAX_STRENGTH:
            raise ValueError(f"LoRA strength must be between 0 and {MAX_STRENGTH:g}.")
        name = str(self.name).strip() if self.name is not None else ""
        if not name or weight == 0:
            name, weight = "", 0.0
        object.__setattr__(self, "name", name or None)
        object.__setattr__(self, "weight", weight)

    @property
    def text(self) -> str:
        return "No LoRA" if self.name is None else f"{self.name} @ {self.weight:g}"


@dataclass(frozen=True)
class LoraCompositionDesign:
    operation: str
    prompt: str
    candidates: tuple[Candidate, ...]
    original: str | None = None
    images_per_candidate: int = 1
    #: Explicit, fixed resolution of any Matrix slots in the source; never an experimental axis.
    fixed_slots: Mapping[str, str] = field(default_factory=dict)


def candidates_from_spec(spec: Sequence[Mapping[str, Any]]) -> tuple[Candidate, ...]:
    return tuple(Candidate(item.get("name"), item.get("weight") or 0.0) for item in spec)


def design_from_spec(spec: Mapping[str, Any], prompt: str, images: int) -> LoraCompositionDesign:
    return LoraCompositionDesign(
        str(spec.get("operation") or ""),
        prompt,
        candidates_from_spec(spec.get("candidates") or ()),
        str(spec["original"]).strip() if spec.get("original") else None,
        images,
        dict(spec.get("fixed_slots") or {}),
    )


def validate_bounds(design: LoraCompositionDesign) -> None:
    if not 2 <= len(design.candidates) <= 8:
        raise ValueError("Choose two to eight distinct candidates; none were truncated.")
    images = design.images_per_candidate
    if isinstance(images, bool) or not isinstance(images, int) or not 1 <= images <= 3:
        raise ValueError("Choose one to three images per candidate (at most 24 images).")
    seen = {(c.name and _key(c.name), c.weight) for c in design.candidates}
    if len(seen) != len(design.candidates):
        raise ValueError("Candidates must be distinct; zero strength is the same as No LoRA.")


def validate_operation(design: LoraCompositionDesign) -> None:
    names = {_key(c.name) for c in design.candidates if c.name}
    original = _key(design.original) if design.original else ""
    weights = {c.weight for c in design.candidates if c.name}
    if design.operation == ADD_REMOVE:
        if len(names) != 1:
            raise ValueError(
                "Add / Remove compares one LoRA at different strengths (including No LoRA); choose exactly one LoRA."
            )
        if original and original not in names:
            raise ValueError("The designated original must be the tested LoRA.")
    elif design.operation == REPLACE:
        if not original:
            raise ValueError(
                "Replace requires the original LoRA designated from the baseline prompt."
            )
        if any(c.name is None for c in design.candidates):
            raise ValueError("Replace does not use No LoRA; use Add / Remove to test removal.")
        if original not in names:
            raise ValueError("Include the original LoRA as the control (original) candidate.")
        if len(weights) > 1:
            raise ValueError(
                "Replacement candidates must use the same strength to isolate identity."
            )
    elif design.operation == COMPARE:
        if len(weights) > 1:
            raise ValueError(
                "Compare Candidates uses the same strength for every LoRA; use Add / Remove for different strengths."
            )
    else:
        raise ValueError("Choose Add / Remove, Replace or Compare Candidates.")


def validation_error(spec: Mapping[str, Any], prompt: str, images: int) -> str:
    """The first design-shape refusal ("" when the shape is valid); baseline-dependent checks happen at Preview."""
    try:
        design = design_from_spec(spec, prompt, images)
        validate_bounds(design)
        validate_operation(design)
    except (TypeError, ValueError) as exc:
        return str(exc)
    return ""


def require_target(
    policy: ModelPolicy, baseline: Mapping[str, Any], stage: str = "txt2img"
) -> None:
    if (
        stage != "txt2img"
        or "txt2img" not in policy.stages
        or policy.family != "sdxl"
        or policy.evidence != EVIDENCE_REGISTRY
    ):
        raise ValueError("LoRA Composition currently requires registry-verified SDXL txt2img.")
    if any(
        bool((section.get("prompt_optimizer") or {}).get("enabled"))
        for section in (baseline, baseline.get("txt2img") or {})
    ):
        raise ValueError(
            "Disable the prompt optimizer in the independent Learning baseline before Preview."
        )
    style = baseline.get("style_lora")
    if (
        isinstance(style, Mapping)
        and style.get("enabled", True)
        and any(style.get(k) for k in ("style_id", "id", "name", "lora_name"))
    ):
        raise ValueError(
            "Style Consistency is enabled in the Learning baseline; its LoRA ownership is not part of "
            "this controlled composition. Disable it before Preview."
        )


@dataclass(frozen=True)
class _Source:
    quality: str
    subject: str
    tags: tuple[tuple[str, float], ...]


def _clean(text: str, removed: bool) -> str:
    if not removed:
        return text
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"(,\s*){2,}", ", ", text)
    return text.strip().strip(",").strip()


def _split_inline(text: str) -> tuple[str, list[tuple[str, float]]]:
    if re.search(r"<\s*lyco\s*:", text, re.IGNORECASE):
        raise ValueError(
            "LyCORIS tags are not supported by LoRA Composition; use a <lora:...> tag."
        )
    tags, malformed = extract_lora_tags(text)
    if malformed:
        raise ValueError("A LoRA tag in the prompt is malformed; correct it before Preview.")
    return _clean(_TOKEN.sub("", text), bool(tags)), [(t.name, float(t.weight)) for t in tags]


def _fix_slots(text: str, fixed: Mapping[str, str]) -> str:
    values = {normalize_matrix_slot_name(k): str(v) for k, v in fixed.items()}
    for value in values.values():
        if not value.strip() or re.search(r"<[^>]*>|\[\[|\]\]", value):
            raise ValueError(
                "Fixed slot values must be plain text without LoRA, embedding or Matrix directives."
            )
    return substitute_matrix_tokens(text, values)


def baseline_loras(prompt: str) -> tuple[tuple[str, float], ...]:
    """The inline LoRA declarations of an authored prompt, for display; malformed text shows none."""
    try:
        return tuple(_split_inline(prompt)[1])
    except ValueError:
        return ()


def _resolve_source(design: LoraCompositionDesign, row: PackRow | None) -> _Source:
    if row is not None:
        if row.conditioning or row.controlnet_units:
            raise ValueError("Conditioned PromptPack rows are not supported by LoRA Composition.")
        raw = [(str(n), float(w)) for n, w in row.lora_tags]
        quality, found_q = _split_inline(_fix_slots(row.quality_line, design.fixed_slots))
        subject, found_s = _split_inline(_fix_slots(row.subject_template, design.fixed_slots))
        raw += found_q + found_s
    else:
        quality = ""
        subject, raw = _split_inline(_fix_slots(design.prompt, design.fixed_slots))
    if slots_in(quality) or slots_in(subject):
        raise ValueError(
            "The prompt still contains unresolved Matrix slots; give each slot an explicit fixed value."
        )
    counts = Counter(_key(name) for name, _ in raw)
    repeated = sorted(name for name, count in counts.items() if count > 1)
    if repeated:
        raise ValueError(
            f"LoRA '{repeated[0]}' is declared more than once across the prompt sources; resolve the "
            "duplicate before Preview (it would be silently deduplicated otherwise)."
        )
    return _Source(quality, subject, tuple(raw))


def _reconcile_stage_loras(
    baseline: Mapping[str, Any], raw: Sequence[tuple[str, float]], tested: set[str]
) -> None:
    section = baseline.get("txt2img") or {}
    declared = {_key(name): weight for name, weight in raw}
    for key in ("lora_strengths", "loras"):
        for entry in section.get(key) or ():
            if isinstance(entry, Mapping):
                if not entry.get("enabled", True):
                    continue
                name, weight = entry.get("name"), entry.get("weight", entry.get("strength", 1.0))
            elif isinstance(entry, (list, tuple)) and entry:
                name, weight = entry[0], entry[1] if len(entry) > 1 else 1.0
            else:
                continue
            if not name:
                continue
            known = declared.get(_key(str(name)))
            if (
                known is None
                or abs(float(weight or 1.0) - known) > 1e-9
                or _key(str(name)) in tested
            ):
                raise ValueError(
                    f"Baseline stage LoRA settings name '{name}', which does not match the frozen prompt's "
                    "LoRA declarations (or names the tested position). Clear stage LoRA settings before Preview."
                )


def _evidence(asset: LoraAsset) -> dict[str, str]:
    value = asset.to_dict()
    if asset.status == STATUS_UNCERTAIN:
        value["reason"] = asset.reason
    return value


def _admit_assets(
    names: Sequence[str], resolver: AssetResolver
) -> tuple[dict[str, dict[str, str]], list[str]]:
    evidence: dict[str, dict[str, str]] = {}
    notes: list[str] = []
    for name in names:
        asset = resolver(name)
        if asset.status in _ASSET_PHRASES:
            detail = f": {asset.reason}" if asset.reason else ""
            raise ValueError(f"LoRA '{name}' {_ASSET_PHRASES[asset.status]}{detail}")
        if not asset.usable:
            raise ValueError(f"LoRA '{name}' has unknown availability; refresh LoRA discovery.")
        if not re.fullmatch(r"[0-9a-f]{64}", asset.sha256 or ""):
            raise ValueError(
                f"LoRA '{name}' has no verified asset identity (SHA-256); refresh LoRA discovery first."
            )
        evidence[name] = _evidence(asset)
        if asset.status == STATUS_UNCERTAIN:
            notes.append(
                f"{name}: compatibility is not established by local evidence; pair not physically qualified."
            )
    return evidence, notes


def _admit_policy(policy: ModelPolicy, selection: Sequence[tuple[str, float]]) -> None:
    assessment = assess_lora_selection(policy, list(selection), None)
    if selection and (not assessment.supported or assessment.blocked):
        raise ValueError(f"{policy.display_name} does not support this LoRA selection.")
    if assessment.limit is not None and len(selection) > assessment.limit:
        raise ValueError(
            f"The effective LoRA set has {len(selection)} entries, above the model's LoRA limit of {assessment.limit}."
        )


def multiset(loras: Sequence[Sequence[Any]]) -> list[list[Any]]:
    return sorted([[_key(str(n)), float(w)] for n, w in loras])


def freeze_candidates(
    design: LoraCompositionDesign,
    policy: ModelPolicy,
    baseline: Mapping[str, Any],
    *,
    resolver: AssetResolver,
    negative: str = "",
    row: PackRow | None = None,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    require_target(policy, baseline)
    validate_bounds(design)
    if slots_in(negative):
        raise ValueError("The fixed negative prompt may not contain unresolved Matrix slots.")
    resolved = _resolve_source(design, row)
    raw = list(resolved.tags)
    tested = {_key(c.name) for c in design.candidates if c.name}
    original = _key(design.original) if design.original else ""
    if original:
        tested.add(original)
    _reconcile_stage_loras(baseline, raw, tested)
    position = len(raw)
    original_weight: float | None = None
    if original:
        index = next((i for i, (name, _) in enumerate(raw) if _key(name) == original), None)
        if index is None:
            raise ValueError("The designated original LoRA is not in the baseline prompt.")
        position, original_weight = index, raw[index][1]
        del raw[index]
    validate_operation(design)
    fixed = raw
    for candidate in design.candidates:
        if candidate.name and any(_key(name) == _key(candidate.name) for name, _ in fixed):
            raise ValueError(
                f"LoRA '{candidate.name}' is already in the prompt as a fixed LoRA; designate it as the "
                "original to test its removal or replacement."
            )
    if design.operation == REPLACE and original_weight is not None:
        for candidate in design.candidates:
            if (
                candidate.name
                and _key(candidate.name) == original
                and abs(candidate.weight - original_weight) > 1e-9
            ):
                raise ValueError(
                    f"The original LoRA control must keep its baseline strength ({original_weight:g})."
                )
    shown_names = list(
        dict.fromkeys([name for name, _ in fixed] + [c.name for c in design.candidates if c.name])
    )
    assets, notes = _admit_assets(shown_names, resolver)

    frozen: list[dict[str, Any]] = []
    negative_seen: set[str] = set()
    for index, candidate in enumerate(design.candidates):
        tags = list(fixed)
        if candidate.name:
            tags.insert(min(position, len(tags)), (candidate.name, candidate.weight))
        _admit_policy(policy, [(n, float(w)) for n, w in tags])
        pack_row = PackRow(
            row.embeddings if row else (),
            resolved.quality,
            resolved.subject,
            tuple(tags),
            row.negative_embeddings if row else (),
            row.negative_phrases if row else (),
        )
        intent = resolve_pack_intent(
            pack_row=pack_row, pack_negative=negative, apply_global_negative=False
        )
        if intent.triggers:
            raise ValueError("Trigger-owning contributions are not supported by LoRA Composition.")
        adapted = adapt_pack_intent(intent, policy, optimizer_enabled=False)
        if not adapted.plan.adaptable or not adapted.plan.complete or adapted.plan.changed:
            raise ValueError("Target adaptation cannot prove an unchanged one-position comparison.")
        effective = [(lora.name, float(lora.weight)) for lora in adapted.intent.loras]
        if effective != [(n, float(w)) for n, w in tags]:
            raise ValueError(
                "Target adaptation changed the LoRA set; the comparison cannot be controlled."
            )
        rendered = render_pack_intent(adapted.intent)
        positive, negative_text = expected_execution_prompts(
            rendered.positive, rendered.negative, baseline
        )
        negative_seen.add(rendered.negative)
        frozen.append(
            {
                "label": chr(65 + index),
                "name": candidate.name,
                "weight": candidate.weight,
                "label_text": candidate.text,
                "asset": assets.get(candidate.name) if candidate.name else None,
                "expected_loras": [[n, w] for n, w in effective],
                "lora_digest": digest(multiset(effective)),
                "positive": rendered.positive,
                "negative": rendered.negative,
                "expected_positive": positive,
                "expected_negative": negative_text,
                "source_intent": pack_prompt_intent_to_dict(intent),
                "adaptation": adapted.plan.to_diagnostics(),
                "effective_digest": digest([positive, negative_text]),
            }
        )
    if len({item["expected_positive"] for item in frozen}) != len(frozen):
        raise ValueError("Distinct candidates collapse to the same executable prompt.")
    if len(negative_seen) != 1:
        raise ValueError("The negative prompt must remain fixed.")
    fixed_items = [{"name": n, "weight": w, "asset": assets[n]} for n, w in fixed]
    payload = {
        "contract": CONTRACT,
        "operation": design.operation,
        "original": design.original,
        "original_weight": original_weight,
        "position": position,
        "fixed": fixed_items,
        "fixed_digest": digest(multiset(fixed)),
        "source": dict(source or {"kind": "custom"}),
        "source_digest": digest(
            [resolved.quality, resolved.subject, [list(t) for t in resolved.tags]]
        ),
        "candidates": frozen,
        "images_per_candidate": design.images_per_candidate,
        "assets": assets,
        "compatibility_notes": notes,
        "evidence_limits": EVIDENCE_LIMITS,
    }
    return {**payload, "digest": digest(payload)}


def declarations(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The structured stage declaration of a candidate's effective LoRA set (execution order)."""
    return [{"name": name, "weight": weight} for name, weight in candidate["expected_loras"]]


def frozen_section(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    section = snapshot[STUDY_TYPE]
    if section.get("contract") != CONTRACT or digest(
        {k: v for k, v in section.items() if k != "digest"}
    ) != section.get("digest"):
        raise ValueError("Frozen LoRA Composition contract is missing or corrupt.")
    return dict(section)


def frozen_candidate(snapshot: Mapping[str, Any], label: str) -> dict[str, Any]:
    section = frozen_section(snapshot)
    candidate = next((item for item in section["candidates"] if item["label"] == label), None)
    if candidate is None or label not in snapshot["variant_values"]:
        raise ValueError("Variant does not belong to this frozen LoRA Composition experiment.")
    return copy.deepcopy(candidate)


def verify_assets(snapshot: Mapping[str, Any], resolver: AssetResolver) -> None:
    """Run-time preflight: the frozen asset identity must still match the current registry evidence."""
    for name, frozen in frozen_section(snapshot)["assets"].items():
        current = resolver(name)
        if not current.usable or current.sha256 != frozen["sha256"]:
            raise ValueError(
                f"LoRA asset identity changed or is unavailable for '{name}'. "
                "No variants were admitted; rebuild Preview."
            )


def _readback_loras(prompt: str) -> tuple[Counter[str], dict[str, float]] | None:
    tags, malformed = extract_lora_tags(prompt)
    if malformed:
        return None
    counts: Counter[str] = Counter(_key(t.name) for t in tags)
    return counts, {_key(t.name): float(t.weight) for t in tags}


def readback_reason(snapshot: Mapping[str, Any], variant: Any, readback: Mapping[str, Any]) -> str:
    """ "" when the observed prompt proves the whole expected LoRA set; else a stable reason code."""
    if snapshot.get("study_type") != STUDY_TYPE:
        return ""
    try:
        section = frozen_section(snapshot)
        candidate = frozen_candidate(snapshot, variant.param_value)
        index = snapshot["variant_values"].index(variant.param_value)
        if (
            not variant.job_id
            or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
            or variant.experiment_id != snapshot["experiment_id"]
        ):
            return "lora_composition_identity_unverified"
        config = variant.executed_config or {}
        if digest(config) != snapshot["compiled_lora_composition_plan"][index]["config_digest"]:
            return "lora_composition_compiled_context_conflict"
        if (
            config.get("prompt") != candidate["positive"]
            or config.get("negative_prompt") != candidate["negative"]
        ):
            return "lora_composition_compiled_prompt_conflict"
        if "final_prompt" not in readback or "final_negative_prompt" not in readback:
            return "lora_composition_readback_unavailable"
        observed = _readback_loras(str(readback["final_prompt"]))
        if observed is None:
            return "lora_composition_unexpected_lora"
        counts, weights = observed
        expected = {_key(n): float(w) for n, w in candidate["expected_loras"]}
        considered = {_key(c["name"]) for c in section["candidates"] if c["name"]}
        if section.get("original"):
            considered.add(_key(section["original"]))
        if any(name in counts for name in considered - set(expected)):
            return "lora_composition_excluded_present"
        if any(count > 1 for count in counts.values()):
            return "lora_composition_duplicate"
        if set(counts) - set(expected):
            return "lora_composition_unexpected_lora"
        if set(expected) - set(counts):
            return "lora_composition_missing"
        if any(abs(weights[name] - weight) > 1e-9 for name, weight in expected.items()):
            return "lora_composition_strength_mismatch"
        if (
            readback["final_prompt"] != candidate["expected_positive"]
            or readback["final_negative_prompt"] != candidate["expected_negative"]
        ):
            return "lora_composition_readback_mismatch"
    except (KeyError, TypeError, ValueError, AttributeError):
        return "lora_composition_frozen_evidence_invalid"
    return ""


def rating_metadata(snapshot: Mapping[str, Any], variant: Any) -> dict[str, Any]:
    if snapshot.get("study_type") != STUDY_TYPE:
        return {}
    section = frozen_section(snapshot)
    candidate = frozen_candidate(snapshot, variant.param_value)
    execution = variant.execution_metadata or {}
    return {
        "study_type": STUDY_TYPE,
        STUDY_TYPE: {
            "contract": CONTRACT,
            "operation": section["operation"],
            "candidate_label": candidate["label"],
            "candidate_name": candidate["name"],
            "requested_strength": candidate["weight"],
            "asset": candidate["asset"],
            "fixed_digest": section["fixed_digest"],
            "expected_lora_digest": candidate["lora_digest"],
            "effective_digest": candidate["effective_digest"],
            "controlled_evidence_valid": execution.get("controlled_evidence_valid") is True,
            "runtime_lora_readback_status": str(execution.get("variable_validation_reason") or ""),
            "evidence_limits": EVIDENCE_LIMITS,
        },
        "runtime_prompt_readback": dict(execution.get("runtime_prompt_readback") or {}),
    }


def conclusion(
    plan: Sequence[Any], ratings: Mapping[str, Any], drafts: Mapping[str, Any]
) -> dict[str, Any]:
    """Experiment-local only: saved, explicitly controlled samples are the sole basis for a preference."""
    from src.learning.prompt_slot_experiment import conclusion as local_conclusion

    result = local_conclusion(plan, ratings, drafts)
    winner = result.get("best_value")
    result.update(
        study_type=STUDY_TYPE,
        comparison_claim="experiment_local_lora_preference",
        message=(
            f"Highest rated in this experiment: Candidate {winner}."
            if winner
            else "No unique highest-rated candidate with sufficient controlled saved evidence."
        )
        + " This describes the tested model, prompt, fixed LoRAs and settings; no universal best LoRA or "
        "statistical significance is claimed. Controlled means the canonical LoRA intent was observed in the "
        "prompt readback, not that the backend's loaded LoRA bytes were independently proven.",
    )
    return result


def _section_of(experiment: Any) -> dict[str, Any] | None:
    try:
        snapshot = json.loads(getattr(experiment, "execution_snapshot_json", "") or "{}")
    except (TypeError, ValueError):
        return None
    return snapshot if snapshot.get("study_type") == STUDY_TYPE else None


def visibility_prompt(experiment: Any) -> str:
    """Private input to the existing visibility classifier, never a presentation caption."""
    from src.learning.prompt_slot_experiment import visibility_prompt as slot_prompt

    try:
        snapshot = _section_of(experiment)
        if snapshot is None:
            return slot_prompt(experiment)
        return "\n".join(
            str(candidate[key])
            for candidate in snapshot[STUDY_TYPE]["candidates"]
            for key in ("expected_positive", "expected_negative")
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return "nsfw unverified lora-composition content"


def candidate_caption(experiment: Any, label: str, *, visible: bool) -> str:
    try:
        snapshot = _section_of(experiment)
        if snapshot is None:
            raise ValueError("not a LoRA Composition experiment")
        candidate = frozen_candidate(snapshot, label)
        section = frozen_section(snapshot)
    except (AttributeError, KeyError, TypeError, ValueError):
        return "Candidate LoRA evidence is unavailable or unverified."
    if not visible:
        return f"Candidate {candidate['label']}\nLoRA details hidden by content visibility."
    fixed = ", ".join(f"{item['name']} @ {item['weight']:g}" for item in section["fixed"]) or "none"
    return f"Candidate {candidate['label']}: {candidate['label_text']}\nFixed LoRAs: {fixed}"


def candidate_label_text(experiment: Any, label: str, *, visible: bool) -> str:
    """ "CharacterStyle-A @ 0.8" / "No LoRA", or a generic phrase when LoRA names are hidden."""
    try:
        snapshot = _section_of(experiment)
        if snapshot is None:
            return ""
        item = frozen_candidate(snapshot, label)
    except (AttributeError, KeyError, TypeError, ValueError):
        return "unverified"
    if item["name"] is None:
        return "No LoRA"
    return item["label_text"] if visible else f"LoRA hidden @ {item['weight']:g}"


def preview_details(section: Mapping[str, Any]) -> str:
    fixed = ", ".join(f"{i['name']} @ {i['weight']:g}" for i in section["fixed"]) or "none"
    blocks = [
        f"Operation: {OPERATION_LABELS[section['operation']]}"
        + (f"; tested original: {section['original']}" if section.get("original") else ""),
        f"Fixed LoRAs (unchanged in every candidate): {fixed}",
    ]
    for item in section["candidates"]:
        effective = ", ".join(f"{n} @ {w:g}" for n, w in item["expected_loras"]) or "none"
        asset = item["asset"]
        blocks.append(
            f"Candidate {item['label']}: {item['label_text']}\nEffective LoRAs: {effective}\n"
            + (
                f"Asset {asset['sha256'][:12]}… {asset['status']} ({asset['family'] or 'family unknown'})\n"
                if asset
                else "No tested LoRA contribution\n"
            )
            + f"Expected execution: {item['expected_positive']}"
        )
    blocks.extend(section["compatibility_notes"])
    blocks.append(section["evidence_limits"])
    return "\n\n".join(blocks)


__all__ = [
    "ADD_REMOVE",
    "COMPARE",
    "REPLACE",
    "STUDY_TYPE",
    "VARIABLE",
    "Candidate",
    "LoraAsset",
    "LoraCompositionDesign",
    "freeze_candidates",
]
