"""Helpers for building model/hypernetwork variant runs."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from typing import Any


@dataclass(frozen=True)
class VariantSpec:
    """Concrete model/hypernetwork combination to apply to a prompt run."""

    index: int
    model: str | None
    hypernetwork: str | None
    hypernetwork_strength: float | None

    @property
    def label(self) -> str:
        """Human readable description."""

        model_part = f"model={self.model}" if self.model else "model=base"
        if self.hypernetwork:
            hyper_part = f"hyper={self.hypernetwork}" + (
                f" ({self.hypernetwork_strength:.2f})"
                if self.hypernetwork_strength is not None
                else ""
            )
        else:
            hyper_part = "hyper=off"
        return f"{model_part} | {hyper_part}"


@dataclass(frozen=True)
class VariantPlan:
    """Describes how to iterate variant combinations."""

    mode: str
    variants: list[VariantSpec]

    @property
    def active(self) -> bool:
        return bool(self.variants)


def _clean_matrix_entries(raw: Iterable[Any]) -> list[str]:
    cleaned: list[str] = []
    for entry in raw or []:
        if entry is None:
            continue
        text = str(entry).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _clean_hypernet_entries(raw: Iterable[Any]) -> list[tuple[str | None, float | None]]:
    cleaned: list[tuple[str | None, float | None]] = []
    for entry in raw or []:
        if isinstance(entry, dict):
            name = entry.get("name")
            strength = entry.get("strength")
        else:
            name = entry
            strength = None
        if name is None:
            continue
        text = str(name).strip()
        if not text:
            continue
        if text.lower() == "none":
            cleaned.append((None, None))
        else:
            try:
                strength_value = float(strength) if strength is not None else None
            except (TypeError, ValueError):
                strength_value = None
            cleaned.append((text, strength_value))
    return cleaned


def build_variant_plan(config: dict[str, Any] | None) -> VariantPlan:
    """Create a VariantPlan from the current pipeline configuration."""

    config = config or {}
    pipeline_cfg = config.get("pipeline", {}) or {}

    base_txt = config.get("txt2img", {}) or {}
    base_img = config.get("img2img", {}) or {}
    base_model = base_txt.get("model") or base_img.get("model")
    base_hn = base_txt.get("hypernetwork") or base_img.get("hypernetwork")
    base_hn_strength = base_txt.get("hypernetwork_strength") or base_img.get(
        "hypernetwork_strength"
    )

    matrix_entries = _clean_matrix_entries(pipeline_cfg.get("model_matrix", []))
    hyper_entries = _clean_hypernet_entries(pipeline_cfg.get("hypernetworks", []))

    matrix_defined = bool(matrix_entries)
    hyper_defined = bool(hyper_entries)

    if not matrix_entries:
        matrix_entries = [base_model] if base_model else [None]

    if not hyper_entries:
        if base_hn or base_hn_strength is not None:
            hyper_entries = [(base_hn if base_hn else None, base_hn_strength)]
        else:
            hyper_entries = [(None, None)]

    mode = str(pipeline_cfg.get("variant_mode", "fanout")).strip().lower()
    if mode not in {"fanout", "rotate"}:
        mode = "fanout"

    # If neither matrix nor hypernets were explicitly configured, treat as inactive.
    if not matrix_defined and not hyper_defined:
        return VariantPlan(mode=mode, variants=[])

    variants: list[VariantSpec] = []
    for idx, (model_entry, hyper_entry) in enumerate(product(matrix_entries, hyper_entries)):
        model_value = model_entry if model_entry else None
        hyper_name, hyper_strength = hyper_entry
        variants.append(
            VariantSpec(
                index=idx,
                model=model_value,
                hypernetwork=hyper_name,
                hypernetwork_strength=hyper_strength,
            )
        )

    return VariantPlan(mode=mode, variants=variants)


def apply_variant_to_config(
    config: dict[str, Any] | None,
    variant: VariantSpec | None,
) -> dict[str, Any]:
    """Return a deepcopy of config with the variant overrides applied."""

    cfg = deepcopy(config or {})
    pipeline_cfg = cfg.setdefault("pipeline", {})

    if variant is None:
        pipeline_cfg.pop("active_variant", None)
        return cfg

    for section in ("txt2img", "img2img"):
        stage = cfg.setdefault(section, {})
        if variant.model is not None:
            stage["model"] = variant.model

    for section in ("txt2img", "img2img"):
        stage = cfg.setdefault(section, {})
        stage["hypernetwork"] = variant.hypernetwork
        stage["hypernetwork_strength"] = variant.hypernetwork_strength

    pipeline_cfg["active_variant"] = {
        "index": variant.index,
        "label": variant.label,
    }

    return cfg
