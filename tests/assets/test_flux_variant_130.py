"""PR-IMG-FLUX-130: FLUX layout classes from header-only evidence (safetensors tables and GGUF tensor tables).

Nothing here loads a weight: GGUF fixtures are bounded headers with no tensor data, safetensors evidence is a tensor table
handed straight to the classifier. A variant is a layout class, never an identity.
"""

from __future__ import annotations

import struct

import pytest

from src.assets import AssetRegistry, CompatibilityStatus, EvidenceConfidence, ModelFamily
from src.assets.checkpoint_structure import STRUCTURE_CONTRACT, checkpoint_header_evidence
from src.assets.component_evidence import (
    ARCH_FLUX2_DIT,
    ARCH_FLUX_DIT,
    ARCH_FLUX_GGUF_UNREAD,
    ARCH_QWEN3_VL,
    ARCH_UNRECOGNIZED_DIT,
    ROLE_BUNDLED,
    ROLE_TEXT_ENCODER,
    ROLE_TRANSFORMER,
    classify_tensor_table,
    inspect_component_file,
)
from src.assets.flux_variant import (
    ARCHITECTURE_IDS,
    VARIANT_FLUX1_DEV,
    VARIANT_FLUX1_SCHNELL,
    VARIANT_FLUX2_KLEIN_4B,
    VARIANT_FLUX2_KLEIN_9B,
    VARIANT_FLUX_UNRECOGNIZED,
    FluxVariant,
    classify_flux_variant,
    variant_from_architecture,
)
from src.assets.gguf import MAX_TENSOR_DIMS, inspect_gguf
from tests.assets.checkpoint_fixtures import tensor_checkpoint
from tests.assets.flux_fixtures_130 import (
    FTYPE_Q6_K,
    FTYPE_Q8_0,
    GGML_Q6_K,
    GGML_Q8_0,
    dtypes_of,
    flux1_table,
    fp8_scaled,
    klein_table,
    qwen3_vl_table,
    unrecognized_dit_table,
    write_gguf,
)


def _variant(table, dtype="BF16"):
    return classify_flux_variant(classify_tensor_table(table, dtypes_of(table, dtype)))


# ------------------------------------------------------------------------------------------- GGUF tensor table


def test_gguf_tensor_table_is_read_in_safetensors_order_without_tensor_data(tmp_path):
    path = write_gguf(tmp_path / "flux1-dev-Q4_K_S.gguf", flux1_table())
    evidence = inspect_gguf(path)
    assert evidence.parsed and evidence.tensor_table_error is None
    assert evidence.quantization == "Q4_K_S" and evidence.architecture == "flux"
    assert evidence.tensor_shapes["img_in.weight"] == [3072, 64]  # stored [64, 3072] in the file
    assert evidence.tensor_types["img_in.weight"] == "Q4_K"
    assert len(evidence.tensor_shapes) == evidence.tensor_count


def test_a_truncated_or_malformed_tensor_table_keeps_container_facts_and_guesses_nothing(tmp_path):
    path = write_gguf(tmp_path / "cut.gguf", flux1_table())
    path.write_bytes(path.read_bytes()[:-40])
    evidence = inspect_gguf(path)
    assert evidence.parsed and evidence.quantization == "Q4_K_S"
    assert evidence.tensor_shapes == {} and evidence.tensor_table_error
    component = inspect_component_file(path)
    assert component.architecture == ARCH_FLUX_GGUF_UNREAD and component.role == ROLE_TRANSFORMER
    assert component.dependency_bearing
    variant = classify_flux_variant(component)
    assert variant == FluxVariant(VARIANT_FLUX_UNRECOGNIZED, False, "gguf", "Q4_K_S")


def test_too_many_tensor_dims_is_a_table_error(tmp_path):
    def string(text):
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw

    info = (
        string("img_in.weight")
        + struct.pack("<I", MAX_TENSOR_DIMS + 1)
        + struct.pack("<Q", 1) * (MAX_TENSOR_DIMS + 1)
    )
    data = b"GGUF" + struct.pack("<IQQ", 3, 1, 0) + info + struct.pack("<IQ", 0, 0)
    path = tmp_path / "bad.gguf"
    path.write_bytes(data)
    evidence = inspect_gguf(path)
    assert evidence.parsed and evidence.tensor_table_error and not evidence.tensor_shapes


