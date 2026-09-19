"""Immutable controlled-experiment seed policy helpers.

This module owns the experiment-level facts that must be resolved once during
Build Preview and then reused by every immutable NJR in that experiment.
"""

from __future__ import annotations

import itertools
import secrets
from collections.abc import Callable, Mapping
from typing import Any

from src.pipeline.resolution_layer import UnifiedPromptResolver
from src.promptpacks.storage import (
    PromptPackFormatError,
    load_prompt_pack_document,
    prompt_pack_row_by_index,
)
from src.utils.prompt_pack_utils import get_matrix_slots_dict

_MAX_A1111_SEED = (2**32) - 1


def freeze_prompt_pack_source(
    prompt_source: Mapping[str, Any], *, global_negative: str = ""
) -> dict[str, Any]:
    """Resolve one PromptPack row and its first deterministic Matrix vector."""
    source = dict(prompt_source or {})
    if str(source.get("prompt_source") or "") != "pack":
        return source
    pack_path = str(source.get("selected_prompt_pack_path") or "").strip()
    if not pack_path:
        if not str(source.get("selected_prompt_pack_name") or "").strip():
            # Pre-LEARN-300 saved sessions did not persist Pack identity.
            # Preserve their frozen prompt; the designer cannot create a new
            # Pack-backed experiment without a path.
            return source
        raise ValueError("Selected PromptPack path is unavailable for deterministic freeze")
    try:
        document = load_prompt_pack_document(pack_path)
        row = prompt_pack_row_by_index(document, int(source.get("selected_prompt_index", 0) or 0))
    except (OSError, PromptPackFormatError, ValueError) as exc:
        raise ValueError(f"Selected PromptPack cannot be frozen: {exc}") from exc
    slots = get_matrix_slots_dict(document)
    mode = str(dict(document.get("pack_data", {}).get("matrix", {}) or {}).get("mode") or "sequential")
    if slots and mode == "random":
        raise ValueError("PromptPack Matrix random mode cannot be frozen deterministically")
    vector: dict[str, str] = {}
    if slots:
        names = list(slots)
        choices = [slots[name] for name in names]
        if any(not values for values in choices):
            raise ValueError("PromptPack Matrix contains an unresolved empty slot")
        vector = dict(zip(names, next(itertools.product(*choices)), strict=True))
    resolution = UnifiedPromptResolver().resolve_from_pack(
        pack_row=row,
        matrix_slot_values=vector,
        pack_negative=str(source.get("selected_prompt_negative_text") or ""),
        global_negative=global_negative,
        apply_global_negative=True,
    )
    total = 1
    for values in slots.values():
        total *= len(values)
    source.update({
        "matrix_values": vector,
        "matrix_combination_index": 1 if slots else 0,
        "matrix_combination_total": total if slots else 0,
        "rendered_positive_prompt": resolution.positive,
        "rendered_negative_prompt": resolution.negative,
        "selected_prompt_loras": [
            {"name": name, "weight": weight} for name, weight in resolution.lora_tags
        ],
    })
    return source


def _valid_seed(value: Any) -> int | None:
    try:
        seed = int(value)
    except (TypeError, ValueError):
        return None
    return seed if 0 <= seed <= _MAX_A1111_SEED else None


def freeze_seed_policy(
    baseline_config: Mapping[str, Any],
    images_per_value: int,
    *,
    preserved_policy: Mapping[str, Any] | None = None,
    seed_supplier: Callable[[int], int] | None = None,
) -> dict[str, Any]:
    """Resolve one concrete, immutable seed/subseed vector for an experiment."""

    count = max(1, int(images_per_value or 1))
    txt2img = baseline_config.get("txt2img", {})
    txt2img = dict(txt2img) if isinstance(txt2img, Mapping) else {}
    preserved = dict(preserved_policy or {})

    requested_base = _valid_seed(preserved.get("requested_base_seed"))

    configured_seed = _valid_seed(txt2img.get("seed"))
    supplier = seed_supplier or (lambda upper: secrets.randbelow(upper + 1))
    if requested_base is None:
        requested_base = configured_seed
        if requested_base is None:
            requested_base = int(supplier(_MAX_A1111_SEED))

    try:
        subseed_strength = float(txt2img.get("subseed_strength", 0.0) or 0.0)
    except (TypeError, ValueError):
        subseed_strength = 0.0
    configured_subseed = _valid_seed(txt2img.get("subseed"))
    requested_subseed: int | None = None
    if subseed_strength > 0:
        requested_subseed = _valid_seed(preserved.get("requested_subseed"))
        if requested_subseed is None:
            requested_subseed = configured_subseed
        if requested_subseed is None:
            requested_subseed = int(supplier(_MAX_A1111_SEED))

    return {
        "policy": "requested_seed_with_backend_observed_vector",
        "requested_base_seed": requested_base,
        "requested_sample_count": count,
        "subseed_strength": subseed_strength,
        "requested_subseed": requested_subseed,
    }


def apply_frozen_seed_policy(config: dict[str, Any], policy: Mapping[str, Any]) -> None:
    """Apply frozen requested seed inputs to an isolated execution config."""

    section = config.setdefault("txt2img", {})
    if not isinstance(section, dict):
        raise ValueError("txt2img config must be an object for controlled experiments")
    requested_seed = _valid_seed(policy.get("requested_base_seed"))
    if requested_seed is None:
        raise ValueError("controlled experiment has no frozen requested seed")
    section["seed"] = requested_seed
    if float(policy.get("subseed_strength", 0.0) or 0.0) > 0:
        requested_subseed = _valid_seed(policy.get("requested_subseed"))
        if requested_subseed is None:
            raise ValueError("controlled experiment has no frozen requested subseed")
        section["subseed"] = requested_subseed


def normalize_actual_seed_vector(value: Any) -> list[int]:
    """Return a concrete backend vector, or an empty vector when unavailable."""

    if not isinstance(value, (list, tuple)):
        return []
    normalized = [_valid_seed(item) for item in value]
    return [int(item) for item in normalized] if all(item is not None for item in normalized) else []


def seed_vector_matches(policy: Mapping[str, Any], actual_seeds: Any, actual_subseeds: Any = None) -> bool:
    """Compare backend readback to an already-established observed vector."""

    expected = normalize_actual_seed_vector(policy.get("observed_seed_vector"))
    actual = normalize_actual_seed_vector(actual_seeds)
    if not expected or actual != expected:
        return False
    if float(policy.get("subseed_strength", 0.0) or 0.0) <= 0:
        return True
    return normalize_actual_seed_vector(actual_subseeds) == normalize_actual_seed_vector(policy.get("observed_subseed_vector"))
