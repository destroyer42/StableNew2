"""Controlled, frozen one-slot prompt intent; canonical Matrix/adaptation remain authoritative."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.image_backends.model_policy import EVIDENCE_REGISTRY, ModelPolicy
from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import (
    MATRIX_TOKEN_RE,
    adapt_pack_intent,
    pack_prompt_intent_to_dict,
    render_pack_intent,
    resolve_pack_intent,
    substitute_matrix_tokens,
)
from src.utils.negative_helpers_v2 import merge_global_negative, merge_global_positive
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

STUDY_TYPE = "prompt_slot"
CONTRACT = "learning_prompt_slot/1"
VARIABLE = "Prompt Slot"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class PromptSlotDesign:
    template: str
    slot: str
    candidates: tuple[str, ...]
    fixed_slots: Mapping[str, str] = field(default_factory=dict)
    images_per_candidate: int = 1


def slots_in(template: str) -> tuple[str, ...]:
    for match in MATRIX_TOKEN_RE.finditer(template):
        if (match.start() and template[match.start() - 1] == "[") or (
            match.end() < len(template) and template[match.end()] == "]"
        ):
            raise ValueError("Malformed or nested Matrix placeholder. Use [[slot_name]].")
    residue = MATRIX_TOKEN_RE.sub("", template)
    if "[[" in residue or "]]" in residue:
        raise ValueError("Malformed or nested Matrix placeholder. Use [[slot_name]].")
    return tuple(
        dict.fromkeys(
            normalize_matrix_slot_name(m.group(1)) for m in MATRIX_TOKEN_RE.finditer(template)
        )
    )


def validate_design(design: PromptSlotDesign, *, embedding_names: Sequence[str] = ()) -> None:
    slots = slots_in(design.template)
    selected = normalize_matrix_slot_name(design.slot)
    if not selected or selected not in slots:
        raise ValueError("The selected named slot must occur in the prompt template.")
    fixed: dict[str, str] = {}
    for name, value in design.fixed_slots.items():
        key = normalize_matrix_slot_name(name)
        if not key or (key in fixed and fixed[key] != value):
            raise ValueError("Fixed-slot aliases have conflicting or invalid values.")
        fixed[key] = value
    if selected in fixed or any(
        not isinstance(fixed.get(k), str) or not fixed[k].strip() for k in slots if k != selected
    ):
        raise ValueError("Choose an explicit fixed value for every non-tested slot.")
    if not 2 <= len(design.candidates) <= 8:
        raise ValueError("Choose two to eight distinct candidates; no candidates were truncated.")
    if (
        isinstance(design.images_per_candidate, bool)
        or not isinstance(design.images_per_candidate, int)
        or not 1 <= design.images_per_candidate <= 3
    ):
        raise ValueError("Choose one to three images per candidate (at most 24 images).")
    seen = set()
    for text in (*design.candidates, *fixed.values()):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Candidate and fixed-slot text must not be empty.")
        if (
            "[[" in text
            or "]]" in text
            or re.search(r"<[^>]*>|\bembedding\s*:|__[^_]+__", text, re.IGNORECASE)
        ):
            raise ValueError(
                "Slot text may not introduce Matrix tokens or structured control directives."
            )
        if re.search(
            r"\([^()]*:\s*[+-]?\d+(?:\.\d+)?\s*\)|\[[^\]]*:[^\]]*:\s*\d+(?:\.\d+)?\s*\]|\bBREAK\b",
            text,
        ):
            raise ValueError(
                "Slot text may not introduce attention, scheduling or prompt-break directives."
            )
        if any(
            re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE)
            for name in embedding_names
            if name
        ):
            raise ValueError("Slot text may not introduce a registered embedding.")
    for text in design.candidates:
        # Whitespace-only differences are not a second candidate. Case remains intentional.
        key = text.strip()
        if key in seen:
            raise ValueError("Candidate values must be distinct.")
        seen.add(key)


def require_target(
    policy: ModelPolicy, baseline: Mapping[str, Any], stage: str = "txt2img"
) -> None:
    if (
        stage != "txt2img"
        or "txt2img" not in policy.stages
        or policy.family != "sdxl"
        or policy.evidence != EVIDENCE_REGISTRY
    ):
        raise ValueError("Prompt Slot currently requires registry-verified SDXL txt2img.")
    if any(
        bool((section.get("prompt_optimizer") or {}).get("enabled"))
        for section in (baseline, baseline.get("txt2img") or {})
    ):
        raise ValueError(
            "Disable the prompt optimizer in the independent Learning baseline before Preview."
        )


def freeze_candidates(
    design: PromptSlotDesign,
    policy: ModelPolicy,
    baseline: Mapping[str, Any],
    *,
    negative: str = "",
    row: PackRow | None = None,
    source: Mapping[str, Any] | None = None,
    embedding_names: Sequence[str] = (),
) -> dict[str, Any]:
    require_target(policy, baseline)
    validate_design(design, embedding_names=embedding_names)
    if slots_in(negative):
        raise ValueError("The fixed negative prompt may not contain unresolved Matrix slots.")
    pack_row = row or PackRow((), "", design.template, (), (), ())
    if pack_row.conditioning or pack_row.controlnet_units:
        raise ValueError(
            "Conditioned PromptPack rows are not supported by Prompt Slot experiments."
        )
    template = (pack_row.quality_line + " " + pack_row.subject_template) if row else design.template
    if slots_in(template) != slots_in(design.template):
        raise ValueError(
            "The selected row differs from the authored slot design; refresh the source."
        )
    candidates = []
    selected = normalize_matrix_slot_name(design.slot)
    fixed = {normalize_matrix_slot_name(k): v for k, v in design.fixed_slots.items()}
    for index, value in enumerate(design.candidates):
        vector = {**fixed, selected: value}
        intent = resolve_pack_intent(
            pack_row=pack_row,
            matrix_slot_values=vector,
            pack_negative=negative,
            apply_global_negative=False,
        )
        adapted = adapt_pack_intent(intent, policy, optimizer_enabled=False)
        if not adapted.plan.adaptable or not adapted.plan.complete or adapted.plan.changed:
            raise ValueError("Target adaptation cannot prove an unchanged one-slot comparison.")
        rendered = render_pack_intent(adapted.intent)
        if slots_in(rendered.positive) or slots_in(rendered.negative):
            raise ValueError("Preview contains unresolved Matrix slots.")
        observed_positive, observed_negative = expected_execution_prompts(
            rendered.positive, rendered.negative, baseline
        )
        if slots_in(observed_positive) or slots_in(observed_negative):
            raise ValueError("Frozen global prompt content contains unresolved Matrix slots.")
        candidates.append(
            {
                "label": chr(65 + index),
                "value": value,
                "authored": substitute_matrix_tokens(design.template, vector),
                "positive": rendered.positive,
                "negative": rendered.negative,
                "expected_positive": observed_positive,
                "expected_negative": observed_negative,
                "source_intent": pack_prompt_intent_to_dict(intent),
                "adaptation": adapted.plan.to_diagnostics(),
                "effective_digest": digest([observed_positive, observed_negative]),
            }
        )
    if len({item["expected_positive"] for item in candidates}) != len(candidates):
        raise ValueError("Distinct source candidates collapse to the same executable prompt.")
    if len({item["negative"] for item in candidates}) != 1:
        raise ValueError("The negative prompt must remain fixed.")
    payload = {
        "contract": CONTRACT,
        "slot": selected,
        "template": design.template,
        "fixed_slots": fixed,
        "source": dict(source or {"kind": "custom"}),
        "candidates": candidates,
        "images_per_candidate": design.images_per_candidate,
    }
    return {**payload, "digest": digest(payload)}


def expected_execution_prompts(
    positive: str, negative: str, config: Mapping[str, Any]
) -> tuple[str, str]:
    from src.pipeline.global_prompt_policy import frozen_global_positive_policy

    terms, enabled = frozen_global_positive_policy(config)
    if enabled:
        positive = merge_global_positive(positive, terms)[1]
    if (config.get("pipeline") or {}).get("apply_global_negative_txt2img", False):
        negative = merge_global_negative(negative, config.get("global_negative_prompt"))[1]
    return positive, negative


def frozen_candidate(snapshot: Mapping[str, Any], label: str) -> dict[str, Any]:
    section = snapshot[STUDY_TYPE]
    if section.get("contract") != CONTRACT or digest(
        {k: v for k, v in section.items() if k != "digest"}
    ) != section.get("digest"):
        raise ValueError("Frozen Prompt Slot contract is missing or corrupt.")
    candidate = next((item for item in section["candidates"] if item["label"] == label), None)
    if candidate is None or label not in snapshot["variant_values"]:
        raise ValueError("Variant does not belong to this frozen Prompt Slot experiment.")
    return copy.deepcopy(candidate)


def prompt_readback_reason(
    snapshot: Mapping[str, Any], variant: Any, readback: Mapping[str, Any]
) -> str:
    if snapshot.get("study_type") != STUDY_TYPE:
        return ""
    try:
        candidate = frozen_candidate(snapshot, variant.param_value)
        index = snapshot["variant_values"].index(variant.param_value)
        if (
            not variant.job_id
            or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
            or variant.experiment_id != snapshot["experiment_id"]
        ):
            return "prompt_slot_identity_unverified"
        config = variant.executed_config or {}
        if digest(config) != snapshot["compiled_prompt_slot_plan"][index]["config_digest"]:
            return "prompt_slot_compiled_context_conflict"
        if (
            config.get("prompt") != candidate["positive"]
            or config.get("negative_prompt") != candidate["negative"]
        ):
            return "prompt_slot_compiled_prompt_conflict"
        if "final_prompt" not in readback or "final_negative_prompt" not in readback:
            return "prompt_slot_readback_unavailable"
        if (
            readback["final_prompt"] != candidate["expected_positive"]
            or readback["final_negative_prompt"] != candidate["expected_negative"]
        ):
            return "prompt_slot_readback_mismatch"
    except (KeyError, TypeError, ValueError):
        return "prompt_slot_frozen_evidence_invalid"
    return ""


def rating_metadata(snapshot: Mapping[str, Any], variant: Any) -> dict[str, Any]:
    if snapshot.get("study_type") != STUDY_TYPE:
        return {}
    candidate = frozen_candidate(snapshot, variant.param_value)
    return {
        "study_type": STUDY_TYPE,
        "prompt_slot": {
            "contract": CONTRACT,
            "slot": snapshot[STUDY_TYPE]["slot"],
            "candidate_label": candidate["label"],
            "candidate_value": candidate["value"],
            "effective_digest": candidate["effective_digest"],
        },
        "runtime_prompt_readback": dict(
            (variant.execution_metadata or {}).get("runtime_prompt_readback") or {}
        ),
    }


def conclusion(
    plan: Sequence[Any], ratings: Mapping[str, Any], drafts: Mapping[str, Any]
) -> dict[str, Any]:
    """Only saved, explicitly controlled, exact sample associations support a local preference."""
    import statistics

    rows, saved, draft_count, total = [], 0, 0, 0
    all_controlled = True
    for variant in plan:
        valid = variant.execution_metadata.get("controlled_evidence_valid") is True
        all_controlled = all_controlled and valid
        values = []
        for path in variant.image_refs:
            total += 1
            detail = ratings.get(path) or {}
            rating = detail.get("overall_rating", 0)
            if (
                isinstance(rating, (int, float))
                and not isinstance(rating, bool)
                and 1 <= rating <= 5
            ):
                saved += 1
                if valid:
                    values.append(float(rating))
            elif any(str(key).endswith(f":{path}") for key in drafts):
                draft_count += 1
        rows.append(
            {
                "value": variant.param_value,
                "sample_count": len(variant.image_refs),
                "saved_count": len(values),
                "controlled": valid,
                "average_overall": statistics.mean(values) if values else None,
                "rating_stddev": statistics.stdev(values) if len(values) > 1 else None,
                "rating_distribution": {str(i): values.count(float(i)) for i in range(1, 6)},
                "average_subscores": {},
            }
        )
    eligible = all_controlled and len(rows) >= 2 and all(row["saved_count"] for row in rows)
    best = max((row["average_overall"] for row in rows), default=None) if eligible else None
    winners = [row["value"] for row in rows if row["average_overall"] == best] if eligible else []
    winner = winners[0] if len(winners) == 1 else None
    return {
        "study_type": STUDY_TYPE,
        "controlled_valid": all_controlled,
        "comparison_claim": "experiment_local_prompt_preference",
        "causal_one_variable": True,
        "saved": saved,
        "draft": draft_count,
        "unrated": max(0, total - saved - draft_count),
        "values": rows,
        "best_value": winner,
        "sufficient_evidence": eligible,
        "message": (
            f"Highest rated in this experiment: Candidate {winner}."
            if winner
            else "No unique highest-rated candidate with sufficient controlled saved evidence."
        )
        + " This describes the tested model, prompt and settings; no universal optimum or statistical significance is claimed.",
    }


def visibility_prompt(experiment: Any) -> str:
    """Private input to the existing visibility classifier, never a presentation caption."""
    try:
        snapshot = json.loads(experiment.execution_snapshot_json or "{}")
        if snapshot.get("study_type") == STUDY_TYPE:
            return "\n".join(
                str(candidate[key])
                for candidate in snapshot[STUDY_TYPE]["candidates"]
                for key in ("expected_positive", "expected_negative")
            )
    except (AttributeError, KeyError, TypeError, ValueError):
        return "nsfw unverified prompt-slot content"
    return str(getattr(experiment, "prompt_text", "") or "")


def candidate_caption(experiment: Any, label: str, *, visible: bool) -> str:
    try:
        candidate = frozen_candidate(json.loads(experiment.execution_snapshot_json), label)
    except (AttributeError, KeyError, TypeError, ValueError):
        return "Candidate prompt evidence is unavailable or unverified."
    return f"Candidate {candidate['label']}\n" + (
        candidate["value"] if visible else "Prompt text hidden by content visibility."
    )