def test_a_non_flux_gguf_without_a_recognised_table_is_not_a_flux_transformer(tmp_path):
    path = write_gguf(
        tmp_path / "llm.gguf", {"token_embd.weight": [32000, 4096]}, architecture="llama"
    )
    component = inspect_component_file(path)
    assert component.architecture == "unrecognized" and classify_flux_variant(component) is None


# ------------------------------------------------------------------------------------------- variant taxonomy


@pytest.mark.parametrize(
    "table,variant",
    [
        (flux1_table(), VARIANT_FLUX1_DEV),
        (flux1_table(guidance=False), VARIANT_FLUX1_SCHNELL),
        (flux1_table(prefix="model.diffusion_model."), VARIANT_FLUX1_DEV),
        (klein_table("4b"), VARIANT_FLUX2_KLEIN_4B),
        (klein_table("9b"), VARIANT_FLUX2_KLEIN_9B),
        (flux1_table(doubles=18), VARIANT_FLUX_UNRECOGNIZED),
        (flux1_table(hidden=2048), VARIANT_FLUX_UNRECOGNIZED),
    ],
)
def test_each_layout_class_is_recognised_from_safetensors_structure(table, variant):
    found = _variant(table)
    assert found is not None and found.variant == variant
    assert not found.bundled and found.container == "safetensors" and found.precision == "bf16"
    assert found.identity_pinned is False and found.label.endswith("identity not pinned")


def test_the_same_layouts_are_recognised_from_a_gguf_tensor_table(tmp_path):
    cases = {
        "flux1-dev-Q4_K_S.gguf": (flux1_table(), {}, VARIANT_FLUX1_DEV, "Q4_K_S"),
        "flux1-schnell-Q6_K.gguf": (
            flux1_table(guidance=False),
            {"tensor_type": GGML_Q6_K, "file_type": FTYPE_Q6_K},
            VARIANT_FLUX1_SCHNELL,
            "Q6_K",
        ),
        "flux-2-klein-base-9b-Q8_0.gguf": (
            klein_table("9b"),
            {"tensor_type": GGML_Q8_0, "file_type": FTYPE_Q8_0},
            VARIANT_FLUX2_KLEIN_9B,
            "Q8_0",
        ),
    }
    for name, (table, kwargs, variant, precision) in cases.items():
        found = classify_flux_variant(
            inspect_component_file(write_gguf(tmp_path / name, table, **kwargs))
        )
        assert found == FluxVariant(variant, False, "gguf", precision), name
        assert f"GGUF {precision}" in found.label


def test_fp8_scaled_precision_and_the_bundled_form_are_orthogonal_facts():
    shapes, dtypes = fp8_scaled(klein_table("9b"))
    found = classify_flux_variant(classify_tensor_table(shapes, dtypes))
    assert (
        found is not None
        and found.variant == VARIANT_FLUX2_KLEIN_9B
        and found.precision == "fp8_scaled"
    )
    assert found.label == "FLUX.2 Klein 9B-class, fp8_scaled, identity not pinned"

    bundled_table = flux1_table(bundled=True)
    evidence = classify_tensor_table(bundled_table, dtypes_of(bundled_table))
    assert evidence.role == ROLE_BUNDLED and not evidence.dependency_bearing
    bundled = classify_flux_variant(evidence)
    assert bundled is not None and bundled.variant == VARIANT_FLUX1_DEV and bundled.bundled
    assert bundled.architecture_id == "flux1_dev_bundled" and "bundled encoders" in bundled.label


def test_flux1_discriminators_are_recorded_as_facts():
    evidence = classify_tensor_table(flux1_table(), dtypes_of(flux1_table()))
    assert evidence.architecture == ARCH_FLUX_DIT
    assert (
        evidence.facts["guidance_embedding"] is True and evidence.facts["vector_input_dim"] == 768
    )
    klein = classify_tensor_table(klein_table("4b"), dtypes_of(klein_table("4b")))
    assert klein.architecture == ARCH_FLUX2_DIT and klein.facts["guidance_embedding"] is False


