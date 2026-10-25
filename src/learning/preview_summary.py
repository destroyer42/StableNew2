"""Structured, read-only summary of what a frozen Preview would submit.

Everything is read from the experiment's immutable snapshot (and the plan built from it); nothing is recompiled,
re-resolved against live widgets, or queued. Prompt text and local paths are never included.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.learning.experiment_execution import thaw_snapshot
from src.learning.model_comparison import STUDY_TYPE as MODEL_COMPARISON
from src.learning.two_axis_grid import variant_label

_MAX_VALUES_SHOWN = 8

STUDY_LABELS = {
    "controlled_variable": "Controlled Variable",
    MODEL_COMPARISON: "Model Comparison",
    "two_axis_grid": "Two-Axis Grid",
}


@dataclass(frozen=True)
class PreviewSummary:
    rows: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...]
    variants: int
    images_per_variant: int
    total_images: int
    submissions: int

    @property
    def headline(self) -> str:
        return (
            f"{self.variants} variant{'s' if self.variants != 1 else ''} x {self.images_per_variant} "
            f"image{'s' if self.images_per_variant != 1 else ''} = {self.total_images} expected images"
        )


def _values_text(values: Sequence[Any]) -> str:
    shown = [variant_label(value) for value in values[:_MAX_VALUES_SHOWN]]
    extra = len(values) - len(shown)
    return ", ".join(shown) + (f", +{extra} more" if extra > 0 else "")


def _model_text(context: Mapping[str, Any]) -> str:
    name = str(context.get("selected_model") or "").strip() or "model not recorded"
    profile = context.get("profile_ref")
    if isinstance(profile, Mapping) and profile.get("id"):
        target = f"{profile['id']} v{profile.get('version', '?')}"
    else:
        target = str(context.get("family") or "unqualified")
    evidence = str(context.get("evidence") or "").strip()
    return f"{name} ({target}{', ' + evidence if evidence else ''})"


def _prompt_text(source: Mapping[str, Any]) -> str:
    if str(source.get("prompt_source") or "") == "pack":
        name = str(source.get("selected_prompt_pack_name") or "").strip() or "PromptPack"
        return f"{name}, row {int(source.get('selected_prompt_index', 0) or 0) + 1} (frozen)"
    return "Custom prompt (frozen)"


def _seed_text(seed_policy: Mapping[str, Any]) -> str:
    if not seed_policy:
        return "not recorded"
    base = seed_policy.get("requested_base_seed")
    strength = seed_policy.get("subseed_strength")
    text = f"requested seed {base} shared by every variant"
    if strength:
        text += f", subseed strength {strength}"
    return text


def _settings_text(settings: Mapping[str, Any]) -> str:
    return ", ".join(
        f"{name} {value}"
        for name, value in settings.items()
        if name not in {"stage", "model"} and isinstance(value, (str, int, float)) and value != ""
    )


def _baseline_rows(snapshot: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Where the fixed settings came from and what every variant will effectively use (read from the snapshot)."""
    from src.learning.baseline_authoring import AUTHORING_KEY, OWNERSHIP_BASELINE, origin_text

    record = snapshot.get(AUTHORING_KEY)
    if not isinstance(record, Mapping):
        return []
    rows: list[tuple[str, str]] = [
        ("Baseline", origin_text(record)),
        (
            "Stage run",
            " then ".join(snapshot.get("stage_chain") or [str(snapshot.get("stage") or "")]),
        ),
    ]
    fixed = [
        f"{row['label']} {row['value']}"
        for row in snapshot.get("effective_settings") or []
        if isinstance(row, Mapping)
        and row.get("ownership") == OWNERSHIP_BASELINE
        and row.get("value") not in (None, "")
    ]
    if fixed:
        rows.append(("Fixed settings", "; ".join(fixed)))
    image = snapshot.get("input_image") or {}
    if isinstance(image, Mapping) and image.get("path"):
        name = str(image["path"]).replace("\\", "/").rsplit("/", 1)[-1]
        rows.append(("Source image", f"{name} (file observed at Preview)"))
    variants = [
        entry
        for entry in snapshot.get("variant_effective_settings") or []
        if isinstance(entry, Mapping)
    ]
    for entry in variants[:_MAX_VALUES_SHOWN]:
        rows.append(
            (
                f"Variant {variant_label(entry.get('value'))}",
                _settings_text(entry.get("settings") or {}),
            )
        )
    if len(variants) > _MAX_VALUES_SHOWN:
        rows.append(("More variants", f"+{len(variants) - _MAX_VALUES_SHOWN} more"))
    return rows


