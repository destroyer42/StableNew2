"""Execution eligibility checks used before the canonical repository admission."""

from typing import Any

from src.pipeline.image_admission import require_image_admission
from src.pipeline.retired_execution import require_no_retired_execution
from src.video.workflow_admission import require_workflow_admission


def require_execution_admission(record: Any) -> None:
    require_no_retired_execution(record)
    require_workflow_admission(record)
    # N1: real image-plan blocks are reported at Queue, never only after the job has waited in the queue.
    require_image_admission(record)
