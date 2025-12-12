"""
Replay migration for v2.6 compat (PR-CORE1-D16).

Ensures replayed NJRs always expose a prompt via positive_prompt or config["prompt"].
"""
from typing import Mapping
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.history.legacy_prompt_hydration_v26 import hydrate_prompt_fields

def hydrate_replay_prompt_fields(legacy_entry: Mapping, njr: NormalizedJobRecord) -> None:
    # PR-CORE1-D17: Canonical prompt hydration signature
    hydrate_prompt_fields(njr, legacy_entry)
