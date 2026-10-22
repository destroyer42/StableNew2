"""Two-axis (CFG Scale / Steps / LoRA Strength) exploratory comparison: plan once, materialize frozen cells.

A grid is a study type of the ordinary Learning experiment. Each cell is one ``LearningVariant`` whose ``param_value`` is
the frozen coordinate, so admission, recovery, ratings and review reuse the existing paths. Nothing here queues, runs,
reads live cards or detects a model family; production compiler imports are deferred to the preview/run seams.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.pipeline.job_models_v2 import NormalizedJobRecord

CONTRACT = "learning_two_axis_grid/1"
STUDY_TYPE = "two_axis_grid"
RECORD_KIND = "learning_grid_rating"
GRID_CLAIM = "exploratory_two_variable_observation"
CFG = "CFG Scale"
STEPS = "Steps"
LORA = "LoRA Strength"
SUPPORTED_VARIABLES = (CFG, STEPS, LORA)
MIN_AXIS_VALUES = 2
MAX_AXIS_VALUES = 4
MAX_CELLS = 16
MAX_IMAGES_PER_CELL = 3
MAX_TOTAL_IMAGES = 36
_SHORT = {CFG: "cfg", STEPS: "steps", LORA: "lora"}
_RANGES = {
    CFG: (Decimal("1"), Decimal("30")),
    STEPS: (Decimal("1"), Decimal("150")),
    LORA: (Decimal("0"), Decimal("2")),
}
_CENT = Decimal("0.01")


def digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class GridAxis:
    variable: str
    values: tuple[int | float, ...]


@dataclass(frozen=True)
class GridCell:
    index: int
    row: int
    col: int
    cell_id: str
    x_variable: str
    x_value: int | float
    y_variable: str
    y_value: int | float

    @property
    def param_value(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "x_variable": self.x_variable,
            "x_value": self.x_value,
            "y_variable": self.y_variable,
            "y_value": self.y_value,
        }


def _decimal(raw: Any, variable: str) -> Decimal:
    if isinstance(raw, bool) or raw is None:
        raise ValueError(f"{variable} values must be numbers")
    try:
        value = Decimal(str(raw).strip()) if not isinstance(raw, Decimal) else raw
    except InvalidOperation as exc:
        raise ValueError(f"{variable} value {raw!r} is not a number") from exc
    if not value.is_finite():
        raise ValueError(f"{variable} value {raw!r} is not a finite number")
    return value


def _canonical(value: Decimal, variable: str) -> int | float:
    low, high = _RANGES[variable]
    if value < low or value > high or (variable == LORA and value == 0):
        bounds = f"above 0 up to {high}" if variable == LORA else f"{low} to {high}"
        raise ValueError(f"{variable} values must be {bounds}")
    if variable == STEPS:
        if value != value.to_integral_value():
            raise ValueError("Steps values must be whole numbers")
        return int(value)
    if value.quantize(_CENT) != value:
        raise ValueError(f"{variable} values may have at most two decimal places")
    return float(value)


def parse_axis(spec: Mapping[str, Any]) -> GridAxis:
    """Canonical, ordered, distinct values from a discrete list or a bounded range; never truncated or repaired."""
    variable = str(spec.get("variable") or "").strip()
    if variable not in SUPPORTED_VARIABLES:
        raise ValueError(
            f"Two-Axis Grid supports only {', '.join(SUPPORTED_VARIABLES)}; got {variable or 'no variable'}"
        )
    if "values" in spec and spec["values"] is not None:
        raw_values = spec["values"]
        if not isinstance(raw_values, (list, tuple)):
            raise ValueError(f"{variable} values must be a list")
        decimals = [_decimal(item, variable) for item in raw_values]
    else:
        start, end, step = (_decimal(spec.get(key), variable) for key in ("start", "end", "step"))
        if step <= 0 or end < start:
            raise ValueError(
                f"{variable} range needs a positive step and an end at or above the start"
            )
        count = int((end - start) // step) + 1
        if count > MAX_AXIS_VALUES:
            raise ValueError(
                f"{variable} range would produce {count} values; the limit is {MAX_AXIS_VALUES} per axis. "
                "Narrow the range or raise the step."
            )
        decimals = [start + step * k for k in range(count)]
    values = tuple(_canonical(item, variable) for item in decimals)
    if len(values) != len(set(values)):
        raise ValueError(f"{variable} values must be distinct")
    if not MIN_AXIS_VALUES <= len(values) <= MAX_AXIS_VALUES:
        raise ValueError(
            f"{variable} needs {MIN_AXIS_VALUES} to {MAX_AXIS_VALUES} values; got {len(values)}"
        )
    return GridAxis(variable, values)


def plan_cells(
    experiment_id: str, x_axis: GridAxis, y_axis: GridAxis, images_per_cell: int
) -> tuple[GridCell, ...]:
    """Row-major cells (X across columns, Y down rows, selected order preserved); bounds are refusals, not truncation."""
    if x_axis.variable == y_axis.variable:
        raise ValueError("The two axes must be distinct variables")
    if (
        isinstance(images_per_cell, bool)
        or not isinstance(images_per_cell, int)
        or not 1 <= images_per_cell <= MAX_IMAGES_PER_CELL
    ):
        raise ValueError(f"Two-Axis Grid allows 1 to {MAX_IMAGES_PER_CELL} images per cell")
    total = len(x_axis.values) * len(y_axis.values)
    if total > MAX_CELLS:
        raise ValueError(f"The grid has {total} cells; the limit is {MAX_CELLS}")
    if total * images_per_cell > MAX_TOTAL_IMAGES:
        raise ValueError(
            f"The grid would generate {total * images_per_cell} images; the limit is {MAX_TOTAL_IMAGES}. "
            "Reduce the values per axis or the images per cell."
        )
    cells: list[GridCell] = []
    for row, y in enumerate(y_axis.values):
        for col, x in enumerate(x_axis.values):
            identity = [experiment_id, x_axis.variable, x, y_axis.variable, y]
            cells.append(
                GridCell(
                    len(cells),
                    row,
                    col,
                    digest(identity)[:20],
                    x_axis.variable,
                    x,
                    y_axis.variable,
                    y,
                )
            )
    return tuple(cells)


def grid_spec(metadata: Mapping[str, Any]) -> tuple[GridAxis, GridAxis, str]:
    spec = metadata.get("grid")
    if not isinstance(spec, Mapping):
        raise ValueError("Two-Axis Grid requires both axes; configure them and rebuild preview")
    lora_name = str(spec.get("lora_name") or "").strip()
    axes = parse_axis(spec.get("x") or {}), parse_axis(spec.get("y") or {})
    return axes[0], axes[1], lora_name


def plan_summary(metadata: Mapping[str, Any], images_per_cell: int) -> tuple[int, int]:
    """``(cells, expected images)`` for the live design summary; raises the same refusals as Build Preview."""
    x_axis, y_axis, _ = grid_spec(metadata)
    cells = plan_cells("summary", x_axis, y_axis, images_per_cell)
    return len(cells), len(cells) * images_per_cell


def variable_label(x_variable: str, y_variable: str) -> str:
    return f"{x_variable} x {y_variable}"


def _text(value: int | float) -> str:
    return str(value)


def variant_label(value: Any) -> str:
    if isinstance(value, Mapping) and "x_variable" in value:
        return f"{value['x_variable']} {_text(value['x_value'])} | {value['y_variable']} {_text(value['y_value'])}"
    return str(value)


def filename_label(value: Any) -> str:
    """Filesystem-safe cell label for artifact prefixes."""
    if not (isinstance(value, Mapping) and "x_variable" in value):
        return ""
    parts = [
        f"{_SHORT.get(str(value[f'{axis}_variable']), 'v')}{_text(value[f'{axis}_value']).replace('.', 'p')}"
        for axis in ("x", "y")
    ]
    return "-".join(parts)


def require_plain_txt2img(config: Mapping[str, Any]) -> None:
    """Refuse a baseline whose extra stages or structural features a controlled grid cannot freeze; never disable."""
    base = config.get("txt2img") or {}
    pipeline = config.get("pipeline") or {}
    for stage in ("img2img", "adetailer", "upscale"):
        if (
            pipeline.get(f"{stage}_enabled")
            or config.get(f"{stage}_enabled")
            or (config.get(stage) or {}).get("enabled")
        ):
            raise ValueError(
                f"Two-Axis Grid requires a txt2img-only stage chain; disable {stage} and rebuild preview"
            )
    requested = {
        "hires fix": bool(
            base.get("enable_hr")
            or config.get("enable_hr")
            or (config.get("hires_fix") or {}).get("enabled")
        ),
        "refiner": bool(
            base.get("refiner_enabled")
            or config.get("use_refiner")
            or (config.get("refiner") or {}).get("enabled")
        ),
        "ControlNet": any(
            "controlnet" in str(key).lower()
            and (bool(value.get("enabled")) if isinstance(value, dict) else bool(value))
            for section in (config, base)
            for key, value in section.items()
        ),
        "aesthetic embedding": bool((config.get("aesthetic") or {}).get("enabled")),
        "hypernetwork": str(base.get("hypernetwork") or "none").lower() not in {"", "none"},
    }
    for name, enabled in requested.items():
        if enabled:
            raise ValueError(
                f"Two-Axis Grid cannot freeze {name}; disable it explicitly and rebuild preview"
            )


def _eligible(policy: Any) -> None:
    from src.image_backends.model_policy import EVIDENCE_REGISTRY, QUALIFIED_REGISTRY_POLICY_IDS

    if (
        policy.evidence != EVIDENCE_REGISTRY
        or policy.policy_id not in QUALIFIED_REGISTRY_POLICY_IDS
    ):
        raise ValueError(
            "Two-Axis Grid supports registry-verified SDXL checkpoints in this release; the selected model has no "
            "such evidence"
        )
    if "txt2img" not in policy.stages:
        raise ValueError("The selected model does not support txt2img")


def build_grid_snapshot(
    experiment: Any,
    baseline: dict[str, Any],
    *,
    validate_axis: Callable[[str, list[Any]], dict[str, Any]],
    known_loras: Callable[[], Any],
) -> dict[str, Any]:
    """Freeze axes, prompt, seeds, model context and every cell's effective configuration; all-or-nothing."""
    from src.image_backends.image_backend_types import normalize_image_backend_options
    from src.learning.experiment_freeze import freeze_seed_policy
    from src.learning.model_comparison import require_envelope
    from src.learning.model_policy_service import policy_from_context
    from src.learning.ordinary_prompt_freeze import freeze_ordinary_prompt_source

    if experiment.stage != "txt2img" or experiment.input_image_path:
        raise ValueError("Two-Axis Grid supports image txt2img only")
    x_axis, y_axis, lora_name = grid_spec(experiment.metadata)
    images = max(1, int(experiment.images_per_value or 1))
    cells = plan_cells(experiment.experiment_id, x_axis, y_axis, images)
    baseline = copy.deepcopy(baseline)
    require_plain_txt2img(baseline)
    source = freeze_ordinary_prompt_source(dict(experiment.metadata or {}))
    if str(source.get("prompt_source") or "") == "pack":
        experiment.prompt_text = str(source["rendered_positive_prompt"])
        negative_prompt = str(source["rendered_negative_prompt"])
    else:
        negative_prompt = str(source.get("selected_prompt_negative_text") or "")
    if not experiment.prompt_text.strip():
        raise ValueError(
            "Two-Axis Grid needs a prompt; select a PromptPack row or enter custom text"
        )
    experiment.metadata.update(source)
    experiment.baseline_config = baseline
    uses_lora = LORA in (x_axis.variable, y_axis.variable)
    if uses_lora:
        if not lora_name:
            raise ValueError("LoRA Strength needs one fixed LoRA; select it and rebuild preview")
        if lora_name.casefold() not in {str(name).casefold() for name in (known_loras() or ())}:
            raise ValueError(
                f"LoRA {lora_name} is not a resolved asset; refresh resources or choose another LoRA"
            )
    contexts = []
    for axis in (x_axis, y_axis):
        values = (
            [{"name": lora_name, "weight": weight} for weight in axis.values]
            if axis.variable == LORA
            else list(axis.values)
        )
        contexts.append(validate_axis(axis.variable, values))
    if contexts[0] != contexts[1]:
        raise ValueError("The two axes resolved conflicting model policies")
    context = contexts[0]
    policy = policy_from_context(context)
    _eligible(policy)
    section = baseline.get("txt2img") or {}
    try:
        geometry = {name: int(section[name]) for name in ("width", "height")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Set a valid width and height before Build Preview") from exc
    options = normalize_image_backend_options(baseline.get("backend_options"))
    require_envelope(policy, baseline, options["image"]["backend_id"], geometry)
    seed_policy = freeze_seed_policy(
        baseline, images, preserved_policy=(experiment.metadata.get("frozen_seed_policy") or None)
    )
    variable = variable_label(x_axis.variable, y_axis.variable)
    grid = {
        "contract": CONTRACT,
        "x_axis": {"variable": x_axis.variable, "values": list(x_axis.values)},
        "y_axis": {"variable": y_axis.variable, "values": list(y_axis.values)},
        "lora_name": lora_name if uses_lora else "",
        "cells": [
            {
                "index": c.index,
                "row": c.row,
                "col": c.col,
                "cell_id": c.cell_id,
                "x_value": c.x_value,
                "y_value": c.y_value,
            }
            for c in cells
        ],
        "total_cells": len(cells),
        "total_images": len(cells) * images,
        "limits": {
            "axis_values": [MIN_AXIS_VALUES, MAX_AXIS_VALUES],
            "cells": MAX_CELLS,
            "images_per_cell": MAX_IMAGES_PER_CELL,
            "total_images": MAX_TOTAL_IMAGES,
        },
        "claim": GRID_CLAIM,
        "causal_one_variable": False,
    }
    snapshot = {
        "schema_version": 2,
        "study_type": STUDY_TYPE,
        "experiment_id": experiment.experiment_id,
        "display_name": experiment.name,
        "baseline_config": baseline,
        "prompt_text": experiment.prompt_text,
        "negative_prompt_text": negative_prompt,
        "stage": "txt2img",
        "variable_under_test": variable,
        "variant_values": [c.param_value for c in cells],
        "images_per_value": images,
        "seed_policy": seed_policy,
        "experiment_timestamp": datetime.utcnow().strftime("%Y%m%d-%H%M%S"),
        "prompt_source": source,
        "input_image_path": "",
        "model_policy_context": context,
        "two_axis_grid": grid,
    }
    snapshot = cast(dict[str, Any], json.loads(json.dumps(snapshot, allow_nan=False)))
    for cell in snapshot["two_axis_grid"]["cells"]:
        cell["effective"] = _compile_cell(snapshot, _coordinate(snapshot, cell)).effective
    snapshot["two_axis_grid"]["baseline_sha256"] = digest(snapshot["baseline_config"])
    snapshot["two_axis_grid"]["grid_sha256"] = _grid_digest(snapshot["two_axis_grid"])
    experiment.metadata["frozen_seed_policy"] = seed_policy
    experiment.variable_under_test = variable
    experiment.values = list(snapshot["variant_values"])
    experiment.baseline_config = snapshot["baseline_config"]
    return snapshot


def _grid_digest(grid: Mapping[str, Any]) -> str:
    return digest({key: value for key, value in grid.items() if key != "grid_sha256"})


def _coordinate(snapshot: Mapping[str, Any], cell: Mapping[str, Any]) -> dict[str, Any]:
    grid = snapshot["two_axis_grid"]
    return {
        "cell_id": cell["cell_id"],
        "x_variable": grid["x_axis"]["variable"],
        "x_value": cell["x_value"],
        "y_variable": grid["y_axis"]["variable"],
        "y_value": cell["y_value"],
    }


def frozen_cell(snapshot: Mapping[str, Any], value: Any) -> dict[str, Any]:
    """Validate the sealed grid, then return the one frozen cell exactly matching a coordinate."""
    grid = snapshot.get("two_axis_grid")
    if (
        snapshot.get("study_type") != STUDY_TYPE
        or snapshot.get("stage") != "txt2img"
        or not isinstance(grid, Mapping)
        or grid.get("contract") != CONTRACT
    ):
        raise ValueError("Invalid frozen Two-Axis Grid contract; rebuild preview")
    if grid.get("claim") != GRID_CLAIM or grid.get("causal_one_variable") is not False:
        raise ValueError(
            "Two-Axis Grid must retain its exploratory interpretation; rebuild preview"
        )
    if _grid_digest(grid) != grid.get("grid_sha256"):
        raise ValueError("Frozen Two-Axis Grid integrity mismatch; rebuild preview")
    if grid.get("baseline_sha256") != digest(snapshot.get("baseline_config")):
        raise ValueError("Frozen Two-Axis Grid integrity mismatch; rebuild preview")
    if len(grid["cells"]) != len(snapshot.get("variant_values") or ()):
        raise ValueError("Frozen Two-Axis Grid cells differ from its variants; rebuild preview")
    for cell, coordinate in zip(grid["cells"], snapshot["variant_values"], strict=True):
        if coordinate != _coordinate(snapshot, cell):
            raise ValueError(
                "Frozen Two-Axis Grid coordinates differ from its cells; rebuild preview"
            )
    for cell in grid["cells"]:
        if _coordinate(snapshot, cell) == value:
            return copy.deepcopy(cell)
    raise ValueError("Variant is outside the frozen Two-Axis Grid cells")


@dataclass(frozen=True)
class CompiledCell:
    config: dict[str, Any]
    positive: str
    negative: str
    lora_tags: tuple[tuple[str, float], ...]
    effective: dict[str, Any]


def _axis_override(config: dict[str, Any], variable: str, value: Any, lora_name: str) -> None:
    section = config.setdefault("txt2img", {})
    if variable == CFG:
        section["cfg_scale"] = float(value)
    elif variable == STEPS:
        section["steps"] = int(value)
    else:
        config.setdefault("lora_override", {}).update({"name": lora_name, "weight": float(value)})


def _compile_cell(snapshot: Mapping[str, Any], coordinate: Mapping[str, Any]) -> CompiledCell:
    """Apply both axes to an isolated copy of the frozen baseline and prove each survives compile normalization."""
    from src.image_backends.model_policy import (
        Support,
        apply_model_compile_policy,
        policy_for_model_profile_reference,
    )
    from src.learning.experiment_freeze import apply_frozen_seed_policy
    from src.learning.lora_variant import apply_lora_variant, validate_lora_variant
    from src.learning.model_policy_service import policy_from_context
    from src.learning.ordinary_prompt_freeze import (
        apply_executor_base_prompts,
        validate_ordinary_prompt_snapshot,
    )

    validate_ordinary_prompt_snapshot(snapshot)
    require_plain_txt2img(snapshot["baseline_config"])
    grid = snapshot["two_axis_grid"]
    lora_name = str(grid.get("lora_name") or "")
    config = copy.deepcopy(snapshot["baseline_config"])
    for axis in ("x", "y"):
        _axis_override(
            config, coordinate[f"{axis}_variable"], coordinate[f"{axis}_value"], lora_name
        )
    requested = {
        "cfg_scale": config["txt2img"].get("cfg_scale"),
        "steps": config["txt2img"].get("steps"),
    }
    apply_model_compile_policy(config)
    section = config["txt2img"]
    for key, name in (("cfg_scale", CFG), ("steps", STEPS)):
        if section.get(key) != requested[key]:
            raise ValueError(f"Learning variable {name} overwritten by model compile normalization")
    context = snapshot["model_policy_context"]
    if context.get("profile_ref"):
        compiled = policy_for_model_profile_reference(config.get("backend_options"))
        if compiled is None or dict(compiled.profile_ref or {}) != context["profile_ref"]:
            raise ValueError("Compiled model profile differs from the frozen experiment profile")
    apply_frozen_seed_policy(config, snapshot["seed_policy"])
    prompt = str(snapshot["prompt_text"])
    negative = str(snapshot.get("negative_prompt_text") or "")
    if (
        policy_from_context(context).feature("negative_prompt", "txt2img").support
        is Support.UNSUPPORTED
    ):
        negative = ""
    tags = {
        str(entry["name"]): float(entry.get("weight", entry.get("strength", 1.0)) or 1.0)
        for entry in (snapshot.get("prompt_source") or {}).get("selected_prompt_loras") or ()
        if isinstance(entry, dict) and entry.get("name")
    }
    override = config.get("lora_override")
    lora = None
    if isinstance(override, dict):
        weight = float(override["weight"])
        baseline_prompt = prompt
        prompt = apply_lora_variant(baseline_prompt, lora_name, weight)
        reason = validate_lora_variant(prompt, lora_name, weight, baseline_prompt=baseline_prompt)
        if reason:
            raise ValueError(f"LoRA variant {lora_name}@{weight} rejected: {reason}")
        tags = {k: v for k, v in tags.items() if k.casefold() != lora_name.casefold()}
        tags[lora_name] = weight
        lora = {"name": lora_name, "weight": weight}
    apply_executor_base_prompts(config, prompt, negative, "txt2img")
    effective = {
        "cfg_scale": section["cfg_scale"],
        "steps": section["steps"],
        "lora": lora,
        "model": section.get("model", ""),
        "seed": section["seed"],
        "subseed": section.get("subseed"),
        "positive_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "negative_sha256": hashlib.sha256(negative.encode("utf-8")).hexdigest(),
        "images": snapshot["images_per_value"],
    }
    return CompiledCell(
        config, prompt, negative, tuple(tags.items()), json.loads(json.dumps(effective))
    )


def materialize_njr(
    snapshot: dict[str, Any],
    variant: Any,
    *,
    metadata_factory: Callable[[dict[str, Any]], dict[str, Any]],
    output_dir: str,
    filename_template: str,
) -> NormalizedJobRecord:
    """The immutable NJR for one frozen cell; refuses anything that differs from what Preview showed."""
    from src.learning.learning_njr import assemble_txt2img_njr
    from src.pipeline.job_models_v2 import LearningJobContext

    cell = frozen_cell(snapshot, variant.param_value)
    compiled = _compile_cell(snapshot, variant.param_value)
    if compiled.effective != cell["effective"]:
        raise ValueError("Frozen grid cell differs from its Preview; rebuild preview")
    config = compiled.config
    variable = snapshot["variable_under_test"]
    config.update(
        learning_experiment_id=snapshot["experiment_id"],
        learning_variant_value=variant.param_value,
        learning_variable=variable,
    )
    section = config["txt2img"]
    metadata = metadata_factory(config)
    metadata.update(
        study_type=STUDY_TYPE,
        comparison_claim=GRID_CLAIM,
        causal_one_variable=False,
        grid_cell=cell_identity(snapshot, variant.param_value),
    )
    for key in (
        "subseed",
        "subseed_strength",
        "seed_resize_from_h",
        "seed_resize_from_w",
        "clip_skip",
    ):
        metadata[key] = section.get(key, 0)
    variant.executed_config = copy.deepcopy(config)
    grid_size = snapshot["two_axis_grid"]["total_cells"]
    return assemble_txt2img_njr(
        job_id=f"learning_{snapshot['experiment_id']}_{variant.variant_id or cell['index']}_{uuid.uuid4().hex[:8]}",
        display_name=snapshot["display_name"],
        positive=compiled.positive,
        negative=compiled.negative,
        config=config,
        metadata=metadata,
        backend_options=config["backend_options"],
        images_per_prompt=snapshot["images_per_value"],
        output_dir=output_dir,
        filename_template=filename_template,
        variant_index=cell["index"],
        variant_total=grid_size,
        context=LearningJobContext(
            experiment_id=snapshot["experiment_id"],
            experiment_name=snapshot["display_name"],
            variant_index=cell["index"],
            variable_under_test=variable,
            variant_value=variant.param_value,
        ),
        lora_tags=compiled.lora_tags,
        mismatch_message="Two-Axis Grid NJR does not match frozen execution",
    )


def cell_identity(snapshot: Mapping[str, Any], value: Any) -> dict[str, Any]:
    cell = frozen_cell(snapshot, value)
    return {
        "experiment_id": snapshot["experiment_id"],
        "cell_id": cell["cell_id"],
        "row": cell["row"],
        "col": cell["col"],
        "x_variable": value["x_variable"],
        "x_value": value["x_value"],
        "y_variable": value["y_variable"],
        "y_value": value["y_value"],
    }


def rating_classification(
    snapshot: Mapping[str, Any],
    value: Any,
    execution_metadata: Mapping[str, Any] | None = None,
    *,
    image_ref: str = "",
    image_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Grid evidence is exploratory: its own record kind, never the one-variable causal kind."""
    if snapshot.get("study_type") != STUDY_TYPE:
        raise ValueError("Not a Two-Axis Grid snapshot")
    metadata = dict(execution_metadata or {})
    refs = [str(ref) for ref in (image_refs or [])]
    identity = cell_identity(snapshot, value)
    identity["image_path"] = image_ref
    identity["sample_index"] = refs.index(image_ref) if image_ref in refs else None
    seeds = list(metadata.get("actual_all_seeds") or [])
    identity["requested_seed"] = (snapshot.get("seed_policy") or {}).get("requested_base_seed")
    identity["actual_seed"] = (
        seeds[identity["sample_index"]]
        if (identity["sample_index"] is not None and len(seeds) == len(refs))
        else None
    )
    return {
        "record_kind": RECORD_KIND,
        "study_type": STUDY_TYPE,
        "comparison_claim": GRID_CLAIM,
        "causal_one_variable": False,
        "grid_cell": identity,
        "runtime_prompt_readback": dict(metadata.get("runtime_prompt_readback") or {}),
    }


def preview_summary(snapshot: Mapping[str, Any]) -> str:
    grid = snapshot["two_axis_grid"]
    seeds = snapshot["seed_policy"]
    context = snapshot["model_policy_context"]
    source = snapshot.get("prompt_source") or {}
    prompt_id = (
        f"PromptPack {source.get('selected_prompt_pack_name') or 'row'} row {int(source.get('selected_prompt_index', 0) or 0) + 1}"
        if source.get("prompt_source") == "pack"
        else "custom prompt"
    )
    lines = [
        f"Two-Axis Grid: {grid['x_axis']['variable']} across {len(grid['x_axis']['values'])} columns, "
        f"{grid['y_axis']['variable']} down {len(grid['y_axis']['values'])} rows.",
        f"{grid['total_cells']} cells x {snapshot['images_per_value']} images = {grid['total_images']} expected images.",
        f"Model {context['selected_model']} ({context['family']}); {prompt_id}; common seed {seeds['requested_base_seed']}.",
        "Exploratory comparison: ratings are descriptive and never become recommendation evidence.",
    ]
    for cell in grid["cells"]:
        effective = cell["effective"]
        lora = (
            f", LoRA {effective['lora']['name']}@{effective['lora']['weight']}"
            if effective["lora"]
            else ""
        )
        lines.append(
            f"R{cell['row'] + 1}C{cell['col'] + 1}: CFG {effective['cfg_scale']}, Steps {effective['steps']}{lora}"
        )
    return "\n".join(lines)


def is_grid(experiment_or_snapshot: Any) -> bool:
    if isinstance(experiment_or_snapshot, Mapping):
        return experiment_or_snapshot.get("study_type") == STUDY_TYPE
    from src.learning.model_comparison import study_type

    try:
        return study_type(experiment_or_snapshot) == STUDY_TYPE
    except (ValueError, TypeError):
        return False
