"""GUI state management with state machine pattern."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

logger = logging.getLogger(__name__)


class GUIState(Enum):
    """GUI application states."""

    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


class CancellationError(Exception):
    """Raised when operation is cancelled by user."""

    pass


class CancelToken:
    """Thread-safe cancellation token for cooperative cancellation."""

    def __init__(self) -> None:
        """Initialize cancel token."""
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Request cancellation."""
        with self._lock:
            self._cancelled.set()
            logger.info("Cancellation requested")

    def is_cancelled(self) -> bool:
        """Check if cancellation was requested.

        Returns:
            True if cancelled, False otherwise
        """
        return self._cancelled.is_set()

    def check_cancelled(self) -> None:
        """Check if cancelled and raise exception if so.

        Raises:
            CancellationError: If cancellation was requested
        """
        if self._cancelled.is_set():
            raise CancellationError("Operation cancelled by user")

    def reset(self) -> None:
        """Reset the cancellation token for reuse."""
        with self._lock:
            self._cancelled.clear()


class StateManager:
    """Manages application state transitions with callbacks."""

    def __init__(self, initial_state: GUIState = GUIState.IDLE):
        """Initialize state manager."""
        self._state = initial_state
        self._lock = threading.Lock()
        self._callbacks: dict[GUIState, list[Callable[[], None]]] = {
            state: [] for state in GUIState
        }
        self._transition_callbacks: list[Callable[[GUIState, GUIState], None]] = []
        self.pipeline_overrides: dict[str, object] = {}

    @property
    def current(self) -> GUIState:
        """Get current state.

        Returns:
            Current GUI state
        """
        with self._lock:
            return self._state

    @property
    def state(self) -> GUIState:
        """Backward-compatible alias for tests expecting `.state`."""
        return self.current

    def is_state(self, state: GUIState) -> bool:
        """Check if in specific state.

        Args:
            state: State to check

        Returns:
            True if in that state, False otherwise
        """
        with self._lock:
            return self._state == state

    def can_run(self) -> bool:
        """Check if pipeline can be started.

        Returns:
            True if in IDLE or ERROR state
        """
        with self._lock:
            return self._state in (GUIState.IDLE, GUIState.ERROR)

    def can_stop(self) -> bool:
        """Check if pipeline can be stopped.

        Returns:
            True if in RUNNING state
        """
        with self._lock:
            return self._state == GUIState.RUNNING

    def transition_to(self, new_state: GUIState) -> bool:
        """Transition to new state if valid.

        Args:
            new_state: Target state

        Returns:
            True if transition successful, False if invalid
        """
        with self._lock:
            old_state = self._state

            # Validate transitions
            valid = self._is_valid_transition(old_state, new_state)
            if not valid:
                logger.warning(f"Invalid state transition: {old_state.name} -> {new_state.name}")
                return False

            self._state = new_state
            logger.info(f"State transition: {old_state.name} -> {new_state.name}")

        # Call callbacks outside lock to avoid deadlock
        self._notify_transition(old_state, new_state)
        self._notify_state_callbacks(new_state)

        return True

    def _is_valid_transition(self, from_state: GUIState, to_state: GUIState) -> bool:
        """Check if state transition is valid.

        Args:
            from_state: Current state
            to_state: Target state

        Returns:
            True if transition is allowed
        """
        valid_transitions = {
            GUIState.IDLE: {GUIState.RUNNING, GUIState.ERROR},
            GUIState.RUNNING: {GUIState.STOPPING, GUIState.IDLE, GUIState.ERROR},
            GUIState.STOPPING: {GUIState.IDLE, GUIState.ERROR},
            GUIState.ERROR: {GUIState.IDLE},
        }

        return to_state in valid_transitions.get(from_state, set())

    def on_state(self, state: GUIState, callback: Callable[[], None]) -> None:
        """Register callback for when entering specific state.

        Args:
            state: State to watch
            callback: Function to call when entering state
        """
        with self._lock:
            self._callbacks[state].append(callback)

    def on_transition(self, callback: Callable[[GUIState, GUIState], None]) -> None:
        """Register callback for any state transition.

        Args:
            callback: Function to call with (old_state, new_state)
        """
        with self._lock:
            self._transition_callbacks.append(callback)

    def _notify_state_callbacks(self, state: GUIState) -> None:
        """Notify callbacks registered for specific state.

        Args:
            state: State that was entered
        """
        callbacks = []
        with self._lock:
            callbacks = self._callbacks[state].copy()

        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in state callback: {e}")

    def _notify_transition(self, old_state: GUIState, new_state: GUIState) -> None:
        """Notify callbacks registered for transitions.

        Args:
            old_state: Previous state
            new_state: New state
        """
        callbacks = []
        with self._lock:
            callbacks = self._transition_callbacks.copy()

        for callback in callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.error(f"Error in transition callback: {e}")

    def reset(self) -> None:
        """Reset to IDLE state."""
        self.transition_to(GUIState.IDLE)

    # ------------------------------------------------------------------
    # Pipeline overrides (GUI -> controller bridge)
    # ------------------------------------------------------------------
    def get_pipeline_overrides(self) -> dict[str, object]:
        """Return the current pipeline override dict (used by PipelineController)."""
        return dict(self.pipeline_overrides or {})


@dataclass
class LoraRuntimeSettings:
    """Runtime settings for a single LoRA."""

    enabled: bool = True
    strength: float = 1.0


@dataclass
class PipelineState:
    """Lightweight in-memory pipeline configuration."""

    run_mode: str = "direct"  # or "queue"
    run_scope: str = "full"  # selected | from_selected | full
    batch_runs: int = 1
    stage_txt2img_enabled: bool = True
    stage_img2img_enabled: bool = False
    stage_adetailer_enabled: bool = False
    stage_upscale_enabled: bool = False
    pending_jobs: int = 0
    randomizer_mode: str = "off"  # off | sequential | rotate | random
    max_variants: int = 1
    lora_settings: dict[str, LoraRuntimeSettings] = field(default_factory=dict)

    def set_lora_setting(self, name: str, enabled: bool, strength: float) -> None:
        """Set LoRA runtime settings for a specific LoRA."""
        self.lora_settings[name] = LoraRuntimeSettings(enabled=enabled, strength=strength)

    def get_lora_setting(self, name: str) -> LoraRuntimeSettings:
        """Get LoRA runtime settings for a specific LoRA."""
        return self.lora_settings.get(name, LoraRuntimeSettings())

    def reset_lora_settings(self) -> None:
        """Reset all LoRA settings to defaults."""
        self.lora_settings.clear()
