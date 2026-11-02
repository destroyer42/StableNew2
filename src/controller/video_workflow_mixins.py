"""The controller surfaces ``VideoWorkflowController`` is composed of (kept apart so the controller module stays small)."""

from __future__ import annotations

from src.controller.video_eval_controller import VideoEvalControllerMixin
from src.controller.video_motion_conversion_controller import VideoMotionConversionControllerMixin
from src.controller.video_motion_library_controller import VideoMotionLibraryControllerMixin
from src.controller.video_preflight_controller import VideoPreflightControllerMixin
from src.controller.video_recent_outputs_controller import VideoRecentOutputsControllerMixin
from src.controller.video_sequence_controller import VideoSequenceControllerMixin


class VideoWorkflowMixins(
    VideoEvalControllerMixin,
    VideoMotionConversionControllerMixin,
    VideoMotionLibraryControllerMixin,
    VideoPreflightControllerMixin,
    VideoRecentOutputsControllerMixin,
    VideoSequenceControllerMixin,
):
    """Experiment review, readiness, the Motion Library, recent outputs and multi-segment sequences on one controller."""


__all__ = ["VideoWorkflowMixins"]
