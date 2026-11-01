"""Execution eligibility checks used before the canonical repository admission."""

from typing import Any

from src.pipeline.retired_execution import require_no_retired_execution
from src.video.workflow_admission import require_workflow_admission


def require_execution_admission(record: Any) -> None:
    require_no_retired_execution(record)
    require_workflow_admission(record)
