"""Model-aware generation-settings profiles (PR-IMG-PROFILE-630).

Recommendations only: they never widen the executable model policy, never enable a stage, and never run or queue work.
"""

from src.generation_profiles.contract import (
    KIND_CUSTOM,
    KIND_LEARNING,
    KIND_RESEARCH,
    GenerationProfile,
    ModelIdentity,
    ProfileError,
    ProfileRef,
)
from src.generation_profiles.service import GenerationProfileService
from src.generation_profiles.store import GenerationProfileStore

__all__ = [
    "KIND_CUSTOM",
    "KIND_LEARNING",
    "KIND_RESEARCH",
    "GenerationProfile",
    "GenerationProfileService",
    "GenerationProfileStore",
    "ModelIdentity",
    "ProfileError",
    "ProfileRef",
]
