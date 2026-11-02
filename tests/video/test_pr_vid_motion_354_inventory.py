"""PR-VID-MOTION-354: inventory, FBX scan, archive safety, rig compatibility (no Blender, no GPU, no network)."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from src.video.motion_conversion import inventory as inv
from src.video.motion_conversion.archive_extract import (
    ArchiveRefused,
    extract_archive,
    safe_member_path,
)
from src.video.motion_conversion.fbx_scan import scan_fbx
from src.video.motion_conversion.rig_compat import (
    CORE_HUMANOID_BONES,
    FAMILY_MIXAMO,
    FAMILY_UNKNOWN,
    identify_rig,
    plan_binding,
)
from tests.helpers.motion_conversion_354 import MIXAMO_BONES, write_bvh, write_fbx


def _tree_state(root: Path) -> list[tuple[str, int, int]]:
    return sorted(
        (str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    )


def test_fbx_scan_distinguishes_character_skeleton_only_and_animation_only(tmp_path: Path) -> None:
    full = scan_fbx(write_fbx(tmp_path / "full.fbx"))
    skeleton = scan_fbx(write_fbx(tmp_path / "skel.fbx", mesh=False, skin=False))
    nothing = scan_fbx(write_fbx(tmp_path / "anim.fbx", mesh=False, skin=False, bones=()))
    static = scan_fbx(write_fbx(tmp_path / "static.fbx", curves=0))
    assert (full.has_mesh, full.has_skin, full.has_skeleton, full.has_animation) == (
        True,
        True,
        True,
        True,
    )
    assert (skeleton.has_mesh, skeleton.has_skeleton, skeleton.has_animation) == (False, True, True)
    assert (nothing.has_skeleton, nothing.has_animation) == (False, True)
    assert static.has_animation is False
    assert "mixamorig:Hips" in full.bone_names


def test_fbx_scan_refuses_corrupt_and_unknown_files_without_raising(tmp_path: Path) -> None:
    junk = tmp_path / "junk.fbx"
    junk.write_bytes(b"this is not an fbx file at all")
    truncated = tmp_path / "cut.fbx"
    truncated.write_bytes(write_fbx(tmp_path / "ok.fbx").read_bytes()[:90])
    ascii_fbx = tmp_path / "ascii.fbx"
    ascii_fbx.write_text("; FBX 7.4.0 project file\n", encoding="ascii")
    assert scan_fbx(junk).error
    assert scan_fbx(truncated).error
    assert scan_fbx(ascii_fbx).encoding == "ascii"
    assert scan_fbx(tmp_path / "missing.fbx").error


def test_inventory_classifies_every_family_and_never_modifies_the_originals(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    write_fbx(root / "Mixamo" / "walk.fbx")
    write_fbx(root / "Rokoko" / "skeleton.fbx", mesh=False, skin=False, bones=("Hips", "Spine"))
    write_fbx(root / "Rokoko" / "noskeleton.fbx", mesh=False, skin=False, bones=())
    write_bvh(root / "Rokoko" / "run.bvh")
    write_bvh(root / "Rokoko" / "bad.bvh", valid=False)
    (root / "Rokoko" / "x.asf").write_text(":version 1.10\n", encoding="utf-8")
    (root / "Rokoko" / "x.amc").write_text(":FULLY-SPECIFIED\n", encoding="utf-8")
    (root / "Rokoko" / "lonely.amc").write_text(":FULLY-SPECIFIED\n1 2 3\n", encoding="utf-8")
    (root / "Pexels").mkdir(parents=True)
    (root / "Pexels" / "walk.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42clip")
    (root / "Pexels" / "walk-copy.mov").write_bytes(b"\x00\x00\x00\x18ftypmp42clip")
    (root / "Rokoko" / "corrupt.fbx").write_bytes(b"garbage")
    (root / "notes.xyz").write_text("hello", encoding="utf-8")
    (root / ".DS_Store").write_bytes(b"x")
    before = _tree_state(root)

    report = inv.scan_inventory(root, probe_video=lambda p: {"fps": 24.0})
    by_name = {e.relative_path: e for e in report.entries}

    assert _tree_state(root) == before
    assert by_name["Mixamo/walk.fbx"].state == inv.STATE_READY
    assert by_name["Mixamo/walk.fbx"].route == inv.ROUTE_FBX_CHARACTER
    assert by_name["Mixamo/walk.fbx"].rig_family == FAMILY_MIXAMO
    assert by_name["Rokoko/skeleton.fbx"].route == inv.ROUTE_FBX_SKELETON
    assert by_name["Rokoko/noskeleton.fbx"].state == inv.STATE_MISSING_DEPENDENCY
    assert by_name["Rokoko/noskeleton.fbx"].missing_skeleton is True
    assert by_name["Rokoko/run.bvh"].route == inv.ROUTE_BVH_SKELETON
    assert by_name["Rokoko/bad.bvh"].state == inv.STATE_INVALID
    assert by_name["Rokoko/x.asf"].state == inv.STATE_UNSUPPORTED
    assert by_name["Rokoko/x.amc"].state == inv.STATE_UNSUPPORTED
    assert by_name["Rokoko/lonely.amc"].state == inv.STATE_MISSING_DEPENDENCY
    assert by_name["Rokoko/corrupt.fbx"].state == inv.STATE_INVALID
    assert by_name["notes.xyz"].state == inv.STATE_UNSUPPORTED
    assert ".DS_Store" not in by_name
    assert by_name["Pexels/walk.mp4"].state == inv.STATE_NOT_REQUIRED
    assert by_name["Pexels/walk.mp4"].importable_directly is True
    # same bytes under another name and another container extension are recognised as duplicate content
    # the first path in sorted order is the original; the later one points at it
    assert by_name["Pexels/walk-copy.mov"].duplicate_of == ""
    assert by_name["Pexels/walk.mp4"].duplicate_of == "Pexels/walk-copy.mov"
    summary = report.summary
    assert summary["duplicate_content"] == 1
    assert summary["by_source_family"]["Mixamo"] == 1
    assert report.representative_sample()
    assert "Blender: NOT installed" in inv.format_report(report)


def test_inventory_lists_archives_without_extracting_and_flags_unsafe_members(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    archive = root / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("clips/a.fbx", b"x")
        zf.writestr("../escape.fbx", b"x")
        zf.writestr("readme.txt", b"x")
    before = _tree_state(root)
    report = inv.scan_inventory(root)
    members = {e.relative_path: e for e in report.entries if e.in_archive}
    assert _tree_state(root) == before  # nothing extracted, nothing written
    assert members["pack.zip!clips/a.fbx"].state == inv.STATE_NEEDS_EXTRACTION
    assert members["pack.zip!clips/a.fbx"].importable_directly is False
    assert members["pack.zip!../escape.fbx"].state == inv.STATE_INVALID
    (root / "bad.zip").write_bytes(b"not a zip")
    assert {e.relative_path: e for e in inv.scan_inventory(root).entries}[
        "bad.zip"
    ].state == inv.STATE_INVALID


def test_inventory_report_is_plain_data_and_scan_requires_an_existing_folder(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assets"
    write_fbx(root / "a.fbx")
    record = inv.scan_inventory(root).to_record()
    assert record["schema"] == inv.SCHEMA
    assert record["entries"][0]["relative_path"] == "a.fbx"
    with pytest.raises(FileNotFoundError):
        inv.scan_inventory(tmp_path / "nope")


def test_inventory_cancel_stops_early(tmp_path: Path) -> None:
    import threading

    root = tmp_path / "assets"
    write_fbx(root / "a.fbx")
    stop = threading.Event()
    stop.set()
    assert inv.scan_inventory(root, cancel=stop).cancelled is True


# ------------------------------------------------------------------ archive extraction


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_extract_archive_writes_only_motion_files_into_a_new_folder(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "a.zip", {"clips/walk.fbx": b"FBXDATA", "readme.txt": b"skip me"})
    report = extract_archive(archive, tmp_path / "out")
    assert [f.relative_path for f in report.files] == ["clips/walk.fbx"]
    assert report.skipped_unsupported == 1
    assert (tmp_path / "out" / "clips" / "walk.fbx").read_bytes() == b"FBXDATA"
    assert not list((tmp_path / "out").rglob("*.partial"))


@pytest.mark.parametrize(
    "name",
    [
        "../evil.fbx",
        "/abs/evil.fbx",
        "C:/evil.fbx",
        "a/../../evil.fbx",
        "con.fbx",
        "a/nul.fbx",
        "x/a:b.fbx",
        "dots./a.fbx",
    ],
)
def test_extract_archive_refuses_unsafe_member_names_and_leaves_nothing(
    tmp_path: Path, name: str
) -> None:
    archive = _zip(tmp_path / "a.zip", {"ok.fbx": b"1", name: b"2"})
    with pytest.raises(ArchiveRefused):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "evil.fbx").exists()


def test_extract_archive_refuses_duplicates_links_nonempty_destination_and_bombs(
    tmp_path: Path,
) -> None:
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "keep.txt").write_text("mine", encoding="utf-8")
    simple = _zip(tmp_path / "s.zip", {"a.fbx": b"1"})
    with pytest.raises(ArchiveRefused, match="new or empty"):
        extract_archive(simple, tmp_path / "full")
    assert (tmp_path / "full" / "keep.txt").read_text(encoding="utf-8") == "mine"

    dup = tmp_path / "d.zip"
    with zipfile.ZipFile(dup, "w") as zf:
        zf.writestr("A.fbx", b"1")
        zf.writestr("a.fbx", b"2")
    with pytest.raises(ArchiveRefused, match="Duplicate"):
        extract_archive(dup, tmp_path / "d1")

    link = tmp_path / "l.zip"
    with zipfile.ZipFile(link, "w") as zf:
        info = zipfile.ZipInfo("sneaky.fbx")
        info.external_attr = (0o120777) << 16
        zf.writestr(info, "target")
    with pytest.raises(ArchiveRefused, match="Links"):
        extract_archive(link, tmp_path / "l1")

    bomb = _zip(tmp_path / "b.zip", {"big.fbx": b"\x00" * (5 * 1024 * 1024)})
    with pytest.raises(ArchiveRefused, match="compression ratio"):
        extract_archive(bomb, tmp_path / "b1")


def test_extract_archive_refuses_when_the_declared_size_lies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _zip(tmp_path / "a.zip", {"a.fbx": b"x" * 100})
    monkeypatch.setattr("src.video.motion_conversion.archive_extract.MAX_TOTAL_BYTES", 50)
    with pytest.raises(ArchiveRefused):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_safe_member_path_accepts_ordinary_names() -> None:
    assert safe_member_path("Pack\\Idle (2).fbx").as_posix() == "Pack/Idle (2).fbx"


# ------------------------------------------------------------------ rig compatibility


def test_rig_identity_recognises_mixamo_and_nothing_else() -> None:
    assert identify_rig(MIXAMO_BONES).family == FAMILY_MIXAMO
    assert identify_rig(["Hips", "Spine"]).family == FAMILY_UNKNOWN
    assert (
        identify_rig(MIXAMO_BONES).fingerprint == identify_rig(reversed(MIXAMO_BONES)).fingerprint
    )


def test_binding_is_compatible_for_identical_rigs_and_records_dropped_fingers() -> None:
    source = [*MIXAMO_BONES, "mixamorig:LeftHandPinky3"]
    target = list(MIXAMO_BONES)
    plan = plan_binding(source, target)
    assert plan.compatible is True
    assert plan.dropped_optional == ("mixamorig:LeftHandPinky3",)
    assert all(a == b for a, b in plan.mapping)


def test_binding_refuses_missing_core_unmapped_required_and_ambiguous_names() -> None:
    missing = [b for b in MIXAMO_BONES if not b.endswith("LeftFoot")]
    assert plan_binding(MIXAMO_BONES, missing).compatible is False
    assert "LeftFoot" in plan_binding(MIXAMO_BONES, missing).missing_core
    extra_required = [*MIXAMO_BONES, "mixamorig:Tail1"]
    refused = plan_binding(extra_required, MIXAMO_BONES)
    assert refused.compatible is False and refused.unmapped_required == ("mixamorig:Tail1",)
    ambiguous = plan_binding(MIXAMO_BONES, [*MIXAMO_BONES, "mixamorig1:Hips"])
    assert ambiguous.compatible is False and ambiguous.ambiguous
    assert plan_binding([], MIXAMO_BONES).compatible is False
    assert len(CORE_HUMANOID_BONES) == 22


def test_asset_root_is_never_a_requirement_for_import_time(tmp_path: Path) -> None:
    # importing the package must have no filesystem side effects
    before = set(os.listdir(tmp_path))
    import importlib

    importlib.reload(inv)
    assert set(os.listdir(tmp_path)) == before
