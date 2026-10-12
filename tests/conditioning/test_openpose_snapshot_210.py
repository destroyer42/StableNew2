"""Frozen OpenPose conditioning and its job-owned snapshot (PR-IMG-CNET-210): identity, immutability, verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.conditioning import openpose as op
from src.conditioning import openpose_library as lib
from src.conditioning import openpose_snapshot as snap
from tests.conditioning.openpose_fixtures_210 import make_library, png_bytes


def _selection(asset: str = "Standing/relaxed.png", **overrides) -> op.OpenPoseSelection:
    values = {"asset": asset, "model": "xinsir_openpose_sdxl"}
    values.update(overrides)
    return op.OpenPoseSelection(**values)


def test_freeze_records_verified_identity_and_a_content_addressed_snapshot(tmp_path: Path) -> None:
    data = png_bytes(256, 384)
    library = make_library(tmp_path, {"Standing/relaxed.png": data})
    root = tmp_path / "snapshots"

    frozen = snap.freeze_selection(_selection(weight=0.8), library=library, snapshot_root=root)

    digest = hashlib.sha256(data).hexdigest()
    assert (frozen.asset, frozen.asset_sha256, frozen.asset_size) == ("Standing/relaxed.png", digest, len(data))
    assert (frozen.width, frozen.height, frozen.image_format) == (256, 384, "PNG")
    assert Path(frozen.snapshot_path) == root / f"{digest}.png"
    assert Path(frozen.snapshot_path).read_bytes() == data
    assert frozen.weight == 0.8 and frozen.model == "xinsir_openpose_sdxl"


def test_the_frozen_config_is_json_serializable_and_contains_no_image_bytes(tmp_path: Path) -> None:
    data = png_bytes()
    library = make_library(tmp_path, {"a.png": data})
    frozen = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=tmp_path / "s")

    config = frozen.to_config()
    text = json.dumps(config)

    import base64

    assert base64.b64encode(data).decode("ascii")[:64] not in text
    assert config["contract"] == "openpose.v1" and config["stage"] == "txt2img"
    assert config["snapshot"] == {"path": frozen.snapshot_path}
    assert config["pixel_perfect"] is False and config["preprocessor"] == "None"
    assert snap.FrozenOpenPose.from_config(json.loads(text)) == frozen  # lossless through JSON


def test_replacing_the_library_file_cannot_change_a_frozen_job(tmp_path: Path) -> None:
    original = png_bytes(color=(1, 2, 3))
    library = make_library(tmp_path, {"a.png": original})
    frozen = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=tmp_path / "s")

    (library / "a.png").write_bytes(png_bytes(color=(250, 0, 0)))  # same name, different bytes

    assert snap.verify_frozen(frozen) == original


def test_a_new_freeze_of_the_replaced_file_gets_its_own_snapshot(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.png": png_bytes(color=(1, 2, 3))})
    first = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=tmp_path / "s")
    (library / "a.png").write_bytes(png_bytes(color=(250, 0, 0)))

    second = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=tmp_path / "s")

    assert first.asset_sha256 != second.asset_sha256
    assert first.snapshot_path != second.snapshot_path


def test_identical_bytes_under_two_names_share_one_snapshot(tmp_path: Path) -> None:
    data = png_bytes()
    library = make_library(tmp_path, {"a.png": data, "Walking/b.png": data})
    root = tmp_path / "s"

    first = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=root)
    second = snap.freeze_selection(_selection("Walking/b.png"), library=library, snapshot_root=root)

    assert first.snapshot_path == second.snapshot_path
    assert (first.asset, second.asset) == ("a.png", "Walking/b.png")  # identity of the choice is preserved


def test_a_changed_or_deleted_snapshot_refuses_dispatch(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.png": png_bytes()})
    frozen = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=tmp_path / "s")
    path = Path(frozen.snapshot_path)

    path.write_bytes(png_bytes(color=(9, 9, 9)))
    with pytest.raises(lib.OpenPoseInputError) as changed:
        snap.verify_frozen(frozen)
    assert changed.value.code == lib.CODE_CHANGED

    path.unlink()
    with pytest.raises(lib.OpenPoseInputError) as missing:
        snap.verify_frozen(frozen)
    assert missing.value.code == lib.CODE_MISSING


def test_a_corrupt_content_addressed_file_is_replaced_by_the_verified_bytes(tmp_path: Path) -> None:
    data = png_bytes()
    library = make_library(tmp_path, {"a.png": data})
    root = tmp_path / "s"
    first = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=root)
    Path(first.snapshot_path).write_bytes(b"corrupted")

    again = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=root)

    assert again.snapshot_path == first.snapshot_path
    assert snap.verify_frozen(again) == data


def test_freezing_requires_a_model_and_a_valid_image(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.png": png_bytes(), "bad.png": b"nope"})

    with pytest.raises(ValueError, match="ControlNet model"):
        snap.freeze_selection(_selection("a.png", model=""), library=library, snapshot_root=tmp_path / "s")
    with pytest.raises(lib.OpenPoseInputError):
        snap.freeze_selection(_selection("bad.png"), library=library, snapshot_root=tmp_path / "s")
    assert not (tmp_path / "s").exists() or not any((tmp_path / "s").glob("*.png"))  # nothing published


def test_from_config_is_strict(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.png": png_bytes()})
    good = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=tmp_path / "s").to_config()

    def broken(**changes):
        value = json.loads(json.dumps(good))
        for key, replacement in changes.items():
            if replacement is None:
                value.pop(key, None)
            else:
                value[key] = replacement
        return value

    for bad in (
        broken(enabled=False),
        broken(stage="img2img"),
        broken(asset_sha256="XYZ"),
        broken(asset_size=0),
        broken(pixel_perfect=True),
        broken(model=""),
        broken(snapshot={"path": "C:/elsewhere/not_the_digest.png"}),
        broken(image={"width": 0, "height": 5, "format": "PNG"}),
        broken(surprise=1),
        broken(weight=99),
    ):
        with pytest.raises(op.OpenPoseDeclarationError):
            snap.FrozenOpenPose.from_config(bad)
    with pytest.raises(op.OpenPoseDeclarationError):
        snap.FrozenOpenPose.from_config(None)


def test_evidence_is_content_and_path_free(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.png": png_bytes()})
    frozen = snap.freeze_selection(_selection("a.png"), library=library, snapshot_root=tmp_path / "s")

    evidence = frozen.evidence()

    assert "snapshot" not in evidence and str(tmp_path) not in json.dumps(evidence)
    assert evidence["asset_sha256"] == frozen.asset_sha256 and evidence["model"] == frozen.model
