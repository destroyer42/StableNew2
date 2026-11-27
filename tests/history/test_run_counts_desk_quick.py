"""DESK-QUICK: one bounded pass counts completed txt2img jobs per checkpoint."""

from __future__ import annotations

import json

from src.history.observed_execution import read_run_counts


def _job(model: str, stage: str = "txt2img") -> str:
    return json.dumps({"normalized_job": {"stages": [{"stage_type": stage, "model": model}]}})


def test_counts_completed_txt2img_jobs_per_canonical_checkpoint_in_one_pass() -> None:
    pages = {
        None: ((_job("sdxl\\A.safetensors [aa]"), _job("b.ckpt"), "not json"), 5, False),
        5: ((_job("a"), _job("c", "upscale")), 0, True),
    }
    needles: list[str] = []

    def reader(needle, before, window):  # type: ignore[no-untyped-def]
        needles.append(needle)
        return pages[before]

    assert read_run_counts(reader) == {"a": 2, "b": 1}
    assert needles == ["", ""]


def test_it_stops_at_the_row_bound_and_when_cancelled() -> None:
    calls: list[int] = []

    def reader(needle, before, window):  # type: ignore[no-untyped-def]
        calls.append(window)
        return (_job("a"),), 100, False

    assert read_run_counts(reader, max_rows=30, window=10) == {"a": 3}
    calls.clear()
    assert read_run_counts(reader, cancelled=lambda: True) == {}
    assert calls == []
