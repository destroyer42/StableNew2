"""Controller-owned runtime state primitives.

This module owns the shared lifecycle, cancellation, and lightweight pipeline
state objects used by controller and pipeline runtime code. These primitives are
not GUI-owned, even when GUI surfaces consume them.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

logger = logging.getLogger(__name__)


class GUIState(Enum):
    """Application lifecycle states shared by controller and GUI surfaces."""

    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


class CancellationError(Exception):
    """Raised when operation is cancelled by user."""


class CancelToken:
    """Thread-safe cancellation token for cooperative cancellation."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled.set()
            logger.info("Cancellation requested")

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise CancellationError("Operation cancelled by user")

    def reset(self) -> None:
        with self._lock:
            self._cancelled.clear()


class StateManager:
    """Manages application state transitions with callbacks."""

    def __init__(self, initial_state: GUIState = GUIState.IDLE):
        self._state = initial_state
        self._lock = threading.Lock()
        self._callbacks: dict[GUIState, list[Callable[[], None]]] = {
            state: [] for state in GUIState
        }
        self._transition_callbacks: list[Callable[[GUIState, GUIState], None]] = []
        self.pipeline_overrides: dict[str, object] = {}

    @property
    def current(self) -> GUIState:
        with self._lock:
            return self._state

    @property
    def state(self) -> GUIState:
        return self.current

    def is_state(self, state: GUIState) -> bool:
        with self._lock:
            return self._state == state

    def can_run(self) -> bool:
        with self._lock:
            return self._state in (GUIState.IDLE, GUIState.ERROR)

    def can_stop(self) -> bool:
        with self._lock:
            return self._state == GUIState.RUNNING

    def transition_to(self, new_state: GUIState) -> bool:
        with self._lock:
            old_state = self._state
            valid = self._is_valid_transition(old_state, new_state)
            if not valid:
                logger.warning("Invalid state transition: %s -> %s", old_state.name, new_state.name)
                return False
            self._state = new_state
            logger.info("State transition: %s -> %s", old_state.name, new_state.name)

        self._notify_transition(old_state, new_state)
        self._notify_state_callbacks(new_state)
        return True

    def _is_valid_transition(self, from_state: GUIState, to_state: GUIState) -> bool:
        valid_transitions = {
            GUIState.IDLE: {GUIState.RUNNING, GUIState.ERROR},
            GUIState.RUNNING: {GUIState.STOPPING, GUIState.IDLE, GUIState.ERROR},
            GUIState.STOPPING: {GUIState.IDLE, GUIState.ERROR},
            GUIState.ERROR: {GUIState.IDLE},
        }
        return to_state in valid_transitions.get(from_state, set())

    def on_state(self, state: GUIState, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks[state].append(callback)

    def on_transition(self, callback: Callable[[GUIState, GUIState], None]) -> None:
        with self._lock:
            self._transition_callbacks.append(callback)

    def _notify_state_callbacks(self, state: GUIState) -> None:
        with self._lock:
            callbacks = self._callbacks[state].copy()
        for callback in callbacks:
            try:
                callback()
            except Exception as exc:
                logger.error("Error in state callback: %s", exc)

    def _notify_transition(self, old_state: GUIState, new_state: GUIState) -> None:
        with self._lock:
            callbacks = self._transition_callbacks.copy()
        for callback in callbacks:
            try:
                callback(old_state, new_state)
            except Exception as exc:
                logger.error("Error in transition callback: %s", exc)

    def reset(self) -> None:
        self.transition_to(GUIState.IDLE)

    def get_pipeline_overrides(self) -> dict[str, object]:
        return dict(self.pipeline_overrides or {})


@dataclass
class LoraRuntimeSettings:
    """Runtime settings for a single LoRA."""

    enabled: bool = True
    strength: float = 1.0


@dataclass
class PipelineState:
    """Lightweight in-memory pipeline configuration."""

    run_mode: str = "queue"
    run_scope: str = "full"
    batch_runs: int = 1
    stage_txt2img_enabled: bool = True
    stage_img2img_enabled: bool = False
    stage_adetailer_enabled: bool = False
    stage_upscale_enabled: bool = False
    pending_jobs: int = 0
    randomizer_mode: str = "off"
    max_variants: int = 1
    lora_settings: dict[str, LoraRuntimeSettings] = field(default_factory=dict)

    def set_lora_setting(self, name: str, enabled: bool, strength: float) -> None:
        self.lora_settings[name] = LoraRuntimeSettings(enabled=enabled, strength=strength)

    def get_lora_setting(self, name: str) -> LoraRuntimeSettings:
        return self.lora_settings.get(name, LoraRuntimeSettings())
