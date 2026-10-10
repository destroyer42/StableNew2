"""PR-IMG-MODELS-153: Z-Image-Turbo FP8-scaled feasibility evaluator. Synthetic headers, fakes and static checks only."""

from __future__ import annotations

import ast
import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from src.assets.component_evidence import inspect_component_file
from tests.assets import topology_fixtures_152 as fx
from tools.qualification.img151.feasibility import GIB, HostTelemetry
from tools.qualification.img153 import feasibility as f

DIGEST = {"transformer": "a" * 64, "text_encoder": "b" * 64, "vae": "c" * 64}


def zimage_dit(*, dim=3840, scales="marker", noise_refiner=True, extra=None):
    """A tiny synthetic Z-Image FP8-scaled header (sparse payload); ``scales`` selects the convention under test."""

    t = {
        "cap_embedder.0.weight": ("F32", [2560]),
        "cap_embedder.1.weight": ("F8_E4M3", [dim, 2560]),
        "cap_embedder.1.bias": ("F32", [dim]),
        "layers.0.attention.qkv.weight": ("F8_E4M3", [8, 8]),
        "layers.0.attention.q_norm.weight": ("F32", [128]),
        "layers.0.attention_norm1.weight": (
            "F32",
            [dim],
        ),  # ordinary norm weights are not quantization evidence
        "layers.0.adaLN_modulation.0.weight": ("F8_E4M3", [8, 8]),
        "x_embedder.weight": ("F8_E4M3", [dim, 64]),
    }
    if noise_refiner:
        t["noise_refiner.0.attention.k_norm.weight"] = ("F32", [128])
    if scales in ("marker", "orphan_scale"):
        t["scaled_fp8"] = ("F8_E4M3", [2])
    if scales in ("marker", "missing_one", "orphan_scale"):
        for layer in (
            "cap_embedder.1",
            "layers.0.attention.qkv",
            "layers.0.adaLN_modulation.0",
            "x_embedder",
        ):
            if scales == "missing_one" and layer == "x_embedder":
                continue
            t[f"{layer}.scale_weight"] = ("F32", [1])
    if scales == "orphan_scale":
        t["layers.9.attention.qkv.scale_weight"] = ("F32", [1])
    if scales == "comfy_quant":
        for layer in (
            "cap_embedder.1",
            "layers.0.attention.qkv",
            "layers.0.adaLN_modulation.0",
            "x_embedder",
        ):
            t[f"{layer}.weight_scale"] = ("F32", [1])
            t[f"{layer}.comfy_quant"] = ("U8", [20])
    if scales == "e5m2_mixed":
        t["scaled_fp8"] = ("F8_E4M3", [2])
        t["layers.0.attention.out.weight"] = ("U8", [4, 4])
        for layer in (
            "cap_embedder.1",
            "layers.0.attention.qkv",
            "layers.0.adaLN_modulation.0",
            "x_embedder",
        ):
            t[f"{layer}.scale_weight"] = ("F32", [1])
    t.update(extra or {})
    return t


@pytest.fixture
def tree(tmp_path: Path):
    """A synthetic WebUI tree holding the exact candidate; returns (root, writers)."""

    root = tmp_path / "webui"
    models = root / "models"
    fx.safetensors(
        models / "Stable-diffusion" / f.TRANSFORMER_NAME,
        zimage_dit(),
        {"model_type": "z-image-turbo"},
    )
    fx.safetensors(models / "text_encoder" / f.ENCODER_NAME, fx.qwen3_encoder(2560))
    fx.safetensors(models / "VAE" / f.VAE_NAME, fx.vae(16))
    return root


def candidate(root: Path, *, hashed=True) -> f.CandidateSet:
    found = f.collect_candidate(root)
    if not hashed:
        return found
    return dataclasses.replace(
        found,
        transformer=dataclasses.replace(found.transformer, sha256=DIGEST["transformer"]),
        text_encoder=dataclasses.replace(found.text_encoder, sha256=DIGEST["text_encoder"]),
        vae=dataclasses.replace(found.vae, sha256=DIGEST["vae"]),
    )


