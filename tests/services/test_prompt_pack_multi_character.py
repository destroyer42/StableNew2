"""PR-CORE-014: Multi-Character Support – service-level tests.

These tests exercise the multi-character pipeline from the services boundary:
actor resolution through LoRAManager → actor LoRA ordering in the resolved
prompt → and actors surviving as an intent payload in NJR round-trips.

The fuller unit-level coverage lives in
``tests/pipeline/test_prompt_pack_multi_character.py``.
This file satisfies the PR-CORE-014 spec's required file path and adds
additional integration-style checks that span the service boundary.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from src.pipeline.config_contract_v26 import (
    canonicalize_intent_config,
    extract_actors_intent,
    validate_multi_character_actors,
)
from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import UnifiedPromptResolver
from src.training.lora_manager import LoRAManager


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_actor(
    name: str,
    trigger: str,
    lora_name: str,
    weight: float = 1.0,
) -> dict[str, Any]:
    return {
        "name": name,
        "character_name": name.lower(),
        "trigger_phrase": trigger,
        "lora_name": lora_name,
        "weight": weight,
        "source": "explicit",
    }


def _empty_row() -> PackRow:
    return PackRow(
        embeddings=(), quality_line="", subject_template="",
        lora_tags=(), negative_embeddings=(), negative_phrases=(),
    )


# ---------------------------------------------------------------------------
# Integration: prompt assembly with multiple characters
# ---------------------------------------------------------------------------

class TestMultiCharacterPromptIntegration:
    def test_two_characters_both_in_prompt(self) -> None:
        resolver = UnifiedPromptResolver(max_preview_length=800)
        actors = [
            _make_actor("Kaladin", "kaladin stormblessed", "kaladin_lora", weight=0.9),
            _make_actor("Shallan", "shallan davar", "shallan_lora", weight=0.8),
        ]
        result = resolver.resolve_from_pack(
            pack_row=_empty_row(),
            actor_resolutions=actors,
            pack_negative="",
            global_negative="",
        )
        assert "kaladin stormblessed" in result.positive
        assert "shallan davar" in result.positive

    def test_lora_order_actors_first_style_last(self) -> None:
        resolver = UnifiedPromptResolver(max_preview_length=800)
        row = PackRow(
            embeddings=(), quality_line="",
            subject_template="", lora_tags=(("scene_lora", 0.5),),
            negative_embeddings=(), negative_phrases=(),
        )
        result = resolver.resolve_from_pack(
            pack_row=row,
            actor_resolutions=[
                _make_actor("Kaladin", "kaladin stormblessed", "kaladin_lora", 0.9),
                _make_actor("Shallan", "shallan davar", "shallan_lora", 0.8),
            ],
            style_lora={
                "trigger_phrase": "noir style",
                "lora_name": "style_noir",
                "weight": 0.6,
                "applied": True,
            },
            pack_negative="",
            global_negative="",
        )
        names = [name for name, _w in result.lora_tags]
        assert names.index("kaladin_lora") < names.index("scene_lora")
        assert names.index("shallan_lora") < names.index("scene_lora")
        assert names[-1] == "style_noir"

    def test_three_characters_all_appear(self) -> None:
        resolver = UnifiedPromptResolver(max_preview_length=800)
        actors = [
            _make_actor("Kaladin", "kaladin stormblessed", "kaladin_lora", 0.9),
            _make_actor("Shallan", "shallan davar", "shallan_lora", 0.8),
            _make_actor("Dalinar", "dalinar kholin", "dalinar_lora", 0.7),
        ]
        result = resolver.resolve_from_pack(
            pack_row=_empty_row(),
            actor_resolutions=actors,
            pack_negative="",
            global_negative="",
        )
        for phrase in ("kaladin stormblessed", "shallan davar", "dalinar kholin"):
            assert phrase in result.positive
        lora_names = [n for n, _w in result.lora_tags]
        assert lora_names == ["kaladin_lora", "shallan_lora", "dalinar_lora"]

    def test_actor_weights_honoured_with_non_default_values(self) -> None:
        resolver = UnifiedPromptResolver(max_preview_length=800)
        actors = [
            _make_actor("Primary", "primary char", "primary_lora", weight=1.5),
            _make_actor("Secondary", "secondary char", "secondary_lora", weight=0.3),
        ]
        result = resolver.resolve_from_pack(
            pack_row=_empty_row(),
            actor_resolutions=actors,
            pack_negative="",
            global_negative="",
        )
        tag_dict = dict(result.lora_tags)
        assert tag_dict["primary_lora"] == pytest.approx(1.5)
        assert tag_dict["secondary_lora"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Integration: LoRAManager manifest lookup for multi-character scenes
# ---------------------------------------------------------------------------

class TestLoRAManagerMultiCharacterResolution:
    def test_register_and_resolve_two_characters(self, tmp_path: Path) -> None:
        manager = LoRAManager(base_dir=tmp_path / "embeddings")

        for char, trigger, lora in [
            ("kaladin", "kaladin stormblessed", "kaladin_lora"),
            ("shallan", "shallan davar", "shallan_lora"),
        ]:
            weight_file = tmp_path / f"{char}.safetensors"
            weight_file.write_bytes(b"fake")
            manager.register(
                character_name=char,
                weight_path=str(weight_file),
                metadata={"trigger_phrase": trigger, "lora_name": lora},
            )

        resolved = list(manager.resolve_actors_safe([{"name": "kaladin"}, {"name": "shallan"}]))
        assert len(resolved) == 2
        assert resolved[0]["trigger_phrase"] == "kaladin stormblessed"
        assert resolved[1]["trigger_phrase"] == "shallan davar"

    def test_missing_character_skipped_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = LoRAManager(base_dir=tmp_path / "embeddings")
        actors = [
            {"name": "ghost_character", "lora_name": "ghost_lora"}
            # no trigger_phrase, not in manifest
        ]
        with caplog.at_level(logging.WARNING, logger="src.training.lora_manager"):
            result = list(manager.resolve_actors_safe(actors))
        assert result == []

    def test_one_valid_one_missing_returns_one(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        lora_file = tmp_path / "kaladin.safetensors"
        lora_file.write_bytes(b"fake")
        manager = LoRAManager(base_dir=tmp_path / "embeddings")
        manager.register(
            character_name="kaladin",
            weight_path=str(lora_file),
            metadata={"trigger_phrase": "kaladin stormblessed", "lora_name": "kaladin_lora"},
        )
        actors = [
            {"name": "kaladin"},
            {"name": "ghost", "lora_name": "ghost_lora"},  # no trigger_phrase, not in manifest
        ]
        with caplog.at_level(logging.WARNING, logger="src.training.lora_manager"):
            result = list(manager.resolve_actors_safe(actors))
        assert len(result) == 1
        assert result[0]["name"] == "kaladin"


# ---------------------------------------------------------------------------
# Integration: actors in intent_config schema
# ---------------------------------------------------------------------------

class TestActorsIntentSchemaIntegration:
    def test_validate_then_canonicalize_round_trip(self) -> None:
        raw = [
            {"name": "Kaladin", "lora_name": "k_lora", "weight": 0.9, "trigger_phrase": "k t"},
            {"name": "Shallan", "lora_name": "s_lora"},
        ]
        validated = validate_multi_character_actors(raw)
        canonical = canonicalize_intent_config({"actors": validated})
        extracted = extract_actors_intent(canonical)
        assert len(extracted) == 2
        assert extracted[0]["name"] == "Kaladin"
        assert extracted[0]["weight"] == pytest.approx(0.9)

    def test_actors_in_layered_config_structure_extracted(self) -> None:
        # Simulate a layered config (intent_config / execution_config layers).
        layered = {
            "intent_config": {
                "actors": [
                    {"name": "Kaladin", "lora_name": "k_lora", "weight": 0.9},
                    {"name": "Shallan", "lora_name": "s_lora", "weight": 0.8},
                ]
            },
            "execution_config": {},
            "backend_options": {},
        }
        extracted = extract_actors_intent(layered)
        assert len(extracted) == 2
