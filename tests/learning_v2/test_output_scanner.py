# Tests: Learning subsystem
# PR: PR-CORE-LEARN-040 — Output scanner and grouping engine

"""Tests for OutputScanner — manifest-first artifact scanning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.learning.discovered_review_models import OutputScanIndexEntry
from src.learning.output_scan_models import ScanRecord
from src.learning.output_scanner import (
    OutputScanner,
    _manifest_scan_key,
    _normalize_prompt,
    _prompt_hash,
    _record_from_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    path: Path,
    stage: str = "txt2img",
    model: str = "sd_xl_base_1.0",
    sampler: str = "Euler",
    scheduler: str = "Normal",
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 12345,
    prompt: str = "a fantasy knight",
    neg: str = "",
    width: int = 832,
    height: int = 1216,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "stage_manifest": {
            "stage": stage,
            "model": model,
            "sampler_name": sampler,
            "scheduler": scheduler,
            "steps": steps,
            "cfg_scale": cfg,
            "seed": seed,
            "width": width,
            "height": height,
            "prompt": prompt,
            "negative_prompt": neg,
        }
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _make_image(img_path: Path) -> Path:
    """Create a minimal 1×1 PNG so the file exists."""
    import struct, zlib
    img_path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal valid 1x1 PNG bytes
    sig = b'\x89PNG\r\n\x1a\n'
    def chunk(ctype, data):
        c = struct.pack('>I', len(data)) + ctype + data
        return c + struct.pack('>I', zlib.crc32(ctype + data) & 0xffffffff)
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff'))
    iend = chunk(b'IEND', b'')
    img_path.write_bytes(sig + ihdr + idat + iend)
    return img_path


def _make_scan_fixture(tmp_path: Path, stem: str = "img001", **kwargs) -> tuple[Path, Path]:
    """Create a manifest+image pair and return (manifest_path, image_path)."""
    run_dir = tmp_path / "run1"
    manifests_dir = run_dir / "manifests"
    manifest_path = manifests_dir / f"{stem}.json"
    image_path = run_dir / f"{stem}.png"
    _make_manifest(manifest_path, **kwargs)
    _make_image(image_path)
    return manifest_path, image_path


# ---------------------------------------------------------------------------
# Prompt normalization
# ---------------------------------------------------------------------------


def test_normalize_prompt_strips_whitespace():
    assert _normalize_prompt("  sword ,  knight  ") == "sword,knight"


def test_normalize_prompt_lowercases():
    assert _normalize_prompt("Fantasy Knight").lower() == _normalize_prompt("fantasy knight")


def test_normalize_prompt_empty():
    assert _normalize_prompt("") == ""


def test_prompt_hash_same_prompts():
    h1 = _prompt_hash("a fantasy knight", "blurry")
    h2 = _prompt_hash("a fantasy knight", "blurry")
    assert h1 == h2


def test_prompt_hash_different_prompts():
    h1 = _prompt_hash("a fantasy knight", "")
    h2 = _prompt_hash("a dragon", "")
    assert h1 != h2


def test_prompt_hash_case_insensitive():
    h1 = _prompt_hash("A Fantasy Knight", "")
    h2 = _prompt_hash("a fantasy knight", "")
    assert h1 == h2


# ---------------------------------------------------------------------------
# Record construction from manifest
# ---------------------------------------------------------------------------


def test_record_from_manifest_basic(tmp_path):
    mp, ip = _make_scan_fixture(tmp_path)
    record = _record_from_manifest(mp, ip)
    assert record is not None
    assert record.stage == "txt2img"
    assert record.model == "sd_xl_base_1.0"
    assert record.steps == 20
    assert record.positive_prompt == "a fantasy knight"
    assert record.prompt_hash != ""
    assert record.dedupe_key != ""


def test_record_from_manifest_sets_scan_source(tmp_path):
    mp, ip = _make_scan_fixture(tmp_path)
    record = _record_from_manifest(mp, ip)
    assert record.scan_source == "manifest"


def test_record_from_missing_manifest(tmp_path):
    fake = tmp_path / "manifests" / "ghost.json"
    fake_img = tmp_path / "ghost.png"
    result = _record_from_manifest(fake, fake_img)
    assert result is None


def test_record_from_empty_manifest(tmp_path):
    mp = tmp_path / "manifests" / "empty.json"
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text("{}", encoding="utf-8")
    ip = tmp_path / "empty.png"
    # An empty JSON object is falsy in Python — scanner treats it as unreadable
    result = _record_from_manifest(mp, ip)
    assert result is None


def test_manifest_scan_key_stable(tmp_path):
    mp = tmp_path / "manifests" / "img.json"
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text('{"a": 1}', encoding="utf-8")
    k1 = _manifest_scan_key(mp)
    k2 = _manifest_scan_key(mp)
    assert k1 == k2
    assert len(k1) == 16


def test_manifest_scan_key_changes_on_modification(tmp_path):
    mp = tmp_path / "manifests" / "img.json"
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text('{"a": 1}', encoding="utf-8")
    k1 = _manifest_scan_key(mp)
    mp.write_text('{"a": 2}', encoding="utf-8")
    k2 = _manifest_scan_key(mp)
    assert k1 != k2


# ---------------------------------------------------------------------------
# OutputScanner.scan_incremental
# ---------------------------------------------------------------------------


def test_scanner_finds_new_artifact(tmp_path):
    _make_scan_fixture(tmp_path, "img001")
    scanner = OutputScanner(tmp_path)
    records = scanner.scan_incremental()
    assert len(records) == 1
    assert records[0].stage == "txt2img"


def test_scanner_skips_already_indexed(tmp_path):
    mp, ip = _make_scan_fixture(tmp_path, "img001")
    scan_key = _manifest_scan_key(mp)
    existing_index = {str(ip): OutputScanIndexEntry(str(ip), scan_key, "2026-01-01T00:00:00Z")}
    scanner = OutputScanner(tmp_path, scan_index=existing_index)
    records = scanner.scan_incremental()
    assert len(records) == 0


def test_scanner_rescans_changed_manifest(tmp_path):
    mp, ip = _make_scan_fixture(tmp_path, "img001")
    old_key = "stale_key"
    existing_index = {str(ip): OutputScanIndexEntry(str(ip), old_key, "2026-01-01T00:00:00Z")}
    scanner = OutputScanner(tmp_path, scan_index=existing_index)
    records = scanner.scan_incremental()
    assert len(records) == 1


def test_scanner_multiple_artifacts(tmp_path):
    for i in range(4):
        _make_scan_fixture(tmp_path, f"img{i:03d}", seed=i * 100)
    scanner = OutputScanner(tmp_path)
    records = scanner.scan_incremental()
    assert len(records) == 4


def test_scanner_scan_full_returns_all(tmp_path):
    for i in range(3):
        _make_scan_fixture(tmp_path, f"img{i:03d}")
    # Pre-index 1 artifact
    mp = tmp_path / "run1" / "manifests" / "img000.json"
    ip = tmp_path / "run1" / "img000.png"
    scan_key = _manifest_scan_key(mp)
    existing_index = {str(ip): OutputScanIndexEntry(str(ip), scan_key, "2026-01-01T00:00:00Z")}
    scanner = OutputScanner(tmp_path, scan_index=existing_index)
    # scan_full ignores the index
    records = scanner.scan_full()
    assert len(records) == 3


def test_scanner_mark_group_assignment(tmp_path):
    mp, ip = _make_scan_fixture(tmp_path, "img001")
    scan_key = _manifest_scan_key(mp)
    scanner = OutputScanner(tmp_path)
    scanner.mark_group_assignment(str(ip), scan_key, group_id="g-001", eligible=True)
    index = scanner.get_updated_index()
    assert str(ip) in index
    assert index[str(ip)].group_id == "g-001"
    assert index[str(ip)].eligible is True


def test_scanner_deterministic_order(tmp_path):
    for i in range(5):
        _make_scan_fixture(tmp_path, f"img{i:03d}", seed=i * 10)
    
    scanner1 = OutputScanner(tmp_path)
    records1 = scanner1.scan_incremental()
    scanner2 = OutputScanner(tmp_path)
    records2 = scanner2.scan_incremental()
    
    assert [r.artifact_path for r in records1] == [r.artifact_path for r in records2]


def test_scanner_scan_full_finds_artifacts_across_output_routes(tmp_path):
    _make_scan_fixture(tmp_path / "Pipeline", "pipe001")
    _make_scan_fixture(tmp_path / "Testing", "test001")
    _make_scan_fixture(tmp_path / "SVD", "svd001")

    scanner = OutputScanner(tmp_path)
    records = scanner.scan_full()

    artifact_names = {Path(record.artifact_path).name for record in records}
    assert artifact_names == {"pipe001.png", "test001.png", "svd001.png"}


def test_scanner_scan_incremental_finds_artifacts_across_output_routes(tmp_path):
    _make_scan_fixture(tmp_path / "Pipeline", "pipe001")
    _make_scan_fixture(tmp_path / "Testing", "test001")

    scanner = OutputScanner(tmp_path)
    records = scanner.scan_incremental()

    artifact_names = {Path(record.artifact_path).name for record in records}
    assert artifact_names == {"pipe001.png", "test001.png"}