GOOD_PIN = f.PinEvidence(
    marker_revision=f.PINNED_REVISION,
    marker_status="verified",
    source_scanned=True,
    defines_zimage=True,
    zimage_dim=3840,
    zimage_dtypes=("bfloat16", "float32"),
    zimage_memory_factor=2.8,
    zimage_clip_target="qwen3_4b.transformer",
    loader_has_zimage_transformer=True,
    loader_has_qwen3_4b=True,
    detects_via_cap_embedder=True,
    converts_scaled_fp8=True,
    supports_fp8_e4m3_layer=True,
    preset={"steps": "9", "cfg": "1.0"},
)
GOOD_TELEMETRY = HostTelemetry(
    total_ram_bytes=34 * GIB,
    available_ram_bytes=14 * GIB,
    commit_headroom_bytes=40 * GIB,
    pagefile_allocated_bytes=18 * GIB,
    vram_total_bytes=12 * GIB,
    vram_used_bytes=2 * GIB,
    vram_free_bytes=10 * GIB,
    shared_gpu_memory_bytes=0,
    forge_endpoint_listening=False,
)


def verdict(cand, pin=GOOD_PIN, telemetry=GOOD_TELEMETRY):
    return f.evaluate(cand, pin, telemetry)


def real_sizes(cand):
    """Give the tiny synthetic files the real candidate's sizes so resource math matches the installed stack."""

    sizes = {"transformer": 6_158_115_074, "text_encoder": 8_044_982_048, "vae": 335_304_388}
    return dataclasses.replace(
        cand,
        transformer=dataclasses.replace(cand.transformer, size_bytes=sizes["transformer"]),
        text_encoder=dataclasses.replace(cand.text_encoder, size_bytes=sizes["text_encoder"]),
        vae=dataclasses.replace(cand.vae, size_bytes=sizes["vae"]),
    )


# ------------------------------------------------------------------------------------------------ happy path


def test_exact_stack_with_verified_bytes_and_pin_support_is_eligible_with_stated_gaps(tree):
    report = verdict(real_sizes(candidate(tree)))
    assert report.verdict == f.ELIGIBLE
    assert "FP8_SCALE_CONVENTION_COMFY_SCALED_FP8" in report.reason_codes
    assert "PIN_SUPPORTS_ZIMAGE_SOFTWARE" in report.reason_codes
    assert any(
        "provenance" in gap for gap in report.evidence_gaps
    )  # official provenance is a gap, not a blocker
    assert "OFFICIAL_PROVENANCE_UNVERIFIED" in report.reason_codes
    assert (
        report.candidate["transformer_scales"]["matched_scales"] == 4
        and report.candidate["forge_detectable"] is True
    )
    assert "stop" in report.next_recommendation.lower()


def test_an_encoder_with_the_img115_digest_is_noted_as_a_same_bytes_baseline(tree):
    cand = candidate(tree)
    cand = dataclasses.replace(
        cand, text_encoder=dataclasses.replace(cand.text_encoder, sha256=f.IMG115_ENCODER_SHA256)
    )
    assert "ENCODER_BYTES_MATCH_IMG115_QUALIFIED_ENCODER" in verdict(real_sizes(cand)).reason_codes


# ------------------------------------------------------------------------------------------------ dependency mismatches


def _swap(tree, relative, tensors):
    fx.safetensors(tree / "models" / relative, tensors)


@pytest.mark.parametrize(
    ("relative", "tensors", "code"),
    [
        (
            "text_encoder/" + f.ENCODER_NAME,
            fx.qwen3_encoder(4096),
            "ENCODER_NOT_QWEN3_4B",
        ),  # an 8B encoder
        (
            "text_encoder/" + f.ENCODER_NAME,
            fx.qwen3_encoder(2560, quantized=True),
            "ENCODER_QUANTIZED",
        ),
        ("VAE/" + f.VAE_NAME, fx.vae(32, batch_norm=True), "VAE_NOT_FLUX1_AE_16"),  # FLUX.2 VAE
        ("VAE/" + f.VAE_NAME, fx.vae(4), "VAE_NOT_FLUX1_AE_16"),  # SD-class channels
        ("VAE/" + f.VAE_NAME, fx.qwen_image_vae(), "VAE_NOT_FLUX1_AE_16"),
        ("VAE/" + f.VAE_NAME, fx.vae(16, key_format="diffusers"), "VAE_KEY_LAYOUT_NOT_NATIVE"),
    ],
    ids=[
        "encoder_8b",
        "encoder_quantized",
        "vae_flux2",
        "vae_4ch",
        "vae_qwen_image",
        "vae_diffusers_keys",
    ],
)
def test_substituted_components_are_missing_dependencies_never_accepted(
    tree, relative, tensors, code
):
    _swap(tree, relative, tensors)
    report = verdict(real_sizes(candidate(tree)))
    assert report.verdict == f.MISSING_DEPENDENCY and code in report.reason_codes


