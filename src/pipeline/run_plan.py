from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class PlannedJob:
    stage_name: str
    prompt_text: str
    variant_id: int
    batch_index: int
    seed: int | None = None


@dataclass
class RunPlan:
    jobs: List[PlannedJob] = field(default_factory=list)
    total_jobs: int = 0
    total_images: int = 0
    enabled_stages: List[str] = field(default_factory=list)

