from __future__ import annotations

import json
from pathlib import Path

from src.video.story_plan_models import StoryPlan, StoryPlanSummary


class StoryPlanStore:
    DEFAULT_ROOT = Path("data") / "story_plans"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else self.DEFAULT_ROOT

    @staticmethod
    def _safe_plan_id(plan_id: str) -> str:
        return str(plan_id).replace("/", "_").replace(":", "_")

    def plan_path(self, plan_id: str) -> Path:
        safe_plan_id = self._safe_plan_id(plan_id)
        if not safe_plan_id:
            raise ValueError("Story plan id is required")
        return self.root / f"{safe_plan_id}.json"

    def save_plan(self, plan: StoryPlan) -> Path:
        path = self.plan_path(plan.plan_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(plan.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(path)
        return path

    def load_plan(self, plan_id: str) -> StoryPlan | None:
        path = self.plan_path(plan_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return StoryPlan.from_dict(payload)

    def list_plan_summaries(self) -> list[StoryPlanSummary]:
        if not self.root.exists():
            return []
        summaries: list[StoryPlanSummary] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            summaries.append(StoryPlan.from_dict(payload).summary())
        summaries.sort(key=lambda item: (item.display_name.lower(), item.plan_id))
        return summaries


__all__ = ["StoryPlanStore"]