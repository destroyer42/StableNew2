"""PR-GUI-UX-560: the authoritative Preview shows each job's compiled Matrix values and frozen selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.gui.preview_panel_v2 import PreviewPanelV2
from src.pipeline.job_models_v2 import UnifiedJobSummary
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.pipeline.test_prompt_pack_matrix_560 import _compile, _matrix


def _label(panel: PreviewPanelV2) -> str:
    return str(panel.randomizer_label.cget("text"))


@pytest.fixture
def panel():
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk unavailable")
    widget = PreviewPanelV2(root)
    yield widget
    widget.destroy()


def test_the_preview_shows_the_selected_values_and_the_frozen_selection(
    panel: PreviewPanelV2, tmp_path: Path
) -> None:
    records = _compile(tmp_path, _matrix(limit=4, mode="random", sample_seed=12))
    panel.set_jobs(records)
    shown = _label(panel)

    # Whichever job the panel is showing, its label and its values belong to the same frozen record.
    matches = [
        record
        for record in records
        if shown == f"{record.matrix_expansion_label()}: {record.matrix_slot_values_preview()}"
    ]
    assert len(matches) == 1
    assert "(24 possible, sample seed 12)" in shown
    for name, value in dict(matches[0].matrix_slot_values).items():
        assert f"{name}={value}" in shown


def test_an_unseeded_random_job_says_so(panel: PreviewPanelV2, tmp_path: Path) -> None:
    records = _compile(tmp_path, _matrix(limit=3, mode="random"))
    panel.set_jobs(records)

    assert "no sample seed" in _label(panel)


def test_format_helper_reads_the_summary_field_that_exists(tmp_path: Path) -> None:
    [record, *_] = _compile(tmp_path, _matrix(limit=2, mode="fanout"))
    summary = UnifiedJobSummary.from_normalized_record(record)

    assert PreviewPanelV2._format_matrix_slots(summary) == summary.matrix_slot_values_preview != ""  # noqa: SLF001
    assert PreviewPanelV2._format_matrix_slots(None) == ""  # noqa: SLF001
