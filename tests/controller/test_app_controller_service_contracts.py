"""Contract tests for app_controller_services seams.

These tests lock the behavior of extracted service modules so that further
decomposition of AppController does not inadvertently change semantics.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call
import pytest

from src.controller.app_controller_services.learning_completion_router import (
    route_job_completion_to_learning,
    build_learning_completion_handler,
)


class TestRoutJobCompletionToLearning:
    """route_job_completion_to_learning contract."""

    def test_no_op_when_main_window_is_none(self):
        """Must not raise when main_window is None."""
        route_job_completion_to_learning(None, object(), {})

    def test_no_op_when_learning_tab_missing(self):
        """Must not raise when main_window has no learning_tab."""
        mw = MagicMock(spec=[])  # no attributes
        route_job_completion_to_learning(mw, object(), {})

    def test_no_op_when_controller_missing(self):
        """Must not raise when learning_tab has no controller attribute."""
        tab = MagicMock(spec=[])
        mw = MagicMock(learning_tab=tab)
        route_job_completion_to_learning(mw, object(), {})

    def test_calls_on_job_completed_callback(self):
        """Must call on_job_completed_callback(job, result) when present."""
        job = MagicMock()
        result = {"status": "ok"}
        callback = MagicMock()
        controller = MagicMock(on_job_completed_callback=callback)
        tab = MagicMock(learning_controller=controller)
        mw = MagicMock(learning_tab=tab)

        route_job_completion_to_learning(mw, job, result)

        callback.assert_called_once_with(job, result)

    def test_falls_back_to_controller_attribute(self):
        """Must fall back to .controller when .learning_controller is absent."""
        job = MagicMock()
        result = {"status": "ok"}
        callback = MagicMock()
        controller = MagicMock(on_job_completed_callback=callback)
        # learning_controller is intentionally absent
        tab = MagicMock(spec=["controller"])
        tab.controller = controller
        mw = MagicMock(learning_tab=tab)

        route_job_completion_to_learning(mw, job, result)

        callback.assert_called_once_with(job, result)

    def test_no_op_when_callback_not_callable(self):
        """Must not raise when on_job_completed_callback exists but is not callable."""
        controller = MagicMock(on_job_completed_callback="not-callable")
        tab = MagicMock(learning_controller=controller)
        mw = MagicMock(learning_tab=tab)
        route_job_completion_to_learning(mw, object(), {})

    def test_swallows_callback_exception(self):
        """Exceptions inside the callback must be caught, not propagated."""
        def bad_callback(job, result):
            raise RuntimeError("boom")

        controller = MagicMock(on_job_completed_callback=bad_callback)
        tab = MagicMock(learning_controller=controller)
        mw = MagicMock(learning_tab=tab)
        # Should not raise
        route_job_completion_to_learning(mw, object(), {})


class TestBuildLearningCompletionHandler:
    """build_learning_completion_handler contract."""

    def test_returns_callable(self):
        handler = build_learning_completion_handler(lambda: None)
        assert callable(handler)

    def test_handler_calls_get_main_window_on_each_call(self):
        """get_main_window must be called fresh for every handler invocation."""
        calls = []
        mw = MagicMock(spec=[])  # no learning_tab → no-op delivery

        def get_mw():
            calls.append(1)
            return mw

        handler = build_learning_completion_handler(get_mw)
        handler(object(), {})
        handler(object(), {})
        assert len(calls) == 2

    def test_handler_delivers_to_callback(self):
        """Handler built from a live window must deliver job+result."""
        callback = MagicMock()
        controller = MagicMock(on_job_completed_callback=callback)
        tab = MagicMock(learning_controller=controller)
        mw = MagicMock(learning_tab=tab)

        handler = build_learning_completion_handler(lambda: mw)
        job = MagicMock()
        result = {"x": 1}
        handler(job, result)

        callback.assert_called_once_with(job, result)