def test_an_unknown_transformer_only_dit_is_dependency_bearing_but_never_a_flux_variant():
    table = unrecognized_dit_table()
    evidence = classify_tensor_table(table, dtypes_of(table))
    assert evidence.architecture == ARCH_UNRECOGNIZED_DIT and evidence.role == ROLE_TRANSFORMER
    assert evidence.dependency_bearing and evidence.facts["single_blocks"] == 4
    assert classify_flux_variant(evidence) is None


def test_a_vision_language_qwen3_encoder_is_a_text_encoder_with_its_own_architecture():
    table = qwen3_vl_table()
    evidence = classify_tensor_table(table, dtypes_of(table))
    assert evidence.architecture == ARCH_QWEN3_VL and evidence.role == ROLE_TEXT_ENCODER
    assert evidence.facts["language_hidden_size"] == 2560 and "hidden_size" not in evidence.facts
    assert classify_flux_variant(evidence) is None


def test_architecture_ids_round_trip():
    assert variant_from_architecture("flux1_dev") == (VARIANT_FLUX1_DEV, False)
    assert variant_from_architecture("flux2_klein_9b_bundled") == (VARIANT_FLUX2_KLEIN_9B, True)
    for value in (None, "", "sdxl_base", "flux_dit", "flux1_dev_extra"):
        assert variant_from_architecture(value) is None
    assert len(ARCHITECTURE_IDS) == 10


# ------------------------------------------------------------------------------------------- registry structure


def test_header_evidence_contract_two_records_the_flux_layout(tmp_path, monkeypatch):
    assert STRUCTURE_CONTRACT == "checkpoint_structure/2"
    gguf = checkpoint_header_evidence(write_gguf(tmp_path / "flux1-dev-Q4_K_S.gguf", flux1_table()))
    assert gguf["structure"] == {
        "contract": STRUCTURE_CONTRACT,
        "architecture": "flux1_dev",
        "error": None,
    }
    plain = checkpoint_header_evidence(
        write_gguf(tmp_path / "llm.gguf", {"t.weight": [2, 2]}, architecture="llama")
    )
    assert plain["structure"]["architecture"] == "unrecognized" and plain["structure"]["error"]

    # Real-size FLUX safetensors are gigabytes: hand the reader the table a valid tiny file would carry.
    path = tensor_checkpoint(tmp_path / "flux1-dev-fp8.safetensors")
    shapes, dtypes = fp8_scaled(flux1_table())
    monkeypatch.setattr(
        "src.assets.checkpoint_structure.read_tensor_table", lambda _p: (shapes, dtypes, {})
    )
    assert checkpoint_header_evidence(path)["structure"]["architecture"] == "flux1_dev"


def test_registry_records_a_gguf_flux_transformer_as_structural_flux_evidence(tmp_path):
    path = write_gguf(tmp_path / "Stable-diffusion" / "flux1-dev-Q4_K_S.gguf", flux1_table())
    registry = AssetRegistry(tmp_path, cache_path=tmp_path / "cache.json")
    inspection = registry.inspect_checkpoint(path)
    assert inspection.compatibility.status is CompatibilityStatus.RESOLVED
    assert inspection.compatibility.family is ModelFamily.FLUX
    assert inspection.compatibility.checkpoint_architecture == "flux1_dev"
    assert any(
        item.confidence is EvidenceConfidence.STRUCTURAL
        for item in inspection.compatibility.evidence
    )
    assert not registry.cache_path.exists()


def test_a_structural_flux_layout_conflicts_with_an_sdxl_metadata_claim(tmp_path, monkeypatch):
    path = tensor_checkpoint(
        tmp_path / "mislabelled.safetensors", metadata={"ss_base_model_version": "sdxl_base_v1-0"}
    )
    monkeypatch.setattr(
        "src.assets.checkpoint_structure.read_tensor_table",
        lambda _p: (
            flux1_table(),
            dtypes_of(flux1_table()),
            {"ss_base_model_version": "sdxl_base_v1-0"},
        ),
    )
    inspection = AssetRegistry(tmp_path, cache_path=tmp_path / "cache.json").inspect_checkpoint(
        path
    )
    assert inspection.compatibility.status is CompatibilityStatus.CONFLICTING
