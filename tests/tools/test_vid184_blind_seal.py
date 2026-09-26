"""PR-VID-184 arm-blinding: deterministic, filesystem-only (tmp_path) tests. No network, no real
media -- placeholder files stand in for output clips."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.qualification.vid184.blind_seal import seal, verify_mapping_hash


def _make_source(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_seal_produces_one_unique_id_per_entry_and_copies_files(tmp_path: Path) -> None:
    a = _make_source(tmp_path, "a.mp4", b"AAAA")
    b = _make_source(tmp_path, "b.mp4", b"BBBB")
    mapping, mapping_sha256 = seal(
        [("run1", a), ("run2", b)],
        blind_dir=tmp_path / "blind",
        mapping_path=tmp_path / "mapping.json",
    )
    assert set(mapping) == {"run1", "run2"}
    assert mapping["run1"] != mapping["run2"]
    sealed_files = list((tmp_path / "blind").iterdir())
    assert len(sealed_files) == 2
    assert mapping_sha256  # non-empty hex digest


def test_sealed_filenames_do_not_leak_the_run_label(tmp_path: Path) -> None:
    a = _make_source(tmp_path, "distilled_seed1.mp4", b"X")
    mapping, _ = seal(
        [("Distilled seed S1", a)],
        blind_dir=tmp_path / "blind",
        mapping_path=tmp_path / "mapping.json",
    )
    sealed_id = mapping["Distilled seed S1"]
    sealed_path = tmp_path / "blind" / f"{sealed_id}.mp4"
    assert sealed_path.exists()
    assert "distilled" not in sealed_path.name.lower()
    assert "seed" not in sealed_path.name.lower()


def test_verify_accepts_a_matching_hash_and_returns_the_real_mapping(tmp_path: Path) -> None:
    a = _make_source(tmp_path, "a.mp4", b"AAAA")
    mapping_path = tmp_path / "mapping.json"
    mapping, mapping_sha256 = seal(
        [("run1", a)], blind_dir=tmp_path / "blind", mapping_path=mapping_path
    )
    revealed = verify_mapping_hash(mapping_path, mapping_sha256)
    assert revealed == mapping


def test_verify_rejects_a_tampered_mapping(tmp_path: Path) -> None:
    a = _make_source(tmp_path, "a.mp4", b"AAAA")
    mapping_path = tmp_path / "mapping.json"
    _, mapping_sha256 = seal([("run1", a)], blind_dir=tmp_path / "blind", mapping_path=mapping_path)
    mapping_path.write_text('{"run1":"tampered0000"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        verify_mapping_hash(mapping_path, mapping_sha256)
