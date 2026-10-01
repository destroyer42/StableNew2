"""Test-only workflow registry for generic video-backend contract behavior.

The production catalog keeps the retained LTX anchor workflows ``disabled`` (the required
StableNewLTXAnchorBridge implementation and accepted runtime evidence are absent), so they are
neither runnable nor operator-offerable.  Their contract metadata (inputs, dependencies, compile
shape) is still exercised by generic compiler/probe/backend tests; those tests use this
registry, which never reaches the production registry or any operator-facing surface.
"""

from __future__ import annotations

from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_contracts import WorkflowSpec
from src.video.workflow_registry import WorkflowRegistry


def build_ltx_contract_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    for spec in build_builtin_workflow_specs():
        values = {field: getattr(spec, field) for field in spec.__dataclass_fields__}
        if spec.workflow_id.startswith("ltx_"):
            values["governance_state"] = "approved"
        registry.register(WorkflowSpec(**values))
    return registry
