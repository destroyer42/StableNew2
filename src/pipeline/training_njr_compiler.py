"""Pure compiler for the supported train-LoRA NJR workload."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.pipeline.config_contract_v26 import (
    canonicalize_intent_config,
    derive_backend_options,
    validate_train_lora_execution_config,
)
from src.pipeline.job_models_v2 import (
    CURRENT_NJR_SCHEMA_VERSION,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    TrainingWorkloadSpec,
    WorkloadKind,
)


@dataclass(frozen=True, slots=True)
class TrainingIntent:
    """User-authorized training input; it contains no queue/runtime objects."""

    config: Mapping[str, Any]
    character_name: str
    character_key: str
    output_dir: str = "output"
    requested_job_label: str = "Character Training"


def compile_training_intent(
    intent: TrainingIntent,
    *,
    id_fn: Any | None = None,
) -> NormalizedJobRecord:
    """Compile validated training intent into one immutable NJR."""

    config = validate_train_lora_execution_config(dict(intent.config))
    train_config = dict(config.get("train_lora") or {})
    character_name = str(intent.character_name or train_config.get("character_name") or "").strip()
    character_key = str(intent.character_key or "character").strip() or "character"
    output_dir = str(train_config.get("output_dir") or intent.output_dir or "output")
    positive_prompt = f"Train LoRA for {character_name}" if character_name else "Train LoRA"
    metadata = {
        "job_type": "train_lora",
        "character_name": character_name,
        "character_key": character_key,
        "requested_job_label": intent.requested_job_label,
        "submission_source": "character_training",
    }
    return NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id=str((id_fn or (lambda: uuid4().hex))()),
        workload_kind=WorkloadKind.TRAINING,
        source=SourceDescriptor(
            kind=SourceKind.TRAINING,
            id=character_key,
            display_name=intent.requested_job_label,
            metadata=metadata,
        ),
        workload=TrainingWorkloadSpec(
            positive_prompt=positive_prompt,
            negative_prompt="",
            config=config,
            intent_config=canonicalize_intent_config(
                {
                    "source": "character_training",
                    "prompt_source": "training",
                    "character_key": character_key,
                    "requested_job_label": intent.requested_job_label,
                }
            ),
            backend_options=derive_backend_options(config),
            metadata=metadata,
        ),
        stages=(
            StageConfig(
                stage_type="train_lora",
                enabled=bool(train_config.get("enabled", True)),
                model=str(train_config.get("base_model") or ""),
                extra=train_config,
            ),
        ),
        output_plan=OutputPlan(base_output_dir=output_dir, filename_template="{seed}"),
        provenance=NJRProvenance(metadata=metadata),
    )


__all__ = ["TrainingIntent", "compile_training_intent"]
