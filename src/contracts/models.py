from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PackJobEntry:
    pack_id: str
    pack_name: str
    config_snapshot: dict[str, Any]
    prompt_text: str | None = None
    negative_prompt_text: str | None = None
    stage_flags: dict[str, bool] = field(default_factory=dict)
    randomizer_metadata: dict[str, Any] | None = None
    pack_row_index: int | None = None
    pack_version: str | None = None
    matrix_slot_values: dict[str, str] = field(default_factory=dict)
    learning_metadata: dict[str, Any] | None = None


@dataclass
class JobDraftPart:
    positive_prompt: str
    negative_prompt: str
    estimated_images: int = 1


@dataclass
class JobDraftSummary:
    part_count: int = 0
    total_images: int = 0
    last_positive_prompt: str = ""
    last_negative_prompt: str = ""


@dataclass
class JobDraft:
    packs: list[PackJobEntry] = field(default_factory=list)
    parts: list[JobDraftPart] = field(default_factory=list)
    summary: JobDraftSummary = field(default_factory=JobDraftSummary)

    def add_part(self, part: JobDraftPart) -> None:
        self.parts.append(part)
        self.summary.part_count = len(self.parts)
        self.summary.total_images += part.estimated_images
        self.summary.last_positive_prompt = part.positive_prompt
        self.summary.last_negative_prompt = part.negative_prompt

    def clear(self) -> None:
        self.parts.clear()
        self.summary = JobDraftSummary()


@dataclass
class CurrentConfig:
    """Lightweight facade for the currently selected run configuration."""

    preset_name: str = ""
    model_name: str = ""
    vae_name: str = ""
    sampler_name: str = ""
    scheduler_name: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    batch_size: int = 1
    seed: int | None = None
    subseed: int = -1
    subseed_strength: float = 0.0
    randomization_enabled: bool = False
    max_variants: int = 1
    refiner_enabled: bool = False
    refiner_model_name: str = ""
    refiner_switch_at: float = 0.8
    hires_enabled: bool = False
    hires_upscaler_name: str = "Latent"
    hires_upscale_factor: float = 2.0
    hires_steps: int | None = None
    hires_denoise: float = 0.3
    hires_use_base_model_for_hires: bool = True

