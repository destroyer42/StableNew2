"""Calls the Convert Motion dialog needs, supplied by the controller (PR-VID-MOTION-354).

Plain callables over video-domain types, so both the toolkit-neutral session and the controller can name them without the
controller importing the GUI.  Every call is worker-safe and cancellable; none queues or builds a job.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.blender import BlenderInstall
from src.video.motion_conversion.conditioning_preview import ConditioningPreview
from src.video.motion_conversion.conversion_service import ConversionResult
from src.video.motion_conversion.workbench import SourceFacts
from src.video.motion_library.importer import ImportOutcome


@dataclass(frozen=True)
class WorkflowChoice:
    """The workflow whose rules the clip must satisfy (``spec`` is ``None`` when none is selected)."""

    workflow_id: str = ""
    workflow_version: str = ""
    display_name: str = ""
    spec: Any = None
    default_frames: int = 17
    legal_frames: tuple[int, ...] = ()


@dataclass(frozen=True)
class ConversionPorts:
    """Worker-safe calls the controller supplies."""

    remembered_blender: Callable[[threading.Event], BlenderInstall | None]
    select_blender: Callable[[str, threading.Event], BlenderInstall]
    describe: Callable[[str, threading.Event], SourceFacts]
    probe: Callable[[SourceFacts, threading.Event], cp.AnimationProbe]
    convert: Callable[[cp.ConversionPlan, bool, threading.Event], ConversionResult]
    accept: Callable[[str, str, tuple[str, ...], str, threading.Event], ImportOutcome]
    conditioning: Callable[[str, str, str, tuple[int, int], threading.Event], ConditioningPreview]
    workflow: Callable[[], WorkflowChoice]
    check_character: Callable[[SourceFacts, str], tuple[SourceFacts, Any]]
    #: Pure and fast (no disk, no process): freeze the plan or raise ``ConversionPlanError``.
    build_plan: Callable[
        [SourceFacts, cp.AnimationProbe, WorkflowChoice, Mapping[str, Any], Any], cp.ConversionPlan
    ]
