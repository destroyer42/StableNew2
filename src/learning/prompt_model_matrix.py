"""Bounded Prompt x Model study: plan once, freeze every cell, materialize ordinary immutable NJRs.

``learning_prompt_model_matrix/1`` compares 2-4 prompt candidates of ONE named ``[[slot]]`` across 2-4 qualified models
inside one shared backend/geometry/seed cohort. It owns no compiler, queue, runner, policy or rating store: prompts come
from the canonical Matrix/intent resolvers, each (prompt, model) cell is an arm built by the same helpers Model Comparison
uses (``prepare_arm_envelope`` / ``build_arm`` / ``verify_arm`` / ``arm_njr``), and model eligibility stays with
``candidate_ineligibility`` / ``require_envelope``.

The study is deliberately narrow and refuses (never drops or transforms) anything it cannot freeze: LoRAs, embeddings,
aesthetic conditioning, hypernetworks, ControlNet, extra stages, hires/refiner, the prompt optimizer, unsupported
negatives, candidates that collapse or lose their distinguishing content in adaptation, and oversized designs.
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from src.learning.model_comparison import (
    arm_njr,
    build_arm,
    candidate_models,
    digest,
    prepare_arm_envelope,
    shared_global_positive,
    verify_arm,
)
from src.learning.prompt_slot_experiment import (
    PromptSlotDesign,
    expected_execution_prompts,
    slots_in,
    validate_design,
)
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

CONTRACT = "learning_prompt_model_matrix/1"
STUDY_TYPE = "prompt_model_matrix"
VARIABLE = "Prompt x Model"
RECORD_KIND = "learning_prompt_model_matrix_rating"
CLAIM = "prompt_by_target_envelope_preference"
SEED_INTERPRETATION = (
    "same requested seed cohort; latent and noise semantics may differ between models"
)
SETTINGS_NOTICE = (
    "Each model uses its own validated execution settings. "
    "Prompt candidates are compared within those settings."
)
MIN_PROMPTS, MAX_PROMPTS = 2, 4
MIN_MODELS, MAX_MODELS = 2, 4
MAX_CELLS = 16
MAX_IMAGES_PER_CELL = 3
MAX_TOTAL_IMAGES = 36
LIMITS = {
    "prompts": [MIN_PROMPTS, MAX_PROMPTS],
    "models": [MIN_MODELS, MAX_MODELS],
    "cells": MAX_CELLS,
    "images_per_cell": MAX_IMAGES_PER_CELL,
    "total_images": MAX_TOTAL_IMAGES,
}
_STRUCTURED_TEXT = re.compile(r"<[^>]*>|\bembedding\s*:", re.IGNORECASE)


# --------------------------------------------------------------------------------------------------------------------
# Refusals: nothing below disables, drops or rewrites a request to make a study fit.
# --------------------------------------------------------------------------------------------------------------------
def aesthetic_conditioning_requested(config: Mapping[str, Any]) -> bool:
    """True when any config surface could make the executor apply aesthetic conditioning (fails closed).

    The executor's aesthetic fallback can append an ``<embedding:...>`` phrase to the prompt, so the matrix must never
    freeze a configuration on which that path is reachable, for any model.
    """
    sections = [config]
    for name in ("txt2img", "pipeline"):
        section = config.get(name)
        if isinstance(section, Mapping):
            sections.append(section)
    for section in sections:
        aesthetic = section.get("aesthetic")
        if isinstance(aesthetic, Mapping):
            if aesthetic.get("enabled"):
                return True
        elif aesthetic:
            return True
        if section.get("aesthetic_enabled") or section.get("aesthetic_gradient_enabled"):
            return True
    return False


def excluded_conditioning(config: Mapping[str, Any]) -> list[str]:
    """Names of every requested feature a Prompt x Model cell cannot freeze."""
    base = config.get("txt2img") or {}
    pipeline = config.get("pipeline") or {}
    found: list[str] = []
    for stage in ("img2img", "adetailer", "upscale"):
        if (
            pipeline.get(f"{stage}_enabled")
            or config.get(f"{stage}_enabled")
            or (config.get(stage) or {}).get("enabled")
        ):
            found.append(stage)
    if aesthetic_conditioning_requested(config):
        found.append("aesthetic conditioning")
    if str(base.get("hypernetwork") or "none").lower() not in {"", "none"}:
        found.append("hypernetwork")
    if (
        base.get("enable_hr")
        or config.get("enable_hr")
        or (config.get("hires_fix") or {}).get("enabled")
    ):
        found.append("hires fix")
    if (
        base.get("refiner_enabled")
        or config.get("use_refiner")
        or (config.get("refiner") or {}).get("enabled")
    ):
        found.append("refiner")
    if any(
        "controlnet" in str(key).lower()
        and (bool(value.get("enabled")) if isinstance(value, dict) else bool(value))
        for section in (config, base)
        for key, value in section.items()
    ):
        found.append("ControlNet")
    if config.get("lora_override") or base.get("lora_strengths"):
        found.append("LoRA")
    if any(
        bool((section.get("prompt_optimizer") or {}).get("enabled")) for section in (config, base)
    ):
        found.append("prompt optimizer")
    return found


def require_matrix_baseline(config: Mapping[str, Any]) -> None:
    found = excluded_conditioning(config)
    if found:
        raise ValueError(
            "Prompt x Model Matrix cannot freeze "
            + ", ".join(found)
            + "; disable it explicitly and rebuild preview. Only plain txt2img with prompt text is compared."
        )


def _norm(text: str) -> str:
    return " ".join(str(text).casefold().split())


def _model_failure(index: int, exc: Exception) -> str:
    return (
        f"Prompt x Model Matrix model {index + 1} cannot execute the shared study: {exc}. "
        "Nothing was queued; shared geometry, sample count, seed policy and stages are not changed for a model - "
        "adjust the shared settings or the model list and rebuild preview."
    )


def bounded_models(values: Any) -> list[str]:
    models = candidate_models(values)
    if not MIN_MODELS <= len(models) <= MAX_MODELS:
        raise ValueError(
            f"Choose {MIN_MODELS} to {MAX_MODELS} distinct models; no models were truncated."
        )
    return models


def check_bounds(prompts: int, models: int, images: Any) -> None:
    if not MIN_PROMPTS <= prompts <= MAX_PROMPTS:
        raise ValueError(
            f"Choose {MIN_PROMPTS} to {MAX_PROMPTS} prompt candidates; no candidates were truncated."
        )
    if not MIN_MODELS <= models <= MAX_MODELS:
        raise ValueError(
            f"Choose {MIN_MODELS} to {MAX_MODELS} distinct models; no models were truncated."
        )
    if (
        isinstance(images, bool)
        or not isinstance(images, int)
        or not 1 <= images <= MAX_IMAGES_PER_CELL
    ):
        raise ValueError(f"Choose 1 to {MAX_IMAGES_PER_CELL} images per cell.")
    if prompts * models > MAX_CELLS:
        raise ValueError(f"The matrix has {prompts * models} cells; the limit is {MAX_CELLS}.")
    if prompts * models * images > MAX_TOTAL_IMAGES:
        raise ValueError(
            f"The matrix would generate {prompts * models * images} images; the limit is {MAX_TOTAL_IMAGES}. "
            "Reduce prompts, models or images per cell."
        )


def plan_summary(prompts: int, models: int, images: int) -> tuple[int, int]:
    """``(cells, expected images)`` with the same refusals as Build Preview."""
    check_bounds(prompts, models, images)
    return prompts * models, prompts * models * images


# --------------------------------------------------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------------------------------------------------
def prompt_label(index: int) -> str:
    return chr(65 + index)


def model_label(index: int) -> str:
    return f"Model {index + 1}"


def coordinate(cell: Mapping[str, Any]) -> dict[str, Any]:
    """The frozen ``LearningVariant.param_value`` of a cell: identity only, never prompt text or a local path."""
    return {
        "cell_id": cell["cell_id"],
        "prompt_label": cell["prompt_label"],
        "model_label": cell["model_label"],
        "row": cell["row"],
        "col": cell["col"],
    }


def variant_label(value: Any) -> str:
    if isinstance(value, Mapping) and "prompt_label" in value:
        return f"Prompt {value['prompt_label']} | {value['model_label']}"
    return str(value)


def filename_label(value: Any) -> str:
    if not (isinstance(value, Mapping) and "prompt_label" in value):
        return ""
    return f"p{value['prompt_label']}-m{int(value['col']) + 1}".lower()


def is_matrix(snapshot_or_experiment: Any) -> bool:
    if isinstance(snapshot_or_experiment, Mapping):
        return snapshot_or_experiment.get("study_type") == STUDY_TYPE
    raw = str(getattr(snapshot_or_experiment, "execution_snapshot_json", "") or "")
    if not raw:
        return False
    try:
        return bool(json.loads(raw).get("study_type") == STUDY_TYPE)
    except (ValueError, AttributeError):
        return False


# --------------------------------------------------------------------------------------------------------------------
# Preview: freeze everything
# --------------------------------------------------------------------------------------------------------------------
def _intent_for(
    design: PromptSlotDesign, value: str, row: Any, baseline: Mapping[str, Any], negative: str
) -> Any:
    from src.pipeline.prompt_pack_parser import PackRow
    from src.pipeline.resolution_layer import resolve_pack_intent

    pack_row = row or PackRow(
        embeddings=(),
        quality_line="",
        subject_template=design.template,
        lora_tags=(),
        negative_embeddings=(),
        negative_phrases=(),
    )
    if getattr(pack_row, "conditioning", None) or getattr(pack_row, "controlnet_units", None):
        raise ValueError(
            "Conditioned PromptPack rows are not supported by the Prompt x Model Matrix."
        )
    selected = normalize_matrix_slot_name(design.slot)
    vector = {normalize_matrix_slot_name(k): v for k, v in design.fixed_slots.items()}
    vector[selected] = value
    intent = resolve_pack_intent(
        pack_row=pack_row,
        matrix_slot_values=vector,
        pack_negative="" if row is not None else negative,
        global_negative=str(baseline.get("global_negative_prompt") or ""),
        apply_global_negative=bool(
            (baseline.get("pipeline") or {}).get("apply_global_negative_txt2img")
        ),
    )
    if intent.loras:
        raise ValueError(
            "Prompt x Model Matrix does not support LoRAs; remove them from the prompt source."
        )
    if intent.positive_embeddings or intent.negative_embeddings:
        raise ValueError(
            "Prompt x Model Matrix does not support textual inversion embeddings; remove them from the prompt source."
        )
    return intent


def _projection(record: Any) -> dict[str, Any]:
    """Executable inputs only: no identity, timestamps or duplicated provenance snapshots."""
    from src.pipeline.njr_core_v26 import thaw_json

    return {
        "config": thaw_json(record.workload.config),
        "positive": record.positive_prompt,
        "negative": record.negative_prompt,
        "model": record.stages[0].model,
        "stages": [stage.stage_type for stage in record.stages if stage.enabled],
        "images": record.workload.images_per_prompt,
        "seed": record.seed,
        "backend_options": thaw_json(record.workload.backend_options),
    }


def build_matrix_snapshot(
    experiment: Any,
    baseline: dict[str, Any],
    *,
    design: PromptSlotDesign,
    row: Any = None,
    source: Mapping[str, Any] | None = None,
    negative: str = "",
    models: Any = None,
    evidence: Any = None,
    policy_resolver: Any = None,
    embedding_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Freeze prompts, models, seeds and every cell's effective arm; all-or-nothing and queue-free."""
    from src.image_backends.image_backend_types import normalize_image_backend_options
    from src.image_backends.model_policy import Support
    from src.learning.experiment_freeze import freeze_seed_policy
    from src.learning.model_capabilities import policy_context
    from src.pipeline.compile_evidence import CompileEvidence
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy
    from src.pipeline.resolution_layer import (
        pack_prompt_intent_from_dict,
        pack_prompt_intent_to_dict,
        render_pack_intent,
    )

    if experiment.stage != "txt2img" or experiment.input_image_path:
        raise ValueError("Prompt x Model Matrix supports image txt2img only")
    images = design.images_per_candidate
    selected_models = bounded_models(
        models if models is not None else (experiment.metadata or {}).get("selected_models")
    )
    check_bounds(len(design.candidates), len(selected_models), images)
    validate_design(design, embedding_names=embedding_names)
    if slots_in(negative):
        raise ValueError("The fixed negative prompt may not contain unresolved Matrix slots.")

    baseline = copy.deepcopy(baseline)
    pipeline = baseline.get("pipeline") or {}
    baseline = apply_global_prompt_policy(
        baseline,
        positive_enabled=bool(pipeline.get("apply_global_positive_txt2img")),
        positive_text=str(baseline.get("global_positive_prompt") or ""),
        negative_enabled=bool(pipeline.get("apply_global_negative_txt2img")),
        negative_text=str(baseline.get("global_negative_prompt") or ""),
    )
    require_matrix_baseline(baseline)
    for text in (baseline.get("global_positive_prompt"), baseline.get("global_negative_prompt")):
        if text and _STRUCTURED_TEXT.search(str(text)):
            raise ValueError(
                "Global prompt text contains structured conditioning (<...> or embedding:); "
                "the Prompt x Model Matrix compares plain prompt text only."
            )
    section = baseline.get("txt2img") or {}
    try:
        geometry = {name: int(section[name]) for name in ("width", "height")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Set a valid shared width and height before Build Preview") from exc
    if any(value <= 0 for value in geometry.values()):
        raise ValueError("Set a valid shared width and height before Build Preview")
    options = normalize_image_backend_options(baseline.get("backend_options"))
    backend = options["image"]["backend_id"]
    seed_policy = freeze_seed_policy(
        baseline, images, preserved_policy=(experiment.metadata or {}).get("frozen_seed_policy")
    )
    evidence = evidence or CompileEvidence()
    shared_positive = shared_global_positive(baseline)

    prompts: list[dict[str, Any]] = []
    for index, value in enumerate(design.candidates):
        intent = _intent_for(design, value, row, baseline, negative)
        rendered = render_pack_intent(intent)
        if slots_in(rendered.positive) or slots_in(rendered.negative):
            raise ValueError("Preview contains unresolved Matrix slots.")
        for text in (rendered.positive, rendered.negative):
            if _STRUCTURED_TEXT.search(text):
                raise ValueError(
                    "Prompt text contains structured conditioning (<...> or embedding:); "
                    "the Prompt x Model Matrix compares plain prompt text only."
                )
        serialized = pack_prompt_intent_to_dict(intent)
        prompts.append(
            {
                "label": prompt_label(index),
                "value": value,
                "source_intent": serialized,
                "source_intent_sha256": digest(serialized),
                "source_negative_present": bool(rendered.negative.strip()),
            }
        )

    model_records: list[dict[str, Any]] = []
    envelopes: list[tuple[Any, dict[str, Any], str, str]] = []
    for col, model in enumerate(selected_models):
        policy = policy_resolver(model) if policy_resolver else evidence.policy_for(model)
        try:
            config, positive_mode, offered = prepare_arm_envelope(
                baseline,
                model,
                policy,
                index=col,
                backend=backend,
                geometry=geometry,
                options=options,
                shared_positive=shared_positive,
                arm_failure=_model_failure,
            )
        except ValueError as exc:
            if str(exc).startswith("Prompt x Model Matrix model"):
                raise
            raise ValueError(_model_failure(col, exc)) from exc
        if aesthetic_conditioning_requested(config):
            raise ValueError(
                _model_failure(col, ValueError("aesthetic conditioning is not supported"))
            )
        if policy.feature("negative_prompt").support is Support.UNSUPPORTED and any(
            p["source_negative_present"] for p in prompts
        ):
            raise ValueError(
                _model_failure(
                    col,
                    ValueError("the model cannot execute the requested negative prompt; remove it"),
                )
            )
        envelopes.append((policy, config, positive_mode, offered))
    optimizer_enabled = False  # a prompt optimizer is refused by require_matrix_baseline

    cells: list[dict[str, Any]] = []
    for row_index, prompt in enumerate(prompts):
        intent = pack_prompt_intent_from_dict(prompt["source_intent"])
        for col, model in enumerate(selected_models):
            policy, config, positive_mode, offered = envelopes[col]
            index = len(cells)
            cell_id = digest(
                [experiment.experiment_id, prompt["label"], prompt["source_intent_sha256"], model]
            )[:20]
            identity = {
                "cell_id": cell_id,
                "prompt_label": prompt["label"],
                "prompt_index": row_index,
                "model_label": model_label(col),
                "model_index": col,
                "row": row_index,
                "col": col,
            }
            arm = build_arm(
                index=index,
                model=model,
                policy=policy,
                intent=intent,
                source_sha=prompt["source_intent_sha256"],
                config=config,
                positive_mode=positive_mode,
                offered_positive=offered,
                shared_positive=shared_positive,
                evidence=evidence,
                optimizer_enabled=optimizer_enabled,
                seed_policy=seed_policy,
                geometry=geometry,
                backend=backend,
                contract=CONTRACT,
                study=STUDY_TYPE,
                claim=CLAIM,
                extra={"matrix_cell": identity},
                arm_failure=_model_failure,
            )
            if _norm(prompt["value"]) not in _norm(arm["adapted_positive_prompt"]):
                raise ValueError(
                    f"Prompt {prompt['label']} loses its distinguishing content when adapted for "
                    f"{model_label(col)}; nothing was queued. Choose different candidates or models."
                )
            cells.append({**identity, "index": index, "arm": arm})
    for col in range(len(selected_models)):
        executable = [
            cell["arm"]["executor_base_positive_prompt"] for cell in cells if cell["col"] == col
        ]
        if len({_norm(text) for text in executable}) != len(executable):
            raise ValueError(
                f"Distinct prompt candidates collapse to the same executable prompt for {model_label(col)}; "
                "nothing was queued."
            )

    for col, model in enumerate(selected_models):
        policy = envelopes[col][0]
        model_records.append(
            {
                "label": model_label(col),
                "index": col,
                "model": model,
                "selected_model": policy_context(policy, model, "txt2img")["selected_model"],
                "model_policy_context": policy_context(policy, model, "txt2img"),
                "checkpoint_evidence": copy.deepcopy(
                    getattr(evidence, "model_identities", {}).get(model, {})
                ),
            }
        )
    study = {
        "contract": CONTRACT,
        "template": design.template,
        "slot": normalize_matrix_slot_name(design.slot),
        "fixed_slots": dict(design.fixed_slots),
        "source": dict(source or {"kind": "custom"}),
        "prompts": prompts,
        "models": model_records,
        "cells": cells,
        "shared_geometry": geometry,
        "global_positive": shared_positive,
        "seed_interpretation": SEED_INTERPRETATION,
        "settings_notice": SETTINGS_NOTICE,
        "limits": dict(LIMITS),
        "total_cells": len(cells),
        "total_images": len(cells) * images,
        "comparison_claim": CLAIM,
        "causal_one_variable": False,
    }
    snapshot = {
        "schema_version": 2,
        "study_type": STUDY_TYPE,
        STUDY_TYPE: study,
        "experiment_id": experiment.experiment_id,
        "display_name": experiment.name,
        "baseline_config": baseline,
        "prompt_text": design.template,
        "negative_prompt_text": negative,
        "stage": "txt2img",
        "variable_under_test": VARIABLE,
        "variant_values": [coordinate(cell) for cell in cells],
        "images_per_value": images,
        "seed_policy": seed_policy,
        "experiment_timestamp": datetime.utcnow().strftime("%Y%m%d-%H%M%S"),
        "prompt_source": dict(source or {"kind": "custom"}),
        "input_image_path": "",
    }
    snapshot = json.loads(json.dumps(snapshot, allow_nan=False))
    _verify_study(snapshot, sealed=False)
    # Compile every cell through the exact Run boundary so one incompatible cell refuses the whole study at Preview.
    for cell in snapshot[STUDY_TYPE]["cells"]:
        try:
            record = _cell_record(
                snapshot,
                cell,
                SimpleNamespace(param_value=coordinate(cell), executed_config=None, variant_id=""),
            )
        except ValueError as exc:
            raise ValueError(
                f"Prompt {cell['prompt_label']} x {cell['model_label']} cannot be admitted: {exc}. "
                "Nothing was queued; rebuild preview after adjusting the design."
            ) from exc
        config = cell["arm"]["effective_config"]
        positive, negative_text = expected_execution_prompts(
            cell["arm"]["executor_base_positive_prompt"],
            cell["arm"]["executor_base_negative_prompt"],
            config,
        )
        cell["compiled"] = {
            "input_digest": digest(_projection(record)),
            "expected_positive": positive,
            "expected_negative": negative_text,
        }
    snapshot[STUDY_TYPE]["digest"] = _study_digest(snapshot[STUDY_TYPE])
    _verify_study(snapshot)
    experiment.metadata["frozen_seed_policy"] = seed_policy
    result: dict[str, Any] = snapshot
    return result


def _study_digest(study: Mapping[str, Any]) -> str:
    return digest({key: value for key, value in study.items() if key != "digest"})


# --------------------------------------------------------------------------------------------------------------------
# Verification of frozen records (pure; used at Preview, Run, readback and rating time)
# --------------------------------------------------------------------------------------------------------------------
def _verify_study(snapshot: Mapping[str, Any], *, sealed: bool = True) -> None:
    study = snapshot.get(STUDY_TYPE)
    if (
        snapshot.get("study_type") != STUDY_TYPE
        or snapshot.get("stage") != "txt2img"
        or not isinstance(study, Mapping)
        or study.get("contract") != CONTRACT
    ):
        raise ValueError("Invalid frozen Prompt x Model Matrix contract; rebuild preview")
    if study.get("comparison_claim") != CLAIM or study.get("causal_one_variable") is not False:
        raise ValueError("Prompt x Model Matrix must retain its target-envelope interpretation")
    if study.get("seed_interpretation") != SEED_INTERPRETATION:
        raise ValueError("Prompt x Model Matrix seed interpretation is missing; rebuild preview")
    if sealed and (study.get("digest") != _study_digest(study)):
        raise ValueError("Frozen Prompt x Model Matrix integrity mismatch; rebuild preview")
    prompts, models, cells = study["prompts"], study["models"], study["cells"]
    images = snapshot.get("images_per_value")
    check_bounds(len(prompts), len(models), images)
    if len(cells) != len(prompts) * len(models) or len(snapshot["variant_values"]) != len(cells):
        raise ValueError(
            "Frozen Prompt x Model Matrix cells differ from its design; rebuild preview"
        )
    seeds = snapshot.get("seed_policy") or {}
    if seeds.get("requested_sample_count") != images:
        raise ValueError("Frozen sample count differs from seed request")
    if aesthetic_conditioning_requested(snapshot.get("baseline_config") or {}):
        raise ValueError(
            "Frozen Prompt x Model Matrix may not carry aesthetic conditioning; rebuild preview"
        )
    for row, prompt in enumerate(prompts):
        if prompt["source_intent_sha256"] != digest(prompt["source_intent"]) or prompt[
            "label"
        ] != prompt_label(row):
            raise ValueError("Frozen prompt candidate digest mismatch; rebuild preview")
    for index, cell in enumerate(cells):
        row, col = divmod(index, len(models))
        prompt, model = prompts[row], models[col]
        if (
            cell["index"] != index
            or (cell["row"], cell["col"]) != (row, col)
            or cell["prompt_label"] != prompt["label"]
            or cell["model_label"] != model["label"]
            or snapshot["variant_values"][index] != coordinate(cell)
        ):
            raise ValueError(
                "Frozen Prompt x Model Matrix coordinates differ from its cells; rebuild preview"
            )
        arm = cell["arm"]
        if arm.get("matrix_cell") is None or arm["matrix_cell"].get("cell_id") != cell["cell_id"]:
            raise ValueError("Frozen matrix cell identity mismatch; rebuild preview")
        if aesthetic_conditioning_requested(arm["effective_config"]) or excluded_conditioning(
            arm["effective_config"]
        ):
            raise ValueError("Frozen matrix cell carries excluded conditioning; rebuild preview")
        verify_arm(
            arm,
            index=index,
            model=model["model"],
            study=dict(study),
            seeds=seeds,
            source_sha=prompt["source_intent_sha256"],
            contract=CONTRACT,
            study_type_name=STUDY_TYPE,
            claim=CLAIM,
        )
        if (
            arm["effective_positive_embeddings"]
            or arm["effective_negative_embeddings"]
            or arm["effective_lora_tags"]
        ):
            raise ValueError("Frozen matrix cell carries embeddings or LoRAs; rebuild preview")
        if arm["model_policy_context"] != model["model_policy_context"]:
            raise ValueError("Frozen matrix model identity mismatch; rebuild preview")
        if _STRUCTURED_TEXT.search(arm["executor_base_positive_prompt"]) or _STRUCTURED_TEXT.search(
            arm["executor_base_negative_prompt"]
        ):
            raise ValueError(
                "Frozen matrix prompt carries structured conditioning; rebuild preview"
            )
        if sealed and "compiled" not in cell:
            raise ValueError("Frozen matrix cell lacks its compiled evidence; rebuild preview")


def frozen_cell(snapshot: Mapping[str, Any], value: Any) -> dict[str, Any]:
    """Validate the sealed matrix, then return the one frozen cell exactly matching a coordinate."""
    _verify_study(snapshot)
    for cell in snapshot[STUDY_TYPE]["cells"]:
        if coordinate(cell) == value:
            return copy.deepcopy(cell)
    raise ValueError("Variant is outside the frozen Prompt x Model Matrix cells")


def _cell_record(
    snapshot: Mapping[str, Any], cell: Mapping[str, Any], variant: Any, **kwargs: Any
) -> Any:
    metadata_factory = kwargs.pop("metadata_factory", lambda config: {})
    return arm_njr(
        dict(snapshot),
        cell["arm"],
        variant,
        metadata_factory=metadata_factory,
        output_dir=kwargs.pop("output_dir", "output"),
        filename_template=kwargs.pop("filename_template", "{seed}"),
        variable=VARIABLE,
        study=STUDY_TYPE,
        claim=CLAIM,
        arm_key="prompt_model_matrix_arm",
        metadata_extra={
            "prompt_model_matrix": {
                "contract": CONTRACT,
                "cell": cell["arm"]["matrix_cell"],
                "digest": snapshot[STUDY_TYPE].get("digest", ""),
            }
        },
        job_id=kwargs.pop("job_id", None),
        variant_index=cell["index"],
        variant_total=len(snapshot["variant_values"]),
        mismatch_message="Prompt x Model Matrix NJR does not match frozen execution",
    )


def materialize_njr(
    snapshot: dict[str, Any],
    variant: Any,
    *,
    metadata_factory: Any,
    output_dir: str,
    filename_template: str,
    job_id: str | None = None,
) -> Any:
    """The immutable NJR for one frozen cell; refuses anything that differs from what Preview showed."""
    cell = frozen_cell(snapshot, variant.param_value)
    record = _cell_record(
        snapshot,
        cell,
        variant,
        metadata_factory=metadata_factory,
        output_dir=output_dir,
        filename_template=filename_template,
        job_id=job_id,
    )
    if digest(_projection(record)) != cell["compiled"]["input_digest"]:
        raise ValueError(
            "Prompt x Model Matrix NJR differs from the frozen Preview. No cells were admitted; rebuild preview."
        )
    return record


# --------------------------------------------------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------------------------------------------------
def _model_key(name: str) -> str:
    base = os.path.basename(str(name).replace("\\", "/")).strip()
    base = re.sub(r"\s*\[[0-9a-fA-F]+\]\s*$", "", base)
    return re.sub(r"\.(safetensors|ckpt|pt)$", "", base, flags=re.IGNORECASE).casefold()


def model_readback(variant_payload: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    """The model the executor reports it requested for this job ('' when no readback exists)."""
    for source in (variant_payload, metadata):
        config = source.get("config")
        if isinstance(config, Mapping):
            override = config.get("override_settings")
            if isinstance(override, Mapping) and override.get("sd_model_checkpoint"):
                return str(override["sd_model_checkpoint"])
        if isinstance(source.get("model"), str) and source["model"]:
            return str(source["model"])
    return ""


def readback_reason(
    snapshot: Mapping[str, Any],
    variant: Any,
    readback: Mapping[str, Any],
    variant_payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Empty when the completed job proves this cell's prompt and model; otherwise why it is uncontrolled."""
    if snapshot.get("study_type") != STUDY_TYPE:
        return ""
    try:
        cell = frozen_cell(snapshot, variant.param_value)
        index = cell["index"]
        if (
            not variant.job_id
            or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
            or variant.experiment_id != snapshot["experiment_id"]
        ):
            return "matrix_identity_unverified"
        config = variant.executed_config or {}
        arm = cell["arm"]
        if (
            config.get("prompt") != arm["executor_base_positive_prompt"]
            or config.get("negative_prompt") != arm["executor_base_negative_prompt"]
            or (config.get("txt2img") or {}).get("model")
            != arm["effective_config"]["txt2img"]["model"]
        ):
            return "matrix_compiled_context_conflict"
        if "final_prompt" not in readback or "final_negative_prompt" not in readback:
            return "matrix_prompt_readback_unavailable"
        if (
            readback["final_prompt"] != cell["compiled"]["expected_positive"]
            or readback["final_negative_prompt"] != cell["compiled"]["expected_negative"]
        ):
            return "matrix_prompt_readback_mismatch"
        observed = model_readback(variant_payload or {}, metadata or {})
        if not observed:
            return "matrix_model_readback_unavailable"
        if _model_key(observed) != _model_key(arm["effective_config"]["txt2img"]["model"]):
            return "matrix_model_readback_mismatch"
    except (KeyError, TypeError, ValueError):
        return "matrix_frozen_evidence_invalid"
    return ""


def execution_evidence(
    snapshot: Mapping[str, Any], variant_payload: Mapping[str, Any], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    """Compact, path-free model readback retained on the variant (``{}`` for any other study)."""
    if snapshot.get("study_type") != STUDY_TYPE:
        return {}
    observed = model_readback(variant_payload, metadata)
    return {"runtime_model_readback": _model_key(observed) if observed else ""}


def rating_classification(
    snapshot: Mapping[str, Any],
    value: Any,
    execution_metadata: Mapping[str, Any] | None = None,
    *,
    image_ref: str = "",
    image_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Matrix ratings carry their own record kind and never the one-variable causal kind."""
    if snapshot.get("study_type") != STUDY_TYPE:
        raise ValueError("Not a Prompt x Model Matrix snapshot")
    metadata = dict(execution_metadata or {})
    cell = frozen_cell(snapshot, value)
    study = snapshot[STUDY_TYPE]
    arm = cell["arm"]
    refs = [str(ref) for ref in (image_refs or [])]
    sample = refs.index(image_ref) if image_ref in refs else None
    seeds = list(metadata.get("actual_all_seeds") or [])
    reason = str(metadata.get("variable_validation_reason") or "")
    controlled = metadata.get("controlled_evidence_valid") is True
    model = study["models"][cell["col"]]
    evidence = {
        "contract": CONTRACT,
        "experiment_id": snapshot["experiment_id"],
        "cell_id": cell["cell_id"],
        "row": cell["row"],
        "col": cell["col"],
        "prompt_label": cell["prompt_label"],
        "prompt_source_sha256": arm["source_intent_sha256"],
        "prompt_effective_digest": digest(
            [cell["compiled"]["expected_positive"], cell["compiled"]["expected_negative"]]
        ),
        "model_label": cell["model_label"],
        "model_context_digest": digest(model["model_policy_context"]),
        "checkpoint_evidence_digest": digest(model["checkpoint_evidence"]),
        "arm_sha256": arm["arm_sha256"],
        "study_digest": study["digest"],
        "image_path": image_ref,
        "sample_index": sample,
        "requested_seed": (snapshot.get("seed_policy") or {}).get("requested_base_seed"),
        "actual_seed": seeds[sample] if sample is not None and len(seeds) == len(refs) else None,
        "prompt_readback_status": "matched"
        if controlled and reason == "valid"
        else (reason or "unproven"),
        "model_readback_status": (
            "matched"
            if controlled and reason == "valid"
            else "unavailable"
            if "model_readback_unavailable" in reason
            else "mismatch"
            if "model_readback_mismatch" in reason
            else "unproven"
        ),
        "controlled_evidence_valid": controlled,
        "seed_interpretation": SEED_INTERPRETATION,
    }
    return {
        "record_kind": RECORD_KIND,
        "study_type": STUDY_TYPE,
        "comparison_claim": CLAIM,
        "causal_one_variable": False,
        "prompt_model_matrix": evidence,
        "runtime_prompt_readback": dict(metadata.get("runtime_prompt_readback") or {}),
    }


def conclusion(
    plan: Sequence[Any], ratings: Mapping[str, Any], drafts: Mapping[str, Any]
) -> dict[str, Any]:
    """Descriptive, model-scoped results from saved, controlled, exactly-associated ratings only.

    Within each model column the highest-rated prompt is reported; ties and insufficient samples are stated. No global
    winner, significance or causal claim is made, and nothing here feeds recommendations.
    """
    import statistics

    cells: list[dict[str, Any]] = []
    saved = draft_count = total = 0
    all_controlled = True
    for variant in plan:
        value = variant.param_value if isinstance(variant.param_value, Mapping) else {}
        valid = (variant.execution_metadata or {}).get("controlled_evidence_valid") is True
        if variant.image_refs:
            all_controlled = all_controlled and valid
        scores: list[float] = []
        for path in variant.image_refs:
            total += 1
            rating = (ratings.get(path) or {}).get("overall_rating", 0)
            if (
                isinstance(rating, (int, float))
                and not isinstance(rating, bool)
                and 1 <= rating <= 5
            ):
                saved += 1
                if valid:
                    scores.append(float(rating))
            elif any(str(key).endswith(f":{path}") for key in drafts):
                draft_count += 1
        cells.append(
            {
                "value": value,
                "prompt_label": value.get("prompt_label"),
                "model_label": value.get("model_label"),
                "sample_count": len(variant.image_refs),
                "saved_count": len(scores),
                "controlled": valid,
                "average_overall": statistics.mean(scores) if scores else None,
                "rating_stddev": statistics.stdev(scores) if len(scores) > 1 else None,
                "rating_distribution": {str(i): scores.count(float(i)) for i in range(1, 6)},
            }
        )
    by_model: dict[str, dict[str, Any]] = {}
    for model in dict.fromkeys(cell["model_label"] for cell in cells):
        column = [cell for cell in cells if cell["model_label"] == model]
        if len(column) < 2 or any(not cell["saved_count"] for cell in column):
            by_model[model] = {
                "status": "insufficient_samples",
                "best_prompts": [],
                "message": f"{model}: insufficient controlled saved ratings to compare prompts.",
            }
            continue
        best = max(cell["average_overall"] for cell in column)
        winners = [cell["prompt_label"] for cell in column if cell["average_overall"] == best]
        by_model[model] = {
            "status": "tie" if len(winners) > 1 else "highest_rated",
            "best_prompts": winners,
            "message": (
                f"{model}: tie between Prompts {', '.join(winners)}."
                if len(winners) > 1
                else f"Highest rated within this study ({model}): Prompt {winners[0]}."
            ),
        }
    return {
        "study_type": STUDY_TYPE,
        "controlled_valid": all_controlled,
        "comparison_claim": CLAIM,
        "causal_one_variable": False,
        "saved": saved,
        "draft": draft_count,
        "unrated": max(0, total - saved - draft_count),
        "values": cells,
        "models": by_model,
        "best_value": None,
        "sufficient_evidence": bool(by_model)
        and all(item["status"] != "insufficient_samples" for item in by_model.values()),
        "message": (
            " ".join(item["message"] for item in by_model.values())
            + " Results describe these prompts within each model's own validated settings in this study only; "
            "there is no global winner, statistical significance or causal claim."
        ).strip(),
    }


def preview_summary(snapshot: Mapping[str, Any], *, show_names: bool = False) -> str:
    """Readiness without prompt text or local paths; model names are explicitly opt-in."""
    study = snapshot[STUDY_TYPE]
    size = study["shared_geometry"]
    seeds = snapshot["seed_policy"]
    lines = [
        f"Prompt x Model Matrix: {len(study['prompts'])} prompts x {len(study['models'])} models = "
        f"{study['total_cells']} cells x {snapshot['images_per_value']} images = {study['total_images']} expected images.",
        SETTINGS_NOTICE,
        f"Shared {size['width']}x{size['height']}; common requested seed {seeds['requested_base_seed']}. "
        "Seed semantics may differ between models.",
        "Descriptive comparison: ratings are experiment-local and never become recommendation evidence.",
    ]
    for model in study["models"]:
        context = model["model_policy_context"]
        profile = context.get("profile_ref")
        target = f"{profile['id']} v{profile['version']}" if profile else context["family"]
        name = f": {model['selected_model']}" if show_names else ""
        lines.append(f"{model['label']}{name}: {target}; ready.")
    for cell in study["cells"]:
        changed = "changes" if cell["arm"]["prompt_adaptation"]["changed"] else "preserves"
        lines.append(
            f"R{cell['row'] + 1}C{cell['col'] + 1}: Prompt {cell['prompt_label']} x {cell['model_label']} "
            f"(adaptation {changed} the source projection)"
        )
    return "\n".join(lines)


def visibility_prompt(experiment: Any) -> str:
    """Private input to the content-visibility classifier, never a presentation caption."""
    try:
        snapshot = json.loads(experiment.execution_snapshot_json or "{}")
        if snapshot.get("study_type") == STUDY_TYPE:
            return "\n".join(
                str(cell["compiled"][key])
                for cell in snapshot[STUDY_TYPE]["cells"]
                for key in ("expected_positive", "expected_negative")
            )
    except (AttributeError, KeyError, TypeError, ValueError):
        return "nsfw unverified prompt-model-matrix content"
    return str(getattr(experiment, "prompt_text", "") or "")


def candidate_caption(experiment: Any, value: Any, *, visible: bool) -> str:
    """Review caption for one cell; prompt text appears only when content visibility allows it."""
    try:
        snapshot = json.loads(experiment.execution_snapshot_json)
        cell = frozen_cell(snapshot, value)
    except (AttributeError, KeyError, TypeError, ValueError):
        return "Matrix cell evidence is unavailable or unverified."
    prompt = snapshot[STUDY_TYPE]["prompts"][cell["row"]]["value"]
    return f"Prompt {cell['prompt_label']} x {cell['model_label']}\n" + (
        prompt if visible else "Prompt text hidden by content visibility."
    )
