"""
Unit tests for collision failsafe (PR-FILENAME-001).

Tests get_unique_output_path() function that prevents file overwrites
by appending _copy1, _copy2, etc.
"""

import pytest
from pathlib import Path
from src.utils.file_io import get_unique_output_path


def test_no_collision_returns_original(tmp_path):
    """Verify original path returned when no collision."""
    test_file = tmp_path / "test.png"
    result = get_unique_output_path(test_file)
    assert result == test_file, f"Expected {test_file}, got {result}"


def test_collision_appends_copy1(tmp_path):
    """Verify _copy1 appended on collision."""
    test_file = tmp_path / "test.png"
    test_file.touch()  # Create collision
    
    result = get_unique_output_path(test_file)
    assert result.name == "test_copy1.png", f"Expected test_copy1.png, got {result.name}"
    assert not result.exists(), f"Result path should not exist yet"


def test_multiple_collisions(tmp_path):
    """Verify _copy2, _copy3, etc. on multiple collisions."""
    test_file = tmp_path / "test.png"
    test_file.touch()
    (tmp_path / "test_copy1.png").touch()
    (tmp_path / "test_copy2.png").touch()
    
    result = get_unique_output_path(test_file)
    assert result.name == "test_copy3.png", f"Expected test_copy3.png, got {result.name}"
    assert not result.exists(), f"Result path should not exist yet"


def test_max_attempts_exceeded(tmp_path):
    """Verify ValueError when max attempts exceeded."""
    test_file = tmp_path / "test.png"
    test_file.touch()
    
    # Create 10 collision files (test with smaller max_attempts)
    for i in range(1, 11):
        (tmp_path / f"test_copy{i}.png").touch()
    
    with pytest.raises(ValueError, match="Could not find unique filename"):
        get_unique_output_path(test_file, max_attempts=10)


def test_preserves_extension(tmp_path):
    """Verify file extension preserved correctly."""
    test_file = tmp_path / "test.json"
    test_file.touch()
    
    result = get_unique_output_path(test_file)
    assert result.suffix == ".json", f"Expected .json extension, got {result.suffix}"
    assert result.name == "test_copy1.json", f"Expected test_copy1.json, got {result.name}"


def test_complex_filename_with_underscores(tmp_path):
    """Verify correct handling of filenames with multiple underscores."""
    test_file = tmp_path / "txt2img_p01_v01_FantasyHer_batch1.png"
    test_file.touch()
    
    result = get_unique_output_path(test_file)
    assert result.name == "txt2img_p01_v01_FantasyHer_batch1_copy1.png", \
        f"Expected correct _copy1 suffix, got {result.name}"


def test_works_with_absolute_paths(tmp_path):
    """Verify function works with absolute paths."""
    test_file = tmp_path / "subdir" / "test.png"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()
    
    result = get_unique_output_path(test_file)
    assert result.is_absolute(), "Result should be absolute path"
    assert result.parent == test_file.parent, "Parent directory should be preserved"
    assert result.name == "test_copy1.png"


def test_gap_in_sequence(tmp_path):
    """Verify fills first available slot even with gaps."""
    test_file = tmp_path / "test.png"
    test_file.touch()
    (tmp_path / "test_copy1.png").touch()
    # Gap: test_copy2.png doesn't exist
    (tmp_path / "test_copy3.png").touch()
    
    result = get_unique_output_path(test_file)
    assert result.name == "test_copy2.png", \
        f"Should fill gap at copy2, got {result.name}"


def test_no_extension_file(tmp_path):
    """Verify works with files without extension."""
    test_file = tmp_path / "README"
    test_file.touch()
    
    result = get_unique_output_path(test_file)
    assert result.name == "README_copy1", f"Expected README_copy1, got {result.name}"


def test_collision_with_directory(tmp_path):
    """Verify collision detected even if path is directory."""
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    
    result = get_unique_output_path(test_dir)
    assert result.name == "test_copy1", f"Expected test_copy1, got {result.name}"


def test_large_counter(tmp_path):
    """Verify handles large counter values correctly."""
    test_file = tmp_path / "test.png"
    test_file.touch()
    
    # Create copies 1-49
    for i in range(1, 50):
        (tmp_path / f"test_copy{i}.png").touch()
    
    result = get_unique_output_path(test_file)
    assert result.name == "test_copy50.png", f"Expected copy50, got {result.name}"


def test_nested_directory_structure(tmp_path):
    """Verify works with deeply nested directories."""
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True, exist_ok=True)
    test_file = nested / "test.png"
    test_file.touch()
    
    result = get_unique_output_path(test_file)
    assert result.parent == nested, "Parent should be preserved"
    assert result.name == "test_copy1.png"


def test_utf8_filename(tmp_path):
    """Verify handles UTF-8 filenames correctly."""
    test_file = tmp_path / "テスト_画像.png"
    test_file.touch()
    
    result = get_unique_output_path(test_file)
    assert result.name == "テスト_画像_copy1.png", \
        f"UTF-8 filename should be preserved: {result.name}"


def test_special_chars_in_stem(tmp_path):
    """Verify handles special characters in filename stem."""
    test_file = tmp_path / "image-2024.12.25.png"
    test_file.touch()
    
    result = get_unique_output_path(test_file)
    assert result.name == "image-2024.12.25_copy1.png", \
        f"Special chars should be preserved: {result.name}"