def build_preview_summary(
    experiment: Any,
    plan: Sequence[Any],
    *,
    show_model_names: bool = False,
    extra_warnings: Sequence[str] = (),
) -> PreviewSummary | None:
    """Summary of the frozen Preview, or ``None`` when the experiment has no readable snapshot."""
    snapshot_json = str(getattr(experiment, "execution_snapshot_json", "") or "")
    if experiment is None or not snapshot_json or not plan:
        return None
    warnings = list(extra_warnings)
    try:
        snapshot = thaw_snapshot(snapshot_json)
    except (ValueError, TypeError):
        return PreviewSummary(
            rows=(),
            warnings=("The saved Preview could not be read. Build Preview again.", *warnings),
            variants=len(plan),
            images_per_variant=int(getattr(experiment, "images_per_value", 1) or 1),
            total_images=0,
            submissions=0,
        )

    study = str(
        (snapshot.get("study_type") or (experiment.metadata or {}).get("study_type"))
        or "controlled_variable"
    )
    if "model_comparison" in snapshot:
        study = MODEL_COMPARISON
    elif "two_axis_grid" in snapshot:
        study = "two_axis_grid"
    variants = len(snapshot.get("variant_values") or plan)
    images = max(1, int(snapshot.get("images_per_value") or 1))
    grid = snapshot.get("two_axis_grid") or {}
    total = int(grid.get("total_images") or variants * images)
    context = snapshot.get("model_policy_context") or {}
    source = snapshot.get("prompt_source") or {}
    seeds = snapshot.get("seed_policy") or {}

    rows: list[tuple[str, str]] = [
        ("Experiment", str(getattr(experiment, "name", "") or "Unnamed experiment")),
        ("Study type", STUDY_LABELS.get(study, study)),
        ("Target stage", str(snapshot.get("stage") or getattr(experiment, "stage", "txt2img"))),
    ]
    if study == MODEL_COMPARISON:
        arms = (snapshot.get("model_comparison") or {}).get("arms") or []
        if show_model_names:
            rows.append(
                ("Models compared", _values_text([arm.get("selected_model", "?") for arm in arms]))
            )
        else:
            rows.append(
                ("Models compared", f"{len(arms)} models (names hidden by content visibility)")
            )
        rows.append(
            (
                "Comparison",
                "Each model keeps its own validated settings and prompt adaptation; not a one-variable test.",
            )
        )
    elif study == "two_axis_grid":
        x_axis, y_axis = grid.get("x_axis") or {}, grid.get("y_axis") or {}
        rows.append(
            (
                "Columns (X)",
                f"{x_axis.get('variable', '?')}: {_values_text(list(x_axis.get('values') or []))}",
            )
        )
        rows.append(
            (
                "Rows (Y)",
                f"{y_axis.get('variable', '?')}: {_values_text(list(y_axis.get('values') or []))}",
            )
        )
        rows.append(("Model", _model_text(context)))
    else:
        rows.append(("Setting tested", str(snapshot.get("variable_under_test") or "not recorded")))
        rows.append(("Values", _values_text(list(snapshot.get("variant_values") or []))))
        rows.append(("Model", _model_text(context)))
        rows.extend(_baseline_rows(snapshot))
    rows.extend(
        [
            ("Prompt", _prompt_text(source)),
            ("Variants", str(variants)),
            ("Images per variant", str(images)),
            ("Total expected images", str(total)),
            ("Seed", _seed_text(seeds)),
            (
                "Queue submission",
                f"{variants} job{'s' if variants != 1 else ''} in one all-or-none submission",
            ),
        ]
    )
    if len(plan) != variants:
        warnings.append(
            "The plan and the frozen Preview disagree on the variant count. Build Preview again."
        )
    return PreviewSummary(
        rows=tuple(rows),
        warnings=tuple(warnings),
        variants=variants,
        images_per_variant=images,
        total_images=total,
        submissions=variants,
    )


__all__ = ["PreviewSummary", "STUDY_LABELS", "build_preview_summary"]
