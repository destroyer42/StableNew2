from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict

from src.config.prompting_defaults import DEFAULT_PROMPT_OPTIMIZER_SETTINGS
from src.prompting.prompt_optimizer_errors import PromptConfigError


@dataclass(slots=True)
class PromptOptimizerConfig:
    enabled: bool = True
    optimize_positive: bool = True
    optimize_negative: bool = True
    dedupe_enabled: bool = True
    preserve_lora_relative_order: bool = True
    preserve_unknown_order: bool = True
    log_before_after: bool = True
    log_bucket_assignments: bool = False
    warn_on_large_chunk_count: bool = True
    large_chunk_warning_threshold: int = 18
    enable_score_based_classification: bool = False
    allow_subject_anchor_boost: bool = False
    subject_anchor_boost_min_chunk_count: int = 8
    opt_out_pipeline_names: list[str] | None = None

    def validate(self) -> None:
        if self.large_chunk_warning_threshold < 1:
            raise PromptConfigError("large_chunk_warning_threshold must be >= 1")
        if self.subject_anchor_boost_min_chunk_count < 1:
            raise PromptConfigError("subject_anchor_boost_min_chunk_count must be >= 1")
        if self.opt_out_pipeline_names is None:
            return
        if not isinstance(self.opt_out_pipeline_names, list):
            raise PromptConfigError("opt_out_pipeline_names must be a list of strings")
        if any(not isinstance(item, str) for item in self.opt_out_pipeline_names):
            raise PromptConfigError("opt_out_pipeline_names must only contain strings")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["opt_out_pipeline_names"] = list(self.opt_out_pipeline_names or [])
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "PromptOptimizerConfig":
        data = dict(DEFAULT_PROMPT_OPTIMIZER_SETTINGS)
        for key, value in dict(payload or {}).items():
            if key in data:
                data[key] = value
        config = cls(**data)
        config.validate()
        return config
