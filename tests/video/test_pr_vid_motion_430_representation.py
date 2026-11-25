"""PR-VID-MOTION-430 Workstream B: related character / silhouette / skeleton variants with verified provenance."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.library_bridge import derivation_from_record
from src.video.motion_conversion.representation import (
    movement_key,
    movement_key_of_record,
    verify_bindings,
    verify_variant,
    verify_variants,
)
from src.video.motion_library.models import (
    LOCATOR_LINKED,
    AssetLocator,
    DerivationRecord,
    MotionAsset,
)
from src.video.motion_library.variants import group_variants, related_variants, variant_lines

SOURCE_SHA = "a" * 64
PROBE = cp.AnimationProbe(Fraction(24), Fraction(1), Fraction(121), (), True, "4.2.3")


def _plan(**over):
    options = {
        "source_path": "C:/anim/Walk.fbx",
        "source_sha256": SOURCE_SHA,
        "source_route": cp.SOURCE_FBX_CHARACTER,
        "probe": PROBE,
        "profile": cp.PROFILE_CHARACTER,
        "camera": cp.CAMERA_FRONT,
        "output_frames": 17,
        "width": 480,
        "height": 832,
        "rig_fingerprint": "rig-1",
    }
    options.update(over)
    return cp.build_plan(**options)


def _record(plan, *, video_sha, character_mode="embedded_skinned_mesh"):
    return {
        "schema": "stablenew.motion-conversion.v1",
        "plan_digest": plan.digest,
        "plan": plan.to_record(),
        "source": {
            "path": plan.source_path,
            "sha256": plan.source_sha256,
            "type": plan.source_type,
            "route": plan.source_route,
        },
        "rig": {"fingerprint": plan.rig_fingerprint, "bone_count": 20},
        "character": {"mode": character_mode, "path": "", "sha256": ""},
        "conversion": {
            "profile": plan.profile,
            "camera": plan.camera,
            "camera_mode": plan.camera_mode,
            "root_motion": plan.root_motion,
        },
        "tools": {"blender": {"version": "4.2.3"}, "script_version": cp.SCRIPT_VERSION},
        "output": {"file": "walk.mp4", "sha256": video_sha},
    }


def _asset(asset_id, plan, record, *, with_key=True):
    derivation = derivation_from_record(record, f"/prov/{asset_id}.json")
    if not with_key:
        derivation = replace(derivation, movement_key="")
    return MotionAsset(
        asset_id=asset_id,
        display_name=f"{plan.profile} {asset_id}",
        sha256=record["output"]["sha256"],
        locator=AssetLocator(LOCATOR_LINKED, f"C:/lib/{asset_id}.mp4"),
        derivation=derivation,
    ), record


def _trio(**over):
    out = {}
    for name, profile, mode in (
        ("c", cp.PROFILE_CHARACTER, "embedded_skinned_mesh"),
        ("s", cp.PROFILE_SILHOUETTE, "embedded_skinned_mesh"),
        ("k", cp.PROFILE_SKELETON, "skeleton_only"),
    ):
        plan = _plan(profile=profile, **over)
        record = _record(plan, video_sha=name * 64, character_mode=mode)
        out[name] = _asset(name, plan, record)
    return out


def _reader(trio):
    records = {f"/prov/{k}.json": r for k, (_a, r) in trio.items()}
    return lambda path: records.get(path)


def test_movement_key_ignores_the_render_profile_but_nothing_that_changes_the_movement():
    base = movement_key(_plan().to_record())
    assert movement_key(_plan(profile=cp.PROFILE_SILHOUETTE).to_record()) == base
    assert movement_key(_plan(profile=cp.PROFILE_SKELETON).to_record()) == base
    for change in (
        {"camera": cp.CAMERA_SIDE},
        {"camera_mode": cp.CAMERA_TRACKING},
        {"root_motion": cp.ROOT_IN_PLACE},
        {"output_frames": 21},
        {"start_seconds": "1/4"},
        {"width": 496},
        {"source_sha256": "b" * 64},
        {"rig_fingerprint": "rig-2"},
    ):
        assert movement_key(_plan(**change).to_record()) != base, change


def test_a_new_derivation_records_its_key_and_legacy_records_load_without_one():
    plan = _plan()
    record = _record(plan, video_sha="c" * 64)
    derivation = derivation_from_record(record, "/p.json")
    assert derivation.movement_key == movement_key_of_record(record) != ""
    payload = derivation.to_dict()
    assert DerivationRecord.from_dict(payload) == derivation
    legacy = {k: v for k, v in payload.items() if k != "movement_key"}
    assert DerivationRecord.from_dict(legacy).movement_key == ""
    assert DerivationRecord.from_dict({**payload, "movement_key": "not-a-sha"}).movement_key == ""


def test_catalog_grouping_uses_stored_keys_and_never_guesses_a_legacy_clip_into_a_group():
    trio = _trio()
    legacy, _ = _asset("old", _plan(), _record(_plan(), video_sha="d" * 64), with_key=False)
    other_view, _ = _asset(
        "side",
        _plan(camera=cp.CAMERA_SIDE),
        _record(_plan(camera=cp.CAMERA_SIDE), video_sha="e" * 64),
    )
    assets = [a for a, _r in trio.values()] + [legacy, other_view]
    groups = group_variants(assets)
    assert len(groups) == 2  # the trio, and the side-view clip alone
    group = next(g for g in groups.values() if len(g.members) == 3)
    assert group.multi_representation
    assert set(group.representations) == {
        "rendered_character",
        "rendered_silhouette",
        "rendered_skeleton",
    }
    related = related_variants(assets, trio["c"][0])
    assert {m.asset_id for m in related} == {"s", "k"}
    assert related_variants(assets, legacy) == ()
    assert "not tracked" in variant_lines(legacy, ())[0]
    assert (
        "no other representation"
        in variant_lines(other_view, related_variants(assets, other_view))[0]
    )
    lines = "\n".join(variant_lines(trio["c"][0], related))
    assert "own identity" in lines and "interchangeable" in lines


def test_a_verified_trio_is_a_controlled_comparison_with_honest_disclosures():
    trio = _trio()
    evidence = verify_variants([a for a, _r in trio.values()], _reader(trio))
    assert evidence.common_movement_verified and evidence.controlled
    assert evidence.kind_label().startswith("Controlled")
    text = "\n".join(evidence.disclosures)
    assert "identical movement key" in text and "no body shape" in text and "not prove" in text
    binding = evidence.binding_for("k")
    assert (
        binding["representation"] == "rendered_skeleton"
        and binding["movement_key"] == evidence.movement_key
    )
    assert evidence.binding_for("missing") is None


def test_a_changed_parameter_breaks_the_controlled_claim_and_is_named():
    trio = _trio()
    side_plan = _plan(profile=cp.PROFILE_SKELETON, camera=cp.CAMERA_SIDE)
    side = _asset(
        "k", side_plan, _record(side_plan, video_sha="k" * 64, character_mode="skeleton_only")
    )
    mixed = {"c": trio["c"], "s": trio["s"], "k": side}
    evidence = verify_variants([a for a, _r in mixed.values()], _reader(mixed))
    assert not evidence.common_movement_verified and not evidence.controlled
    assert evidence.kind_label().startswith("Exploratory")
    assert any("same movement" in p for p in evidence.problems)
    assert evidence.binding_for("c") is None


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda r: r["output"].update(sha256="f" * 64), "different video bytes"),
        (lambda r: r["source"].update(sha256="b" * 64), "different animation file"),
        (lambda r: r.pop("plan"), "no plan"),
    ],
)
def test_a_record_that_disagrees_with_the_catalog_is_unverified(mutate, expected):
    trio = _trio()
    asset, record = trio["c"]
    mutate(record)
    evidence = verify_variant(asset, _reader(trio))
    assert not evidence.verified and expected in evidence.problem


def test_missing_provenance_and_unconverted_assets_are_unverified_not_assumed():
    trio = _trio()
    assert "missing" in verify_variant(trio["c"][0], lambda _p: None).problem
    plain = MotionAsset("p", "plain", "9" * 64, AssetLocator(LOCATOR_LINKED, "C:/x.mp4"))
    assert verify_variant(plain, _reader(trio)).problem == "not a converted clip"
    evidence = verify_variants([plain, trio["c"][0]], _reader(trio))
    assert not evidence.controlled and evidence.problems


def test_one_representation_alone_is_not_a_comparison():
    trio = _trio()
    alone = verify_variants([trio["c"][0]], _reader(trio))
    assert alone.common_movement_verified and not alone.controlled


def test_suite_bindings_naming_unknown_assets_are_a_reported_problem():
    trio = _trio()
    by_id = {k: a for k, (a, _r) in trio.items()}
    evidence = verify_bindings([{"asset_id": "c"}, {"asset_id": "ghost"}], by_id, _reader(trio))
    assert not evidence.controlled and any("ghost" in p for p in evidence.problems)
    ok = verify_bindings([{"asset_id": "c"}, {"asset_id": "s"}], by_id, _reader(trio))
    assert ok.controlled


def test_the_default_reader_refuses_an_oversized_or_missing_record(tmp_path):
    from src.video.motion_conversion.representation import MAX_RECORD_BYTES, _bounded_reader

    big = tmp_path / "provenance.json"
    big.write_bytes(b" " * (MAX_RECORD_BYTES + 1))
    assert _bounded_reader(str(big)) is None
    assert _bounded_reader(str(tmp_path / "missing.json")) is None
