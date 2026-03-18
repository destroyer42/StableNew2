"""Video utilities package for StableNew v2.6."""

from src.video.animatediff_backend import AnimateDiffVideoBackend
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

__all__ = [
    "AnimateDiffVideoBackend",
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
    "build_default_video_backend_registry",
]
