"""Tests for the global negative merging helper."""

from src.utils.negative_helpers_v2 import merge_global_negative


def test_merge_global_negative_appends_global_terms() -> None:
    original, final, applied, terms = merge_global_negative("clear prompt", "GLOBAL_BAD")
    assert original == "clear prompt"
    assert final == "clear prompt, GLOBAL_BAD"
    assert applied is True
    assert terms == "GLOBAL_BAD"


def test_merge_global_negative_handles_empty_global() -> None:
    original, final, applied, terms = merge_global_negative("target", "")
    assert original == "target"
    assert final == "target"
    assert applied is False
    assert terms == ""