def test_absent_files_are_missing_and_alternates_are_never_substituted(tree):
    (tree / "models/VAE" / f.VAE_NAME).unlink()
    fx.safetensors(tree / "models/VAE/other_ae.safetensors", fx.vae(16))
    report = verdict(candidate(tree))
    assert report.verdict == f.MISSING_DEPENDENCY and "VAE_FILE_MISSING" in report.reason_codes
    assert "ALTERNATE_COMPONENT_FILES_PRESENT" in report.reason_codes


# ------------------------------------------------------------------------------------------------ scale keys and key layout


def _transformer(tree, **kw):
    fx.safetensors(tree / "models/Stable-diffusion" / f.TRANSFORMER_NAME, zimage_dit(**kw))
    return real_sizes(candidate(tree))


def test_rmsnorm_norm_weights_are_not_scale_evidence_and_missing_scales_are_unknown(tree):
    cand = _transformer(tree, scales="none")
    scales = cand.zimage.scales
    assert (
        scales.convention == "unknown"
        and scales.fp8_without_scale == 4
        and not scales.marker_present
    )
    report = verdict(cand)
    assert (
        report.verdict == f.INCONCLUSIVE and "FP8_SCALE_CONVENTION_UNKNOWN" in report.reason_codes
    )


@pytest.mark.parametrize("scales", ["missing_one", "orphan_scale", "e5m2_mixed"])
def test_partial_orphaned_or_mixed_scale_conventions_are_unknown_not_guessed(tree, scales):
    cand = _transformer(tree, scales=scales)
    assert cand.zimage.scales.convention == "unknown"
    assert verdict(cand).verdict == f.INCONCLUSIVE


def test_per_layer_comfy_quant_is_recognised_as_its_own_convention(tree):
    cand = _transformer(tree, scales="comfy_quant")
    assert cand.zimage.scales.convention == "comfy_quant_per_layer"
    assert verdict(cand).verdict == f.ELIGIBLE


@pytest.mark.parametrize(
    "kw",
    [{"noise_refiner": False}, {"dim": 2304}],
    ids=["no_noise_refiner_key", "lumina2_width"],
)
def test_a_transformer_the_pinned_detector_would_not_classify_as_zimage_is_a_mismatch(tree, kw):
    report = verdict(_transformer(tree, **kw))
    assert (
        report.verdict == f.MISSING_DEPENDENCY
        and "TRANSFORMER_NOT_FORGE_ZIMAGE_LAYOUT" in report.reason_codes
    )


def test_a_non_fp8_transformer_is_not_the_exact_candidate(tree):
    t = {
        k: ("BF16" if v[0] == "F8_E4M3" else v)
        if False
        else (("BF16", v[1]) if v[0] == "F8_E4M3" else v)
        for k, v in zimage_dit(scales="none").items()
    }
    fx.safetensors(tree / "models/Stable-diffusion" / f.TRANSFORMER_NAME, t)
    report = verdict(real_sizes(candidate(tree)))
    assert (
        report.verdict == f.MISSING_DEPENDENCY
        and "TRANSFORMER_NOT_FP8_SCALED" in report.reason_codes
    )


# ------------------------------------------------------------------------------------------------ identity


def test_unverified_byte_identity_blocks_eligibility(tree):
    report = verdict(real_sizes(candidate(tree, hashed=False)))
    assert report.verdict == f.IDENTITY_PENDING
    assert {
        "TRANSFORMER_SHA256_PENDING",
        "TEXT_ENCODER_SHA256_PENDING",
        "VAE_SHA256_PENDING",
    } <= set(report.reason_codes)


