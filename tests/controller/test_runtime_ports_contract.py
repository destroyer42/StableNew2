"""Contract tests for runtime_ports Protocol definitions.

Verifies that the Protocol classes are correctly defined and that objects
satisfying the protocols pass isinstance checks, while objects missing the
required methods do not.
"""

from __future__ import annotations

import pytest

from src.controller.ports.runtime_ports import (
    ImageRuntimePorts,
    NJRSummaryPort,
    NJRUISummaryPort,
    JobCompletionCallbackPort,
    WorkflowRegistryPort,
)


class _FullNJR:
    """Satisfies both NJRSummaryPort and NJRUISummaryPort."""

    def to_unified_summary(self):
        return {"type": "unified"}

    def to_ui_summary(self):
        return {"type": "ui"}


class _SummaryOnly:
    """Satisfies only NJRSummaryPort."""

    def to_unified_summary(self):
        return {"type": "unified"}


class _UIOnly:
    """Satisfies only NJRUISummaryPort."""

    def to_ui_summary(self):
        return {"type": "ui"}


class _NoSummary:
    """Satisfies neither summary port."""
    pass


class _Controller:
    """Satisfies JobCompletionCallbackPort."""

    def on_job_completed_callback(self, job, result):
        pass


class _NotAController:
    """Does not satisfy JobCompletionCallbackPort."""
    pass


class _RuntimePorts:
    def create_client(self, *, base_url: str):
        return {"base_url": base_url}

    def create_runner(self, *, api_client, structured_logger, status_callback=None):
        return {
            "client": api_client,
            "logger": structured_logger,
            "status_callback": status_callback,
        }


class _WorkflowRegistry:
    def list_specs_for_backend(self, backend_id: str):
        return [{"backend_id": backend_id}]

    def get(self, workflow_id: str, workflow_version: str | None = None):
        return {"workflow_id": workflow_id, "workflow_version": workflow_version}


class TestNJRSummaryPort:
    def test_full_njr_satisfies(self):
        assert isinstance(_FullNJR(), NJRSummaryPort)

    def test_summary_only_satisfies(self):
        assert isinstance(_SummaryOnly(), NJRSummaryPort)

    def test_ui_only_does_not_satisfy(self):
        assert not isinstance(_UIOnly(), NJRSummaryPort)

    def test_no_summary_does_not_satisfy(self):
        assert not isinstance(_NoSummary(), NJRSummaryPort)


class TestNJRUISummaryPort:
    def test_full_njr_satisfies(self):
        assert isinstance(_FullNJR(), NJRUISummaryPort)

    def test_ui_only_satisfies(self):
        assert isinstance(_UIOnly(), NJRUISummaryPort)

    def test_summary_only_does_not_satisfy(self):
        assert not isinstance(_SummaryOnly(), NJRUISummaryPort)

    def test_no_summary_does_not_satisfy(self):
        assert not isinstance(_NoSummary(), NJRUISummaryPort)


class TestJobCompletionCallbackPort:
    def test_controller_satisfies(self):
        assert isinstance(_Controller(), JobCompletionCallbackPort)

    def test_non_controller_does_not_satisfy(self):
        assert not isinstance(_NotAController(), JobCompletionCallbackPort)

    def test_lambda_does_not_satisfy(self):
        # A bare lambda has no on_job_completed_callback attribute.
        f = lambda job, result: None
        assert not isinstance(f, JobCompletionCallbackPort)


class TestImageRuntimePorts:
    def test_runtime_port_bundle_satisfies(self):
        assert isinstance(_RuntimePorts(), ImageRuntimePorts)

    def test_missing_runtime_port_methods_do_not_satisfy(self):
        assert not isinstance(_NoSummary(), ImageRuntimePorts)


class TestWorkflowRegistryPort:
    def test_workflow_registry_port_satisfies(self):
        assert isinstance(_WorkflowRegistry(), WorkflowRegistryPort)

    def test_non_registry_object_does_not_satisfy(self):
        assert not isinstance(_NoSummary(), WorkflowRegistryPort)
