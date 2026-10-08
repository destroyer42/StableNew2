"""Learning's explicit target-envelope study: plan once, materialize frozen arms.

No family detector, prompt rules, runtime selection or durable store lives here.
Production compiler imports are deliberately deferred to the preview/run seams.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

CONTRACT = "learning_model_comparison/1"
STUDY_TYPE = "model_comparison"
COMPARISON_CLAIM = "target_envelope_preference"
RECORD_KIND = "learning_model_comparison_rating"


def executor_global_prompt_policy(config: dict) -> dict:
    """Evidence projection of the canonical frozen config, without applying terms."""
    from src.pipeline.global_prompt_policy import (
        GLOBAL_NEGATIVE_STAGE_FLAGS,
        GLOBAL_POSITIVE_STAGE_FLAG,
        has_frozen_global_prompt_policy,
    )

    if not has_frozen_global_prompt_policy(config):
        raise ValueError("Model Comparison requires a frozen executor global prompt policy")
    return {
        key: copy.deepcopy(config[key])
        for key in (
            "global_prompt_policy_source",
            "global_positive_prompt",
            "global_negative_prompt",
        )
    } | {
        "pipeline": {
            key: config["pipeline"][key]
            for key in (GLOBAL_POSITIVE_STAGE_FLAG, *GLOBAL_NEGATIVE_STAGE_FLAGS)
        }
    }


def digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def study_type(experiment: Any) -> str:
    """The preview is authoritative; old definitions default to controlled_variable."""
    raw = getattr(experiment, "execution_snapshot_json", "")
    source = json.loads(raw) if raw else getattr(experiment, "metadata", {})
    return str(source.get("study_type", "controlled_variable"))


def candidate_models(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("Select at least two distinct Models to Compare")
    result: list[str] = []
    identities: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\x00\r\n"):
            raise ValueError("Malformed model selection; choose an installed model")
        name = value.strip()
        identity = os.path.basename(name.replace("\\", "/")).casefold()
        if not identity or identity in {".", ".."}:
            raise ValueError("Malformed model selection; choose an installed model")
        if identity in identities:
            raise ValueError("Models to Compare must be distinct; remove duplicate selections")
        identities.add(identity)
        result.append(name)
    if len(result) < 2:
        raise ValueError("Select at least two distinct Models to Compare")
    return result


def _require_candidate(policy: Any) -> None:
    if not (policy.qualified and policy.evidence == "exact_profile") and not (
        policy.family == "sdxl" and policy.evidence == "registry_evidence"
    ):
        raise ValueError(
            "Model Comparison requires an exact qualified profile or registry-evidenced SDXL; target evidence is unavailable or conflicting"
        )
    if "txt2img" not in policy.stages:
        raise ValueError("Candidate does not support txt2img Model Comparison")


def _require_envelope(policy: Any, config: dict, backend: str, geometry: dict) -> None:
    from src.image_backends.model_policy import Support

    if (policy.required_backend and backend != policy.required_backend) or (
        policy.allowed_backends and backend not in policy.allowed_backends
    ):
        raise ValueError(
            "Candidate requires a different configured image backend; select a compatible backend explicitly and rebuild preview"
        )
    allowed = policy.control("geometry", "txt2img").allowed
    size = (geometry["width"], geometry["height"])
    if allowed and size not in tuple(tuple(item) for item in allowed):
        choices = ", ".join(f"{w}x{h}" for w, h in allowed)
        raise ValueError(
            f"Shared geometry {size[0]}x{size[1]} is not qualified for this candidate; set shared geometry to {choices} and rebuild preview"
        )
    base = config.get("txt2img") or {}
    pipeline = config.get("pipeline") or {}
    for stage in ("img2img", "adetailer", "upscale"):
        if (
            pipeline.get(f"{stage}_enabled")
            or config.get(f"{stage}_enabled")
            or (config.get(stage) or {}).get("enabled")
        ):
            raise ValueError(
                "Model Comparison requires a txt2img-only stage chain; disable additional stages and rebuild preview"
            )
    requested = {
        "hires": bool(
            base.get("enable_hr")
            or config.get("enable_hr")
            or (config.get("hires_fix") or {}).get("enabled")
        ),
        "refiner": bool(
            base.get("refiner_enabled")
            or config.get("use_refiner")
            or (config.get("refiner") or {}).get("enabled")
        ),
        "controlnet": any(
            "controlnet" in str(key).lower()
            and (bool(value.get("enabled")) if isinstance(value, dict) else bool(value))
            for section in (config, base)
            for key, value in section.items()
        ),
    }
    for name, enabled in requested.items():
        if enabled and policy.feature(name, "txt2img").support is not Support.SUPPORTED:
            raise ValueError(
                f"Candidate cannot execute requested {name}; disable it explicitly and rebuild preview"
            )
    if policy.qualified and (
        (config.get("aesthetic") or {}).get("enabled")
        or str(base.get("hypernetwork") or "none").lower() not in {"", "none"}
    ):
        raise ValueError(
            "Candidate cannot execute requested non-prompt feature; disable it explicitly and rebuild preview"
        )


def build_comparison_snapshot(
    experiment: Any, baseline: dict, *, evidence=None, policy_resolver=None
) -> dict:
    """Build all semantic blueprints using one bounded canonical evidence context."""
    from src.image_backends.image_backend_types import normalize_image_backend_options
    from src.image_backends.model_policy import apply_model_compile_policy
    from src.learning.experiment_freeze import (
        apply_frozen_seed_policy,
        freeze_prompt_pack_source,
        freeze_seed_policy,
    )
    from src.learning.model_capabilities import policy_context
    from src.pipeline.compile_evidence import CompileEvidence
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy
    from src.pipeline.resolution_layer import (
        adapt_pack_intent,
        pack_prompt_intent_from_dict,
        pack_prompt_intent_to_dict,
        render_pack_intent,
    )

    metadata = dict(experiment.metadata or {})
    if experiment.stage != "txt2img" or experiment.input_image_path:
        raise ValueError("Model Comparison supports image txt2img only")
    if metadata.get("prompt_source") != "pack" or not metadata.get("selected_prompt_pack_path"):
        raise ValueError(
            "Model Comparison requires one PromptPack row; Custom/Current sources are not supported"
        )
    models = candidate_models(metadata.get("selected_models", metadata.get("selected_items", [])))
    baseline = copy.deepcopy(baseline)
    pipeline = baseline.get("pipeline") or {}
    baseline = apply_global_prompt_policy(
        baseline,
        positive_enabled=bool(pipeline.get("apply_global_positive_txt2img")),
        positive_text=str(baseline.get("global_positive_prompt") or ""),
        negative_enabled=bool(pipeline.get("apply_global_negative_txt2img")),
        negative_text=str(baseline.get("global_negative_prompt") or ""),
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
    global_negative = str(baseline.get("global_negative_prompt") or "")
    source = freeze_prompt_pack_source(
        metadata,
        global_negative=global_negative,
        structured=True,
        apply_global_negative=bool(
            (baseline.get("pipeline") or {}).get("apply_global_negative_txt2img")
        ),
    )
    intent = pack_prompt_intent_from_dict(source["source_intent"])
    source_sha = digest(source["source_intent"])
    seed_policy = freeze_seed_policy(
        baseline, experiment.images_per_value, preserved_policy=metadata.get("frozen_seed_policy")
    )
    evidence = evidence or CompileEvidence()
    optimizer_enabled = bool(
        (baseline.get("prompt_optimizer") or {}).get("enabled")
        or (section.get("prompt_optimizer") or {}).get("enabled")
    )
    arms = []
    for index, model in enumerate(models):
        policy = policy_resolver(model) if policy_resolver else evidence.policy_for(model)
        _require_candidate(policy)
        _require_envelope(policy, baseline, backend, geometry)
        adapted = adapt_pack_intent(
            intent,
            policy,
            lora_resolver=evidence.lora_evidence,
            optimizer_enabled=optimizer_enabled,
        )
        manifest = {"contract": "prompt_adaptation/1", **adapted.plan.to_diagnostics()}
        if manifest["complete"] is not True or manifest["adaptable"] is not True:
            raise ValueError(
                f"Model Comparison arm {index + 1}: prompt adaptation evidence is incomplete; verify target/LoRA compatibility and rebuild preview"
            )
        adapted_rendered = render_pack_intent(adapted.intent)
        # Keep global participation in adaptation evidence, but leave application
        # to the executor. This projection uses the canonical intent renderer;
        # it neither parses prompts nor changes the frozen execution apply flags.
        rendered = render_pack_intent(replace(adapted.intent, apply_global_negative=False))
        config = copy.deepcopy(baseline)
        for container in (config, config.setdefault("txt2img", {})):
            for key in ("model", "model_name", "sd_model_checkpoint", "base_model"):
                if key in container or key == "model":
                    container[key] = model
        config["backend_options"] = copy.deepcopy(options)
        config["backend_options"]["image"].pop("model_profile", None)
        apply_model_compile_policy(config)
        apply_frozen_seed_policy(config, seed_policy)
        config["pipeline"] = {
            **dict(config.get("pipeline") or {}),
            "txt2img_enabled": True,
            "img2img_enabled": False,
            "adetailer_enabled": False,
            "upscale_enabled": False,
        }
        for container in (config, config["txt2img"]):
            container["prompt"] = rendered.positive
            container["negative_prompt"] = rendered.negative
        # Structured declarations describe execution, not the unadapted source row.
        config["txt2img"]["lora_strengths"] = [
            {"name": name, "weight": weight} for name, weight in rendered.lora_tags
        ]
        if (
            config["txt2img"].get("width") != geometry["width"]
            or config["txt2img"].get("height") != geometry["height"]
        ):
            raise ValueError(
                "Canonical policy changed shared geometry; Model Comparison cannot normalize geometry"
            )
        if config["backend_options"]["image"]["backend_id"] != backend:
            raise ValueError(
                "Canonical policy changed backend; Model Comparison cannot switch runtimes"
            )
        arm = {
            "contract": CONTRACT,
            "study_type": STUDY_TYPE,
            "candidate_index": index,
            "selected_model": policy_context(policy, model, "txt2img")["selected_model"],
            "source_intent_sha256": source_sha,
            "model_policy_context": policy_context(policy, model, "txt2img"),
            "prompt_adaptation": manifest,
            "effective_intent": pack_prompt_intent_to_dict(adapted.intent),
            "adapted_positive_prompt": adapted_rendered.positive,
            "adapted_negative_prompt": adapted_rendered.negative,
            "executor_base_positive_prompt": rendered.positive,
            "executor_base_negative_prompt": rendered.negative,
            "executor_global_prompt_policy": executor_global_prompt_policy(config),
            "prompt_semantics": "executor_base_before_globals_and_optimizer",
            "effective_positive_embeddings": list(rendered.positive_embeddings),
            "effective_negative_embeddings": list(rendered.negative_embeddings),
            "effective_lora_tags": list(rendered.lora_tags),
            "effective_config": config,
            "effective_backend_options": config["backend_options"],
            "shared_geometry": geometry,
            "comparison_claim": COMPARISON_CLAIM,
            "causal_one_variable": False,
        }
        # Freeze JSON lists consistently before checksumming (no mutable objects escape).
        arm = json.loads(json.dumps(arm, allow_nan=False))
        arm["arm_sha256"] = digest(arm)
        arms.append(arm)
    study = {
        "contract": CONTRACT,
        "source_intent": source["source_intent"],
        "source_intent_sha256": source_sha,
        "source_intent_contract": source["source_intent"]["contract"],
        "shared_geometry": geometry,
        "arms": arms,
        "comparison_claim": COMPARISON_CLAIM,
        "causal_one_variable": False,
        "seed_interpretation": "requested seed held constant; latent/noise semantics may differ",
    }
    snapshot = {
        "schema_version": 2,
        "study_type": STUDY_TYPE,
        "model_comparison": study,
        "experiment_id": experiment.experiment_id,
        "display_name": experiment.name,
        "baseline_config": baseline,
        "prompt_text": source["rendered_positive_prompt"],
        "negative_prompt_text": source["rendered_negative_prompt"],
        "stage": "txt2img",
        "variable_under_test": "Model Comparison",
        "variant_values": models,
        "images_per_value": max(1, int(experiment.images_per_value or 1)),
        "seed_policy": seed_policy,
        "experiment_timestamp": datetime.utcnow().strftime("%Y%m%d-%H%M%S"),
        "prompt_source": source,
        "input_image_path": "",
    }
    frozen_arm(snapshot, models[0])
    return snapshot


def frozen_arm(snapshot: dict, value: Any) -> dict:
    """Validate every frozen arm before returning one; never look up live assets/rules."""
    from src.image_backends.model_policy import (
        ControlMode,
        Support,
        policy_for_model_profile_reference,
    )
    from src.learning.model_capabilities import policy_context
    from src.learning.model_policy_service import policy_from_context
    from src.pipeline.resolution_layer import pack_prompt_intent_from_dict, render_pack_intent

    study = snapshot.get("model_comparison") or {}
    if (
        snapshot.get("study_type") != STUDY_TYPE
        or snapshot.get("stage") != "txt2img"
        or study.get("contract") != CONTRACT
    ):
        raise ValueError("Invalid frozen Model Comparison contract; rebuild preview")
    if (
        study.get("comparison_claim") != COMPARISON_CLAIM
        or study.get("causal_one_variable") is not False
    ):
        raise ValueError("Model Comparison must retain target-envelope interpretation")
    models = candidate_models(snapshot.get("variant_values"))
    if value not in models or len(study.get("arms", [])) != len(models):
        raise ValueError("Variant is outside the frozen Model Comparison arms")
    source_sha = digest(study.get("source_intent"))
    if source_sha != study.get("source_intent_sha256"):
        raise ValueError("Frozen source-intent digest mismatch")
    pack_prompt_intent_from_dict(study["source_intent"])
    seeds = snapshot.get("seed_policy") or {}
    if seeds.get("requested_sample_count") != snapshot.get("images_per_value"):
        raise ValueError("Frozen sample count differs from seed request")
    for index, arm in enumerate(study["arms"]):
        sealed = {key: item for key, item in arm.items() if key != "arm_sha256"}
        if digest(sealed) != arm.get("arm_sha256"):
            raise ValueError("Frozen comparison arm integrity mismatch")
        if (
            arm.get("contract") != CONTRACT
            or arm.get("study_type") != STUDY_TYPE
            or arm.get("candidate_index") != index
            or arm.get("source_intent_sha256") != source_sha
            or arm.get("shared_geometry") != study.get("shared_geometry")
        ):
            raise ValueError("Frozen comparison source/geometry/identity mismatch")
        if (
            arm.get("comparison_claim") != COMPARISON_CLAIM
            or arm.get("causal_one_variable") is not False
        ):
            raise ValueError("Model Comparison must retain target-envelope interpretation")
        context = arm["model_policy_context"]
        policy = policy_from_context(context)
        _require_candidate(policy)
        config = arm["effective_config"]
        section = config["txt2img"]
        options = arm["effective_backend_options"]
        if config.get("backend_options") != options:
            raise ValueError("Frozen backend options mismatch")
        if context.get("profile_ref"):
            canonical = policy_for_model_profile_reference(options)
            if canonical is None or policy_context(canonical, models[index], "txt2img") != context:
                raise ValueError("Frozen exact profile is unknown or incompatible; rebuild preview")
        elif options["image"].get("model_profile") is not None:
            raise ValueError("Unexpected frozen model profile")
        _require_envelope(policy, config, options["image"]["backend_id"], study["shared_geometry"])
        for container in (config, section):
            if container.get("model") != models[index]:
                raise ValueError("Frozen model identity mismatch")
        if arm["selected_model"] != context["selected_model"] or context[
            "selected_model"
        ] != os.path.basename(models[index].replace("\\", "/")):
            raise ValueError("Frozen candidate identity mismatch")
        if {key: section[key] for key in ("width", "height")} != study["shared_geometry"]:
            raise ValueError("Frozen shared geometry mismatch")
        if (
            section.get("seed") != seeds.get("requested_base_seed")
            or (float(section.get("subseed_strength", 0.0) or 0.0) != seeds.get("subseed_strength"))
            or (
                float(seeds.get("subseed_strength", 0.0) or 0.0) > 0
                and section.get("subseed") != seeds.get("requested_subseed")
            )
        ):
            raise ValueError("Frozen arm differs from shared seed request")
        for name, key in (
            ("sampler", "sampler_name"),
            ("scheduler", "scheduler"),
            ("steps", "steps"),
            ("cfg_scale", "cfg_scale"),
            ("vae", "vae"),
        ):
            control = policy.control(name, "txt2img")
            if control.mode is ControlMode.FIXED and section.get(key) != control.value:
                raise ValueError("Frozen effective settings differ from canonical fixed policy")
        effective_intent = pack_prompt_intent_from_dict(arm["effective_intent"])
        adapted_rendered = render_pack_intent(effective_intent)
        rendered = render_pack_intent(replace(effective_intent, apply_global_negative=False))
        if (
            arm.get("executor_global_prompt_policy") != executor_global_prompt_policy(config)
            or arm.get("prompt_semantics") != "executor_base_before_globals_and_optimizer"
            or arm.get("adapted_positive_prompt") != adapted_rendered.positive
            or arm.get("adapted_negative_prompt") != adapted_rendered.negative
        ):
            raise ValueError("Frozen adapted/base/global prompt evidence mismatch")
        if policy.feature("negative_prompt").support is Support.UNSUPPORTED and (
            config["pipeline"]["apply_global_negative_txt2img"]
            or config["pipeline"]["apply_global_positive_txt2img"]
        ):
            raise ValueError("Frozen target cannot execute standard global prompt semantics")
        if policy.feature("negative_prompt").support is Support.UNSUPPORTED and rendered.negative:
            raise ValueError("Frozen target cannot execute a negative channel")
        if policy.feature("embeddings").support is Support.UNSUPPORTED and (
            rendered.positive_embeddings or rendered.negative_embeddings
        ):
            raise ValueError("Frozen target cannot execute embeddings")
        declarations = [{"name": name, "weight": weight} for name, weight in rendered.lora_tags]
        if section.get("lora_strengths") != declarations:
            raise ValueError("Frozen LoRA declarations differ from execution")
        for key, actual in (
            ("executor_base_positive_prompt", rendered.positive),
            ("executor_base_negative_prompt", rendered.negative),
            (
                "effective_positive_embeddings",
                [list(item) for item in rendered.positive_embeddings],
            ),
            (
                "effective_negative_embeddings",
                [list(item) for item in rendered.negative_embeddings],
            ),
            ("effective_lora_tags", [list(item) for item in rendered.lora_tags]),
        ):
            if arm.get(key) != actual:
                raise ValueError("Frozen prompt/provenance mismatch")
        for container in (config, section):
            if (
                container.get("prompt") != rendered.positive
                or container.get("negative_prompt") != rendered.negative
            ):
                raise ValueError("Frozen executable prompt mismatch")
        manifest = arm.get("prompt_adaptation") or {}
        if (
            manifest.get("contract") != "prompt_adaptation/1"
            or manifest.get("complete") is not True
            or manifest.get("adaptable") is not True
            or manifest.get("mode") != "compile"
        ):
            raise ValueError("Frozen prompt-adaptation manifest is missing or incomplete")
        if any(
            manifest.get(key) != context.get(key)
            for key in ("policy_id", "family", "evidence", "profile_ref")
        ):
            raise ValueError("Frozen adaptation target mismatch")
        expected_counts = {
            "positive_embeddings": len(rendered.positive_embeddings),
            "negative_embeddings": len(rendered.negative_embeddings),
            "loras": sum(lora.kind != "style" for lora in effective_intent.loras),
            "style_lora": sum(lora.kind == "style" for lora in effective_intent.loras),
            "negative_present": bool(
                adapted_rendered.negative.strip()
                and (
                    effective_intent.pack_negative
                    or effective_intent.global_negative_applied
                    or effective_intent.negative_phrases
                    or effective_intent.safety_negative
                )
            ),
        }
        if manifest.get("counts") != expected_counts:
            raise ValueError("Frozen adaptation counts differ from effective intent")
    return copy.deepcopy(study["arms"][models.index(value)])


def materialize_njr(
    snapshot: dict, variant: Any, *, metadata_factory, output_dir: str, filename_template: str
):
    """Materialize one Learning NJR from its preview blueprint, with no adaptation."""
    from src.learning.experiment_freeze import apply_frozen_seed_policy
    from src.pipeline.job_models_v2 import (
        CURRENT_NJR_SCHEMA_VERSION,
        ImageWorkloadSpec,
        LearningJobContext,
        LoRATag,
        NJRProvenance,
        NormalizedJobRecord,
        OutputPlan,
        SourceDescriptor,
        SourceKind,
        StageConfig,
        WorkloadKind,
    )
    from src.utils.embedding_prompt_utils import render_embedding_reference

    arm = frozen_arm(snapshot, variant.param_value)
    config = copy.deepcopy(arm["effective_config"])
    apply_frozen_seed_policy(config, snapshot["seed_policy"])
    config.update(
        learning_experiment_id=snapshot["experiment_id"],
        learning_variant_value=variant.param_value,
        learning_variable="Model Comparison",
    )
    section = config["txt2img"]
    metadata = metadata_factory(config)
    metadata.update(
        study_type=STUDY_TYPE,
        comparison_claim=COMPARISON_CLAIM,
        causal_one_variable=False,
        model_comparison=arm,
        prompt_adaptation=arm["prompt_adaptation"],
        source_intent_sha256=arm["source_intent_sha256"],
        shared_geometry=arm["shared_geometry"],
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
    context = LearningJobContext(
        experiment_id=snapshot["experiment_id"],
        experiment_name=snapshot["display_name"],
        variant_index=arm["candidate_index"],
        variable_under_test="Model Comparison",
        variant_value=variant.param_value,
    )
    record = NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id=f"learning_{snapshot['experiment_id']}_{uuid.uuid4().hex}",
        workload_kind=WorkloadKind.IMAGE,
        source=SourceDescriptor(kind=SourceKind.LEARNING, display_name=snapshot["display_name"]),
        workload=ImageWorkloadSpec(
            positive_prompt=arm["executor_base_positive_prompt"],
            negative_prompt=arm["executor_base_negative_prompt"],
            config=config,
            images_per_prompt=snapshot["images_per_value"],
            metadata=metadata,
            backend_options=arm["effective_backend_options"],
        ),
        stages=(
            StageConfig(
                stage_type="txt2img",
                enabled=True,
                model=section["model"],
                vae=section.get("vae", ""),
                steps=int(section["steps"]),
                cfg_scale=float(section["cfg_scale"]),
                sampler_name=section["sampler_name"],
                scheduler=section["scheduler"],
                extra={},
            ),
        ),
        output_plan=OutputPlan(
            base_output_dir=output_dir or "output", filename_template=filename_template
        ),
        provenance=NJRProvenance(
            seed=section["seed"],
            variant_index=arm["candidate_index"],
            variant_total=len(snapshot["variant_values"]),
            learning_context=context,
            positive_embeddings=tuple(
                render_embedding_reference(*item) for item in arm["effective_positive_embeddings"]
            ),
            negative_embeddings=tuple(
                render_embedding_reference(*item) for item in arm["effective_negative_embeddings"]
            ),
            lora_tags=tuple(
                LoRATag(name=name, weight=weight) for name, weight in arm["effective_lora_tags"]
            ),
            metadata=metadata,
        ),
    )
    if (
        record.positive_prompt != config["prompt"]
        or record.negative_prompt != config["negative_prompt"]
        or record.workload.backend_options != config["backend_options"]
    ):
        raise ValueError("Model Comparison NJR does not match frozen execution")
    return record


def rating_classification(
    snapshot: dict, value: Any, execution_metadata: dict | None = None
) -> dict:
    if snapshot.get("study_type") != STUDY_TYPE:
        return {"record_kind": "learning_experiment_rating"}
    arm = frozen_arm(snapshot, value)
    return {
        "record_kind": RECORD_KIND,
        "study_type": STUDY_TYPE,
        "comparison_claim": COMPARISON_CLAIM,
        "causal_one_variable": False,
        "model_comparison": arm,
        "prompt_adaptation": arm["prompt_adaptation"],
        "prompt_semantics": arm["prompt_semantics"],
        "runtime_prompt_readback": dict(
            (execution_metadata or {}).get("runtime_prompt_readback") or {}
        ),
    }


def runtime_prompt_readback(variant_payload: dict, metadata: dict) -> dict:
    """Retain executor truth only when supplied, including an empty negative channel."""
    readback = {}
    for key in ("final_prompt", "final_negative_prompt"):
        for source in (variant_payload, metadata):
            if key in source and isinstance(source[key], str):
                readback[key] = source[key]
                break
    return readback


def preview_summary(snapshot: dict) -> str:
    """Content-free readiness: no prompt text, asset names or local paths."""
    study = snapshot["model_comparison"]
    size = study["shared_geometry"]
    rows = [
        "Target-envelope comparison: model-specific validated settings and prompt adaptation; requested seed held constant."
    ]
    for arm in study["arms"]:
        context = arm["model_policy_context"]
        profile = context.get("profile_ref")
        target = f"{profile['id']} v{profile['version']}" if profile else context["family"]
        rows.append(
            f"Arm {arm['candidate_index'] + 1}: {target}; ready; adaptation {'changes' if arm['prompt_adaptation']['changed'] else 'preserves'} source projection; shared {size['width']}x{size['height']} valid."
        )
    return "\n".join(rows)
