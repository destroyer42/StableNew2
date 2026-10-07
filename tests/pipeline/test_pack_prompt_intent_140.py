"""PR-PROMPT-140: structured PromptPack intent (structure -> adapt -> render) keeps today's SDXL strings byte-for-byte.

``_legacy_resolve_from_pack`` is a verbatim copy of the pre-140 ``UnifiedPromptResolver.resolve_from_pack`` body. The grid below
proves the refactored wrapper, and ``render_pack_intent(resolve_pack_intent(...))``, are identical to it for every combination
of actors, Style Consistency, row LoRAs, embeddings, Matrix values and negative components.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from src.pipeline import resolution_layer as rl
from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import (
    PackPromptIntent,
    PromptResolution,
    UnifiedPromptResolver,
    render_pack_intent,
    resolve_pack_intent,
)
from src.prompting.prompt_adaptation import KIND_ACTOR, KIND_PACK, KIND_STYLE
from src.utils.embedding_prompt_utils import render_embedding_reference


def _legacy_resolve_from_pack(
    resolver: UnifiedPromptResolver,
    *,
    pack_row: PackRow,
    matrix_slot_values: Mapping[str, str] | None = None,
    actor_resolutions: Iterable[Mapping[str, Any]] | None = None,
    style_lora: Mapping[str, Any] | None = None,
    pack_negative: str | None = None,
    global_negative: str = "",
    apply_global_negative: bool = True,
) -> PromptResolution:
    subject = resolver._substitute_matrix_tokens(pack_row.subject_template, matrix_slot_values)
    quality = resolver._substitute_matrix_tokens(pack_row.quality_line, matrix_slot_values)

    actor_trigger_phrases = list(rl._actor_trigger_phrases(actor_resolutions))
    style_trigger_phrase = rl._style_trigger_phrase(style_lora)
    if style_trigger_phrase:
        actor_trigger_phrases.append(style_trigger_phrase)
    merged_lora_tags = rl._dedupe_lora_tags(
        list(rl._actor_lora_tags(actor_resolutions))
        + list(pack_row.lora_tags)
        + list(rl._style_lora_tags(style_lora))
    )
    lora_tokens = " ".join(f"<lora:{name}:{weight}>" for name, weight in merged_lora_tags)
    positive_parts: list[str] = []
    if pack_row.embeddings:
        positive_parts.extend(render_embedding_reference(name, weight) for name, weight in pack_row.embeddings)
    if actor_trigger_phrases:
        positive_parts.append(", ".join(actor_trigger_phrases))
    if quality:
        positive_parts.append(quality)
    if subject:
        positive_parts.append(subject)
    if lora_tokens:
        positive_parts.append(lora_tokens)
    positive = " ".join(part for part in positive_parts if part).strip()
    if not positive:
        positive = "professional photo, high quality"

    negative_parts = []
    global_applied = False
    if apply_global_negative and global_negative:
        negative_parts.append(global_negative.strip())
        global_applied = True
    if pack_negative:
        negative_parts.append(pack_negative.strip())
    if pack_row.negative_embeddings:
        negative_parts.extend(
            render_embedding_reference(name, weight) for name, weight in pack_row.negative_embeddings
        )
    negative_parts.extend(phrase for phrase in pack_row.negative_phrases if phrase)
    if resolver._safety_negative:
        negative_parts.append(resolver._safety_negative)
    negative = ", ".join(part for part in negative_parts if part).strip()
    return PromptResolution(
        positive=positive,
        negative=negative,
        positive_preview=rl._truncate(positive, resolver._max_preview_length),
        negative_preview=rl._truncate(negative, resolver._max_preview_length),
        positive_embeddings=pack_row.embeddings,
        negative_embeddings=pack_row.negative_embeddings,
        lora_tags=merged_lora_tags,
        global_negative_applied=global_applied,
    )


ROWS = {
    "plain": PackRow((), "high quality", "a knight in [[env]]", (), (), ()),
    "rich": PackRow(
        (("styleA", 0.8), ("styleB", 1.0)), "cinematic, (soft light:1.2)", "a [[job]] near [[env]] BREAK end",
        (("detail", 0.6), ("Actor-Lora", 0.5), ("other", 1.0)), (("bad_hands", 1.2), ("neg2", 1.0)), ("blurry", "", "extra fingers"),
    ),
    "empty": PackRow((), "", "", (), (), ()),
}
ACTORS = {
    "none": None,
    "one": [{"lora_name": "Actor-Lora", "weight": 0.9, "trigger_phrase": "actor one"}],
    "shared_phrase": [
        {"lora_name": "a1", "weight": 1, "trigger_phrase": "shared trigger"},
        {"lora_name": "a2", "weight": 0.4, "trigger_phrase": "Shared Trigger"},
        {"lora_path": "C:/loras/pathy.safetensors", "trigger_phrase": "path trigger"},
        {"trigger_phrase": "no lora trigger"},
    ],
}
STYLES = {
    "none": None,
    "applied": {"applied": True, "lora_name": "style-lora", "weight": 0.7, "trigger_phrase": "in style x"},
    "unapplied": {"applied": False, "lora_name": "style-lora", "weight": 0.7, "trigger_phrase": "in style x"},
    "trigger_only": {"applied": True, "trigger_phrase": "style words only"},
    "dup_of_actor": {"applied": True, "lora_name": "Actor-Lora", "weight": 0.3, "trigger_phrase": "dup style"},
}
NEGATIVES = [
    {"pack_negative": None, "global_negative": "", "apply_global_negative": True},
    {"pack_negative": "  pack noise  ", "global_negative": " global hush ", "apply_global_negative": True},
    {"pack_negative": "pack", "global_negative": "global", "apply_global_negative": False},
    {"pack_negative": "", "global_negative": "   ", "apply_global_negative": True},
]
MATRIX = [None, {"env": "castle", "job": "wizard"}, {"env": "forest"}]
GRID = list(itertools.product(ROWS, ACTORS, STYLES, range(len(NEGATIVES)), range(len(MATRIX)), ("", "no nsfw")))


@pytest.mark.parametrize("row_key,actor_key,style_key,neg_i,matrix_i,safety", GRID)
def test_wrapper_and_structure_render_equal_the_legacy_resolver_byte_for_byte(
    row_key, actor_key, style_key, neg_i, matrix_i, safety
) -> None:
    kwargs = dict(
        pack_row=ROWS[row_key], matrix_slot_values=MATRIX[matrix_i], actor_resolutions=ACTORS[actor_key],
        style_lora=STYLES[style_key], **NEGATIVES[neg_i],
    )
    resolver = UnifiedPromptResolver(max_preview_length=40, safety_negative=safety)
    legacy = _legacy_resolve_from_pack(resolver, **kwargs)

    assert resolver.resolve_from_pack(**kwargs) == legacy
    intent = resolver.resolve_intent(**kwargs)
    assert resolver.render_intent(intent) == legacy
    assert render_pack_intent(
        resolve_pack_intent(safety_negative=safety, **kwargs), max_preview_length=40
    ) == legacy


# --- ownership, ordering, structure ----------------------------------------------------------------------------------


def test_matrix_expanded_quality_and_subject_keep_their_roles_and_order() -> None:
    intent = resolve_pack_intent(pack_row=ROWS["rich"], matrix_slot_values={"env": "castle", "job": "wizard"})
    assert intent.quality == "cinematic, (soft light:1.2)"
    assert intent.subject == "a wizard near castle BREAK end"
    rendered = render_pack_intent(intent).positive
    assert rendered.index("cinematic") < rendered.index("a wizard near castle")


def test_embedding_and_negative_component_order_is_preserved() -> None:
    intent = resolve_pack_intent(
        pack_row=ROWS["rich"], pack_negative="pack noise", global_negative="global", safety_negative="safe"
    )
    assert intent.positive_embeddings == (("styleA", 0.8), ("styleB", 1.0))
    assert render_pack_intent(intent).negative == (
        "global, pack noise, " + ", ".join(
            [render_embedding_reference("bad_hands", 1.2), render_embedding_reference("neg2", 1.0), "blurry", "extra fingers", "safe"]
        )
    )


def test_lora_execution_order_is_actor_then_pack_then_style_with_kinds() -> None:
    intent = resolve_pack_intent(
        pack_row=ROWS["rich"], actor_resolutions=ACTORS["one"], style_lora=STYLES["applied"]
    )
    assert [(lora.name, lora.kind) for lora in intent.loras] == [
        ("Actor-Lora", KIND_ACTOR), ("detail", KIND_PACK), ("other", KIND_PACK), ("style-lora", KIND_STYLE),
    ]
    assert intent.loras[0].weight == 0.9  # the actor contribution wins the duplicate name, as it always did


def test_duplicate_lora_names_are_deduplicated_case_insensitively_first_wins() -> None:
    intent = resolve_pack_intent(pack_row=ROWS["rich"], actor_resolutions=ACTORS["one"], style_lora=STYLES["dup_of_actor"])
    names = [lora.name.lower() for lora in intent.loras]
    assert names.count("actor-lora") == 1 and intent.loras[0].kind == KIND_ACTOR


def test_actor_triggers_stay_paired_with_their_actor_lora() -> None:
    intent = resolve_pack_intent(pack_row=ROWS["plain"], actor_resolutions=ACTORS["shared_phrase"])
    owners = {t.text: t.owners for t in intent.triggers}
    assert owners["shared trigger"] == ("a1", "a2")  # one distinct phrase, owned by both carriers
    assert owners["path trigger"] == ("pathy",)
    assert owners["no lora trigger"] == ()  # not LoRA-owned: survives any LoRA omission
    assert [t.kind for t in intent.triggers] == [KIND_ACTOR] * 3


def test_style_trigger_stays_paired_with_the_style_lora_and_is_rendered_last_among_triggers() -> None:
    intent = resolve_pack_intent(pack_row=ROWS["plain"], actor_resolutions=ACTORS["one"], style_lora=STYLES["applied"])
    assert [(t.text, t.kind, t.owners) for t in intent.triggers] == [
        ("actor one", KIND_ACTOR, ("Actor-Lora",)), ("in style x", KIND_STYLE, ("style-lora",)),
    ]
    assert render_pack_intent(intent).positive.startswith("actor one, in style x ")
    trigger_only = resolve_pack_intent(pack_row=ROWS["plain"], style_lora=STYLES["trigger_only"])
    assert trigger_only.triggers[0].owners == () and not trigger_only.loras


def test_an_empty_row_keeps_the_historic_positive_fallback() -> None:
    assert render_pack_intent(resolve_pack_intent(pack_row=ROWS["empty"])).positive == "professional photo, high quality"


def test_the_intent_is_immutable() -> None:
    intent = resolve_pack_intent(pack_row=ROWS["plain"])
    assert isinstance(intent, PackPromptIntent)
    with pytest.raises(AttributeError):
        intent.quality = "changed"  # type: ignore[misc]
