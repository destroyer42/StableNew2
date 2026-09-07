"""Immutable eight-part Normalized Job Record contract for StableNew v2.6."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, TypeAlias

CURRENT_NJR_SCHEMA_VERSION = "2.6"

_IMAGE_STAGE_TYPES = {"txt2img", "img2img", "adetailer", "upscale"}
_VIDEO_STAGE_TYPES = {"animatediff", "svd_native", "video_workflow"}
_TRAINING_STAGE_TYPES = {"train_lora"}

JsonScalar: TypeAlias = str | int | float | bool | None
FrozenJsonValue: TypeAlias = "JsonScalar | tuple[FrozenJsonValue, ...] | FrozenJsonMap"


class FrozenJsonMap(Mapping[str, FrozenJsonValue]):
    """Recursively immutable JSON object used inside authorized NJR values."""

    __slots__ = ("_data",)

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self._data = {str(key): freeze_json(value) for key, value in dict(values or {}).items()}

    def __getitem__(self, key: str) -> FrozenJsonValue:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenJsonMap({self._data!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(sorted(self._data.items())))


def freeze_json(value: Any) -> FrozenJsonValue:
    """Validate and recursively freeze one JSON-compatible value."""

    if isinstance(value, FrozenJsonMap):
        return value
    if isinstance(value, Enum):
        return freeze_json(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return FrozenJsonMap(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"NJR values must be JSON-compatible, got {type(value).__name__}")


def freeze_json_mapping(value: Mapping[str, Any] | None) -> FrozenJsonMap:
    frozen = freeze_json(value or {})
    if not isinstance(frozen, FrozenJsonMap):
        raise TypeError("expected a JSON object")
    return frozen


def thaw_json(value: FrozenJsonValue | Any) -> Any:
    """Return a detached mutable JSON representation."""

    if isinstance(value, FrozenJsonMap):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_str(value: Any) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


class SourceKind(str, Enum):
    PROMPT_PACK = "prompt_pack"
    IMAGE_EDIT = "image_edit"
    REPROCESS = "reprocess"
    HISTORY_REPLAY = "history_replay"
    LEARNING = "learning"
    VIDEO_WORKFLOW = "video_workflow"
    CLI = "cli"
    TRAINING = "training"


class WorkloadKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    TRAINING = "training"


@dataclass(frozen=True)
class LearningJobContext:
    experiment_id: str
    experiment_name: str
    variant_index: int
    variable_under_test: str
    variant_value: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "variant_value", freeze_json(self.variant_value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "variant_index": self.variant_index,
            "variable_under_test": self.variable_under_test,
            "variant_value": thaw_json(self.variant_value),
        }


@dataclass(frozen=True)
class StagePromptInfo:
    original_prompt: str
    final_prompt: str
    original_negative_prompt: str
    final_negative_prompt: str
    global_negative_applied: bool
    global_negative_terms: str | None = None


@dataclass(frozen=True)
class PackUsageInfo:
    pack_name: str
    pack_path: str | None = None
    prompt_index: int | None = None
    used_for_stage: str = "txt2img"


@dataclass(frozen=True)
class LoRATag:
    name: str
    weight: float


@dataclass(frozen=True)
class StageConfig:
    stage_type: str
    enabled: bool = False
    steps: int | None = None
    cfg_scale: float | None = None
    denoising_strength: float | None = None
    sampler_name: str | None = None
    scheduler: str | None = None
    model: str | None = None
    vae: str | None = None
    extra: Mapping[str, Any] = field(default_factory=FrozenJsonMap)

    def __post_init__(self) -> None:
        raw_type = (
            self.stage_type.value if isinstance(self.stage_type, Enum) else str(self.stage_type)
        )
        if not raw_type:
            raise ValueError("stage_type is required")
        object.__setattr__(self, "stage_type", raw_type)
        object.__setattr__(self, "extra", freeze_json_mapping(self.extra))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_type": self.stage_type,
            "enabled": self.enabled,
            "steps": self.steps,
            "cfg_scale": self.cfg_scale,
            "denoising_strength": self.denoising_strength,
            "sampler_name": self.sampler_name,
            "scheduler": self.scheduler,
            "model": self.model,
            "vae": self.vae,
            "extra": thaw_json(self.extra),
        }

    @classmethod
    def from_value(cls, value: Any) -> StageConfig:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(stage_type=value, enabled=True)
        if not isinstance(value, Mapping):
            raise ValueError("NJR stage must be an object or stage name")
        return cls(
            stage_type=str(value.get("stage_type") or value.get("stage_name") or ""),
            enabled=bool(value.get("enabled", True)),
            steps=_optional_int(value.get("steps")),
            cfg_scale=_optional_float(value.get("cfg_scale")),
            denoising_strength=_optional_float(value.get("denoising_strength")),
            sampler_name=_optional_str(value.get("sampler_name")),
            scheduler=_optional_str(value.get("scheduler")),
            model=_optional_str(value.get("model")),
            vae=_optional_str(value.get("vae")),
            extra=_mapping_or_empty(value.get("extra")),
        )


@dataclass(frozen=True)
class SourceDescriptor:
    kind: SourceKind
    id: str | None = None
    revision: str | None = None
    display_name: str | None = None
    row_index: int | None = None
    parent_job_id: str | None = None
    parent_artifact_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=FrozenJsonMap)

    def __post_init__(self) -> None:
        kind = self.kind if isinstance(self.kind, SourceKind) else SourceKind(str(self.kind))
        object.__setattr__(self, "kind", kind)
        for name in (
            "id",
            "revision",
            "display_name",
            "parent_job_id",
            "parent_artifact_id",
        ):
            value = getattr(self, name)
            normalized = str(value).strip() if value is not None else None
            object.__setattr__(self, name, normalized or None)
        if self.row_index is not None and self.row_index < 0:
            raise ValueError("source.row_index cannot be negative")
        if kind is SourceKind.PROMPT_PACK and not self.id:
            raise ValueError("prompt_pack source requires source.id")
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "id": self.id,
            "revision": self.revision,
            "display_name": self.display_name,
            "row_index": self.row_index,
            "parent_job_id": self.parent_job_id,
            "parent_artifact_id": self.parent_artifact_id,
            "metadata": thaw_json(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SourceDescriptor:
        return cls(
            kind=SourceKind(str(data["kind"])),
            id=data.get("id"),
            revision=data.get("revision"),
            display_name=data.get("display_name"),
            row_index=int(data["row_index"]) if data.get("row_index") is not None else None,
            parent_job_id=data.get("parent_job_id"),
            parent_artifact_id=data.get("parent_artifact_id"),
            metadata=_mapping_or_empty(data.get("metadata")),
        )


@dataclass(frozen=True)
class WorkloadSpec:
    positive_prompt: str = ""
    negative_prompt: str = ""
    config: Mapping[str, Any] = field(default_factory=FrozenJsonMap)
    input_image_paths: tuple[str, ...] = ()
    start_stage: str | None = None
    images_per_prompt: int = 1
    loop_type: Literal["pipeline", "prompt", "image"] = "pipeline"
    loop_count: int = 1
    variant_mode: str = "standard"
    intent_config: Mapping[str, Any] = field(default_factory=FrozenJsonMap)
    backend_options: Mapping[str, Any] = field(default_factory=FrozenJsonMap)
    metadata: Mapping[str, Any] = field(default_factory=FrozenJsonMap)

    def __post_init__(self) -> None:
        if self.images_per_prompt <= 0:
            raise ValueError("workload.images_per_prompt must be positive")
        if self.loop_count <= 0:
            raise ValueError("workload.loop_count must be positive")
        if self.loop_type not in {"pipeline", "prompt", "image"}:
            raise ValueError(f"unsupported workload.loop_type: {self.loop_type}")
        object.__setattr__(
            self,
            "input_image_paths",
            tuple(str(path) for path in self.input_image_paths if str(path)),
        )
        object.__setattr__(self, "config", freeze_json_mapping(self.config))
        object.__setattr__(self, "intent_config", freeze_json_mapping(self.intent_config))
        object.__setattr__(self, "backend_options", freeze_json_mapping(self.backend_options))
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    def common_dict(self) -> dict[str, Any]:
        return {
            "positive_prompt": self.positive_prompt,
            "negative_prompt": self.negative_prompt,
            "config": thaw_json(self.config),
            "input_image_paths": list(self.input_image_paths),
            "start_stage": self.start_stage,
            "images_per_prompt": self.images_per_prompt,
            "loop_type": self.loop_type,
            "loop_count": self.loop_count,
            "variant_mode": self.variant_mode,
            "intent_config": thaw_json(self.intent_config),
            "backend_options": thaw_json(self.backend_options),
            "metadata": thaw_json(self.metadata),
        }


@dataclass(frozen=True)
class ImageWorkloadSpec(WorkloadSpec):
    def to_dict(self) -> dict[str, Any]:
        return self.common_dict()


@dataclass(frozen=True)
class VideoWorkloadSpec(WorkloadSpec):
    sequence_intent: Mapping[str, Any] | None = None
    continuity_link: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.sequence_intent is not None:
            object.__setattr__(
                self,
                "sequence_intent",
                freeze_json_mapping(self.sequence_intent),
            )
        if self.continuity_link is not None:
            object.__setattr__(
                self,
                "continuity_link",
                freeze_json_mapping(self.continuity_link),
            )

    def to_dict(self) -> dict[str, Any]:
        data = self.common_dict()
        data["sequence_intent"] = (
            thaw_json(self.sequence_intent) if self.sequence_intent is not None else None
        )
        data["continuity_link"] = (
            thaw_json(self.continuity_link) if self.continuity_link is not None else None
        )
        return data


@dataclass(frozen=True)
class TrainingWorkloadSpec(WorkloadSpec):
    def to_dict(self) -> dict[str, Any]:
        return self.common_dict()


Workload: TypeAlias = ImageWorkloadSpec | VideoWorkloadSpec | TrainingWorkloadSpec


@dataclass(frozen=True)
class OutputPlan:
    base_output_dir: str = "output"
    filename_template: str = "{seed}"
    route: str | None = None

    def __post_init__(self) -> None:
        if not str(self.base_output_dir).strip():
            raise ValueError("output_plan.base_output_dir is required")
        if not str(self.filename_template).strip():
            raise ValueError("output_plan.filename_template is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_output_dir": self.base_output_dir,
            "filename_template": self.filename_template,
            "route": self.route,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OutputPlan:
        return cls(
            base_output_dir=str(data.get("base_output_dir") or "output"),
            filename_template=str(data.get("filename_template") or "{seed}"),
            route=_optional_str(data.get("route")),
        )


def _prompt_info_to_dict(value: StagePromptInfo | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "original_prompt": value.original_prompt,
        "final_prompt": value.final_prompt,
        "original_negative_prompt": value.original_negative_prompt,
        "final_negative_prompt": value.final_negative_prompt,
        "global_negative_applied": value.global_negative_applied,
        "global_negative_terms": value.global_negative_terms,
    }


def _prompt_info_from_value(value: Any) -> StagePromptInfo | None:
    if not isinstance(value, Mapping):
        return None
    return StagePromptInfo(
        original_prompt=str(value.get("original_prompt") or ""),
        final_prompt=str(value.get("final_prompt") or ""),
        original_negative_prompt=str(value.get("original_negative_prompt") or ""),
        final_negative_prompt=str(value.get("final_negative_prompt") or ""),
        global_negative_applied=bool(value.get("global_negative_applied", False)),
        global_negative_terms=_optional_str(value.get("global_negative_terms")),
    )


@dataclass(frozen=True)
class NJRProvenance:
    seed: int | None = None
    variant_index: int = 0
    variant_total: int = 1
    batch_index: int = 0
    batch_total: int = 1
    randomizer_summary: Mapping[str, Any] = field(default_factory=FrozenJsonMap)
    matrix_slot_values: Mapping[str, Any] = field(default_factory=FrozenJsonMap)
    matrix_name: str | None = None
    matrix_mode: str | None = None
    matrix_prompt_mode: str | None = None
    config_variant_label: str = "base"
    config_variant_index: int = 0
    config_variant_overrides: Mapping[str, Any] = field(default_factory=FrozenJsonMap)
    positive_embeddings: tuple[str, ...] = ()
    negative_embeddings: tuple[str, ...] = ()
    lora_tags: tuple[LoRATag, ...] = ()
    pack_usage: tuple[PackUsageInfo, ...] = ()
    txt2img_prompt_info: StagePromptInfo | None = None
    img2img_prompt_info: StagePromptInfo | None = None
    aesthetic_enabled: bool = False
    aesthetic_weight: float | None = None
    aesthetic_text: str | None = None
    aesthetic_embedding: str | None = None
    learning_context: LearningJobContext | None = None
    metadata: Mapping[str, Any] = field(default_factory=FrozenJsonMap)

    def __post_init__(self) -> None:
        if self.variant_total <= 0 or not 0 <= self.variant_index < self.variant_total:
            raise ValueError("invalid provenance variant index/total")
        if self.batch_total <= 0 or not 0 <= self.batch_index < self.batch_total:
            raise ValueError("invalid provenance batch index/total")
        if self.config_variant_index < 0:
            raise ValueError("provenance.config_variant_index cannot be negative")
        object.__setattr__(
            self,
            "randomizer_summary",
            freeze_json_mapping(self.randomizer_summary),
        )
        object.__setattr__(
            self,
            "matrix_slot_values",
            freeze_json_mapping(self.matrix_slot_values),
        )
        object.__setattr__(
            self,
            "config_variant_overrides",
            freeze_json_mapping(self.config_variant_overrides),
        )
        object.__setattr__(
            self,
            "positive_embeddings",
            tuple(str(value) for value in self.positive_embeddings),
        )
        object.__setattr__(
            self,
            "negative_embeddings",
            tuple(str(value) for value in self.negative_embeddings),
        )
        object.__setattr__(self, "lora_tags", tuple(self.lora_tags))
        object.__setattr__(self, "pack_usage", tuple(self.pack_usage))
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "variant_index": self.variant_index,
            "variant_total": self.variant_total,
            "batch_index": self.batch_index,
            "batch_total": self.batch_total,
            "randomizer_summary": thaw_json(self.randomizer_summary),
            "matrix_slot_values": thaw_json(self.matrix_slot_values),
            "matrix_name": self.matrix_name,
            "matrix_mode": self.matrix_mode,
            "matrix_prompt_mode": self.matrix_prompt_mode,
            "config_variant_label": self.config_variant_label,
            "config_variant_index": self.config_variant_index,
            "config_variant_overrides": thaw_json(self.config_variant_overrides),
            "positive_embeddings": list(self.positive_embeddings),
            "negative_embeddings": list(self.negative_embeddings),
            "lora_tags": [{"name": tag.name, "weight": tag.weight} for tag in self.lora_tags],
            "pack_usage": [
                {
                    "pack_name": usage.pack_name,
                    "pack_path": usage.pack_path,
                    "prompt_index": usage.prompt_index,
                    "used_for_stage": usage.used_for_stage,
                }
                for usage in self.pack_usage
            ],
            "txt2img_prompt_info": _prompt_info_to_dict(self.txt2img_prompt_info),
            "img2img_prompt_info": _prompt_info_to_dict(self.img2img_prompt_info),
            "aesthetic_enabled": self.aesthetic_enabled,
            "aesthetic_weight": self.aesthetic_weight,
            "aesthetic_text": self.aesthetic_text,
            "aesthetic_embedding": self.aesthetic_embedding,
            "learning_context": (
                self.learning_context.to_dict() if self.learning_context is not None else None
            ),
            "metadata": thaw_json(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NJRProvenance:
        learning_data = data.get("learning_context")
        learning_context = None
        if isinstance(learning_data, Mapping):
            learning_context = LearningJobContext(
                experiment_id=str(learning_data.get("experiment_id") or ""),
                experiment_name=str(learning_data.get("experiment_name") or ""),
                variant_index=int(learning_data.get("variant_index") or 0),
                variable_under_test=str(learning_data.get("variable_under_test") or ""),
                variant_value=learning_data.get("variant_value"),
            )
        return cls(
            seed=_optional_int(data.get("seed")),
            variant_index=int(data.get("variant_index") or 0),
            variant_total=int(data.get("variant_total") or 1),
            batch_index=int(data.get("batch_index") or 0),
            batch_total=int(data.get("batch_total") or 1),
            randomizer_summary=_mapping_or_empty(data.get("randomizer_summary")),
            matrix_slot_values=_mapping_or_empty(data.get("matrix_slot_values")),
            matrix_name=_optional_str(data.get("matrix_name")),
            matrix_mode=_optional_str(data.get("matrix_mode")),
            matrix_prompt_mode=_optional_str(data.get("matrix_prompt_mode")),
            config_variant_label=str(data.get("config_variant_label") or "base"),
            config_variant_index=int(data.get("config_variant_index") or 0),
            config_variant_overrides=_mapping_or_empty(data.get("config_variant_overrides")),
            positive_embeddings=tuple(data.get("positive_embeddings") or ()),
            negative_embeddings=tuple(data.get("negative_embeddings") or ()),
            lora_tags=tuple(
                LoRATag(name=str(item["name"]), weight=float(item["weight"]))
                for item in data.get("lora_tags") or ()
                if isinstance(item, Mapping)
            ),
            pack_usage=tuple(
                PackUsageInfo(
                    pack_name=str(item.get("pack_name") or ""),
                    pack_path=_optional_str(item.get("pack_path")),
                    prompt_index=_optional_int(item.get("prompt_index")),
                    used_for_stage=str(item.get("used_for_stage") or "txt2img"),
                )
                for item in data.get("pack_usage") or ()
                if isinstance(item, Mapping)
            ),
            txt2img_prompt_info=_prompt_info_from_value(data.get("txt2img_prompt_info")),
            img2img_prompt_info=_prompt_info_from_value(data.get("img2img_prompt_info")),
            aesthetic_enabled=bool(data.get("aesthetic_enabled", False)),
            aesthetic_weight=_optional_float(data.get("aesthetic_weight")),
            aesthetic_text=_optional_str(data.get("aesthetic_text")),
            aesthetic_embedding=_optional_str(data.get("aesthetic_embedding")),
            learning_context=learning_context,
            metadata=_mapping_or_empty(data.get("metadata")),
        )


def _workload_common_from_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "positive_prompt": str(data.get("positive_prompt") or ""),
        "negative_prompt": str(data.get("negative_prompt") or ""),
        "config": _mapping_or_empty(data.get("config")),
        "input_image_paths": tuple(str(path) for path in data.get("input_image_paths") or ()),
        "start_stage": _optional_str(data.get("start_stage")),
        "images_per_prompt": int(data.get("images_per_prompt") or 1),
        "loop_type": str(data.get("loop_type") or "pipeline"),
        "loop_count": int(data.get("loop_count") or 1),
        "variant_mode": str(data.get("variant_mode") or "standard"),
        "intent_config": _mapping_or_empty(data.get("intent_config")),
        "backend_options": _mapping_or_empty(data.get("backend_options")),
        "metadata": _mapping_or_empty(data.get("metadata")),
    }


@dataclass(frozen=True)
class NormalizedJobRecord:
    """Immutable, versioned description of authorized work."""

    schema_version: str
    job_id: str
    workload_kind: WorkloadKind
    source: SourceDescriptor
    workload: Workload
    stages: tuple[StageConfig, ...]
    output_plan: OutputPlan
    provenance: NJRProvenance

    def __post_init__(self) -> None:
        if self.schema_version != CURRENT_NJR_SCHEMA_VERSION:
            raise ValueError(f"unsupported NJR schema_version: {self.schema_version}")
        if not str(self.job_id).strip():
            raise ValueError("NJR job_id is required")
        kind = (
            self.workload_kind
            if isinstance(self.workload_kind, WorkloadKind)
            else WorkloadKind(str(self.workload_kind))
        )
        object.__setattr__(self, "workload_kind", kind)
        object.__setattr__(self, "stages", tuple(self.stages))
        if not self.stages:
            raise ValueError("NJR requires at least one stage")
        if not any(stage.enabled for stage in self.stages):
            raise ValueError("NJR requires at least one enabled stage")
        self._validate_workload_type()
        self._validate_source_workload()
        self._validate_stages()

    def _validate_workload_type(self) -> None:
        expected: dict[WorkloadKind, type[WorkloadSpec]] = {
            WorkloadKind.IMAGE: ImageWorkloadSpec,
            WorkloadKind.VIDEO: VideoWorkloadSpec,
            WorkloadKind.TRAINING: TrainingWorkloadSpec,
        }
        if not isinstance(self.workload, expected[self.workload_kind]):
            raise ValueError(
                f"{self.workload_kind.value} NJR requires {expected[self.workload_kind].__name__}"
            )

    def _validate_source_workload(self) -> None:
        required_kinds = {
            SourceKind.PROMPT_PACK: WorkloadKind.IMAGE,
            SourceKind.IMAGE_EDIT: WorkloadKind.IMAGE,
            SourceKind.REPROCESS: WorkloadKind.IMAGE,
            SourceKind.LEARNING: WorkloadKind.IMAGE,
            SourceKind.VIDEO_WORKFLOW: WorkloadKind.VIDEO,
            SourceKind.CLI: WorkloadKind.IMAGE,
            SourceKind.TRAINING: WorkloadKind.TRAINING,
        }
        expected = required_kinds.get(self.source.kind)
        if expected is not None and expected is not self.workload_kind:
            raise ValueError(
                f"source {self.source.kind.value} cannot authorize "
                f"{self.workload_kind.value} workload"
            )

    def _validate_stages(self) -> None:
        stage_names = {stage.stage_type for stage in self.stages if stage.enabled}
        permitted = {
            WorkloadKind.IMAGE: _IMAGE_STAGE_TYPES,
            WorkloadKind.VIDEO: _VIDEO_STAGE_TYPES,
            WorkloadKind.TRAINING: _TRAINING_STAGE_TYPES,
        }[self.workload_kind]
        invalid = stage_names - permitted
        if invalid:
            raise ValueError(
                f"{self.workload_kind.value} workload has incompatible stages: {sorted(invalid)}"
            )
        if self.workload_kind is WorkloadKind.TRAINING and stage_names != {"train_lora"}:
            raise ValueError("training NJR must enable only train_lora")
        if (
            self.workload_kind is WorkloadKind.IMAGE
            and "txt2img" in stage_names
            and not self.workload.positive_prompt.strip()
        ):
            raise ValueError("txt2img workload requires a positive prompt")

    @property
    def config(self) -> dict[str, Any]:
        return thaw_json(self.workload.config)

    @property
    def path_output_dir(self) -> str:
        return self.output_plan.base_output_dir

    @property
    def filename_template(self) -> str:
        return self.output_plan.filename_template

    @property
    def seed(self) -> int | None:
        return self.provenance.seed

    @property
    def variant_index(self) -> int:
        return self.provenance.variant_index

    @property
    def variant_total(self) -> int:
        return self.provenance.variant_total

    @property
    def batch_index(self) -> int:
        return self.provenance.batch_index

    @property
    def batch_total(self) -> int:
        return self.provenance.batch_total

    @property
    def randomizer_summary(self) -> dict[str, Any]:
        return thaw_json(self.provenance.randomizer_summary)

    @property
    def txt2img_prompt_info(self) -> StagePromptInfo | None:
        return self.provenance.txt2img_prompt_info

    @property
    def img2img_prompt_info(self) -> StagePromptInfo | None:
        return self.provenance.img2img_prompt_info

    @property
    def pack_usage(self) -> tuple[PackUsageInfo, ...]:
        return self.provenance.pack_usage

    @property
    def prompt_source(self) -> str:
        return "pack" if self.source.kind is SourceKind.PROMPT_PACK else self.source.kind.value

    @property
    def prompt_pack_id(self) -> str:
        if self.source.kind is SourceKind.PROMPT_PACK:
            return self.source.id or ""
        return ""

    @property
    def prompt_pack_name(self) -> str:
        if self.source.kind is SourceKind.PROMPT_PACK:
            return self.source.display_name or self.source.id or ""
        return ""

    @property
    def prompt_pack_row_index(self) -> int:
        return self.source.row_index or 0

    @property
    def prompt_pack_version(self) -> str | None:
        return self.source.revision

    @property
    def positive_prompt(self) -> str:
        return self.workload.positive_prompt

    @property
    def negative_prompt(self) -> str:
        return self.workload.negative_prompt

    @property
    def positive_embeddings(self) -> tuple[str, ...]:
        return self.provenance.positive_embeddings

    @property
    def negative_embeddings(self) -> tuple[str, ...]:
        return self.provenance.negative_embeddings

    @property
    def lora_tags(self) -> tuple[LoRATag, ...]:
        return self.provenance.lora_tags

    @property
    def matrix_slot_values(self) -> dict[str, Any]:
        return thaw_json(self.provenance.matrix_slot_values)

    @property
    def stage_chain(self) -> tuple[StageConfig, ...]:
        return self.stages

    @property
    def images_per_prompt(self) -> int:
        return self.workload.images_per_prompt

    @property
    def loop_type(self) -> str:
        return self.workload.loop_type

    @property
    def loop_count(self) -> int:
        return self.workload.loop_count

    @property
    def variant_mode(self) -> str:
        return self.workload.variant_mode

    @property
    def input_image_paths(self) -> tuple[str, ...]:
        return self.workload.input_image_paths

    @property
    def start_stage(self) -> str | None:
        return self.workload.start_stage

    @property
    def learning_context(self) -> LearningJobContext | None:
        return self.provenance.learning_context

    @property
    def sequence_intent(self) -> dict[str, Any] | None:
        if not isinstance(self.workload, VideoWorkloadSpec):
            return None
        if self.workload.sequence_intent is None:
            return None
        return thaw_json(self.workload.sequence_intent)

    @property
    def continuity_link(self) -> dict[str, Any] | None:
        if not isinstance(self.workload, VideoWorkloadSpec):
            return None
        if self.workload.continuity_link is None:
            return None
        return thaw_json(self.workload.continuity_link)

    @property
    def extra_metadata(self) -> dict[str, Any]:
        return thaw_json(self.provenance.metadata)

    @property
    def intent_config(self) -> dict[str, Any]:
        return thaw_json(self.workload.intent_config)

    @property
    def backend_options(self) -> dict[str, Any]:
        return thaw_json(self.workload.backend_options)

    @property
    def matrix_name(self) -> str | None:
        return self.provenance.matrix_name

    @property
    def matrix_mode(self) -> str | None:
        return self.provenance.matrix_mode

    @property
    def matrix_prompt_mode(self) -> str | None:
        return self.provenance.matrix_prompt_mode

    @property
    def config_variant_label(self) -> str:
        return self.provenance.config_variant_label

    @property
    def config_variant_index(self) -> int:
        return self.provenance.config_variant_index

    @property
    def config_variant_overrides(self) -> dict[str, Any]:
        return thaw_json(self.provenance.config_variant_overrides)

    @property
    def randomization_enabled(self) -> bool:
        return bool(self.provenance.randomizer_summary.get("enabled", False))

    @property
    def aesthetic_enabled(self) -> bool:
        return self.provenance.aesthetic_enabled

    @property
    def aesthetic_weight(self) -> float | None:
        return self.provenance.aesthetic_weight

    @property
    def aesthetic_text(self) -> str | None:
        return self.provenance.aesthetic_text

    @property
    def aesthetic_embedding(self) -> str | None:
        return self.provenance.aesthetic_embedding

    def _stage_value(self, attribute: str) -> Any:
        for stage in self.stages:
            if stage.enabled:
                value = getattr(stage, attribute, None)
                if value not in (None, ""):
                    return value
        return None

    def _config_value(self, *keys: str) -> Any:
        config = self.config
        for key in keys:
            value = config.get(key)
            if value not in (None, "", []):
                return value
        for section_name in ("txt2img", "img2img", "svd_native", "train_lora"):
            section = config.get(section_name)
            if not isinstance(section, Mapping):
                continue
            for key in keys:
                value = section.get(key)
                if value not in (None, "", []):
                    return value
        return None

    @property
    def steps(self) -> int:
        return int(self._stage_value("steps") or self._config_value("steps") or 0)

    @property
    def cfg_scale(self) -> float:
        return float(self._stage_value("cfg_scale") or self._config_value("cfg_scale") or 0.0)

    @property
    def width(self) -> int:
        return int(self._config_value("width") or 0)

    @property
    def height(self) -> int:
        return int(self._config_value("height") or 0)

    @property
    def sampler_name(self) -> str:
        return str(
            self._stage_value("sampler_name") or self._config_value("sampler_name", "sampler") or ""
        )

    @property
    def scheduler(self) -> str:
        return str(self._stage_value("scheduler") or self._config_value("scheduler") or "")

    @property
    def clip_skip(self) -> int:
        return int(self._config_value("clip_skip") or 0)

    @property
    def base_model(self) -> str:
        return str(
            self._stage_value("model")
            or self._config_value("model", "model_name", "base_model")
            or ""
        )

    @property
    def vae(self) -> str | None:
        value = self._stage_value("vae") or self._config_value("vae", "vae_name")
        return str(value) if value else None

    @property
    def num_parts(self) -> int:
        return len(self.pack_usage) if self.pack_usage else 1

    @property
    def num_expected_images(self) -> int:
        total = self.variant_total * self.batch_total
        return total if total > 0 else 1

    @property
    def is_pack_job(self) -> bool:
        return self.source.kind is SourceKind.PROMPT_PACK

    @property
    def stage_chain_labels(self) -> list[str]:
        return [stage.stage_type for stage in self.stages if stage.enabled]

    def matrix_slot_values_preview(self) -> str:
        return "; ".join(f"{key}={value}" for key, value in self.matrix_slot_values.items())

    @property
    def lora_preview(self) -> str:
        return ", ".join(f"{tag.name}({tag.weight})" for tag in self.lora_tags)

    def estimated_image_count(self) -> int:
        return max(1, self.images_per_prompt * self.loop_count)

    def _extract_prompt_field(self, attr_name: str, *fallback_keys: str) -> str:
        if self.txt2img_prompt_info:
            info_value = getattr(self.txt2img_prompt_info, attr_name, None)
            if info_value:
                return str(info_value)
        fallback = self._config_value(*fallback_keys)
        return str(fallback) if fallback is not None else ""

    def _extract_stage_names(self) -> list[str]:
        return self.stage_chain_labels

    def _extract_model_name(self) -> str:
        return self.base_model or "unknown"

    def get_display_summary(self) -> str:
        primary_label = self.prompt_pack_name or self.base_model or self.source.kind.value
        total_images = int(self._config_value("batch_size") or 1) * int(
            self._config_value("n_iter") or 1
        )
        image_info = f" | {total_images} images" if total_images > 1 else " | (1 image)"
        seed_text = str(self.seed) if self.seed is not None else "?"
        variant_info = (
            f" [v{self.variant_index + 1}/{self.variant_total}]" if self.variant_total > 1 else ""
        )
        batch_info = (
            f" [b{self.batch_index + 1}/{self.batch_total}]" if self.batch_total > 1 else ""
        )
        return f"{primary_label}{image_info} | seed={seed_text}{variant_info}{batch_info}"

    def to_unified_summary(self) -> Any:
        from src.pipeline.job_models_v2 import UnifiedJobSummary

        return UnifiedJobSummary.from_normalized_record(self)

    def to_ui_summary(self) -> Any:
        from src.pipeline.job_models_v2 import JobUiSummary

        return JobUiSummary.from_job_view(self.to_job_view())

    def to_job_view(
        self,
        *,
        status: str = "queued",
        created_at: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        is_active: bool = False,
        last_error: str | None = None,
        worker_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Any:
        from src.pipeline.job_models_v2 import JobView

        return JobView.from_njr(
            self,
            status=status,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            is_active=is_active,
            last_error=last_error,
            worker_id=worker_id,
            result=result,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "workload_kind": self.workload_kind.value,
            "source": self.source.to_dict(),
            "workload": self.workload.to_dict(),
            "stages": [stage.to_dict() for stage in self.stages],
            "output_plan": self.output_plan.to_dict(),
            "provenance": self.provenance.to_dict(),
        }

    def to_queue_snapshot(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NormalizedJobRecord:
        expected_keys = {
            "schema_version",
            "job_id",
            "workload_kind",
            "source",
            "workload",
            "stages",
            "output_plan",
            "provenance",
        }
        if set(data) != expected_keys:
            missing = sorted(expected_keys - set(data))
            extra = sorted(set(data) - expected_keys)
            raise ValueError(f"invalid NJR top-level keys; missing={missing}, extra={extra}")
        workload_kind = WorkloadKind(str(data["workload_kind"]))
        workload_data = data["workload"]
        if not isinstance(workload_data, Mapping):
            raise ValueError("NJR workload must be an object")
        common = _workload_common_from_dict(workload_data)
        if workload_kind is WorkloadKind.IMAGE:
            workload: Workload = ImageWorkloadSpec(**common)
        elif workload_kind is WorkloadKind.VIDEO:
            workload = VideoWorkloadSpec(
                **common,
                sequence_intent=(
                    _mapping_or_empty(workload_data.get("sequence_intent"))
                    if workload_data.get("sequence_intent") is not None
                    else None
                ),
                continuity_link=(
                    _mapping_or_empty(workload_data.get("continuity_link"))
                    if workload_data.get("continuity_link") is not None
                    else None
                ),
            )
        else:
            workload = TrainingWorkloadSpec(**common)
        source_data = data["source"]
        output_data = data["output_plan"]
        provenance_data = data["provenance"]
        if not isinstance(source_data, Mapping):
            raise ValueError("NJR source must be an object")
        if not isinstance(output_data, Mapping):
            raise ValueError("NJR output_plan must be an object")
        if not isinstance(provenance_data, Mapping):
            raise ValueError("NJR provenance must be an object")
        stage_data = data["stages"]
        if not isinstance(stage_data, Sequence) or isinstance(stage_data, (str, bytes)):
            raise ValueError("NJR stages must be an array")
        return cls(
            schema_version=str(data["schema_version"]),
            job_id=str(data["job_id"]),
            workload_kind=workload_kind,
            source=SourceDescriptor.from_dict(source_data),
            workload=workload,
            stages=tuple(StageConfig.from_value(stage) for stage in stage_data),
            output_plan=OutputPlan.from_dict(output_data),
            provenance=NJRProvenance.from_dict(provenance_data),
        )


def _legacy_stage_chain(
    data: Mapping[str, Any],
    config: Mapping[str, Any],
) -> tuple[StageConfig, ...]:
    raw_stages = data.get("stage_chain")
    stages: list[StageConfig] = []
    if isinstance(raw_stages, Sequence) and not isinstance(raw_stages, (str, bytes)):
        stages = [StageConfig.from_value(stage) for stage in raw_stages]
    if not stages:
        configured = config.get("stages")
        if isinstance(configured, Sequence) and not isinstance(configured, (str, bytes)):
            stages = [StageConfig.from_value(stage) for stage in configured]
    if not stages:
        if isinstance(config.get("train_lora"), Mapping):
            stages = [
                StageConfig.from_value({"stage_type": "train_lora", "extra": config["train_lora"]})
            ]
        elif isinstance(config.get("svd_native"), Mapping):
            stages = [
                StageConfig.from_value({"stage_type": "svd_native", "extra": config["svd_native"]})
            ]
        elif isinstance(config.get("video_workflow"), Mapping):
            stages = [
                StageConfig.from_value(
                    {"stage_type": "video_workflow", "extra": config["video_workflow"]}
                )
            ]
        else:
            stages = [
                StageConfig.from_value(
                    {
                        "stage_type": "txt2img",
                        "steps": data.get("steps") or config.get("steps"),
                        "cfg_scale": data.get("cfg_scale") or config.get("cfg_scale"),
                        "model": data.get("base_model") or config.get("model"),
                    }
                )
            ]
    return tuple(stages)


def _legacy_source_kind(
    data: Mapping[str, Any],
    stages: tuple[StageConfig, ...],
) -> SourceKind:
    raw = str(data.get("prompt_source") or data.get("source_kind") or "").lower()
    aliases = {
        "pack": SourceKind.PROMPT_PACK,
        "prompt_pack": SourceKind.PROMPT_PACK,
        "image_edit": SourceKind.IMAGE_EDIT,
        "reprocess": SourceKind.REPROCESS,
        "history": SourceKind.HISTORY_REPLAY,
        "history_replay": SourceKind.HISTORY_REPLAY,
        "learning": SourceKind.LEARNING,
        "video": SourceKind.VIDEO_WORKFLOW,
        "video_workflow": SourceKind.VIDEO_WORKFLOW,
        "cli": SourceKind.CLI,
        "manual": SourceKind.CLI,
        "training": SourceKind.TRAINING,
    }
    if raw in aliases:
        return aliases[raw]
    stage_names = {stage.stage_type for stage in stages}
    if stage_names & _TRAINING_STAGE_TYPES:
        return SourceKind.TRAINING
    if stage_names & _VIDEO_STAGE_TYPES:
        return SourceKind.VIDEO_WORKFLOW
    if data.get("prompt_pack_id"):
        return SourceKind.PROMPT_PACK
    return SourceKind.CLI


def migrate_legacy_njr(data: Mapping[str, Any]) -> NormalizedJobRecord:
    """Translate one legacy flat NJR snapshot without retaining runtime facts."""

    config = _mapping_or_empty(data.get("config"))
    stages = _legacy_stage_chain(data, config)
    stage_names = {stage.stage_type for stage in stages if stage.enabled}
    if stage_names & _TRAINING_STAGE_TYPES:
        workload_kind = WorkloadKind.TRAINING
    elif stage_names & _VIDEO_STAGE_TYPES:
        workload_kind = WorkloadKind.VIDEO
    else:
        workload_kind = WorkloadKind.IMAGE

    source_kind = _legacy_source_kind(data, stages)
    if workload_kind is WorkloadKind.TRAINING:
        source_kind = SourceKind.TRAINING
    elif workload_kind is WorkloadKind.VIDEO:
        source_kind = SourceKind.VIDEO_WORKFLOW

    source = SourceDescriptor(
        kind=source_kind,
        id=(
            str(data.get("prompt_pack_id") or "").strip() or None
            if source_kind is SourceKind.PROMPT_PACK
            else None
        ),
        revision=_optional_str(data.get("prompt_pack_version")),
        display_name=_optional_str(data.get("prompt_pack_name")),
        row_index=_optional_int(data.get("prompt_pack_row_index")),
        parent_job_id=_optional_str(
            _mapping_or_empty(data.get("extra_metadata")).get("parent_job_id")
        ),
        parent_artifact_id=_optional_str(
            _mapping_or_empty(data.get("extra_metadata")).get("parent_artifact_id")
        ),
        metadata={"migrated_from": "legacy_flat_njr"},
    )
    common: dict[str, Any] = {
        "positive_prompt": str(data.get("positive_prompt") or config.get("prompt") or ""),
        "negative_prompt": str(data.get("negative_prompt") or config.get("negative_prompt") or ""),
        "config": config,
        "input_image_paths": tuple(data.get("input_image_paths") or ()),
        "start_stage": _optional_str(data.get("start_stage")),
        "images_per_prompt": int(data.get("images_per_prompt") or 1),
        "loop_type": str(data.get("loop_type") or "pipeline"),
        "loop_count": int(data.get("loop_count") or 1),
        "variant_mode": str(data.get("variant_mode") or "standard"),
        "intent_config": _mapping_or_empty(data.get("intent_config")),
        "backend_options": _mapping_or_empty(data.get("backend_options")),
        "metadata": {},
    }
    if workload_kind is WorkloadKind.IMAGE:
        workload: Workload = ImageWorkloadSpec(**common)
    elif workload_kind is WorkloadKind.VIDEO:
        workload = VideoWorkloadSpec(
            **common,
            sequence_intent=(
                _mapping_or_empty(data.get("sequence_intent"))
                if data.get("sequence_intent") is not None
                else None
            ),
            continuity_link=(
                _mapping_or_empty(data.get("continuity_link"))
                if data.get("continuity_link") is not None
                else None
            ),
        )
    else:
        workload = TrainingWorkloadSpec(**common)

    return NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id=str(data.get("job_id") or "").strip(),
        workload_kind=workload_kind,
        source=source,
        workload=workload,
        stages=stages,
        output_plan=OutputPlan(
            base_output_dir=str(data.get("path_output_dir") or "output"),
            filename_template=str(data.get("filename_template") or "{seed}"),
            route=_optional_str(config.get("output_route")),
        ),
        provenance=NJRProvenance(
            seed=_optional_int(data.get("seed")),
            variant_index=int(data.get("variant_index") or 0),
            variant_total=int(data.get("variant_total") or 1),
            batch_index=int(data.get("batch_index") or 0),
            batch_total=int(data.get("batch_total") or 1),
            randomizer_summary=_mapping_or_empty(data.get("randomizer_summary")),
            matrix_slot_values=_mapping_or_empty(data.get("matrix_slot_values")),
            matrix_name=_optional_str(data.get("matrix_name")),
            matrix_mode=_optional_str(data.get("matrix_mode")),
            matrix_prompt_mode=_optional_str(data.get("matrix_prompt_mode")),
            config_variant_label=str(data.get("config_variant_label") or "base"),
            config_variant_index=int(data.get("config_variant_index") or 0),
            config_variant_overrides=_mapping_or_empty(data.get("config_variant_overrides")),
            positive_embeddings=tuple(data.get("positive_embeddings") or ()),
            negative_embeddings=tuple(data.get("negative_embeddings") or ()),
            lora_tags=tuple(
                LoRATag(name=str(item["name"]), weight=float(item["weight"]))
                for item in data.get("lora_tags") or ()
                if isinstance(item, Mapping)
            ),
            pack_usage=tuple(
                PackUsageInfo(
                    pack_name=str(item.get("pack_name") or ""),
                    pack_path=_optional_str(item.get("pack_path")),
                    prompt_index=_optional_int(item.get("prompt_index")),
                    used_for_stage=str(item.get("used_for_stage") or "txt2img"),
                )
                for item in data.get("pack_usage") or ()
                if isinstance(item, Mapping)
            ),
            txt2img_prompt_info=_prompt_info_from_value(data.get("txt2img_prompt_info")),
            img2img_prompt_info=_prompt_info_from_value(data.get("img2img_prompt_info")),
            aesthetic_enabled=bool(data.get("aesthetic_enabled", False)),
            aesthetic_weight=_optional_float(data.get("aesthetic_weight")),
            aesthetic_text=_optional_str(data.get("aesthetic_text")),
            aesthetic_embedding=_optional_str(data.get("aesthetic_embedding")),
            metadata={
                **dict(_mapping_or_empty(data.get("extra_metadata"))),
                "migrated_from": "legacy_flat_njr",
            },
        ),
    )


def read_njr(data: Mapping[str, Any]) -> NormalizedJobRecord:
    """Read a current NJR or explicitly migrate a legacy flat snapshot."""

    canonical_keys = {
        "schema_version",
        "job_id",
        "workload_kind",
        "source",
        "workload",
        "stages",
        "output_plan",
        "provenance",
    }
    if set(data) == canonical_keys:
        return NormalizedJobRecord.from_dict(data)
    return migrate_legacy_njr(data)


__all__ = [
    "CURRENT_NJR_SCHEMA_VERSION",
    "FrozenJsonMap",
    "ImageWorkloadSpec",
    "LearningJobContext",
    "LoRATag",
    "NJRProvenance",
    "NormalizedJobRecord",
    "OutputPlan",
    "PackUsageInfo",
    "SourceDescriptor",
    "SourceKind",
    "StageConfig",
    "StagePromptInfo",
    "TrainingWorkloadSpec",
    "VideoWorkloadSpec",
    "WorkloadKind",
    "freeze_json",
    "migrate_legacy_njr",
    "read_njr",
    "thaw_json",
]
