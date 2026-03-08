"""Tests for rating persistence and retrieval."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_get_ratings_for_experiment():
    """Verify ratings can be retrieved for an experiment."""
    from src.learning.learning_record import LearningRecordWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)

        # Write some test records
        records = [
            {"metadata": {"experiment_name": "exp1", "image_path": "a.png", "user_rating": 4}},
            {"metadata": {"experiment_name": "exp1", "image_path": "b.png", "user_rating": 5}},
            {"metadata": {"experiment_name": "exp2", "image_path": "c.png", "user_rating": 3}},
        ]

        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        # Query ratings
        ratings = writer.get_ratings_for_experiment("exp1")

        assert len(ratings) == 2
        assert ratings["a.png"] == 4
        assert ratings["b.png"] == 5


def test_get_average_rating_for_variant():
    """Verify average rating calculation."""
    from src.learning.learning_record import LearningRecordWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)

        # Write records with multiple ratings for same variant
        records = [
            {"metadata": {"experiment_name": "exp", "variant_value": 7.0, "user_rating": 4}},
            {"metadata": {"experiment_name": "exp", "variant_value": 7.0, "user_rating": 5}},
            {"metadata": {"experiment_name": "exp", "variant_value": 8.0, "user_rating": 3}},
        ]

        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        avg = writer.get_average_rating_for_variant("exp", 7.0)
        assert avg == 4.5

        avg = writer.get_average_rating_for_variant("exp", 8.0)
        assert avg == 3.0


def test_is_image_rated():
    """Verify duplicate rating detection."""
    from src.learning.learning_record import LearningRecordWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)

        records = [
            {"metadata": {"experiment_name": "exp", "image_path": "rated.png", "user_rating": 4}},
        ]

        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        assert writer.is_image_rated("exp", "rated.png") is True
        assert writer.is_image_rated("exp", "unrated.png") is False


def test_get_ratings_empty_file():
    """Verify empty file handling."""
    from src.learning.learning_record import LearningRecordWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)

        # File doesn't exist yet
        ratings = writer.get_ratings_for_experiment("exp")
        assert len(ratings) == 0


def test_get_ratings_malformed_json():
    """Verify graceful handling of malformed records."""
    from src.learning.learning_record import LearningRecordWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)

        # Write malformed JSON
        with open(path, "w") as f:
            f.write("{invalid json}\n")
            f.write('{"metadata": {"experiment_name": "exp", "image_path": "a.png", "user_rating": 5}}\n')

        # Should skip malformed line and read valid one
        ratings = writer.get_ratings_for_experiment("exp")
        assert len(ratings) == 1
        assert ratings["a.png"] == 5


def test_get_average_rating_no_ratings():
    """Verify None returned when no ratings exist."""
    from src.learning.learning_record import LearningRecordWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)

        avg = writer.get_average_rating_for_variant("exp", 7.0)
        assert avg is None


def test_get_ratings_missing_fields():
    """Verify handling of records with missing rating or image_path fields."""
    from src.learning.learning_record import LearningRecordWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)

        records = [
            {"metadata": {"experiment_name": "exp", "image_path": "a.png"}},  # Missing rating
            {"metadata": {"experiment_name": "exp", "user_rating": 4}},  # Missing image_path
            {"metadata": {"experiment_name": "exp", "image_path": "b.png", "user_rating": 5}},  # Valid
        ]

        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        ratings = writer.get_ratings_for_experiment("exp")
        assert len(ratings) == 1
        assert ratings["b.png"] == 5
