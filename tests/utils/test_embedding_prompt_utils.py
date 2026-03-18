"""Tests for embedding_prompt_utils helper functions."""

from __future__ import annotations

import pytest

from src.utils.embedding_prompt_utils import (
    extract_embedding_entries,
    normalize_embedding_entries,
    render_embedding_reference,
    serialize_embedding_entries,
    strip_embedding_entries,
)


class TestRenderEmbeddingReference:
    def test_plain_weight_omits_parens(self):
        assert render_embedding_reference("myEmbed", 1.0) == "<embedding:myEmbed>"

    def test_fractional_weight_uses_parens(self):
        assert render_embedding_reference("myEmbed", 0.8) == "(<embedding:myEmbed>:0.8)"

    def test_over_one_weight(self):
        assert render_embedding_reference("myEmbed", 1.2) == "(<embedding:myEmbed>:1.2)"

    def test_empty_name_returns_empty(self):
        assert render_embedding_reference("", 1.0) == ""

    def test_default_weight_is_one(self):
        assert render_embedding_reference("x") == "<embedding:x>"


class TestExtractEmbeddingEntries:
    def test_plain_embedding(self):
        entries = extract_embedding_entries("<embedding:alpha>")
        assert entries == [("alpha", 1.0)]

    def test_weighted_embedding(self):
        entries = extract_embedding_entries("(<embedding:alpha>:0.8)")
        assert entries == [("alpha", 0.8)]

    def test_mixed_plain_and_weighted(self):
        entries = extract_embedding_entries("(<embedding:a>:0.7) <embedding:b>")
        assert ("a", 0.7) in entries
        assert ("b", 1.0) in entries

    def test_no_duplicates_on_weighted(self):
        """Weighted form should not produce a duplicate plain match."""
        entries = extract_embedding_entries("(<embedding:x>:0.5)")
        names = [name for name, _ in entries]
        assert names.count("x") == 1

    def test_empty_string(self):
        assert extract_embedding_entries("") == []


class TestStripEmbeddingEntries:
    def test_strips_plain(self):
        assert strip_embedding_entries("<embedding:foo> some text") == "some text"

    def test_strips_weighted(self):
        assert strip_embedding_entries("(<embedding:foo>:0.8) some text") == "some text"

    def test_empty_string(self):
        assert strip_embedding_entries("") == ""


class TestNormalizeEmbeddingEntries:
    def test_string_gets_weight_one(self):
        assert normalize_embedding_entries(["alpha"]) == [("alpha", 1.0)]

    def test_tuple_preserved(self):
        assert normalize_embedding_entries([("alpha", 0.8)]) == [("alpha", 0.8)]

    def test_dict_form(self):
        assert normalize_embedding_entries([{"name": "x", "weight": 0.6}]) == [("x", 0.6)]

    def test_none_returns_empty(self):
        assert normalize_embedding_entries(None) == []

    def test_empty_name_skipped(self):
        assert normalize_embedding_entries([""]) == []


class TestSerializeEmbeddingEntries:
    def test_weight_one_serializes_as_string(self):
        result = serialize_embedding_entries([("alpha", 1.0)])
        assert result == ["alpha"]

    def test_non_unit_weight_serializes_as_list(self):
        result = serialize_embedding_entries([("alpha", 0.8)])
        assert result == [["alpha", 0.8]]

    def test_round_trip(self):
        original = [("a", 1.0), ("b", 0.75)]
        serialized = serialize_embedding_entries(original)
        restored = normalize_embedding_entries(serialized)
        assert restored == original
