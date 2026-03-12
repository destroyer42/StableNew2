"""Contract tests for learning_controller_services seams.

These tests lock the behavior of extracted service modules so that further
decomposition of LearningController does not inadvertently change semantics.
"""

from __future__ import annotations

import pytest

from src.learning.learning_controller_services.experiment_persistence import (
    RESUME_SCHEMA_VERSION,
    build_resume_payload,
    validate_resume_payload,
    extract_workflow_state,
)


class TestBuildResumePayload:
    """build_resume_payload contract."""

    def _base_state(self) -> dict:
        return {"current_experiment": None, "plan": [], "selected_variant": None}

    def test_includes_all_required_keys(self):
        payload = build_resume_payload(
            state_dict=self._base_state(),
            workflow_state="running",
            learning_enabled=True,
        )
        assert "workflow_state" in payload
        assert "learning_enabled" in payload
        assert "resume_schema_version" in payload
        assert "saved_at" in payload

    def test_workflow_state_preserved(self):
        payload = build_resume_payload(
            state_dict=self._base_state(),
            workflow_state="review",
            learning_enabled=False,
        )
        assert payload["workflow_state"] == "review"

    def test_learning_enabled_coerced_to_bool(self):
        payload = build_resume_payload(
            state_dict=self._base_state(),
            workflow_state="",
            learning_enabled=1,
        )
        assert payload["learning_enabled"] is True

        payload2 = build_resume_payload(
            state_dict=self._base_state(),
            workflow_state="",
            learning_enabled=0,
        )
        assert payload2["learning_enabled"] is False

    def test_schema_version_is_canonical_constant(self):
        payload = build_resume_payload(
            state_dict=self._base_state(),
            workflow_state="",
            learning_enabled=False,
        )
        assert payload["resume_schema_version"] == RESUME_SCHEMA_VERSION

    def test_state_dict_keys_are_preserved(self):
        state = {"current_experiment": "exp-1", "plan": [1, 2, 3], "extra": "x"}
        payload = build_resume_payload(
            state_dict=state,
            workflow_state="",
            learning_enabled=False,
        )
        assert payload["current_experiment"] == "exp-1"
        assert payload["plan"] == [1, 2, 3]
        assert payload["extra"] == "x"

    def test_does_not_mutate_input_state_dict(self):
        state = {"key": "value"}
        original = dict(state)
        build_resume_payload(state_dict=state, workflow_state="x", learning_enabled=True)
        assert state == original


class TestValidateResumePayload:
    """validate_resume_payload contract."""

    def test_returns_false_for_none(self):
        assert validate_resume_payload(None) is False

    def test_returns_false_for_empty_dict(self):
        assert validate_resume_payload({}) is False

    def test_returns_false_for_non_dict(self):
        for v in [42, "string", [], True]:
            assert validate_resume_payload(v) is False

    def test_returns_true_for_non_empty_dict(self):
        assert validate_resume_payload({"a": 1}) is True

    def test_returns_true_for_complete_payload(self):
        payload = build_resume_payload(
            state_dict={"plan": []},
            workflow_state="running",
            learning_enabled=True,
        )
        assert validate_resume_payload(payload) is True


class TestExtractWorkflowState:
    """extract_workflow_state contract."""

    def test_returns_lowercase_trimmed_string(self):
        assert extract_workflow_state({"workflow_state": "  Running  "}) == "running"

    def test_returns_empty_string_when_key_missing(self):
        assert extract_workflow_state({}) == ""

    def test_returns_empty_string_when_value_is_none(self):
        assert extract_workflow_state({"workflow_state": None}) == ""

    def test_returns_empty_string_when_value_is_empty(self):
        assert extract_workflow_state({"workflow_state": ""}) == ""
