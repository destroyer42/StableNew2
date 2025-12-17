"""Config Variant Plan V2 — Config Sweep Support (PR-CORE-E).

This module provides ConfigVariantPlanV2 for defining config-level sweeps
that expand jobs without modifying prompts or PromptPack content.

Architecture alignment:
- PromptPack-only invariant: Sweeps affect configs, not prompts
- Builder purity: Expansion happens inside builder pipeline
- Determinism: Config variants are applied deterministically

Typical expansion:
    rows × config_variants × matrix_variants × batches → NormalizedJobRecord[]

Example:
    PromptPack "warriors" with 3 rows
    Config sweep: [cfg_low=4.5, cfg_mid=7.0, cfg_high=10.0]
    Matrix variants: 2
    Batch size: 2

    Total jobs: 3 rows × 3 configs × 2 variants × 2 batch = 36 jobs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ConfigVariant", "ConfigVariantPlanV2"]


@dataclass
class ConfigVariant:
    """A single config variant in a sweep.

    Attributes:
        label: Human-readable name (e.g., "cfg_low", "sampler_euler_a")
        overrides: Dict of config paths to values (e.g., {"txt2img.cfg_scale": 4.5})
        index: Position in variant list (0-based)

    Examples:
        ConfigVariant(
            label="cfg_high",
            overrides={"txt2img.cfg_scale": 10.0, "txt2img.steps": 30},
            index=2
        )
    """

    label: str
    overrides: dict[str, Any]
    index: int

    def __post_init__(self):
        """Validate variant data."""
        if not self.label or not self.label.strip():
            raise ValueError("ConfigVariant.label must be non-empty")
        if not isinstance(self.overrides, dict):
            raise TypeError("ConfigVariant.overrides must be a dict")
        if not isinstance(self.index, int) or self.index < 0:
            raise ValueError("ConfigVariant.index must be non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for job metadata."""
        return {
            "label": self.label,
            "overrides": self.overrides.copy(),
            "index": self.index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigVariant:
        """Deserialize from dict."""
        return cls(
            label=data["label"],
            overrides=data.get("overrides", {}),
            index=data["index"],
        )


@dataclass
class ConfigVariantPlanV2:
    """Config sweep plan defining multiple config variants.

    When enabled=True, the builder expands jobs across all variants.
    When enabled=False (default), a single implicit variant is used.

    Attributes:
        variants: List of config variants to expand
        enabled: Whether sweep is active

    Rules:
        - If enabled and variants is empty → validation error
        - If disabled, builder uses base merged config (no sweep)
        - Variant labels must be unique within a plan
        - Overrides use dot-notation paths (e.g., "txt2img.cfg_scale")

    Examples:
        # Simple CFG sweep
        ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant("cfg_low", {"txt2img.cfg_scale": 4.5}, 0),
                ConfigVariant("cfg_mid", {"txt2img.cfg_scale": 7.0}, 1),
                ConfigVariant("cfg_high", {"txt2img.cfg_scale": 10.0}, 2),
            ]
        )

        # Multi-parameter sweep
        ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant(
                    "fast",
                    {"txt2img.steps": 15, "txt2img.sampler_name": "Euler a"},
                    0
                ),
                ConfigVariant(
                    "quality",
                    {"txt2img.steps": 30, "txt2img.sampler_name": "DPM++ 2M Karras"},
                    1
                ),
            ]
        )
    """

    variants: list[ConfigVariant] = field(default_factory=list)
    enabled: bool = False

    def __post_init__(self):
        """Validate plan consistency."""
        if self.enabled and not self.variants:
            raise ValueError("ConfigVariantPlanV2: enabled=True requires at least one variant")

        # Check for duplicate labels
        labels = [v.label for v in self.variants]
        if len(labels) != len(set(labels)):
            duplicates = [label for label in labels if labels.count(label) > 1]
            raise ValueError(f"ConfigVariantPlanV2: duplicate variant labels: {duplicates}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for config snapshots."""
        return {
            "enabled": self.enabled,
            "variants": [v.to_dict() for v in self.variants],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigVariantPlanV2:
        """Deserialize from dict."""
        return cls(
            enabled=data.get("enabled", False),
            variants=[ConfigVariant.from_dict(v) for v in data.get("variants", [])],
        )

    @classmethod
    def single_variant(cls, label: str = "base") -> ConfigVariantPlanV2:
        """Create a plan with a single implicit variant (no overrides).

        Used when sweep is disabled but builder expects a plan.
        """
        return cls(
            enabled=False,
            variants=[ConfigVariant(label=label, overrides={}, index=0)],
        )

    def get_variant_count(self) -> int:
        """Return number of variants, or 1 if disabled."""
        if not self.enabled or not self.variants:
            return 1
        return len(self.variants)

    def iter_variants(self):
        """Iterate over variants, yielding single implicit variant if disabled."""
        if not self.enabled or not self.variants:
            yield ConfigVariant(label="base", overrides={}, index=0)
        else:
            yield from self.variants
