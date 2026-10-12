"""ControlNet weight header evidence (PR-IMG-CNET-210): SDXL is substantiated by shapes, never by a filename."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.assets import controlnet_structure as cs
from tests.conditioning.openpose_fixtures_210 import write_controlnet_weights


@pytest.mark.parametrize(
    ("family", "status"),
    [
        ("sdxl", cs.STATUS_SDXL),
        ("sdxl_original_layout", cs.STATUS_SDXL),
        ("sd15", cs.STATUS_NOT_SDXL),
        ("sd2", cs.STATUS_NOT_SDXL),
        ("unknown", cs.STATUS_UNVERIFIED),
        ("contradictory", cs.STATUS_UNVERIFIED),
    ],
)
def test_header_shapes_classify_the_family(tmp_path: Path, family: str, status: str) -> None:
    evidence = cs.inspect_controlnet_file(write_controlnet_weights(tmp_path / f"{family}.safetensors", family))

    assert evidence.status == status
    assert evidence.source == "safetensors_header"


def test_a_misleading_filename_is_not_evidence(tmp_path: Path) -> None:
    # The name says SDXL; the header says SD 1.x: the header wins.
    path = write_controlnet_weights(tmp_path / "controlnet-openpose-sdxl-1.0.safetensors", "sd15")
    # ... and a name that says nothing is still identified by its header.
    plain = write_controlnet_weights(tmp_path / "pose.safetensors", "sdxl")

    assert cs.inspect_controlnet_file(path).status == cs.STATUS_NOT_SDXL
    assert cs.inspect_controlnet_file(plain).status == cs.STATUS_SDXL


def test_unreadable_or_unsupported_containers_are_unverified_never_a_crash(tmp_path: Path) -> None:
    broken = tmp_path / "broken.safetensors"
    broken.write_bytes(b"\xff" * 64)
    pickle_like = tmp_path / "old.pth"
    pickle_like.write_bytes(b"not read")

    assert cs.inspect_controlnet_file(broken).status == cs.STATUS_UNVERIFIED
    assert cs.inspect_controlnet_file(pickle_like).status == cs.STATUS_UNVERIFIED
    assert cs.inspect_controlnet_file(tmp_path / "absent.safetensors").status == cs.STATUS_UNVERIFIED


def test_name_keys_ignore_hash_suffix_extension_path_and_case() -> None:
    assert cs.name_key("Sub/XINSIR_openpose_sdxl.safetensors [1a2b3c4d]") == "xinsir_openpose_sdxl"
    assert cs.name_key("xinsir_openpose_sdxl") == "xinsir_openpose_sdxl"
    assert cs.name_key("x.PTH") == "x"


def test_located_by_name_only_when_unambiguous(tmp_path: Path) -> None:
    root = tmp_path / "ControlNet"
    write_controlnet_weights(root / "xinsir_openpose_sdxl.safetensors", "sdxl")
    write_controlnet_weights(root / "dup.safetensors", "sdxl")
    write_controlnet_weights(root / "sub" / "dup.safetensors", "sd15")

    assert cs.locate_controlnet_file(root, "xinsir_openpose_sdxl [abcd1234]") == root / "xinsir_openpose_sdxl.safetensors"
    assert cs.locate_controlnet_file(root, "dup") is None  # two files: never pick one
    assert cs.locate_controlnet_file(root, "missing") is None
    assert cs.locate_controlnet_file(None, "x") is None
    assert cs.controlnet_evidence_for_name(root, "xinsir_openpose_sdxl").status == cs.STATUS_SDXL
    assert cs.controlnet_evidence_for_name(root, "missing").status == cs.STATUS_UNVERIFIED


def test_listing_reports_each_weight_with_its_evidence_and_never_hashes(tmp_path: Path) -> None:
    root = tmp_path / "ControlNet"
    write_controlnet_weights(root / "b_sdxl.safetensors", "sdxl")
    write_controlnet_weights(root / "a_old.safetensors", "sd15")
    (root / "notes.txt").write_text("not a weight")

    options = cs.list_controlnet_models(root)

    assert [(item.name, item.evidence.status) for item in options] == [
        ("a_old", cs.STATUS_NOT_SDXL),
        ("b_sdxl", cs.STATUS_SDXL),
    ]
    assert cs.list_controlnet_models(tmp_path / "absent") == []
    assert cs.list_controlnet_models(None) == []
