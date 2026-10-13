"""PR-LEARN-COMPARE-145: the acceptance intent digest ignores minted batch identity, not execution intent.

PR-REVIEW-BATCH-200 mints a fresh random ``batch_id`` for every Review submission, so the dry-run NJR and the
real-run NJR of the same intent used to hash differently and the Klein edit smoke refused to run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

import tools.acceptance.img_116_klein_acceptance as driver
from tools.acceptance.img_forge_100_acceptance import intent_digest


def _review_njr(source: Path, out: Path, instruction: str | None = None):
    original = driver.EDIT_INSTRUCTION
    try:
        if instruction is not None:
            driver.EDIT_INSTRUCTION = instruction
        capture = driver._CapturingService()
        with driver.forge_selected_in_memory():
            (njr,) = driver.run_review_handler(source, capture, out)
        return njr
    finally:
        driver.EDIT_INSTRUCTION = original


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "a768.png"
    Image.new("RGB", (768, 1024), (80, 110, 70)).save(path)
    return path


def test_two_review_compilations_differ_in_batch_identity_but_not_in_intent(source: Path, tmp_path: Path) -> None:
    first = _review_njr(source, tmp_path / "out")
    second = _review_njr(source, tmp_path / "out")
    assert json.dumps(first.to_dict(), sort_keys=True, default=str) != json.dumps(
        second.to_dict(), sort_keys=True, default=str
    ), "premise: the Review builder mints a new batch id per submission"
    assert intent_digest(first) == intent_digest(second)


def test_digest_still_changes_when_the_execution_intent_changes(source: Path, tmp_path: Path) -> None:
    baseline = _review_njr(source, tmp_path / "out")
    edited = _review_njr(source, tmp_path / "out", instruction=driver.EDIT_INSTRUCTION + " Also add rain.")
    assert intent_digest(baseline) != intent_digest(edited)


def test_digest_does_not_alter_the_record_it_summarizes(source: Path, tmp_path: Path) -> None:
    njr = _review_njr(source, tmp_path / "out")
    before = json.dumps(njr.to_dict(), sort_keys=True, default=str)
    intent_digest(njr)
    assert json.dumps(njr.to_dict(), sort_keys=True, default=str) == before
