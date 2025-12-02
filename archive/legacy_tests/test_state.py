"""Tests for GUI state management."""

import threading
import time

import pytest

from src.gui.state import (
    CancellationError,
    CancelToken,
    GUIState,
    StateManager,
)


class TestCancelToken:
    """Tests for CancelToken."""

    def test_initial_state(self):
        """Test initial state is not cancelled."""
        token = CancelToken()
        assert not token.is_cancelled()

    def test_cancel(self):
        """Test cancellation."""
        token = CancelToken()
        token.cancel()
        assert token.is_cancelled()

    def test_check_cancelled_raises(self):
        """Test check_cancelled raises when cancelled."""
        token = CancelToken()
        token.cancel()
        with pytest.raises(CancellationError):
            token.check_cancelled()

    def test_check_cancelled_ok(self):
        """Test check_cancelled passes when not cancelled."""
        token = CancelToken()
        token.check_cancelled()  # Should not raise

    def test_reset(self):
        """Test reset clears cancellation."""
        token = CancelToken()
        token.cancel()
        assert token.is_cancelled()
        token.reset()
        assert not token.is_cancelled()

    def test_thread_safety(self):
        """Test thread-safe cancellation."""
        token = CancelToken()
        results = []

        def worker():
            try:
                for i in range(100):
                    token.check_cancelled()
                    time.sleep(0.001)
                results.append("completed")
            except CancellationError:
                results.append("cancelled")

        thread = threading.Thread(target=worker)
        thread.start()

        time.sleep(0.05)  # Let it run a bit
        token.cancel()
        thread.join(timeout=1.0)

        assert "cancelled" in results


class TestStateManager:
    """Tests for StateManager."""

    def test_initial_state(self):
        """Test initial state is IDLE."""
        manager = StateManager()
        assert manager.current == GUIState.IDLE
        assert manager.is_state(GUIState.IDLE)

    def test_valid_transitions(self):
        """Test valid state transitions."""
        manager = StateManager()

        # IDLE -> RUNNING
        assert manager.transition_to(GUIState.RUNNING)
        assert manager.current == GUIState.RUNNING

        # RUNNING -> STOPPING
        assert manager.transition_to(GUIState.STOPPING)
        assert manager.current == GUIState.STOPPING

        # STOPPING -> IDLE
        assert manager.transition_to(GUIState.IDLE)
        assert manager.current == GUIState.IDLE

    def test_invalid_transitions(self):
        """Test invalid state transitions are rejected."""
        manager = StateManager()

        # Can't go from IDLE to STOPPING
        assert not manager.transition_to(GUIState.STOPPING)
        assert manager.current == GUIState.IDLE

        # Transition to RUNNING first
        manager.transition_to(GUIState.RUNNING)

        # Can't go from RUNNING to IDLE directly through STOPPING path
        # (actually RUNNING -> IDLE is valid for completion)
        assert manager.transition_to(GUIState.IDLE)

    def test_error_state_transitions(self):
        """Test error state transitions."""
        manager = StateManager()

        # IDLE -> RUNNING -> ERROR
        manager.transition_to(GUIState.RUNNING)
        assert manager.transition_to(GUIState.ERROR)
        assert manager.current == GUIState.ERROR

        # ERROR -> IDLE
        assert manager.transition_to(GUIState.IDLE)
        assert manager.current == GUIState.IDLE

    def test_can_run(self):
        """Test can_run checks."""
        manager = StateManager()

        assert manager.can_run()  # IDLE

        manager.transition_to(GUIState.RUNNING)
        assert not manager.can_run()  # RUNNING

        manager.transition_to(GUIState.ERROR)
        assert manager.can_run()  # ERROR

    def test_can_stop(self):
        """Test can_stop checks."""
        manager = StateManager()

        assert not manager.can_stop()  # IDLE

        manager.transition_to(GUIState.RUNNING)
        assert manager.can_stop()  # RUNNING

        manager.transition_to(GUIState.STOPPING)
        assert not manager.can_stop()  # STOPPING

    def test_state_callbacks(self):
        """Test callbacks on state entry."""
        manager = StateManager()
        called = []

        manager.on_state(GUIState.RUNNING, lambda: called.append("running"))
        manager.on_state(GUIState.IDLE, lambda: called.append("idle"))

        manager.transition_to(GUIState.RUNNING)
        assert "running" in called

        manager.transition_to(GUIState.STOPPING)
        manager.transition_to(GUIState.IDLE)
        assert "idle" in called

    def test_transition_callbacks(self):
        """Test callbacks on any transition."""
        manager = StateManager()
        transitions = []

        def record_transition(old, new):
            transitions.append((old.name, new.name))

        manager.on_transition(record_transition)

        manager.transition_to(GUIState.RUNNING)
        assert ("IDLE", "RUNNING") in transitions

        manager.transition_to(GUIState.STOPPING)
        assert ("RUNNING", "STOPPING") in transitions

    def test_reset(self):
        """Test reset to IDLE."""
        manager = StateManager()

        manager.transition_to(GUIState.RUNNING)
        manager.reset()
        assert manager.current == GUIState.IDLE

    def test_thread_safety(self):
        """Test thread-safe state transitions."""
        manager = StateManager()
        results = []

        def worker():
            for _ in range(10):
                if manager.transition_to(GUIState.RUNNING):
                    results.append("running")
                    time.sleep(0.001)
                    manager.transition_to(GUIState.IDLE)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        # Should have some successful transitions
        assert len(results) > 0
