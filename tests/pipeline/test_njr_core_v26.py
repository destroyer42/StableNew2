from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from src.pipeline.job_models_v2 import (
    CURRENT_NJR_SCHEMA_VERSION,
    ImageWorkloadSpec,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    TrainingWorkloadSpec,
    VideoWorkloadSpec,
    WorkloadKind,
    migrate_legacy_njr,
)

_TOP_LEVEL_FIELDS = (
    "schema_version",
    "job_id",
    "workload_kind",
    "source",
    "workload",
    "stages",
    "output_plan",
    "provenance",
)


def _image_record(*, source: SourceDescriptor | None = None) -> NormalizedJobRecord:
    return NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id="image-1",
        workload_kind=WorkloadKind.IMAGE,
        source=source or SourceDescriptor(kind=SourceKind.CLI),
        workload=ImageWorkloadSpec(
            positive_prompt="a lighthouse",
            config={"txt2img": {"width": 768}, "nested": {"values": [1, 2]}},
        ),
        stages=(StageConfig("txt2img", enabled=True),),
        output_plan=OutputPlan(base_output_dir="output/images"),
        provenance=NJRProvenance(seed=42, metadata={"origin": {"rows": [1]}}),
    )


def test_njr_has_exactly_eight_immutable_top_level_fields() -> None:
    record = _image_record()

    assert tuple(field.name for field in fields(record)) == _TOP_LEVEL_FIELDS
    assert tuple(record.to_dict()) == _TOP_LEVEL_FIELDS
    with pytest.raises(FrozenInstanceError):
        record.job_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        record.workload.config["new"] = True  # type: ignore[index]
    detached = record.config
    detached["nested"]["values"].append(3)
    assert record.config["nested"]["values"] == [1, 2]


def test_canonical_round_trip_preserves_every_value() -> None:
    record = _image_record(
        source=SourceDescriptor(
            kind=SourceKind.PROMPT_PACK,
            id="pack-1",
            revision="3",
            display_name="Lighthouses",
            row_index=2,
        )
    )

    assert NormalizedJobRecord.from_dict(record.to_dict()) == record


def test_prompt_pack_identity_is_conditional() -> None:
    assert _image_record().prompt_pack_id == ""
    with pytest.raises(ValueError, match="requires source.id"):
        SourceDescriptor(kind=SourceKind.PROMPT_PACK)


@pytest.mark.parametrize(
    ("kind", "source", "workload", "stage"),
    [
        (
            WorkloadKind.VIDEO,
            SourceDescriptor(kind=SourceKind.VIDEO_WORKFLOW),
            VideoWorkloadSpec(input_image_paths=("frame.png",)),
            StageConfig("svd_native", enabled=True),
        ),
        (
            WorkloadKind.TRAINING,
            SourceDescriptor(kind=SourceKind.TRAINING),
            TrainingWorkloadSpec(config={"train_lora": {"character_name": "Ada"}}),
            StageConfig("train_lora", enabled=True),
        ),
    ],
)
def test_non_image_workload_contracts(
    kind: WorkloadKind,
    source: SourceDescriptor,
    workload: VideoWorkloadSpec | TrainingWorkloadSpec,
    stage: StageConfig,
) -> None:
    record = NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id=f"{kind.value}-1",
        workload_kind=kind,
        source=source,
        workload=workload,
        stages=(stage,),
        output_plan=OutputPlan(),
        provenance=NJRProvenance(),
    )

    assert NormalizedJobRecord.from_dict(record.to_dict()) == record


def test_source_workload_and_stage_mismatches_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot authorize"):
        NormalizedJobRecord(
            schema_version=CURRENT_NJR_SCHEMA_VERSION,
            job_id="bad-source",
            workload_kind=WorkloadKind.IMAGE,
            source=SourceDescriptor(kind=SourceKind.TRAINING),
            workload=ImageWorkloadSpec(positive_prompt="prompt"),
            stages=(StageConfig("txt2img", enabled=True),),
            output_plan=OutputPlan(),
            provenance=NJRProvenance(),
        )
    with pytest.raises(ValueError, match="incompatible stages"):
        NormalizedJobRecord(
            schema_version=CURRENT_NJR_SCHEMA_VERSION,
            job_id="bad-stage",
            workload_kind=WorkloadKind.IMAGE,
            source=SourceDescriptor(kind=SourceKind.CLI),
            workload=ImageWorkloadSpec(positive_prompt="prompt"),
            stages=(StageConfig("svd_native", enabled=True),),
            output_plan=OutputPlan(),
            provenance=NJRProvenance(),
        )


def test_strict_reader_rejects_unknown_shape_and_schema() -> None:
    data = _image_record().to_dict()
    data["status"] = "queued"
    with pytest.raises(ValueError, match="top-level keys"):
        NormalizedJobRecord.from_dict(data)

    data = _image_record().to_dict()
    data["schema_version"] = "9.9"
    with pytest.raises(ValueError, match="unsupported"):
        NormalizedJobRecord.from_dict(data)


def test_legacy_migration_drops_execution_facts() -> None:
    record = migrate_legacy_njr(
        {
            "job_id": "legacy-1",
            "config": {"prompt": "legacy prompt", "model": "sdxl"},
            "stage_chain": [{"stage_type": "txt2img", "enabled": True}],
            "status": "completed",
            "completed_at_ts": 123.0,
            "output_paths": ["result.png"],
            "thumbnail_path": "thumb.png",
            "error_message": "old error",
        }
    )

    serialized = record.to_dict()
    assert tuple(serialized) == _TOP_LEVEL_FIELDS
    for forbidden in (
        "status",
        "completed_at_ts",
        "output_paths",
        "thumbnail_path",
        "error_message",
    ):
        assert forbidden not in serialized