# ------------------------------------------------------------------------------------------------ pinned loading


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"defines_zimage": False}, "PIN_LACKS_ZIMAGE_MODEL"),
        ({"loader_has_zimage_transformer": False}, "PIN_LACKS_ZIMAGE_TRANSFORMER_LOADER"),
        ({"loader_has_qwen3_4b": False}, "PIN_LACKS_QWEN3_4B_LOADER"),
        ({"detects_via_cap_embedder": False}, "PIN_LACKS_ZIMAGE_DETECTION"),
        ({"converts_scaled_fp8": False}, "PIN_LACKS_SCALED_FP8_CONVERTER"),
        ({"supports_fp8_e4m3_layer": False}, "PIN_LACKS_FP8_E4M3_LAYER"),
        ({"zimage_dim": 2304}, "PIN_ZIMAGE_DIM_MISMATCH"),
        ({"marker_revision": "deadbeef"}, "PIN_NOT_VERIFIED"),
        ({"marker_status": "incomplete"}, "PIN_NOT_VERIFIED"),
    ],
)
def test_unsupported_pinned_loading_is_a_pin_no_go(tree, change, code):
    report = verdict(real_sizes(candidate(tree)), dataclasses.replace(GOOD_PIN, **change))
    assert report.verdict == f.NO_GO_PINNED_FORGE and code in report.reason_codes


def test_an_unreadable_pinned_source_is_inconclusive_not_a_go(tree):
    report = verdict(
        real_sizes(candidate(tree)),
        f.PinEvidence(marker_revision=f.PINNED_REVISION, marker_status="verified"),
    )
    assert report.verdict == f.INCONCLUSIVE and "PIN_SOURCE_NOT_READ" in report.reason_codes


# ------------------------------------------------------------------------------------------------ resources and telemetry


def test_insufficient_physical_memory_is_a_resource_no_go(tree):
    small = dataclasses.replace(GOOD_TELEMETRY, total_ram_bytes=16 * GIB)
    report = verdict(real_sizes(candidate(tree)), telemetry=small)
    assert (
        report.verdict == f.NO_GO_RESOURCE_RISK
        and "HOST_RESIDENT_WEIGHTS_EXCEED_PHYSICAL" in report.reason_codes
    )


def test_projection_beyond_commit_capacity_is_a_resource_no_go(tree):
    tight = dataclasses.replace(
        GOOD_TELEMETRY, total_ram_bytes=20 * GIB, pagefile_allocated_bytes=8 * GIB
    )
    report = verdict(real_sizes(candidate(tree)), telemetry=tight)
    assert (
        report.verdict == f.NO_GO_RESOURCE_RISK
        and "HOST_PEAK_PROJECTION_EXCEEDS_COMMIT_CAPACITY" in report.reason_codes
    )


def test_a_transformer_that_cannot_be_vram_resident_is_a_resource_no_go(tree):
    small = dataclasses.replace(GOOD_TELEMETRY, vram_total_bytes=8 * GIB)
    assert (
        "VRAM_TRANSFORMER_EXCEEDS_DEDICATED"
        in verdict(real_sizes(candidate(tree)), telemetry=small).reason_codes
    )


def test_a_momentary_low_headroom_is_a_launch_precondition_not_a_verdict_input(tree):
    busy = dataclasses.replace(GOOD_TELEMETRY, commit_headroom_bytes=10 * GIB)
    report = verdict(real_sizes(candidate(tree)), telemetry=busy)
    assert (
        report.verdict == f.ELIGIBLE
        and "CURRENT_COMMIT_HEADROOM_BELOW_PROJECTION" in report.reason_codes
    )
    assert any("Commit headroom" in item for item in report.preconditions)


def test_thin_vram_margin_is_reported_without_overstating(tree):
    tight = dataclasses.replace(GOOD_TELEMETRY, vram_total_bytes=int(11.6 * GIB))
    report = verdict(real_sizes(candidate(tree)), telemetry=tight)
    assert "VRAM_MARGIN_THIN_IN_UPPER_PROJECTION" in report.reason_codes
    assert report.estimated["vram_peak_low_bytes"] < report.estimated["vram_peak_high_bytes"]


@pytest.mark.parametrize(
    "missing", ["total_ram_bytes", "vram_total_bytes", "pagefile_allocated_bytes"]
)
def test_missing_telemetry_is_inconclusive_never_a_go(tree, missing):
    gone = dataclasses.replace(GOOD_TELEMETRY, **{missing: None})
    report = verdict(real_sizes(candidate(tree)), telemetry=gone)
    assert (
        report.verdict == f.INCONCLUSIVE
        and f"TELEMETRY_{missing.upper()}_MISSING" in report.reason_codes
    )


