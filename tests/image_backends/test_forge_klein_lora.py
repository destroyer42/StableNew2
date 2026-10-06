"""PR-IMG-117: FLUX.2 Klein 4B LoRA compatibility interpretation and v2 admission (pure, hermetic).

Real ``AssetRegistry`` records are built from tiny safetensors fixtures in temporary roots, so the SHA-256 identity
and the preserved header/sidecar metadata are exactly what production sees. No network, WebUI, model or GPU.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

import src.image_backends.forge_klein_lora as lora_module
from src.assets import AssetKind, AssetRegistry
from src.image_backends.forge_klein_lora import (
    KleinLoraStatus,
    RegistryLoraResolver,
    classify_klein_lora,
    evaluate_klein_loras,
    extract_lora_tags,
    find_lora_record,
    is_klein_4b_value,
    is_other_flux_value,
    observe_lora_consumption,
    unavailable_decision,
)


def _write_lora(root: Path, name: str, metadata: dict | None, *, sidecar: dict | None = None) -> Path:
    path = root / "models" / "Lora" / f"{name}.safetensors"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {"w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    if metadata is not None:
        header["__metadata__"] = metadata
    blob = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(blob)) + blob + name.encode()[:4].ljust(4, b"\0"))
    if sidecar is not None:
        path.with_suffix(".civitai.info").write_text(json.dumps(sidecar), encoding="utf-8")
    return path


def _record(tmp_path: Path, name: str, metadata: dict | None, **kwargs):
    path = _write_lora(tmp_path, name, metadata, **kwargs)
    registry = AssetRegistry(tmp_path, cache_path=tmp_path / "cache.json")
    snapshot = registry.refresh(kinds={AssetKind.LORA}).snapshot
    record, reason = find_lora_record(snapshot, name)
    assert record is not None, reason
    return record, path


KLEIN = {"ss_base_model_version": "flux2_klein_4b"}


# --- exact evidence tokens ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["flux2_klein_4b", "FLUX2_KLEIN_4B", " flux2_klein_4b ", "black-forest-labs/FLUX.2-klein-4B",
     "black-forest-labs/FLUX.2-klein-base-4B", "black-forest-labs\\FLUX.2-klein-4B"],
)
def test_exact_klein_4b_values_are_recognized(value: str) -> None:
    assert is_klein_4b_value(value)
    assert not is_other_flux_value(value)


@pytest.mark.parametrize(
    "value",
    ["", "flux", "flux2", "flux2_klein_4b_extra", "xflux2_klein_4b", "my flux2_klein_4b lora", "flux2_klein_4",
     "flux2-klein-4b", "klein", "flux2_klein_9b", "sdxl", "FLUX.1-dev", "flux2_klein_4b,flux2_klein_9b"],
)
def test_no_loose_substring_or_near_miss_is_klein_4b(value: str) -> None:
    assert not is_klein_4b_value(value)


@pytest.mark.parametrize(
    "value", ["flux2_klein_9b", "flux2_klein_base_9b", "black-forest-labs/FLUX.2-dev", "flux1_dev", "flux.1-dev", "flux_1"]
)
def test_explicit_other_flux_variants_are_recognized_but_never_klein_4b(value: str) -> None:
    assert is_other_flux_value(value)
    assert not is_klein_4b_value(value)


# --- classification from real registry records -------------------------------------------------


def test_explicit_embedded_klein_4b_evidence_is_compatible_and_reuses_the_registry_sha(tmp_path) -> None:
    record, path = _record(tmp_path, "klein-style", KLEIN)

    decision = classify_klein_lora("klein-style", record)

    assert decision.status is KleinLoraStatus.COMPATIBLE and decision.runnable
    assert decision.evidence_source == "embedded_metadata:ss_base_model_version"
    assert decision.evidence_raw_value == "flux2_klein_4b"
    assert decision.sha256 == hashlib.sha256(path.read_bytes()).hexdigest() == record.sha256
    assert "\\" not in json.dumps(decision.as_dict()) and str(tmp_path) not in json.dumps(decision.as_dict())


def test_explicit_sidecar_klein_4b_evidence_is_compatible(tmp_path) -> None:
    record, _ = _record(tmp_path, "sidecar-only", None, sidecar={"baseModel": "black-forest-labs/FLUX.2-klein-base-4B"})

    decision = classify_klein_lora("sidecar-only", record)

    assert decision.status is KleinLoraStatus.COMPATIBLE
    assert decision.evidence_source == "sidecar_metadata:baseModel"


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"ss_base_model_version": "sdxl_base_v1-0"}, KleinLoraStatus.INCOMPATIBLE),
        ({"ss_base_model_version": "sd_v1"}, KleinLoraStatus.INCOMPATIBLE),
        ({"ss_base_model_version": "sd_v2"}, KleinLoraStatus.INCOMPATIBLE),
        ({"modelspec.architecture": "stable-diffusion-v3"}, KleinLoraStatus.INCOMPATIBLE),
        ({"ss_base_model_version": "flux2_klein_9b"}, KleinLoraStatus.INCOMPATIBLE),
        ({"ss_base_model_version": "flux2_klein_4b", "modelspec.architecture": "stable-diffusion-xl-v1-base"},
         KleinLoraStatus.CONFLICTING),
        ({"ss_base_model_version": "flux2_klein_4b", "modelspec.base_model_version": "flux2_klein_9b"},
         KleinLoraStatus.CONFLICTING),
        ({"ss_base_model_version": "sdxl_base_v1-0", "modelspec.architecture": "stable-diffusion-v1"},
         KleinLoraStatus.CONFLICTING),
        ({"ss_base_model_version": "flux"}, KleinLoraStatus.UNVERIFIED),
        ({"ss_base_model_version": "Pony"}, KleinLoraStatus.UNVERIFIED),
        ({"software": "ai-toolkit"}, KleinLoraStatus.UNVERIFIED),
        (None, KleinLoraStatus.UNVERIFIED),
    ],
)
def test_classification_table(tmp_path, metadata, expected) -> None:
    record, _ = _record(tmp_path, "adapter", metadata)

    decision = classify_klein_lora("adapter", record)

    assert decision.status is expected
    assert decision.runnable is (expected is KleinLoraStatus.COMPATIBLE)


def test_klein_header_with_a_contradicting_sidecar_is_conflicting(tmp_path) -> None:
    record, _ = _record(tmp_path, "mixed", KLEIN, sidecar={"baseModel": "SDXL 1.0"})

    assert classify_klein_lora("mixed", record).status is KleinLoraStatus.CONFLICTING


def test_a_filename_or_generic_flux_alone_never_proves_klein(tmp_path) -> None:
    for name in ("flux2-klein-4b-lookalike", "flux-style"):
        record, _ = _record(tmp_path, name, None)
        decision = classify_klein_lora(name, record)
        assert decision.status is KleinLoraStatus.UNVERIFIED, name
        assert "cannot verify" in decision.reason


def test_the_decision_never_rewrites_the_asset_metadata(tmp_path) -> None:
    record, path = _record(tmp_path, "untouched", {"software": "x"})
    before = path.read_bytes()

    classify_klein_lora("untouched", record)

    assert path.read_bytes() == before
    assert not path.with_suffix(".civitai.info").exists()


def test_forge_listing_a_name_is_not_compatibility_and_the_module_hashes_nothing() -> None:
    source = Path(lora_module.__file__).read_text(encoding="utf-8")

    assert "hashlib" not in source and "sha256(" not in source.replace("sha256: str", "")  # no second hashing authority
    assert "rglob" not in source and "os.walk" not in source  # no second LoRA scanner


# --- lookup ------------------------------------------------------------------------------------


def test_lookup_is_exact_and_missing_or_ambiguous_names_are_unverified(tmp_path) -> None:
    _write_lora(tmp_path, "alpha", KLEIN)
    sub = tmp_path / "models" / "Lora" / "sub"
    sub.mkdir(parents=True)
    other = _write_lora(tmp_path, "alpha-copy", {"ss_base_model_version": "sdxl_base_v1-0"})
    other.rename(sub / "alpha.safetensors")  # a distinct file also named "alpha" (different bytes)
    resolver = RegistryLoraResolver(AssetRegistry(tmp_path, cache_path=tmp_path / "c.json"))

    assert resolver("alp").status is KleinLoraStatus.UNVERIFIED  # no prefix matching
    assert "not found" in resolver("alp").reason
    ambiguous = resolver("alpha")
    assert ambiguous.status is KleinLoraStatus.UNVERIFIED and "more than one" in ambiguous.reason
    assert resolver("sub/alpha").status is KleinLoraStatus.INCOMPATIBLE  # unambiguous by relative path


def test_resolver_without_a_webui_root_cannot_identify_assets(monkeypatch) -> None:
    monkeypatch.delenv("STABLENEW_WEBUI_ROOT", raising=False)
    registry = AssetRegistry.__new__(AssetRegistry)
    registry.webui_root = None
    decision = RegistryLoraResolver(registry)("anything")

    assert decision.status is KleinLoraStatus.UNVERIFIED and "no local WebUI root" in decision.reason


# --- prompt tags and the v2 contract -----------------------------------------------------------


def test_extract_lora_tags_keeps_malformed_tags_visible() -> None:
    tags, malformed = extract_lora_tags(
        "a <lora:good:0.8> b <LORA:Other Name:1> <lora:noweight> <lora:bad:abc> <lora::1> <lora:nan:nan> <lyco:c:0.5>"
    )

    assert [(t.name, t.weight) for t in tags] == [("good", 0.8), ("Other Name", 1.0), ("c", 0.5)]
    assert malformed == ("<lora:noweight>", "<lora:bad:abc>", "<lora::1>", "<lora:nan:nan>")


def _ok(name: str):
    return lora_module.KleinLoraDecision(name, KleinLoraStatus.COMPATIBLE, "ok", "embedded_metadata:ss_base_model_version", "flux2_klein_4b", "ab" * 32)


def test_exactly_one_compatible_lora_is_admitted() -> None:
    problems, decisions, tags = evaluate_klein_loras(max_loras=1, prompt="x <lora:a:0.8>", resolver=_ok)

    assert problems == [] and [d.name for d in decisions] == ["a"] and tags[0].weight == 0.8


def test_no_lora_is_admitted_without_consulting_the_resolver() -> None:
    def boom(_name: str):
        raise AssertionError("not consulted")

    assert evaluate_klein_loras(max_loras=1, prompt="plain", resolver=boom)[0] == []


def test_two_loras_are_rejected_not_silently_dropped() -> None:
    problems, _, tags = evaluate_klein_loras(max_loras=1, prompt="<lora:a:0.8> <lora:b:0.5>", resolver=_ok)

    assert len(tags) == 2 and any("2 LoRAs" in p and "at most 1" in p for p in problems)


@pytest.mark.parametrize("weight", ["0", "-0.5", "2.5", "inf", "nan", "1e9"])
def test_out_of_range_or_non_finite_weights_are_rejected(weight: str) -> None:
    problems, _, _ = evaluate_klein_loras(max_loras=1, prompt=f"<lora:a:{weight}>", resolver=_ok)

    assert problems, weight


def test_unverified_incompatible_and_unavailable_adapters_are_rejected_with_an_explanation() -> None:
    for status in (KleinLoraStatus.UNVERIFIED, KleinLoraStatus.INCOMPATIBLE, KleinLoraStatus.CONFLICTING):
        problems, _, _ = evaluate_klein_loras(
            max_loras=1,
            prompt="<lora:a:0.8>",
            resolver=lambda n, status=status: lora_module.KleinLoraDecision(n, status, "why"),
        )
        assert any("not verified for FLUX.2 Klein 4B" in p and status.value in p for p in problems)
    problems, _, _ = evaluate_klein_loras(max_loras=1, prompt="<lora:a:0.8>", resolver=None)
    assert any("not verified" in p for p in problems)


def test_a_declared_lora_missing_from_the_prompt_and_strength_overrides_are_rejected() -> None:
    problems, _, _ = evaluate_klein_loras(
        max_loras=1, prompt="plain", declared=(("a", 0.8),), lora_strength_overrides=True, resolver=_ok
    )

    assert any("declared by the job but is not in the prompt" in p for p in problems)
    assert any("lora_strengths" in p for p in problems)
    assert evaluate_klein_loras(max_loras=1, prompt="<lora:a:0.8>", declared=(("A", 0.8),), resolver=_ok)[0] == []


def test_unavailable_decision_is_never_runnable() -> None:
    assert not unavailable_decision("a", "r").runnable


# --- consumption observation -------------------------------------------------------------------

LOADED = "2026-10-06 08:01:02,003 - lora - INFO - [LORA] Loaded flux2-klein-4b-lora-old-gods.safetensors for Flux2-UNet with 160 keys at weight 0.8 (skipped 0 keys) with on_the_fly = False"
MISMATCH = "2026-10-06 08:01:02,003 - lora - WARNING - [LORA] LoRA mismatch for Flux2: flux2-klein-4b-lora-old-gods.safetensors"


def test_consumption_is_true_only_on_forges_loaded_line_for_that_adapter() -> None:
    seen = observe_lora_consumption(["noise", LOADED], "flux2-klein-4b-lora-old-gods")
    assert seen["consumed"] is True and seen["keys"] == 160 and seen["weight"] == 0.8
    assert observe_lora_consumption([LOADED], "some-other-lora")["consumed"] is None
    assert observe_lora_consumption([], "x")["consumed"] is None


def test_a_mismatch_line_means_the_adapter_was_not_applied() -> None:
    seen = observe_lora_consumption([MISMATCH], "flux2-klein-4b-lora-old-gods")

    assert seen["consumed"] is False and "mismatch" in seen["line"].lower()
