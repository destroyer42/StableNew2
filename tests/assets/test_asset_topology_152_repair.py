"""PR #79 focused repair: quantization-scale evidence, sharded component candidates, recorded-verdict attribution."""

from __future__ import annotations

import json

import pytest

from src.assets.bundles import MISSING, build_bundles
from src.assets.component_evidence import classify_tensor_table, precision_facts
from src.assets.inventory_report import build_report
from src.assets.registry import AssetKind
from tests.assets import topology_fixtures_152 as fx
from tests.assets.test_asset_topology_152 import (  # noqa: F401  (fixtures and helpers shared with the A1-A17 module)
    _not_working_tree,
    _recorded,
    bundle_for,
    leaf,
    registry,
    relation,
)


@pytest.fixture
def webui(tmp_path):
    return fx.webui_tree(tmp_path / "webui")


# --------------------------------------------------------------------------------------------------- A


def _precision(tensors):
    return precision_facts(
        {k: v[1] for k, v in tensors.items()}, {k: v[0] for k, v in tensors.items()}
    )


def test_a_rmsnorm_scale_parameters_are_not_quantization_scales():
    plain = _precision(fx.flux2_native())  # BF16 with ordinary "norm.scale" parameters
    assert plain["scale_key_count"] == 0 and plain["precision_layout"] == "plain"
    cast = {f"blocks.{i}.linear.weight": ("F8_E4M3", [4, 4]) for i in range(3)}
    cast.update({f"blocks.{i}.norm.scale": ("F32", [4]) for i in range(3)})
    facts = _precision(cast)
    assert facts["scale_key_count"] == 0
    assert (
        facts["precision_layout"] == "unknown"
    )  # FP8 without quantization scales is never "mixed_scaled"
    assert facts["dtype_histogram"] == {
        "F32": 3,
        "F8_E4M3": 3,
    }  # histograms and byte shares are preserved
    assert facts["dtype_bytes"] == {"F32": 48, "F8_E4M3": 48}


@pytest.mark.parametrize(
    "key", ["weight_scale", "scale_weight", "input_scale", "weight_scale_2", "comfy_quant"]
)
def test_a_genuine_quantization_scales_are_recognised(key):
    tensors = {
        "blocks.0.linear.weight": ("F8_E4M3", [4, 4]),
        "blocks.0.norm.scale": ("F32", [4]),
        f"blocks.0.linear.{key}": ("F32", [1]),
    }
    facts = _precision(tensors)
    assert facts["scale_key_count"] == 1 and facts["precision_layout"] == "mixed_scaled"


def test_a_ambiguous_u8_layout_without_scales_stays_unknown():
    assert (
        _precision({"a.weight": ("U8", [4, 4]), "a.norm.scale": ("F32", [4])})["precision_layout"]
        == "unknown"
    )


def test_a_the_qwen3_quantized_flag_ignores_norm_scale():
    tensors = fx.qwen3_encoder(4096)
    tensors["model.layers.0.input_layernorm.scale"] = ("BF16", [4])
    evidence = classify_tensor_table(
        {k: v[1] for k, v in tensors.items()}, {k: v[0] for k, v in tensors.items()}
    )
    assert evidence.facts["quantized"] is False


# --------------------------------------------------------------------------------------------------- B


def _klein(webui):
    fx.safetensors(webui / "models/Stable-diffusion/klein.safetensors", fx.flux2_native(4096))


def test_b_indexed_shards_of_an_encoder_are_inventoried_but_never_candidates(webui, tmp_path):
    _klein(webui)
    directory = webui / "models/text_encoder"
    tensors = fx.qwen3_encoder(4096)
    names = list(tensors)
    half = len(names) // 2
    first_name, second_name = "model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"
    # shard 1 deliberately carries the tensors that would classify as a whole Qwen3 encoder on their own
    fx.safetensors(
        directory / first_name,
        {k: tensors[k] for k in names[:half]}
        | {"model.embed_tokens.weight": tensors["model.embed_tokens.weight"]},
    )
    fx.safetensors(
        directory / second_name,
        {k: tensors[k] for k in names[half:] if k != "model.embed_tokens.weight"},
    )
    weight_map = dict.fromkeys(names[:half], first_name) | {"model.embed_tokens.weight": first_name}
    weight_map |= {k: second_name for k in names[half:] if k != "model.embed_tokens.weight"}
    (directory / "model.safetensors.index.json").write_text(json.dumps({"weight_map": weight_map}))

    scan = registry(webui, tmp_path).observe()

    assert {i.name for i in scan.files if i.kind == "text_encoder"} == {
        first_name,
        second_name,
    }  # still observed
    rel = relation(bundle_for(build_bundles(scan), "klein.safetensors"), "text_encoder")
    assert rel.candidates == () and rel.outcome == MISSING


