# Subsystem: Learning
# Role: Declares model and LoRA profile descriptors for learning runs.

"""ModelProfile and LoraProfile sidecar dataclasses and helpers."""

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
