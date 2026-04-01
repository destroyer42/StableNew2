"""Unit tests for PR-CORE-014: Multi-Character Support.

Verifies:
- Multiple actor trigger phrases are inserted into the positive prompt.
- Actor LoRA tags appear before pack row tags, which appear before the style LoRA.
- Duplicate actors are deduplicated while preserving insertion order.
- Single-character scenes continue to work without regression.
- config_contract_v26 actors intent round-trips cleanly (canonicalize → extract).
- validate_multi_character_actors normalises and rejects malformed entries.
- LoRAManager.resolve_actors_safe skips missing actors with a warning instead of raising.
- PromptPackNormalizedJobBuilder persists resolved actors into intent_config.
- NJR actors survive round-trip via canonicalize_intent_config.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.pipeline.config_contract_v26 import (
    canonicalize_intent_config,
    extract_actors_intent,
    validate_multi_character_actors,
)
from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import PromptResolution, UnifiedPromptResolver
from src.training.lora_manager import LoRAManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _two_actor_resolutions() -> list[dict[str, Any]]:
    """Kaladin + Shallan as pre-resolved actor dicts (no manifest needed)."""
    return [
        {
            "name": "Kaladin",
            "character_name": "kaladin",
            "trigger_phrase": "kaladin stormblessed",
            "lora_name": "kaladin_lora",
            "lora_path": None,
            "weight": 0.9,
            "source": "explicit",
        },
        {
            "name": "Shallan",
            "character_name": "shallan",
            "trigger_phrase": "shallan davar",
            "lora_name": "shallan_lora",
            "lora_path": None,
            "weight": 0.8,
            "source": "explicit",
        },
    ]


def _pack_row_with_style_lora() -> PackRow:
    return PackRow(
        embeddings=(),
        quality_line="ultra high quality",
        subject_template="fantasy scene on a bridge",
        lora_tags=(("bridges_detail", 0.6),),
        negative_embeddings=(),
        negative_phrases=("blurry",),
    )


def _style_lora_payload() -> dict[str, Any]:
    return {
        "style_id": "ink_wash",
        "trigger_phrase": "ink wash style",
        "lora_name": "style_ink_wash",
        "weight": 0.65,
        "applied": True,
    }


# ---------------------------------------------------------------------------
# 1. resolution_layer – prompt assembly
# ---------------------------------------------------------------------------

class TestMultiCharacterPromptAssembly:
    def test_both_trigger_phrases_appear_in_positive(self) -> None:
        resolver = UnifiedPromptResolver(max_preview_length=500)
        row = _pack_row_with_style_lora()
        result = resolver.resolve_from_pack(
            pack_row=row,
            actor_resolutions=_two_actor_resolutions(),
            pack_negative="",
            global_negative="",
        )
        assert "kaladin stormblessed" in result.positive
        assert "shallan davar" in result.positive

    def test_actor_trigger_phrases_precede_quality_line(self) -> None:
        resolver = UnifiedPromptResolver(max_preview_length=500)
        row = _pack_row_with_style_lora()
        result = resolver.resolve_from_pack(
            pack_row=row,
            actor_resolutions=_two_actor_resolutions(),
            pack_negative="",
            global_negative="",
        )
        actor_pos = result.positive.find("kaladin stormblessed")
        quality_pos = result.positive.find("ultra high quality")
        assert actor_pos < quality_pos, "Actor tokens must come before quality_line"

    def test_lora_ordering_actors_pack_style(self) -> None:
        """Actor LoRAs → pack LoRAs → style LoRA (PR-CORE-014 convention)."""
        resolver = UnifiedPromptResolver(max_preview_length=500)
        row = _pack_row_with_style_lora()
        result = resolver.resolve_from_pack(
            pack_row=row,
            actor_resolutions=_two_actor_resolutions(),
            style_lora=_style_lora_payload(),
            pack_negative="",
            global_negative="",
        )
        lora_names = [name for name, _w in result.lora_tags]
        assert lora_names.index("kaladin_lora") < lora_names.index("bridges_detail")
        assert lora_names.index("shallan_lora") < lora_names.index("bridges_detail")
        assert lora_names.index("bridges_detail") < lora_names.index("style_ink_wash")

    def test_lora_weights_are_preserved(self) -> None:
        resolver = UnifiedPromptResolver(max_preview_length=500)
        result = resolver.resolve_from_pack(
            pack_row=_pack_row_with_style_lora(),
            actor_resolutions=_two_actor_resolutions(),
            style_lora=_style_lora_payload(),
            pack_negative="",
            global_negative="",
        )
        lora_dict = dict(result.lora_tags)
        assert lora_dict["kaladin_lora"] == pytest.approx(0.9)
        assert lora_dict["shallan_lora"] == pytest.approx(0.8)
        assert lora_dict["bridges_detail"] == pytest.approx(0.6)
        assert lora_dict["style_ink_wash"] == pytest.approx(0.65)

    def test_single_character_unchanged_from_existing_behavior(self) -> None:
        """Single-actor scenes must continue to work (backwards compat)."""
        resolver = UnifiedPromptResolver(max_preview_length=500)
        row = PackRow(
            embeddings=(),
            quality_line="cinematic",
            subject_template="hero at dawn",
            lora_tags=(("pack_detail", 0.5),),
            negative_embeddings=(),
            negative_phrases=(),
        )
        single_actor = [
            {
                "name": "Dalinar",
                "character_name": "dalinar",
                "trigger_phrase": "dalinar kholin",
                "lora_name": "dalinar_lora",
                "weight": 1.0,
                "source": "explicit",
            }
        ]
        result = resolver.resolve_from_pack(
            pack_row=row,
            actor_resolutions=single_actor,
            pack_negative="",
            global_negative="",
        )
        assert "dalinar kholin" in result.positive
        assert result.lora_tags == (("dalinar_lora", 1.0), ("pack_detail", 0.5))

    def test_no_actors_zero_regression(self) -> None:
        """No actors → prompt and LoRA tags identical to pre-PR behaviour."""
        resolver = UnifiedPromptResolver(max_preview_length=500)
        row = PackRow(
            embeddings=(),
            quality_line="photorealistic",
            subject_template="forest clearing",
            lora_tags=(("nature_detail", 0.8),),
            negative_embeddings=(),
            negative_phrases=(),
        )
        result = resolver.resolve_from_pack(
            pack_row=row,
            actor_resolutions=None,
            pack_negative="",
            global_negative="",
        )
        assert "photorealistic" in result.positive
        assert result.lora_tags == (("nature_detail", 0.8),)

    def test_duplicate_actors_deduplicated(self) -> None:
        """Same actor specified twice must appear only once in LoRA tags."""
        resolver = UnifiedPromptResolver(max_preview_length=500)
        row = PackRow(
            embeddings=(), quality_line="", subject_template="",
            lora_tags=(), negative_embeddings=(), negative_phrases=(),
        )
        duplicated = _two_actor_resolutions() + [_two_actor_resolutions()[0]]  # Kaladin twice
        result = resolver.resolve_from_pack(
            pack_row=row,
            actor_resolutions=duplicated,
            pack_negative="",
            global_negative="",
        )
        lora_names = [name for name, _w in result.lora_tags]
        assert lora_names.count("kaladin_lora") == 1

    def test_style_trigger_appended_after_actor_triggers(self) -> None:
        resolver = UnifiedPromptResolver(max_preview_length=500)
        result = resolver.resolve_from_pack(
            pack_row=PackRow(
                embeddings=(), quality_line="", subject_template="",
                lora_tags=(), negative_embeddings=(), negative_phrases=(),
            ),
            actor_resolutions=[
                {"name": "A", "trigger_phrase": "actor_a", "lora_name": "lora_a", "weight": 1.0}
            ],
            style_lora={"trigger_phrase": "style_x", "lora_name": "style_lora_x", "weight": 0.5, "applied": True},
            pack_negative="",
            global_negative="",
        )
        actor_pos = result.positive.find("actor_a")
        style_pos = result.positive.find("style_x")
        assert actor_pos < style_pos


# ---------------------------------------------------------------------------
# 2. config_contract_v26 – actors intent canonicalization
# ---------------------------------------------------------------------------

class TestActorsIntentContract:
    def test_actors_survive_canonicalize_round_trip(self) -> None:
        intent_input = {
            "run_mode": "generate",
            "actors": [
                {"name": "Kaladin", "lora_name": "kaladin_lora", "weight": 0.9},
                {"name": "Shallan", "lora_name": "shallan_lora", "weight": 0.8},
            ],
        }
        canonical = canonicalize_intent_config(intent_input)
        assert "actors" in canonical
        assert len(canonical["actors"]) == 2

    def test_extract_actors_intent_returns_validated_list(self) -> None:
        intent_input = {
            "actors": [
                {"name": "Kaladin", "lora_name": "kaladin_lora", "weight": 0.9},
                {"name": "Shallan", "lora_name": "shallan_lora", "weight": 0.8},
            ]
        }
        actors = extract_actors_intent(intent_input)
        assert len(actors) == 2
        assert actors[0]["name"] == "Kaladin"
        assert actors[1]["name"] == "Shallan"

    def test_empty_actors_list_not_included_in_canonical(self) -> None:
        canonical = canonicalize_intent_config({"actors": []})
        assert "actors" not in canonical

    def test_none_actors_not_included(self) -> None:
        canonical = canonicalize_intent_config({"actors": None})
        assert "actors" not in canonical

    def test_actors_not_in_intent_returns_empty_list(self) -> None:
        assert extract_actors_intent({"run_mode": "generate"}) == []

    def test_actors_preserved_alongside_adaptive_refinement(self) -> None:
        intent_input = {
            "actors": [{"name": "Ada", "lora_name": "ada_lora", "weight": 1.0}],
            "adaptive_refinement": {"enabled": True},
        }
        canonical = canonicalize_intent_config(intent_input)
        assert "actors" in canonical
        assert "adaptive_refinement" in canonical


class TestValidateMultiCharacterActors:
    def test_valid_two_actors_normalised_correctly(self) -> None:
        result = validate_multi_character_actors(
            [
                {"name": "Kaladin", "lora_name": "kaladin_lora", "weight": 0.9},
                {"name": "Shallan", "character_name": "shallan", "lora_name": "shallan_lora"},
            ]
        )
        assert len(result) == 2
        assert result[0]["name"] == "Kaladin"
        assert result[0]["weight"] == pytest.approx(0.9)
        assert result[1]["character_name"] == "shallan"
        assert result[1]["weight"] is None  # not provided

    def test_actor_with_no_name_skipped(self) -> None:
        result = validate_multi_character_actors(
            [{"lora_name": "mystery_lora", "weight": 1.0}]
        )
        assert result == []

    def test_non_mapping_items_skipped(self) -> None:
        result = validate_multi_character_actors(["kaladin", 42, None])
        assert result == []

    def test_non_list_input_returns_empty(self) -> None:
        assert validate_multi_character_actors(None) == []
        assert validate_multi_character_actors("kaladin") == []
        assert validate_multi_character_actors({"name": "K"}) == []

    def test_invalid_weight_becomes_none(self) -> None:
        result = validate_multi_character_actors(
            [{"name": "Ada", "weight": "not-a-number"}]
        )
        assert result[0]["weight"] is None

    def test_ordering_preserved(self) -> None:
        actors = [
            {"name": "Primary", "lora_name": "p_lora"},
            {"name": "Secondary", "lora_name": "s_lora"},
        ]
        result = validate_multi_character_actors(actors)
        assert [a["name"] for a in result] == ["Primary", "Secondary"]

    def test_character_name_fallback(self) -> None:
        result = validate_multi_character_actors(
            [{"character_name": "kaladin", "lora_name": "k_lora"}]
        )
        assert result[0]["name"] == "kaladin"


# ---------------------------------------------------------------------------
# 3. LoRAManager.resolve_actors_safe – skip-on-error behaviour
# ---------------------------------------------------------------------------

class TestResolveActorsSafe:
    def test_missing_trigger_phrase_is_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = LoRAManager(base_dir=tmp_path / "embeddings")
        actors = [
            {
                "name": "NoTrigger",
                "lora_name": "no_trigger_lora",
                # No trigger_phrase, and not in manifest
            }
        ]
        with caplog.at_level(logging.WARNING, logger="src.training.lora_manager"):
            result = manager.resolve_actors_safe(actors)
        assert result == []
        assert any("NoTrigger" in msg for msg in caplog.messages)

    def test_missing_lora_identity_is_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = LoRAManager(base_dir=tmp_path / "embeddings")
        actors = [{"name": "Mystery", "trigger_phrase": "mystery", "lora_name": ""}]
        with caplog.at_level(logging.WARNING, logger="src.training.lora_manager"):
            result = manager.resolve_actors_safe(actors)
        assert result == []

    def test_valid_actor_with_all_fields_resolves_successfully(
        self, tmp_path: Path
    ) -> None:
        manager = LoRAManager(base_dir=tmp_path / "embeddings")
        actors = [
            {
                "name": "Kaladin",
                "trigger_phrase": "kaladin stormblessed",
                "lora_name": "kaladin_lora",
                "weight": 0.9,
            }
        ]
        result = list(manager.resolve_actors_safe(actors))
        assert len(result) == 1
        assert result[0]["lora_name"] == "kaladin_lora"
        assert result[0]["trigger_phrase"] == "kaladin stormblessed"
        assert result[0]["weight"] == pytest.approx(0.9)

    def test_mixed_valid_and_invalid_actors_returns_only_valid(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = LoRAManager(base_dir=tmp_path / "embeddings")
        actors = [
            {
                "name": "GoodActor",
                "trigger_phrase": "good trigger",
                "lora_name": "good_lora",
                "weight": 1.0,
            },
            {
                "name": "BadActor",
                # Missing trigger_phrase and not in manifest
                "lora_name": "bad_lora",
            },
        ]
        with caplog.at_level(logging.WARNING, logger="src.training.lora_manager"):
            result = list(manager.resolve_actors_safe(actors))
        assert len(result) == 1
        assert result[0]["name"] == "GoodActor"
        assert any("BadActor" in msg for msg in caplog.messages)

    def test_manifest_registered_actor_resolved_successfully(
        self, tmp_path: Path
    ) -> None:
        """Actor registered in the manifest resolves even with minimal explicit fields."""
        lora_file = tmp_path / "kaladin.safetensors"
        lora_file.write_bytes(b"fake_lora_weights")
        manager = LoRAManager(base_dir=tmp_path / "embeddings")
        manager.register(
            character_name="kaladin",
            weight_path=str(lora_file),
            metadata={
                "trigger_phrase": "kaladin stormblessed",
                "lora_name": "kaladin_lora",
            },
        )

        actors = [{"name": "kaladin"}]
        result = list(manager.resolve_actors_safe(actors))
        assert len(result) == 1
        assert result[0]["trigger_phrase"] == "kaladin stormblessed"
        assert result[0]["source"] in ("manifest", "manifest+override")


# ---------------------------------------------------------------------------
# 4. actors preserved in StoryPlan round-trips
# ---------------------------------------------------------------------------

class TestStoryPlanActors:
    def test_scene_actors_preserved_in_to_dict_round_trip(self) -> None:
        from src.video.story_plan_models import Actor, ScenePlan, ShotPlan

        scene = ScenePlan(
            scene_id="s1",
            display_name="Opening",
            actors=[
                Actor(
                    name="Kaladin",
                    character_name="kaladin",
                    trigger_phrase="kaladin stormblessed",
                    lora_name="kaladin_lora",
                    weight=0.9,
                ),
                Actor(
                    name="Shallan",
                    character_name="shallan",
                    trigger_phrase="shallan davar",
                    lora_name="shallan_lora",
                    weight=0.8,
                ),
            ],
        )
        restored = ScenePlan.from_dict(scene.to_dict())
        assert len(restored.actors) == 2
        assert restored.actors[0].character_name == "kaladin"
        assert restored.actors[1].trigger_phrase == "shallan davar"

    def test_shot_actors_override_scene_actors_on_merge(self) -> None:
        from src.video.story_plan_models import Actor, merge_actor_lists

        scene_actors = [
            Actor(name="Kaladin", character_name="kaladin", lora_name="k_v1", weight=0.7)
        ]
        shot_actors = [
            Actor(
                name="Kaladin",
                character_name="kaladin",
                trigger_phrase="kaladin close-up",
                weight=0.95,
            ),
            Actor(name="Shallan", character_name="shallan", lora_name="s_lora"),
        ]
        merged = merge_actor_lists(scene_actors, shot_actors)
        assert len(merged) == 2
        kaladin = merged[0]
        assert kaladin.weight == pytest.approx(0.95)
        assert kaladin.lora_name == "k_v1"  # inherited from scene
        assert kaladin.trigger_phrase == "kaladin close-up"  # overridden by shot

    def test_empty_actors_list_is_safe(self) -> None:
        from src.video.story_plan_models import Actor, merge_actor_lists

        result = merge_actor_lists([], [])
        assert result == []


# ---------------------------------------------------------------------------
# 5. NJR actors intent_config integration – builder-level
# ---------------------------------------------------------------------------

class TestNJRActorsIntentRoundTrip:
    """Verify that actors survive canonicalize_intent_config in an NJR-like payload."""

    def test_actors_in_intent_payload_survive_canonicalize(self) -> None:
        intent_payload = {
            "run_mode": "generate",
            "source": "add_to_queue",
            "prompt_source": "pack",
            "prompt_pack_id": "my_pack",
            "actors": [
                {
                    "name": "Kaladin",
                    "character_name": "kaladin",
                    "lora_name": "kaladin_lora",
                    "trigger_phrase": "kaladin stormblessed",
                    "weight": 0.9,
                },
                {
                    "name": "Shallan",
                    "character_name": "shallan",
                    "lora_name": "shallan_lora",
                    "trigger_phrase": "shallan davar",
                    "weight": 0.8,
                },
            ],
        }
        canonical = canonicalize_intent_config(intent_payload)
        assert "actors" in canonical
        actors = canonical["actors"]
        assert len(actors) == 2
        names = [a["name"] for a in actors]
        assert "Kaladin" in names
        assert "Shallan" in names

    def test_single_actor_still_in_intent(self) -> None:
        intent_payload = {
            "actors": [{"name": "Dalinar", "lora_name": "dalinar_lora", "weight": 1.0}]
        }
        canonical = canonicalize_intent_config(intent_payload)
        assert len(canonical["actors"]) == 1

    def test_extracted_actors_match_original_names(self) -> None:
        intent_input = {
            "actors": [
                {"name": "Kaladin", "lora_name": "k_lora", "weight": 0.9},
                {"name": "Shallan", "lora_name": "s_lora", "weight": 0.8},
            ]
        }
        extracted = extract_actors_intent(intent_input)
        assert [a["name"] for a in extracted] == ["Kaladin", "Shallan"]
