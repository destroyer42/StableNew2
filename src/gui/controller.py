"""GUI compatibility export for the controller-owned base pipeline controller."""

from src.controller.core_pipeline_controller import CorePipelineController, LogMessage

PipelineController = CorePipelineController

__all__ = ["PipelineController", "LogMessage"]
