"""PR-PROMPT-140: model-adaptive PromptPack compilation (one authored pack -> many immutable, target-specific NJRs).

Real ``PromptPackNormalizedJobBuilder`` + real native PromptPack files + the real Klein admission validator. Only model-family
and LoRA *evidence* is injected (the cache-only AssetRegistry contract); nothing scans, hashes, or reaches a backend.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.gui.app_state_v2 import PackJobEntry
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.image_backends.forge_klein_profile import KleinProfileError
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.prompt_pack_job_builder import (
    PROMPT_ADAPTATION_CONTRACT,
    PromptPackNormalizedJobBuilder,
)
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.prompting import prompt_adaptation as pa
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION, load_prompt_pack_document
from tests.pipeline.test_pack_prompt_intent_140 import _legacy_resolve_from_pack
from tests.pipeline.test_prompt_pack_job_builder import (
    BASE_PACK_CONFIG,
    SequentialIdGenerator,
    StubConfigManager,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "juggernaut.safetensors"
MYSTERY = "mystery.safetensors"
_SDXL = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
S = KleinLoraStatus


@pytest.fixture(autouse=True)
def _forge_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")


def family_lookup(name: str):
    return {SDXL: _SDXL, MYSTERY: CompatibilityProfile(CompatibilityStatus.CONFLICTING, None, ())}.get(name)


def evidence(table: dict[str, KleinLoraStatus], calls: list[str] | None = None):
    def resolve(name: str) -> KleinLoraDecision:
        if calls is not None:
            calls.append(name)
        return KleinLoraDecision(name=name, status=table.get(name, S.UNVERIFIED), reason="test evidence")

    return resolve


class _Config(StubConfigManager):
    def __init__(self, tmp_path: Path, *, model: str, extra: dict[str, Any] | None = None) -> None:
        super().__init__(tmp_path)
        txt2img = {**BASE_PACK_CONFIG["txt2img"], "model": model, "negative_prompt": "config negative"}
        if model == KLEIN:
            txt2img.update(width=768, height=1024)
        self._config = {**BASE_PACK_CONFIG, "txt2img": txt2img, "prompt_optimizer": {"enabled": True}, **(extra or {})}


class _Actors:
    def __init__(self, actors: list[dict[str, Any]]) -> None:
        self.actors = actors

    def resolve_actors(self, _items: Any) -> list[dict[str, Any]]:
        return copy.deepcopy(self.actors)


class _Styles:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def resolve_selection(self, _style: Any, base_model: str | None = None) -> Any:
        return SimpleNamespace(to_dict=lambda: copy.deepcopy(self.payload))


SLOT = {
    "index": 0,
    "text": "masterpiece, (red dress:1.2), a lighthouse (at dusk) BREAK a quiet harbor in [[env]]",
    "negative": "blurry, watermark",
    "positive_embeddings": ["pos_embed"],
    "negative_embeddings": ["neg_embed"],
    "loras": [["lora_bad", 0.8], ["lora_ok", 0.7], ["lora_extra", 0.6]],
}
MATRIX = {"enabled": True, "mode": "sequential", "limit": 8, "slots": [{"name": "env", "values": ["forest", "castle"]}]}


def write_pack(tmp_path: Path, slot: dict[str, Any] | None = None, matrix: dict[str, Any] | None = None) -> Path:
    path = tmp_path / "packs" / "adapt-pack.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": "adapt-pack",
                    "slots": [slot or SLOT],
                    "matrix": matrix or {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def build(
    tmp_path: Path,
    model: str,
    *,
    table: dict[str, KleinLoraStatus] | None = None,
    slot: dict[str, Any] | None = None,
    matrix: dict[str, Any] | None = None,
    actors: list[dict[str, Any]] | None = None,
    style: dict[str, Any] | None = None,
    stage_flags: dict[str, bool] | None = None,
    lookup: Any = family_lookup,
    resolver: Any = None,
    extra_config: dict[str, Any] | None = None,
) -> list[NormalizedJobRecord]:
    config = _Config(tmp_path, model=model, extra=({"style_lora": {"enabled": True, "style_id": "s"}, **(extra_config or {})} if style else extra_config))
    write_pack(tmp_path, slot, matrix)
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config.packs_dir,
        lora_manager=_Actors(actors) if actors else None,
        style_lora_manager=_Styles(style) if style else None,
        model_family_lookup=lookup,
        lora_resolver=resolver or evidence(table or {}),
    )
    snapshot = {"story_plan": {"actors": [{"name": "x"}]}} if actors else {}
    entry = PackJobEntry(
        pack_id="adapt-pack", pack_name="Adapt Pack", config_snapshot=snapshot, stage_flags=stage_flags or {"txt2img": True},
        randomizer_metadata={"enabled": False}, pack_row_index=0, matrix_slot_values={},
    )
    return builder.build_jobs([entry])


def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def manifest(record: NormalizedJobRecord) -> dict[str, Any]:
    return plain(record.provenance.metadata["prompt_adaptation"])


def codes(record: NormalizedJobRecord) -> list[str]:
    return [op["code"] for op in manifest(record)["operations"]]


def compatible_backend(table: dict[str, KleinLoraStatus] | None = None) -> ForgeWebUIImageBackend:
    return ForgeWebUIImageBackend(lora_resolver=evidence(table or {}))


# --- SDXL identity -------------------------------------------------------------------------------------------------------


def test_sdxl_compiles_exactly_as_before_and_only_gains_an_identity_adaptation_block(tmp_path: Path) -> None:
    record = build(tmp_path, SDXL, matrix=MATRIX)[0]
    unknown = build(tmp_path, SDXL, matrix=MATRIX, lookup=lambda _name: None)[0]  # same work, target not evidenced

    assert manifest(record)["adaptable"] is True and manifest(record)["changed"] is False and codes(record) == []
    assert manifest(record)["contract"] == PROMPT_ADAPTATION_CONTRACT and manifest(record)["family"] == "sdxl"

    def stripped(njr: NormalizedJobRecord) -> dict[str, Any]:
        data = njr.to_dict()
        data["provenance"]["metadata"].pop("prompt_adaptation")
        return data

    assert stripped(record) == stripped(unknown)  # settings, stages, backend options, embeddings, LoRAs: identical


def test_sdxl_strings_equal_the_legacy_resolver_for_the_same_inputs(tmp_path: Path) -> None:
    record = build(tmp_path, SDXL, matrix={**MATRIX, "slots": [{"name": "env", "values": ["forest"]}]})[0]
    from src.pipeline.resolution_layer import UnifiedPromptResolver
    from src.promptpacks.storage import prompt_pack_rows

    row = prompt_pack_rows(load_prompt_pack_document(tmp_path / "packs" / "adapt-pack.json"))[0]
    legacy = _legacy_resolve_from_pack(
        UnifiedPromptResolver(), pack_row=row, matrix_slot_values={"env": "forest"}, pack_negative="config negative",
        global_negative="global-negative", apply_global_negative=True,
    )
    assert record.positive_prompt == legacy.positive and record.negative_prompt == legacy.negative
    assert [(t.name, t.weight) for t in record.lora_tags] == list(legacy.lora_tags)
    assert "(red dress:1.2)" in record.positive_prompt and "BREAK" in record.positive_prompt
    assert "blurry" in record.negative_prompt and "global-negative" in record.negative_prompt


# --- Klein adaptation ----------------------------------------------------------------------------------------------------


KLEIN_TABLE = {"lora_bad": S.INCOMPATIBLE, "lora_ok": S.COMPATIBLE, "lora_extra": S.COMPATIBLE}


def test_one_authored_pack_compiles_into_a_klein_compatible_nrj_that_passes_backend_admission(tmp_path: Path) -> None:
    record = build(tmp_path, KLEIN, table=KLEIN_TABLE)[0]

    assert record.negative_prompt == ""  # pack/config/global negative + negative phrases + negative embeddings: all omitted
    assert record.provenance.positive_embeddings == () and record.provenance.negative_embeddings == ()
    assert "embedding:" not in record.positive_prompt and "pos_embed" not in record.positive_prompt
    assert "(red dress:1.2)" not in record.positive_prompt and "red dress" in record.positive_prompt
    assert "BREAK" not in record.positive_prompt and "(at dusk)" in record.positive_prompt  # ordinary prose survives
    # only the compatible LoRA within the one-LoRA envelope remains: bad -> incompatible, extra -> over the limit
    assert [(t.name, t.weight) for t in record.lora_tags] == [("lora_ok", 0.7)]
    assert record.positive_prompt.count("<lora:") == 1 and record.positive_prompt.endswith("<lora:lora_ok:0.7>")
    assert "lora_bad" not in record.positive_prompt and "lora_extra" not in record.positive_prompt
    assert codes(record).count(pa.OP_LORA_DROPPED_INCOMPATIBLE) == 1 and codes(record).count(pa.OP_LORA_DROPPED_OVER_LIMIT) == 1
    compatible_backend(KLEIN_TABLE).validate_njr_intent(record, ["txt2img"])
    assert manifest(record)["complete"] is True


def test_the_effective_njr_is_internally_consistent(tmp_path: Path) -> None:
    record = build(tmp_path, KLEIN, table=KLEIN_TABLE)[0]
    config = dict(record.config)
    assert record.positive_prompt == config["prompt"] and record.negative_prompt == config["negative_prompt"] == ""
    declared = [(t.name, t.weight) for t in record.lora_tags]
    assert declared == [("lora_ok", 0.7)] and f"<lora:{declared[0][0]}:{declared[0][1]}>" in record.positive_prompt


def test_actor_and_style_triggers_follow_their_own_loras_and_unrelated_prose_is_never_deleted(tmp_path: Path) -> None:
    actors = [
        {"lora_name": "actor_bad", "weight": 0.9, "trigger_phrase": "actor-bad-words"},
        {"lora_name": "actor_ok", "weight": 0.8, "trigger_phrase": "actor-ok-words"},
        {"trigger_phrase": "loraless-words"},
    ]
    style = {"applied": True, "lora_name": "style_lora", "weight": 0.5, "trigger_phrase": "style-words"}
    slot = {**SLOT, "text": "a lighthouse; also mentions lora_bad and actor-bad-words in prose"}
    table = {"actor_bad": S.INCOMPATIBLE, "actor_ok": S.COMPATIBLE, "lora_bad": S.INCOMPATIBLE, "style_lora": S.COMPATIBLE,
             "lora_ok": S.COMPATIBLE, "lora_extra": S.COMPATIBLE}
    record = build(tmp_path, KLEIN, table=table, slot=slot, actors=actors, style=style)[0]

    positive = record.positive_prompt
    # actor_ok is first in execution order and compatible, so it takes the single slot; everything after it is over the limit
    assert [(t.name) for t in record.lora_tags] == ["actor_ok"]
    assert "actor-ok-words" in positive and "loraless-words" in positive  # owned-by-retained and un-owned triggers stay
    assert "actor-bad-words, " not in positive.split("a lighthouse")[0]  # the dropped actor's owned trigger is gone ...
    assert "style-words" not in positive  # ... and so is the style trigger of the omitted style LoRA
    assert "also mentions lora_bad and actor-bad-words in prose" in positive  # authored prose is never string-stripped
    ops = codes(record)
    assert pa.OP_ACTOR_TRIGGER_DROPPED in ops and pa.OP_STYLE_TRIGGER_DROPPED in ops
    assert pa.OP_LORA_DROPPED_INCOMPATIBLE in ops  # actor_bad (and the pack-row lora_bad)
    assert pa.OP_PACK_TRIGGER_UNOWNED in ops  # the recorded limitation: pack-row LoRA triggers are not tracked


def test_a_retained_style_lora_keeps_its_trigger(tmp_path: Path) -> None:
    style = {"applied": True, "lora_name": "style_lora", "weight": 0.5, "trigger_phrase": "style-words"}
    slot = {**SLOT, "loras": []}
    record = build(tmp_path, KLEIN, table={"style_lora": S.COMPATIBLE}, slot=slot, style=style)[0]
    assert "style-words" in record.positive_prompt and [t.name for t in record.lora_tags] == ["style_lora"]
    compatible_backend({"style_lora": S.COMPATIBLE}).validate_njr_intent(record, ["txt2img"])


def test_unsupported_non_prompt_features_are_never_silently_removed(tmp_path: Path) -> None:
    record = build(tmp_path, KLEIN, table=KLEIN_TABLE, stage_flags={"txt2img": True, "adetailer": True})[0]
    assert "adetailer" in [stage.stage_type for stage in record.stages if stage.enabled]  # the stage chain is intact
    with pytest.raises(KleinProfileError):
        compatible_backend(KLEIN_TABLE).validate_njr_intent(record, ["txt2img", "adetailer"])


# --- evidence uncertainty ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [S.UNVERIFIED, S.CONFLICTING])
def test_absent_or_conflicting_evidence_never_silently_deletes_an_authored_lora(tmp_path: Path, status) -> None:
    record = build(tmp_path, KLEIN, table={"lora_bad": status, "lora_ok": status, "lora_extra": status})[0]

    assert [t.name for t in record.lora_tags] == ["lora_bad", "lora_ok", "lora_extra"]  # all preserved, authored order
    assert all(f"<lora:{n}:" in record.positive_prompt for n in ("lora_bad", "lora_ok", "lora_extra"))
    assert manifest(record)["complete"] is False
    expected = pa.OP_LORA_RETAINED_CONFLICTING if status is S.CONFLICTING else pa.OP_LORA_RETAINED_UNVERIFIED
    assert codes(record).count(expected) == 3
    with pytest.raises(KleinProfileError):  # the existing fail-closed admission stays final
        compatible_backend({}).validate_njr_intent(record, ["txt2img"])


def test_definitive_incompatibility_is_distinguishable_from_absent_evidence(tmp_path: Path) -> None:
    record = build(tmp_path, KLEIN, table={"lora_bad": S.INCOMPATIBLE})[0]
    assert "lora_bad" not in [t.name for t in record.lora_tags]
    assert [t.name for t in record.lora_tags] == ["lora_ok", "lora_extra"]  # the unverified ones stay
    assert pa.OP_LORA_DROPPED_INCOMPATIBLE in codes(record) and pa.OP_LORA_RETAINED_UNVERIFIED in codes(record)


def test_a_missing_resolver_is_absence_of_evidence_not_incompatibility(tmp_path: Path) -> None:
    config = _Config(tmp_path, model=KLEIN)
    write_pack(tmp_path)
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config, job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config.packs_dir, model_family_lookup=family_lookup,
        lora_resolver=lambda name: KleinLoraDecision(name, S.UNVERIFIED, "no registry"),
    )
    entry = PackJobEntry(pack_id="adapt-pack", pack_name="p", config_snapshot={}, stage_flags={"txt2img": True},
                         randomizer_metadata={"enabled": False}, pack_row_index=0, matrix_slot_values={})
    assert len(builder.build_jobs([entry])[0].lora_tags) == 3


def test_one_evidence_context_serves_every_matrix_variant_and_lora(tmp_path: Path) -> None:
    calls: list[str] = []
    records = build(tmp_path, KLEIN, matrix=MATRIX, resolver=evidence(KLEIN_TABLE, calls))
    assert len(records) == 2
    assert sorted(calls) == ["lora_bad", "lora_extra", "lora_ok"]  # each distinct name once, not per variant or per use


def test_the_default_evidence_path_never_refreshes_scans_or_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Any] = []

    class FakeRegistry:
        webui_root = Path("fake-root")

        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.snapshot_calls = 0
            created.append(self)

        def cached_snapshot(self) -> Any:
            self.snapshot_calls += 1
            return SimpleNamespace(records_for=lambda _kind: [])

        def refresh(self, **_k: Any) -> Any:
            raise AssertionError("PromptPack compilation must never refresh/scan/hash the asset registry")

    monkeypatch.setattr("src.assets.AssetRegistry", FakeRegistry)
    config = _Config(tmp_path, model=KLEIN)
    write_pack(tmp_path, matrix=MATRIX)
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config, job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config.packs_dir,
    )
    entry = PackJobEntry(pack_id="adapt-pack", pack_name="p", config_snapshot={}, stage_flags={"txt2img": True},
                         randomizer_metadata={"enabled": False}, pack_row_index=0, matrix_slot_values={})
    records = builder.build_jobs([entry])

    assert len(records) == 2 and len(created) == 1  # one registry for the whole build
    assert created[0].snapshot_calls == 3  # one cached-snapshot read per distinct LoRA name, none per variant
    assert all(len(r.lora_tags) == 3 for r in records)  # no evidence -> preserved, never guessed away


# --- dialect safety -------------------------------------------------------------------------------------------------------------


def test_dialect_rules_are_conservative_and_only_the_accepted_ones_apply_automatically(tmp_path: Path) -> None:
    text = (
        "(red dress:1.2) (ratio: 2) (ratio:2) (at dusk) waves break on rocks BREAK end "
        "masterpiece, best quality, ultra detailed [[env]] <lora:inline:0.5>"
    )
    record = build(tmp_path, KLEIN, slot={**SLOT, "text": text, "loras": []}, matrix=MATRIX)[0]
    positive = record.positive_prompt
    assert "red dress" in positive and "(red dress:1.2)" not in positive
    assert "(ratio: 2)" in positive and "(ratio:2)" in positive and "(at dusk)" in positive
    assert "waves break on rocks\n\nend" in positive
    assert "masterpiece, best quality, ultra detailed" in positive  # quality boilerplate is advisory, never auto-deleted
    assert "forest" in positive and "[[env]]" not in positive  # Matrix expanded normally
    assert "<lora:inline:0.5>" in positive  # manually typed inline tokens are left to backend validation


def test_matrix_markers_survive_until_normal_substitution_and_each_variant_is_adapted_on_its_own(tmp_path: Path) -> None:
    slot = {**SLOT, "text": "([[env]]:1.3) a harbor BREAK [[env]] light", "loras": []}
    records = build(tmp_path, KLEIN, slot=slot, matrix=MATRIX)
    assert [r.provenance.matrix_slot_values["env"] for r in records] == ["forest", "castle"]
    assert [r.positive_prompt for r in records] == [
        "forest a harbor\n\nforest light".replace("forest a harbor", "forest a harbor"),
        "castle a harbor\n\ncastle light",
    ]
    assert all(manifest(r)["adaptable"] for r in records)


# --- immutable NJR / manifest ----------------------------------------------------------------------------------------------------


def test_the_manifest_is_frozen_content_free_ordered_and_survives_serialization(tmp_path: Path) -> None:
    actors = [{"lora_name": "actor_secret", "weight": 0.9, "trigger_phrase": "secret-trigger"}]
    record = build(tmp_path, KLEIN, table={**KLEIN_TABLE, "actor_secret": S.INCOMPATIBLE}, actors=actors)[0]
    data = manifest(record)

    assert data["ruleset_version"] == pa.ADAPTATION_RULESET_VERSION and data["mode"] == "compile"
    assert data["policy_id"] == "flux2_klein_4b_fp8" and data["profile_ref"] == {"id": "flux2_klein_4b_fp8", "version": 2}
    assert data["evidence"] == "exact_profile" and data["prompt_dialect"] == "natural_language"
    assert [op["code"] for op in data["operations"]][:2] == [pa.OP_WEIGHTED_FLATTENED, pa.OP_BREAK_NORMALIZED]
    blob = json.dumps(data)
    for forbidden in ("lighthouse", "red dress", "blurry", "watermark", "lora_bad", "lora_ok", "lora_extra", "actor_secret",
                      "secret-trigger", "pos_embed", "neg_embed", "config negative"):
        assert forbidden not in blob, forbidden

    restored = NormalizedJobRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert plain(restored.provenance.metadata["prompt_adaptation"]) == data
    assert restored.positive_prompt == record.positive_prompt


def test_building_target_specific_njrs_never_mutates_the_authored_pack(tmp_path: Path) -> None:
    path = write_pack(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    document = copy.deepcopy(load_prompt_pack_document(path))

    klein = build(tmp_path, KLEIN, table=KLEIN_TABLE)[0]
    sdxl = build(tmp_path, SDXL)[0]
    unknown = build(tmp_path, MYSTERY)[0]

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before and load_prompt_pack_document(path) == document
    assert klein.positive_prompt != sdxl.positive_prompt and "blurry" in sdxl.negative_prompt and klein.negative_prompt == ""
    assert unknown.positive_prompt == sdxl.positive_prompt  # the unevidenced target keeps today's generic behavior


# --- unknown target -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", [MYSTERY, "never-seen.safetensors"])
def test_unknown_and_conflicting_targets_are_not_adapted_and_not_guessed(tmp_path: Path, model: str) -> None:
    record = build(tmp_path, model, table=KLEIN_TABLE)[0]
    data = manifest(record)

    assert data["adaptable"] is False and data["changed"] is False and data["reason"] == pa.OP_TARGET_UNVERIFIED
    assert data["complete"] is False and data["family"] == "unknown" and data["profile_ref"] is None
    assert codes(record) == [pa.OP_TARGET_UNVERIFIED]
    assert "(red dress:1.2)" in record.positive_prompt and "BREAK" in record.positive_prompt  # authored semantics untouched
    assert "blurry" in record.negative_prompt and record.provenance.positive_embeddings and record.provenance.negative_embeddings
    assert [t.name for t in record.lora_tags] == ["lora_bad", "lora_ok", "lora_extra"]
    assert "model_profile" not in record.backend_options["image"]


# --- replay -----------------------------------------------------------------------------------------------------------------------------


def test_replay_never_reinterprets_and_a_newer_ruleset_cannot_change_an_existing_njr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = build(tmp_path, KLEIN, table=KLEIN_TABLE)[0]
    frozen_manifest = manifest(record)

    def forbidden(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("replay must not re-run adaptation or reopen the PromptPack")

    monkeypatch.setattr(pa, "adapt_structured_prompt", forbidden)
    monkeypatch.setattr("src.pipeline.resolution_layer.adapt_structured_prompt", forbidden)
    monkeypatch.setattr(PromptPackNormalizedJobBuilder, "build_jobs", forbidden)
    monkeypatch.setattr(PromptPackNormalizedJobBuilder, "_load_pack_rows", forbidden)
    monkeypatch.setattr(pa, "ADAPTATION_RULESET_VERSION", "999.0")
    monkeypatch.setattr(pa, "_flatten_weighted_attention", forbidden)

    replayed = compile_replay_intent(ReplayIntent(record), id_fn=lambda: "replay-1")

    assert replayed.job_id == "replay-1" and replayed.job_id != record.job_id
    assert replayed.positive_prompt == record.positive_prompt and replayed.negative_prompt == record.negative_prompt
    assert [(t.name, t.weight) for t in replayed.lora_tags] == [(t.name, t.weight) for t in record.lora_tags]
    assert plain(replayed.provenance.metadata["prompt_adaptation"]) == frozen_manifest
    assert frozen_manifest["ruleset_version"] != "999.0"
    assert replayed.backend_options == record.backend_options  # the persisted profile/version stays authoritative


# --- one rule authority -----------------------------------------------------------------------------------------------------------


def test_adaptation_rules_live_only_in_the_engine_not_in_the_builder_or_resolver() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "pipeline"
    for name in ("prompt_pack_job_builder.py", "resolution_layer.py", "compile_evidence.py"):
        text = (root / name).read_text(encoding="utf-8")
        for forbidden in ("BREAK", "flatten", "WEIGHTED_ATTENTION", "NON_PROSE", "INCOMPATIBLE", "klein"):
            assert forbidden not in text.replace("klein_selected", "").replace("forge_klein", ""), (name, forbidden)
    assert "adapt_structured_prompt" in (root / "resolution_layer.py").read_text(encoding="utf-8")