def test_b_index_less_shard_named_encoder_and_vae_files_are_not_candidates(webui, tmp_path):
    _klein(webui)
    fx.safetensors(
        webui / "models/text_encoder/model-00001-of-00002.safetensors", fx.qwen3_encoder(4096)
    )
    fx.safetensors(webui / "models/VAE/vae-00001-of-00002.safetensors", fx.vae(32, batch_norm=True))
    fx.safetensors(webui / "models/text_encoder/whole.safetensors", fx.qwen3_encoder(4096))

    scan = registry(webui, tmp_path).observe()

    assert (
        len([i for i in scan.files if i.kind in ("text_encoder", "vae")]) == 3
    )  # preserved in the inventory
    bundle = bundle_for(build_bundles(scan), "klein.safetensors")
    assert [c.path.rsplit("/", 1)[-1] for c in relation(bundle, "text_encoder").candidates] == [
        "whole.safetensors"
    ]
    vae = relation(bundle, "vae")
    assert vae.candidates == () and vae.outcome == MISSING


# --------------------------------------------------------------------------------------------------- C


def _verified(webui, tmp_path):
    _not_working_tree(webui)
    # the sibling is genuinely different bytes (identical bytes would, correctly, be the same verified file)
    fx.safetensors(
        webui / "models/Stable-diffusion/Not Working/flux2Klein_9bBase.safetensors",
        fx.flux2_native(),
        {"v": "other"},
    )
    reg = registry(webui, tmp_path)
    reg.refresh(kinds=[AssetKind.CHECKPOINT])
    return reg


def _outcome(report, name):
    return next(
        item["recorded_outcome"]
        for item in report["priority_candidates"]["items"]
        if leaf(item["bundle"]) == name
    )


EXACT = "flux-2-klein-base-9b.safetensors"


def test_c_a_complete_verified_sha256_match_attributes_the_recorded_verdict(webui, tmp_path):
    reg = _verified(webui, tmp_path)
    report = build_report(reg.observe(), recorded_outcomes=_recorded(webui))
    exact = _outcome(report, EXACT)
    assert exact["applies"] is True and exact["match_basis"] == "sha256_verified"
    assert exact["verdict"] == "NO_GO_RESOURCE_RISK"
    readiness = next(b for b in report["bundles"]["items"] if b["bundle_id"].endswith(":" + EXACT))[
        "readiness"
    ]
    assert readiness["hardware_qualified"] == "recorded_no_go_resource_risk"
    sibling = next(
        item["recorded_outcome"]
        for item in report["not_working_cases"]["items"]
        if leaf(item["bundle"]) == "flux2Klein_9bBase.safetensors"
    )
    assert sibling["applies"] is False  # a different file: the verdict is not transferred


def test_c_a_digest_prefix_and_suffix_are_not_identity(webui, tmp_path):
    reg = _verified(webui, tmp_path)
    records = _recorded(webui)
    digest = records[0]["applies_to"].pop("sha256")
    records[0]["applies_to"]["sha256_prefix"] = digest[:8]
    records[0]["applies_to"]["sha256_suffix"] = digest[-4:]
    outcome = _outcome(build_report(reg.observe(), recorded_outcomes=records), EXACT)
    assert outcome["applies"] is False and outcome["relation"] == "name_and_size_similar_unverified"


def test_c_verified_bytes_that_differ_are_not_the_recorded_candidate(webui, tmp_path):
    reg = _verified(webui, tmp_path)
    records = _recorded(webui)
    records[0]["applies_to"]["sha256"] = "0" * 64
    outcome = _outcome(build_report(reg.observe(), recorded_outcomes=records), EXACT)
    assert outcome["applies"] is False and outcome["relation"] == "verified_bytes_differ"


def test_c_every_record_is_examined_and_the_exact_one_wins_in_any_order(webui, tmp_path):
    reg = _verified(webui, tmp_path)
    exact = _recorded(webui)[0]
    decoy = json.loads(json.dumps(exact))
    decoy["id"] = "A-DECOY"
    decoy["applies_to"]["sha256"] = "f" * 64
    for ordering in ([decoy, exact], [exact, decoy]):
        outcome = _outcome(build_report(reg.observe(), recorded_outcomes=ordering), EXACT)
        assert outcome["applies"] is True and outcome["record"] == "PR-IMG-MODELS-151"
