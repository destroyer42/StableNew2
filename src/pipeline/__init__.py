"""Pipeline module."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "Pipeline",
    "PipelineRunner",
    "PipelineRunResult",
    "StageConfig",
    "StageExecution",
    "StageExecutionPlan",
    "StageTypeEnum",
    "VideoCreator",
    "build_stage_execution_plan",
]

_EXPORT_MAP = {
    "Pipeline": ("src.pipeline.executor", "Pipeline"),
    "PipelineRunner": ("src.pipeline.pipeline_runner", "PipelineRunner"),
    "PipelineRunResult": ("src.pipeline.pipeline_runner", "PipelineRunResult"),
    "StageConfig": ("src.pipeline.stage_sequencer", "StageConfig"),
    "StageExecution": ("src.pipeline.stage_sequencer", "StageExecution"),
    "StageExecutionPlan": ("src.pipeline.stage_sequencer", "StageExecutionPlan"),
    "StageTypeEnum": ("src.pipeline.stage_sequencer", "StageTypeEnum"),
    "VideoCreator": ("src.pipeline.video", "VideoCreator"),
    "build_stage_execution_plan": ("src.pipeline.stage_sequencer", "build_stage_execution_plan"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module 'src.pipeline' has no attribute '{name}'")
    module_name, attr_name = _EXPORT_MAP[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
