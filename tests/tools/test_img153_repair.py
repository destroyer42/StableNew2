"""PR #80 repair: scale-contract strictness, host-memory/VRAM wording and boundaries, and the safety-gate contract."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from tests.assets import topology_fixtures_152 as fx
from tests.tools.test_img153_feasibility import (
    GOOD_PIN,
    GOOD_TELEMETRY,
    candidate,
    real_sizes,
    verdict,
    zimage_dit,
)
from tools.qualification.img151.feasibility import GIB
from tools.qualification.img153 import feasibility as f

DIGESTS = {
    "transformer": "59610861d46ae8d5d1d371ab7b2532ce64c0835052b395551a8550fa0e3eb3cf",
    "text_encoder": "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
    "vae": "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
}
LAYERS = ("cap_embedder.1", "layers.0.attention.qkv", "layers.0.adaLN_modulation.0", "x_embedder")


@pytest.fixture
def tree(tmp_path: Path):
    root = tmp_path / "webui"
    models = root / "models"
    fx.safetensors(models / "Stable-diffusion" / f.TRANSFORMER_NAME, zimage_dit())
    fx.safetensors(models / "text_encoder" / f.ENCODER_NAME, fx.qwen3_encoder(2560))
    fx.safetensors(models / "VAE" / f.VAE_NAME, fx.vae(16))
    return root


def variant(name: str) -> dict:
    t = zimage_dit(scales="marker")
    if name == "exact":
        return t
    if name == "marker_missing":
        del t["scaled_fp8"]
    elif name == "partial_coverage":
        del t["x_embedder.scale_weight"]
    elif name == "orphan_scale":
        t["layers.9.attention.qkv.scale_weight"] = ("F32", [1])
    elif name == "scale_bf16":
        t["x_embedder.scale_weight"] = ("BF16", [1])
    elif name == "scale_per_row":
        t["x_embedder.scale_weight"] = ("F32", [4, 1])
    elif name == "marker_prefix_not_shared":
        t["model.diffusion_model.scaled_fp8"] = t.pop("scaled_fp8")
    elif name == "two_markers":
        t["other.scaled_fp8"] = ("F8_E4M3", [2])
    elif name == "marker_one_element":
        t["scaled_fp8"] = ("F8_E4M3", [1])
    elif name == "fp8_not_a_weight":
        t["layers.0.attention.bias_q"] = ("F8_E4M3", [4])
    elif name == "scale_input":
        t["layers.0.attention.qkv.scale_input"] = ("F32", [1])
    elif name == "lone_comfy_quant":
        for layer in LAYERS:
            del t[f"{layer}.scale_weight"]
        del t["scaled_fp8"]
        t["x_embedder.comfy_quant"] = ("U8", [20])
        t["x_embedder.weight_scale"] = ("F32", [1])
    elif name == "full_comfy_quant":
        for layer in LAYERS:
            del t[f"{layer}.scale_weight"]
            t[f"{layer}.weight_scale"] = ("F32", [1])
            t[f"{layer}.comfy_quant"] = ("U8", [20])
        del t["scaled_fp8"]
    else:  # pragma: no cover
        raise AssertionError(name)
    return t


def installed(tree: Path, name: str):
    fx.safetensors(tree / "models/Stable-diffusion" / f.TRANSFORMER_NAME, variant(name))
    return real_sizes(candidate(tree))


# ------------------------------------------------------------------------------------------------ scale contract


@pytest.mark.parametrize(
    "name",
    [
        "marker_missing",
        "partial_coverage",
        "orphan_scale",
        "scale_bf16",
        "scale_per_row",
        "marker_prefix_not_shared",
        "two_markers",
        "marker_one_element",
        "fp8_not_a_weight",
        "scale_input",
        "lone_comfy_quant",
    ],
)
def test_incomplete_or_unsupported_scale_placements_fail_closed(tree, name):
    cand = installed(tree, name)
    assert cand.zimage.scales.convention == "unknown", cand.zimage.scales
    report = verdict(cand)
    assert (
        report.verdict == f.INCONCLUSIVE and "FP8_SCALE_CONVENTION_UNKNOWN" in report.reason_codes
    )


def test_the_exact_scale_configuration_and_a_fully_covered_comfy_quant_layout_are_eligible(tree):
    exact = installed(tree, "exact")
    assert exact.zimage.scales.convention == "comfy_scaled_fp8_marker"
    assert (exact.zimage.scales.fp8_weights, exact.zimage.scales.matched_scales) == (4, 4)
    assert verdict(exact).verdict == f.ELIGIBLE
    full = installed(tree, "full_comfy_quant")
    assert full.zimage.scales.convention == "comfy_quant_per_layer"
    assert verdict(full).verdict == f.ELIGIBLE


def test_a_lone_comfy_quant_marker_never_yields_eligibility(tree):
    report = verdict(installed(tree, "lone_comfy_quant"))
    assert report.verdict != f.ELIGIBLE


# ------------------------------------------------------------------------------------------------ host memory


def estimated(tree, telemetry=GOOD_TELEMETRY, assumptions=None):
    return f.evaluate(real_sizes(candidate(tree)), GOOD_PIN, telemetry, assumptions)


def test_the_physical_memory_warning_appears_when_an_analogue_exceeds_usable_ram(tree):
    report = estimated(tree)  # 34 GiB RAM: usable 30 GiB, analogues 28.2-30.7 GiB
    assert "HOST_PEAK_PROJECTION_EXCEEDS_USABLE_PHYSICAL" in report.reason_codes
    assert report.estimated["projected_paging_pressure_high_bytes"] > 0
    detail = next(
        x.detail
        for x in report.findings
        if x.code == "HOST_PEAK_PROJECTION_EXCEEDS_USABLE_PHYSICAL"
    )
    assert "paging" in detail.lower() and "0.01" in detail
    roomy = dataclasses.replace(GOOD_TELEMETRY, total_ram_bytes=40 * GIB)
    assert "HOST_PEAK_PROJECTION_EXCEEDS_USABLE_PHYSICAL" not in estimated(tree, roomy).reason_codes


def test_the_policy_commit_limit_is_ram_plus_pagefile_minus_the_declared_reserve(tree):
    report = estimated(tree)
    total, pagefile = GOOD_TELEMETRY.total_ram_bytes, GOOD_TELEMETRY.pagefile_allocated_bytes
    assert f.Assumptions().host_reserve_bytes == 4 * GIB
    assert report.estimated["system_commit_limit_bytes"] == total + pagefile
    assert report.estimated["host_reserve_bytes"] == 4 * GIB
    assert report.estimated["policy_commit_limit_bytes"] == total + pagefile - 4 * GIB
    bigger = estimated(tree, assumptions=f.Assumptions(host_reserve_bytes=8 * GIB))
    assert bigger.estimated["policy_commit_limit_bytes"] == total + pagefile - 8 * GIB


def test_the_policy_limit_boundaries_set_the_resource_no_go_and_the_upper_band(tree):
    low = estimated(tree).estimated["host_peak_projection_low_bytes"]
    high = estimated(tree).estimated["host_peak_projection_high_bytes"]

    def at(limit: int):
        # total RAM stays large enough that physical residency passes; the pagefile sets the policy limit exactly
        telemetry = dataclasses.replace(
            GOOD_TELEMETRY,
            total_ram_bytes=20 * GIB,
            pagefile_allocated_bytes=limit + 4 * GIB - 20 * GIB,
        )
        return estimated(tree, telemetry)

    assert at(low - 1).verdict == f.NO_GO_RESOURCE_RISK
    assert "HOST_PEAK_PROJECTION_EXCEEDS_POLICY_COMMIT_LIMIT" in at(low - 1).reason_codes
    inside = at(low)
    assert (
        inside.verdict == f.ELIGIBLE
        and "HOST_PEAK_UPPER_PROJECTION_EXCEEDS_POLICY_COMMIT_LIMIT" in inside.reason_codes
    )
    top = at(high)
    assert "HOST_PEAK_PROJECTIONS_WITHIN_POLICY_COMMIT_LIMIT" in top.reason_codes


def test_the_policy_commit_limit_finding_does_not_claim_demonstrated_fit(tree):
    report = estimated(tree)
    assert "HOST_PEAK_PROJECTIONS_FIT_QUIESCED_CAPACITY" not in report.reason_codes
    detail = next(
        x.detail
        for x in report.findings
        if x.code == "HOST_PEAK_PROJECTIONS_WITHIN_POLICY_COMMIT_LIMIT"
    )
    assert (
        "theoretical ceiling" in detail
        and "not measured free headroom" in detail
        and "does not demonstrate" in detail
    )


def test_eligibility_is_stated_as_conditional_not_as_hardware_fit(tree):
    report = estimated(tree)
    assert report.verdict == f.ELIGIBLE and "ELIGIBILITY_IS_CONDITIONAL" in report.reason_codes
    text = report.next_recommendation
    assert "Conditional eligibility only" in text and "not confirmation" in text


# ------------------------------------------------------------------------------------------------ VRAM


def vram_report(tree, total):
    return estimated(tree, dataclasses.replace(GOOD_TELEMETRY, vram_total_bytes=total))


def test_vram_boundaries_thin_exceeding_total_and_insufficient(tree):
    probe = vram_report(tree, 12 * GIB).estimated
    documented, bound = (
        probe["vram_documented_img115_peak_bytes"],
        probe["vram_additive_bound_bytes"],
    )
    assert documented == 9696 * 1024 * 1024 and bound > documented

    roomy = vram_report(
        tree, int(bound / 0.9)
    )  # bound is 90% of the card: neither thin nor exceeding
    assert roomy.verdict == f.ELIGIBLE
    assert not {
        "VRAM_MARGIN_THIN_IN_ADDITIVE_BOUND",
        "VRAM_ADDITIVE_BOUND_EXCEEDS_DEDICATED",
    } & set(roomy.reason_codes)

    thin = vram_report(
        tree, bound
    )  # bound equals the card: above the 95% line, not above the total
    assert "VRAM_MARGIN_THIN_IN_ADDITIVE_BOUND" in thin.reason_codes and thin.verdict == f.ELIGIBLE

    over = vram_report(
        tree, bound - 1
    )  # the derived bound exceeds the card, the documented peak still fits
    assert "VRAM_ADDITIVE_BOUND_EXCEEDS_DEDICATED" in over.reason_codes
    assert (
        over.verdict == f.ELIGIBLE
    )  # a conservative derived bound is a flagged risk, not a disproof

    short = vram_report(tree, documented - 1)  # even the documented peak would not fit
    assert (
        short.verdict == f.NO_GO_RESOURCE_RISK
        and "VRAM_DOCUMENTED_PEAK_EXCEEDS_DEDICATED" in short.reason_codes
    )

    small = vram_report(
        tree, 8 * GIB
    )  # the transformer cannot be resident after the activation reserve
    assert (
        small.verdict == f.NO_GO_RESOURCE_RISK
        and "VRAM_TRANSFORMER_EXCEEDS_DEDICATED" in small.reason_codes
    )


def test_the_thin_margin_fraction_is_a_declared_assumption(tree):
    bound = vram_report(tree, 12 * GIB).estimated["vram_additive_bound_bytes"]
    total = int(bound / 0.97)
    assert (
        "VRAM_MARGIN_THIN_IN_ADDITIVE_BOUND"
        in estimated(tree, dataclasses.replace(GOOD_TELEMETRY, vram_total_bytes=total)).reason_codes
    )
    relaxed = f.Assumptions(vram_thin_margin_fraction=0.99)
    assert (
        "VRAM_MARGIN_THIN_IN_ADDITIVE_BOUND"
        not in estimated(
            tree, dataclasses.replace(GOOD_TELEMETRY, vram_total_bytes=total), relaxed
        ).reason_codes
    )


def test_vram_wording_separates_measured_documented_and_derived_and_drops_the_desktop_claim(tree):
    report = vram_report(tree, 12 * GIB)
    text = json.dumps(report.as_dict(), default=str)
    assert "about 2 GiB" not in text and "desktop use" not in text.replace(
        "desktop and other processes", ""
    )
    kinds = {x.code: x.kind for x in report.findings}
    assert kinds["CURRENT_VRAM_UTILIZATION_RECORDED"] == "measured"
    thin = next(
        (x for x in report.findings if x.code == "VRAM_MARGIN_THIN_IN_ADDITIVE_BOUND"), None
    )
    if thin:
        assert (
            "no established phase attribution" in thin.detail
            and "not a denoise-phase figure" in thin.detail
        )
    pin_note = next(x.detail for x in report.findings if x.code == "PIN_CONVERTS_SCALED_FP8")
    assert ">= 8.9" not in pin_note and "does not select the execution path" in pin_note


# ------------------------------------------------------------------------------------------------ safety-gate contract


def test_no_executable_abort_threshold_is_claimed_and_the_future_package_requirements_are_stated(
    tree,
):
    report = estimated(tree)
    payload = report.as_dict()
    assert "abort thresholds" not in report.next_recommendation
    assert "preconditions_for_any_future_qualification" not in payload
    requirements = " ".join(payload["future_physical_package_requirements"])
    for phrase in (
        "Measurable preflight",
        "Instrumentation",
        "operator stop conditions",
        "Fault-event",
        "lifecycle ownership",
        "cannot be guaranteed recoverable",
    ):
        assert phrase in requirements
    assert payload[
        "future_package_inputs_not_gates"
    ]  # inputs for the next package, labelled as not gates


def test_the_evaluator_implements_no_process_control_or_telemetry_sampling():
    source = Path(f.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\b(terminate|kill|taskkill|Stop-Process|psutil)\b", source)


def test_the_canonical_document_records_all_three_complete_digests_and_the_conditional_framing():
    doc = (
        Path(f.__file__).resolve().parents[3]
        / "docs/Subsystems/Image/PR-IMG-MODELS-153_ZImage_Turbo_FP8_Feasibility.md"
    ).read_text(encoding="utf-8")
    for digest in DIGESTS.values():
        assert digest in doc
    assert "conditional eligibility only" in doc.lower()
    assert "defines **no** executable preflight gate, abort threshold" in doc
    assert "stated preconditions and abort thresholds" not in doc
