"""Video utilities package for StableNew v2.6."""

from src.video.animatediff_backend import AnimateDiffVideoBackend
from src.video.comfy_api_client import ComfyApiClient
from src.video.comfy_dependency_probe import ComfyDependencyProbe, DependencyProbeResult
from src.video.comfy_healthcheck import ComfyHealthCheckTimeout, validate_comfy_health, wait_for_comfy_ready
from src.video.comfy_process_manager import (
    ComfyProcessConfig,
    ComfyProcessManager,
    ComfyStartupError,
    build_default_comfy_process_config,
    clear_global_comfy_process_manager,
    get_global_comfy_process_manager,
)
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.svd_config import SVDConfig, SVDInferenceConfig, SVDOutputConfig, SVDPreprocessConfig
from src.video.svd_native_backend import SVDNativeVideoBackend
from src.video.svd_runner import SVDRunner
from src.video.svd_service import SVDService
from src.video.video_backend_registry import VideoBackendRegistry, build_default_video_backend_registry
from src.video.video_backend_types import (
    VideoBackendCapabilities,
    VideoBackendInterface,
    VideoExecutionRequest,
    VideoExecutionResult,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_contracts import (
    CompiledWorkflowRequest,
    WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
    WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,
    WORKFLOW_CAP_SEGMENT_STITCHABLE,
    WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry

__all__ = [
    "AnimateDiffVideoBackend",
    "ComfyApiClient",
    "ComfyDependencyProbe",
    "ComfyHealthCheckTimeout",
    "ComfyProcessConfig",
    "ComfyProcessManager",
    "ComfyStartupError",
    "ComfyWorkflowVideoBackend",
    "CompiledWorkflowRequest",
    "DependencyProbeResult",
    "SVDConfig",
    "SVDInferenceConfig",
    "SVDNativeVideoBackend",
    "SVDOutputConfig",
    "SVDPreprocessConfig",
    "SVDRunner",
    "SVDService",
    "VideoBackendCapabilities",
    "VideoBackendInterface",
    "VideoBackendRegistry",
    "VideoExecutionRequest",
    "VideoExecutionResult",
    "WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED",
    "WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO",
    "WORKFLOW_CAP_SEGMENT_STITCHABLE",
    "WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO",
    "WorkflowCompiler",
    "WorkflowDependencySpec",
    "WorkflowInputBinding",
    "WorkflowOutputBinding",
    "WorkflowRegistry",
    "WorkflowSpec",
    "build_default_comfy_process_config",
    "build_default_video_backend_registry",
    "build_default_workflow_registry",
    "clear_global_comfy_process_manager",
    "get_global_comfy_process_manager",
    "validate_comfy_health",
    "wait_for_comfy_ready",
]
