"""PR-VID-MOTION-430 Workstream C: the effective-conditioning preview follows the pinned graph and labels its limits."""

from __future__ import annotations

import numpy as np
import pytest

from src.video import conditioning_advisories as adv
from src.video.motion_conversion import conditioning_preview as cond
from src.video.workflow_conditioning import conditioning_contract
from src.video.workflow_registry import build_default_workflow_registry
from tests.video import canny_vectors_430 as vectors

# Reference edge maps (bit-packed) produced by kornia 0.8.3 ``canny(low=0.1, high=0.6)`` in the pinned managed ComfyUI
# v0.38.0 venv (CPU, torch 2.14.0) on the deterministic images of ``canny_vectors_430``.  Recorded 2026-11-25.
KORNIA_VECTORS = {
    "shapes": (
        (40, 32),
        (
            "0000000080000000600000003000000098000000cc0000006400000033ff800019007000050010000400100004001000"
            "0400100004001000040010000400100004001000040010000400080004000800040008000400080002001800038031c0"
            "007fe0600000002000000990000044d00000465000004330000021a8000020cc000038c4000007820000000100000000"
            "00000000000000000000000000000000"
        ),
    ),
    "textured": (
        (48, 64),
        (
            "000000000000100000000000000010000000000000000800000000000000080000000000000010000000000000001000"
            "000000000000100000000000000010000000000000001000000002f800c0100000000d07ff3010000000080000100800"
            "000010000010080000001000001008000000100000100800000008000010080000000800001008000000080000101000"
            "000008000010100000001000001010000000100000081000000010000008100000001000000810000000100000081000"
            "000008000010100000001000001010000000100000101000000010000010100000001000001010000000100000100800"
            "000010000010080000001000001010000000100000101000000010000008100000001000000810000000080000101000"
            "00000800001010000000080000101000000008000010080000000f8078f008000000007f870008000000000000000800"
            "000000000000080000000000000008000000000000001000000000000000100000000000000010000000000000000800"
        ),
    ),
    "thin_line": (
        (32, 32),
        (
            "00028000000280000002800000028000ffffffff00028000ffffffff0002800000028000000280000002800000028000"
            "000280000002800000028000000280000002800000028000000280000002800000028000000280000002800000028000"
            "0002800000028000000280000002800000028000000280000002800000028000"
        ),
    ),
    "step": (
        (24, 40),
        (
            "000040000000004000000000400000000040000000004000000000400000000040000000004000000000400000000040"
            "000000004000000000400000000040000000004000000000400000000040000000004000000000400000000040000000"
            "004000000000400000000040000000004000000000400000"
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(KORNIA_VECTORS))
def test_the_edge_detector_matches_the_pinned_kornia_canny_on_recorded_vectors(name):
    shape, expected = KORNIA_VECTORS[name]
    image = vectors.VECTORS[name]()
    assert image.shape == shape
    assert vectors.pack(cond.canny_edges(image)) == expected


def test_the_gaussian_is_the_exact_sigma_one_kernel_not_the_binomial_approximation():
    expected = np.exp(-0.5 * np.arange(-2, 3, dtype=np.float32) ** 2)
    expected = expected / expected.sum()
    assert np.allclose(cond._GAUSS_1D, expected, atol=1e-7)
    assert not np.allclose(
        cond._GAUSS_1D, np.array([1, 4, 6, 4, 1], dtype=np.float32) / 16, atol=1e-3
    )


def test_parity_on_four_vectors_does_not_make_the_preview_exact():
    assert cond.EXACT_PARITY_VERIFIED is False
    assert cond.EXACTNESS_APPROXIMATE != cond.EXACTNESS_EXACT
    assert "not verified" in cond.EXACTNESS_REASON


def test_graph_order_is_edges_then_crop_then_resize_not_crop_then_edges():
    # A wide frame with a vertical bar near the left edge: detecting edges first keeps the bar's two edges before the crop
    # decides what is lost; cropping first would have changed the blur's reflect padding at the new border.
    gray = np.full((24, 64), 0.1, dtype=np.float32)
    gray[:, 3:6] = 0.9
    graph_order = cond.center_crop_to_aspect(cond.canny_edges(gray), 24, 24)
    wrong_order = cond.canny_edges(cond.center_crop_to_aspect(gray, 24, 24))
    assert graph_order.shape == wrong_order.shape == (24, 24)
    assert cond.OPERATION_ORDER.index(
        "Canny edge detection at the frame's own size"
    ) < cond.OPERATION_ORDER.index("centre-crop to the generation aspect")
    # The bar lies in the cropped-away left margin, so only the graph order knows it existed.
    assert not graph_order.any() and not wrong_order.any()
    wide = vectors.shapes(60, 100)
    first = cond.center_crop_to_aspect(cond.canny_edges(wide), 40, 40)
    second = cond.canny_edges(cond.center_crop_to_aspect(wide, 40, 40))
    assert first.shape == second.shape == (60, 60)
    assert not np.array_equal(
        first, second
    )  # the two orders are observably different near the crop border


def test_bilinear_resize_follows_the_half_pixel_convention():
    ramp = np.array([[0.0, 1.0], [0.0, 1.0]], dtype=np.float32)
    up = cond.resize_bilinear(ramp, 4, 2)
    # torch interpolate(bilinear, align_corners=False): source = (dst + 0.5) / 2 - 0.5, clamped at 0
    assert np.allclose(up[0], [0.0, 0.25, 0.75, 1.0])
    same = cond.resize_bilinear(ramp, 2, 2)
    assert np.array_equal(same, ramp)
    down = cond.resize_bilinear(np.arange(16, dtype=np.float32).reshape(4, 4), 2, 2)
    assert down.shape == (2, 2)


def test_conditioned_view_crops_to_aspect_then_resizes_to_the_target():
    edges = np.zeros((40, 80), dtype=bool)
    edges[:, 40] = True
    view = cond.conditioned_view(edges, (24, 40))
    assert view.shape == (40, 24)
    assert view.max() > 0.5 and view.dtype == np.float32


def _gray_clip(h=40, w=40):
    return np.full((h, w), 0.5, dtype=np.float32)


def _frame_kwargs(**over):
    base = {
        "densities": [0.03],
        "border_shares": [0.0],
        "motion_diffs": [0.05],
        "gray_frames": [],
        "edge_frames": [],
        "video_aspect": 0.5,
        "target_aspect": 0.5,
        "reference_iou": None,
        "downscaled": False,
        "min_density": cond.MIN_EDGE_DENSITY,
        "max_density": cond.MAX_EDGE_DENSITY,
        "border_edge_share": cond.BORDER_EDGE_SHARE,
        "near_static": cond.NEAR_STATIC_DIFF,
        "large_change": cond.LARGE_CHANGE_DIFF,
        "aspect_tolerance": cond.ASPECT_TOLERANCE,
    }
    base.update(over)
    return base


def _codes(advisories):
    return {a.code for a in advisories}


def test_measured_advisories_state_a_number_and_a_basis():
    flat = _gray_clip()
    flat[:, :8] = 0.5  # constant
    found = adv.frame_advisories(
        **_frame_kwargs(gray_frames=[flat], edge_frames=[np.zeros((40, 40), bool)])
    )
    by_code = {a.code: a for a in found}
    assert by_code["low_contrast"].basis == "measured" and "0.000" in by_code["low_contrast"].text
    assert by_code["uniform_border"].basis == "measured"
    assert "top 100%" in by_code["uniform_border"].text


def test_uniform_band_detection_finds_padding_but_not_a_textured_frame():
    padded = np.full((50, 40), 0.0, dtype=np.float32)
    padded[10:40, :] = np.linspace(0.2, 0.9, 40, dtype=np.float32)[None, :]
    bands = adv.uniform_bands(padded)
    assert set(bands) == {"top", "bottom"} and abs(bands["top"] - 0.2) < 1e-6
    ramp = np.tile(np.linspace(0, 1, 40, dtype=np.float32), (30, 1))
    assert adv.uniform_bands(ramp) == {}
    assert not adv.uniform_bands(np.random.default_rng(1).random((30, 30), dtype=np.float32))


def test_multiple_subject_heuristic_counts_separated_edge_groups_and_is_labelled_heuristic():
    edges = np.zeros((40, 100), dtype=bool)
    edges[5:35, 10:14] = True
    edges[5:35, 60:64] = True
    assert adv.subject_clusters(edges) == 2
    one = np.zeros((40, 100), dtype=bool)
    one[5:35, 40:46] = True
    assert adv.subject_clusters(one) == 1 and adv.subject_clusters(np.zeros((4, 4), bool)) == 0
    found = adv.frame_advisories(**_frame_kwargs(edge_frames=[edges], gray_frames=[]))
    multi = next(a for a in found if a.code == "multiple_subjects")
    assert multi.basis == "heuristic" and "may" in multi.text


def test_dense_interior_texture_is_flagged_as_a_heuristic_not_a_defect():
    dense = np.zeros((40, 40), dtype=bool)
    dense[10:30, 10:30] = np.indices((20, 20)).sum(axis=0) % 2 == 0
    found = adv.frame_advisories(**_frame_kwargs(edge_frames=[dense]))
    texture = next(a for a in found if a.code == "internal_texture")
    assert texture.basis == "heuristic"


def test_canny_working_set_is_computed_from_the_pinned_kernel_and_flagged_for_oversized_drivers():
    assert adv.canny_working_set_bytes(3840, 2160, 17) == 3840 * 2160 * 17 * 4 * 8
    fun = conditioning_contract(
        build_default_workflow_registry().get(
            "wan22_fun_control_5b_canny_i2v_v1", "1.1.0", allow_experimental=True
        )
    )
    found = adv.preparation_advisories(
        contract=fun,
        width=3840,
        height=2160,
        frames=49,
        target_size=(480, 832),
        file_bytes=107_409_268,
    )
    by = {a.code: a for a in found}
    assert set(by) == {"canny_working_set", "excessive_resolution", "upload_limit"}
    assert (
        by["canny_working_set"].basis == "runtime_source"
        and "not measured" in by["canny_working_set"].text
    )
    assert by["excessive_resolution"].basis == "historical"
    assert by["upload_limit"].basis == "measured" and "413" in by["upload_limit"].text
    right_sized = adv.preparation_advisories(
        contract=fun, width=480, height=832, frames=49, target_size=(480, 832), file_bytes=3_000_000
    )
    assert _codes(right_sized) == {
        "canny_working_set"
    }  # information only; no refusal and no threshold imposed


def test_oversized_driver_for_the_rgb_workflow_is_not_called_a_memory_failure():
    animate = conditioning_contract(
        build_default_workflow_registry().get(
            "wan_animate2_drive_i2v_v1", "1.2.0", allow_experimental=True
        )
    )
    found = adv.preparation_advisories(
        contract=animate,
        width=3840,
        height=2160,
        frames=49,
        target_size=(480, 832),
        file_bytes=None,
    )
    assert _codes(found) == {"excessive_resolution"} and found[0].basis == "heuristic"
    assert "memory" not in found[0].text


def test_context_advisories_distinguish_representation_workflow_window_and_viewpoint():
    registry = build_default_workflow_registry()
    animate = conditioning_contract(
        registry.get("wan_animate2_drive_i2v_v1", "1.2.0", allow_experimental=True)
    )
    fun = conditioning_contract(
        registry.get("wan22_fun_control_5b_canny_i2v_v1", "1.1.0", allow_experimental=True)
    )
    rgb = {
        a.code: a
        for a in adv.context_advisories(
            contract=animate, representation="rgb_footage", window_frames=33, generation_frames=49
        )
    }
    assert rgb["driver_appearance"].basis == "runtime_source"
    assert (
        rgb["window_short"].basis == "runtime_source"
        and "holding the last one" in rgb["window_short"].text
    )
    canny = {
        a.code: a
        for a in adv.context_advisories(
            contract=fun,
            representation="rendered_character",
            window_frames=81,
            generation_frames=49,
        )
    }
    assert canny["driver_appearance"].basis == "historical"
    assert canny["window_long"].basis == "runtime_source"
    skeleton = adv.context_advisories(
        contract=fun,
        representation="rendered_skeleton",
        window_frames=49,
        generation_frames=49,
        motion_category="head_turn",
        driver_viewpoint="side",
        source_viewpoint="front",
    )
    assert _codes(skeleton) == {"skeleton_head_orientation", "viewpoint_mismatch"}
    assert all(a.basis in ("heuristic", "historical") for a in skeleton)
    assert not adv.context_advisories(
        contract=fun, representation="rendered_silhouette", window_frames=49, generation_frames=49
    )


def test_every_advisory_has_a_known_basis_and_the_preview_serialises_it():
    assert adv.COMFY_UPLOAD_LIMIT_BYTES == 104_857_600
    found = adv.context_advisories(
        contract=None,
        representation="rendered_skeleton",
        window_frames=10,
        generation_frames=20,
        motion_category="head_turn",
    )
    payload = adv.advisories_payload(found)
    assert payload and all(set(item) == {"code", "text", "basis"} for item in payload)
    assert adv.advisory_texts(found) == tuple(a.text for a in found)