def test_a_listening_endpoint_is_a_precondition(tree):
    live = dataclasses.replace(GOOD_TELEMETRY, forge_endpoint_listening=True)
    report = verdict(real_sizes(candidate(tree)), telemetry=live)
    assert "FORGE_ENDPOINT_ALREADY_LISTENING" in report.reason_codes and report.preconditions


# ------------------------------------------------------------------------------------------------ verdict precedence


def test_verdict_precedence_is_missing_then_pin_then_resource_then_inconclusive_then_identity(tree):
    bad_pin = dataclasses.replace(GOOD_PIN, defines_zimage=False)
    small = dataclasses.replace(GOOD_TELEMETRY, total_ram_bytes=16 * GIB)
    gone = dataclasses.replace(GOOD_TELEMETRY, vram_total_bytes=None)
    unhashed = real_sizes(candidate(tree, hashed=False))
    hashed = real_sizes(candidate(tree))
    _swap(tree, "VAE/" + f.VAE_NAME, fx.vae(32, batch_norm=True))
    wrong_vae = real_sizes(candidate(tree))
    assert verdict(wrong_vae, bad_pin, small).verdict == f.MISSING_DEPENDENCY
    assert verdict(hashed, bad_pin, small).verdict == f.NO_GO_PINNED_FORGE
    assert (
        verdict(hashed, GOOD_PIN, dataclasses.replace(small, vram_total_bytes=None)).verdict
        == f.NO_GO_RESOURCE_RISK
    )
    assert verdict(unhashed, GOOD_PIN, gone).verdict == f.INCONCLUSIVE
    assert verdict(unhashed, GOOD_PIN, GOOD_TELEMETRY).verdict == f.IDENTITY_PENDING
    assert verdict(hashed, GOOD_PIN, GOOD_TELEMETRY).verdict == f.ELIGIBLE


# ------------------------------------------------------------------------------------------------ report properties and side effects


def test_the_report_is_deterministic_bounded_and_contains_no_local_paths(tree):
    cand = real_sizes(candidate(tree))
    first = json.dumps(verdict(cand).as_dict(), sort_keys=True, default=str)
    second = json.dumps(verdict(cand).as_dict(), sort_keys=True, default=str)
    assert first == second and len(first) < 200_000
    assert str(tree) not in first and "Users" not in first
    report = json.loads(first)
    assert (
        report["official_guidance"]["guidance_scale"] == 0.0
        and report["official_guidance"]["dit_forward_passes"] == 8
    )
    assert "TURBO_NOT_FOUNDATION" in report["reason_codes"]


def test_collection_and_evaluation_write_nothing_and_start_no_process(tree, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no subprocess may run during collection or evaluation")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    before = sorted(str(p.relative_to(tree.parent)) for p in tree.parent.rglob("*"))
    verdict(real_sizes(candidate(tree)))
    f.collect_candidate(tree, hash_files=True)
    assert sorted(str(p.relative_to(tree.parent)) for p in tree.parent.rglob("*")) == before


def test_only_allow_listed_read_only_commands_may_run():
    with pytest.raises(PermissionError):
        f.base.run_read_only(["nvidia-smi", "-pl", "100"])
    with pytest.raises(PermissionError):
        f.base.run_read_only(["powershell", "-Command", "Stop-Process -Name python"])


def test_the_module_has_no_network_write_or_launch_surface():
    source = Path(f.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    imported |= {
        n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
    }
    assert not imported & {"requests", "urllib", "http", "socket", "subprocess", "shutil", "httpx"}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {
        "post",
        "put",
        "unlink",
        "rename",
        "rmtree",
        "copy",
        "copyfile",
        "move",
        "Popen",
        "system",
    }
    assert "write_text" in attrs  # the only write is the report file the caller names, in main()
    assert source.count("write_text(") == 1


def test_inspected_components_reuse_the_pr152_header_evidence(tree):
    evidence = inspect_component_file(tree / "models/text_encoder" / f.ENCODER_NAME)
    assert evidence.architecture == "qwen3" and evidence.fact("hidden_size") == 2560
