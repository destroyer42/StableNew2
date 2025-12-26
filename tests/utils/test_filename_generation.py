"""
Unit tests for filename generation (PR-FILENAME-001).

Tests human-readable filename convention with 1-based indexing,
pack names, and proper sanitization.
"""

import pytest
from src.utils.file_io import build_safe_image_name


def test_one_based_indexing():
    """Verify 1-based indexing for batch numbers."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        batch_index=0,  # Internal 0-based
        pack_name="TestPack"
    )
    assert "batch1" in name, f"Expected batch1 in {name}"
    assert "batch0" not in name, f"Should not have batch0 in {name}"


def test_zero_based_indexing_disabled():
    """Verify 0-based indexing when use_one_based_indexing=False."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        batch_index=0,
        pack_name="TestPack",
        use_one_based_indexing=False
    )
    assert "batch0" in name, f"Expected batch0 in {name}"
    assert "batch1" not in name, f"Should not have batch1 in {name}"


def test_pack_name_truncation():
    """Verify pack name truncated to 10 chars."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="VeryLongPromptPackName_v2.5"
    )
    # Should be truncated to ~10 chars
    parts = name.split("_")
    # Format: txt2img_p01_v01_<PACK>
    assert len(parts) >= 4, f"Expected at least 4 parts in {name}"
    pack_part = parts[3]  # txt2img_p01_v01_<PACK>
    assert len(pack_part) <= 10, f"Pack name '{pack_part}' should be <= 10 chars"


def test_pack_name_sanitization():
    """Verify special characters sanitized."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="Fantasy/Heroes:v2!"
    )
    # Should be safe filename
    assert "/" not in name, f"Should not have '/' in {name}"
    assert ":" not in name, f"Should not have ':' in {name}"
    assert "!" not in name, f"Should not have '!' in {name}"


def test_fallback_to_hash_when_no_pack():
    """Verify hash used when pack name unavailable."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name=None,
        seed=12345
    )
    # Should contain 8-char hex hash
    parts = name.split("_")
    # Format: txt2img_p01_v01_<HASH>
    assert len(parts) >= 4, f"Expected at least 4 parts in {name}"
    hash_part = parts[3]
    assert len(hash_part) == 8, f"Hash '{hash_part}' should be 8 chars"
    assert all(c in "0123456789abcdef" for c in hash_part.lower()), \
        f"Hash '{hash_part}' should be hexadecimal"


def test_fallback_to_hash_when_empty_pack():
    """Verify hash used when pack name is empty string."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="",
        seed=12345
    )
    # Should fall back to hash
    parts = name.split("_")
    hash_part = parts[3]
    assert len(hash_part) == 8, f"Hash '{hash_part}' should be 8 chars"


def test_no_redundant_stage_suffix():
    """Verify stage name only appears once (prefix)."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="TestPack"
    )
    # Count occurrences of "txt2img"
    occurrences = name.count("txt2img")
    assert occurrences == 1, f"Expected 1 occurrence of 'txt2img', found {occurrences} in {name}"


def test_batch_index_none():
    """Verify no batch suffix when batch_index is None."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="TestPack",
        batch_index=None
    )
    assert "batch" not in name, f"Should not have 'batch' in {name}"


def test_matrix_values_in_hash():
    """Verify matrix values affect hash when no pack name."""
    name1 = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        matrix_values={"hair": "blonde", "eyes": "blue"},
        pack_name=None
    )
    name2 = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        matrix_values={"hair": "brown", "eyes": "green"},
        pack_name=None
    )
    # Different matrix values should produce different hashes
    assert name1 != name2, "Different matrix values should produce different filenames"


def test_pack_name_preferred_over_hash():
    """Verify pack name used instead of hash when available."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="MyPack",
        seed=12345,
        matrix_values={"test": "value"}
    )
    assert "MyPack" in name, f"Expected 'MyPack' in {name}"
    # Should NOT contain an 8-char hex hash
    parts = name.split("_")
    pack_part = parts[3]
    # MyPack should be there, not a hex hash
    assert not all(c in "0123456789abcdef" for c in pack_part.lower()), \
        f"Should use pack name, not hash in {name}"


def test_max_length_enforcement():
    """Verify filename truncated to max_length."""
    very_long_prefix = "txt2img_" + "x" * 200
    name = build_safe_image_name(
        base_prefix=very_long_prefix,
        pack_name="TestPack",
        batch_index=5,
        max_length=50
    )
    # Total length should be <= 50
    assert len(name) <= 50, f"Filename length {len(name)} exceeds max_length 50"


def test_whitespace_stripped_from_pack_name():
    """Verify leading/trailing whitespace stripped from pack name."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="  TestPack  "
    )
    assert "TestPack" in name, f"Expected 'TestPack' in {name}"


def test_seed_affects_hash():
    """Verify different seeds produce different hashes when no pack name."""
    name1 = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name=None,
        seed=12345
    )
    name2 = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name=None,
        seed=67890
    )
    assert name1 != name2, "Different seeds should produce different filenames"


def test_full_filename_example():
    """Verify example from PR spec matches expected format."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="Fantasy_Heroes_v2",
        batch_index=0
    )
    # Expected: "txt2img_p01_v01_FantasyHer_batch1"
    assert name.startswith("txt2img_p01_v01_"), f"Wrong prefix in {name}"
    assert "batch1" in name, f"Missing batch1 in {name}"
    assert "Fantasy" in name or "FantasyHer" in name, f"Missing pack name in {name}"
