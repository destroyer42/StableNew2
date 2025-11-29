from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict, field
from typing import Any
from pathlib import Path

LAST_RUN_PATH = Path("state/last_run_v2_5.json")

@dataclass
class LastRunConfigV2_5:
    model: str | None = None
    vae: str | None = None
    sampler_name: str | None = None
    scheduler: str | None = None
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    negative_prompt: str = ""
    prompt: str = ""
    # Add other fields as needed

class LastRunStoreV2_5:
    def __init__(self, path: Path | None = None):
        self.path = path or LAST_RUN_PATH

    def load(self) -> LastRunConfigV2_5 | None:
        if not self.path.exists():
            logging.info(f"Last-run config file not found: {self.path}")
            return None
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Tolerate missing/extra fields
            return LastRunConfigV2_5(**{k: v for k, v in data.items() if k in LastRunConfigV2_5.__annotations__})
        except Exception as exc:
            logging.warning(f"Failed to load last-run config: {exc}")
            return None

    def save(self, cfg: LastRunConfigV2_5) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(asdict(cfg), f, indent=2)
            logging.info(f"Saved last-run config: model={cfg.model}, sampler={cfg.sampler_name}, steps={cfg.steps}, size={cfg.width}x{cfg.height}")
        except Exception as exc:
            logging.warning(f"Failed to save last-run config: {exc}")
