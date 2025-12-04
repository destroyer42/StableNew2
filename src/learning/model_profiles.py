# Subsystem: Learning
# Role: Declares model and LoRA profile descriptors for learning runs.

"""Model Profiles & Style-Aware Defaults (V2-P1)

This module defines the data structures and helpers used to represent
**ModelProfiles** – structured sidecar "priors" that StableNewV2 uses to
bootstrap good pipeline defaults for a given base model.

ModelProfiles are consumed by:
- The controller / app state when constructing a fresh PipelineConfig.
- The Learning System as a baseline config to vary in controlled experiments.
- Future analytics and recommendation layers.
(See Learning_System_Spec_v2 for the full design.)

Core Concepts

1. ModelProfile
   A ModelProfile describes recommended settings for a single base model
   (e.g., SDXL base, RealisticVision, WD1.5, AnythingV5).  In addition to
   presets and sampler/scheduler recommendations, V2-P1 introduces refiner
   and hires-fix defaults:

   - default_refiner_id: Optional[str]
       Logical identifier for the recommended refiner (per docs/model_defaults_v2/V2-P1.md §2.1).
   - default_hires_upscaler_id: Optional[str]
       Logical identifier for the hires upscaler (per docs/model_defaults_v2/V2-P1.md §2.2).
   - default_hires_denoise: Optional[float]
       Suggested hires denoise strength within the ranges described in §3.3.
   - style_profile_id: Optional[str]
       Optional link to a StyleProfile like "sdxl_realism" or "anime".

   These fields are priors only; they are used only when there is no last-run
   or preset override for a pipeline run.

2. Precedence
   Defaults from ModelProfiles follow this order:
   1. Last-run config
   2. User preset
   3. ModelProfile/style defaults
   4. Engine fallback

3. Learning & Randomizer Integration
   Learning treats ModelProfile defaults as the baseline and may sweep hires
   denoise nearby. Randomizer does not change refiner/hires by default.

Implementation guidance:
- Canonical IDs live in docs/model_defaults_v2/V2-P1.md.
- ModelProfiles may leave these fields None to fall back to existing behavior.
- Keep this module GUI-free.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Literal
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

@dataclass
class LoraOverlay:
    name: str
    weight: float

@dataclass
class ModelPreset:
    id: str
    label: str
    rating: str  # "bad" | "neutral" | "good" | "better" | "best"
    source: str  # "internet_prior", "local_learning", etc.
    sampler: str
    scheduler: Optional[str]
    steps: int
    cfg: float
    resolution: Tuple[int, int]
    lora_overlays: List[LoraOverlay] = field(default_factory=list)

@dataclass
class ModelProfile:
    kind: Literal["model_profile"]
    version: int
    model_name: str
    base_type: str
    tags: List[str]
    recommended_presets: List[ModelPreset]
    learning_summary: Dict[str, Any] = field(default_factory=dict)
    default_refiner_id: Optional[str] = None
    default_hires_upscaler_id: Optional[str] = None
    default_hires_denoise: Optional[float] = None
    style_profile_id: Optional[str] = None


# ModelProfile refiner/hires defaults (V2-P1):
#   default_refiner_id: Optional[str]
#       Canonical refiner ID (see docs/model_defaults_v2/V2-P1.md §2.1).
#   default_hires_upscaler_id: Optional[str]
#       Canonical hires upscaler ID (see docs/model_defaults_v2/V2-P1.md §2.2).
#   default_hires_denoise: Optional[float]
#       Recommended hires denoise strength (see §3.3 for ranges).
#   style_profile_id: Optional[str]
#       Link to a style profile (e.g., "sdxl_realism", "anime").
    style_profile_id: Optional[str] = None

@dataclass
class LoraRecommendedWeight:
    label: str
    weight: float
    rating: str

@dataclass
class LoraRecommendedPairing:
    model: str
    preset_id: Optional[str]
    rating: str

@dataclass
class LoraProfile:
    kind: Literal["lora_profile"]
    version: int
    lora_name: str
    target_base_type: str
    intended_use: List[str]
    trigger_phrases: List[str]
    recommended_weights: List[LoraRecommendedWeight] = field(default_factory=list)
    recommended_pairings: List[LoraRecommendedPairing] = field(default_factory=list)
    learning_summary: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SuggestedPreset:
    sampler: str
    scheduler: Optional[str]
    steps: int
    cfg: float
    resolution: Tuple[int, int]
    lora_weights: Dict[str, float]
    source: str
    preset_id: Optional[str]

# --- Sidecar Loaders ---
def load_model_profile(path: Path) -> Optional[ModelProfile]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("kind") != "model_profile" or data.get("version") != 1:
            raise ValueError(f"Invalid model_profile kind/version in {path}")
        return ModelProfile(**data)
    except Exception as e:
        logger.warning(f"Failed to load model profile {path}: {e}")
        return None

def load_lora_profile(path: Path) -> Optional[LoraProfile]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("kind") != "lora_profile" or data.get("version") != 1:
            raise ValueError(f"Invalid lora_profile kind/version in {path}")
        return LoraProfile(**data)
    except Exception as e:
        logger.warning(f"Failed to load lora profile {path}: {e}")
        return None

def find_model_profile_for_checkpoint(checkpoint_path: Path) -> Optional[ModelProfile]:
    stem = checkpoint_path.stem
    sidecar = checkpoint_path.parent / f"{stem}.modelprofile.json"
    return load_model_profile(sidecar)

def find_lora_profile_for_name(lora_name: str, lora_search_paths: Sequence[Path]) -> Optional[LoraProfile]:
    for base in lora_search_paths:
        candidate = base / f"{lora_name}.loraprofile.json"
        if candidate.exists():
            return load_lora_profile(candidate)
    return None

# --- Preset Suggestion Helper ---
def suggest_preset_for(model_profile: Optional[ModelProfile], lora_profiles: Sequence[LoraProfile]) -> Optional[SuggestedPreset]:
    if not model_profile or not model_profile.recommended_presets:
        return None
    # Sort presets by rating
    rating_order = {"best": 5, "better": 4, "good": 3, "neutral": 2, "bad": 1}
    presets = sorted(model_profile.recommended_presets, key=lambda p: rating_order.get(p.rating, 0), reverse=True)
    chosen = presets[0]
    # Merge LoRA weights
    lora_weights = {}
    for overlay in chosen.lora_overlays:
        lora_weights[overlay.name] = overlay.weight
    # Overlay recommended weights from LoraProfiles
    for lora in lora_profiles:
        for rw in lora.recommended_weights:
            lora_weights[lora.lora_name] = rw.weight
    return SuggestedPreset(
        sampler=chosen.sampler,
        scheduler=chosen.scheduler,
        steps=chosen.steps,
        cfg=chosen.cfg,
        resolution=chosen.resolution,
        lora_weights=lora_weights,
        source=chosen.source,
        preset_id=chosen.id,
    )


STYLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "sdxl_realism": {
        "default_refiner_id": "sdxl_refiner_default",
        "default_hires_upscaler_id": "Latent",
        "default_hires_denoise": 0.25,
    },
    "sdxl_portrait": {
        "default_refiner_id": "sdxl_portrait_refiner",
        "default_hires_upscaler_id": "ESRGAN_4x",
        "default_hires_denoise": 0.2,
    },
    "sdxl_stylized": {
        "default_refiner_id": "sdxl_stylized_refiner",
        "default_hires_upscaler_id": "4x-UltraSharp",
        "default_hires_denoise": 0.35,
    },
    "sd15_realism": {
        "default_refiner_id": "sd15_refiner_default",
        "default_hires_upscaler_id": "Latent",
        "default_hires_denoise": 0.3,
    },
    "anime": {
        "default_refiner_id": "anime_refiner",
        "default_hires_upscaler_id": "4x-UltraSharp",
        "default_hires_denoise": 0.4,
    },
}


def get_profile_defaults(profile: ModelProfile) -> dict[str, Any]:
    for style_id, defaults in STYLE_DEFAULTS.items():
        if style_id in profile.tags or style_id == profile.base_type:
            return defaults
    return {}


def infer_style_id_for_model(model_name: str | None) -> str | None:
    if not model_name:
        return None
    normalized = model_name.lower()
    if "anime" in normalized or "wd" in normalized or "waifu" in normalized:
        return "anime"
    if "sdxl" in normalized:
        if "portrait" in normalized or "face" in normalized:
            return "sdxl_portrait"
        if "stylized" in normalized or "stylize" in normalized:
            return "sdxl_stylized"
        return "sdxl_realism"
    if "sd15" in normalized or "stable-diffusion-v1" in normalized or "v1-5" in normalized:
        return "sd15_realism"
    return None


def get_model_profile_defaults_for_model(model_name: str | None) -> dict[str, Any]:
    style_id = infer_style_id_for_model(model_name)
    if not style_id:
        return {}
    return STYLE_DEFAULTS.get(style_id, {})
